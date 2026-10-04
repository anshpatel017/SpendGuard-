"""Cases: the queue, one case in full, its evidence, and the review action.

The review action is the only write in the API besides the demo endpoint, and
it is a person's: nothing in the agent layer calls it (D-04, D-07).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import threading
from typing import Annotated, Any, Literal
from uuid import UUID

import duckdb
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from spendguard.api.deps import Duck, Stores, not_found
from spendguard.api.schemas import (
    AnomalyTypeName,
    AuditNote,
    BandName,
    Case,
    CaseDetailResponse,
    CaseListResponse,
    CaseReviewItem,
    CaseSummary,
    Citation,
    EvidenceResponse,
    InvestigationJobResponse,
    InvestigationStatus,
    StatusName,
    StatusUpdateRequest,
    TraceStep,
    TransactionRow,
    VerdictName,
    VerificationName,
)
from spendguard.config import settings
from spendguard.db.duck import AUDIT_FIELDS, AUDIT_VIEW
from spendguard.db.store import (
    AuditNoteRecord,
    CaseRecord,
    CaseReviewRecord,
    CaseStatus,
    CitationRecord,
    InvalidTransitionError,
    TraceRecord,
    get_case_reviews,
    latest_note,
    set_status,
)
from spendguard.investigation import investigate_case_by_id

router = APIRouter(prefix="/cases", tags=["cases"])

EXCERPT_CHARS = 180
SORTS = {
    "severity_prelim": CaseRecord.severity_prelim,
    "severity_final": CaseRecord.severity_final,
    "amount_at_risk": CaseRecord.amount_at_risk,
    "created_at": CaseRecord.created_at,
}


DETECTOR_MAP = {
    "duplicate": "duplicate",
    "duplicates": "duplicate",
    "d1": "duplicate",
    "d1_duplicate": "duplicate",
    "d1_duplicates": "duplicate",
    "split": "split",
    "splits": "split",
    "d2": "split",
    "d2_split": "split",
    "d2_splits": "split",
    "inflation": "inflation",
    "d3": "inflation",
    "d3_inflation": "inflation",
    "vendor": "vendor_flag",
    "vendor_flag": "vendor_flag",
    "vendor_risk": "vendor_flag",
    "d4": "vendor_flag",
    "d4_vendor": "vendor_flag",
    "d4_vendor_risk": "vendor_flag",
}


@dataclass
class _JobRecord:
    state: str  # "queued", "investigating", "verifying", "completed", "failed"
    stage: str
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None


_JOB_LOCK = threading.Lock()
_JOBS: dict[str, _JobRecord] = {}


def _get_job(case_id: str) -> _JobRecord | None:
    with _JOB_LOCK:
        return _JOBS.get(case_id)


def _set_job(
    case_id: str,
    state: str,
    stage: str,
    error: str | None = None,
    finished: bool = False,
) -> None:
    with _JOB_LOCK:
        existing = _JOBS.get(case_id)
        now = datetime.now(UTC).replace(tzinfo=None)
        if existing is None:
            _JOBS[case_id] = _JobRecord(
                state=state,
                stage=stage,
                started_at=now,
                finished_at=now if finished else None,
                error=error,
            )
        else:
            existing.state = state
            existing.stage = stage
            if finished:
                existing.finished_at = now
            if error is not None:
                existing.error = error


def _get_case_investigation_status(cid: str, record: CaseRecord) -> InvestigationStatus:
    job = _get_job(cid)
    if job:
        return InvestigationStatus(
            state=job.state,  # type: ignore[arg-type]
            stage=job.stage,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error=job.error,
        )
    if record.investigated:
        return InvestigationStatus(
            state="completed",
            stage="Completed",
            started_at=record.updated_at,
            finished_at=record.updated_at,
        )
    return InvestigationStatus(
        state="not_investigated",
        stage="Not investigated",
    )


def _run_investigation_worker(case_id: str, engine: Any, duckdb_path: Path) -> None:
    if settings.llm_api_key in ("", "not-set"):
        _set_job(
            case_id,
            "failed",
            "AI investigation is unavailable: no supported provider configured.",
            error="AI investigation is unavailable because no supported provider is configured.",
            finished=True,
        )
        return

    _set_job(case_id, "investigating", "Investigating transactions and policy")
    try:
        def on_stage(stage: str) -> None:
            if stage == "verifying":
                _set_job(case_id, "verifying", "Verifying citations and evidence claims")
            elif stage == "investigating":
                _set_job(case_id, "investigating", "Investigating transactions and policy")

        investigate_case_by_id(
            case_id,
            engine=engine,
            db_path=duckdb_path,
            on_stage=on_stage,
        )
        _set_job(case_id, "completed", "Investigation completed", finished=True)
    except Exception as exc:
        _set_job(case_id, "failed", "Investigation failed", error=str(exc), finished=True)


def money(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(f"{value:.2f}")


def to_case(record: CaseRecord) -> Case:
    return Case(
        case_id=UUID(record.case_id),
        run_id=record.run_id,
        anomaly_type=record.anomaly_type,  # type: ignore[arg-type]
        detector=record.detector,
        row_ids=list(record.row_ids),
        vendor_key=record.vendor_key,
        detector_score=record.detector_score,
        amount_at_risk=money(record.amount_at_risk) or Decimal("0.00"),
        severity_prelim=record.severity_prelim,
        severity_final=record.severity_final,
        severity_band=record.severity_band,  # type: ignore[arg-type]
        status=record.status,  # type: ignore[arg-type]
        investigated=record.investigated,
        dismissed_by_agent=record.dismissed_by_agent,
        reviewer_note=record.reviewer_note,
        metadata=record.details or {},
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _excerpt(text: str | None) -> str | None:
    if not text:
        return None
    return text if len(text) <= EXCERPT_CHARS else text[: EXCERPT_CHARS - 1].rstrip() + "…"


def with_latest_note(query: Select[Any]) -> tuple[Select[Any], Any]:
    """Join each case to the note that currently stands for it: newest, not an ablation."""
    latest = (
        select(AuditNoteRecord.case_id, func.max(AuditNoteRecord.created_at).label("at"))
        .where(AuditNoteRecord.is_ablation.is_(False))
        .group_by(AuditNoteRecord.case_id)
        .subquery()
    )
    note = aliased(AuditNoteRecord)
    query = query.outerjoin(latest, latest.c.case_id == CaseRecord.case_id).outerjoin(
        note,
        and_(
            note.case_id == latest.c.case_id,
            note.created_at == latest.c.at,
            note.is_ablation.is_(False),
        ),
    )
    return query, note


@router.get("", response_model=CaseListResponse)
def list_cases(
    store: Stores,
    status: Annotated[list[StatusName] | None, Query()] = None,
    anomaly_type: Annotated[list[AnomalyTypeName] | None, Query()] = None,
    detector: Annotated[list[str] | None, Query()] = None,
    severity_band: Annotated[list[BandName] | None, Query()] = None,
    severity: Annotated[list[BandName] | None, Query()] = None,
    verdict: Annotated[list[VerdictName] | None, Query()] = None,
    verification_status: Annotated[list[VerificationName] | None, Query()] = None,
    investigated: bool | None = None,
    dismissed_by_agent: bool | None = None,
    search: Annotated[str | None, Query()] = None,
    min_amount: Annotated[Decimal | None, Query(ge=0)] = None,
    sort: Literal["severity_prelim", "severity_final", "amount_at_risk", "created_at"] = (
        "severity_prelim"
    ),
    order: Literal["asc", "desc"] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 50,
) -> CaseListResponse:
    """The case queue (FR-5.5). "Dismissed by agent" stays reachable as a filter (FR-5.4)."""
    page_size = min(page_size, settings.api_page_size_max)
    query, note = with_latest_note(select(CaseRecord))
    query = query.add_columns(note)

    filters: list[ColumnElement[bool]] = []
    if status:
        filters.append(CaseRecord.status.in_(status))

    target_types: set[str] = set()
    if anomaly_type:
        target_types.update(DETECTOR_MAP.get(t.lower(), t) for t in anomaly_type)
    if detector:
        target_types.update(DETECTOR_MAP.get(d.lower(), d) for d in detector)
    if target_types:
        filters.append(CaseRecord.anomaly_type.in_(list(target_types)))

    target_severities = severity_band or severity
    if target_severities:
        filters.append(CaseRecord.severity_band.in_(target_severities))

    if verdict:
        filters.append(note.verdict.in_(verdict))
    if verification_status:
        filters.append(note.verification_status.in_(verification_status))
    if investigated is not None:
        filters.append(CaseRecord.investigated.is_(investigated))
    if dismissed_by_agent is not None:
        filters.append(CaseRecord.dismissed_by_agent.is_(dismissed_by_agent))
    if search and search.strip():
        s = search.strip()
        filters.append(
            or_(
                CaseRecord.vendor_key.ilike(f"%{s}%"),
                CaseRecord.case_id.ilike(f"%{s}%"),
                CaseRecord.detector.ilike(f"%{s}%"),
            )
        )
    if min_amount is not None:
        filters.append(CaseRecord.amount_at_risk >= float(min_amount))
    if filters:
        query = query.where(*filters)

    column = SORTS[sort]
    ordering = column.asc() if order == "asc" else column.desc()
    query = query.order_by(ordering.nulls_last(), CaseRecord.case_id)

    with Session(store.engine) as session:
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = session.execute(query.offset((page - 1) * page_size).limit(page_size)).all()
        items = [
            CaseSummary(
                **to_case(record).model_dump(exclude={"metadata"}),
                verdict=n.verdict if n else None,
                verification_status=n.verification_status if n else None,
                citations_checked=n.citations_checked if n else None,
                citations_passed=n.citations_passed if n else None,
                finding_excerpt=_excerpt(n.finding) if n else None,
            )
            for record, n in rows
        ]
    return CaseListResponse(
        items=items, total=total, page=page, page_size=page_size, currency=settings.currency
    )


# ------------------------------------------------------------------ evidence


def to_row(row: dict[str, Any], in_case: bool, cited: set[int]) -> TransactionRow:
    return TransactionRow(
        **{k: row[k] for k in AUDIT_FIELDS if k not in ("amount", "unit_price")},
        amount=money(row["amount"]) or Decimal("0.00"),
        unit_price=money(row["unit_price"]),
        in_case=in_case,
        cited=int(row["row_id"]) in cited,
    )


def fetch_rows(
    con: duckdb.DuckDBPyConnection, row_ids: list[int], *, limit: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    """Rows from the audit view - the same one the agent read, without the answer key."""
    if not row_ids:
        return []
    sql = (
        f"SELECT {', '.join(AUDIT_FIELDS)} FROM {AUDIT_VIEW} "
        "WHERE row_id IN (SELECT unnest(?)) ORDER BY txn_date, row_id"
    )
    params: list[Any] = [row_ids]
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params += [limit, offset]
    return con.execute(sql, params).pl().to_dicts()


def _nearby(
    con: duckdb.DuckDBPyConnection, record: CaseRecord, around: Any, exclude: list[int]
) -> list[dict[str, Any]]:
    """The same supplier's rows closest in time: what an auditor compares a case against."""
    if not record.vendor_key or around is None or settings.api_context_rows <= 0:
        return []
    return (
        con.execute(
            f"SELECT {', '.join(AUDIT_FIELDS)} FROM {AUDIT_VIEW} "
            "WHERE vendor_key = ? AND row_id NOT IN (SELECT unnest(?)) "
            "ORDER BY abs(date_diff('day', txn_date, ?::DATE)), row_id LIMIT ?",
            [record.vendor_key, exclude, around, settings.api_context_rows],
        )
        .pl()
        .to_dicts()
    )


