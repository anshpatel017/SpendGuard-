"""Everything that is not one case: KPIs, runs, a single transaction, evaluation, health."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import duckdb
from fastapi import APIRouter, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from spendguard.api.cases import fetch_rows, money, to_row, with_latest_note
from spendguard.api.deps import Duck, Stores, not_found
from spendguard.api.schemas import (
    AblationRow,
    AgentMetrics,
    AnomalyBreakdown,
    DetectorMetrics,
    EvaluationResponse,
    HealthResponse,
    MetricsResponse,
    RunSummary,
    TransactionRow,
)
from spendguard.config import settings
from spendguard.db.duck import AUDIT_VIEW, table_exists
from spendguard.db.store import (
    AuditNoteRecord,
    CaseRecord,
    CaseStatus,
    RunRecord,
    TraceRecord,
    get_engine,
)

router = APIRouter(tags=["overview"])


def _rate(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


# ------------------------------------------------------------------ metrics


def _dataset_facts(con: duckdb.DuckDBPyConnection) -> tuple[str | None, str | None, int | None]:
    """Dataset name, the currency it was converted from (if any), and its evaluation seed."""
    name = converted = None
    if table_exists(con, "dataset_cards"):
        row = con.execute("SELECT dataset, card FROM dataset_cards LIMIT 1").fetchone()
        if row:
            name = str(row[0])
            source = json.loads(row[1]).get("source", {})
            if source.get("converted"):
                converted = source.get("currency")
    seed = None
    if table_exists(con, "injection_runs"):
        found = con.execute("SELECT seed FROM injection_runs LIMIT 1").fetchone()
        seed = int(found[0]) if found else None
    return name, converted, seed


@router.get("/metrics", response_model=MetricsResponse)
def metrics(store: Stores, con: Duck) -> MetricsResponse:
    """Dashboard KPIs (FR-5.7). Flagged = investigated + queued, always."""
    dataset, converted, seed = _dataset_facts(con)
    row = con.execute(f"SELECT count(*), coalesce(sum(amount), 0) FROM {AUDIT_VIEW}").fetchone()
    total_rows, total_amount = (int(row[0]), float(row[1])) if row else (0, 0.0)

    with Session(store.engine) as session:
        cases = session.scalars(select(CaseRecord)).all()
        latest, n = with_latest_note(select(CaseRecord.case_id))
        notes = session.execute(latest.add_columns(n.verdict, n.verification_status)).all()
        last = session.scalars(select(RunRecord).order_by(RunRecord.started_at.desc())).first()

    by_type: dict[str, AnomalyBreakdown] = {}
    for kind in sorted({c.anomaly_type for c in cases}):
        of_kind = [c for c in cases if c.anomaly_type == kind]
        by_type[kind] = AnomalyBreakdown(
            count=len(of_kind),
            amount_at_risk=money(sum(c.amount_at_risk for c in of_kind)) or Decimal("0.00"),
        )
    investigated = sum(1 for c in cases if c.investigated)
    # A case a person dismissed is no longer money at risk; everything else is.
    open_amount = sum(c.amount_at_risk for c in cases if c.status != CaseStatus.DISMISSED)
    confirmed = sum(c.amount_at_risk for c in cases if c.status == CaseStatus.CONFIRMED)
    return MetricsResponse(
        dataset=dataset,
        evaluation_seed=seed,
        total_transactions=total_rows,
        total_amount=money(total_amount) or Decimal("0.00"),
        currency=settings.currency,
        converted_from=converted,
        cases_flagged=len(cases),
        cases_investigated=investigated,
        cases_queued=len(cases) - investigated,
        money_at_risk=money(open_amount) or Decimal("0.00"),
        money_at_risk_confirmed=money(confirmed) or Decimal("0.00"),
        by_anomaly_type=by_type,
        by_severity_band=dict(Counter(c.severity_band for c in cases)),
        by_status=dict(Counter(c.status for c in cases)),
        by_verdict=dict(Counter(v for _, v, _ in notes if v)),
        by_verification_status=dict(Counter(s for _, _, s in notes if s)),
        last_run_id=last.run_id if last else None,
        last_run_at=last.started_at if last else None,
    )


# ------------------------------------------------------------------ runs and rows


@router.get("/runs", response_model=list[RunSummary])
def runs(store: Stores, limit: Annotated[int, Query(ge=1, le=200)] = 20) -> list[RunSummary]:
    """Run history, newest first, so the dashboard can say which run it shows."""
    with Session(store.engine) as session:
        records = session.scalars(
            select(RunRecord).order_by(RunRecord.started_at.desc()).limit(limit)
        ).all()
        return [
            RunSummary(
                run_id=r.run_id,
                kind=r.kind,  # type: ignore[arg-type]
                status=r.status,  # type: ignore[arg-type]
                seed=(r.config or {}).get("seed"),
                started_at=r.started_at,
                finished_at=r.finished_at,
                summary=r.summary or {},
            )
            for r in records
        ]


@router.get(
    "/transactions/{row_id}",
    response_model=TransactionRow,
    responses={404: {"description": "Unknown row"}},
)
def transaction(row_id: int, con: Duck) -> TransactionRow:
    """One row, for inspecting a citation. Read from the audit view: never the answer key."""
    rows = fetch_rows(con, [row_id])
    if not rows:
        raise not_found("transaction", row_id)
    return to_row(rows[0], False, set())


# ------------------------------------------------------------------ evaluation


def _latest(directory: Path, pattern: str) -> Path | None:
    found = sorted(directory.glob(pattern))  # names carry a sortable timestamp
    return found[-1] if found else None


def _owns(detector: str, anomaly_type: str) -> bool:
    """Does the detector emit this anomaly type at all?

    The evaluation report scores every detector against every type, so D1 has an
    F1 of 0.000 on split purchases - true, and meaningless, and exactly the
    number a reader would misread. Only the types a detector declares are served;
    the pooled "all" row only for a detector that covers several (the baseline).
    """
    from spendguard.detectors import REGISTRY

    detector_class = REGISTRY.get(detector)
    if detector_class is None:
        return True
    types = {t.value for t in detector_class.anomaly_types}
    return anomaly_type in types or (anomaly_type == "all" and len(types) > 1)


def _detector_metrics(report: dict[str, Any]) -> list[DetectorMetrics]:
    return [
        DetectorMetrics(
            detector=m["detector"],
            anomaly_type=m["anomaly_type"],
            granularity=m["granularity"],
            precision=m["precision"],
            recall=m["recall"],
            f1=m["f1"],
            pr_auc=m.get("pr_auc"),
            tp=m["tp"],
            fp=m["fp"],
            fn=m["fn"],
        )
        for m in report.get("metrics", [])
        if _owns(m["detector"], m["anomaly_type"])
    ]


def _agent_metrics(
    store_path: Path, triage_report: Path | None
) -> tuple[AgentMetrics, list[AblationRow]]:
    """Aggregated over the evaluation store: every released note, newest per case."""
    empty = AgentMetrics(
        notes=0,
        citation_validity_deterministic=None,
        citation_validity_semantic=None,
        triage_accuracy=None,
        avg_tool_calls=None,
        avg_tokens=None,
        avg_latency_seconds=None,
        notes_regenerated=0,
        notes_failed_after_retries=0,
    )
    if not store_path.exists():
        return empty, []
    engine = get_engine(f"sqlite:///{store_path.as_posix()}")
    with Session(engine) as session:
        notes = session.scalars(select(AuditNoteRecord)).all()
        per_note = {
            note_id: (tools, tokens, latency)
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
    engine.dispose()

    newest: dict[str, AuditNoteRecord] = {}
    for n in sorted((n for n in notes if not n.is_ablation), key=lambda n: n.created_at):
        newest[n.case_id] = n
    released = list(newest.values())

    def validity(group: list[AuditNoteRecord]) -> tuple[float | None, float | None]:
        checked = [n for n in group if n.citations_checked]
        judged = [n for n in checked if n.semantic_passed is not None]
        return (
            _rate(sum(n.deterministic_passed or 0 for n in checked),
                  sum(n.citations_checked or 0 for n in checked)),
            _rate(sum(n.semantic_passed or 0 for n in judged),
                  sum(n.citations_checked or 0 for n in judged)),
        )  # fmt: skip

    triage = None
    if triage_report is not None:
        all_types = json.loads(triage_report.read_text(encoding="utf-8")).get("triage", {})
        triage = all_types.get("all", {}).get("decisive_accuracy")

    stats = [per_note[n.note_id] for n in released if n.note_id in per_note]
    deterministic, semantic = validity(released)
    agent = AgentMetrics(
        notes=len(released),
        citation_validity_deterministic=deterministic,
        citation_validity_semantic=semantic,
        triage_accuracy=triage,
        avg_tool_calls=_rate(sum(s[0] or 0 for s in stats), len(stats)),
        avg_tokens=_rate(sum(s[1] or 0 for s in stats), len(stats)),
        avg_latency_seconds=_rate(sum(s[2] or 0 for s in stats) / 1000, len(stats)),
        notes_regenerated=sum(1 for n in released if n.retry_count),
        notes_failed_after_retries=sum(
            1 for n in released if n.verification_status == "failed_after_retries"
        ),
    )
    ablations = []
    for name in sorted({n.ablation_name for n in notes if n.is_ablation and n.ablation_name}):
        det, sem = validity([n for n in notes if n.ablation_name == name])
        ablations.append(
            AblationRow(
                ablation_name=name,
                configuration=name,
                citation_validity_deterministic=det,
                citation_validity_semantic=sem,
                triage_accuracy=None,
                note_quality_score=None,
            )
        )
    return agent, ablations


@router.get("/evaluation", response_model=EvaluationResponse)
def evaluation(store: Stores, seed: int = settings.random_seed) -> EvaluationResponse:
    """Detector metrics against the baseline, agent metrics and ablations for one seed (FR-5.8)."""
    report_path = _latest(store.eval_dir, f"eval-*-seed{seed}.json")
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path else {}
    metrics_ = _detector_metrics(report)
    agent, ablations = _agent_metrics(
        store.eval_dir / f"investigation_seed{seed}.sqlite",
        _latest(store.eval_dir, f"investigate-eval-*-seed{seed}.json"),
    )
    groups = report.get("ground_truth_groups")
    return EvaluationResponse(
        run_id=report.get("run_id"),
        seed=seed,
        dataset=Path(report["db_path"]).stem if report.get("db_path") else None,
        injected_anomaly_count=sum(groups.values()) if groups else None,
        detector_metrics=[m for m in metrics_ if m.detector != "baseline"],
        baseline_metrics=[m for m in metrics_ if m.detector == "baseline"],
        agent_metrics=agent,
        ablations=ablations,
        generated_at=(
            datetime.fromtimestamp(report_path.stat().st_mtime, UTC) if report_path else None
        ),
    )


# ------------------------------------------------------------------ health


@router.get("/health", response_model=HealthResponse)
def health(store: Stores) -> HealthResponse:
    """Can the stores be read? The LLM is reported as configured, never probed (see schema)."""
    duck_ok = store_ok = False
    try:
        with duckdb.connect(str(store.duckdb_path), read_only=True) as con:
            con.execute(f"SELECT count(*) FROM {AUDIT_VIEW}").fetchone()
        duck_ok = True
    except duckdb.Error:
        pass
    try:
        with store.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        store_ok = True
    except Exception:  # any store failure is "not ok", reported, never raised
        pass
    configured = settings.llm_api_key not in ("", "not-set")
    return HealthResponse(
        status="ok" if duck_ok and store_ok else "degraded",
        duckdb=duck_ok,
        case_store=store_ok,
        llm_configured=configured,
        llm_model=settings.llm_model if configured else None,
    )
