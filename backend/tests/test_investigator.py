"""The Investigator loop, driven by a scripted model - no network, fully deterministic.

Each test scripts the model's turns and checks what the loop does with them:
runs the tools it asks for, feeds errors back, retries malformed notes, stops at
the step limit, keeps the conversation inside the token budget, and records
every step in the trace.
"""

from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from spendguard.agent.investigator import (
    MAX_PARSE_RETRIES,
    InvestigationResult,
    Investigator,
    final_severity,
)
from spendguard.agent.llm import LLMCallError, LLMRequestTooLargeError, LLMResponse, ToolCall
from spendguard.agent.note import Verdict
from spendguard.agent.prompts import case_brief, system_prompt
from spendguard.agent.tools import ToolBox
from spendguard.cases import AnomalyType, Case
from spendguard.config import SeverityBand, settings

from .conftest import build_db

DAY0 = date(2025, 4, 1)


class FakePolicyIndex:
    class _Match:
        def __init__(self, clause_id: str) -> None:
            self.clause_id = clause_id

        def as_dict(self) -> dict[str, Any]:
            return {"clause_id": self.clause_id, "title": "T", "section": "S", "text": "body"}

    def search(self, query: str, k: int = 3) -> list[Any]:
        return [self._Match("SG-PP-4.4")][:k]


class ScriptedModel:
    """Replays scripted turns and records every request it was sent.

    Reports prompt tokens at three characters each, so the Investigator's
    calibration settles on a known ratio and budget tests are exact.
    """

    model = "scripted"

    def __init__(self, turns: list[Any]) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: str = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.requests.append({"messages": copy.deepcopy(messages), "tool_choice": tool_choice})
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        sent = len(json.dumps(messages, default=str)) + len(json.dumps(tools or []))
        return LLMResponse(
            content=turn.content,
            tool_calls=turn.tool_calls,
            prompt_tokens=sent // 3,
            completion_tokens=20,
            latency_seconds=0.01,
        )


def tools(*calls: tuple[str, dict[str, Any]]) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=tuple(
            ToolCall(id=f"call_{i}", name=name, arguments=args, raw_arguments=json.dumps(args))
            for i, (name, args) in enumerate(calls)
        ),
    )


def reply(text: str) -> LLMResponse:
    return LLMResponse(content=text)


def note(row_ids: list[int], verdict: str = "likely_true_positive") -> LLMResponse:
    return reply(
        json.dumps(
            {
                "verdict": verdict,
                "finding": "Rows 1 and 2 record the same obligation twice, six days apart.",
                "claims": [
                    {
                        "text": "Both rows are for the same amount.",
                        "row_ids": row_ids,
                        "facts": [{"row_id": row_ids[0], "field": "amount", "value": 5000.0}],
                    }
                ],
                "policy_clauses": ["SG-PP-4.4"],
                "recommended_action": "Hold payment on row 2 and confirm with the supplier.",
            }
        )
    )


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    rows: list[dict[str, object]] = [
        {"amount": 5000.0, "txn_date": DAY0, "invoice_no": "INV-04471"},
        {"amount": 5000.0, "txn_date": DAY0 + timedelta(days=6), "invoice_no": "4471/2025"},
    ]
    rows += [
        {"amount": 1000.0 + i, "txn_date": DAY0 + timedelta(days=i), "item_desc": "Toner " * 8}
        for i in range(60)
    ]
    return build_db(tmp_path / "t.duckdb", rows)


@pytest.fixture
def case() -> Case:
    return Case.build(
        detector="d1",
        anomaly_type=AnomalyType.DUPLICATE,
        row_ids=[1, 2],
        detector_score=0.97,
        amount_at_risk=5000.0,
        vendor_key="sharma",
        metadata={"match_probability": 0.97},
    )


def investigator(con: duckdb.DuckDBPyConnection, model: ScriptedModel, **kw: Any) -> Investigator:
    return Investigator(model, con, policy_index=FakePolicyIndex(), **kw)


def kinds(result: InvestigationResult) -> list[str]:
    return [s.kind for s in result.trace]


# ------------------------------------------------------------------ the loop


def test_tools_are_run_and_the_note_is_accepted(con: Any, case: Case) -> None:
    model = ScriptedModel(
        [tools(("vendor_profile", {"vendor_key": "sharma"}), ("calculator", {"expression": "5000*2"})),
         note([1, 2])]
    )  # fmt: skip
    result = investigator(con, model).investigate(case)

    assert result.status == "completed"
    assert result.verdict is Verdict.LIKELY_TRUE_POSITIVE
    assert kinds(result) == ["model", "tool", "tool", "model"]
    assert result.trace[2].tool_result == {"expression": "5000*2", "result": 10000.0}
    assert result.tool_calls == 2
    assert result.prompt_tokens > 0
    # The second request carries the tool results, matched to their call ids.
    sent = model.requests[1]["messages"]
    assert [m["role"] for m in sent[-3:]] == ["assistant", "tool", "tool"]
    assert sent[-1]["tool_call_id"] == "call_1"