def _note(session: Session, record: AuditNoteRecord) -> AuditNote:
    citations = session.scalars(
        select(CitationRecord)
        .where(CitationRecord.note_id == record.note_id)
        .order_by(CitationRecord.claim_index, CitationRecord.row_id)
    ).all()
    return AuditNote(
        note_id=UUID(record.note_id),
        case_id=UUID(record.case_id),
        finding=record.finding,
        recommended_action=record.recommended_action,
        verdict=record.verdict,  # type: ignore[arg-type]
        policy_clauses=list(record.policy_clauses or []),
        verification_status=record.verification_status,  # type: ignore[arg-type]
        citations=[
            Citation(
                citation_id=UUID(c.citation_id),
                claim_index=c.claim_index,
                claim_text=c.claim_text,
                row_id=c.row_id,
                asserted=c.asserted or {},
                row_exists=c.row_exists,
                values_match=c.values_match,
                supports_claim=c.supports_claim,
                failure_reason=c.failure_reason,
            )
            for c in citations
        ],
        citations_checked=record.citations_checked,
        citations_passed=record.citations_passed,
        deterministic_passed=record.deterministic_passed,
        semantic_passed=record.semantic_passed,
        retry_count=record.retry_count,
        model_name=record.model_name,
        created_at=record.created_at,
    )


