"""Krippendorff's alpha: pinned to published values, then to the properties we rely on.

A reliability coefficient that is subtly wrong is worse than none - it would
make an unreliable rubric look trustworthy in the report. So the first test
reproduces the worked three-observer example that the published figures come
from, to three decimal places, and the rest pin the behaviour around it.
"""

from __future__ import annotations

import random

import pytest

from spendguard.eval.agreement import exact_agreement, interpret, krippendorff_alpha

N = None

# The canonical three-observer example, with its published alphas: 0.691 nominal
# and 0.807 ordinal. Fifteen units; two observers cover most of them, unit 14 is
# graded by nobody and units 1, 2 and 5 by one observer only.
PUBLISHED = list(
    zip(
        [N, N, N, N, N, 3, 4, 1, 2, 1, 1, 3, 3, N, 3],
        [1, N, 2, 1, 3, 3, 4, 3, N, N, N, N, N, N, N],
        [N, N, 2, 1, 3, 4, 4, N, 2, 1, 1, 3, 3, N, 4],
        strict=True,
    )
)


def test_alpha_reproduces_the_published_worked_example() -> None:
    assert krippendorff_alpha(PUBLISHED, ordinal=False) == pytest.approx(0.691, abs=0.001)
    assert krippendorff_alpha(PUBLISHED, ordinal=True) == pytest.approx(0.807, abs=0.001)


def test_units_only_one_grader_scored_are_left_out() -> None:
    """They carry no information about agreement, so adding them must change nothing."""
    with_extras = [*PUBLISHED, (2, N, N), (N, 4, N), (N, N, 1)]
    assert krippendorff_alpha(with_extras) == pytest.approx(krippendorff_alpha(PUBLISHED))


def test_perfect_agreement_is_one_and_pure_noise_is_about_zero() -> None:
    assert krippendorff_alpha([(2, 2, 2), (0, 0, 0), (1, 1, 1)] * 5) == 1.0

    rng = random.Random(42)
    noise = [tuple(rng.randint(0, 2) for _ in range(3)) for _ in range(4000)]
    assert krippendorff_alpha(noise) == pytest.approx(0.0, abs=0.05)


def test_the_ordinal_scale_punishes_a_two_point_gap_harder_than_a_one_point_gap() -> None:
    """The whole reason for choosing ordinal over Fleiss' kappa on a 0-1-2 rubric."""
    near = [(0, 1), (1, 2), (2, 2), (0, 0), (1, 1), (2, 1)]
    far = [(0, 2), (2, 0), (2, 2), (0, 0), (1, 1), (2, 1)]
    assert krippendorff_alpha(near) > krippendorff_alpha(far)
    # Nominal cannot tell them apart: both have the same number of mismatches.
    assert krippendorff_alpha(near, ordinal=False) == pytest.approx(
        krippendorff_alpha(far, ordinal=False)
    )


def test_graders_who_disagree_more_than_chance_score_below_zero() -> None:
    assert krippendorff_alpha([(0, 2), (2, 0)] * 10) < 0.0


def test_nothing_to_measure_is_none_not_zero() -> None:
    """Zero would read as "they disagreed"; they did not grade."""
    assert krippendorff_alpha([(1, N), (N, 2)]) is None
    assert exact_agreement([(1, N), (N, 2)]) is None
    assert interpret(None) == "not measurable"


def test_one_value_used_throughout_is_perfect_agreement() -> None:
    """Chance is undefined when nobody varied; that is agreement, not an error."""
    assert krippendorff_alpha([(2, 2), (2, 2), (2, 2)]) == 1.0


def test_exact_agreement_counts_units_every_grader_scored_the_same() -> None:
    assert exact_agreement([(1, 1, 1), (0, 0, 1), (2, 2, N), (1, N, N)]) == pytest.approx(2 / 3)


@pytest.mark.parametrize(
    ("alpha", "expected"),
    [(0.95, "reliable"), (0.8, "reliable"), (0.7, "tentative"), (0.4, "unreliable")],
)
def test_the_customary_reading_is_stated_not_left_to_the_reader(
    alpha: float, expected: str
) -> None:
    assert expected in interpret(alpha)
