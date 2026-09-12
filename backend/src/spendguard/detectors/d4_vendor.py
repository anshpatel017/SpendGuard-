"""D4 - vendor red flags (policy SG-PP-5.5).

Patterns that mark a supplier's *whole billing history* as worth examining,
rather than any single transaction: invoice amounts concentrated on round
figures, a first-digit distribution unlike naturally occurring values, and
billing clustered at month and financial-year end.

Each indicator is a **statistical test against the population's own behaviour**,
not a hand-set cut-off. "40% round numbers" means nothing on its own; "this
supplier bills round figures far more often than the 6% of suppliers around it"
is a measurable claim. The independent p-values are combined per supplier with
**Fisher's method**, and significance across every supplier tested is controlled
with **Benjamini-Hochberg FDR** rather than testing each at 5% — with ~380
suppliers, a naive 5% test would produce about 19 false accusations by chance.

Four guards keep the tests honest. Each was added because its absence produced
false accusations against real suppliers on the development seed:

* **Tests run on distinct amounts, not transactions.** A fixed monthly contract
  is one price decision repeated twelve times, not twelve independent
  observations. Counting each invoice would make every legitimate security or
  housekeeping contract look overwhelmingly "round".
* **Expectations are conditional on what the supplier sells.** A consultancy
  quoting round figures is normal *for a consultancy*. The expected rate for a
  supplier is the average of its own categories' rates - indirect
  standardization - not one global number. Without this, every training and
  advisory firm was flagged.
* **Significance is not enough; the effect must be material.** With 400+
  invoices, a three-point deviation is highly significant and means nothing. A
  supplier must also exceed twice its expected rate.
* **The first-digit test compares suppliers to their peers, not to Benford's
  law.** Benford describes values spanning orders of magnitude. Procurement
  invoices are quantity times a near-fixed price, so honest suppliers depart
  from Benford routinely: testing against the law directly accused 61 of 210
  real suppliers on the development seed. The null used here is the empirical
  digit distribution of the same categories, with conformity to Benford still
  reported alongside as context for the auditor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar, cast

import duckdb
import numpy as np
import polars as pl

from spendguard.cases import AnomalyType, Case
from spendguard.config import settings
from spendguard.detectors.base import AUDIT_VIEW

POLICY_CLAUSES = ("SG-PP-5.5", "SG-PP-7.1")

# P(first digit = d) under Benford's law.
BENFORD = tuple(math.log10(1 + 1 / d) for d in range(1, 10))

# Benford needs values spanning orders of magnitude; below this the test is skipped.
MIN_MAGNITUDE_SPAN = 30.0  # max / min amount

# A supplier must exceed twice the rate expected for what it sells. Statistical
# significance alone flags large suppliers over trivial deviations.
MIN_RISK_RATIO = 2.0

# Nigrini's mean-absolute-deviation criterion for first-digit conformity:
# above 0.015 is "nonconformity", below is acceptable. Used so a chi-square that
# is significant only because the supplier has many invoices does not count.
MIN_BENFORD_MAD = 0.015


@dataclass(frozen=True)
class VendorTest:
    name: str
    p_value: float
    detail: dict[str, Any]


def first_digits(amounts: np.ndarray) -> np.ndarray:
    """Leading significant digit of each amount, 1-9."""
    positive = amounts[amounts > 0]
    scaled = positive / np.power(10.0, np.floor(np.log10(positive)))
    return np.floor(scaled).astype(int)


def digit_share(amounts: np.ndarray) -> np.ndarray:
    """Share of each leading digit 1-9."""
    counts = np.bincount(first_digits(amounts), minlength=10)[1:10].astype(float)
    total = counts.sum()
    return counts / total if total else counts


def first_digit_test(amounts: np.ndarray, peer_share: np.ndarray) -> VendorTest | None:
    """Chi-square of leading digits against how peer suppliers in the same categories bill.

    ``peer_share`` is the empirical digit distribution of the supplier's own
    categories. Benford conformity is computed too, but only reported - it is
    not the null, because procurement invoices do not follow Benford.
    """
    from scipy import stats

    if len(amounts) < settings.benford_min_transactions:
        return None
    if float(amounts.max() / amounts.min()) < MIN_MAGNITUDE_SPAN:
        return None  # too narrow a range for a digit distribution to mean anything

    observed_share = digit_share(amounts)
    total = float(len(amounts))
    expected = np.where(peer_share > 0, peer_share, 1e-6) * total
    statistic = float(((observed_share * total - expected) ** 2 / expected).sum())
    mad = float(np.abs(observed_share - peer_share).mean())
    if mad < MIN_BENFORD_MAD:
        return None  # bills like its peers
    return VendorTest(
        "first_digit",
        float(stats.chi2.sf(statistic, df=8)),
        {
            "null": "empirical digit distribution of the same categories",
            "chi_square": round(statistic, 2),
            "mean_absolute_deviation_vs_peers": round(mad, 4),
            "mean_absolute_deviation_vs_benford": round(
                float(np.abs(observed_share - np.array(BENFORD)).mean()), 4
            ),
            "distinct_amounts": int(len(amounts)),
            "observed_share": [round(x, 3) for x in observed_share],
            "peer_share": [round(x, 3) for x in peer_share],
        },
    )


def proportion_test(
    name: str, successes: int, trials: int, expected_rate: float, detail: dict[str, Any]
) -> VendorTest | None:
    """One-sided binomial test against the rate expected for what this supplier sells.

    ``expected_rate`` is the average of the population rates of the supplier's own
    categories. The exact null is Poisson-binomial; a binomial at the mean rate is
    the standard approximation and is close when the rates are similar.

    Returns None unless the excess is also **material** - at least twice the
    expected rate - so a large supplier cannot be flagged for a trivial deviation.
    """
    from scipy import stats

    if trials < settings.vendor_min_transactions or not 0 < expected_rate < 1:
        return None
    observed_rate = successes / trials
    if observed_rate < MIN_RISK_RATIO * expected_rate:
        return None
    p = float(stats.binomtest(successes, trials, expected_rate, alternative="greater").pvalue)
    return VendorTest(
        name,
        p,
        {
            **detail,
            "observed_rate": round(observed_rate, 3),
            "expected_rate": round(expected_rate, 4),
            "risk_ratio": round(observed_rate / expected_rate, 2),
            "observations": trials,
        },
    )


def fisher_combine(tests: list[VendorTest]) -> float:
    """Fisher's method: combine independent p-values into one."""
    from scipy import stats

    statistic = -2.0 * sum(math.log(max(t.p_value, 1e-300)) for t in tests)
    return float(stats.chi2.sf(statistic, df=2 * len(tests)))