def _trace(session: Session, note_id: str) -> list[TraceStep]:
    steps = session.scalars(
        select(TraceRecord).where(TraceRecord.note_id == note_id).order_by(TraceRecord.step_index)
    ).all()
    return [
        TraceStep(
            step_index=s.step_index,
            role=s.role,  # type: ignore[arg-type]
            kind=s.kind,
            tool_name=s.tool_name,
            tool_args=s.tool_args,
            tool_result=s.tool_result,
            latency_ms=s.latency_ms,
            prompt_tokens=s.prompt_tokens,
            completion_tokens=s.completion_tokens,
            detail=s.detail,
            error=s.error,
        )
        for s in steps
    ]


@router.get(
    "/{case_id}",
    response_model=CaseDetailResponse,
    responses={404: {"description": "Unknown case"}},
)
def case_detail(case_id: UUID, store: Stores, con: Duck) -> CaseDetailResponse:
    """Everything an auditor needs to decide one case (FR-5.6)."""
    with Session(store.engine) as session:
        record = session.get(CaseRecord, str(case_id))
        if record is None:
            raise not_found("case", case_id)
        note_record = latest_note(store.engine, record.case_id)
        note = _note(session, note_record) if note_record else None
        trace = _trace(session, note_record.note_id) if note_record else []
        case = to_case(record)
        review_records = get_case_reviews(store.engine, record.case_id)
        reviews = [
            CaseReviewItem(
                id=r.id,
                case_id=r.case_id,
                previous_status=r.previous_status,
                new_status=r.new_status,
                note=r.note,
                reviewer=r.reviewer,
                created_at=r.created_at,
            )
            for r in review_records
        ]
        inv_status = _get_case_investigation_status(record.case_id, record)

    case_rows = list(record.row_ids)
    cited = {c.row_id for c in note.citations} if note else set()
    evidence = fetch_rows(con, case_rows, limit=settings.api_evidence_rows)
    outside = sorted(cited - set(case_rows))  # rows the note relies on beyond the case itself
    context = fetch_rows(con, outside)
    around = evidence[0]["txn_date"] if evidence else None
    context += _nearby(con, record, around, case_rows + outside)
    return CaseDetailResponse(
        case=case,
        audit_note=note,
        evidence_rows=[to_row(r, True, cited) for r in evidence],
        evidence_total=len(case_rows),
        context_rows=[to_row(r, False, cited) for r in context],
        trace=trace,
        currency=settings.currency,
        investigation_status=inv_status,
        reviews=reviews,
    )


