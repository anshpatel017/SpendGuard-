"""Inter-grader agreement: Krippendorff's alpha (EVALUATION section 5.3).

Three people grading the same notes will not agree perfectly, and a rubric
nobody agrees on measures the graders rather than the notes. So the report
states agreement beside every score.

**Why alpha and not something simpler.** Percent agreement rewards a rubric
where everyone says 2 to everything: with three points on the scale, two
graders who answer at random still match about a third of the time. Cohen's
kappa handles two coders only. Fleiss' kappa handles three but treats the
scale as nominal, so scoring 0 where another grader scored 2 counts the same
as scoring 1 - which is wrong for a 0-1-2 rubric where the distance means
something. Krippendorff's alpha takes any number of coders, tolerates a grader
skipping a note, and accepts an **ordinal** difference function. Percent
agreement is still reported next to it, because it is the number a reader
understands without a definition.

Alpha is 1 for perfect agreement, 0 for agreement no better than chance, and
negative when graders disagree more than chance would predict. The usual
reading: 0.8 and above is reliable, 0.667 is the floor for tentative
conclusions, below that the rubric needs work rather than the notes.

The implementation follows Krippendorff (2011), *Computing Krippendorff's
Alpha-Reliability*, and is tested against the worked example in that paper.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

# Values a rubric dimension can take. Ordinal, so 0 against 2 is a worse
# disagreement than 0 against 1, and the metric has to know it.
Score = int
Ratings = Sequence[Sequence[Score | None]]  # one row per unit, one column per coder


def _ordinal_deltas(
    counts: dict[Score, float], values: list[Score]
) -> dict[tuple[int, int], float]:
    """The ordinal difference function: how far apart two ranks are on this scale.

    Distance is measured in *observed* values, not in the labels themselves, so
    a rubric point nobody ever used does not widen the gap around it.
    """
    deltas = {}
    for i, c in enumerate(values):
        for j, k in enumerate(values):
            lo, hi = (i, j) if i <= j else (j, i)
            total = sum(counts[values[g]] for g in range(lo, hi + 1))
            deltas[(i, j)] = (total - (counts[c] + counts[k]) / 2.0) ** 2
    return deltas


def _nominal_deltas(values: list[Score]) -> dict[tuple[int, int], float]:
    return {(i, j): float(i != j) for i in range(len(values)) for j in range(len(values))}


def krippendorff_alpha(ratings: Ratings, *, ordinal: bool = True) -> float | None:
    """Alpha over a units x coders matrix, ``None`` where a coder did not grade.

    Returns ``None`` when there is nothing to measure - fewer than two units
    that two or more graders both scored. Returns 1.0 when every grader who
    scored anything gave the same value throughout: there is no disagreement to
    explain, even though the chance term is then undefined.
    """
    # Only units two or more graders scored carry information about agreement.
    units = [[v for v in row if v is not None] for row in ratings]
    units = [u for u in units if len(u) >= 2]
    if not units:
        return None

    counts = Counter(v for u in units for v in u)
    values = sorted(counts)
    n = float(sum(counts.values()))
    if len(values) == 1:
        return 1.0  # everyone said the same thing about everything
    index = {v: i for i, v in enumerate(values)}
    frequencies = {v: float(counts[v]) for v in values}
    deltas = _ordinal_deltas(frequencies, values) if ordinal else _nominal_deltas(values)

    # Observed coincidences: every ordered pair of ratings within a unit,
    # weighted by 1/(m-1) so a unit graded by more people does not count more.
    observed = 0.0
    for unit in units:
        pairs = len(unit) - 1
        for i, a in enumerate(unit):
            for j, b in enumerate(unit):
                if i != j:
                    observed += deltas[(index[a], index[b])] / pairs

    expected = 0.0
    for a in values:
        for b in values:
            expected += frequencies[a] * frequencies[b] * deltas[(index[a], index[b])]
    if expected == 0.0:
        return 1.0
    return 1.0 - (n - 1.0) * observed / expected


def exact_agreement(ratings: Ratings) -> float | None:
    """The share of graded units every grader scored identically. Plain, and reported as such."""
    units = [[v for v in row if v is not None] for row in ratings]
    units = [u for u in units if len(u) >= 2]
    if not units:
        return None
    return sum(1 for u in units if len(set(u)) == 1) / len(units)


def interpret(alpha: float | None) -> str:
    """The customary reading, stated so a report does not have to argue it."""
    if alpha is None:
        return "not measurable"
    if alpha >= 0.8:
        return "reliable"
    if alpha >= 0.667:
        return "tentative conclusions only"
    return "unreliable - the rubric needs work before the scores mean anything"
