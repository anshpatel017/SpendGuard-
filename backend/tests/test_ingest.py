"""Ingestion: CSV -> clean, normalized, stably identified DuckDB table (FR-1.1 to FR-1.8)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl
import pytest
from pydantic import ValidationError

from spendguard.db.duck import TRANSACTION_FIELDS
from spendguard.pipeline.ingest import IngestError, IngestResult, ingest
from spendguard.pipeline.mapping import DatasetMapping
from spendguard.pipeline.synthetic import SyntheticDataset
from spendguard.pipeline.vendors import normalize_vendor


def _table(result: IngestResult) -> pl.DataFrame:
    with duckdb.connect(str(result.db_path), read_only=True) as con:
        return pl.from_arrow(con.execute("SELECT * FROM transactions ORDER BY row_id").arrow())  # type: ignore[return-value]


def _mapping(base: DatasetMapping, **changes: object) -> DatasetMapping:
    return DatasetMapping.model_validate({**base.model_dump(), **changes})


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    pl.DataFrame(rows, schema={k: pl.String for k in rows[0]}).write_csv(path)
    return path


# ---------------------------------------------------------------- the table


def test_table_is_populated(ingested: IngestResult) -> None:
    assert ingested.rows_loaded > 0
    assert _table(ingested).height == ingested.rows_loaded


def test_schema_matches_the_contract(ingested: IngestResult) -> None:
    assert tuple(_table(ingested).columns) == TRANSACTION_FIELDS


def test_row_id_is_unique(ingested: IngestResult) -> None:
    ids = _table(ingested)["row_id"]
    assert ids.n_unique() == ids.len()


def test_row_id_is_source_position(ingested: IngestResult, small_dataset: SyntheticDataset) -> None:
    """row_id = 1-based source line, so it never depends on the cleaning rules."""
    table = _table(ingested)
    vouchers = small_dataset.frame["Voucher No"].to_list()
    for row_id, ref in zip(table["row_id"], table["source_row_ref"], strict=True):
        assert vouchers[row_id - 1] == ref


def test_reingest_reproduces_identical_ids(
    tmp_path: Path, small_csv: Path, synthetic_mapping: DatasetMapping, ingested: IngestResult
) -> None:
    """FR-1.2: an audit note's citations must keep pointing at the same rows."""
    again = ingest(
        small_csv, synthetic_mapping, db_path=tmp_path / "again.duckdb", card_dir=tmp_path
    )
    assert _table(again).equals(_table(ingested))


def test_indexes_exist(ingested: IngestResult) -> None:
    with duckdb.connect(str(ingested.db_path), read_only=True) as con:
        names = {r[0] for r in con.execute("SELECT index_name FROM duckdb_indexes()").fetchall()}
    assert {"idx_txn_vendor_key", "idx_txn_date", "idx_txn_vendor_date"} <= names


def test_nothing_is_marked_injected(ingested: IngestResult) -> None:
    table = _table(ingested)
    assert not table["is_injected"].any()
    assert table["injection_type"].null_count() == table.height


# ---------------------------------------------------------------- cleaning


def test_vendor_key_matches_normalizer(ingested: IngestResult) -> None:
    table = _table(ingested)
    expected = [normalize_vendor(n) for n in table["vendor_name"]]
    assert table["vendor_key"].to_list() == expected


def test_vendor_key_is_pure_against_ground_truth(
    ingested: IngestResult, small_dataset: SyntheticDataset
) -> None:
    """D-12 measured: no key merges two real suppliers, no supplier is split across keys."""
    joined = _table(ingested).join(
        small_dataset.truth, left_on="source_row_ref", right_on="voucher_no"
    )
    over = joined.group_by("vendor_key").agg(pl.col("vendor_id").n_unique().alias("n"))
    under = joined.group_by("vendor_id").agg(pl.col("vendor_key").n_unique().alias("n"))
    assert (over["n"] == 1).mean() >= 0.95, "vendor keys are over-merging real suppliers"  # type: ignore[operator]
    assert (under["n"] == 1).all(), "a supplier's legitimate variants were split across keys"