@router.get(
    "/{case_id}/evidence",
    response_model=EvidenceResponse,
    responses={404: {"description": "Unknown case"}},
)
def case_evidence(
    case_id: UUID,
    store: Stores,
    con: Duck,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1)] = 100,
) -> EvidenceResponse:
    """A case's rows, a page at a time - a vendor case can hold hundreds."""
    with Session(store.engine) as session:
        record = session.get(CaseRecord, str(case_id))
        if record is None:
            raise not_found("case", case_id)
        row_ids = list(record.row_ids)
    limit = min(limit, settings.api_page_size_max)
    rows = fetch_rows(con, row_ids, limit=limit, offset=offset)
    return EvidenceResponse(
        case_id=case_id, rows=[to_row(r, True, set()) for r in rows], total=len(row_ids)
    )


@router.patch(
    "/{case_id}/status",
    response_model=Case,
    responses={
        404: {"description": "Unknown case"},
        400: {"description": "Invalid status transition"},
    },
)
def update_status(case_id: UUID, body: StatusUpdateRequest, store: Stores) -> Case:
    """The human decision (FR-5.2). The agent never calls this."""
    try:
        set_status(
            store.engine,
            str(case_id),
            CaseStatus(body.status),
            body.reviewer_note,
            reviewer=body.reviewer,
        )
    except KeyError:
        raise not_found("case", case_id) from None
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_transition", "message": str(exc)},
        ) from None

    with Session(store.engine) as session:
        record = session.get(CaseRecord, str(case_id))
        assert record is not None
        return to_case(record)


