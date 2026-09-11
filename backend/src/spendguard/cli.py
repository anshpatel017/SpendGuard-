"""SpendGuard command line.

spendguard generate                 synthetic INR dataset -> data/raw/
spendguard ingest <csv>             CSV -> DuckDB transactions + dataset card
spendguard check-policy             policy.md and config.py agree?
"""

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from spendguard.config import settings

# Windows consoles default to cp1252, which cannot encode the rupee sign and
# would crash every command that prints money. Force UTF-8 on our own output.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(
    help="SpendGuard - procurement anomaly detection and investigation.", no_args_is_help=True
)
console = Console()


@app.command()
def generate(
    rows: Annotated[int, typer.Option(help="Number of transactions.")] = 50_000,
    seed: Annotated[int, typer.Option(help="Random seed.")] = settings.random_seed,
    out: Annotated[Path | None, typer.Option(help="Output CSV path.")] = None,
) -> None:
    """Generate a seeded synthetic INR procurement dataset."""
    from spendguard.pipeline.synthetic import GeneratorConfig, default_output_path, generate, write

    config = GeneratorConfig(n_transactions=rows, seed=seed)
    with console.status(f"Generating {rows:,} transactions (seed {seed})..."):
        dataset = generate(config)
        csv_path, truth_path = write(dataset, out or default_output_path(config))

    r = dataset.report
    table = Table(title="Synthetic dataset", show_header=False)
    table.add_row("Rows", f"{r['rows']:,}")
    table.add_row("Vendors / officers", f"{r['vendors']:,} / {r['officers']:,}")
    table.add_row(
        "Recurring contracts", f"{r['recurring_contracts']} ({r['recurring_rows']:,} rows)"
    )
    table.add_row("Legitimate name variants", f"{r['legitimate_name_variants']:,}")
    table.add_row("Dirty rows (cleanable)", str(sum(r["dirty_rows"].values())))  # type: ignore[attr-defined]
    table.add_row("Malformed rows (droppable)", str(sum(r["malformed_rows"].values())))  # type: ignore[attr-defined]
    table.add_row(
        f"At or above {settings.money(settings.approval_threshold)}",
        f"{r['rows_above_approval_threshold']:,}",
    )
    table.add_row("Total value", settings.money(float(r["total_amount"])))  # type: ignore[arg-type]
    console.print(table)
    console.print(f"[green]Wrote[/green] {csv_path}")
    console.print(f"[green]Wrote[/green] {truth_path} [dim](ground truth - never ingested)[/dim]")


@app.command()
def ingest(
    source: Annotated[Path, typer.Argument(help="Source CSV file.", exists=True, dir_okay=False)],
    mapping: Annotated[str, typer.Option(help="Mapping name or YAML path.")] = "synthetic_inr",
    db: Annotated[Path | None, typer.Option(help="DuckDB path.")] = None,
) -> None:
    """Ingest a CSV into the DuckDB transactions table."""
    from spendguard.pipeline.ingest import ingest as run_ingest
    from spendguard.pipeline.mapping import load_mapping

    with console.status(f"Ingesting {source.name}..."):
        result = run_ingest(source, load_mapping(mapping), db_path=db)

    table = Table(title=f"Ingested {result.dataset}", show_header=False)
    table.add_row("Rows read", f"{result.rows_read:,}")
    table.add_row("Rows loaded", f"[green]{result.rows_loaded:,}[/green]")
    table.add_row("Rows dropped", f"{result.rows_dropped:,}")
    for reason, count in result.dropped.items():
        if count:
            table.add_row(f"  {reason}", f"{count:,}")
    for name, count in result.coerced_to_null.items():
        if count:
            table.add_row(f"Coerced to null: {name}", f"{count:,}")
    entities = result.card["entities"]
    assert isinstance(entities, dict)
    table.add_row(
        "Vendor names -> keys",
        f"{entities['distinct_vendor_names']:,} -> {entities['distinct_vendor_keys']:,}",
    )
    table.add_row("Time", f"{result.duration_seconds:.2f}s")
    console.print(table)
    console.print(f"[green]DuckDB[/green]  {result.db_path}")
    for path in result.card_paths:
        console.print(f"[green]Card[/green]    {path}")


@app.command("check-policy")
def check_policy() -> None:
    """Verify policy/policy.md and config.py state the same thresholds."""
    from spendguard.policy_check import find_disagreements

    problems = find_disagreements()
    if problems:
        for p in problems:
            console.print(f"[red]x[/red] {p}")
        raise typer.Exit(code=1)
    console.print("[green]Policy and configuration agree.[/green]")


if __name__ == "__main__":
    app()
