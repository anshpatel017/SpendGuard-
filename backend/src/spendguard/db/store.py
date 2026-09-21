"""Operational case store - SQLite, through SQLAlchemy (decision D-09).

DuckDB holds what was *observed*; this store holds what is being *done* about
it: each case, its status in the review workflow (New -> Under Review ->
Confirmed / Dismissed), the reviewer's note, and the run history.

**Re-running detection never discards review work.** A case's id is derived
from the detector and the rows it covers, so the same anomaly found again maps
to the same case. Its detector fields are refreshed; its status, reviewer note
and investigation state are left untouched.

Investigation results live here too: one audit note per investigation, one
citation row per (claim, cited row), and every step of the agent's trace.

Swapping to PostgreSQL is a one-line change to ``DATABASE_URL``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from spendguard.cases import AnomalyType, Case
from spendguard.config import settings

if TYPE_CHECKING:
    from spendguard.agent.investigator import InvestigationResult


class CaseStatus(StrEnum):
    NEW = "new"
    UNDER_REVIEW = "under_review"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class CaseRecord(Base):
    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(100), index=True)
    run_id: Mapped[str] = mapped_column(String(80), index=True)  # last run that produced it
    anomaly_type: Mapped[str] = mapped_column(String(20), index=True)
    detector: Mapped[str] = mapped_column(String(20))
    row_ids: Mapped[list[int]] = mapped_column(JSON)
    vendor_key: Mapped[str | None] = mapped_column(String(200), index=True)
    detector_score: Mapped[float] = mapped_column(Float)
    amount_at_risk: Mapped[float] = mapped_column(Float)
    severity_prelim: Mapped[float] = mapped_column(Float, index=True)
    severity_final: Mapped[float | None] = mapped_column(Float)
    severity_band: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(20), default=CaseStatus.NEW.value, index=True)
    investigated: Mapped[bool] = mapped_column(Boolean, default=False)
    dismissed_by_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    # "metadata" is reserved on SQLAlchemy models, so the attribute is named details.
    details: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class RunRecord(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    dataset: Mapped[str] = mapped_column(String(100))
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"  # written by the Investigator, not yet checked (Phase 7)
    VERIFIED = "verified"
    FAILED_AFTER_RETRIES = "failed_after_retries"


class AuditNoteRecord(Base):
    """One note per investigation. A case investigated twice keeps both; the newest counts."""

    __tablename__ = "audit_notes"

    note_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(String(80), index=True)
    verdict: Mapped[str] = mapped_column(String(30), index=True)
    finding: Mapped[str] = mapped_column(Text)
    recommended_action: Mapped[str] = mapped_column(Text)
    claims: Mapped[list[dict[str, Any]]] = mapped_column(JSON)  # the structured claims
    policy_clauses: Mapped[list[str]] = mapped_column(JSON, default=list)
    verification_status: Mapped[str] = mapped_column(
        String(30), default=VerificationStatus.UNVERIFIED.value, index=True
    )
    citations_checked: Mapped[int | None] = mapped_column(Integer)
    citations_passed: Mapped[int | None] = mapped_column(Integer)
    deterministic_passed: Mapped[int | None] = mapped_column(Integer)
    semantic_passed: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    model_name: Mapped[str] = mapped_column(String(100))
    is_ablation: Mapped[bool] = mapped_column(Boolean, default=False)
    ablation_name: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CitationRecord(Base):
    """One row per (claim, cited row), so citation validity is a query, not text parsing.

    ``asserted`` holds the field values the claim states about this row; the
    Verifier fills ``row_exists`` / ``values_match`` / ``supports_claim``.
    """

    __tablename__ = "citations"

    citation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    note_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_index: Mapped[int] = mapped_column(Integer)
    claim_text: Mapped[str] = mapped_column(Text)
    row_id: Mapped[int] = mapped_column(Integer, index=True)
    asserted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    row_exists: Mapped[bool | None] = mapped_column(Boolean)
    values_match: Mapped[bool | None] = mapped_column(Boolean)
    supports_claim: Mapped[bool | None] = mapped_column(Boolean)
    failure_reason: Mapped[str | None] = mapped_column(Text)


class TraceRecord(Base):
    """Every step of every investigation, including the ones that failed."""

    __tablename__ = "agent_traces"

    trace_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(String(80), index=True)
    note_id: Mapped[str | None] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(20), default="investigator")
    step_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    tool_name: Mapped[str | None] = mapped_column(String(40))
    tool_args: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    tool_result: Mapped[Any] = mapped_column(JSON)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class StoreMismatchError(RuntimeError):
    """The store already holds cases for a different dataset."""


def get_engine(url: str | None = None) -> Engine:
    engine = create_engine(url or settings.database_url)
    Base.metadata.create_all(engine)
    return engine


@dataclass
class SaveResult:
    inserted: int
    refreshed: int
    total_in_store: int


def save_cases(
    engine: Engine,
    run_id: str,
    dataset: str,
    cases: Sequence[Case],
    *,
    reset: bool = False,
) -> SaveResult:
    """Upsert cases: new ones start as New; existing ones keep their review state."""
    with Session(engine) as session, session.begin():
        others = session.scalar(
            select(func.count()).select_from(CaseRecord).where(CaseRecord.dataset != dataset)
        )
        if others and not reset:
            raise StoreMismatchError(
                f"The case store holds {others} cases from a different dataset. "
                "Re-run with --reset to clear it, or point DATABASE_URL at another store."
            )
        if reset:
            # Notes, citations and traces belong to the cases being cleared.
            for table in (CitationRecord, TraceRecord, AuditNoteRecord, CaseRecord):
                session.execute(delete(table))

        existing = {
            r.case_id: r
            for r in session.scalars(
                select(CaseRecord).where(CaseRecord.case_id.in_([c.case_id for c in cases]))
            )
        }
        inserted = refreshed = 0
        for case in cases:
            record = existing.get(case.case_id)
            if record is None:
                session.add(
                    CaseRecord(
                        case_id=case.case_id,
                        dataset=dataset,
                        run_id=run_id,
                        anomaly_type=case.anomaly_type.value,
                        detector=case.detector,
                        row_ids=list(case.row_ids),
                        vendor_key=case.vendor_key,
                        detector_score=case.detector_score,
                        amount_at_risk=case.amount_at_risk,
                        severity_prelim=case.severity_prelim,
                        severity_band=case.severity_band,
                        details=case.metadata,
                    )
                )
                inserted += 1
            else:
                # Refresh what the detector knows. Leave what the auditor decided alone.
                record.run_id = run_id
                record.detector_score = case.detector_score
                record.amount_at_risk = case.amount_at_risk
                record.severity_prelim = case.severity_prelim
                if not record.investigated:
                    record.severity_band = case.severity_band
                record.details = case.metadata
                refreshed += 1
        session.flush()
        total = session.scalar(select(func.count()).select_from(CaseRecord)) or 0
    return SaveResult(inserted=inserted, refreshed=refreshed, total_in_store=int(total))


def record_run(
    engine: Engine,
    run_id: str,
    kind: str,
    dataset: str,
    config: dict[str, Any],
    summary: dict[str, Any],
    started_at: datetime,
    status: str = "completed",
) -> None:
    with Session(engine) as session, session.begin():
        session.merge(
            RunRecord(
                run_id=run_id,
                kind=kind,
                status=status,
                dataset=dataset,
                config=config,
                summary=summary,
                started_at=started_at,
                finished_at=_now(),
            )
        )


def set_status(
    engine: Engine, case_id: str, status: CaseStatus, note: str | None = None
) -> CaseRecord:
    """The human-in-the-loop action (decision D-07). Only people call this, never the agent.

    ``note=None`` leaves the reviewer's note as it is; an empty or blank note
    clears it - to null, never to an empty string (API-CONTRACT: explicit nulls).
    """
    with Session(engine, expire_on_commit=False) as session, session.begin():
        record = session.get(CaseRecord, case_id)
        if record is None:
            raise KeyError(f"No case {case_id}")
        record.status = status.value
        if note is not None:
            record.reviewer_note = note.strip() or None
    return record


# ------------------------------------------------------------------ investigation

# Tool results are stored for the trace view, capped so one 50-row query cannot
# bloat the store. The cap is recorded, never silent.
TRACE_RESULT_CHARS = 20_000


def _trace_result(value: Any) -> Any:
    text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= TRACE_RESULT_CHARS:
        return json.loads(text)  # a JSON-safe copy: dates become strings
    return {"truncated": True, "chars": len(text), "head": text[:TRACE_RESULT_CHARS]}


def case_from_record(record: CaseRecord) -> Case:
    """Rebuild the detector's case from its stored form, for investigation."""
    return Case(
        case_id=record.case_id,
        anomaly_type=AnomalyType(record.anomaly_type),
        detector=record.detector,
        row_ids=tuple(record.row_ids),
        detector_score=record.detector_score,
        amount_at_risk=record.amount_at_risk,
        severity_prelim=record.severity_prelim,
        vendor_key=record.vendor_key,
        metadata=record.details or {},
    )