@router.post(
    "/{case_id}/investigate",
    response_model=InvestigationJobResponse,
    responses={404: {"description": "Unknown case"}},
)
def trigger_investigation(
    case_id: UUID,
    store: Stores,
    background_tasks: BackgroundTasks,
) -> InvestigationJobResponse:
    """Trigger an AI investigation for a case in the background."""
    with Session(store.engine) as session:
        record = session.get(CaseRecord, str(case_id))
        if record is None:
            raise not_found("case", case_id)

    cid = str(case_id)
    current_job = _get_job(cid)
    if current_job and current_job.state in ("queued", "investigating", "verifying"):
        return InvestigationJobResponse(
            case_id=case_id,
            state=current_job.state,
            message=f"Investigation already {current_job.state}",
        )

    _set_job(cid, "queued", "Queued for investigation")
    background_tasks.add_task(_run_investigation_worker, cid, store.engine, settings.duckdb_path)
    return InvestigationJobResponse(
        case_id=case_id,
        state="queued",
        message="Investigation queued successfully",
    )


@router.get(
    "/{case_id}/investigate",
    response_model=InvestigationStatus,
    responses={404: {"description": "Unknown case"}},
)
def get_investigation_status(case_id: UUID, store: Stores) -> InvestigationStatus:
    """Check the real-time or historical investigation status of a case."""
    with Session(store.engine) as session:
        record = session.get(CaseRecord, str(case_id))
        if record is None:
            raise not_found("case", case_id)
        return _get_case_investigation_status(str(case_id), record)


@router.get(
    "/{case_id}/reviews",
    response_model=list[CaseReviewItem],
    responses={404: {"description": "Unknown case"}},
)
def list_case_reviews(case_id: UUID, store: Stores) -> list[CaseReviewItem]:
    """Retrieve full audit history of human reviews and status changes for this case."""
    with Session(store.engine) as session:
        record = session.get(CaseRecord, str(case_id))
        if record is None:
            raise not_found("case", case_id)
        history = get_case_reviews(store.engine, str(case_id))
        return [
            CaseReviewItem(
                id=r.id,
                case_id=r.case_id,
                previous_status=r.previous_status,
                new_status=r.new_status,
                note=r.note,
                reviewer=r.reviewer,
                created_at=r.created_at,
            )
            for r in history
        ]


