"""Run the Investigator over prioritized cases - ``spendguard investigate``.

Two modes, kept apart for the same reason detection and evaluation are:

**Operational** reads the case store, takes the top-N uninvestigated cases by
preliminary severity (decision D-05), investigates each, and writes the note,
citations and trace back. Review status is never touched (D-04).

**Evaluation** runs on an injected database, where the truth of every case is
known. It samples real and spurious cases of each type, investigates them, and
measures triage: did the agent keep the real ones and filter the spurious ones?
Results go to a separate store and a report, never to the operational store.

Sampling in evaluation is random (seeded), not top-severity: the highest
severity cases are nearly all real, and a triage number measured only on those
would say nothing about the cases where investigation matters.

**Both modes stop cleanly on a spent daily quota and resume on the next run.**
The Groq free tier allows about 200,000 tokens a day - ten or so investigations
(D-30). Operational mode resumes naturally, because an unfinished case is still
uninvestigated. Evaluation mode draws the same seeded sample every time and
skips the cases that already have a note, so a sample can be built up over days.
"""

from __future__ import annotations

import json
import random
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spendguard.agent.investigator import InvestigationResult, Investigator
from spendguard.agent.verifier import Verifier, investigate_and_verify
from spendguard.cases import AnomalyType, Case
from spendguard.config import settings
from spendguard.db.duck import connect, table_exists
from spendguard.db.store import (
    CaseRecord,
    cases_to_investigate,
    get_engine,
    latest_note,
    record_run,
    save_cases,
    save_investigation,
)
from spendguard.detection import EvaluationDatabaseError
from spendguard.detectors import PRODUCTION_DETECTORS, REGISTRY
from spendguard.eval.matching import VENDOR_LEVEL_TYPES, TruthGroup, load_ground_truth, match
from spendguard.eval.triage import TriageItem, triage_metrics

ProgressFn = Callable[[int, int, Case, InvestigationResult], None]


@dataclass
class InvestigationRun:
    run_id: str
    dataset: str
    results: list[InvestigationResult]
    seconds: float
    rate_limit_wait_seconds: float = 0.0
    truth: dict[str, bool] = field(default_factory=dict)  # evaluation only: case_id -> real
    triage: dict[str, dict[str, object]] = field(default_factory=dict)
    report_paths: tuple[Path, ...] = ()
    not_attempted: int = 0  # left for the next run after the quota ran out
    sampled: int = 0  # evaluation only: size of the seeded sample
    investigated_so_far: int = 0  # evaluation only: sampled cases with a note, all runs

    @property
    def quota_stopped(self) -> bool:
        return any(r.quota_exhausted for r in self.results)

    def summary(self) -> dict[str, Any]:
        done = [r for r in self.results if r.status == "completed"]
        return {
            "cases": len(self.results),
            "completed": len(done),
            "failed": len(self.results) - len(done),
            "verdicts": dict(Counter(r.verdict.value for r in done if r.verdict)),
            "tool_calls": sum(r.tool_calls for r in self.results),
            "prompt_tokens": sum(r.prompt_tokens for r in self.results),
            "completion_tokens": sum(r.completion_tokens for r in self.results),
            "unseen_citations": sum(len(r.unseen_citations) for r in done),
            "seconds": self.seconds,
            "rate_limit_wait_seconds": round(self.rate_limit_wait_seconds, 1),
            "quota_stopped": self.quota_stopped,
            "not_attempted": self.not_attempted,
            "verification": citation_validity(done),
        }


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def citation_validity(results: Sequence[InvestigationResult]) -> dict[str, Any]:
    """Citation validity as two numbers, never one (D-13), before and after the Verifier.

    ``deterministic`` - rows exist and stated values match - is the headline.
    ``semantic`` is model-judged and labelled so. The first-draft figure is what
    the Investigator produced unaided; the gap to the released figure is what the
    Verifier's regeneration bought.
    """
    released = [r.verification for r in results if r.verification]
    first = [r.first_check for r in results if r.first_check]
    judged = [v for v in released if v.semantic_ran]
    checked = sum(v.checked for v in released)
    judged_checked = sum(v.checked for v in judged)
    return {
        "status": dict(Counter(r.verification_status for r in results)),
        "regenerated": sum(1 for r in results if r.retry_count),
        "citations_checked": checked,
        "deterministic_valid": _rate(sum(v.deterministic_passed for v in released), checked),
        "semantic_supported_model_judged": _rate(
            sum(v.semantic_passed or 0 for v in judged), judged_checked
        ),
        "first_draft_deterministic_valid": _rate(
            sum(v.deterministic_passed for v in first), sum(v.checked for v in first)
        ),
        "first_draft_passed": sum(1 for v in first if v.passed),
    }


