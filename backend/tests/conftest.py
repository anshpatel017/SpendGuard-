"""Shared fixtures. Generated data is session-scoped: built once, reused by every test."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import polars as pl
import pytest

from spendguard.db.duck import TRANSACTION_FIELDS, write_transactions
from spendguard.eval.injection import InjectionConfig, InjectionResult, inject
from spendguard.pipeline.ingest import IngestResult, ingest
from spendguard.pipeline.mapping import DatasetMapping, load_mapping
from spendguard.pipeline.synthetic import GeneratorConfig, SyntheticDataset, generate, write
from spendguard.pipeline.vendors import normalize_vendor

_SCHEMA = {
    "row_id": pl.Int64, "vendor_name": pl.String, "vendor_key": pl.String,
    "invoice_no": pl.String, "amount": pl.Float64, "txn_date": pl.Date,
    "officer_id": pl.String, "item_desc": pl.String, "item_category": pl.String,
    "quantity": pl.Float64, "unit_price": pl.Float64, "source_dataset": pl.String,
    "source_row_ref": pl.String, "is_injected": pl.Boolean,
    "injection_group_id": pl.String, "injection_type": pl.String,
}  # fmt: skip


def build_db(path: Path, rows: list[dict[str, object]]) -> duckdb.DuckDBPyConnection:
    """A transactions table from hand-written rows; unspecified fields get plain defaults."""
    full = []
    for i, r in enumerate(rows, 1):
        row: dict[str, object] = {
            "row_id": i, "vendor_name": "Sharma Traders", "invoice_no": f"INV-{i:05d}",
            "amount": 5000.0, "txn_date": date(2025, 4, 1), "officer_id": "ADM-001",
            "item_desc": "Paper", "item_category": "Paper", "quantity": 10.0, "unit_price": 500.0,
            "source_dataset": "test", "source_row_ref": None, "is_injected": False,
            "injection_group_id": None, "injection_type": None, **r,
        }  # fmt: skip
        row.setdefault("vendor_key", normalize_vendor(str(row["vendor_name"])))
        full.append(row)
    con = duckdb.connect(str(path))
    write_transactions(con, pl.DataFrame(full, schema=_SCHEMA).select(TRANSACTION_FIELDS))
    return con


SMALL = GeneratorConfig(n_transactions=3_000, seed=7)


@pytest.fixture(scope="session")
def small_dataset() -> SyntheticDataset:
    return generate(SMALL)


@pytest.fixture(scope="session")
def small_csv(tmp_path_factory: pytest.TempPathFactory, small_dataset: SyntheticDataset) -> Path:
    csv_path, _ = write(small_dataset, tmp_path_factory.mktemp("raw") / "small.csv")
    return csv_path


@pytest.fixture(scope="session")
def synthetic_mapping() -> DatasetMapping:
    return load_mapping("synthetic_inr")


@pytest.fixture(scope="session")
def ingested(
    tmp_path_factory: pytest.TempPathFactory, small_csv: Path, synthetic_mapping: DatasetMapping
) -> IngestResult:
    out = tmp_path_factory.mktemp("db")
    return ingest(small_csv, synthetic_mapping, db_path=out / "t.duckdb", card_dir=out)


# A higher rate than the default so a 3,000-row dataset still gets every anomaly type.
INJECTION = InjectionConfig(seed=11, rate=0.02)


@pytest.fixture(scope="session")
def injected(tmp_path_factory: pytest.TempPathFactory, ingested: IngestResult) -> InjectionResult:
    out = tmp_path_factory.mktemp("injected") / "injected.duckdb"
    return inject(ingested.db_path, out, INJECTION)
