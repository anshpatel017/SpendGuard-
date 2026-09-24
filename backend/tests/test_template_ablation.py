"""The template-notes ablation: what a detector's output alone can and cannot say.

Offline. Nothing here writes prose with a model - that is the point of the arm -
and the judge is scripted, so these tests pin down the arm's mechanics: the note
states only values the rows hold, it cites only clauses the policy has, it never
dismisses anything, and it is stored apart from the agent's own notes.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest
from sqlalchemy.orm import Session

from spendguard.ablations import NO_VERIFIER, TEMPLATE
from spendguard.agent.checks import check_citations
from spendguard.agent.llm import LLMResponse
from spendguard.agent.note import Verdict
from spendguard.agent.template import CLAUSES, template_note
from spendguard.agent.verifier import JUDGE_PROMPT, UNVERIFIED, VERIFIED, known_clause_ids
from spendguard.cases import AnomalyType, Case
from spendguard.db.store import CaseRecord, get_engine, latest_note
from spendguard.eval.injection import InjectionResult
from spendguard.investigation import evaluate_investigation

from .conftest import build_db
from .test_investigation import CitesFirstRow

DAY0 = date(2025, 4, 1)


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    rows: list[dict[str, object]] = [
        {"vendor_name": "Sharma Traders", "amount": 87450.0, "txn_date": DAY0,
         "invoice_no": "INV-04471", "item_desc": "Office Chair", "quantity": 10.0,
         "unit_price": 8745.0},
        {"vendor_name": "Sharma Traders", "amount": 87449.0, "txn_date": DAY0 + timedelta(days=6),
         "invoice_no": "4471/2025", "item_desc": "Office Chair", "quantity": 10.0,
         "unit_price": 8744.9},
        {"vendor_name": "Sharma Traders", "amount": 240000.0, "txn_date": DAY0 + timedelta(days=2),
         "invoice_no": None, "item_desc": "Laptop", "quantity": None, "unit_price": None},
    ]  # fmt: skip
    return build_db(tmp_path / "t.duckdb", rows)


def _rows(con: duckdb.DuckDBPyConnection, row_ids: list[int]) -> list[dict[str, Any]]:
    from spendguard.agent.tools import AUDIT_FIELDS, AUDIT_VIEW

    return (
        con.execute(
            f"SELECT {', '.join(AUDIT_FIELDS)} FROM {AUDIT_VIEW} "
            "WHERE row_id IN (SELECT unnest(?)) ORDER BY row_id",
            [row_ids],
        )
        .pl()
        .to_dicts()
    )


def _case(kind: AnomalyType, row_ids: list[int]) -> Case:
    return Case.build(
        detector={AnomalyType.DUPLICATE: "d1", AnomalyType.SPLIT: "d2",
                  AnomalyType.INFLATION: "d3", AnomalyType.VENDOR_FLAG: "d4"}[kind],
        anomaly_type=kind, row_ids=row_ids, detector_score=0.9,
        amount_at_risk=87450.0, vendor_key="sharma",
    )  # fmt: skip


EVERY_TYPE = [
    (AnomalyType.DUPLICATE, [1, 2]),
    (AnomalyType.SPLIT, [1, 2]),
    (AnomalyType.INFLATION, [3]),  # no unit price or quantity: the sparse-row path
    (AnomalyType.VENDOR_FLAG, [1, 2, 3]),
]


@pytest.mark.parametrize(("kind", "row_ids"), EVERY_TYPE, ids=lambda v: getattr(v, "value", ""))
def test_a_template_note_states_only_values_its_rows_actually_hold(
    con: duckdb.DuckDBPyConnection, kind: AnomalyType, row_ids: list[int]
) -> None:
    """The arm's whole claim to fairness: it copies, so the hard check must pass."""
    note = template_note(_case(kind, row_ids), _rows(con, row_ids))
    report = check_citations(con, note, known_clause_ids())

    assert report.checked == report.deterministic_passed > 0
    assert report.note_problems == []
    assert not report.failures


def test_a_template_note_cites_only_clauses_the_policy_has() -> None:
    known = known_clause_ids()
    assert set(AnomalyType) == set(CLAUSES)
    missing = {c for ids in CLAUSES.values() for c in ids} - known
    assert not missing, f"policy.md has no {sorted(missing)}"


@pytest.mark.parametrize(("kind", "row_ids"), EVERY_TYPE, ids=lambda v: getattr(v, "value", ""))
def test_the_template_never_dismisses_a_case(
    con: duckdb.DuckDBPyConnection, kind: AnomalyType, row_ids: list[int]
) -> None:
    """It cannot weigh an innocent explanation, so it agrees with the detector every time.

    That is the ablation's finding, not a bug: triage is what the agent adds.
    """
    note = template_note(_case(kind, row_ids), _rows(con, row_ids))
    assert note.verdict is Verdict.LIKELY_TRUE_POSITIVE