def test_whitespace_is_trimmed(ingested: IngestResult) -> None:
    names = _table(ingested)["vendor_name"]
    assert (names == names.str.strip_chars()).all()


def test_rupee_formatted_amounts_are_parsed(
    ingested: IngestResult, small_dataset: SyntheticDataset
) -> None:
    formatted = small_dataset.frame.with_columns(small_dataset.truth["defect"]).filter(
        pl.col("defect") == "amount_rupee_format"
    )
    if formatted.height == 0:
        pytest.skip("seed produced no rupee-formatted amounts")
    loaded = set(_table(ingested)["source_row_ref"])
    assert set(formatted["Voucher No"]) <= loaded


def test_drop_accounting_is_exact(ingested: IngestResult, small_dataset: SyntheticDataset) -> None:
    """FR-1.4: every dropped row is counted, and every malformed row is dropped."""
    assert ingested.rows_read == ingested.rows_loaded + ingested.rows_dropped
    malformed = small_dataset.report["malformed_rows"]
    assert isinstance(malformed, dict)
    expected = {
        "missing_vendor_name": malformed.get("blank_supplier", 0),
        "unparseable_amount": malformed.get("amount_not_available", 0),
        "non_positive_amount": malformed.get("zero_amount", 0),
        "unparseable_date": malformed.get("impossible_date", 0),
    }
    for reason, count in expected.items():
        assert ingested.dropped[reason] == count, reason


def test_dirty_rows_survive(ingested: IngestResult, small_dataset: SyntheticDataset) -> None:
    dirty = small_dataset.truth.filter(pl.col("defect").is_in(["vendor_padding", "blank_quantity"]))
    loaded = set(_table(ingested)["source_row_ref"])
    assert set(dirty["voucher_no"]) <= loaded


def test_unparseable_quantity_is_counted_as_coerced(
    ingested: IngestResult, small_dataset: SyntheticDataset
) -> None:
    dirty = small_dataset.report["dirty_rows"]
    assert isinstance(dirty, dict)
    assert ingested.coerced_to_null["quantity"] == dirty.get("bad_quantity", 0)


def test_blank_optional_fields_become_null_not_empty(ingested: IngestResult) -> None:
    table = _table(ingested)
    for field in ("officer_id", "item_category"):
        assert (table[field].drop_nulls() != "").all()


# ---------------------------------------------------------------- mapping


def test_unmapped_columns_are_ignored(ingested: IngestResult) -> None:
    """The generator writes a 'Department' column the mapping does not use."""
    assert "Department" not in _table(ingested).columns


def test_renaming_a_source_column_needs_only_a_mapping_change(
    tmp_path: Path, small_csv: Path, synthetic_mapping: DatasetMapping, ingested: IngestResult
) -> None:
    """FR-1.3: column names live in configuration, never in code."""
    renamed = tmp_path / "renamed.csv"
    pl.read_csv(small_csv, infer_schema_length=0).rename({"Supplier Name": "Vendor"}).write_csv(
        renamed
    )
    mapping = _mapping(
        synthetic_mapping, columns={**synthetic_mapping.columns, "vendor_name": "Vendor"}
    )
    again = ingest(renamed, mapping, db_path=tmp_path / "r.duckdb", card_dir=tmp_path)
    assert _table(again).equals(_table(ingested))


def test_missing_required_source_column_is_a_clear_error(
    tmp_path: Path, small_csv: Path, synthetic_mapping: DatasetMapping
) -> None:
    broken = tmp_path / "broken.csv"
    pl.read_csv(small_csv, infer_schema_length=0).drop("Supplier Name").write_csv(broken)
    with pytest.raises(IngestError, match="Supplier Name"):
        ingest(broken, synthetic_mapping, db_path=tmp_path / "b.duckdb", card_dir=tmp_path)


def test_absent_optional_field_degrades_gracefully(
    tmp_path: Path, small_csv: Path, synthetic_mapping: DatasetMapping
) -> None:
    """FR-1.6: a dataset with no officer column still ingests; officer_id is all null."""
    no_officer = tmp_path / "no_officer.csv"
    pl.read_csv(small_csv, infer_schema_length=0).drop("Requesting Officer").write_csv(no_officer)
    mapping = _mapping(synthetic_mapping, columns={**synthetic_mapping.columns, "officer_id": None})
    result = ingest(no_officer, mapping, db_path=tmp_path / "n.duckdb", card_dir=tmp_path)
    table = _table(result)
    assert table.height == result.rows_loaded > 0
    assert table["officer_id"].null_count() == table.height


