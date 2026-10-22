"""The rule-based baseline (FR-2.10) - and the rule that detectors never see the answer key."""

from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path

import duckdb
import polars as pl
import pytest

from spendguard.cases import AnomalyType
from spendguard.config import settings
from spendguard.db.duck import HIDDEN_FROM_DETECTORS, TRANSACTION_FIELDS, write_transactions
from spendguard.detectors import REGISTRY, BaselineDetector, Detector
from spendguard.eval.injection import InjectionResult
from spendguard.eval.runner import run_evaluation

T = settings.approval_threshold


def _db(tmp_path: Path, rows: list[dict[str, object]]) -> duckdb.DuckDBPyConnection:
    defaults: dict[str, object] = {
        "invoice_no": None, "officer_id": "ADM-001", "item_desc": "Item", "item_category": "Cat",
        "quantity": 1.0, "unit_price": None, "source_dataset": "test", "source_row_ref": None,
        "is_injected": False, "injection_group_id": None, "injection_type": None,
    }  # fmt: skip
    full = []
    for i, r in enumerate(rows, 1):
        row = {**defaults, "row_id": i, "txn_date": date(2025, 4, 1), **r}
        row.setdefault("vendor_key", str(row["vendor_name"]).lower())
        if row["unit_price"] is None:
            row["unit_price"] = row["amount"]
        full.append(row)
    schema = {
        "row_id": pl.Int64, "vendor_name": pl.String, "vendor_key": pl.String,
        "invoice_no": pl.String, "amount": pl.Float64, "txn_date": pl.Date,
        "officer_id": pl.String, "item_desc": pl.String, "item_category": pl.String,
        "quantity": pl.Float64, "unit_price": pl.Float64, "source_dataset": pl.String,
        "source_row_ref": pl.String, "is_injected": pl.Boolean,
        "injection_group_id": pl.String, "injection_type": pl.String,
    }  # fmt: skip
    con = duckdb.connect(str(tmp_path / "b.duckdb"))
    write_transactions(con, pl.DataFrame(full, schema=schema).select(TRANSACTION_FIELDS))
    return con


def _of(cases: list, kind: AnomalyType) -> list:  # type: ignore[type-arg]
    return [c for c in cases if c.anomaly_type == kind]


def test_satisfies_the_detector_interface() -> None:
    assert isinstance(BaselineDetector(), Detector)
    assert REGISTRY["baseline"] is BaselineDetector


def test_empty_table_gives_no_cases(tmp_path: Path) -> None:
    con = _db(tmp_path, [])
    assert BaselineDetector().detect(con) == []


def test_exact_duplicate_is_caught(tmp_path: Path) -> None:
    con = _db(tmp_path, [
        {"vendor_name": "Sharma Traders", "invoice_no": "INV-1", "amount": 5000.0},
        {"vendor_name": "sharma traders ", "invoice_no": "INV-1", "amount": 5000.0},
    ])  # fmt: skip
    dups = _of(BaselineDetector().detect(con), AnomalyType.DUPLICATE)
    assert len(dups) == 1 and dups[0].row_ids == (1, 2)


def test_disguised_duplicate_is_missed(tmp_path: Path) -> None:
    """The gap the ML detector must close: a reformatted invoice number defeats exact match."""
    con = _db(tmp_path, [
        {"vendor_name": "Sharma Traders", "invoice_no": "INV-4471", "amount": 5000.0},
        {"vendor_name": "Sharma Traders", "invoice_no": "4471/2025", "amount": 5000.0},
    ])  # fmt: skip
    assert _of(BaselineDetector().detect(con), AnomalyType.DUPLICATE) == []


@pytest.mark.parametrize(
    ("amount", "flagged"),
    [(T * 0.89, False), (T * 0.90, True), (T * 0.99, True), (T, False), (T * 1.2, False)],
)
def test_near_threshold_band(tmp_path: Path, amount: float, flagged: bool) -> None:
    """'At or above' the threshold is not a split (policy SG-PP-3.2)."""
    con = _db(tmp_path, [{"vendor_name": "A", "amount": amount}])
    assert bool(_of(BaselineDetector().detect(con), AnomalyType.SPLIT)) is flagged