def _default_llm() -> Any:
    from spendguard.agent.llm import LLMClient

    return LLMClient()


def _investigate_all(
    investigator: Investigator,
    verifier: Verifier,
    cases: Sequence[Case],
    engine: Any,
    run_id: str,
    on_result: ProgressFn | None,
    *,
    verify: bool,
) -> list[InvestigationResult]:
    results = []
    for i, case in enumerate(cases, start=1):
        result = investigate_and_verify(investigator, verifier, case, enabled=verify)
        save_investigation(engine, run_id, result)  # saved as it goes: a crash loses one case
        results.append(result)
        if on_result:
            on_result(i, len(cases), case, result)
        if result.quota_exhausted:  # every later case would fail the same way
            break
    return results


def run_investigation(
    *,
    top_n: int | None = None,
    anomaly_type: str | None = None,
    case_ids: Sequence[str] | None = None,
    include_investigated: bool = False,
    db_path: Path | None = None,
    store_url: str | None = None,
    llm: Any | None = None,
    on_result: ProgressFn | None = None,
    verify: bool | None = None,
) -> InvestigationRun:
    """Operational mode: the top-N cases from the case store."""
    verify = settings.verifier_enabled if verify is None else verify
    started = datetime.now(UTC).replace(tzinfo=None)
    t0 = time.perf_counter()
    db_path = db_path or settings.duckdb_path
    engine = get_engine(store_url)
    cases = cases_to_investigate(
        engine,
        top_n=settings.investigate_top_n if top_n is None else top_n,
        anomaly_type=anomaly_type,
        case_ids=case_ids,
        include_investigated=include_investigated,
    )
    run_id = f"investigate-{started:%Y%m%dT%H%M%S}"
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        first = session.get(CaseRecord, cases[0].case_id) if cases else None
        dataset = first.dataset if first else "unknown"

    llm = llm or _default_llm()
    results: list[InvestigationResult] = []
    with connect(db_path, read_only=True) as con:
        if table_exists(con, "injection_runs"):
            raise EvaluationDatabaseError(
                f"{db_path.name} contains planted anomalies. Use `spendguard investigate "
                "--eval-seed` for it; the case store is for real findings only."
            )
        if cases:
            results = _investigate_all(
                Investigator(llm, con), Verifier(llm, con), cases, engine, run_id, on_result,
                verify=verify,
            )  # fmt: skip

    run = InvestigationRun(
        run_id=run_id,
        dataset=dataset,
        results=results,
        seconds=round(time.perf_counter() - t0, 1),
        rate_limit_wait_seconds=getattr(llm, "rate_limit_wait_seconds", 0.0),
        not_attempted=len(cases) - len(results),
    )
    record_run(
        engine,
        run_id,
        "investigate",
        dataset,
        config=_config_snapshot(llm, verify, top_n=top_n, anomaly_type=anomaly_type),
        summary=run.summary(),
        started_at=started,
    )
    return run


# ------------------------------------------------------------------ evaluation


def _overlaps_truth(case: Case, groups: Sequence[TruthGroup]) -> bool:
    """Does the case touch any planted anomaly - of any type, even one already claimed?

    Any type, because a detector can catch real fraud under the wrong label: D2
    flagged a planted *duplicate* pair as a split (two identical orders summing
    past the threshold). Scoring that as a false alarm the agent failed to
    filter would be wrong - the agent rightly called it genuine, and even
    suggested checking for a duplicate record.
    """
    rows = set(case.row_ids)
    for g in groups:
        if g.anomaly_type in VENDOR_LEVEL_TYPES and g.vendor_key == case.vendor_key:
            return True
        if rows & g.row_ids:
            return True
    return False


