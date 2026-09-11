"""Case-to-truth matching and the metrics built on it (decision D-03, docs/EVALUATION.md)."""

from __future__ import annotations

import pytest

from spendguard.cases import AnomalyType, Case
from spendguard.eval.matching import TruthGroup, match
from spendguard.eval.metrics import ALL, average_precision, evaluate_cases, precision_recall_f1

DUP, SPLIT, VENDOR = AnomalyType.DUPLICATE, AnomalyType.SPLIT, AnomalyType.VENDOR_FLAG


def case(
    rows: list[int], kind: AnomalyType = SPLIT, score: float = 1.0, vendor: str | None = None
) -> Case:
    return Case.build(
        detector="t", anomaly_type=kind, row_ids=rows, detector_score=score,
        amount_at_risk=1.0, vendor_key=vendor,
    )  # fmt: skip


def group(
    gid: str, rows: list[int], kind: AnomalyType = SPLIT, vendor: str | None = None
) -> TruthGroup:
    return TruthGroup(gid, kind, frozenset(rows), vendor, 1.0)


# ---------------------------------------------------------------- the overlap rule


def test_exact_match_is_a_true_positive() -> None:
    m = match([case([1, 2, 3])], [group("g", [1, 2, 3])], SPLIT)
    assert (m.tp, m.fp, m.fn) == (1, 0, 0)


def test_exactly_half_spurious_still_matches() -> None:
    """The boundary is inclusive: 2 of 4 rows spurious is 50%."""
    m = match([case([1, 2, 90, 91])], [group("g", [1, 2, 3])], SPLIT)
    assert m.tp == 1


def test_more_than_half_spurious_does_not_match() -> None:
    m = match([case([1, 90, 91])], [group("g", [1, 2, 3])], SPLIT)
    assert (m.tp, m.fp, m.fn) == (0, 1, 1)


def test_no_overlap_is_a_false_positive_and_a_miss() -> None:
    m = match([case([50, 51])], [group("g", [1, 2])], SPLIT)
    assert (m.tp, m.fp, m.fn) == (0, 1, 1)


def test_partial_detection_of_a_group_counts() -> None:
    """Finding 2 of a 5-part split with no noise is a hit - the auditor has the lead."""
    m = match([case([1, 2])], [group("g", [1, 2, 3, 4, 5])], SPLIT)
    assert m.tp == 1


# ---------------------------------------------------------------- one-to-one


def test_second_case_on_a_claimed_group_is_a_false_positive() -> None:
    """Five alerts for one scheme is four redundant alerts."""
    m = match([case([1]), case([2]), case([3])], [group("g", [1, 2, 3])], SPLIT)
    assert (m.tp, m.fp, m.fn) == (1, 2, 0)


def test_higher_score_claims_the_group_first() -> None:
    weak, strong = case([1], score=0.2), case([2], score=0.9)
    m = match([weak, strong], [group("g", [1, 2])], SPLIT)
    assert m.matched == {strong.case_id: "g"}
    assert m.false_positives == [weak.case_id]


def test_case_takes_the_group_it_overlaps_most() -> None:
    m = match([case([1, 2, 10])], [group("a", [1, 50]), group("b", [2, 10, 60])], SPLIT)
    assert list(m.matched.values()) == ["b"]
    assert m.false_negatives == ["a"]


def test_types_must_agree() -> None:
    m = match([case([1, 2], kind=DUP)], [group("g", [1, 2], kind=SPLIT)], SPLIT)
    assert (m.tp, m.fp, m.fn) == (0, 0, 1)


# ---------------------------------------------------------------- vendor level


def test_vendor_flags_match_on_vendor_not_rows() -> None:
    """A vendor case holds all the supplier's rows; row overlap would wrongly fail it."""
    m = match(
        [case(list(range(100)), kind=VENDOR, vendor="kaveri")],
        [group("v", [5, 6], kind=VENDOR, vendor="kaveri")],
        VENDOR,
    )
    assert m.tp == 1


def test_vendor_flag_on_the_wrong_vendor_misses() -> None:
    m = match(
        [case([5, 6], kind=VENDOR, vendor="sharma")],
        [group("v", [5, 6], kind=VENDOR, vendor="kaveri")],
        VENDOR,
    )
    assert (m.tp, m.fp, m.fn) == (0, 1, 1)


# ---------------------------------------------------------------- metrics


def test_precision_recall_f1() -> None:
    assert precision_recall_f1(3, 1, 2) == pytest.approx((0.75, 0.6, 2 * 0.75 * 0.6 / 1.35))
    assert precision_recall_f1(0, 0, 5) == (0.0, 0.0, 0.0)
    assert precision_recall_f1(0, 4, 0) == (0.0, 0.0, 0.0)


def test_average_precision_perfect_ranking() -> None:
    assert average_precision([(0.9, True), (0.8, True), (0.1, False)], positives=2) == 1.0


def test_average_precision_hand_computed() -> None:
    # hits at ranks 1 and 3 of 2 positives: (1/1 + 2/3) / 2
    ranked = [(0.9, True), (0.8, False), (0.7, True)]
    assert average_precision(ranked, positives=2) == pytest.approx((1 + 2 / 3) / 2)


def test_average_precision_penalizes_missed_groups() -> None:
    assert average_precision([(0.9, True)], positives=4) == pytest.approx(0.25)


def test_binary_scores_give_precision_times_recall_regardless_of_tie_order() -> None:
    """Ties enter together, so a yes/no detector's AP never depends on list order."""
    a = [(1.0, True), (1.0, False), (1.0, False), (1.0, True)]
    b = [(1.0, False), (1.0, False), (1.0, True), (1.0, True)]
    expected = (2 / 4) * (2 / 5)
    assert average_precision(a, positives=5) == pytest.approx(expected)
    assert average_precision(b, positives=5) == pytest.approx(expected)


def test_evaluate_cases_reports_every_type_and_a_pooled_row() -> None:
    groups = [group("s", [1, 2, 3]), group("d", [10, 11], kind=DUP)]
    cases = [case([1, 2]), case([40], kind=DUP)]
    results = evaluate_cases("t", cases, groups)
    kinds = {(m.anomaly_type, m.granularity) for m in results}
    assert {("split", "case"), ("duplicate", "row"), (ALL, "case"), (ALL, "row")} <= kinds

    pooled = next(m for m in results if m.anomaly_type == ALL and m.granularity == "case")
    assert (pooled.tp, pooled.fp, pooled.fn) == (1, 1, 1)


def test_counts_are_consistent(injected_eval: list) -> None:  # type: ignore[type-arg]
    for m in injected_eval:
        assert 0.0 <= m.precision <= 1.0 and 0.0 <= m.recall <= 1.0
        if m.pr_auc is not None:
            assert 0.0 <= m.pr_auc <= 1.0


@pytest.fixture
def injected_eval(injected):  # type: ignore[no-untyped-def]
    import duckdb

    from spendguard.detectors import BaselineDetector
    from spendguard.eval.matching import load_ground_truth

    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        groups = load_ground_truth(con)
        cases = BaselineDetector().detect(con)
    return evaluate_cases("baseline", cases, groups)
