"""CSV -> clean, normalized, stably-identified DuckDB ``transactions`` table.

    read (all columns as text)
      -> assign row_id from source position
      -> map source headers onto canonical fields      (mapping file, never code)
      -> clean text, parse amounts / quantities / dates
      -> convert to INR at the pinned rate             (decision D-15)
      -> normalize vendor names                        (decision D-12)
      -> drop unusable rows, counting every reason     (FR-1.4)
      -> write DuckDB, build indexes, write dataset card

**On ``row_id``.** It is the 1-based position of the row in the source file,
assigned *before* any row is dropped. So it depends only on the file, never on
the cleaning rules: tightening a cleaning rule later removes rows but never
renumbers the ones that remain, and an audit note's citations never silently
start pointing at different transactions. Gaps in the sequence are expected.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from spendguard.config import settings
from spendguard.db.duck import (
    DATASET_CARDS_DDL,
    TRANSACTION_FIELDS,
    TRANSACTIONS_INDEXES,
    connect,
    transactions_ddl,
)
from spendguard.pipeline.dataset_card import build_card, write_card
from spendguard.pipeline.mapping import DatasetMapping
from spendguard.pipeline.vendors import normalize_vendor

TEXT_FIELDS: tuple[str, ...] = (
    "vendor_name",
    "invoice_no",
    "officer_id",
    "item_desc",
    "item_category",
)
NUMERIC_FIELDS: tuple[str, ...] = ("amount", "quantity", "unit_price")

# Currency markers, thousands separators and whitespace stripped before parsing.
_NUMBER_NOISE = r"(?i)rs\.?|inr|usd|₹|\$|,|\s"

# Evaluated in this order; a row is dropped for the first reason that applies.
DROP_REASONS: tuple[str, ...] = (
    "missing_vendor_name",
    "unparseable_amount",
    "non_positive_amount",
    "unparseable_date",
    "empty_vendor_key",
)


class IngestError(RuntimeError):
    """The source file cannot be ingested with the given mapping."""


@dataclass
class IngestResult:
    dataset: str
    source_path: Path
    source_sha256: str
    db_path: Path
    rows_read: int
    rows_loaded: int
    dropped: dict[str, int]
    coerced_to_null: dict[str, int]
    duration_seconds: float
    card: dict[str, object] = field(default_factory=dict)
    card_paths: tuple[Path, ...] = ()

    @property
    def rows_dropped(self) -> int:
        return sum(self.dropped.values())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_text(name: str) -> pl.Expr:
    """Trim whitespace; empty strings become explicit nulls."""
    trimmed = pl.col(name).str.strip_chars()
    return pl.when(trimmed == "").then(None).otherwise(trimmed).alias(name)


def _parse_number(name: str) -> pl.Expr:
    return (
        pl.col(name)
        .str.replace_all(_NUMBER_NOISE, "")
        .cast(pl.Float64, strict=False)
        .alias(f"{name}__num")
    )


def _parse_date(formats: list[str]) -> pl.Expr:
    attempts = [pl.col("txn_date").str.strptime(pl.Date, f, strict=False) for f in formats]
    return pl.coalesce(attempts).alias("txn_date__date")


def _read_source(source: Path, mapping: DatasetMapping) -> pl.DataFrame:
    raw = pl.read_csv(source, infer_schema_length=0, encoding="utf8-lossy")
    missing = [h for h in mapping.source_headers() if h not in raw.columns]
    if missing:
        raise IngestError(
            f"{source.name} is missing columns required by mapping {mapping.dataset!r}: {missing}. "
            f"Columns present: {raw.columns}"
        )

    selected = [pl.col("row_id").cast(pl.Int64)]
    for canonical, header in mapping.columns.items():
        selected.append(
            pl.col(header).alias(canonical) if header else pl.lit(None, pl.String).alias(canonical)
        )
    ref = (
        pl.col(mapping.source_row_ref)
        if mapping.source_row_ref
        else pl.col("row_id").cast(pl.String)
    )
    selected.append(ref.alias("source_row_ref"))

    return raw.with_row_index("row_id", offset=1).select(selected)


def _clean(frame: pl.DataFrame, mapping: DatasetMapping) -> pl.DataFrame:
    frame = frame.with_columns(
        [_clean_text(f) for f in (*TEXT_FIELDS, *NUMERIC_FIELDS, "txn_date")]
    )
    frame = frame.with_columns(
        [_parse_number(f) for f in NUMERIC_FIELDS] + [_parse_date(mapping.date_formats)]
    )

    rate = mapping.fx_rate
    names = frame.get_column("vendor_name").drop_nulls().unique().to_list()
    keys = pl.DataFrame(
        {"vendor_name": names, "vendor_key": [normalize_vendor(n) for n in names]},
        schema={"vendor_name": pl.String, "vendor_key": pl.String},
    )
    frame = frame.join(keys, on="vendor_name", how="left")

    reason = (
        pl.when(pl.col("vendor_name").is_null())
        .then(pl.lit("missing_vendor_name"))
        .when(pl.col("amount__num").is_null())
        .then(pl.lit("unparseable_amount"))
        .when(pl.col("amount__num") <= 0)
        .then(pl.lit("non_positive_amount"))
        .when(pl.col("txn_date__date").is_null())
        .then(pl.lit("unparseable_date"))
        .when(pl.col("vendor_key").is_null() | (pl.col("vendor_key") == ""))
        .then(pl.lit("empty_vendor_key"))
        .otherwise(None)
    )
    return frame.with_columns(
        reason.alias("drop_reason"),
        (pl.col("amount__num") * rate).alias("amount_inr"),
        (pl.col("unit_price__num") * rate).alias("unit_price_inr"),
    )


def _to_canonical(frame: pl.DataFrame, dataset: str) -> pl.DataFrame:
    return frame.select(
        pl.col("row_id"),
        pl.col("vendor_name"),
        pl.col("vendor_key"),
        pl.col("invoice_no"),
        pl.col("amount_inr").alias("amount"),
        pl.col("txn_date__date").alias("txn_date"),
        pl.col("officer_id"),
        pl.col("item_desc"),
        pl.col("item_category"),
        pl.col("quantity__num").alias("quantity"),
        pl.col("unit_price_inr").alias("unit_price"),
        pl.lit(dataset).alias("source_dataset"),
        pl.col("source_row_ref"),
        pl.lit(False).alias("is_injected"),
        pl.lit(None, pl.String).alias("injection_group_id"),
        pl.lit(None, pl.String).alias("injection_type"),
    ).sort("row_id")


def _write_duckdb(
    table: pl.DataFrame, db_path: Path, dataset: str, card: dict[str, object]
) -> None:
    import json

    arrow = table.to_arrow(compat_level=pl.CompatLevel.oldest())
    with connect(db_path) as con:
        con.execute(transactions_ddl())
        con.register("staged", arrow)
        con.execute(
            f"INSERT INTO transactions ({', '.join(TRANSACTION_FIELDS)}) "
            f"SELECT {', '.join(TRANSACTION_FIELDS)} FROM staged"
        )
        con.unregister("staged")
        for statement in TRANSACTIONS_INDEXES:
            con.execute(statement)
        con.execute(DATASET_CARDS_DDL)
        con.execute(
            "INSERT OR REPLACE INTO dataset_cards VALUES (?, ?, ?)",
            [dataset, datetime.now(UTC).replace(tzinfo=None), json.dumps(card, default=str)],
        )


def ingest(
    source: Path,
    mapping: DatasetMapping,
    db_path: Path | None = None,
    card_dir: Path | None = None,
) -> IngestResult:
    """Ingest one source CSV into a fresh ``transactions`` table.

    One DuckDB file holds one dataset: ingesting replaces the table. Use a
    different ``db_path`` to keep several datasets side by side.
    """
    started = time.perf_counter()
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source}")
    db_path = db_path or settings.duckdb_path
    card_dir = card_dir or settings.processed_data_dir

    staged = _clean(_read_source(source, mapping), mapping)

    rejected = staged.filter(pl.col("drop_reason").is_not_null())
    dropped = {
        reason: int(rejected.filter(pl.col("drop_reason") == reason).height)
        for reason in DROP_REASONS
    }
    kept = staged.filter(pl.col("drop_reason").is_null())

    # Values that were present but unparseable, and so were stored as null.
    coerced = {
        name: int(kept.filter(pl.col(name).is_not_null() & pl.col(f"{name}__num").is_null()).height)
        for name in ("quantity", "unit_price")
    }

    table = _to_canonical(kept, mapping.dataset)
    source_sha256 = _sha256(source)

    result = IngestResult(
        dataset=mapping.dataset,
        source_path=source,
        source_sha256=source_sha256,
        db_path=db_path,
        rows_read=staged.height,
        rows_loaded=table.height,
        dropped=dropped,
        coerced_to_null=coerced,
        duration_seconds=0.0,
    )

    card = build_card(table, mapping, result)
    _write_duckdb(table, db_path, mapping.dataset, card)
    result.card = card
    result.card_paths = write_card(card, card_dir)
    result.duration_seconds = round(time.perf_counter() - started, 3)
    return result
