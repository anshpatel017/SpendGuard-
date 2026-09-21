"""Storing investigations, choosing which cases to investigate, and scoring triage.

The model is scripted (see test_investigator.py), so these run offline: they
test what SpendGuard does with a note, not what a model writes.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from spendguard.agent.investigator import InvestigationResult, TraceStep
from spendguard.agent.llm import LLMQuotaExhaustedError
from spendguard.agent.note import InvestigatorNote, Verdict
from spendguard.agent.verifier import JUDGE_PROMPT
from spendguard.cases import AnomalyType, Case
from spendguard.db.store import (
    AuditNoteRecord,
    CaseRecord,
    CaseStatus,
    CitationRecord,
    RunRecord,
    TraceRecord,
    VerificationStatus,
    case_from_record,
    cases_to_investigate,
    get_engine,
    latest_note,
    save_cases,
    save_investigation,
    set_status,
)
from spendguard.detection import EvaluationDatabaseError, run_detection
from spendguard.eval.injection import InjectionResult
from spendguard.eval.matching import TruthGroup
from spendguard.eval.triage import TriageItem, triage_metrics
from spendguard.investigation import evaluate_investigation, run_investigation, sample_for_triage
from spendguard.pipeline.ingest import IngestResult

from .conftest import build_db
from .test_investigator import ScriptedModel, note, reply


def _case(
    rows: list[int], amount: float = 50_000.0, kind: str = "duplicate", score: float = 0.9
) -> Case:
    return Case.build(
        detector="d1", anomaly_type=AnomalyType(kind), row_ids=rows,
        detector_score=score, amount_at_risk=amount, vendor_key="sharma",
    )  # fmt: skip


def _note(verdict: Verdict = Verdict.LIKELY_TRUE_POSITIVE) -> InvestigatorNote:
    return InvestigatorNote.model_validate(
        {
            "verdict": verdict.value,
            "finding": "Rows 1 and 2 record the same obligation twice.",
            "claims": [
                {
                    "text": "Both rows are for Rs 50,000.",
                    "row_ids": [1, 2],
                    "facts": [
                        {"row_id": 1, "field": "amount", "value": 50000.0},
                        {"row_id": 2, "field": "amount", "value": 50000.0},
                    ],
                },
                {"text": "Same supplier.", "row_ids": [2]},
            ],
            "policy_clauses": ["SG-PP-4.4"],
            "recommended_action": "Hold payment on row 2.",
        }
    )


def _result(case: Case, note: InvestigatorNote | None, severity: float | None = 20.0) -> Any:
    return InvestigationResult(
        case_id=case.case_id,
        anomaly_type=case.anomaly_type.value,
        status="completed" if note else "failed",
        model="scripted",
        note=note,
        severity_final=severity if note else None,
        severity_band="low" if note else None,
        trace=[
            TraceStep(0, "model", prompt_tokens=900, note="requested calculator"),
            TraceStep(
                1,
                "tool",
                tool_name="calculator",
                tool_args={"expression": "1+1"},
                tool_result={"result": 2.0},
            ),
        ],
        error=None if note else "groq unreachable",
    )


@pytest.fixture
def engine(tmp_path: Path) -> Any:
    return get_engine(f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")


def _count(engine: Any, table: Any) -> int:
    with Session(engine) as s:
        return int(s.scalar(select(func.count()).select_from(table)) or 0)


# ------------------------------------------------------------------ persistence


def test_a_note_is_stored_with_one_citation_per_claim_and_row(engine: Any) -> None:
    case = _case([1, 2])
    save_cases(engine, "d", "ds", [case])
    note_id = save_investigation(engine, "inv-1", _result(case, _note()))

    stored = latest_note(engine, case.case_id)
    assert stored is not None and stored.note_id == note_id
    assert stored.verification_status == VerificationStatus.UNVERIFIED.value
    assert stored.claims[0]["row_ids"] == [1, 2]
    with Session(engine) as s:
        citations = s.scalars(select(CitationRecord).order_by(CitationRecord.claim_index)).all()
    assert [(c.claim_index, c.row_id) for c in citations] == [(0, 1), (0, 2), (1, 2)]
    assert citations[0].asserted == {"amount": 50000.0}
    assert citations[2].asserted == {}
    assert _count(engine, TraceRecord) == 2


def test_investigating_updates_severity_but_never_the_review_status(engine: Any) -> None:
    """D-04: the agent recommends; only a person moves a case."""
    case = _case([1, 2], amount=5_000_000)
    save_cases(engine, "d", "ds", [case])
    save_investigation(engine, "inv-1", _result(case, _note(Verdict.LIKELY_FALSE_POSITIVE)))

    with Session(engine) as s:
        record = s.get(CaseRecord, case.case_id)
        assert record is not None
        assert record.investigated and record.dismissed_by_agent
        assert record.severity_final == 20.0 and record.severity_band == "low"
        assert record.status == CaseStatus.NEW.value


def test_a_failed_investigation_keeps_its_trace_and_leaves_the_case_open(engine: Any) -> None:
    case = _case([1, 2])
    save_cases(engine, "d", "ds", [case])
    assert save_investigation(engine, "inv-1", _result(case, None)) is None

    assert _count(engine, AuditNoteRecord) == 0
    assert _count(engine, TraceRecord) == 2  # the trace is what explains the failure
    assert cases_to_investigate(engine) == [case]  # still waiting


def test_an_ablation_note_is_kept_apart_from_the_case(engine: Any) -> None:
    case = _case([1, 2])
    save_cases(engine, "d", "ds", [case])
    save_investigation(engine, "abl-1", _result(case, _note()), ablation_name="no_tools")

    assert latest_note(engine, case.case_id) is None
    with Session(engine) as s:
        record = s.get(CaseRecord, case.case_id)
        assert record is not None and not record.investigated


def test_rerunning_detection_keeps_the_investigation(engine: Any) -> None:
    case = _case([1, 2])
    save_cases(engine, "d1", "ds", [case])
    save_investigation(engine, "inv-1", _result(case, _note(Verdict.LIKELY_FALSE_POSITIVE)))
    save_cases(engine, "d2", "ds", [case])
    with Session(engine) as s:
        record = s.get(CaseRecord, case.case_id)
        assert record is not None and record.investigated and record.severity_band == "low"


def test_resetting_the_store_clears_notes_with_their_cases(engine: Any) -> None:
    case = _case([1, 2])
    save_cases(engine, "d", "ds", [case])
    save_investigation(engine, "inv-1", _result(case, _note()))
    save_cases(engine, "d", "other", [_case([3, 4])], reset=True)
    for table in (AuditNoteRecord, CitationRecord, TraceRecord):
        assert _count(engine, table) == 0


def test_a_stored_case_rebuilds_exactly() -> None:
    case = _case([3, 1, 2])
    record = CaseRecord(
        case_id=case.case_id, anomaly_type="duplicate", detector="d1", row_ids=[1, 2, 3],
        detector_score=0.9, amount_at_risk=case.amount_at_risk,
        severity_prelim=case.severity_prelim, vendor_key="sharma", details={},
    )  # fmt: skip
    assert case_from_record(record) == case


# ------------------------------------------------------------------ what gets investigated


def test_the_highest_severity_uninvestigated_open_cases_go_first(engine: Any) -> None:
    small, big, huge, decided = (
        _case([1, 2], 10_000),
        _case([3, 4], 1_000_000),
        _case([5, 6], 9_000_000),
        _case([7, 8], 8_000_000),
    )
    save_cases(engine, "d", "ds", [small, big, huge, decided])
    set_status(engine, decided.case_id, CaseStatus.CONFIRMED)
    save_investigation(engine, "inv-1", _result(huge, _note()))

    assert cases_to_investigate(engine, top_n=5) == [big, small]
    assert cases_to_investigate(engine, top_n=1) == [big]
    assert cases_to_investigate(engine, include_investigated=True)[0] == huge
    assert cases_to_investigate(engine, anomaly_type="split") == []
    assert cases_to_investigate(engine, case_ids=[decided.case_id]) == [decided]


# ------------------------------------------------------------------ triage


def test_triage_separates_the_costly_error_from_the_cheap_one() -> None:
    items = [
        TriageItem("split", True, "likely_true_positive"),
        TriageItem("split", True, "likely_false_positive"),  # hides a real scheme
        TriageItem("split", False, "likely_false_positive"),  # filtered: the contribution
        TriageItem("split", False, "likely_true_positive"),  # passed on: costs a review
        TriageItem("inflation", False, "inconclusive"),
        TriageItem("inflation", True, None),  # no note
    ]
    m = triage_metrics(items)
    assert m["split"]["real_kept"] == 0.5
    assert m["split"]["real_wrongly_dismissed"] == 0.5
    assert m["split"]["spurious_filtered"] == 0.5
    assert m["split"]["decisive_accuracy"] == 0.5
    assert m["inflation"]["spurious_filtered"] == 0.0
    assert m["inflation"]["failed"] == 0.5 and m["inflation"]["inconclusive"] == 0.5
    assert m["all"]["cases"] == 6 and list(m)[-1] == "all"
    assert m["inflation"]["confusion"]["real"]["failed"] == 1  # type: ignore[index]


def test_a_rate_with_nothing_to_measure_is_none_not_zero() -> None:
    m = triage_metrics([TriageItem("vendor_flag", True, "likely_true_positive")])
    assert m["vendor_flag"]["spurious_filtered"] is None


def test_real_fraud_caught_under_another_label_is_not_scored_as_a_false_alarm() -> None:
    """Seen live: D2 flagged a planted duplicate pair as a split. The agent called it
    genuine - rightly - so it must not count as a false alarm the agent failed to filter."""
    duplicate = TruthGroup("g1", AnomalyType.DUPLICATE, frozenset({1, 2}), "acme", 50_000.0)
    split_on_duplicate = _case([1, 2], kind="split")
    clean_split = _case([30, 31], kind="split")

    _, truth = sample_for_triage([split_on_duplicate, clean_split], [duplicate], 2, seed=7)
    assert split_on_duplicate.case_id not in truth  # neither real nor spurious
    assert truth[clean_split.case_id] is False


def test_triage_sampling_leaves_out_redundant_alerts_and_is_seeded() -> None:
    group = TruthGroup("g1", AnomalyType.SPLIT, frozenset({1, 2, 3}), "acme", 300_000.0)
    real = _case([1, 2, 3], kind="split", score=0.95)
    redundant = _case([2, 3], kind="split", score=0.9)  # a second alert on the same scheme
    spurious = [_case([10 + i, 20 + i], kind="split") for i in range(5)]
    cases = [real, redundant, *spurious]

    chosen, truth = sample_for_triage(cases, [group], per_type=2, seed=7)
    assert truth[real.case_id] is True
    assert redundant.case_id not in truth
    assert sum(1 for v in truth.values() if not v) == 2
    assert sample_for_triage(cases, [group], per_type=2, seed=7) == (chosen, truth)


# ------------------------------------------------------------------ orchestration


class CitesFirstRow(ScriptedModel):
    """Writes a valid note citing the first evidence row, and as judge supports every claim.

    ``quota`` is how many calls it answers before the provider's daily quota runs
    out; ``None`` means it never does. A verified case costs two: note, judgement.
    """

    def __init__(self, verdict: str = "likely_true_positive", quota: int | None = None) -> None:
        super().__init__([])
        self.verdict = verdict
        self.quota = quota

    def chat(self, messages: Any, tools: Any = None, **kw: Any) -> Any:
        if self.quota is not None:
            if self.quota == 0:
                raise LLMQuotaExhaustedError("tokens per day: try again in 21m22s")
            self.quota -= 1
        if messages[0]["content"] == JUDGE_PROMPT:
            self.turns = [reply('{"claims":[{"index":0,"supported":true,"reason":"shown"}]}')]
        else:
            found = re.search(r'\{"row_id":(\d+),.*?"amount":([\d.]+)', messages[1]["content"])
            assert found is not None
            row_id, amount = int(found.group(1)), float(found.group(2))
            self.turns = [note([row_id], self.verdict, amount=amount)]
        return super().chat(messages, tools, **kw)


def test_investigate_writes_notes_and_a_run_record(tmp_path: Path, ingested: IngestResult) -> None:
    store = f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}"
    db = tmp_path / "clean.duckdb"
    shutil.copy(ingested.db_path, db)
    detected = run_detection(db, store_url=store)
    if not detected.cases:
        save_cases(get_engine(store), "d", "ds", [_case([1, 2])])

    seen: list[str] = []
    run = run_investigation(
        top_n=2, db_path=db, store_url=store, llm=CitesFirstRow(),
        on_result=lambda i, n, c, r: seen.append(c.case_id),
    )  # fmt: skip

    assert run.summary()["completed"] == len(seen) == len(run.results) >= 1
    engine = get_engine(store)
    assert _count(engine, AuditNoteRecord) == len(seen)
    with Session(engine) as s:
        record = s.scalars(select(RunRecord).where(RunRecord.kind == "investigate")).one()
        assert record.summary["completed"] == len(seen)
        assert record.config["model"] == "scripted"


def test_investigate_refuses_a_database_with_planted_anomalies(
    tmp_path: Path, injected: InjectionResult
) -> None:
    store = f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}"
    save_cases(get_engine(store), "d", "ds", [_case([1, 2])])
    with pytest.raises(EvaluationDatabaseError):
        run_investigation(db_path=injected.out_db, store_url=store, llm=CitesFirstRow())


def test_evaluation_mode_scores_triage_in_its_own_store(
    tmp_path: Path, injected: InjectionResult
) -> None:
    run = evaluate_investigation(
        11, per_type=1, db_path=injected.out_db, report_dir=tmp_path, llm=CitesFirstRow()
    )
    assert run.results and run.triage["all"]["cases"] == len(run.results)
    assert run.triage["all"]["real_kept"] in (1.0, None)  # the scripted agent keeps everything
    md, js = run.report_paths
    assert md.exists() and js.exists()
    assert (tmp_path / "investigation_seed11.sqlite").exists()


def test_a_spent_quota_stops_the_run_and_the_next_run_carries_on(tmp_path: Path) -> None:
    """Free tier: ~10 investigations a day. The rest must wait, not fail one by one."""
    store = f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}"
    build_db(tmp_path / "clean.duckdb", [{"amount": 1000.0 + i} for i in range(8)]).close()
    engine = get_engine(store)
    save_cases(engine, "d", "ds", [_case([1, 2], 3e6), _case([3, 4], 2e6), _case([5, 6], 1e6)])

    first = run_investigation(
        db_path=tmp_path / "clean.duckdb", store_url=store, llm=CitesFirstRow(quota=2)
    )
    assert first.quota_stopped
    assert [r.status for r in first.results] == ["completed", "failed"]
    assert first.not_attempted == 1
    assert len(cases_to_investigate(engine)) == 2  # the cut-short case is still waiting

    second = run_investigation(
        db_path=tmp_path / "clean.duckdb", store_url=store, llm=CitesFirstRow()
    )
    assert second.summary()["completed"] == 2 and not second.quota_stopped
    assert cases_to_investigate(engine) == []


def test_evaluation_resumes_its_sample_and_never_scores_a_quota_stop(
    tmp_path: Path, injected: InjectionResult
) -> None:
    def evaluate(llm: CitesFirstRow) -> Any:
        return evaluate_investigation(
            11, per_type=1, db_path=injected.out_db, report_dir=tmp_path, llm=llm
        )

    first = evaluate(CitesFirstRow(quota=1))
    assert first.quota_stopped and first.investigated_so_far == 1
    assert first.triage["all"]["failed"] == 0.0  # the quota, not the agent, stopped the rest
    assert "Stopped early" in first.report_paths[0].read_text(encoding="utf-8")

    second = evaluate(CitesFirstRow())
    assert len(second.results) == first.sampled - 1  # only what was left
    assert second.investigated_so_far == second.sampled == first.sampled


def test_an_evaluation_counts_only_notes_by_its_own_model(
    tmp_path: Path, injected: InjectionResult
) -> None:
    """Groq and Gemini notes share the store but never one number (D-33)."""
    first = evaluate_investigation(
        11, per_type=1, db_path=injected.out_db, report_dir=tmp_path, llm=CitesFirstRow()
    )
    assert first.investigated_so_far == first.sampled

    other_model = CitesFirstRow()
    other_model.model = "gemini-2.5-flash"
    second = evaluate_investigation(
        11, per_type=1, db_path=injected.out_db, report_dir=tmp_path, llm=other_model
    )
    assert len(second.results) == first.sampled  # none of the scripted model's notes count
    assert {r.model for r in second.results} == {"gemini-2.5-flash"}
