"""Operational case store - SQLite, through SQLAlchemy (decision D-09).

DuckDB holds what was *observed*; this store holds what is being *done* about
it: each case, its status in the review workflow (New -> Under Review ->
Confirmed / Dismissed), the reviewer's note, and the run history.

**Re-running detection never discards review work.** A case's id is derived
from the detector and the rows it covers, so the same anomaly found again maps
to the same case. Its detector fields are refreshed; its status, reviewer note
and investigation state are left untouched.

Swapping to PostgreSQL is a one-line change to ``DATABASE_URL``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    String,
    Text,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from spendguard.cases import Case
from spendguard.config import settings


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
            session.execute(delete(CaseRecord))

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
    """The human-in-the-loop action (decision D-07). Only people call this, never the agent."""
    with Session(engine, expire_on_commit=False) as session, session.begin():
        record = session.get(CaseRecord, case_id)
        if record is None:
            raise KeyError(f"No case {case_id}")
        record.status = status.value
        if note is not None:
            record.reviewer_note = note
    return record