def benjamini_hochberg(p_values: list[float], alpha: float) -> float:
    """Largest p-value that keeps the false discovery rate at or below alpha.

    Returns 0.0 when nothing is significant, so no supplier is flagged.
    """
    if not p_values:
        return 0.0
    ordered = sorted(p_values)
    cutoff = 0.0
    for rank, p in enumerate(ordered, start=1):
        if p <= alpha * rank / len(ordered):
            cutoff = p
    return cutoff


def _is_period_end(day: date) -> bool:
    """Last four days of a month, or anywhere in March (financial year end)."""
    import calendar

    return day.month == 3 or day.day > calendar.monthrange(day.year, day.month)[1] - 4


class VendorFlagDetector:
    name: ClassVar[str] = "d4"
    anomaly_types: ClassVar[tuple[AnomalyType, ...]] = (AnomalyType.VENDOR_FLAG,)

    def __init__(self, alpha: float | None = None) -> None:
        self.alpha = settings.vendor_fdr_alpha if alpha is None else alpha
        self.vendors_tested = 0
        self.fdr_cutoff = 0.0

    def _load(self, con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
        return con.execute(
            f"""
            SELECT row_id, vendor_key, vendor_name, amount, txn_date, officer_id,
                   coalesce(item_category, '(uncategorised)') AS item_category
            FROM {AUDIT_VIEW}
            WHERE amount > 0
            ORDER BY vendor_key, row_id
            """
        ).pl()

    def assess(self, con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
        """Per-supplier test results and combined p-value. Exposed for analysis."""
        frame = self._load(con)
        if frame.is_empty():
            return []

        unit = settings.round_number_unit
        frame = frame.with_columns(
            (pl.col("amount") % unit == 0).alias("is_round"),
            pl.col("txn_date")
            .map_elements(_is_period_end, return_dtype=pl.Boolean)
            .alias("is_period_end"),
        )

        # Population baselines, measured from the data rather than assumed, and
        # held per category: round pricing is normal in some trades and not others.
        distinct = frame.unique(subset=["vendor_key", "amount"])
        round_by_category = dict(
            distinct.group_by("item_category").agg(pl.col("is_round").mean()).iter_rows()
        )
        period_end_by_category = dict(
            frame.group_by("item_category").agg(pl.col("is_period_end").mean()).iter_rows()
        )
        overall_round = float(cast(float, distinct["is_round"].mean() or 0.0))
        overall_period_end = float(cast(float, frame["is_period_end"].mean() or 0.0))
        first_seen = cast(date, frame["txn_date"].min())

        def expected(rows: pl.DataFrame, rates: dict[str, float], fallback: float) -> float:
            """Rate expected for this supplier, given the mix of what it sells."""
            values = [rates.get(c, fallback) or fallback for c in rows["item_category"]]
            return float(sum(values) / len(values)) if values else fallback

        # Peer digit distribution per category, over distinct amounts.
        digits_by_category = {
            str(category): digit_share(part["amount"].to_numpy())
            for (category,), part in distinct.group_by(["item_category"])
        }
        overall_digits = digit_share(distinct["amount"].to_numpy())

        def expected_digits(rows: pl.DataFrame) -> np.ndarray:
            shares = [digits_by_category.get(c, overall_digits) for c in rows["item_category"]]
            return np.mean(shares, axis=0) if shares else overall_digits

        results: list[dict[str, Any]] = []
        for (vendor_key,), rows in frame.group_by(["vendor_key"], maintain_order=True):
            amounts = rows.unique(subset=["amount"]).sort("amount")
            values = amounts["amount"].to_numpy()

            tests: list[VendorTest] = []
            if len(values) >= settings.vendor_min_distinct_amounts:
                if (t := first_digit_test(values, expected_digits(amounts))) is not None:
                    tests.append(t)
                if (
                    t := proportion_test(
                        "round_numbers",
                        int(amounts["is_round"].sum()),
                        len(values),
                        expected(amounts, round_by_category, overall_round),
                        {"unit": unit},
                    )
                ) is not None:
                    tests.append(t)
            if (
                t := proportion_test(
                    "period_end",
                    int(rows["is_period_end"].sum()),
                    rows.height,
                    expected(rows, period_end_by_category, overall_period_end),
                    {"definition": "last four days of a month, or March"},
                )
            ) is not None:
                tests.append(t)
            if not tests:
                continue

            onboarded = cast(date, rows["txn_date"].min())
            largest = float(cast(float, rows["amount"].max()))
            results.append(
                {
                    "vendor_key": str(vendor_key),
                    "vendor_name": rows["vendor_name"][0],
                    "row_ids": rows["row_id"].to_list(),
                    "transactions": rows.height,
                    "distinct_amounts": len(values),
                    "total_amount": float(rows["amount"].sum()),
                    "largest_amount": largest,
                    "officers": sorted({o for o in rows["officer_id"].to_list() if o}),
                    "combined_p": fisher_combine(tests),
                    "tests": tests,
                    # Policy SG-PP-5.3, recorded as context: a supplier first seen
                    # partway through the period, already taking large orders.
                    "new_vendor_high_value": bool(
                        (onboarded - first_seen).days > settings.new_vendor_days
                        and largest >= settings.approval_threshold
                    ),
                    "first_seen": onboarded.isoformat(),
                }
            )
        self.vendors_tested = len(results)
        return results

    def detect(self, con: duckdb.DuckDBPyConnection) -> list[Case]:
        assessed = self.assess(con)
        if not assessed:
            return []
        self.fdr_cutoff = benjamini_hochberg([r["combined_p"] for r in assessed], self.alpha)

        cases: list[Case] = []
        for r in sorted(assessed, key=lambda x: x["vendor_key"]):
            if r["combined_p"] > self.fdr_cutoff:
                continue
            # -log10(p) mapped into 0-1: monotone in the strength of the evidence.
            score = min(1.0, -math.log10(max(r["combined_p"], 1e-300)) / 20.0)
            cases.append(
                Case.build(
                    detector=self.name,
                    anomaly_type=AnomalyType.VENDOR_FLAG,
                    row_ids=r["row_ids"],
                    detector_score=round(score, 4),
                    amount_at_risk=r["total_amount"],
                    vendor_key=r["vendor_key"],
                    metadata={
                        "policy_clauses": list(POLICY_CLAUSES),
                        "vendor_name": r["vendor_name"],
                        "transactions": r["transactions"],
                        "distinct_amounts": r["distinct_amounts"],
                        "combined_p_value": f"{r['combined_p']:.3g}",
                        "fdr_cutoff": f"{self.fdr_cutoff:.3g}",
                        "vendors_tested": self.vendors_tested,
                        "first_seen": r["first_seen"],
                        "officers": r["officers"],
                        "new_vendor_high_value": r["new_vendor_high_value"],
                        "indicators": {
                            t.name: {"p_value": f"{t.p_value:.3g}", **t.detail} for t in r["tests"]
                        },
                    },
                )
            )
        return cases