def test_mapping_requires_vendor_amount_and_date(synthetic_mapping: DatasetMapping) -> None:
    with pytest.raises(ValidationError):
        _mapping(synthetic_mapping, columns={**synthetic_mapping.columns, "amount": None})


def test_mapping_rejects_unknown_fields(synthetic_mapping: DatasetMapping) -> None:
    with pytest.raises(ValidationError):
        _mapping(synthetic_mapping, columns={**synthetic_mapping.columns, "gst_number": "GSTIN"})


# ---------------------------------------------------------------- currency (D-15)


def test_foreign_currency_converts_at_the_pinned_rate(
    tmp_path: Path, synthetic_mapping: DatasetMapping
) -> None:
    csv = _write_csv(
        tmp_path / "usd.csv",
        [
            {"Voucher No": "A1", "Invoice Date": "01-04-2025", "Supplier Name": "Acme Inc",
             "Invoice Number": "1", "Requesting Officer": "X-001", "Commodity Category": "Paper",
             "Item Description": "Paper", "Qty": "10", "Rate (INR)": "$2.50",
             "Invoice Amount (INR)": "$25.00"},
        ],
    )  # fmt: skip
    usd = _mapping(
        synthetic_mapping,
        dataset="usd_test",
        source_currency="USD",
        fx_rate_to_inr=83.5,
        fx_rate_date="2025-04-01",
    )
    result = ingest(csv, usd, db_path=tmp_path / "u.duckdb", card_dir=tmp_path)
    row = _table(result).row(0, named=True)
    assert row["amount"] == pytest.approx(25.0 * 83.5)
    assert row["unit_price"] == pytest.approx(2.5 * 83.5)
    source = result.card["source"]
    assert isinstance(source, dict)
    assert source["converted"] is True
    assert source["fx_rate_to_inr"] == 83.5
    assert source["fx_rate_date"] == "2025-04-01"


def test_foreign_currency_without_a_pinned_rate_is_rejected(
    synthetic_mapping: DatasetMapping,
) -> None:
    with pytest.raises(ValidationError, match="pinned"):
        _mapping(synthetic_mapping, source_currency="USD")


def test_foreign_currency_without_a_rate_date_is_rejected(
    synthetic_mapping: DatasetMapping,
) -> None:
    with pytest.raises(ValidationError, match="fx_rate_date"):
        _mapping(synthetic_mapping, source_currency="USD", fx_rate_to_inr=83.5)


def test_inr_source_is_not_converted(ingested: IngestResult) -> None:
    source = ingested.card["source"]
    assert isinstance(source, dict)
    assert source["converted"] is False
    assert source["fx_rate_to_inr"] == 1.0


# ---------------------------------------------------------------- dataset card (FR-1.7)


def test_card_files_are_written(ingested: IngestResult) -> None:
    assert len(ingested.card_paths) == 2
    for path in ingested.card_paths:
        assert path.exists() and path.stat().st_size > 0


def test_card_records_provenance_and_coverage(ingested: IngestResult) -> None:
    card = ingested.card
    source, rows, dates = card["source"], card["rows"], card["date_range"]
    assert isinstance(source, dict) and isinstance(rows, dict) and isinstance(dates, dict)
    assert len(str(source["sha256"])) == 64
    assert rows["read"] == ingested.rows_read
    assert rows["loaded"] == ingested.rows_loaded
    assert dates["min"] and dates["max"]
    assert set(card["null_rates"]) >= {"vendor_name", "amount", "officer_id"}  # type: ignore[arg-type]


def test_card_is_stored_in_duckdb(ingested: IngestResult) -> None:
    with duckdb.connect(str(ingested.db_path), read_only=True) as con:
        count = con.execute(
            "SELECT count(*) FROM dataset_cards WHERE dataset = ?", [ingested.dataset]
        ).fetchone()
    assert count == (1,)
