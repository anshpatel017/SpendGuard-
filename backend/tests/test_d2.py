"""D2 split-purchase detection (policy SG-PP-3.1 to 3.4, decision D-21)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import polars as pl
import pytest

from spendguard.cases import AnomalyType
from spendguard.config import settings
from spendguard.db.duck import TRANSACTION_FIELDS, write_transactions
from spendguard.detectors import BaselineDetector, SplitDetector
from spendguard.detectors.d2_splits import Purchase, minimal_runs, score_run
from spendguard.eval.injection import InjectionResult
from spendguard.eval.matching import load_ground_truth
from spendguard.eval.metrics import evaluate_cases
from spendguard.pipeline.ingest import IngestResult

from .conftest import build_db

T = settings.approval_threshold
DAY0 = date(2025, 4, 1)


def p(
    row_id: int, amount: float, day: int, item: str = "Cement", rate: float | None = 410.0
) -> Purchase:
    return Purchase(row_id, amount, DAY0 + timedelta(days=day), item, rate)


# ---------------------------------------------------------------- run finding


def test_parts_crossing_the_threshold_form_a_run() -> None:
    runs = minimal_runs([p(1, 0.4 * T, 0), p(2, 0.4 * T, 2), p(3, 0.4 * T, 4)], T, 14)
    assert [[x.row_id for x in r] for r in runs] == [[1, 2, 3]]


def test_total_below_threshold_is_not_a_run() -> None:
    assert minimal_runs([p(1, 0.3 * T, 0), p(2, 0.3 * T, 1)], T, 14) == []


def test_exactly_reaching_the_threshold_qualifies() -> None:
    """Policy SG-PP-3.2 tests 'at or above'."""
    assert minimal_runs([p(1, 0.5 * T, 0), p(2, 0.5 * T, 1)], T, 14)


def test_purchases_outside_the_window_are_not_grouped() -> None:
    assert minimal_runs([p(1, 0.6 * T, 0), p(2, 0.6 * T, 15)], T, 14) == []


def test_runs_are_trimmed_to_the_minimum() -> None:
    """A small purchase before the split is not dragged into it."""
    runs = minimal_runs([p(1, 0.05 * T, 0), p(2, 0.5 * T, 1), p(3, 0.6 * T, 2)], T, 14)
    assert [[x.row_id for x in r] for r in runs] == [[2, 3]]


def test_routine_buying_does_not_chain_into_one_sprawling_run() -> None:
    weekly = [p(i, 0.3 * T, 3 * i) for i in range(20)]
    runs = minimal_runs(weekly, T, 14)
    assert runs and all(len(r) <= 4 for r in runs)
    assert len({x.row_id for r in runs for x in r}) == sum(len(r) for r in runs), "runs overlap"


# ---------------------------------------------------------------- scoring


def test_tighter_windows_score_higher() -> None:
    tight, _ = score_run([p(1, 0.5 * T, 0), p(2, 0.5 * T, 2), p(3, 0.5 * T, 3)])
    loose, _ = score_run([p(1, 0.5 * T, 0), p(2, 0.5 * T, 6), p(3, 0.5 * T, 13)])
    assert tight > loose


def test_one_quoted_rate_scores_higher_than_repricing() -> None:
    same, _ = score_run([p(i, 0.4 * T, i, rate=410.0) for i in range(3)])
    varied, _ = score_run([p(i, 0.4 * T, i, rate=400.0 + i * 7) for i in range(3)])
    assert same > varied


def test_score_components_are_reported() -> None:
    score, detail = score_run([p(i, 0.4 * T, i) for i in range(3)])
    assert 0.0 <= score <= 1.0
    assert set(detail["components"]) == {"window", "homogeneity", "single_rate", "parts"}


# ---------------------------------------------------------------- detector


def _db(tmp_path: Path, rows: list[dict[str, object]]) -> duckdb.DuckDBPyConnection:
    full = []
    for i, r in enumerate(rows, 1):
        full.append({
            "row_id": i, "vendor_name": "Sharma Constructions", "vendor_key": "constructions sharma",
            "invoice_no": f"INV-{i}", "txn_date": DAY0, "officer_id": "PWD-001",
            "item_desc": "Cement", "item_category": "Cement", "quantity": 100.0, "unit_price": 410.0,
            "source_dataset": "t", "source_row_ref": None, "is_injected": False,
            "injection_group_id": None, "injection_type": None, **r,
        })  # fmt: skip
    frame = pl.DataFrame(full, infer_schema_length=None).with_columns(
        pl.col("quantity", "unit_price", "amount").cast(pl.Float64),
        pl.col("officer_id", "invoice_no", "source_row_ref", "injection_group_id", "injection_type").cast(pl.String),
    )  # fmt: skip
    con = duckdb.connect(str(tmp_path / "s.duckdb"))
    write_transactions(con, frame.select(TRANSACTION_FIELDS))
    return con


def test_classic_split_is_caught(tmp_path: Path) -> None:
    con = _db(
        tmp_path, [{"amount": 0.4 * T, "txn_date": DAY0 + timedelta(days=d)} for d in (0, 1, 2)]
    )
    cases = SplitDetector().detect(con)
    assert len(cases) == 1
    c = cases[0]
    assert c.anomaly_type == AnomalyType.SPLIT and c.row_ids == (1, 2, 3)
    assert "SG-PP-3.3" in c.metadata["policy_clauses"]
    assert c.amount_at_risk == pytest.approx(1.2 * T)


def test_purchases_at_or_above_threshold_are_never_parts(tmp_path: Path) -> None:
    con = _db(tmp_path, [{"amount": T}, {"amount": 0.3 * T}, {"amount": 0.3 * T}])
    assert SplitDetector(score_threshold=0.0).detect(con) == []


def test_different_officers_are_not_grouped(tmp_path: Path) -> None:
    con = _db(tmp_path, [{"amount": 0.6 * T, "officer_id": f"PWD-00{i}"} for i in (1, 2)])
    assert SplitDetector(score_threshold=0.0).detect(con) == []


def test_without_officers_groups_by_supplier_and_says_so(tmp_path: Path) -> None:
    """FR-1.6: degrade gracefully when the dataset has no officer field."""
    con = _db(
        tmp_path,
        [
            {"amount": 0.4 * T, "officer_id": None, "txn_date": DAY0 + timedelta(days=d)}
            for d in (0, 1, 2)
        ],
    )
    cases = SplitDetector().detect(con)
    assert len(cases) == 1
    assert "no officer field" in cases[0].metadata["grain"]


def test_threshold_filters_low_scoring_runs(tmp_path: Path) -> None:
    rows = [
        {
            "amount": 0.6 * T,
            "txn_date": DAY0 + timedelta(days=d),
            "unit_price": 400.0 + d,
            "item_category": f"Item{d}",
        }
        for d in (0, 13)
    ]
    con = _db(tmp_path, rows)
    assert SplitDetector(score_threshold=0.0).detect(con)
    assert SplitDetector(score_threshold=0.99).detect(con) == []


def test_beats_the_baseline_on_injected_data(injected: InjectionResult) -> None:
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        groups = load_ground_truth(con)
        d2 = evaluate_cases("d2", SplitDetector().detect(con), groups)
        base = evaluate_cases("baseline", BaselineDetector().detect(con), groups)
    f1 = {
        m.detector: m.f1 for m in d2 + base if m.anomaly_type == "split" and m.granularity == "case"
    }
    assert f1["d2"] > 5 * max(f1["baseline"], 0.01), f1


def test_clean_data_raises_almost_nothing(ingested: IngestResult) -> None:
    with duckdb.connect(str(ingested.db_path), read_only=True) as con:
        assert len(SplitDetector().detect(con)) <= 3


def test_changing_the_configured_threshold_changes_the_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-2.6: the approval threshold is configuration, not a constant in the code."""
    rows = [{"amount": 150_000.0, "txn_date": DAY0 + timedelta(days=d)} for d in (0, 1, 2)]
    con = build_db(tmp_path / "t.duckdb", rows)
    assert SplitDetector(score_threshold=0.0).detect(con)  # 4.5L across three parts of 1.5L

    monkeypatch.setattr(settings, "approval_threshold", 500_000.0)
    assert SplitDetector(score_threshold=0.0).detect(con) == []  # now below the limit

    monkeypatch.setattr(settings, "approval_threshold", 140_000.0)
    assert SplitDetector(score_threshold=0.0).detect(con) == []  # now each part is above it
