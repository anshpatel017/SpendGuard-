"""The operational case store and `spendguard detect` (decisions D-07, D-09)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from spendguard.cases import AnomalyType, Case
from spendguard.db.store import (
    CaseRecord,
    CaseStatus,
    RunRecord,
    StoreMismatchError,
    cases_to_investigate,
    get_engine,
    save_cases,
    set_status,
)
from spendguard.detection import EvaluationDatabaseError, run_detection
from spendguard.eval.injection import InjectionResult
from spendguard.pipeline.ingest import IngestResult


def _case(rows: list[int], score: float = 0.9) -> Case:
    return Case.build(
        detector="d1", anomaly_type=AnomalyType.DUPLICATE, row_ids=rows,
        detector_score=score, amount_at_risk=50_000.0, vendor_key="sharma",
    )  # fmt: skip


@pytest.fixture
def store(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}"


def _get(url: str, case_id: str) -> CaseRecord:
    with Session(get_engine(url)) as s:
        record = s.get(CaseRecord, case_id)
        assert record is not None
        return record


def test_new_cases_start_in_new_status(store: str) -> None:
    result = save_cases(get_engine(store), "r1", "ds", [_case([1, 2])])
    assert result.inserted == 1
    record = _get(store, _case([1, 2]).case_id)
    assert record.status == CaseStatus.NEW.value
    assert record.row_ids == [1, 2]
    assert record.severity_band in {"high", "medium", "low"}


def test_rerun_keeps_the_auditors_work(store: str) -> None:
    """Re-running detection must never discard review state."""
    engine = get_engine(store)
    case = _case([1, 2], score=0.9)
    save_cases(engine, "r1", "ds", [case])
    set_status(engine, case.case_id, CaseStatus.CONFIRMED, "Recovery initiated")

    result = save_cases(engine, "r2", "ds", [_case([1, 2], score=0.7)])
    assert (result.inserted, result.refreshed) == (0, 1)
    record = _get(store, case.case_id)
    assert record.status == CaseStatus.CONFIRMED.value
    assert record.reviewer_note == "Recovery initiated"
    assert record.detector_score == 0.7  # detector facts refreshed
    assert record.run_id == "r2"


def test_mixing_datasets_is_refused(store: str) -> None:
    engine = get_engine(store)
    save_cases(engine, "r1", "dataset_a", [_case([1, 2])])
    with pytest.raises(StoreMismatchError):
        save_cases(engine, "r2", "dataset_b", [_case([3, 4])])


def test_reset_clears_the_store(store: str) -> None:
    engine = get_engine(store)
    save_cases(engine, "r1", "dataset_a", [_case([1, 2])])
    result = save_cases(engine, "r2", "dataset_b", [_case([3, 4])], reset=True)
    assert result.total_in_store == 1


def test_status_change_on_unknown_case_is_an_error(store: str) -> None:
    with pytest.raises(KeyError):
        set_status(get_engine(store), "no-such-case", CaseStatus.DISMISSED)


def test_detect_stores_cases_and_records_the_run(store: str, ingested: IngestResult) -> None:
    run = run_detection(ingested.db_path, store_url=store)
    with Session(get_engine(store)) as s:
        stored = s.scalars(select(CaseRecord)).all()
        runs = s.scalars(select(RunRecord)).all()
    assert len(stored) == len(run.cases)
    assert [r.run_id for r in runs] == [run.run_id]
    assert runs[0].summary["cases"] == len(run.cases)


def test_detect_refuses_a_database_with_planted_anomalies(
    store: str, injected: InjectionResult
) -> None:
    """Planted anomalies must never reach the case store as if they were real findings."""
    with pytest.raises(EvaluationDatabaseError):
        run_detection(injected.out_db, store_url=store)


def test_unknown_detector_is_a_clear_error(store: str, ingested: IngestResult) -> None:
    with pytest.raises(KeyError, match="Unknown detector"):
        run_detection(ingested.db_path, ["d9"], store_url=store)


def test_the_store_creates_its_own_directory_like_duckdb_does(tmp_path: Path) -> None:
    """A fresh clone has no `data/processed/`: it is git-ignored, so it exists on
    every machine that has run the pipeline and on none that has just cloned.

    SQLite will not create a missing directory, while DuckDB already does - and
    that asymmetry is how CI failed unnoticed from Phase 5 to Phase 9. Even asking
    the API for its OpenAPI schema builds the case store, so the contract test died
    on `unable to open database file` on every runner while passing on every laptop.
    """
    missing = tmp_path / "data" / "processed" / "nested"
    assert not missing.exists()

    engine = get_engine(f"sqlite:///{(missing / 'cases.sqlite').as_posix()}")
    save_cases(engine, "run-1", "dataset", [_case([1, 2])])

    assert (missing / "cases.sqlite").exists()
    assert cases_to_investigate(engine)


def test_an_in_memory_store_needs_no_directory() -> None:
    """The pattern must not try to mkdir for ':memory:' or a server-backed URL."""
    engine = get_engine("sqlite:///:memory:")
    save_cases(engine, "run-1", "dataset", [_case([1, 2])])
    assert cases_to_investigate(engine)


def test_status_transition_validation_and_review_history() -> None:
    from spendguard.db.store import (
        CaseStatus,
        InvalidTransitionError,
        get_case_reviews,
        set_status,
    )

    engine = get_engine("sqlite:///:memory:")
    case = _case([1, 2])
    save_cases(engine, "run-1", "dataset", [case])

    # Valid: new -> under_review
    set_status(
        engine,
        case.case_id,
        CaseStatus.UNDER_REVIEW,
        note="Reviewing vendor docs",
        reviewer="Auditor Alice",
    )
    reviews = get_case_reviews(engine, case.case_id)
    assert len(reviews) == 1
    assert reviews[0].previous_status == "new"
    assert reviews[0].new_status == "under_review"
    assert reviews[0].note == "Reviewing vendor docs"
    assert reviews[0].reviewer == "Auditor Alice"

    # Valid: under_review -> confirmed
    set_status(
        engine,
        case.case_id,
        CaseStatus.CONFIRMED,
        note="Confirmed duplicate payment",
        reviewer="Auditor Bob",
    )
    reviews = get_case_reviews(engine, case.case_id)
    assert len(reviews) == 2
    assert reviews[1].previous_status == "under_review"
    assert reviews[1].new_status == "confirmed"

    # Invalid: confirmed -> dismissed directly (must go via under_review)
    with pytest.raises(InvalidTransitionError, match="Cannot move case from confirmed to dismissed"):
        set_status(engine, case.case_id, CaseStatus.DISMISSED)

    # Valid: confirmed -> under_review -> dismissed
    set_status(engine, case.case_id, CaseStatus.UNDER_REVIEW, note="Re-evaluating")
    set_status(engine, case.case_id, CaseStatus.DISMISSED, note="Dismissed after check")
    reviews = get_case_reviews(engine, case.case_id)
    assert len(reviews) == 4
    assert reviews[-1].new_status == "dismissed"

