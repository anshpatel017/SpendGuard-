"""D1 duplicate detection (decisions D-12, D-19, D-20)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pytest

from spendguard.cases import AnomalyType
from spendguard.detectors import DuplicateDetector
from spendguard.detectors.d1_duplicates import (
    COMPARISONS,
    FellegiSunter,
    compare,
    invoice_core_numbers,
    model_frame,
)
from spendguard.eval.injection import InjectionResult
from spendguard.eval.matching import load_ground_truth, match
from spendguard.pipeline.ingest import IngestResult

from .conftest import build_db

JAN = date(2025, 1, 15)


def _row(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "vendor_name": "Sharma Traders", "invoice_no": "INV-04471", "amount": 5000.0,
        "txn_date": JAN, "officer_id": "ADM-001", "item_category": "Paper", "quantity": 10.0,
    }  # fmt: skip
    return {**base, **kw}


# ---------------------------------------------------------------- invoice evidence


@pytest.mark.parametrize(
    ("invoice", "expected"),
    [
        ("INV-04471", {4471}),
        ("4471/2025", {4471}),
        ("4471/25", {4471}),
        ("ST/24-25/045", {45}),  # financial-year parts are not identifying
        ("BILL", set()),
        (None, set()),
    ],
)
def test_invoice_core_numbers(invoice: str | None, expected: set[int]) -> None:
    assert invoice_core_numbers(invoice, JAN) == expected


def test_reformatted_invoice_shares_a_core_but_next_invoice_does_not() -> None:
    assert invoice_core_numbers("INV-04471", JAN) & invoice_core_numbers("4471/2025", JAN)
    assert not invoice_core_numbers("ST/24-25/045", JAN) & invoice_core_numbers("ST/24-25/046", JAN)


# ---------------------------------------------------------------- comparison vector


def _levels(a: dict[str, object], b: dict[str, object], sim: float = 100.0) -> dict[str, str]:
    vector = compare(a, b, sim)
    return {c.name: c.levels[v] for c, v in zip(COMPARISONS, vector, strict=True)}


def test_identical_records_agree_on_everything() -> None:
    levels = _levels(_row(), _row())
    assert levels["invoice"] == "identical"
    assert levels["context"].startswith("same officer, item, quantity and amount")
    assert levels["date_gap"] == "0-3 days"


def test_reformatted_invoice_is_a_core_match() -> None:
    assert _levels(_row(), _row(invoice_no="4471/2025"))["invoice"] == "same core number"


def test_missing_invoice_is_its_own_level() -> None:
    assert _levels(_row(), _row(invoice_no=None))["invoice"] == "missing"


def test_context_degrades_as_fields_differ() -> None:
    assert _levels(_row(), _row(amount=5010.0))["context"].startswith("same officer and item")
    assert _levels(_row(), _row(officer_id="PWD-002"))["context"] == "officer or item differs"
    assert (
        _levels(_row(), _row(officer_id="PWD-002", item_category="Ink"))["context"]
        == "officer and item both differ"
    )


def test_date_gap_levels() -> None:
    assert _levels(_row(), _row(txn_date=date(2025, 1, 20)))["date_gap"] == "4-7 days"
    assert _levels(_row(), _row(txn_date=date(2025, 1, 27)))["date_gap"] == "8-14 days"


# ---------------------------------------------------------------- the model


def _mixture(n_match: int, n_non: int, seed: int = 0) -> np.ndarray:
    """Matches agree on invoice and context; non-matches mostly do not."""
    rng = np.random.default_rng(seed)
    matches = np.column_stack([
        rng.choice(3, n_match, p=[0.8, 0.15, 0.05]), rng.choice(4, n_match, p=[0.4, 0.55, 0.04, 0.01]),
        rng.choice(4, n_match, p=[0.9, 0.05, 0.04, 0.01]), rng.choice(3, n_match),
    ])  # fmt: skip
    non = np.column_stack([
        rng.choice(3, n_non, p=[0.3, 0.3, 0.4]), rng.choice(4, n_non, p=[0.001, 0.001, 0.997, 0.001]),
        rng.choice(4, n_non, p=[0.1, 0.03, 0.27, 0.6]), rng.choice(3, n_non),
    ])  # fmt: skip
    return np.vstack([matches, non]).astype(np.int64)


def test_em_separates_a_clear_mixture() -> None:
    x = _mixture(200, 2000)
    p = FellegiSunter().fit(x, 200).posterior(x)
    assert p[:200].mean() > 0.9
    assert p[200:].mean() < 0.05


def test_em_does_not_invent_duplicates_when_there_are_none() -> None:
    """Regression: plain EM put 94.5% of pairs in the duplicate class on clean data."""
    x = _mixture(0, 2000)
    model = FellegiSunter().fit(x, 200)
    assert model.prior < 0.02
    assert (model.posterior(x) >= 0.5).mean() < 0.01


def test_tiny_data_keeps_the_prior_model() -> None:
    model = FellegiSunter().fit(_mixture(2, 5), 200)
    assert model.iterations == 0


def test_match_weights_explain_the_score() -> None:
    model = FellegiSunter().fit(_mixture(200, 2000), 200)
    weights = model.match_weights((0, 1, 0, 0))
    assert weights["invoice"] > 0 and weights["context"] > 0
    assert model.match_weights((2, 2, 3, 2))["invoice"] < 0


# ---------------------------------------------------------------- the detector


def test_quality_on_injected_data(injected: InjectionResult) -> None:
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        groups = load_ground_truth(con)
        cases = DuplicateDetector().detect(con)
    m = match(cases, groups, AnomalyType.DUPLICATE)
    precision = m.tp / max(m.tp + m.fp, 1)
    recall = m.tp / (m.tp + m.fn)
    assert precision >= 0.9, precision
    assert recall >= 0.75, recall


def test_no_duplicates_found_in_clean_data(ingested: IngestResult) -> None:
    """The clean generator plants none; recurring contracts must not look like any."""
    with duckdb.connect(str(ingested.db_path), read_only=True) as con:
        assert len(DuplicateDetector().detect(con)) <= 1


def test_triplicates_become_one_case(injected: InjectionResult) -> None:
    triples = [
        r
        for r in injected.records
        if r.injection_type == AnomalyType.DUPLICATE and len(r.row_ids) == 3
    ]
    if not triples:
        pytest.skip("this seed placed no triplicate")
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        cases = DuplicateDetector().detect(con)
    found = {c.row_ids for c in cases}
    assert any(tuple(sorted(t.row_ids)) in found for t in triples)


def test_detection_is_deterministic(injected: InjectionResult) -> None:
    """Same cases, same order, every run. Regression: an unordered GROUP BY let
    DuckDB's parallel aggregation reorder the output between runs."""
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        runs = [[c.model_dump() for c in DuplicateDetector().detect(con)] for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


@pytest.mark.parametrize("detector", ["baseline", "d1", "d2"])
def test_every_detector_is_deterministic(injected: InjectionResult, detector: str) -> None:
    from spendguard.detectors import REGISTRY

    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        runs = [[c.case_id for c in REGISTRY[detector]().detect(con)] for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


def test_cases_carry_their_evidence(injected: InjectionResult) -> None:
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        detector = DuplicateDetector()
        cases = detector.detect(con)
    assert cases
    for c in cases:
        assert c.metadata["policy_clause"] == "SG-PP-4.4"
        assert c.metadata["pairs"]
        assert 0.0 <= c.detector_score <= 1.0
    assert set(model_frame(detector)["field"]) == {c.name for c in COMPARISONS}


# ---------------------------------------------------------------- boundaries


def test_two_identical_rows_are_one_case_of_two(tmp_path: Path) -> None:
    con = build_db(tmp_path / "t.duckdb", [{"invoice_no": "INV-1"}, {"invoice_no": "INV-1"}])
    cases = DuplicateDetector().detect(con)
    assert [c.row_ids for c in cases] == [(1, 2)]
    assert cases[0].detector_score == 1.0
    assert cases[0].metadata["stages"] == ["exact"]


def test_same_amount_far_outside_the_window_is_not_a_candidate(tmp_path: Path) -> None:
    """Different invoices, 60 days apart: outside the 14-day policy window."""
    con = build_db(
        tmp_path / "t.duckdb",
        [{"txn_date": date(2025, 4, 1)}, {"txn_date": date(2025, 5, 31)}],
    )
    detector = DuplicateDetector()
    assert detector.detect(con) == []
    assert detector.candidates_blocked == 0


@pytest.mark.parametrize(
    ("second_amount", "is_candidate"),
    [
        # |a - b| < 0.5% of the larger amount (policy SG-PP-4.4: "less than")
        (10_000.0, True),  # identical
        (10_049.0, True),  # 49 / 10,049 = 0.488%
        (10_050.0, True),  # 50 / 10,050 = 0.4975%
        (10_051.0, False),  # 51 / 10,051 = 0.507%
        (9_950.0, False),  # 50 / 10,000 = exactly 0.5% - not "less than"
        (9_951.0, True),  # 49 / 10,000 = 0.49%
        (9_900.0, False),  # 1%
    ],
)
def test_amount_tolerance_boundary(
    tmp_path: Path, second_amount: float, is_candidate: bool
) -> None:
    con = build_db(tmp_path / "t.duckdb", [{"amount": 10_000.0}, {"amount": second_amount}])
    detector = DuplicateDetector()
    assert (detector._blocked_pairs(con) == [(1, 2)]) is is_candidate


def test_amount_tolerance_is_symmetric(tmp_path: Path) -> None:
    """Whichever row comes first, the pair qualifies the same way."""
    a = build_db(tmp_path / "a.duckdb", [{"amount": 10_000.0}, {"amount": 10_050.0}])
    b = build_db(tmp_path / "b.duckdb", [{"amount": 10_050.0}, {"amount": 10_000.0}])
    assert DuplicateDetector()._blocked_pairs(a) == DuplicateDetector()._blocked_pairs(b)