def test_inflation_above_twice_the_category_mean(tmp_path: Path) -> None:
    rows = [{"vendor_name": "A", "amount": 100.0, "unit_price": 100.0} for _ in range(9)]
    rows.append({"vendor_name": "B", "amount": 500.0, "unit_price": 500.0})  # mean 140 -> 3.6x
    cases = _of(BaselineDetector().detect(_db(tmp_path, rows)), AnomalyType.INFLATION)
    assert [c.row_ids for c in cases] == [(10,)]
    assert cases[0].amount_at_risk == pytest.approx(360.0)


def test_round_number_vendor(tmp_path: Path) -> None:
    rows = [{"vendor_name": "Round", "amount": 50_000.0} for _ in range(12)]
    rows += [{"vendor_name": "Natural", "amount": 48_237.55 + i} for i in range(12)]
    cases = _of(BaselineDetector().detect(_db(tmp_path, rows)), AnomalyType.VENDOR_FLAG)
    assert [c.vendor_key for c in cases] == ["round"]


def test_every_score_is_binary(injected: InjectionResult) -> None:
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        assert {c.detector_score for c in BaselineDetector().detect(con)} == {1.0}


def test_end_to_end_evaluation(tmp_path: Path, injected: InjectionResult) -> None:
    run = run_evaluation(injected.out_db, ["baseline"], report_dir=tmp_path)
    assert run.seed == 11
    assert all(p.exists() for p in run.report_paths)
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        stored = con.execute(
            "SELECT count(*) FROM eval_results WHERE run_id = ?", [run.run_id]
        ).fetchone()
    assert stored == (len(run.metrics),)


def test_a_run_records_the_thresholds_that_produced_its_numbers(
    tmp_path: Path, injected: InjectionResult
) -> None:
    """FR-7.10: parameters, seeds and results - not two of the three.

    `eval_results` carries a run's numbers and its seed. Without the thresholds
    in force at the time, re-running after a config change appends rows that are
    not comparable to the ones already there, and nothing says so.
    """
    from spendguard.config import DETECTOR_SETTINGS
    from spendguard.eval.runner import detector_config

    run = run_evaluation(injected.out_db, ["baseline"], report_dir=tmp_path)

    assert set(run.config) == set(DETECTOR_SETTINGS)
    assert run.config == detector_config(), "the run recorded settings it did not use"

    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        row = con.execute(
            "SELECT seed, transactions, detectors, config FROM eval_runs WHERE run_id = ?",
            [run.run_id],
        ).fetchone()
    assert row is not None, "the run was not logged to the tracker at all"
    seed, transactions, detectors, config_json = row
    assert seed == run.seed
    assert transactions == run.transactions
    assert detectors == "baseline"
    assert json.loads(config_json) == {
        k: str(v) if not isinstance(v, (int, float, bool, str, type(None))) else v
        for k, v in run.config.items()
    }


def test_the_recorded_thresholds_follow_the_settings_actually_in_force(
    tmp_path: Path, injected: InjectionResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A snapshot that always reports the defaults would record nothing useful."""
    from spendguard.config import settings as live
    from spendguard.eval.runner import detector_config

    monkeypatch.setattr(live, "split_window_days", 99, raising=False)
    assert detector_config()["split_window_days"] == 99

    run = run_evaluation(injected.out_db, ["baseline"], report_dir=tmp_path)
    assert run.config["split_window_days"] == 99


def test_unknown_detector_is_a_clear_error(injected: InjectionResult) -> None:
    with pytest.raises(KeyError, match="Unknown detector"):
        run_evaluation(injected.out_db, ["nonexistent"])


# ---------------------------------------------------------------- isolation


DETECTOR_SOURCES = sorted((Path(__file__).parents[1] / "src/spendguard/detectors").glob("*.py"))


@pytest.mark.parametrize("path", DETECTOR_SOURCES, ids=lambda p: p.name)
def test_detectors_never_mention_the_answer_key(path: Path) -> None:
    """Detectors may only see what an auditor sees. A string literal naming a
    hidden column, the ground-truth table or the raw table is a leak."""
    forbidden = HIDDEN_FROM_DETECTORS | {"ground_truth", "injection_runs"}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            leaked = [name for name in forbidden if name in text]
            assert not leaked, f"{path.name} references {leaked}"
            assert " FROM transactions" not in text, f"{path.name} reads the raw table"
