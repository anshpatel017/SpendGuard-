"""Cases: the queue, one case in full, its evidence, and the review action.

The review action is the only write in the API besides the demo endpoint, and
it is a person's: nothing in the agent layer calls it (D-04, D-07).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

import duckdb
from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, Select, and_, func, select
from sqlalchemy.orm import Session, aliased

from spendguard.api.deps import Duck, Stores, not_found
from spendguard.api.schemas import (
    AnomalyTypeName,
    AuditNote,
    BandName,
    Case,
    CaseDetailResponse,
    CaseListResponse,
    CaseSummary,
    Citation,
    EvidenceResponse,
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
    CaseStatus,
    CitationRecord,
    TraceRecord,
    latest_note,
    set_status,
)

router = APIRouter(prefix="/cases", tags=["cases"])

EXCERPT_CHARS = 180
SORTS = {
    "severity_prelim": CaseRecord.severity_prelim,
    "severity_final": CaseRecord.severity_final,
    "amount_at_risk": CaseRecord.amount_at_risk,
    "created_at": CaseRecord.created_at,
}


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
    severity_band: Annotated[list[BandName] | None, Query()] = None,
    verdict: Annotated[list[VerdictName] | None, Query()] = None,
    verification_status: Annotated[list[VerificationName] | None, Query()] = None,
    investigated: bool | None = None,
    dismissed_by_agent: bool | None = None,
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
    if anomaly_type:
        filters.append(CaseRecord.anomaly_type.in_(anomaly_type))
    if severity_band:
        filters.append(CaseRecord.severity_band.in_(severity_band))
    if verdict:
        filters.append(note.verdict.in_(verdict))
    if verification_status:
        filters.append(note.verification_status.in_(verification_status))
    if investigated is not None:
        filters.append(CaseRecord.investigated.is_(investigated))
    if dismissed_by_agent is not None:
        filters.append(CaseRecord.dismissed_by_agent.is_(dismissed_by_agent))
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
    responses={404: {"description": "Unknown case"}},
)
def update_status(case_id: UUID, body: StatusUpdateRequest, store: Stores) -> Case:
    """The human decision (FR-5.2). The agent never calls this."""
    try:
        set_status(store.engine, str(case_id), CaseStatus(body.status), body.reviewer_note)
    except KeyError:
        raise not_found("case", case_id) from None
    with Session(store.engine) as session:
        record = session.get(CaseRecord, str(case_id))
        assert record is not None
        return to_case(record)