def test_a_case_with_no_surviving_rows_is_refused(con: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(ValueError, match="no evidence rows"):
        template_note(_case(AnomalyType.DUPLICATE, [9999]), [])


# ------------------------------------------------------------ the arm end to end


class AgreesWithEveryClaim(CitesFirstRow):
    """As judge, supports every claim it is shown, however many there are."""

    def chat(self, messages: Any, tools: Any = None, **kw: Any) -> Any:
        if messages[0]["content"] != JUDGE_PROMPT:
            return super().chat(messages, tools, **kw)
        found = re.findall(r"^\[(\d+)\] ", messages[1]["content"], re.MULTILINE)
        claims = [{"index": int(i), "supported": True, "reason": "shown"} for i in found]
        return LLMResponse(content=json.dumps({"claims": claims}))


def _store(report_dir: Path) -> Any:
    return get_engine(f"sqlite:///{(report_dir / 'investigation_seed11.sqlite').as_posix()}")


def test_the_template_arm_is_stored_apart_and_leaves_the_cases_untouched(
    tmp_path: Path, injected: InjectionResult
) -> None:
    """An arm's notes are evidence about the arm, never the finding an auditor reads."""
    run = evaluate_investigation(
        11, per_type=1, db_path=injected.out_db, report_dir=tmp_path,
        llm=AgreesWithEveryClaim(), ablation=TEMPLATE,
    )  # fmt: skip

    assert run.run_id.endswith(f"-{TEMPLATE}")
    assert run.results and {r.model for r in run.results} == {TEMPLATE}
    assert {r.status for r in run.results} == {"completed"}
    assert {r.verification_status for r in run.results} <= {VERIFIED, UNVERIFIED}

    engine = _store(tmp_path)
    with Session(engine) as session:
        cases = {c.case_id: c for c in session.query(CaseRecord).all()}
    for result in run.results:
        assert latest_note(engine, result.case_id) is None  # not the case's own note
        stored = latest_note(engine, result.case_id, ablation_name=TEMPLATE)
        assert stored is not None and stored.is_ablation
        assert cases[result.case_id].investigated is False
        assert cases[result.case_id].severity_final is None
    assert f"Ablation arm: **{TEMPLATE}**" in run.report_paths[0].read_text(encoding="utf-8")


def test_the_template_arm_is_scored_on_its_own_notes_and_resumes_like_any_run(
    tmp_path: Path, injected: InjectionResult
) -> None:
    def arm() -> Any:
        return evaluate_investigation(
            11, per_type=1, db_path=injected.out_db, report_dir=tmp_path,
            llm=AgreesWithEveryClaim(), ablation=TEMPLATE,
        )  # fmt: skip

    first = arm()
    assert first.investigated_so_far == first.sampled == len(first.results)
    assert first.triage["all"]["real_kept"] in (1.0, None)  # it keeps everything, by construction

    second = arm()
    assert second.results == []  # nothing left: the arm's own notes are already there
    assert second.investigated_so_far == second.sampled


def test_the_agent_and_the_template_do_not_see_each_others_notes(
    tmp_path: Path, injected: InjectionResult
) -> None:
    agent = evaluate_investigation(
        11, per_type=1, db_path=injected.out_db, report_dir=tmp_path, llm=CitesFirstRow()
    )
    template = evaluate_investigation(
        11, per_type=1, db_path=injected.out_db, report_dir=tmp_path,
        llm=AgreesWithEveryClaim(), ablation=TEMPLATE,
    )  # fmt: skip

    assert len(template.results) == agent.sampled  # the agent's notes did not count as done
    engine = _store(tmp_path)
    for result in template.results:
        own = latest_note(engine, result.case_id)
        assert own is not None and own.model_name == "scripted"  # still the agent's


def test_running_with_the_verifier_off_is_an_arm_of_its_own(
    tmp_path: Path, injected: InjectionResult
) -> None:
    """FR-7.8 off-switch: unverified notes must not replace the verified ones."""
    verified = evaluate_investigation(
        11, per_type=1, db_path=injected.out_db, report_dir=tmp_path, llm=CitesFirstRow()
    )
    ablated = evaluate_investigation(
        11, per_type=1, db_path=injected.out_db, report_dir=tmp_path,
        llm=CitesFirstRow(), verify=False,
    )  # fmt: skip

    assert ablated.run_id.endswith(f"-{NO_VERIFIER}")
    assert len(ablated.results) == verified.sampled
    assert {r.verification_status for r in ablated.results} == {UNVERIFIED}
    engine = _store(tmp_path)
    for result in ablated.results:
        own = latest_note(engine, result.case_id)
        assert own is not None and own.verification_status != UNVERIFIED
        assert latest_note(engine, result.case_id, ablation_name=NO_VERIFIER) is not None


def test_an_unknown_arm_is_refused_before_anything_runs(
    tmp_path: Path, injected: InjectionResult
) -> None:
    with pytest.raises(ValueError, match="unknown ablation"):
        evaluate_investigation(
            11, db_path=injected.out_db, report_dir=tmp_path, llm=CitesFirstRow(), ablation="hunch"
        )
