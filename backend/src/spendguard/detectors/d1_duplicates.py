"""D1 - duplicate transaction records (decisions D-01, D-12, D-19, D-20).

"Duplicate transaction records (POs or payments, depending on the source
system)" - the same obligation appearing twice in the data.

Stage 1, exact
    Same vendor key, same amount, same invoice number, at any distance in time.
    Certain: detector_score 1.0.

Stage 2, probabilistic
    1. Block: every pair of transactions within ±0.5% in amount and 14 days in
       date (policy SG-PP-4.4). Blocking on amount rather than vendor key means a
       typo in the supplier's name cannot hide a duplicate (D-19).
    2. Confirm identity: keep pairs whose supplier names score at least 80 on
       ``name_similarity``. Two different firms that share a stem - "Kaveri
       Traders" and "Kaveri Enterprises" - stop here (D-12).
    3. Compare field by field and score with a Fellegi-Sunter model fitted by EM
       (D-20). The posterior probability is the detector_score.

Pairs at or above the match threshold are joined transitively, so a record
entered three times becomes one case of three rows, not three pairwise cases.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar

import duckdb
import numpy as np
import polars as pl

from spendguard.cases import AnomalyType, Case
from spendguard.config import settings
from spendguard.detectors.base import AUDIT_VIEW
from spendguard.pipeline.vendors import name_similarity

POLICY_CLAUSE = "SG-PP-4.4"


# ---------------------------------------------------------------- comparisons


def invoice_core_numbers(invoice: str | None, when: date) -> frozenset[int]:
    """The numbers in an invoice reference that identify *the invoice*.

    Year and financial-year parts are dropped - every invoice in a year shares
    them, so they say nothing. 'INV-04471' -> {4471}; '4471/2026' -> {4471};
    'ST/24-25/045' dated Jan 2025 -> {45}.
    """
    if not invoice:
        return frozenset()
    y = when.year
    calendar_parts = {y - 1, y, y + 1, (y - 1) % 100, y % 100, (y + 1) % 100}
    return frozenset(
        n for n in (int(g) for g in re.findall(r"\d+", invoice)) if n not in calendar_parts
    )


@dataclass(frozen=True)
class Comparison:
    """One field compared across a pair, discretized into levels.

    Level 0 is always the strongest agreement. ``m_init`` is where EM starts
    for P(level | duplicate); EM moves it to wherever the data puts it.
    """

    name: str
    levels: tuple[str, ...]
    m_init: tuple[float, ...]


# Officer, item and exact amount are compared *jointly* as one "context" field.
# Among innocent look-alikes they agree together - the same officer re-ordering
# the same item from the same supplier - so treating them as independent, as
# Fellegi-Sunter assumes, counts one fact three times and drowns out the invoice
# evidence that actually separates a duplicate from repeat business (D-20).
COMPARISONS: tuple[Comparison, ...] = (
    Comparison("name", ("≥95", "88-95", "80-88"), (0.70, 0.20, 0.10)),
    Comparison("invoice", ("identical", "same core number", "different", "missing"),
               (0.45, 0.45, 0.05, 0.05)),
    Comparison("context", ("same officer, item, quantity and amount",
                           "same officer and item, amount within 0.5%",
                           "officer or item differs",
                           "officer and item both differ"),
               (0.85, 0.08, 0.05, 0.02)),
    Comparison("date_gap", ("0-3 days", "4-7 days", "8-14 days"), (0.40, 0.35, 0.25)),
)  # fmt: skip


def compare(a: dict[str, Any], b: dict[str, Any], similarity: float) -> tuple[int, ...]:
    """Comparison vector for a pair: one level index per entry in COMPARISONS."""
    name = 0 if similarity >= 95 else 1 if similarity >= 88 else 2

    if a["invoice_no"] is None or b["invoice_no"] is None:
        invoice = 3
    elif a["invoice_no"].strip().lower() == b["invoice_no"].strip().lower():
        invoice = 0
    else:
        shared = invoice_core_numbers(a["invoice_no"], a["txn_date"]) & invoice_core_numbers(
            b["invoice_no"], b["txn_date"]
        )
        invoice = 1 if shared else 2

    same_officer = a["officer_id"] is not None and a["officer_id"] == b["officer_id"]
    same_item = (
        a["item_category"] is not None
        and a["item_category"] == b["item_category"]
        and a["quantity"] == b["quantity"]
    )
    if same_officer and same_item:
        context = 0 if a["amount"] == b["amount"] else 1
    else:
        context = 2 if (same_officer or same_item) else 3

    gap = abs((a["txn_date"] - b["txn_date"]).days)
    date_gap = 0 if gap <= 3 else 1 if gap <= 7 else 2

    return (name, invoice, context, date_gap)


# ---------------------------------------------------------------- Fellegi-Sunter


@dataclass
class FellegiSunter:
    """Two-class mixture over comparison vectors, fitted by EM.

    Classes are "duplicate" (M) and "not a duplicate" (U). Fields are assumed
    conditionally independent given the class - the standard Fellegi-Sunter
    assumption, and the one Splink makes.
    """

    comparisons: tuple[Comparison, ...] = COMPARISONS
    prior: float = 0.1  # P(M) among identity-confirmed candidates, before fitting
    m: list[np.ndarray] = field(default_factory=list)
    u: list[np.ndarray] = field(default_factory=list)
    iterations: int = 0
    converged: bool = False

    SMOOTHING: ClassVar[float] = 1e-3
    # MAP-EM priors. Plain maximum-likelihood EM always finds two classes, even
    # when one does not exist: on clean data with no duplicates it put 94.5% of
    # pairs in the "duplicate" class and decided a different invoice number was
    # normal for one. Real data has few duplicates, which is exactly that regime.
    # So m_init is a Dirichlet prior worth M_PRIOR_STRENGTH pairs, and the
    # duplicate rate gets a Beta prior centred on 5%. Plenty of real duplicates
    # overrule both; none leaves the model sensible instead of inventing a class.
    M_PRIOR_STRENGTH: ClassVar[float] = 50.0
    RATE_PRIOR: ClassVar[tuple[float, float]] = (2.0, 38.0)  # Beta(a, b): mean 0.05

    def _init(self, x: np.ndarray) -> None:
        self.m = [np.array(c.m_init, dtype=float) for c in self.comparisons]
        # u starts at the observed level frequencies: most candidates are not duplicates.
        self.u = [
            self._normalize(np.bincount(x[:, j], minlength=len(c.levels)).astype(float))
            for j, c in enumerate(self.comparisons)
        ]

    def _normalize(self, counts: np.ndarray) -> np.ndarray:
        counts = counts + self.SMOOTHING
        return counts / counts.sum()

    def _log_likelihoods(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        log_m = sum(np.log(self.m[j][x[:, j]]) for j in range(len(self.comparisons)))
        log_u = sum(np.log(self.u[j][x[:, j]]) for j in range(len(self.comparisons)))
        return np.asarray(log_m, dtype=float), np.asarray(log_u, dtype=float)

    def posterior(self, x: np.ndarray) -> np.ndarray:
        log_m, log_u = self._log_likelihoods(x)
        log_odds = math.log(self.prior / (1 - self.prior)) + log_m - log_u
        return np.asarray(1.0 / (1.0 + np.exp(-np.clip(log_odds, -50, 50))), dtype=float)

    def fit(
        self,
        x: np.ndarray,
        max_iterations: int,
        u_fixed: list[np.ndarray] | None = None,
        tolerance: float = 1e-6,
    ) -> FellegiSunter:
        """Fit by EM. With ``u_fixed``, only m and the prior are learned.

        Fixing u matters. Left free, EM finds the *largest* cluster of look-alike
        pairs - a supplier repeatedly selling one officer the same item - and
        calls that the match class, deciding invoice numbers barely matter.
        Pinning u to how innocent look-alikes behave forces EM to learn what is
        different about true duplicates instead.
        """
        self._init(x)
        if u_fixed is not None:
            self.u = [np.asarray(u, dtype=float) for u in u_fixed]
        # Too few pairs to learn from: keep the starting model rather than overfit noise.
        if len(x) < 20:
            return self
        a, b = self.RATE_PRIOR
        for self.iterations in range(1, max_iterations + 1):
            w = self.posterior(x)
            new_prior = float(np.clip((w.sum() + a) / (len(w) + a + b), 1e-4, 1 - 1e-4))
            new_m, new_u = [], []
            for j, c in enumerate(self.comparisons):
                levels = np.arange(len(c.levels))[:, None] == x[:, j][None, :]
                pseudo = self.M_PRIOR_STRENGTH * np.array(c.m_init, dtype=float)
                new_m.append(self._normalize((levels * w).sum(axis=1) + pseudo))
                new_u.append(self._normalize((levels * (1 - w)).sum(axis=1)))
            if u_fixed is not None:
                new_u = self.u
            change = abs(new_prior - self.prior) + max(
                float(np.abs(a - b).max())
                for a, b in zip(new_m + new_u, self.m + self.u, strict=True)
            )
            self.prior, self.m, self.u = new_prior, new_m, new_u
            if change < tolerance:
                self.converged = True
                break
        return self

    def match_weights(self, vector: tuple[int, ...]) -> dict[str, float]:
        """log2(m/u) per field: positive is evidence for a duplicate, negative against."""
        return {
            c.name: round(math.log2(self.m[j][level] / self.u[j][level]), 2)
            for j, (c, level) in enumerate(zip(self.comparisons, vector, strict=True))
        }

    def describe(self) -> dict[str, Any]:
        return {
            "prior": round(self.prior, 4),
            "iterations": self.iterations,
            "converged": self.converged,
            "fields": {
                c.name: {
                    level: {"m": round(float(self.m[j][i]), 4), "u": round(float(self.u[j][i]), 4)}
                    for i, level in enumerate(c.levels)
                }
                for j, c in enumerate(self.comparisons)
            },
        }


# ---------------------------------------------------------------- union-find


class _Groups:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)

    def components(self) -> list[list[int]]:
        """Groups ordered by their smallest row id, so output never depends on insertion order."""
        out: dict[int, list[int]] = defaultdict(list)
        for x in self.parent:
            out[self.find(x)].append(x)
        return sorted((sorted(v) for v in out.values()), key=lambda g: g[0])


# ---------------------------------------------------------------- detector

_FIELDS = "row_id, vendor_name, vendor_key, invoice_no, amount, txn_date, officer_id, item_category, quantity"


class DuplicateDetector:
    name: ClassVar[str] = "d1"
    anomaly_types: ClassVar[tuple[AnomalyType, ...]] = (AnomalyType.DUPLICATE,)

    def __init__(self) -> None:
        self.model = FellegiSunter()
        self.candidates_blocked = 0
        self.candidates_confirmed = 0
        self.reference_pairs = 0

    # ------------------------------------------------------------ stage 1

    def _exact_pairs(self, con: duckdb.DuckDBPyConnection) -> list[tuple[int, int]]:
        rows = con.execute(
            f"""
            SELECT list(row_id ORDER BY row_id)
            FROM {AUDIT_VIEW}
            WHERE invoice_no IS NOT NULL
            GROUP BY vendor_key, amount, lower(trim(invoice_no))
            HAVING count(*) > 1
            ORDER BY min(row_id)
            """
        ).fetchall()
        return [(ids[0], other) for (ids,) in rows for other in ids[1:]]

    # ------------------------------------------------------------ stage 2

    def _blocked_pairs(self, con: duckdb.DuckDBPyConnection) -> list[tuple[int, int]]:
        """Pairs within the amount tolerance and date window (D-19).

        Amounts qualify when they differ by *less than* the tolerance, measured
        against the larger of the two - the policy's wording (SG-PP-4.4), and
        symmetric, so a pair never depends on which row comes first.

        An equi-join on a log-amount bucket of width -ln(1 - tolerance), against
        the bucket and both neighbours, then the exact filter. Any qualifying
        pair has a log-ratio below one bucket width, so it lands in the same or
        an adjacent bucket: identical to the naive range join, ~300x faster.
        """
        tol = settings.duplicate_amount_tolerance
        window = settings.duplicate_date_window_days
        rows = con.execute(
            f"""
            WITH k AS (
                SELECT row_id, amount, txn_date,
                       floor(ln(amount) / -ln(1 - {tol}))::BIGINT AS bucket
                FROM {AUDIT_VIEW}
                WHERE amount > 0
            ),
            shifted AS (
                SELECT k.*, bucket + s AS join_bucket FROM k, (VALUES (-1), (0), (1)) t(s)
            )
            SELECT a.row_id, b.row_id
            FROM k a JOIN shifted b ON b.join_bucket = a.bucket
            WHERE a.row_id < b.row_id
              AND abs(a.amount - b.amount) < {tol} * greatest(a.amount, b.amount)
              AND abs(date_diff('day', a.txn_date, b.txn_date)) <= {window}
            ORDER BY a.row_id, b.row_id
            """
        ).fetchall()
        return [(int(a), int(b)) for a, b in rows]

    def _reference_pairs(self, con: duckdb.DuckDBPyConnection) -> list[tuple[int, int]]:
        """Look-alike pairs too far apart in time to be duplicates.

        Selected exactly as candidates are - same amount band, then the same
        name-similarity check - but 30-180 days apart instead of within 14, so
        by the policy's own definition none is a duplicate. How often *these*
        agree on each field is how often innocent look-alikes do: the
        u-probabilities (decision D-20).

        It must mirror candidate selection exactly. An earlier version also
        required the same vendor key, which excluded the similar-but-different
        supplier names common among real candidates; EM then built a spurious
        "duplicate" class out of exactly those pairs.
        """
        tol = settings.duplicate_amount_tolerance
        near = 2 * settings.duplicate_date_window_days + 2
        rows = con.execute(
            f"""
            WITH k AS (
                SELECT row_id, amount, txn_date,
                       floor(ln(amount) / -ln(1 - {tol}))::BIGINT AS bucket
                FROM {AUDIT_VIEW}
                WHERE amount > 0
            ),
            shifted AS (
                SELECT k.*, bucket + s AS join_bucket FROM k, (VALUES (-1), (0), (1)) t(s)
            )
            SELECT a.row_id, b.row_id
            FROM k a JOIN shifted b ON b.join_bucket = a.bucket
            WHERE a.row_id < b.row_id
              AND abs(a.amount - b.amount) < {tol} * greatest(a.amount, b.amount)
              AND abs(date_diff('day', a.txn_date, b.txn_date)) BETWEEN {near} AND 180
            ORDER BY a.row_id, b.row_id
            """
        ).fetchall()
        return [(int(a), int(b)) for a, b in rows]

    def detect(self, con: duckdb.DuckDBPyConnection) -> list[Case]:
        exact = self._exact_pairs(con)
        blocked = self._blocked_pairs(con)
        reference = self._reference_pairs(con)
        self.candidates_blocked = len(blocked)

        ids = sorted({r for pair in exact + blocked + reference for r in pair})
        if not ids:
            return []
        rows = {
            r["row_id"]: r
            for r in con.execute(
                f"SELECT {_FIELDS} FROM {AUDIT_VIEW} WHERE row_id IN (SELECT unnest(?))", [ids]
            )
            .pl()
            .iter_rows(named=True)
        }

        # Identity confirmation (D-12). Names repeat heavily, so cache by pair of names.
        similarity_cache: dict[tuple[str, str], float] = {}

        def similarity(a: str, b: str) -> float:
            key = (a, b) if a <= b else (b, a)
            if key not in similarity_cache:
                similarity_cache[key] = name_similarity(*key)
            return similarity_cache[key]

        confirmed: list[tuple[int, int, float]] = []
        for a, b in blocked:
            s = similarity(rows[a]["vendor_name"], rows[b]["vendor_name"])
            if s >= settings.duplicate_name_confirm:
                confirmed.append((a, b, s))
        self.candidates_confirmed = len(confirmed)

        vectors = np.array(
            [compare(rows[a], rows[b], s) for a, b, s in confirmed], dtype=np.int64
        ).reshape(-1, len(COMPARISONS))

        reference_vectors = np.array(
            [
                compare(rows[a], rows[b], s)
                for a, b in reference
                if (s := similarity(rows[a]["vendor_name"], rows[b]["vendor_name"]))
                >= settings.duplicate_name_confirm
            ],
            dtype=np.int64,
        ).reshape(-1, len(COMPARISONS))
        self.reference_pairs = len(reference_vectors)
        self.model = FellegiSunter().fit(
            vectors,
            settings.duplicate_em_max_iterations,
            u_fixed=self._u_from_reference(reference_vectors, vectors),
        )
        probabilities = self.model.posterior(vectors) if len(vectors) else np.array([])

        # Group everything at or above the threshold, transitively.
        groups = _Groups()
        evidence: dict[tuple[int, int], dict[str, Any]] = {}
        for a, b in exact:
            groups.union(a, b)
            evidence[(a, b)] = {"stage": "exact", "probability": 1.0}
        for (a, b, s), p, vector in zip(confirmed, probabilities, vectors, strict=True):
            if p < settings.duplicate_match_threshold:
                continue
            groups.union(a, b)
            if (a, b) not in evidence:
                evidence[(a, b)] = {
                    "stage": "probabilistic",
                    "probability": round(float(p), 4),
                    "name_similarity": round(s, 1),
                    "levels": {
                        c.name: c.levels[int(v)] for c, v in zip(COMPARISONS, vector, strict=True)
                    },
                    "match_weights": self.model.match_weights(tuple(int(v) for v in vector)),
                }

        return [self._case(members, rows, evidence) for members in groups.components()]

    MIN_REFERENCE_PAIRS: ClassVar[int] = 50

    def _u_from_reference(
        self, reference: np.ndarray, candidates: np.ndarray
    ) -> list[np.ndarray] | None:
        """u per field from the far-apart look-alikes.

        The date gap is the one field they cannot inform - they are far apart by
        construction - so its u comes from the candidates, where non-duplicates
        dominate and gaps spread across the window. Too few reference pairs (a
        small dataset) and u is left to EM rather than estimated from noise.
        """
        if len(reference) < self.MIN_REFERENCE_PAIRS or len(candidates) == 0:
            return None
        u: list[np.ndarray] = []
        for j, c in enumerate(COMPARISONS):
            source = candidates if c.name == "date_gap" else reference
            counts = np.bincount(source[:, j], minlength=len(c.levels)).astype(float)
            counts += FellegiSunter.SMOOTHING * len(source)
            u.append(counts / counts.sum())
        return u

    def _case(
        self,
        members: list[int],
        rows: dict[int, dict[str, Any]],
        evidence: dict[tuple[int, int], dict[str, Any]],
    ) -> Case:
        pairs = {k: v for k, v in evidence.items() if k[0] in members and k[1] in members}
        score = max(float(v["probability"]) for v in pairs.values())
        ordered = sorted(members, key=lambda r: (rows[r]["txn_date"], r))
        original = rows[ordered[0]]
        return Case.build(
            detector=self.name,
            anomaly_type=AnomalyType.DUPLICATE,
            row_ids=members,
            detector_score=score,
            # Everything after the first record is the repeat.
            amount_at_risk=sum(float(rows[r]["amount"]) for r in ordered[1:]),
            vendor_key=original["vendor_key"],
            metadata={
                "policy_clause": POLICY_CLAUSE,
                "original_row_id": ordered[0],
                "stages": sorted({str(v["stage"]) for v in pairs.values()}),
                "pairs": [{"row_ids": list(k), **v} for k, v in sorted(pairs.items())],
            },
        )


def model_frame(detector: DuplicateDetector) -> pl.DataFrame:
    """The fitted m and u probabilities as a table - for reports and the viva."""
    rows = [
        {"field": c.name, "level": level, "m": float(detector.model.m[j][i]), "u": float(detector.model.u[j][i])}
        for j, c in enumerate(COMPARISONS)
        for i, level in enumerate(c.levels)
    ]  # fmt: skip
    return pl.DataFrame(rows).with_columns(
        (pl.col("m") / pl.col("u")).log(base=2).round(2).alias("match_weight")
    )
