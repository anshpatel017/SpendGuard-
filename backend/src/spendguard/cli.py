"""SpendGuard command line.

spendguard generate                 synthetic INR dataset -> data/raw/
spendguard ingest <csv>             CSV -> DuckDB transactions + dataset card
spendguard detect                   run the detectors, store cases for review
spendguard inject                   plant seeded anomalies in a copy of the database
spendguard evaluate                 score detectors against the planted anomalies
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


@app.command()
def detect(
    detector: Annotated[
        list[str] | None, typer.Option(help="Detector(s) to run. Repeatable. Default: all.")
    ] = None,
    db: Annotated[Path | None, typer.Option(help="DuckDB to scan. Default: the clean one.")] = None,
    reset: Annotated[bool, typer.Option(help="Clear the case store first.")] = False,
) -> None:
    """Scan 100% of transactions and store every case for review."""
    from collections import defaultdict

    from spendguard.cases import Case
    from spendguard.detection import run_detection

    with console.status("Scanning every transaction..."):
        run = run_detection(db, detector, reset=reset)

    if not run.cases:
        console.print(
            f"[green]No anomalies found[/green] in {run.transactions:,} transactions "
            f"({', '.join(f'{k} {v:.2f}s' for k, v in run.seconds.items())})."
        )
        return

    table = Table(title=f"Detection - {run.run_id} - {run.transactions:,} transactions")
    for col in ("Detector", "Anomaly", "Cases", "High", "Medium", "Low", "Amount at risk", "Time"):
        table.add_column(col, justify="left" if col in ("Detector", "Anomaly") else "right")
    grouped: dict[tuple[str, str], list[Case]] = defaultdict(list)
    for c in run.cases:
        grouped[(c.detector, c.anomaly_type.value)].append(c)
    for (name, kind), found in sorted(grouped.items()):
        bands = [c.severity_band for c in found]
        table.add_row(
            name,
            kind,
            f"{len(found):,}",
            str(bands.count("high")),
            str(bands.count("medium")),
            str(bands.count("low")),
            settings.money(sum(c.amount_at_risk for c in found)),
            f"{run.seconds[name]:.2f}s",
        )
    console.print(table)
    if run.saved:
        console.print(
            f"Case store: {run.saved.inserted:,} new, {run.saved.refreshed:,} refreshed "
            f"(review state kept), {run.saved.total_in_store:,} total"
        )


@app.command()
def inject(
    seed: Annotated[int, typer.Option(help="Random seed.")] = settings.random_seed,
    rate: Annotated[float, typer.Option(help="Anomaly groups per transaction.")] = 0.01,
    source: Annotated[Path | None, typer.Option(help="Clean DuckDB to copy from.")] = None,
    out: Annotated[Path | None, typer.Option(help="Injected DuckDB to write.")] = None,
) -> None:
    """Plant seeded, realistic anomalies in a copy of the clean database."""
    from spendguard.eval.injection import InjectionConfig
    from spendguard.eval.injection import inject as run_inject

    with console.status(f"Injecting anomalies (seed {seed}, rate {rate:.1%})..."):
        result = run_inject(source, out, InjectionConfig(seed=seed, rate=rate))

    table = Table(title=f"Injected - seed {result.seed}")
    for col in ("Anomaly", "Groups", "Rows", "Amount at risk"):
        table.add_column(col, justify="left" if col == "Anomaly" else "right")
    for kind, groups in result.groups.items():
        table.add_row(
            kind,
            str(groups),
            f"{result.rows_injected[kind]:,}",
            settings.money(result.amount_at_risk[kind]),
        )
    console.print(table)
    console.print(
        f"{result.rows_before:,} rows -> {result.rows_after:,} "
        f"({result.row_share:.2%} injected, {result.rows_deleted} split originals replaced)"
    )
    if result.shortfall:
        console.print(f"[yellow]Could not place:[/yellow] {result.shortfall}")
    console.print(f"[green]Wrote[/green] {result.out_db}")


@app.command()
def evaluate(
    detector: Annotated[
        list[str] | None, typer.Option(help="Detector(s) to score. Repeatable.")
    ] = None,
    seed: Annotated[
        int, typer.Option(help="Seed of the injected database.")
    ] = settings.random_seed,
    db: Annotated[Path | None, typer.Option(help="Injected DuckDB to evaluate.")] = None,
) -> None:
    """Score detectors against the planted anomalies."""
    from spendguard.eval.injection import default_injected_path
    from spendguard.eval.metrics import ALL
    from spendguard.eval.runner import run_evaluation

    path = db or default_injected_path(seed)
    if not path.exists():
        console.print(f"[red]No injected database at {path}.[/red] Run `spendguard inject` first.")
        raise typer.Exit(code=1)

    with console.status("Running detectors..."):
        run = run_evaluation(path, detector or ["baseline"])

    for granularity in ("case", "row"):
        table = Table(title=f"Per {granularity} - {run.run_id}")
        for col in ("Detector", "Anomaly", "Precision", "Recall", "F1", "PR-AUC", "TP", "FP", "FN"):
            table.add_column(col, justify="left" if col in ("Detector", "Anomaly") else "right")
        for m in run.metrics:
            if m.granularity != granularity:
                continue
            style = "bold" if m.anomaly_type == ALL else None
            table.add_row(
                m.detector,
                m.anomaly_type,
                f"{m.precision:.3f}",
                f"{m.recall:.3f}",
                f"{m.f1:.3f}",
                f"{m.pr_auc:.3f}" if m.pr_auc is not None else "-",
                f"{m.tp:,}",
                f"{m.fp:,}",
                f"{m.fn:,}",
                style=style,
            )
        console.print(table)
    for path_out in run.report_paths:
        console.print(f"[green]Report[/green] {path_out}")


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