def sample_for_triage(
    cases: Sequence[Case], groups: Sequence[TruthGroup], per_type: int, seed: int
) -> tuple[list[Case], dict[str, bool]]:
    """Up to ``per_type`` real and ``per_type`` spurious cases of each type.

    "Real" means matched to a planted anomaly of the case's type. "Spurious"
    means touching no planted anomaly of any type. Cases in between - a
    redundant second alert on a real scheme, or real fraud caught under another
    type's label - count as detection false positives, but an investigator is
    right to call them genuine, so they are left out of both pools rather than
    scored against the agent.
    """
    rng = random.Random(seed)
    chosen: list[Case] = []
    truth: dict[str, bool] = {}
    for kind in AnomalyType:
        result = match(cases, groups, kind)
        of_kind = [c for c in cases if c.anomaly_type == kind]
        real = sorted((c for c in of_kind if c.case_id in result.matched), key=lambda c: c.case_id)
        spurious = sorted(
            (
                c
                for c in of_kind
                if c.case_id not in result.matched and not _overlaps_truth(c, groups)
            ),
            key=lambda c: c.case_id,
        )
        for pool, is_real in ((real, True), (spurious, False)):
            for case in rng.sample(pool, min(per_type, len(pool))):
                chosen.append(case)
                truth[case.case_id] = is_real
    chosen.sort(key=lambda c: (-c.severity_prelim, c.case_id))
    return chosen, truth


def evaluate_investigation(
    seed: int,
    *,
    per_type: int = 2,
    include_investigated: bool = False,
    db_path: Path | None = None,
    report_dir: Path | None = None,
    llm: Any | None = None,
    on_result: ProgressFn | None = None,
    verify: bool | None = None,
) -> InvestigationRun:
    """Evaluation mode: sampled cases on an injected database, scored for triage.

    Triage is scored over every sampled case that has a note by the same model,
    from this run or an earlier one; the newest such note counts. Notes by other
    models stay in the store but never enter this model's numbers. ``include_investigated``
    re-investigates the whole sample, for example after a prompt change.
    """
    from spendguard.eval.injection import default_injected_path

    verify = settings.verifier_enabled if verify is None else verify
    started = datetime.now(UTC).replace(tzinfo=None)
    t0 = time.perf_counter()
    db_path = db_path or default_injected_path(seed)
    report_dir = report_dir or settings.processed_data_dir / "eval"
    report_dir.mkdir(parents=True, exist_ok=True)
    engine = get_engine(f"sqlite:///{(report_dir / f'investigation_seed{seed}.sqlite').as_posix()}")
    run_id = f"investigate-eval-{started:%Y%m%dT%H%M%S}-seed{seed}"
    dataset = f"injected_seed{seed}"

    llm = llm or _default_llm()
    with connect(db_path, read_only=True) as con:
        groups = load_ground_truth(con)
        cases = [c for name in PRODUCTION_DETECTORS for c in REGISTRY[name]().detect(con)]
        chosen, truth = sample_for_triage(cases, groups, per_type, seed)
        # Every flagged case goes to the store, not just the sample: the store then
        # shows what an auditor would see - everything flagged, some of it
        # investigated - and the dashboard's coverage line is honest about it.
        save_cases(engine, run_id, dataset, cases)
        # Per model: switching provider starts that model's sample afresh (D-33).
        model = str(getattr(llm, "model", "unknown"))
        done_before = {
            c.case_id for c in chosen if latest_note(engine, c.case_id, model_name=model)
        }
        pending = [c for c in chosen if include_investigated or c.case_id not in done_before]
        results = _investigate_all(
            Investigator(llm, con), Verifier(llm, con), pending, engine, run_id, on_result,
            verify=verify,
        )  # fmt: skip

    # A case counts once: its newest note, or this run's failure if it has no note.
    # A case the quota cut short was never really investigated, so it is not scored.
    failed_now = {r.case_id for r in results if r.note is None and not r.quota_exhausted}
    items = []
    for case in chosen:
        stored = latest_note(engine, case.case_id, model_name=model)
        if stored is not None:
            items.append(TriageItem(case.anomaly_type.value, truth[case.case_id], stored.verdict))
        elif case.case_id in failed_now:
            items.append(TriageItem(case.anomaly_type.value, truth[case.case_id], None))
    run = InvestigationRun(
        run_id=run_id,
        dataset=dataset,
        results=results,
        seconds=round(time.perf_counter() - t0, 1),
        rate_limit_wait_seconds=getattr(llm, "rate_limit_wait_seconds", 0.0),
        truth=truth,
        triage=triage_metrics(items),
        not_attempted=len(pending) - len(results),
        sampled=len(chosen),
        investigated_so_far=sum(1 for i in items if i.verdict is not None),
    )
    record_run(
        engine,
        run_id,
        "investigate",
        dataset,
        config={**_config_snapshot(llm, verify), "seed": seed, "per_type": per_type},
        summary={
            **run.summary(),
            "sampled": run.sampled,
            "investigated_so_far": run.investigated_so_far,
            "triage": run.triage,
        },
        started_at=started,
    )
    run.report_paths = write_triage_report(run, report_dir, seed=seed, per_type=per_type)
    return run


