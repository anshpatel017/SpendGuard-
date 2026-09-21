"""How well the Investigator sorts real anomalies from detector false positives.

Detection metrics say whether the detectors found the planted anomalies. These
say whether the *investigation* added anything: shown a case whose truth is
known, did the agent keep a real anomaly and dismiss a spurious one?

    real case       likely_true_positive  -> kept         (good)
                    likely_false_positive -> wrongly dismissed (the costly error)
    spurious case   likely_false_positive -> filtered     (good - the contribution)
                    likely_true_positive  -> passed on    (no worse than no agent)
    either          inconclusive          -> handed to a person, counted separately
    either          no note               -> failed, counted separately

A wrongly dismissed real anomaly is worse than a spurious one passed on: the
first hides fraud, the second costs an auditor ten minutes. That asymmetry is
why the two rates are reported separately and never folded into one accuracy.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

TRUE_POSITIVE = "likely_true_positive"
FALSE_POSITIVE = "likely_false_positive"
INCONCLUSIVE = "inconclusive"
FAILED = "failed"
ALL = "all"


@dataclass(frozen=True)
class TriageItem:
    anomaly_type: str
    is_real: bool  # the case matches a planted anomaly
    verdict: str | None  # None when the investigation produced no note


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def triage_metrics(items: Iterable[TriageItem]) -> dict[str, dict[str, object]]:
    """Per anomaly type and overall. Rates are None where there was nothing to measure."""
    grouped: dict[str, list[TriageItem]] = defaultdict(list)
    for item in items:
        grouped[item.anomaly_type].append(item)
        grouped[ALL].append(item)

    out: dict[str, dict[str, object]] = {}
    for kind in sorted(grouped, key=lambda k: (k == ALL, k)):
        group = grouped[kind]
        counts: dict[tuple[bool, str], int] = defaultdict(int)
        for item in group:
            counts[(item.is_real, item.verdict or FAILED)] += 1
        real = sum(1 for i in group if i.is_real)
        spurious = len(group) - real
        decisive = sum(
            n for (_, verdict), n in counts.items() if verdict in (TRUE_POSITIVE, FALSE_POSITIVE)
        )
        correct = counts[(True, TRUE_POSITIVE)] + counts[(False, FALSE_POSITIVE)]
        out[kind] = {
            "cases": len(group),
            "real": real,
            "spurious": spurious,
            "confusion": {
                "real": {
                    v: counts[(True, v)]
                    for v in (TRUE_POSITIVE, FALSE_POSITIVE, INCONCLUSIVE, FAILED)
                },
                "spurious": {
                    v: counts[(False, v)]
                    for v in (TRUE_POSITIVE, FALSE_POSITIVE, INCONCLUSIVE, FAILED)
                },
            },
            "real_kept": _rate(counts[(True, TRUE_POSITIVE)], real),
            "real_wrongly_dismissed": _rate(counts[(True, FALSE_POSITIVE)], real),
            "spurious_filtered": _rate(counts[(False, FALSE_POSITIVE)], spurious),
            "inconclusive": _rate(
                counts[(True, INCONCLUSIVE)] + counts[(False, INCONCLUSIVE)], len(group)
            ),
            "failed": _rate(counts[(True, FAILED)] + counts[(False, FAILED)], len(group)),
            "decisive_accuracy": _rate(correct, decisive),
        }
    return out