def cases_to_investigate(
    engine: Engine,
    *,
    top_n: int | None = None,
    anomaly_type: str | None = None,
    case_ids: Sequence[str] | None = None,
    include_investigated: bool = False,
) -> list[Case]:
    """Highest preliminary severity first: investigation is top-N (decision D-05).

    Cases a person has already confirmed or dismissed are skipped - model time
    is not spent second-guessing a decision already made. Naming case ids
    explicitly overrides every filter.
    """
    query = select(CaseRecord)
    if case_ids:
        query = query.where(CaseRecord.case_id.in_(list(case_ids)))
    else:
        if not include_investigated:
            query = query.where(CaseRecord.investigated.is_(False))
        if anomaly_type:
            query = query.where(CaseRecord.anomaly_type == anomaly_type)
        query = query.where(
            CaseRecord.status.in_([CaseStatus.NEW.value, CaseStatus.UNDER_REVIEW.value])
        )
    query = query.order_by(CaseRecord.severity_prelim.desc(), CaseRecord.case_id)
    if top_n is not None and not case_ids:
        query = query.limit(top_n)
    with Session(engine) as session:
        return [case_from_record(r) for r in session.scalars(query)]


def save_investigation(
    engine: Engine,
    run_id: str,
    result: InvestigationResult,
    *,
    ablation_name: str | None = None,
) -> str | None:
    """Store the note, its citations and the full trace. Returns the note id, if any.

    The case is marked investigated and its final severity set, but its review
    status is never changed: the agent recommends, a person decides (D-04). A
    failed investigation stores its trace - that is what explains the failure -
    and leaves the case uninvestigated. An ablation run stores its note for
    comparison and leaves the case alone.
    """
    note_id: str | None = None
    report = result.verification
    with Session(engine) as session, session.begin():
        if result.note is not None:
            note_id = str(uuid.uuid4())
            session.add(
                AuditNoteRecord(
                    note_id=note_id,
                    case_id=result.case_id,
                    run_id=run_id,
                    verdict=result.note.verdict.value,
                    finding=result.note.finding,
                    recommended_action=result.note.recommended_action,
                    claims=[c.model_dump(mode="json") for c in result.note.claims],
                    policy_clauses=list(result.note.policy_clauses),
                    verification_status=result.verification_status,
                    citations_checked=report.checked if report else None,
                    citations_passed=report.citations_passed if report else None,
                    deterministic_passed=report.deterministic_passed if report else None,
                    semantic_passed=report.semantic_passed if report else None,
                    retry_count=result.retry_count,
                    model_name=result.model,
                    is_ablation=ablation_name is not None,
                    ablation_name=ablation_name,
                )
            )
            checks = {(c.claim_index, c.row_id): c for c in report.citations} if report else {}
            for citation in result.note.citations():
                check = checks.get((citation.claim_index, citation.row_id))
                session.add(
                    CitationRecord(
                        citation_id=str(uuid.uuid4()),
                        note_id=note_id,
                        claim_index=citation.claim_index,
                        claim_text=citation.claim_text,
                        row_id=citation.row_id,
                        asserted=_trace_result(citation.asserted),
                        row_exists=check.row_exists if check else None,
                        values_match=check.values_match if check else None,
                        supports_claim=check.supports_claim if check else None,
                        failure_reason=check.failure_reason if check else None,
                    )
                )
        for step in result.trace:
            session.add(
                TraceRecord(
                    trace_id=str(uuid.uuid4()),
                    case_id=result.case_id,
                    run_id=run_id,
                    note_id=note_id,
                    step_index=step.step_index,
                    role=step.role,
                    kind=step.kind,
                    tool_name=step.tool_name,
                    tool_args=_trace_result(step.tool_args),
                    tool_result=_trace_result(step.tool_result),
                    latency_ms=step.latency_ms,
                    prompt_tokens=step.prompt_tokens,
                    completion_tokens=step.completion_tokens,
                    detail=step.note,
                    error=step.error,
                )
            )
        if note_id is not None and ablation_name is None:
            record = session.get(CaseRecord, result.case_id)
            if record is not None:
                record.investigated = True
                record.severity_final = result.severity_final
                if result.severity_band is not None:
                    record.severity_band = result.severity_band
                record.dismissed_by_agent = result.dismissed_by_agent
    return note_id


def latest_note(
    engine: Engine, case_id: str, *, model_name: str | None = None
) -> AuditNoteRecord | None:
    """The note that currently stands for a case: newest, ablations excluded.

    With ``model_name``, the newest note by that model - so an evaluation of one
    model is never scored on notes another model wrote.
    """
    query = select(AuditNoteRecord).where(
        AuditNoteRecord.case_id == case_id, AuditNoteRecord.is_ablation.is_(False)
    )
    if model_name is not None:
        query = query.where(AuditNoteRecord.model_name == model_name)
    with Session(engine, expire_on_commit=False) as session:
        return session.scalars(query.order_by(AuditNoteRecord.created_at.desc()).limit(1)).first()
