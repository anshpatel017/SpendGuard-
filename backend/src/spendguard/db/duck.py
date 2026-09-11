"""DuckDB - the analytical store (docs/DATA-SCHEMA.md section 1).

Written only by batch runs. The API opens it read-only, so a batch run and the
dashboard never contend for DuckDB's single write lock (decision D-09).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from spendguard.config import settings

# (column, type) in table order. This is the contract between ingestion and
# every detector, agent tool and the Verifier.
TRANSACTIONS_COLUMNS: tuple[tuple[str, str], ...] = (
    ("row_id", "BIGINT NOT NULL PRIMARY KEY"),  # what the agent cites
    ("vendor_name", "VARCHAR NOT NULL"),
    ("vendor_key", "VARCHAR NOT NULL"),
    ("invoice_no", "VARCHAR"),
    ("amount", "DOUBLE NOT NULL"),
    ("txn_date", "DATE NOT NULL"),
    ("officer_id", "VARCHAR"),
    ("item_desc", "VARCHAR"),
    ("item_category", "VARCHAR"),
    ("quantity", "DOUBLE"),
    ("unit_price", "DOUBLE"),
    ("source_dataset", "VARCHAR NOT NULL"),
    ("source_row_ref", "VARCHAR"),
    # Evaluation-only. Detectors must never read these (enforced by test).
    ("is_injected", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("injection_group_id", "VARCHAR"),
    ("injection_type", "VARCHAR"),
)

TRANSACTION_FIELDS: tuple[str, ...] = tuple(name for name, _ in TRANSACTIONS_COLUMNS)

INJECTION_FIELDS: frozenset[str] = frozenset(
    {"is_injected", "injection_group_id", "injection_type"}
)

TRANSACTIONS_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_txn_vendor_key ON transactions (vendor_key)",
    "CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions (txn_date)",
    "CREATE INDEX IF NOT EXISTS idx_txn_vendor_date ON transactions (vendor_key, txn_date)",
)

DATASET_CARDS_DDL = """
CREATE TABLE IF NOT EXISTS dataset_cards (
    dataset      VARCHAR PRIMARY KEY,
    ingested_at  TIMESTAMP NOT NULL,
    card         JSON NOT NULL
)
"""


def transactions_ddl() -> str:
    body = ",\n    ".join(f"{name} {kind}" for name, kind in TRANSACTIONS_COLUMNS)
    return f"CREATE OR REPLACE TABLE transactions (\n    {body}\n)"


def connect(db_path: Path | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the analytical store. Use ``read_only=True`` everywhere except batch writers."""
    path = db_path or settings.duckdb_path
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.exists():
        raise FileNotFoundError(f"No DuckDB database at {path}. Run `spendguard ingest` first.")
    return duckdb.connect(str(path), read_only=read_only)