def _format_case_report_markdown(
    case: Case,
    note: AuditNote | None,
    evidence_rows: list[TransactionRow],
    reviews: list[CaseReviewItem],
    trace: list[TraceStep],
) -> str:
    lines: list[str] = [
        f"# SpendGuard Case Report: {case.case_id}",
        "",
        "## Summary",
        f"- **Case ID:** `{case.case_id}`",
        f"- **Detector:** {case.detector} ({case.anomaly_type})",
        f"- **Severity:** {case.severity_band.upper()} (Preliminary: {case.severity_prelim:.2f}, Final: {case.severity_final or case.severity_prelim:.2f})",
        f"- **Status:** {case.status.replace('_', ' ').title()}",
        f"- **Vendor Key:** {case.vendor_key or 'N/A'}",
        f"- **Amount at Risk:** {settings.currency} {case.amount_at_risk:,.2f}",
        f"- **Created At:** {case.created_at.isoformat() if case.created_at else 'N/A'}",
        "",
        "## Detector Facts",
        f"- **Anomaly Type:** {case.anomaly_type}",
        f"- **Detector Score:** {case.detector_score:.3f}",
        f"- **Involved Row IDs:** {', '.join(str(r) for r in case.row_ids)}",
    ]

    if case.metadata:
        lines.append("- **Detector Details:**")
        for k, v in case.metadata.items():
            lines.append(f"  - `{k}`: {v}")

    lines.extend([
        "",
        "## AI Investigation",
    ])
    if note is None:
        lines.append("*This case has not been investigated by the AI agent yet.*")
    else:
        lines.extend([
            f"- **Verdict:** **{note.verdict.upper()}**",
            f"- **Recommended Action:** {note.recommended_action or 'None'}",
            f"- **Model Used:** `{note.model_name or 'Default'}`",
            f"- **Policy Clauses Cited:** {', '.join(note.policy_clauses) if note.policy_clauses else 'None'}",
            "",
            "### AI Finding",
            note.finding,
        ])

    lines.extend([
        "",
        "## Verification",
    ])
    if note is None:
        lines.append("*No verification performed.*")
    else:
        lines.extend([
            f"- **Overall Status:** {note.verification_status.upper() if note.verification_status else 'UNKNOWN'}",
            f"- **Deterministic Rule Check:** {'PASSED' if note.deterministic_passed else 'FAILED' if note.deterministic_passed is False else 'SKIPPED'}",
            f"- **Semantic Check:** {'PASSED' if note.semantic_passed else 'FAILED' if note.semantic_passed is False else 'SKIPPED'}",
            f"- **Citations Checked:** {note.citations_checked}",
            f"- **Citations Passed:** {note.citations_passed}",
            f"- **Retry Count:** {note.retry_count}",
        ])
        if note.citations:
            lines.extend([
                "",
                "### Evidence Citations",
                "| Claim # | Claim Text | Row ID | Row Exists | Values Match | Supports Claim | Failure Reason |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for c in note.citations:
                c_text = c.claim_text.replace("\n", " ").replace("|", "\\|")
                lines.append(
                    f"| {c.claim_index} | {c_text} | {c.row_id} | "
                    f"{'✓' if c.row_exists else '✗'} | "
                    f"{'✓' if c.values_match else '✗'} | "
                    f"{'✓' if c.supports_claim else '✗'} | "
                    f"{c.failure_reason or '-'} |"
                )

    lines.extend([
        "",
        "## Evidence Transactions",
        f"Showing {len(evidence_rows)} evidence row(s):",
        "",
        "| Row ID | Date | Vendor | Amount | Officer | Category | Description |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])
    for r in evidence_rows:
        lines.append(
            f"| {r.row_id} | {r.txn_date} | {r.vendor_name or r.vendor_key or '-'} | "
            f"{settings.currency} {r.amount:,.2f} | {r.officer_id or '-'} | "
            f"{r.item_category or '-'} | {r.item_desc or '-'} |"
        )

    lines.extend([
        "",
        "## Human Review History",
        f"- **Current Reviewer Note:** {case.reviewer_note or 'None'}",
        "",
    ])
    if not reviews:
        lines.append("*No review actions recorded yet.*")
    else:
        lines.extend([
            "| Date | Reviewer | Previous Status | New Status | Note |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])
        for rev in reviews:
            rev_note = (rev.note or "").replace("\n", " ").replace("|", "\\|")
            lines.append(
                f"| {rev.created_at.strftime('%Y-%m-%d %H:%M:%S')} | {rev.reviewer} | "
                f"{rev.previous_status} | {rev.new_status} | {rev_note} |"
            )

    if trace:
        lines.extend([
            "",
            "## Investigation Trace Summary",
            "*Internal investigation steps (prompts and chain-of-thought omitted for audit privacy).*",
            "",
            "| Step | Role | Tool | Latency (ms) | Tokens (Prompt/Comp) | Error |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for s in trace:
            tokens = f"{s.prompt_tokens or 0}/{s.completion_tokens or 0}"
            lines.append(
                f"| {s.step_index} | {s.role} | {s.tool_name or '-'} | "
                f"{s.latency_ms or 0}ms | {tokens} | {s.error or '-'} |"
            )

    return "\n".join(lines)


@router.get(
    "/{case_id}/export",
    responses={
        200: {
            "content": {"text/markdown": {}, "text/html": {}},
            "description": "Formatted case report",
        },
        404: {"description": "Unknown case"},
    },
)
def export_case_report(
    case_id: UUID,
    store: Stores,
    con: Duck,
    format: Literal["markdown", "html"] = "markdown",
) -> Response:
    """Export an evidence-backed audit report for a case in Markdown or HTML (P1)."""
    with Session(store.engine) as session:
        record = session.get(CaseRecord, str(case_id))
        if record is None:
            raise not_found("case", case_id)
        note_record = latest_note(store.engine, record.case_id)
        note = _note(session, note_record) if note_record else None
        trace = _trace(session, note_record.note_id) if note_record else []
        case = to_case(record)
        review_records = get_case_reviews(store.engine, record.case_id)
        reviews = [
            CaseReviewItem(
                id=r.id,
                case_id=r.case_id,
                previous_status=r.previous_status,
                new_status=r.new_status,
                note=r.note,
                reviewer=r.reviewer,
                created_at=r.created_at,
            )
            for r in review_records
        ]

    case_rows = list(record.row_ids)
    cited = {c.row_id for c in note.citations} if note else set()
    evidence_dicts = fetch_rows(con, case_rows, limit=settings.api_evidence_rows)
    evidence_rows = [to_row(r, True, cited) for r in evidence_dicts]

    md_content = _format_case_report_markdown(case, note, evidence_rows, reviews, trace)

    if format == "html":
        # Convert to a clean standalone HTML document with styling
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SpendGuard Case Report - {case.case_id}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #1e293b; max-width: 960px; margin: 2rem auto; padding: 0 1.5rem; }}
  h1, h2, h3 {{ color: #0f172a; margin-top: 1.5rem; }}
  h1 {{ border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; }}
  h2 {{ border-bottom: 1px solid #e2e8f0; padding-bottom: 0.3rem; margin-top: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.9rem; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 0.5rem 0.75rem; text-align: left; }}
  th {{ background-color: #f1f5f9; font-weight: 600; }}
  code {{ background-color: #f1f5f9; padding: 0.2rem 0.4rem; border-radius: 4px; font-size: 0.85em; }}
  .badge {{ display: inline-block; padding: 0.2rem 0.5rem; border-radius: 4px; font-weight: 600; font-size: 0.85rem; }}
  ul {{ padding-left: 1.5rem; }}
</style>
</head>
<body>
<pre style="white-space: pre-wrap; font-family: inherit;">{md_content}</pre>
</body>
</html>"""
        return HTMLResponse(
            content=html_content,
            headers={"Content-Disposition": f'inline; filename="spendguard-case-{case_id}.html"'},
        )

    return PlainTextResponse(
        content=md_content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="spendguard-case-{case_id}.md"'},
    )