def _config_snapshot(llm: Any, verify: bool, **extra: Any) -> dict[str, Any]:
    return {
        "verifier_enabled": verify,
        "verifier_semantic_check": settings.verifier_semantic_check,
        "verifier_max_retries": settings.verifier_max_retries,
        "provider": str(getattr(llm, "provider", "unknown")),
        "model": str(getattr(llm, "model", "unknown")),
        "temperature": settings.llm_temperature,
        "agent_max_steps": settings.agent_max_steps,
        "agent_context_tokens": settings.agent_context_tokens,
        "agent_tool_result_chars": settings.agent_tool_result_chars,
        **{k: v for k, v in extra.items() if v is not None},
    }


def write_triage_report(
    run: InvestigationRun, out_dir: Path, *, seed: int, per_type: int
) -> tuple[Path, Path]:
    cases = [
        {
            "case_id": r.case_id,
            "anomaly_type": r.anomaly_type,
            "real": run.truth.get(r.case_id),
            "status": r.status,
            "verdict": r.verdict.value if r.verdict else None,
            "severity_final": r.severity_final,
            "tool_calls": r.tool_calls,
            "prompt_tokens": r.prompt_tokens,
            "seconds": r.seconds,
            "unseen_citations": r.unseen_citations,
            "verification_status": r.verification_status,
            "retry_count": r.retry_count,
            "citations_checked": r.verification.checked if r.verification else None,
            "deterministic_passed": r.verification.deterministic_passed if r.verification else None,
            "semantic_passed": r.verification.semantic_passed if r.verification else None,
            "error": r.error,
        }
        for r in run.results
    ]
    payload = {
        "run_id": run.run_id,
        "seed": seed,
        "per_type": per_type,
        "sampled": run.sampled,
        "investigated_so_far": run.investigated_so_far,
        "summary": run.summary(),
        "triage": run.triage,
        "cases": cases,
    }
    json_path = out_dir / f"{run.run_id}.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# Investigation triage - `{run.run_id}`",
        "",
        f"Seed {seed}, up to {per_type} real and {per_type} spurious cases per type. "
        "Real = matched to a planted anomaly; spurious = touching none. "
        f"**{run.investigated_so_far} of {run.sampled} sampled cases investigated so far** "
        "- notes accumulate across runs and the newest note for a case counts.",
        "",
        "| Type | Cases | Real kept | Real wrongly dismissed | Spurious filtered "
        "| Inconclusive | Failed |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    def cell(value: object) -> str:
        return "-" if value is None else f"{value:.0%}" if isinstance(value, float) else str(value)

    for kind, m in run.triage.items():
        lines.append(
            f"| {kind} | {m['cases']} ({m['real']} real) | {cell(m['real_kept'])} "
            f"| {cell(m['real_wrongly_dismissed'])} | {cell(m['spurious_filtered'])} "
            f"| {cell(m['inconclusive'])} | {cell(m['failed'])} |"
        )
    s = run.summary()
    lines += [
        "",
        f"{s['completed']} of {s['cases']} investigations produced a valid note; "
        f"{s['tool_calls']} tool calls, {s['prompt_tokens']:,} prompt tokens, "
        f"{s['unseen_citations']} citations of rows the agent never saw. "
        f"{s['seconds']:.0f}s in total, {s['rate_limit_wait_seconds']:.0f}s of it waiting on "
        "rate limits.",
    ]
    v = s["verification"]
    lines += [
        "",
        "## Citation validity (this run)",
        "",
        "| | First draft | Released |",
        "|---|---:|---:|",
        f"| Deterministic - rows exist, values match | {cell(v['first_draft_deterministic_valid'])} "
        f"| {cell(v['deterministic_valid'])} |",
        f"| Semantic - evidence supports the claim (model-judged) | - "
        f"| {cell(v['semantic_supported_model_judged'])} |",
        "",
        f"{v['citations_checked']} citations checked. Release status {v['status']}; "
        f"{v['regenerated']} note(s) regenerated after the Verifier objected.",
    ]
    if run.quota_stopped:
        lines += [
            "",
            "**Stopped early: the provider's daily quota ran out.** "
            f"{run.not_attempted} sampled case(s) not attempted this run; run the same command "
            "later to continue where it stopped.",
        ]
    md_path = out_dir / f"{run.run_id}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path
