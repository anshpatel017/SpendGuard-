"""Agent results across seeds, models and ablation arms - ``spendguard report agent``.

The detector table (``report detection``) can be regenerated from one command
because detection is deterministic: same seed, same output. Agent results are
not. They accumulate a handful of cases a day against a free-tier quota (D-30),
across three seeds, three arms and however many models, and no single run holds
them all. Assembling that table by hand is how a number gets copied wrong.

So this reads the **evaluation stores**, not the run logs:

* **Citation validity and efficiency** come from the notes themselves - newest
  note per (case, model, arm), which is the note that stands. A case
  investigated twice counts once, and a revision counts as the draft that was
  released.
* **Triage** comes from the newest run record for that (seed, model, arm),
  because triage needs the seeded sample's answer key, and the run that drew
  the sample already computed it over every note stored at the time.

Nothing here blends a model-judged number into a deterministic one (D-13), and
nothing here merges two models into one row (D-33). Arms stay beside the main
run, never inside it (D-35).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from spendguard.ablations import ARMS
from spendguard.config import settings
from spendguard.db.store import AuditNoteRecord, RunRecord, TraceRecord, get_engine
from spendguard.eval.report import Spread, provenance

MAIN_ARM = "agent"


def _rate(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


@dataclass
class ArmResult:
    """One (seed, model, arm) cell of the results table."""

    seed: int
    model: str
    arm: str
    notes: int
    sampled: int | None
    citations_checked: int
    deterministic_valid: float | None
    semantic_valid: float | None  # model-judged, never blended with the above
    first_draft_valid: float | None
    regenerated: int
    released: dict[str, int] = field(default_factory=dict)
    triage: dict[str, Any] = field(default_factory=dict)
    avg_tool_calls: float | None = None
    avg_tokens: float | None = None
    avg_seconds: float | None = None
    quota_stopped: bool = False

    @property
    def triage_accuracy(self) -> float | None:
        value = self.triage.get("decisive_accuracy")
        return float(value) if isinstance(value, int | float) else None

    @property
    def real_kept(self) -> float | None:
        value = self.triage.get("real_kept")
        return float(value) if isinstance(value, int | float) else None

    @property
    def spurious_filtered(self) -> float | None:
        value = self.triage.get("spurious_filtered")
        return float(value) if isinstance(value, int | float) else None


@dataclass
class AgentReport:
    seeds: list[int]
    results: list[ArmResult]
    manifest: dict[str, Any] = field(default_factory=dict)

    def arms_present(self) -> list[str]:
        order = [MAIN_ARM, *ARMS]
        found = {r.arm for r in self.results}
        return [a for a in order if a in found] + sorted(found - set(order))

    def models_present(self) -> list[str]:
        return sorted({r.model for r in self.results})


def _store_path(seed: int, eval_dir: Path) -> Path:
    return eval_dir / f"investigation_seed{seed}.sqlite"


def collect_seed(engine: Engine, seed: int) -> list[ArmResult]:
    """Every (model, arm) that has notes in this seed's store."""
    with Session(engine) as session:
        notes = list(session.scalars(select(AuditNoteRecord)))
        runs = list(session.scalars(select(RunRecord).where(RunRecord.kind == "investigate")))
        per_note = {
            note_id: (tools or 0, tokens or 0, latency or 0)
            for note_id, tools, tokens, latency in session.execute(
                select(
                    TraceRecord.note_id,
                    func.sum(func.iif(TraceRecord.kind == "tool", 1, 0)),
                    func.sum(TraceRecord.prompt_tokens + TraceRecord.completion_tokens),
                    func.sum(TraceRecord.latency_ms),
                )
                .where(TraceRecord.note_id.is_not(None))
                .group_by(TraceRecord.note_id)
            ).all()
        }

    # The note that stands for a case, per arm and per model.
    newest: dict[tuple[str, str, str], AuditNoteRecord] = {}
    for note in sorted(notes, key=lambda n: n.created_at):
        newest[(note.case_id, note.ablation_name or MAIN_ARM, note.model_name)] = note

    # The run that last drew this arm's sample already computed its triage.
    latest_run: dict[tuple[str, str], RunRecord] = {}
    for run in sorted(runs, key=lambda r: r.started_at):
        config = run.config or {}
        model = str(config.get("model", "unknown"))
        arm = config.get("ablation") or MAIN_ARM
        if arm == ARMS[0]:  # the template arm writes its own name as the model
            model = arm
        latest_run[(model, arm)] = run

    grouped: dict[tuple[str, str], list[AuditNoteRecord]] = {}
    for (_, arm, model), note in newest.items():
        grouped.setdefault((model, arm), []).append(note)

    results = []
    for (model, arm), group in sorted(grouped.items()):
        checked = [n for n in group if n.citations_checked]
        judged = [n for n in checked if n.semantic_passed is not None]
        stats = [per_note[n.note_id] for n in group if n.note_id in per_note]
        found = latest_run.get((model, arm))
        summary: dict[str, Any] = (found.summary or {}) if found else {}
        verification = summary.get("verification") or {}
        results.append(
            ArmResult(
                seed=seed,
                model=model,
                arm=arm,
                notes=len(group),
                sampled=summary.get("sampled"),
                citations_checked=sum(n.citations_checked or 0 for n in checked),
                deterministic_valid=_rate(
                    sum(n.deterministic_passed or 0 for n in checked),
                    sum(n.citations_checked or 0 for n in checked),
                ),
                semantic_valid=_rate(
                    sum(n.semantic_passed or 0 for n in judged),
                    sum(n.citations_checked or 0 for n in judged),
                ),
                first_draft_valid=verification.get("first_draft_deterministic_valid"),
                regenerated=sum(1 for n in group if n.retry_count),
                released={
                    status: sum(1 for n in group if n.verification_status == status)
                    for status in sorted({n.verification_status for n in group})
                },
                triage=(summary.get("triage") or {}).get("all") or {},
                avg_tool_calls=_rate(sum(s[0] for s in stats), len(stats)),
                avg_tokens=_rate(sum(s[1] for s in stats), len(stats)),
                avg_seconds=_rate(sum(s[2] for s in stats) / 1000, len(stats)),
                quota_stopped=bool(summary.get("quota_stopped")),
            )
        )
    return results


