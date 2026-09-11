"""DuckDB - the analytical store (docs/DATA-SCHEMA.md section 1).

Written only by batch runs. The API opens it read-only, so a batch run and the
dashboard never contend for DuckDB's single write lock (decision D-09).

**Detectors read ``audit_transactions``, never ``transactions``.** The view
exposes only what a real auditor would see. The injection harness's answer key
(``is_injected`` and friends) and ingestion provenance (``source_row_ref``) are
not in it, so a detector cannot learn from them even by accident.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

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

# Never visible to a detector: the answer key, plus provenance fields that would
# leak it (injected rows have no source reference).
HIDDEN_FROM_DETECTORS: frozenset[str] = INJECTION_FIELDS | {"source_row_ref", "source_dataset"}

AUDIT_VIEW = "audit_transactions"
AUDIT_FIELDS: tuple[str, ...] = tuple(
    f for f in TRANSACTION_FIELDS if f not in HIDDEN_FROM_DETECTORS
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

# docs/DATA-SCHEMA.md 1.2. vendor_key supports vendor-level matching (decision D-03).
GROUND_TRUTH_DDL = """
CREATE OR REPLACE TABLE ground_truth (
    injection_group_id  VARCHAR PRIMARY KEY,
    injection_type      VARCHAR NOT NULL,
    row_ids             BIGINT[] NOT NULL,
    source_row_ids      BIGINT[],
    vendor_key          VARCHAR,
    amount_at_risk      DOUBLE NOT NULL,
    seed                INTEGER NOT NULL,
    params              JSON
)
"""

INJECTION_RUNS_DDL = """
CREATE OR REPLACE TABLE injection_runs (
    seed        INTEGER NOT NULL,
    created_at  TIMESTAMP NOT NULL,
    config      JSON NOT NULL,
    summary     JSON NOT NULL
)
"""

# docs/DATA-SCHEMA.md 1.4
EVAL_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS eval_results (
    run_id        VARCHAR NOT NULL,
    detector      VARCHAR NOT NULL,
    anomaly_type  VARCHAR NOT NULL,
    granularity   VARCHAR NOT NULL,
    precision     DOUBLE NOT NULL,
    recall        DOUBLE NOT NULL,
    f1            DOUBLE NOT NULL,
    pr_auc        DOUBLE,
    tp            INTEGER NOT NULL,
    fp            INTEGER NOT NULL,
    fn            INTEGER NOT NULL,
    seed          INTEGER,
    created_at    TIMESTAMP NOT NULL
)
"""


def transactions_ddl() -> str:
    body = ",\n    ".join(f"{name} {kind}" for name, kind in TRANSACTIONS_COLUMNS)
    return f"CREATE OR REPLACE TABLE transactions (\n    {body}\n)"


def audit_view_ddl() -> str:
    return (
        f"CREATE OR REPLACE VIEW {AUDIT_VIEW} AS SELECT {', '.join(AUDIT_FIELDS)} FROM transactions"
    )


def connect(db_path: Path | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the analytical store. Use ``read_only=True`` everywhere except batch writers."""
    path = db_path or settings.duckdb_path
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.exists():
        raise FileNotFoundError(f"No DuckDB database at {path}. Run `spendguard ingest` first.")
    return duckdb.connect(str(path), read_only=read_only)


def write_transactions(con: duckdb.DuckDBPyConnection, frame: pl.DataFrame) -> None:
    """Replace ``transactions`` with ``frame``, then rebuild indexes and the audit view."""
    missing = set(TRANSACTION_FIELDS) - set(frame.columns)
    if missing:
        raise ValueError(f"Frame is missing transaction fields: {sorted(missing)}")

    fields = ", ".join(TRANSACTION_FIELDS)
    arrow = frame.select(TRANSACTION_FIELDS).to_arrow(compat_level=pl.CompatLevel.oldest())
    con.execute(transactions_ddl())
    con.register("staged_transactions", arrow)
    try:
        con.execute(f"INSERT INTO transactions ({fields}) SELECT {fields} FROM staged_transactions")
    finally:
        con.unregister("staged_transactions")
    for statement in TRANSACTIONS_INDEXES:
        con.execute(statement)
    con.execute(audit_view_ddl())


def read_transactions(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    return con.execute(
        f"SELECT {', '.join(TRANSACTION_FIELDS)} FROM transactions ORDER BY row_id"
    ).pl()


def table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    row = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()
    return bool(row and row[0])
