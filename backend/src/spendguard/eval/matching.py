"""Matching detected cases to injected ground truth (decision D-03).

Row-group anomalies (duplicate, split, inflation)
    A case matches a ground-truth group when it contains at least one of the
    group's rows **and** no more than half of the case's rows are spurious.
    Exactly 50% spurious is still a match.

Vendor-level anomalies (vendor_flag)
    A vendor case contains *all* of a supplier's rows, so row overlap is the
    wrong test. A case matches when its ``vendor_key`` is the injected vendor's.

Matching is one-to-one and score-ordered. Cases are visited from highest
``detector_score`` down (ties broken by ``case_id``), and each takes the best
still-unclaimed group - most overlap, then least spurious. A second case landing
on an already-claimed group is a false positive: an auditor handed five alerts
for one split scheme has four redundant alerts, and the metric should say so.
This is the same convention object detection uses, and it is what makes the
ranked list consistent with average precision.

Types must agree. A duplicate case never matches a split group.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import duckdb

from spendguard.cases import AnomalyType, Case
from spendguard.db.duck import table_exists

MAX_SPURIOUS_FRACTION = 0.5
VENDOR_LEVEL_TYPES: frozenset[AnomalyType] = frozenset({AnomalyType.VENDOR_FLAG})


@dataclass(frozen=True)
class TruthGroup:
    group_id: str
    anomaly_type: AnomalyType
    row_ids: frozenset[int]
    vendor_key: str | None
    amount_at_risk: float
    params: dict[str, object] = field(default_factory=dict, compare=False, hash=False)


@dataclass
class MatchResult:
    anomaly_type: AnomalyType
    matched: dict[str, str]  # case_id -> group_id
    false_positives: list[str]  # case_ids
    false_negatives: list[str]  # group_ids
    ranked: list[tuple[float, bool]]  # (detector_score, is_true_positive), best first

    @property
    def tp(self) -> int:
        return len(self.matched)

    @property
    def fp(self) -> int:
        return len(self.false_positives)

    @property
    def fn(self) -> int:
        return len(self.false_negatives)


def load_ground_truth(con: duckdb.DuckDBPyConnection) -> list[TruthGroup]:
    if not table_exists(con, "ground_truth"):
        raise LookupError("No ground_truth table. Run `spendguard inject` to create one.")
    rows = con.execute(
        "SELECT injection_group_id, injection_type, row_ids, vendor_key, amount_at_risk, params "
        "FROM ground_truth ORDER BY injection_group_id"
    ).fetchall()
    return [
        TruthGroup(
            group_id=gid,
            anomaly_type=AnomalyType(kind),
            row_ids=frozenset(int(r) for r in ids),
            vendor_key=key,
            amount_at_risk=float(amount),
            params=json.loads(params) if params else {},
        )
        for gid, kind, ids, key, amount, params in rows
    ]


def overlap_score(case_rows: frozenset[int], group: TruthGroup) -> tuple[int, float] | None:
    """(overlap, spurious fraction) if the case qualifies for the group, else None."""
    overlap = len(case_rows & group.row_ids)
    if overlap == 0:
        return None
    spurious = (len(case_rows) - overlap) / len(case_rows)
    if spurious > MAX_SPURIOUS_FRACTION:
        return None
    return overlap, spurious


def match(
    cases: Sequence[Case], groups: Sequence[TruthGroup], anomaly_type: AnomalyType
) -> MatchResult:
    ordered = sorted(
        (c for c in cases if c.anomaly_type == anomaly_type),
        key=lambda c: (-c.detector_score, c.case_id),
    )
    unclaimed = {g.group_id: g for g in groups if g.anomaly_type == anomaly_type}

    by_vendor: dict[str | None, list[str]] = defaultdict(list)
    by_row: dict[int, list[str]] = defaultdict(list)
    for g in unclaimed.values():
        by_vendor[g.vendor_key].append(g.group_id)
        for r in g.row_ids:
            by_row[r].append(g.group_id)

    vendor_level = anomaly_type in VENDOR_LEVEL_TYPES
    matched: dict[str, str] = {}
    false_positives: list[str] = []
    ranked: list[tuple[float, bool]] = []

    for case in ordered:
        best_id: str | None = None
        if vendor_level:
            options = [gid for gid in by_vendor.get(case.vendor_key, []) if gid in unclaimed]
            best_id = min(options) if options else None
        else:
            rows = frozenset(case.row_ids)
            best_key: tuple[int, float, str] | None = None
            for gid in {gid for r in rows for gid in by_row.get(r, [])}:
                if gid not in unclaimed:
                    continue
                score = overlap_score(rows, unclaimed[gid])
                if score is None:
                    continue
                key = (-score[0], score[1], gid)
                if best_key is None or key < best_key:
                    best_key, best_id = key, gid

        if best_id is not None:
            matched[case.case_id] = best_id
            del unclaimed[best_id]
        else:
            false_positives.append(case.case_id)
        ranked.append((case.detector_score, best_id is not None))

    return MatchResult(
        anomaly_type=anomaly_type,
        matched=matched,
        false_positives=false_positives,
        false_negatives=sorted(unclaimed),
        ranked=ranked,
    )