def agent_report(seeds: Sequence[int] | None = None, eval_dir: Path | None = None) -> AgentReport:
    seeds = list(seeds or settings.evaluation_seeds)
    eval_dir = eval_dir or settings.processed_data_dir / "eval"
    results: list[ArmResult] = []
    for seed in seeds:
        path = _store_path(seed, eval_dir)
        if not path.exists():
            continue
        engine = get_engine(f"sqlite:///{path.as_posix()}")
        results += collect_seed(engine, seed)
        engine.dispose()
    return AgentReport(seeds=seeds, results=results, manifest=provenance(()))


# ------------------------------------------------------------------ rendering


def _pct(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}%}"


def _num(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:,.{digits}f}"


def across_seeds(results: Sequence[ArmResult], attribute: str) -> Spread | None:
    values = [v for r in results if (v := getattr(r, attribute)) is not None]
    return Spread.of(values) if values else None


def render_markdown(report: AgentReport) -> str:
    m = report.manifest
    dirty = " **(uncommitted changes)**" if m.get("dirty") else ""
    lines = [
        "# Agent results - investigation and verification",
        "",
        f"Generated {m.get('generated_at')} from commit `{m.get('commit')}`{dirty}. "
        "Regenerate with `spendguard report agent`.",
        "",
        "Read from the evaluation stores, not from any single run: notes accumulate a "
        "few a day against a free-tier daily quota (D-30), and the newest note per "
        "(case, model, arm) is the one that stands. **Numbers are per model** - two "
        "models are never merged into one row (D-33) - and ablation arms sit beside "
        "the main run, never inside it (D-35).",
        "",
    ]
    if not report.results:
        return "\n".join([*lines, "No investigations stored yet.", ""])

    lines += [
        "## Citation validity",
        "",
        "**The deterministic column is the headline** - rows exist and every stated "
        "value matches, checked by rule with no model involved. The semantic column is "
        "judged by a model and is labelled so; the two are never blended (D-13). "
        "*First draft* is what the Investigator produced unaided, so the gap to "
        "*released* is what the Verifier's regeneration bought.",
        "",
        "| Seed | Model | Arm | Notes | Citations | First draft | Released (deterministic) "
        "| Supported (model-judged) | Regenerated |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in sorted(report.results, key=lambda r: (r.seed, r.arm, r.model)):
        lines.append(
            f"| {r.seed} | {r.model} | {r.arm} | {r.notes} | {r.citations_checked} "
            f"| {_pct(r.first_draft_valid)} | **{_pct(r.deterministic_valid)}** "
            f"| {_pct(r.semantic_valid)} | {r.regenerated} |"
        )

    lines += [
        "",
        "## Triage - what the agent filters",
        "",
        "Over the seeded sample of real and spurious cases for each seed. *Real kept* is "
        "the share of genuine anomalies the agent did not dismiss; *spurious filtered* is "
        "the share of false alarms it did. A template arm scores 0 on the second by "
        "construction - it cannot weigh an innocent explanation - which is the comparison "
        "the arm exists to make.",
        "",
        "| Seed | Model | Arm | Sample | Investigated | Real kept | Spurious filtered "
        "| Decisive accuracy |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in sorted(report.results, key=lambda r: (r.seed, r.arm, r.model)):
        cases = r.triage.get("cases")
        lines.append(
            f"| {r.seed} | {r.model} | {r.arm} | {r.sampled or '-'} | {cases or '-'} "
            f"| {_pct(r.real_kept, 0)} | {_pct(r.spurious_filtered, 0)} "
            f"| **{_pct(r.triage_accuracy, 0)}** |"
        )

    lines += [
        "",
        "## Cost per investigation",
        "",
        "| Seed | Model | Arm | Tool calls | Tokens | Seconds of model time |",
        "|---:|---|---|---:|---:|---:|",
    ]
    for r in sorted(report.results, key=lambda r: (r.seed, r.arm, r.model)):
        lines.append(
            f"| {r.seed} | {r.model} | {r.arm} | {_num(r.avg_tool_calls)} "
            f"| {_num(r.avg_tokens, 0)} | {_num(r.avg_seconds)} |"
        )

    # Across seeds, per model and arm - the headline form (EVALUATION 7).
    combinations = sorted({(r.model, r.arm) for r in report.results})
    multi = [c for c in combinations if len({r.seed for r in report.results if (r.model, r.arm) == c}) > 1]  # fmt: skip
    if multi:
        lines += [
            "",
            "## Across seeds",
            "",
            "Mean and sample standard deviation over the seeds that have notes for that "
            "model and arm. A single-seed row is not reported here - one run is not a spread.",
            "",
            "| Model | Arm | Seeds | Citations valid (deterministic) | Triage accuracy |",
            "|---|---|---:|---|---|",
        ]
        for model, arm in multi:
            rows = [r for r in report.results if (r.model, r.arm) == (model, arm)]
            valid = across_seeds(rows, "deterministic_valid")
            triage = across_seeds(rows, "triage_accuracy")
            lines.append(
                f"| {model} | {arm} | {len(rows)} "
                f"| {valid.text() if valid else '-'} | {triage.text() if triage else '-'} |"
            )

    stopped = [r for r in report.results if r.quota_stopped]
    if stopped:
        lines += [
            "",
            "**Some runs stopped on the provider's daily quota** and have fewer notes than "
            "their sample: "
            + ", ".join(f"seed {r.seed} / {r.model} / {r.arm}" for r in stopped)
            + ". Running the same command later continues where it stopped (D-30).",
            "",
        ]
    incomplete = [r for r in report.results if r.sampled and r.notes < r.sampled]
    if incomplete:
        lines += [
            "",
            f"**{len(incomplete)} arm(s) are still short of their sample.** Every rate above "
            "is over the notes that exist, so it will move as the rest arrive. Treat a row "
            "with fewer than ~20 notes as an indication, not a rate.",
            "",
        ]
    return "\n".join(lines) + "\n"


def write_agent_report(report: AgentReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "agent.md"
    js = out_dir / "agent.json"
    md.write_text(render_markdown(report), encoding="utf-8")
    js.write_text(
        json.dumps(
            {
                "manifest": report.manifest,
                "seeds": report.seeds,
                "results": [
                    {
                        **asdict(r),
                        "triage_accuracy": r.triage_accuracy,
                        "real_kept": r.real_kept,
                        "spurious_filtered": r.spurious_filtered,
                    }
                    for r in report.results
                ],
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return md, js
