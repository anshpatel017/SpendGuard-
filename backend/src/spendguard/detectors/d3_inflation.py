"""D3 - price inflation (policy SG-PP-6.3).

A unit price materially above the norm for its commodity, with no recorded
reason. The hard part is that honest prices in one category legitimately span a
wide range: economy and premium specifications, urgent purchases at a premium,
bulk discounts, and year-on-year drift.

    For each commodity category with enough history, take the median of **log**
    unit price; adjust it for the two legitimate effects the ledger can measure
    - bulk discount and year-on-year drift - and flag line items whose robust
    z-score against that expectation exceeds the threshold. An Isolation Forest
    runs alongside as an independent second opinion and is recorded, never used
    to raise a case on its own.

**Measured limits, stated plainly.** No price statistic tried - ratio to median,
ratio to mean, robust z, IQR z, controlled z - beat the rule baseline's F1 by a
meaningful margin, and across three seeds D3 lands slightly *below* it:
**F1 0.419 vs 0.432**. Legitimate premium specifications and urgent purchases
occupy the same band as the injected markups - 7,508 honest rows sit above 1.4x
their category median - so no price statistic can separate them.

What D3 does add is **ranking**: PR-AUC **0.280 vs 0.196**, a 43% gain over a
rule that can only say yes or no. That is what matters when only the top-N cases
by severity are investigated. Separating the remainder needs the description and
the policy - evidence for the Investigator, not for a detector.

**Why log space.** Prices vary multiplicatively: a 1.5x markup is the same event
on a ₹300 ream and a ₹60,000 laptop. On the raw scale, expensive categories
would dominate the spread and cheap ones would look uniformly fine.

**Why median and MAD.** Both are robust: the outliers being hunted barely move
them. A mean and standard deviation are dragged upward by the very inflation the
detector is looking for, which raises the bar until it can no longer see it.

**Why the item description is ignored.** Half the legitimate premium purchases
say so in their description ("- Premium Grade", "(Urgent Supply)"). Using that
as a feature would mean trusting text written by the same party that set the
price - a fraudster need only type the word. The description is evidence for the
Investigator to weigh, not an input to the detector.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar

import duckdb
import numpy as np
import polars as pl

from spendguard.cases import AnomalyType, Case
from spendguard.config import settings
from spendguard.detectors.base import AUDIT_VIEW

POLICY_CLAUSE = "SG-PP-6.3"

# Consistency factor making MAD an estimator of the standard deviation
# for normally distributed data.
MAD_TO_SIGMA = 1.4826

# Isolation Forest inputs. Every one is a number the ledger already contains;
# none is free text.
FEATURES = ("relative_log_price", "log_quantity", "vendor_category_share", "days_elapsed")


def _robust_stats(frame: pl.DataFrame) -> pl.DataFrame:
    """Median and MAD of log unit price, per category, on categories with enough history."""
    medians = frame.group_by("item_category").agg(
        pl.col("log_price").median().alias("median_log_price"),
        pl.len().alias("category_size"),
    )
    with_median = frame.join(medians, on="item_category")
    mads = (
        with_median.with_columns(
            (pl.col("log_price") - pl.col("median_log_price")).abs().alias("deviation")
        )
        .group_by("item_category")
        .agg(pl.col("deviation").median().alias("mad_log_price"))
    )
    return medians.join(mads, on="item_category").filter(
        pl.col("category_size") >= settings.inflation_min_category_size
    )


@dataclass(frozen=True)
class PriceControls:
    """How much of a price difference the ledger can legitimately explain.

    Two effects, both measurable without trusting any text: buying more per
    order lowers the unit price, and prices drift year on year. Fitted pooled
    across categories on the median-removed log price. Note what is *not* here:
    the supplier is never a control. Adjusting for "what this supplier usually
    charges" would raise the bar for exactly the supplier under suspicion.
    """

    bulk_discount: float  # per unit of log quantity
    annual_drift: float  # per year
    scale: float  # robust spread of the residual, in log space

    def describe(self) -> dict[str, float]:
        return {
            "bulk_discount_per_log_quantity": round(self.bulk_discount, 5),
            "annual_price_drift": round(self.annual_drift, 4),
            "residual_scale_log": round(self.scale, 4),
        }


def _fit_controls(frame: pl.DataFrame, min_scale: float) -> tuple[PriceControls, np.ndarray]:
    """Least squares for the two controls, then a robust scale for the residual."""
    relative = (frame["log_price"] - frame["median_log_price"]).to_numpy()
    design = np.column_stack(
        [
            np.ones(frame.height),
            frame["log_quantity"].to_numpy(),
            frame["days_elapsed"].to_numpy(),
        ]
    )
    coefficients, *_ = np.linalg.lstsq(design, relative, rcond=None)
    residual = relative - design @ coefficients
    centre = float(np.median(residual))
    scale = max(MAD_TO_SIGMA * float(np.median(np.abs(residual - centre))), min_scale)
    controls = PriceControls(
        bulk_discount=float(coefficients[1]),
        annual_drift=float(coefficients[2]) * 365.25,
        scale=scale,
    )
    return controls, (residual - centre) / scale


def _second_opinion(frame: pl.DataFrame) -> pl.DataFrame:
    """Isolation Forest over engineered features - a multivariate cross-check.

    Seeded, so a rerun reproduces it exactly. Its verdict is recorded on each
    case; it never raises one by itself, because at the configured contamination
    it would flag a percent or two of *every* row.
    """
    from sklearn.ensemble import IsolationForest

    features = frame.select(FEATURES).to_numpy()
    forest = IsolationForest(
        n_estimators=200,
        contamination=settings.isolation_forest_contamination,
        random_state=settings.random_seed,
    ).fit(features)
    return frame.with_columns(
        pl.Series("forest_outlier", forest.predict(features) == -1),
        pl.Series("forest_score", forest.score_samples(features).round(4)),
    )


class InflationDetector:
    name: ClassVar[str] = "d3"
    anomaly_types: ClassVar[tuple[AnomalyType, ...]] = (AnomalyType.INFLATION,)

    # Floor on the scale estimate. A category where every price is identical has
    # MAD 0; without a floor every rounding difference becomes infinitely
    # anomalous. 0.02 in log space is roughly a 2% spread.
    MIN_SCALE: ClassVar[float] = 0.02

    def __init__(self, z_threshold: float | None = None) -> None:
        self.z_threshold = (
            settings.inflation_zscore_threshold if z_threshold is None else z_threshold
        )
        self.categories_scored = 0
        self.rows_scored = 0
        self.controls = PriceControls(0.0, 0.0, self.MIN_SCALE)

    def _load(self, con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
        return con.execute(
            f"""
            SELECT row_id, vendor_key, item_category, unit_price, quantity, amount, txn_date
            FROM {AUDIT_VIEW}
            WHERE unit_price > 0 AND item_category IS NOT NULL AND quantity > 0
            ORDER BY row_id
            """
        ).pl()

    def score(self, con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
        """Every eligible row with its robust z-score. Exposed for analysis and ablations."""
        frame = self._load(con)
        if frame.is_empty():
            return frame
        frame = frame.with_columns(pl.col("unit_price").log().alias("log_price"))

        stats = _robust_stats(frame)
        self.categories_scored = stats.height
        if stats.is_empty():
            return frame.head(0)

        scored = frame.join(stats, on="item_category", how="inner")
        self.rows_scored = scored.height

        spend = scored.group_by("item_category").agg(pl.col("amount").sum().alias("category_spend"))
        by_vendor = scored.group_by(["item_category", "vendor_key"]).agg(
            pl.col("amount").sum().alias("vendor_spend")
        )
        start = scored["txn_date"].min()
        scored = (
            scored.join(spend, on="item_category")
            .join(by_vendor, on=["item_category", "vendor_key"])
            .with_columns(
                (pl.col("log_price") - pl.col("median_log_price")).alias("relative_log_price"),
                pl.col("quantity").log().alias("log_quantity"),
                (pl.col("vendor_spend") / pl.col("category_spend")).alias("vendor_category_share"),
                (pl.col("txn_date") - pl.lit(start))
                .dt.total_days()
                .cast(pl.Float64)
                .alias("days_elapsed"),
            )
        )

        self.controls, z = _fit_controls(scored, self.MIN_SCALE)
        scored = scored.with_columns(
            pl.Series("robust_z", z),
            # What the price should have been, given the category, the order size
            # and when it was bought.
            (
                pl.col("median_log_price")
                + self.controls.bulk_discount * pl.col("log_quantity")
                + (self.controls.annual_drift / 365.25) * pl.col("days_elapsed")
            )
            .exp()
            .alias("expected_price"),
        )
        return _second_opinion(scored).sort("row_id")

    def detect(self, con: duckdb.DuckDBPyConnection) -> list[Case]:
        scored = self.score(con)
        if scored.is_empty():
            return []
        flagged = scored.filter(pl.col("robust_z") >= self.z_threshold)

        cases: list[Case] = []
        for row in flagged.iter_rows(named=True):
            expected = row["expected_price"]
            excess = max((row["unit_price"] - expected) * row["quantity"], 0.0)
            # Logistic on the robust z (decision D-08): 0.5 at the threshold,
            # rising with the strength of the evidence.
            score = 1.0 / (1.0 + math.exp(-(row["robust_z"] - self.z_threshold)))
            cases.append(
                Case.build(
                    detector=self.name,
                    anomaly_type=AnomalyType.INFLATION,
                    row_ids=[row["row_id"]],
                    detector_score=round(score, 4),
                    amount_at_risk=excess,
                    vendor_key=row["vendor_key"],
                    metadata={
                        "policy_clause": POLICY_CLAUSE,
                        "item_category": row["item_category"],
                        "category_size": row["category_size"],
                        "unit_price": round(row["unit_price"], 2),
                        "category_median_price": round(math.exp(row["median_log_price"]), 2),
                        "expected_price": round(expected, 2),
                        "times_expected": round(row["unit_price"] / expected, 2),
                        "robust_z": round(row["robust_z"], 2),
                        "controls": self.controls.describe(),
                        "quantity": row["quantity"],
                        "isolation_forest_agrees": bool(row["forest_outlier"]),
                        "isolation_forest_score": row["forest_score"],
                    },
                )
            )
        return cases


def second_opinion_gap(
    detector: InflationDetector, con: duckdb.DuckDBPyConnection
) -> dict[str, int]:
    """How much the Isolation Forest would add or lose on its own - for the ablation table."""
    scored = detector.score(con)
    if scored.is_empty():
        return {"z_only": 0, "forest_only": 0, "both": 0}
    z = scored["robust_z"] >= detector.z_threshold
    f = scored["forest_outlier"]
    return {
        "z_only": int((z & ~f).sum()),
        "forest_only": int((~z & f).sum()),
        "both": int((z & f).sum()),
    }
