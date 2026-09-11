"""Precision, recall, F1 and PR-AUC - per case (primary) and per row (secondary).

Per case answers the auditor's question: how many of the frauds did we find,
and how many alerts were wasted? Per row answers the completeness question: how
much of the implicated data did we surface? Both are reported because they
genuinely differ (docs/EVALUATION.md 3.3).

Conventions:

* Precision with no predictions, and recall with no positives, are 0.0.
* PR-AUC is average precision computed over *distinct score thresholds*, the
  same definition scikit-learn uses: tied scores enter together. So a binary
  detector - every case scored 1.0 - gets exactly precision x recall, with no
  dependence on the arbitrary order of its ties.
* Recall's denominator is every ground-truth group, including ones no case
  touched. Missed groups drag PR-AUC down, as they should.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import groupby

from spendguard.cases import AnomalyType, Case
from spendguard.eval.matching import TruthGroup, match

ALL = "all"


@dataclass(frozen=True)
class DetectionMetrics:
    detector: str
    anomaly_type: str  # an AnomalyType value, or "all"
    granularity: str  # "case" or "row"
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    pr_auc: float | None  # per-case only

    @property
    def predicted(self) -> int:
        return self.tp + self.fp

    @property
    def actual(self) -> int:
        return self.tp + self.fn


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def average_precision(ranked: Sequence[tuple[float, bool]], positives: int) -> float:
    """Area under the precision-recall curve, stepping at each distinct score.

    ``ranked`` is (score, is_true_positive) for every prediction.
    """
    if positives == 0 or not ranked:
        return 0.0
    ordered = sorted(ranked, key=lambda item: -item[0])
    tp = fp = 0
    ap = previous_recall = 0.0
    for _, block in groupby(ordered, key=lambda item: item[0]):
        for _, hit in block:
            tp += hit
            fp += not hit
        recall = tp / positives
        ap += (recall - previous_recall) * (tp / (tp + fp))
        previous_recall = recall
    return ap


def _metrics(
    detector: str, kind: str, granularity: str, tp: int, fp: int, fn: int, pr_auc: float | None
) -> DetectionMetrics:
    p, r, f = precision_recall_f1(tp, fp, fn)
    return DetectionMetrics(detector, kind, granularity, tp, fp, fn, p, r, f, pr_auc)


def evaluate_cases(
    detector: str, cases: Sequence[Case], groups: Sequence[TruthGroup]
) -> list[DetectionMetrics]:
    """Per-type and pooled ("all") metrics, at case and row granularity."""
    kinds = [t for t in AnomalyType if any(g.anomaly_type == t for g in groups)] + [
        t
        for t in AnomalyType
        if any(c.anomaly_type == t for c in cases) and not any(g.anomaly_type == t for g in groups)
    ]
    results: list[DetectionMetrics] = []
    pooled_ranked: list[tuple[float, bool]] = []
    totals: dict[str, tuple[int, int, int]] = {"case": (0, 0, 0), "row": (0, 0, 0)}

    for kind in kinds:
        m = match(cases, groups, kind)
        positives = m.tp + m.fn
        results.append(
            _metrics(
                detector,
                kind.value,
                "case",
                m.tp,
                m.fp,
                m.fn,
                average_precision(m.ranked, positives),
            )
        )
        pooled_ranked.extend(m.ranked)

        predicted_rows = {r for c in cases if c.anomaly_type == kind for r in c.row_ids}
        true_rows = {r for g in groups if g.anomaly_type == kind for r in g.row_ids}
        hits = len(predicted_rows & true_rows)
        row_tp, row_fp, row_fn = hits, len(predicted_rows) - hits, len(true_rows) - hits
        results.append(_metrics(detector, kind.value, "row", row_tp, row_fp, row_fn, None))

        for granularity, (tp, fp, fn) in (
            ("case", (m.tp, m.fp, m.fn)),
            ("row", (row_tp, row_fp, row_fn)),
        ):
            t_tp, t_fp, t_fn = totals[granularity]
            totals[granularity] = (t_tp + tp, t_fp + fp, t_fn + fn)

    case_tp, case_fp, case_fn = totals["case"]
    pooled_ap = average_precision(pooled_ranked, case_tp + case_fn)
    results.append(_metrics(detector, ALL, "case", case_tp, case_fp, case_fn, pooled_ap))
    row_tp, row_fp, row_fn = totals["row"]
    results.append(_metrics(detector, ALL, "row", row_tp, row_fp, row_fn, None))
    return results
