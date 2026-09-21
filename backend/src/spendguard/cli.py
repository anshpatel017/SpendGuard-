"""SpendGuard command line.

spendguard generate                 synthetic INR dataset -> data/raw/
spendguard ingest <csv>             CSV -> DuckDB transactions + dataset card
spendguard detect                   run the detectors, store cases for review
spendguard inject                   plant seeded anomalies in a copy of the database
spendguard evaluate                 score detectors against the planted anomalies
spendguard investigate              the Investigator on the top-N cases (or --eval-seed)
spendguard serve                    the API and dashboard (or --eval-seed for an evaluation run)
spendguard openapi                  write the API schema the frontend's types are generated from
spendguard report detection         every seed, clean data, determinism -> docs/results/
spendguard check-llm                the LLM endpoint answers and can call tools?
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


@app.command()
def investigate(
    top: Annotated[int | None, typer.Option(help="How many cases, highest severity first.")] = None,
    anomaly_type: Annotated[
        str | None,
        typer.Option("--type", help="Only this type: duplicate, split, inflation, vendor_flag."),
    ] = None,
    case: Annotated[
        list[str] | None, typer.Option(help="Investigate these case ids. Repeatable.")
    ] = None,
    again: Annotated[bool, typer.Option(help="Include cases already investigated.")] = False,
    eval_seed: Annotated[
        int | None,
        typer.Option(help="Evaluation mode: sample cases from this injected database instead."),
    ] = None,
    per_type: Annotated[
        int, typer.Option(help="Evaluation mode: real and spurious cases per type.")
    ] = 2,
    verify: Annotated[
        bool | None,
        typer.Option(
            "--verify/--no-verify",
            help="Check every citation and regenerate failures. Default: VERIFIER_ENABLED.",
        ),
    ] = None,
) -> None:
    """Investigate prioritized cases and write verified, cited audit notes. Never closes a case."""
    from spendguard.agent.investigator import InvestigationResult
    from spendguard.agent.llm import LLMClient, LLMNotConfiguredError
    from spendguard.cases import Case
    from spendguard.investigation import evaluate_investigation, run_investigation

    try:
        llm = LLMClient()
    except LLMNotConfiguredError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    badge = {
        "verified": "[green]verified[/green]",
        "failed_after_retries": "[red]failed checks[/red]",
    }

    def progress(i: int, n: int, c: Case, r: InvestigationResult) -> None:
        verdict = r.verdict.value if r.verdict else f"[red]failed[/red] {(r.error or '')[:80]}"
        severity = (
            f"{c.severity_prelim:.1f} -> {r.severity_final:.1f} {r.severity_band}"
            if r.severity_final is not None
            else f"{c.severity_prelim:.1f}"
        )
        checked = ""
        if r.verification:
            v = r.verification
            checked = (
                f"  {badge.get(r.verification_status, r.verification_status)} "
                f"{v.deterministic_passed}/{v.checked} cited"
                + (f", {r.retry_count} retry" if r.retry_count else "")
            )
        console.print(
            f"[{i}/{n}] {c.anomaly_type.value:<11} {c.case_id[:8]}  {verdict:<22} "
            f"severity {severity}  {r.tool_calls} tools  {r.seconds:.0f}s{checked}"
        )

    console.print(f"Model: {llm.model} ({llm.provider.value})")
    if eval_seed is not None:
        from spendguard.eval.injection import default_injected_path

        if not default_injected_path(eval_seed).exists():
            console.print(f"[red]No injected database for seed {eval_seed}.[/red] Run inject.")
            raise typer.Exit(code=1)
        run = evaluate_investigation(
            eval_seed,
            per_type=per_type,
            include_investigated=again,
            llm=llm,
            on_result=progress,
            verify=verify,
        )
    else:
        run = run_investigation(
            top_n=top,
            anomaly_type=anomaly_type,
            case_ids=case,
            include_investigated=again,
            llm=llm,
            on_result=progress,
            verify=verify,
        )

    s = run.summary()
    if not s["cases"] and not run.sampled:
        console.print("[yellow]Nothing to investigate.[/yellow] Run `spendguard detect` first.")
        return
    console.print(
        f"\n{s['completed']}/{s['cases']} notes written - verdicts {s['verdicts']} - "
        f"{s['tool_calls']} tool calls, {s['prompt_tokens']:,} prompt tokens, "
        f"{s['seconds']:.0f}s ({s['rate_limit_wait_seconds']:.0f}s waiting on rate limits)"
    )

    def pct(value: object) -> str:
        return "-" if value is None else f"{value:.0%}"

    v = s["verification"]
    if v["citations_checked"]:
        console.print(
            f"Citations: {pct(v['deterministic_valid'])} exist and match "
            f"(first drafts {pct(v['first_draft_deterministic_valid'])}), "
            f"{pct(v['semantic_supported_model_judged'])} supported (model-judged) - "
            f"status {v['status']}, {v['regenerated']} regenerated"
        )
    if run.quota_stopped:
        console.print(
            f"[yellow]Stopped: the provider's daily quota ran out.[/yellow] {run.not_attempted} "
            "case(s) not attempted. Run the same command later; it continues where it stopped."
        )
    if run.sampled:
        console.print(f"Sample: {run.investigated_so_far} of {run.sampled} investigated so far.")
    if run.triage:
        table = Table(title=f"Triage - {run.run_id}")
        for col in ("Type", "Cases", "Real", "Real kept", "Wrongly dismissed", "Spurious filtered"):
            table.add_column(col, justify="left" if col == "Type" else "right")
        for kind, m in run.triage.items():
            table.add_row(
                kind,
                str(m["cases"]),
                str(m["real"]),
                pct(m["real_kept"]),
                pct(m["real_wrongly_dismissed"]),
                pct(m["spurious_filtered"]),
                style="bold" if kind == "all" else None,
            )
        console.print(table)
    for path_out in run.report_paths:
        console.print(f"[green]Report[/green] {path_out}")


def _eval_stores(seed: int) -> tuple[Path, str]:
    from spendguard.eval.injection import default_injected_path

    db = default_injected_path(seed)
    store = settings.processed_data_dir / "eval" / f"investigation_seed{seed}.sqlite"
    if not db.exists() or not store.exists():
        console.print(
            f"[red]No evaluation stores for seed {seed}.[/red] Run `spendguard inject --seed "
            f"{seed}` and `spendguard investigate --eval-seed {seed}` first."
        )
        raise typer.Exit(code=1)
    return db, f"sqlite:///{store.as_posix()}"


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Interface to listen on.")] = settings.api_host,
    port: Annotated[int, typer.Option(help="Port.")] = settings.api_port,
    eval_seed: Annotated[
        int | None,
        typer.Option(help="Show an evaluation run's stores (planted anomalies) instead."),
    ] = None,
) -> None:
    """Serve the API, and the dashboard if it has been built (frontend/dist)."""
    import uvicorn

    from spendguard.api import create_app

    db, url = _eval_stores(eval_seed) if eval_seed is not None else (settings.duckdb_path, None)
    app_ = create_app(duckdb_path=db, database_url=url)
    built = (settings.frontend_dist / "index.html").exists()
    console.print(f"Data: {db.name}" + (" (evaluation, planted anomalies)" if eval_seed else ""))
    console.print(f"API:  http://{host}:{port}/api/v1  ·  docs http://{host}:{port}/docs")
    if built:
        console.print(f"[green]Dashboard[/green] http://{host}:{port}/")
    else:
        console.print(
            "[yellow]Dashboard not built.[/yellow] `cd frontend && npm run build`, or run "
            "`npm run dev` there for the development server."
        )
    uvicorn.run(app_, host=host, port=port, log_level=settings.log_level.lower())


@app.command()
def openapi(
    out: Annotated[Path, typer.Option(help="Where to write the schema.")] = (
        settings.project_root / "frontend" / "openapi.json"
    ),
) -> None:
    """Write the OpenAPI schema. The frontend generates its types from it (API-CONTRACT §4)."""
    import json

    from spendguard.api import create_app

    schema = create_app().openapi()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    console.print(f"[green]Wrote[/green] {out} ({len(schema['paths'])} paths)")


report_app = typer.Typer(help="Regenerate the result tables in docs/results/ (Phase 9).")
app.add_typer(report_app, name="report")


@report_app.command("detection")
def report_detection(
    seed: Annotated[
        list[int] | None,
        typer.Option(help="Seeds to report. Repeatable. Default: EVALUATION_SEEDS."),
    ] = None,
) -> None:
    """Every detector on every seed, the clean-data check and a determinism check."""
    from spendguard.eval.report import detection_report

    seeds = seed or settings.evaluation_seeds
    with console.status(f"Evaluating seeds {', '.join(map(str, seeds))} (about 25 s each)..."):
        report = detection_report(seeds)

    table = Table(title=f"Detection - seeds {', '.join(map(str, report.seeds))}, per case")
    for col in ("Anomaly", "Detector", "Precision", "Recall", "F1", "PR-AUC"):
        table.add_column(col, justify="left" if col in ("Anomaly", "Detector") else "right")
    for r in report.rows:
        if r.granularity == "case":
            table.add_row(
                r.anomaly_type, r.detector, r.precision.text(), r.recall.text(), r.f1.text(),
                r.pr_auc.text() if r.pr_auc else "-",
                style=None if r.detector == "baseline" else "bold",
            )  # fmt: skip
    console.print(table)
    clean = ", ".join(f"{k.upper()} {v}" for k, v in report.clean.cases.items())
    console.print(f"Clean data ({report.clean.transactions:,} rows): cases {clean}")
    verdict = "[green]identical[/green]" if report.reproduced else "[red]DIFFERENT[/red]"
    console.print(f"Seed {report.seeds[0]} detected again: {verdict}")
    dirty = report.manifest["dirty"]
    console.print(
        f"Commit {report.manifest['commit']}"
        + (" [yellow](uncommitted changes: commit, then re-run for a clean record)[/yellow]"
           if dirty else "")
    )  # fmt: skip
    for path in report.paths:
        console.print(f"[green]Wrote[/green] {path}")


@app.command("check-llm")
def check_llm() -> None:
    """Verify the configured LLM endpoint answers, and that tool calling works."""
    from spendguard.agent.llm import LLMClient, LLMNotConfiguredError

    try:
        client = LLMClient()
    except LLMNotConfiguredError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    with console.status(f"Asking {client.model}..."):
        health = client.health()
    if not health["ok"]:
        console.print(f"[red]x[/red] {health['error']}")
        raise typer.Exit(code=1)

    table = Table(title="LLM", show_header=False)
    table.add_row("Provider", health["provider"])
    table.add_row("Model", str(health["model"]))
    table.add_row("Latency", f"{health['latency_seconds']:.2f}s")
    console.print(table)

    # Tool calling is what the Investigator depends on; a chat reply alone is not enough.
    probe = {
        "type": "function",
        "function": {
            "name": "vendor_profile",
            "description": "Payment history for one supplier.",
            "parameters": {
                "type": "object",
                "properties": {"vendor_key": {"type": "string"}},
                "required": ["vendor_key"],
            },
        },
    }
    reply = client.chat(
        [{"role": "user", "content": "Look up the supplier with key 'sharma'. Use the tool."}],
        tools=[probe],
    )
    if reply.wants_tool:
        call = reply.tool_calls[0]
        console.print(f"[green]Tool calling works[/green] — {call.name}({call.arguments})")
    else:
        console.print(
            "[yellow]Warning:[/yellow] the model replied in prose instead of calling the tool."
        )


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