def test_the_case_evidence_is_in_the_first_message(con: Any, case: Case) -> None:
    model = ScriptedModel([note([1, 2])])
    investigator(con, model).investigate(case)
    brief = model.requests[0]["messages"][1]["content"]
    assert "INV-04471" in brief and "4471/2025" in brief
    assert "is_injected" not in brief  # the answer key never reaches the model


def test_a_tool_error_is_fed_back_not_raised(con: Any, case: Case) -> None:
    model = ScriptedModel(
        [tools(("query_transactions", {"sql": "SELECT * FROM ground_truth"})), note([1, 2])]
    )
    result = investigator(con, model).investigate(case)
    assert result.status == "completed"
    assert result.trace[1].error and "audit_transactions" in result.trace[1].error
    assert "error" in model.requests[1]["messages"][-1]["content"]


def test_an_unknown_tool_is_an_error_the_model_can_read(con: Any, case: Case) -> None:
    model = ScriptedModel([tools(("delete_case", {})), note([1, 2])])
    result = investigator(con, model).investigate(case)
    assert result.status == "completed"
    assert "No tool named" in (result.trace[1].error or "")


def test_a_malformed_note_is_sent_back_with_the_reason(con: Any, case: Case) -> None:
    bad = reply(json.dumps({"verdict": "likely_true_positive", "finding": "short"}))
    model = ScriptedModel([bad, note([1, 2])])
    result = investigator(con, model).investigate(case)

    assert result.status == "completed"
    assert kinds(result) == ["model", "parse_error", "model"]
    feedback = model.requests[1]["messages"][-1]
    assert feedback["role"] == "user" and "claims" in feedback["content"]


def test_repeated_malformed_notes_end_in_failure_not_a_loop(con: Any, case: Case) -> None:
    model = ScriptedModel([reply("I believe this is a duplicate.")] * (MAX_PARSE_RETRIES + 1))
    result = investigator(con, model).investigate(case)
    assert result.status == "failed"
    assert result.note is None and result.severity_final is None
    assert "malformed" in (result.error or "")
    assert kinds(result).count("parse_error") == MAX_PARSE_RETRIES + 1
    assert kinds(result)[-1] == "failed"


def test_the_step_limit_forces_a_note_with_tools_switched_off(con: Any, case: Case) -> None:
    calc = tools(("calculator", {"expression": "1+1"}))
    model = ScriptedModel([calc, calc, calc, note([1, 2])])
    result = investigator(con, model, max_steps=3).investigate(case)

    assert result.status == "completed"
    assert kinds(result)[-1] == "forced_final"
    assert model.requests[-1]["tool_choice"] == "none"
    assert "Stop gathering evidence" in model.requests[-1]["messages"][-1]["content"]


def test_an_unreachable_model_fails_the_case_and_keeps_the_trace(con: Any, case: Case) -> None:
    model = ScriptedModel(
        [tools(("calculator", {"expression": "2*3"})), LLMCallError("groq unreachable")]
    )
    result = investigator(con, model).investigate(case)
    assert result.status == "failed"
    assert result.error == "groq unreachable"
    assert kinds(result) == ["model", "tool", "failed"]  # the reason is stored with the trace
    assert result.trace[-1].error == "groq unreachable"


def test_rows_seen_in_tool_results_are_tracked(con: Any, case: Case) -> None:
    sql = "SELECT row_id, amount FROM audit_transactions WHERE row_id IN (7, 8)"
    model = ScriptedModel([tools(("query_transactions", {"sql": sql})), note([1, 7])])
    result = investigator(con, model).investigate(case)
    assert {1, 2, 7, 8} <= result.seen_row_ids
    assert result.unseen_citations == []


def test_citing_a_row_never_seen_is_flagged_for_the_verifier(con: Any, case: Case) -> None:
    model = ScriptedModel([note([1, 55])])
    result = investigator(con, model).investigate(case)
    assert result.status == "completed"  # a schema-valid note; checking it is Phase 7
    assert result.unseen_citations == [55]


def test_a_dismissal_lowers_severity_and_marks_the_case(con: Any, case: Case) -> None:
    model = ScriptedModel([note([1, 2], verdict="likely_false_positive")])
    result = investigator(con, model).investigate(case)
    assert result.dismissed_by_agent
    assert result.severity_band == SeverityBand.LOW.value


# ------------------------------------------------------------------ tool results


def test_a_large_tool_result_is_cut_by_whole_rows(con: Any, case: Case) -> None:
    """Cutting mid-JSON left the model re-running the same query."""
    sql = "SELECT * FROM audit_transactions ORDER BY row_id"
    model = ScriptedModel([tools(("query_transactions", {"sql": sql})), note([1, 2])])
    investigator(con, model).investigate(case)
    content = model.requests[1]["messages"][-1]["content"]

    assert len(content) <= settings.agent_tool_result_chars
    payload = json.loads(content)  # still valid JSON
    assert "narrow the request" in payload["shown"]
    assert len(payload["rows"]) < 50


