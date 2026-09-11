"""D2 - split purchases (policy SG-PP-3.1 to SG-PP-3.4).

A requirement divided into several smaller purchases so each stays below the
approval threshold and the aggregate value never meets the authority it needs.
Trivial for a computer, invisible to a human reading invoices one at a time.

    For each supplier and requesting officer, walk their sub-threshold
    purchases in date order and find the shortest runs that, within the
    14-day policy window, add up to the threshold or more (SG-PP-3.2).

Runs are kept *minimal*: a run is closed as soon as it reaches the threshold,
and trimmed from the front while it still does. Without that, an officer who
buys from the same supplier every few days chains months of routine purchases
into one sprawling "split" that buries the real one.

Scoring (0-1) ranks what an auditor should look at first. Four indicators from
the policy and the split-purchase literature, weighted **equally** - the choice
that involves the least tuning (decision D-21):

    window        tighter is more deliberate - 3 days scores above 7 above 14
                  (SG-PP-3.3: shorter windows attract higher scrutiny)
    homogeneity   share of the run that is the same item - one requirement
                  split up, rather than unrelated purchases (SG-PP-3.4)
    single rate   share of the run billed at one identical unit price - one
                  quotation divided into invoices, where routine repeat buying
                  is re-priced each time
    parts         3-6 parts is the classic shape; 2 is weaker evidence

A run is raised as a case only if it scores at least ``split_score_threshold``.
Every sub-threshold run crossing the limit is a *candidate*; routine repeat
purchasing produces thousands of them, and an alert list that long is one no
auditor reads.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar

import duckdb

from spendguard.cases import AnomalyType, Case
from spendguard.config import settings
from spendguard.detectors.base import AUDIT_VIEW

WEIGHTS = {"window": 0.25, "homogeneity": 0.25, "single_rate": 0.25, "parts": 0.25}


@dataclass(frozen=True)
class Purchase:
    row_id: int
    amount: float
    txn_date: date
    item: str | None
    unit_price: float | None = None


def minimal_runs(
    purchases: list[Purchase], threshold: float, window_days: int
) -> list[list[Purchase]]:
    """Shortest date-ordered runs reaching ``threshold`` within ``window_days``.

    ``purchases`` must be sorted by date and each below the threshold. Runs do
    not overlap. A run meeting the threshold exactly qualifies - the policy
    tests "at or above" (SG-PP-3.2).
    """
    runs: list[list[Purchase]] = []
    i, n = 0, len(purchases)
    while i < n:
        total, end = 0.0, None
        for j in range(i, n):
            if (purchases[j].txn_date - purchases[i].txn_date).days > window_days:
                break
            total += purchases[j].amount
            if total >= threshold:
                end = j
                break
        if end is None:
            i += 1
            continue
        # Trim from the front while what remains still reaches the threshold.
        while i < end and total - purchases[i].amount >= threshold:
            total -= purchases[i].amount
            i += 1
        runs.append(purchases[i : end + 1])
        i = end + 1
    return runs


def score_run(run: list[Purchase]) -> tuple[float, dict[str, Any]]:
    windows = settings.split_windows_all  # e.g. [3, 7, 14]
    span = (run[-1].txn_date - run[0].txn_date).days
    tightest = next(w for w in windows if span <= w)
    window_score = 1.0 - 0.5 * windows.index(tightest) / max(len(windows) - 1, 1)

    n = len(run)
    items = [p.item for p in run if p.item]
    homogeneity = Counter(items).most_common(1)[0][1] / n if items else 0.5

    # Rates are compared as issued (to the paisa): one quotation, one number.
    rates = [round(p.unit_price, 2) for p in run if p.unit_price is not None]
    single_rate = Counter(rates).most_common(1)[0][1] / n if rates else 0.5

    parts_score = 1.0 if 3 <= n <= 6 else 0.6 if n == 2 else 0.7

    components = {
        "window": round(window_score, 3),
        "homogeneity": round(homogeneity, 3),
        "single_rate": round(single_rate, 3),
        "parts": parts_score,
    }
    score = sum(WEIGHTS[k] * v for k, v in components.items())
    return round(score, 4), {
        "window_days": tightest,
        "span_days": span,
        "homogeneity": round(homogeneity, 3),
        "single_rate": round(single_rate, 3),
        "components": components,
    }


class SplitDetector:
    name: ClassVar[str] = "d2"
    anomaly_types: ClassVar[tuple[AnomalyType, ...]] = (AnomalyType.SPLIT,)

    def detect(self, con: duckdb.DuckDBPyConnection) -> list[Case]:
        threshold = settings.approval_threshold
        frame = con.execute(
            f"""
            SELECT row_id, vendor_key, officer_id, amount, txn_date, unit_price,
                   coalesce(item_category, item_desc) AS item
            FROM {AUDIT_VIEW}
            WHERE amount < ?
            ORDER BY vendor_key, officer_id NULLS LAST, txn_date, row_id
            """,
            [threshold],
        ).pl()
        if frame.is_empty():
            return []

        # FR-1.6: without an officer column, group by supplier alone - and say so.
        has_officers = frame["officer_id"].null_count() < frame.height

        cases: list[Case] = []
        for (vendor_key, officer_id), part in frame.group_by(
            ["vendor_key", "officer_id"], maintain_order=True
        ):
            purchases = [
                Purchase(r["row_id"], float(r["amount"]), r["txn_date"], r["item"], r["unit_price"])
                for r in part.iter_rows(named=True)
            ]
            if has_officers and officer_id is not None:
                grain = "supplier and officer"
            elif has_officers:
                grain = "supplier, officer not recorded"
            else:
                grain = "supplier only - dataset has no officer field"

            for run in minimal_runs(purchases, threshold, settings.split_window_days):
                self.candidates += 1
                case = self._case(run, str(vendor_key), officer_id, grain, threshold)
                if case.detector_score >= self.score_threshold:
                    cases.append(case)
        return cases

    def __init__(self, score_threshold: float | None = None) -> None:
        self.score_threshold = (
            settings.split_score_threshold if score_threshold is None else score_threshold
        )
        self.candidates = 0

    def _case(
        self,
        run: list[Purchase],
        vendor_key: str,
        officer_id: str | None,
        grain: str,
        threshold: float,
    ) -> Case:
        score, detail = score_run(run)
        total = sum(p.amount for p in run)
        clauses = ["SG-PP-3.2"] + (["SG-PP-3.3"] if detail["window_days"] <= 7 else [])
        return Case.build(
            detector=self.name,
            anomaly_type=AnomalyType.SPLIT,
            row_ids=[p.row_id for p in run],
            detector_score=score,
            amount_at_risk=total,
            vendor_key=vendor_key,
            metadata={
                "policy_clauses": clauses,
                "grain": grain,
                "officer_id": officer_id,
                "parts": len(run),
                "total": round(total, 2),
                "threshold": threshold,
                "largest_part": round(max(p.amount for p in run), 2),
                **detail,
            },
        )
