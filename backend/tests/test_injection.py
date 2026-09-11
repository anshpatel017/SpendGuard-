"""The anomaly-injection harness (FR-7.1, FR-7.2, docs/EVALUATION.md section 2)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import polars as pl
import pytest

from spendguard.cases import AnomalyType
from spendguard.config import settings
from spendguard.db.duck import AUDIT_FIELDS, AUDIT_VIEW, HIDDEN_FROM_DETECTORS
from spendguard.eval.injection import (
    InjectionConfig,
    InjectionResult,
    TruthRecord,
    _bump_invoice,
    inject,
)
from spendguard.pipeline.ingest import IngestResult

from .conftest import INJECTION


def _frame(db: Path, sql: str = "SELECT * FROM transactions ORDER BY row_id") -> pl.DataFrame:
    with duckdb.connect(str(db), read_only=True) as con:
        return con.execute(sql).pl()


def _records(result: InjectionResult, kind: AnomalyType) -> list[TruthRecord]:
    return [r for r in result.records if r.injection_type == kind]


def _rows(result: InjectionResult, ids: list[int]) -> pl.DataFrame:
    return _frame(result.out_db).filter(pl.col("row_id").is_in(ids)).sort("row_id")


# ---------------------------------------------------------------- the whole run


def test_every_anomaly_type_is_injected(injected: InjectionResult) -> None:
    for kind in AnomalyType:
        assert injected.groups[kind.value] > 0, kind
    assert not injected.shortfall


def test_same_seed_is_identical(
    tmp_path: Path, ingested: IngestResult, injected: InjectionResult
) -> None:
    again = inject(ingested.db_path, tmp_path / "again.duckdb", INJECTION)
    assert _frame(again.out_db).equals(_frame(injected.out_db))
    truth = "SELECT * EXCLUDE (params) FROM ground_truth ORDER BY injection_group_id"
    assert _frame(again.out_db, truth).equals(_frame(injected.out_db, truth))


def test_different_seed_differs(
    tmp_path: Path, ingested: IngestResult, injected: InjectionResult
) -> None:
    other = inject(ingested.db_path, tmp_path / "other.duckdb", InjectionConfig(seed=12, rate=0.02))
    assert not _frame(other.out_db).equals(_frame(injected.out_db))


def test_clean_source_is_never_modified(ingested: IngestResult, injected: InjectionResult) -> None:
    clean = _frame(ingested.db_path)
    assert not clean["is_injected"].any()
    assert clean.height == ingested.rows_loaded


def test_refuses_to_inject_into_its_own_source(ingested: IngestResult) -> None:
    with pytest.raises(ValueError, match="clean source"):
        inject(ingested.db_path, ingested.db_path, INJECTION)


def test_refuses_an_already_injected_source(tmp_path: Path, injected: InjectionResult) -> None:
    with pytest.raises(ValueError, match="already contains injected"):
        inject(injected.out_db, tmp_path / "twice.duckdb", INJECTION)


def test_injection_rate_matches_configuration(injected: InjectionResult) -> None:
    placed = sum(v for k, v in injected.groups.items() if k != AnomalyType.VENDOR_FLAG.value)
    expected = round(injected.rows_before * INJECTION.rate)
    assert abs(placed - expected) <= 2


# ---------------------------------------------------------------- ground truth


def test_ground_truth_rows_exist_and_are_marked(injected: InjectionResult) -> None:
    table = _frame(injected.out_db)
    present = set(table["row_id"])
    injected_ids = set(table.filter(pl.col("is_injected"))["row_id"])
    for r in injected.records:
        assert set(r.row_ids) <= present, r.injection_group_id
        # Every injected row is recorded; the duplicate *original* is real, so not marked.
        marked = set(r.row_ids) - set(
            r.source_row_ids if r.injection_type == AnomalyType.DUPLICATE else []
        )
        assert marked <= injected_ids, r.injection_group_id


def test_a_row_belongs_to_at_most_one_group(injected: InjectionResult) -> None:
    seen: set[int] = set()
    for r in injected.records:
        assert not (seen & set(r.row_ids)), r.injection_group_id
        seen |= set(r.row_ids)


def test_ground_truth_table_matches_result(injected: InjectionResult) -> None:
    truth = _frame(injected.out_db, "SELECT * FROM ground_truth")
    assert truth.height == len(injected.records)
    assert (truth["seed"] == INJECTION.seed).all()


def test_injected_rows_are_traceable_to_their_source(injected: InjectionResult) -> None:
    """FR-7.2: the harness itself is auditable."""
    for kind in (AnomalyType.DUPLICATE, AnomalyType.SPLIT, AnomalyType.INFLATION):
        for r in _records(injected, kind):
            assert r.source_row_ids, r.injection_group_id


# ---------------------------------------------------------------- duplicates


def test_duplicates_keep_amount_officer_and_item(injected: InjectionResult) -> None:
    for r in _records(injected, AnomalyType.DUPLICATE):
        rows = _rows(injected, r.row_ids)
        for field in ("amount", "officer_id", "item_category", "quantity"):
            assert rows[field].n_unique() == 1, (r.injection_group_id, field)


def test_duplicates_stay_inside_the_policy_window(injected: InjectionResult) -> None:
    for r in _records(injected, AnomalyType.DUPLICATE):
        dates = _rows(injected, r.row_ids)["txn_date"]
        span = (dates.max() - dates.min()).days  # type: ignore[operator]
        assert 1 <= span <= settings.duplicate_date_window_days, r.injection_group_id


def test_duplicates_use_every_disguise(injected: InjectionResult) -> None:
    modes = {
        p["name_mode"]
        for r in _records(injected, AnomalyType.DUPLICATE)
        for p in r.params["perturbations"]
    }  # type: ignore[union-attr]
    assert modes == {"exact", "variant", "typo"}


# ---------------------------------------------------------------- splits


def test_split_parts_are_each_below_threshold_and_sum_to_original(
    injected: InjectionResult,
) -> None:
    for r in _records(injected, AnomalyType.SPLIT):
        rows = _rows(injected, r.row_ids)
        assert (rows["amount"] < settings.approval_threshold).all(), r.injection_group_id
        assert rows["amount"].sum() == pytest.approx(r.params["original_amount"], abs=0.01)
        assert r.amount_at_risk >= settings.approval_threshold


def test_split_parts_share_supplier_and_officer(injected: InjectionResult) -> None:
    for r in _records(injected, AnomalyType.SPLIT):
        rows = _rows(injected, r.row_ids)
        assert INJECTION.split_min_parts <= rows.height <= INJECTION.split_max_parts
        assert rows["vendor_key"].n_unique() == 1
        assert rows["officer_id"].n_unique() == 1


def test_split_parts_fall_inside_the_policy_window(injected: InjectionResult) -> None:
    for r in _records(injected, AnomalyType.SPLIT):
        dates = _rows(injected, r.row_ids)["txn_date"]
        assert (dates.max() - dates.min()).days <= settings.split_window_days  # type: ignore[operator]


def test_split_originals_are_replaced(injected: InjectionResult) -> None:
    present = set(_frame(injected.out_db)["row_id"])
    for r in _records(injected, AnomalyType.SPLIT):
        assert not set(r.source_row_ids) & present


def test_split_invoice_numbers_run_in_sequence() -> None:
    assert _bump_invoice("INV-00123", 2) == "INV-00125"
    assert _bump_invoice("ST/24-25/009", 1) == "ST/24-25/010"
    assert _bump_invoice("BILL", 1) == "BILL-1"
    assert _bump_invoice(None, 1) is None


# ---------------------------------------------------------------- inflation


def test_inflation_factor_is_in_range(injected: InjectionResult) -> None:
    for r in _records(injected, AnomalyType.INFLATION):
        factor = r.params["factor"]
        assert isinstance(factor, float)
        assert INJECTION.inflation_min_factor <= factor <= INJECTION.inflation_max_factor
        row = _rows(injected, r.row_ids).row(0, named=True)
        assert row["unit_price"] == pytest.approx(
            r.params["original_unit_price"] * factor, rel=1e-3
        )
        assert row["amount"] == pytest.approx(row["quantity"] * row["unit_price"], abs=0.01)


def test_inflation_respects_the_per_category_cap(injected: InjectionResult) -> None:
    """So planted outliers cannot drag the median they are measured against."""
    table = _frame(injected.out_db)
    sizes = dict(table.group_by("item_category").len().iter_rows())
    per_category: dict[str, int] = {}
    for r in _records(injected, AnomalyType.INFLATION):
        cat = str(r.params["category"])
        per_category[cat] = per_category.get(cat, 0) + 1
    for cat, count in per_category.items():
        assert count <= max(1, int(INJECTION.inflation_category_cap * sizes[cat]) + 1), cat


# ---------------------------------------------------------------- vendor flags


def test_synthetic_vendors_are_new_round_heavy_and_benford_testable(
    ingested: IngestResult, injected: InjectionResult
) -> None:
    clean_keys = set(_frame(ingested.db_path)["vendor_key"])
    for r in _records(injected, AnomalyType.VENDOR_FLAG):
        assert r.vendor_key not in clean_keys
        rows = _rows(injected, r.row_ids)
        assert rows.height >= settings.benford_min_transactions
        assert (rows["amount"] % 5_000 == 0).mean() >= 0.6  # type: ignore[operator]
        onboarded = date.fromisoformat(str(r.params["onboarded"]))
        assert rows["txn_date"].min() >= onboarded  # type: ignore[operator]


# ---------------------------------------------------------------- isolation


def test_audit_view_hides_the_answer_key(injected: InjectionResult) -> None:
    view = _frame(injected.out_db, f"SELECT * FROM {AUDIT_VIEW} LIMIT 1")
    assert tuple(view.columns) == AUDIT_FIELDS
    assert not set(view.columns) & HIDDEN_FROM_DETECTORS


@pytest.mark.parametrize(
    "bad",
    [
        {"rate": 0.0},
        {"rate": 0.2},
        {"duplicate_share": 0.5},
        {"duplicate_max_shift_days": 30},
        {"inflation_min_factor": 0.9},
    ],
)
def test_invalid_config_is_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        InjectionConfig(**bad)  # type: ignore[arg-type]