# ------------------------------------------------------------------ token budget


def _conversation(case: Case, con: Any) -> list[dict[str, Any]]:
    rows = Investigator(ScriptedModel([]), con).evidence(case)
    return [
        {"role": "system", "content": system_prompt(case.anomaly_type)},
        {"role": "user", "content": case_brief(case, rows)},
    ]


def _tool_turn(call_id: str, content: str) -> list[dict[str, Any]]:
    return [
        {"role": "assistant", "content": None, "tool_calls": [{"id": call_id}]},
        {"role": "tool", "tool_call_id": call_id, "content": content},
    ]


def test_trimming_drops_the_bulkiest_old_result_first_and_keeps_its_rows(
    con: Any, case: Case
) -> None:
    inv = investigator(con, ScriptedModel([]))
    big = json.dumps({"rows": [{"row_id": i, "item_desc": "x" * 40} for i in range(30, 60)]})
    small = json.dumps({"expression": "1+1", "result": 2.0})
    messages = _conversation(case, con)
    messages += _tool_turn("a", small) + _tool_turn("b", big) + _tool_turn("c", small)
    before = copy.deepcopy(messages)

    budget = inv.estimate_tokens(messages, None) - 100
    trimmed, fits = inv.fit_to_budget(messages, None, budget)

    assert (trimmed, fits) == (1, True)
    assert messages[:2] == before[:2]  # rules and case untouched
    assert messages[3] == before[3]  # the small summary kept
    assert messages[-1] == before[-1]  # the latest turn kept
    elided = json.loads(messages[5]["content"])
    assert "elided" in elided and elided["row_ids"][:2] == [30, 31]


def test_the_latest_turn_is_protected_until_the_final_write_up(con: Any, case: Case) -> None:
    inv = investigator(con, ScriptedModel([]))
    messages = _conversation(case, con) + _tool_turn("a", json.dumps({"rows": ["x" * 3000]}))
    budget = inv.estimate_tokens(_conversation(case, con), None) + 150  # a 1,000-token result

    assert inv.fit_to_budget(copy.deepcopy(messages), None, budget) == (0, False)
    assert inv.fit_to_budget(messages, None, budget, keep_latest=False) == (1, True)


def test_a_full_context_ends_gathering_and_writes_the_note(con: Any, case: Case) -> None:
    sql = "SELECT * FROM audit_transactions ORDER BY row_id"
    model = ScriptedModel([tools(("query_transactions", {"sql": sql})), note([1, 2])])
    inv = investigator(con, model)
    first = inv.estimate_tokens(_conversation(case, con), ToolBox(con).schemas())
    inv.context_tokens = first + 300  # room to start, not for a 50-row result on top

    result = inv.investigate(case)
    assert result.status == "completed"
    assert "context_trim" in kinds(result)
    assert kinds(result)[-1] == "forced_final"
    assert "elided" in model.requests[-1]["messages"][3]["content"]


def test_a_case_too_big_for_the_budget_fails_without_sending_it(con: Any, case: Case) -> None:
    model = ScriptedModel([note([1, 2])])
    inv = investigator(con, model)
    inv.context_tokens = 100
    result = inv.investigate(case)
    assert result.status == "failed"
    assert "does not fit" in (result.error or "")
    assert model.requests == []


def test_a_request_refused_as_too_large_is_shrunk_and_retried(con: Any, case: Case) -> None:
    model = ScriptedModel([LLMRequestTooLargeError("413"), note([1, 2])])
    result = investigator(con, model).investigate(case)
    assert result.status == "completed"
    assert len(model.requests) == 2


# ------------------------------------------------------------------ final severity


@pytest.mark.parametrize(
    ("prelim", "verdict", "value", "band"),
    [
        (90.0, Verdict.LIKELY_TRUE_POSITIVE, 90.0, SeverityBand.HIGH),
        (90.0, Verdict.INCONCLUSIVE, settings.severity_band_high - 0.01, SeverityBand.MEDIUM),
        (
            90.0,
            Verdict.LIKELY_FALSE_POSITIVE,
            settings.severity_band_medium - 0.01,
            SeverityBand.LOW,
        ),
        (50.0, Verdict.INCONCLUSIVE, 50.0, SeverityBand.MEDIUM),
        (10.0, Verdict.LIKELY_FALSE_POSITIVE, 10.0, SeverityBand.LOW),
    ],
)
def test_final_severity_moves_the_number_with_the_band(
    prelim: float, verdict: Verdict, value: float, band: SeverityBand
) -> None:
    """O-04: sorting by severity and filtering by band must agree."""
    assert final_severity(prelim, verdict) == (pytest.approx(value), band)


def test_final_severity_never_raises_a_case() -> None:
    for verdict in Verdict:
        assert final_severity(20.0, verdict)[0] <= 20.0
