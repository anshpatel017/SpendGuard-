"""Dataset card - what was ingested, from where, and how it was changed (FR-1.7).

Written as JSON (machine-readable, stored in DuckDB for the API) and Markdown
(for humans and the report). The source file's SHA-256 is recorded so any
result can be traced to the exact bytes it came from.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from spendguard import __version__
from spendguard.config import settings
from spendguard.db.duck import INJECTION_FIELDS, TRANSACTION_FIELDS

if TYPE_CHECKING:
    from spendguard.pipeline.ingest import IngestResult
    from spendguard.pipeline.mapping import DatasetMapping

AUDITED_FIELDS = tuple(f for f in TRANSACTION_FIELDS if f not in INJECTION_FIELDS)


def _collapse_groups(table: pl.DataFrame, limit: int = 8) -> list[dict[str, object]]:
    """Vendor keys that absorbed the most distinct raw spellings.

    This is vendor normalization made visible - and it is where any over-merging
    of genuinely different suppliers (decision D-12) shows up first.
    """
    groups = (
        table.group_by("vendor_key")
        .agg(
            pl.col("vendor_name").n_unique().alias("n_raw_names"),
            pl.col("vendor_name").unique().sort().head(6).alias("examples"),
            pl.len().alias("transactions"),
        )
        .filter(pl.col("n_raw_names") > 1)
        .sort(["n_raw_names", "transactions"], descending=True)
        .head(limit)
    )
    return groups.to_dicts()


def build_card(
    table: pl.DataFrame, mapping: DatasetMapping, result: IngestResult
) -> dict[str, object]:
    amounts = table.get_column("amount")
    dates = table.get_column("txn_date")
    n = max(table.height, 1)

    return {
        "dataset": mapping.dataset,
        "description": mapping.description.strip(),
        "spendguard_version": __version__,
        "ingested_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": {
            "file": result.source_path.name,
            "sha256": result.source_sha256,
            "currency": mapping.source_currency,
            "fx_rate_to_inr": mapping.fx_rate,
            "fx_rate_date": mapping.fx_rate_date.isoformat() if mapping.fx_rate_date else None,
            "converted": mapping.is_converted,
        },
        "reporting_currency": settings.currency,
        "rows": {
            "read": result.rows_read,
            "loaded": result.rows_loaded,
            "dropped": result.rows_dropped,
            "dropped_by_reason": {k: v for k, v in result.dropped.items() if v},
            "coerced_to_null": {k: v for k, v in result.coerced_to_null.items() if v},
        },
        "date_range": {
            "min": dates.min().isoformat() if table.height else None,  # type: ignore[union-attr]
            "max": dates.max().isoformat() if table.height else None,  # type: ignore[union-attr]
        },
        "amount": {
            "total": float(amounts.sum()),
            "min": float(amounts.min() or 0),  # type: ignore[arg-type]
            "median": float(amounts.median() or 0),  # type: ignore[arg-type]
            "p95": float(amounts.quantile(0.95) or 0),
            "max": float(amounts.max() or 0),  # type: ignore[arg-type]
            "at_or_above_approval_threshold": int((amounts >= settings.approval_threshold).sum()),
            "approval_threshold": settings.approval_threshold,
        },
        "entities": {
            "distinct_vendor_names": table.get_column("vendor_name").n_unique(),
            "distinct_vendor_keys": table.get_column("vendor_key").n_unique(),
            "distinct_officers": table.get_column("officer_id").drop_nulls().n_unique(),
            "distinct_categories": table.get_column("item_category").drop_nulls().n_unique(),
        },
        "vendor_collapse_groups": _collapse_groups(table),
        "null_rates": {f: round(table.get_column(f).null_count() / n, 4) for f in AUDITED_FIELDS},
        "mapping": {k: v for k, v in mapping.columns.items()},
    }


def render_markdown(card: dict[str, object]) -> str:
    rows = card["rows"]
    amount = card["amount"]
    source = card["source"]
    entities = card["entities"]
    assert isinstance(rows, dict) and isinstance(amount, dict)
    assert isinstance(source, dict) and isinstance(entities, dict)

    money = settings.money
    lines = [
        f"# Dataset card - `{card['dataset']}`",
        "",
        str(card["description"]),
        "",
        "## Source",
        "",
        "| | |",
        "|---|---|",
        f"| File | `{source['file']}` |",
        f"| SHA-256 | `{source['sha256']}` |",
        f"| Source currency | {source['currency']} |",
        f"| Conversion | {'pinned rate ' + str(source['fx_rate_to_inr']) + ' as of ' + str(source['fx_rate_date']) if source['converted'] else 'none - native INR'} |",
        f"| Ingested | {card['ingested_at']} (SpendGuard {card['spendguard_version']}) |",
        "",
        "## Rows",
        "",
        "| | Count |",
        "|---|---:|",
        f"| Read | {rows['read']:,} |",
        f"| Loaded | {rows['loaded']:,} |",
        f"| Dropped | {rows['dropped']:,} |",
    ]
    for reason, count in rows["dropped_by_reason"].items():
        lines.append(f"| &nbsp;&nbsp;{reason} | {count:,} |")
    for name, count in rows["coerced_to_null"].items():
        lines.append(f"| Coerced to null: {name} | {count:,} |")

    date_range = card["date_range"]
    assert isinstance(date_range, dict)
    lines += [
        "",
        "## Coverage",
        "",
        f"- **Date range:** {date_range['min']} to {date_range['max']}",
        f"- **Total value:** {money(float(amount['total']))}",
        f"- **Median / p95 / max transaction:** {money(float(amount['median']))} / "
        f"{money(float(amount['p95']))} / {money(float(amount['max']))}",
        f"- **At or above the {money(float(amount['approval_threshold']))} approval threshold:** "
        f"{amount['at_or_above_approval_threshold']:,} transactions",
        f"- **Vendors:** {entities['distinct_vendor_names']:,} raw names normalize to "
        f"{entities['distinct_vendor_keys']:,} vendor keys",
        f"- **Officers:** {entities['distinct_officers']:,} · "
        f"**Categories:** {entities['distinct_categories']:,}",
        "",
        "## Vendor normalization - largest collapse groups",
        "",
        "Each row is one `vendor_key` and the distinct raw spellings it absorbed. "
        "Review these for over-merging of genuinely different suppliers (decision D-12).",
        "",
        "| vendor_key | raw names | transactions | examples |",
        "|---|---:|---:|---|",
    ]
    groups = card["vendor_collapse_groups"]
    assert isinstance(groups, list)
    for g in groups:
        examples = "; ".join(f"`{e}`" for e in g["examples"])
        lines.append(
            f"| `{g['vendor_key']}` | {g['n_raw_names']} | {g['transactions']:,} | {examples} |"
        )

    null_rates = card["null_rates"]
    mapping = card["mapping"]
    assert isinstance(null_rates, dict) and isinstance(mapping, dict)
    lines += ["", "## Null rates", "", "| Field | Null rate |", "|---|---:|"]
    lines += [f"| `{k}` | {v:.2%} |" for k, v in null_rates.items()]
    lines += ["", "## Column mapping", "", "| Canonical field | Source column |", "|---|---|"]
    lines += [f"| `{k}` | {f'`{v}`' if v else '*(absent)*'} |" for k, v in mapping.items()]
    return "\n".join(lines) + "\n"


def write_card(card: dict[str, object], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{card['dataset']}.card.json"
    md_path = out_dir / f"{card['dataset']}.card.md"
    json_path.write_text(json.dumps(card, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(card), encoding="utf-8")
    return json_path, md_path
