"""The Verifier: deterministic checks, the model judge, and the regeneration loop.

Everything here is offline. The judge and the Investigator are scripted, so the
tests pin down what the Verifier does with their answers - catch, feed back,
retry, release with the right badge - not what a model happens to say.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from spendguard.agent.checks import check_citations, value_matches
from spendguard.agent.investigator import Investigator
from spendguard.agent.llm import LLMQuotaExhaustedError
from spendguard.agent.note import InvestigatorNote
from spendguard.agent.verifier import (
    FAILED_AFTER_RETRIES,
    JUDGE_PROMPT,
    UNVERIFIED,
    VERIFIED,
    Verifier,
    investigate_and_verify,
    release_status,
)
from spendguard.cases import AnomalyType, Case

from .conftest import build_db
from .test_investigator import FakePolicyIndex, ScriptedModel, reply, tools

DAY0 = date(2025, 4, 1)
CLAUSES = {"SG-PP-4.4", "SG-PP-4.5", "SG-PP-3.2"}


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    rows: list[dict[str, object]] = [
        {"vendor_name": "Sharma Traders", "amount": 87450.0, "txn_date": DAY0,
         "invoice_no": "INV-04471", "item_desc": "Office Chair", "quantity": 10.0},
        {"vendor_name": "Sharma Traders", "amount": 87450.0, "txn_date": DAY0 + timedelta(days=6),
         "invoice_no": "4471/2025", "item_desc": "Office Chair", "quantity": 10.0},
        {"vendor_name": "Gupta Stationers", "amount": 1234.56, "txn_date": DAY0,
         "invoice_no": None, "item_desc": "A4 Paper"},
    ]  # fmt: skip
    return build_db(tmp_path / "t.duckdb", rows)


@pytest.fixture
def case() -> Case:
    return Case.build(
        detector="d1", anomaly_type=AnomalyType.DUPLICATE, row_ids=[1, 2],
        detector_score=0.97, amount_at_risk=87450.0, vendor_key="sharma",
    )  # fmt: skip


def make_note(claims: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    return {
        "verdict": "likely_true_positive",
        "finding": "Rows 1 and 2 record the same obligation twice, six days apart.",
        "claims": claims,
        "policy_clauses": ["SG-PP-4.4"],
        "recommended_action": "Hold any payment against row 2 and confirm with the supplier.",
        **overrides,
    }


GOOD_CLAIMS = [
    {
        "text": "Both records are for Rs 87,450.",
        "row_ids": [1, 2],
        "facts": [
            {"row_id": 1, "field": "amount", "value": 87450.0},
            {"row_id": 2, "field": "amount", "value": 87450},
        ],
    },
    {
        "text": "The invoice number was retyped.",
        "row_ids": [1, 2],
        "facts": [
            {"row_id": 1, "field": "invoice_no", "value": "INV-04471"},
            {"row_id": 2, "field": "invoice_no", "value": "4471/2025"},
        ],
    },
]


def parsed(data: dict[str, Any]) -> InvestigatorNote:
    return InvestigatorNote.model_validate(data)


def judgement(*supported: bool, reason: str = "the rows show it") -> Any:
    return reply(
        json.dumps(
            {
                "claims": [
                    {"index": i, "supported": s, "reason": reason} for i, s in enumerate(supported)
                ]
            }
        )
    )


# ------------------------------------------------------------------ extraction


def test_every_claim_and_row_pair_is_one_citation() -> None:
    """FR-4.1: repeated and multi-row citations are all extracted, once per claim."""
    note = parsed(make_note([
        {"text": "Row 1 twice and row 2.", "row_ids": [1, 1, 2]},
        {"text": "Row 2 again, in another claim.", "row_ids": [2]},
    ]))  # fmt: skip
    assert [(c.claim_index, c.row_id) for c in note.citations()] == [(0, 1), (0, 2), (1, 2)]


# ------------------------------------------------------------------ deterministic


def test_a_correct_note_passes_every_deterministic_check(con: Any) -> None:
    report = check_citations(con, parsed(make_note(GOOD_CLAIMS)), CLAUSES)
    assert report.deterministic_passed == report.checked == 4
    assert report.note_problems == []


def test_a_citation_to_a_row_that_does_not_exist_is_caught(con: Any) -> None:
    """FR-4.2: a fabricated citation."""
    note = parsed(make_note([{"text": "Row 999 is a duplicate.", "row_ids": [1, 999]}]))
    report = check_citations(con, note, CLAUSES)
    missing = next(c for c in report.citations if c.row_id == 999)
    assert not missing.row_exists and not missing.passed
    assert "999 does not exist" in report.feedback()


def test_a_wrong_amount_for_a_real_row_is_caught(con: Any) -> None:
    """FR-4.3: the row exists, the number stated about it is wrong."""
    note = parsed(make_note([{
        "text": "Row 2 is for Rs 87,540.", "row_ids": [2],
        "facts": [{"row_id": 2, "field": "amount", "value": 87540.0}],
    }]))  # fmt: skip
    report = check_citations(con, note, CLAUSES)
    [check] = report.citations
    assert check.row_exists and not check.values_match
    assert "the note says 87540.0, the row has 87450.0" in report.feedback()


@pytest.mark.parametrize(
    ("field", "stated", "actual", "matches"),
    [
        ("amount", 1234.56, 1234.56, True),
        ("amount", "₹1,234.56", 1234.56, True),
        ("amount", "Rs. 1,234.56", 1234.56, True),
        ("amount", 1235, 1234.56, True),  # stated to the rupee: rounds to the same
        ("amount", 1234.6, 1234.56, True),  # stated to one decimal
        ("amount", 1200, 1234.56, False),  # rounded to the hundred is a different figure
        ("amount", 1234.65, 1234.56, False),  # transposed digits
        ("amount", True, 1.0, False),
        ("amount", "about a thousand", 1234.56, False),
        ("quantity", 10, 10.0, True),
        ("txn_date", "2025-04-01", date(2025, 4, 1), True),
        ("txn_date", "01-04-2025", date(2025, 4, 1), True),
        ("txn_date", "1 Apr 2025", date(2025, 4, 1), True),
        ("txn_date", "2025-04-02", date(2025, 4, 1), False),
        ("vendor_name", "sharma  traders", "Sharma Traders", True),
        ("vendor_name", "Sharma Trader", "Sharma Traders", False),
        ("invoice_no", "INV-4471", "INV-04471", False),  # a retyped number is the evidence
        ("invoice_no", None, None, True),
        ("invoice_no", "INV-1", None, False),
    ],
)
def test_stated_values_match_only_what_the_row_holds(
    field: str, stated: Any, actual: Any, matches: bool
) -> None:
    assert value_matches(field, stated, actual) is matches


def test_a_policy_clause_that_does_not_exist_is_caught(con: Any) -> None:
    note = parsed(make_note(GOOD_CLAIMS, policy_clauses=["SG-PP-4.4", "SG-PP-9.9"]))
    report = check_citations(con, note, CLAUSES)
    assert report.note_problems == [
        "Policy clause SG-PP-9.9 does not exist. Cite only clauses policy_lookup returned."
    ]
    assert not report.passed


def test_duplicate_payment_wording_is_caught_but_the_register_may_be_named(con: Any) -> None:
    """CLAUDE.md wording discipline; seen in a real note in Phase 6."""
    bad = make_note(GOOD_CLAIMS, recommended_action="Recover the duplicate payment by set-off.")
    assert check_citations(con, parsed(bad), CLAUSES).note_problems

    fine = make_note(GOOD_CLAIMS, recommended_action="Record it in the duplicate-payment register.")
    assert check_citations(con, parsed(fine), CLAUSES).note_problems == []


# ------------------------------------------------------------------ semantic


def _result_for(con: Any, case: Case, note: dict[str, Any], model: ScriptedModel) -> Any:
    """A finished investigation whose note is ``note``, ready to be checked."""
    model.turns.insert(0, reply(json.dumps(note)))
    return Investigator(model, con, policy_index=FakePolicyIndex()).investigate(case)


def test_an_unsupported_claim_is_caught_by_the_judge(con: Any, case: Case) -> None:
    """FR-4.4: the row exists and no stated value is wrong, but it does not show the claim."""
    claims = [*GOOD_CLAIMS, {"text": "The supplier was registered last week.", "row_ids": [1]}]
    model = ScriptedModel([judgement(True, True, False, reason="no registration date shown")])
    result = _result_for(con, case, make_note(claims), model)

    report = Verifier(model, con, clause_ids=CLAUSES).check(result)
    assert report.semantic_ran
    assert report.deterministic_passed == report.checked  # nothing wrong mechanically
    assert report.unsupported == {2: "no registration date shown"}
    assert [c.supports_claim for c in report.citations] == [True] * 4 + [False]
    assert "Claim 2 is not supported" in report.feedback()


def test_the_judge_sees_the_evidence_and_nothing_else(con: Any, case: Case) -> None:
    """A fresh context: the claims, the cited rows, the tool results - no reasoning, no answer key."""
    model = ScriptedModel(
        [tools(("calculator", {"expression": "87450*2"})), reply(json.dumps(make_note(GOOD_CLAIMS))),
         judgement(True, True)]
    )  # fmt: skip
    result = Investigator(model, con, policy_index=FakePolicyIndex()).investigate(case)
    Verifier(model, con, clause_ids=CLAUSES).check(result)

    sent = model.requests[-1]
    assert sent["messages"][0]["content"] == JUDGE_PROMPT
    assert len(sent["messages"]) == 2  # nothing from the Investigator's conversation
    evidence = sent["messages"][1]["content"]
    assert "[1] The invoice number was retyped." in evidence
    assert '"invoice_no":"4471/2025"' in evidence
    assert '"result":174900.0' in evidence  # the calculator result it may rely on
    assert "Gupta" not in evidence  # rows nobody cited stay out
    assert "is_injected" not in evidence and "source_row_ref" not in evidence


def test_an_unparseable_judgement_is_asked_for_again(con: Any, case: Case) -> None:
    model = ScriptedModel([reply("Both look fine to me."), judgement(True, True)])
    result = _result_for(con, case, make_note(GOOD_CLAIMS), model)
    report = Verifier(model, con, clause_ids=CLAUSES).check(result)
    assert report.semantic_ran
    assert [s.kind for s in result.trace if s.role == "verifier"] == ["check", "judge", "judge"]


def test_a_judge_that_never_answers_leaves_the_note_unverified_not_failed(
    con: Any, case: Case
) -> None:
    model = ScriptedModel([reply("?"), reply('{"claims": []}')])
    result = _result_for(con, case, make_note(GOOD_CLAIMS), model)
    report = Verifier(model, con, clause_ids=CLAUSES).check(result)
    assert not report.semantic_ran and report.judge_error
    assert report.semantic_passed is None
    assert release_status(report) == UNVERIFIED  # half the checking happened; say so


# ------------------------------------------------------------------ the loop


def verify(con: Any, case: Case, model: ScriptedModel, **kw: Any) -> Any:
    investigator = Investigator(model, con, policy_index=FakePolicyIndex())
    return investigate_and_verify(
        investigator, Verifier(model, con, clause_ids=CLAUSES), case, **kw
    )


def test_a_clean_note_is_released_as_verified_first_time(con: Any, case: Case) -> None:
    model = ScriptedModel([reply(json.dumps(make_note(GOOD_CLAIMS))), judgement(True, True)])
    result = verify(con, case, model)
    assert result.verification_status == VERIFIED
    assert result.retry_count == 0
    assert result.verification.citations_passed == 4


def test_a_failed_note_is_sent_back_with_the_reasons_and_fixed(con: Any, case: Case) -> None:
    """FR-4.5: the failure reason is the context for the regeneration."""
    wrong = make_note(
        [{**GOOD_CLAIMS[0], "facts": [{"row_id": 1, "field": "amount", "value": 78450}]}]
    )
    right = make_note([GOOD_CLAIMS[0]])
    model = ScriptedModel(
        [reply(json.dumps(wrong)), judgement(True), reply(json.dumps(right)), judgement(True)]
    )
    result = verify(con, case, model)

    feedback = model.requests[2]["messages"][-1]
    assert feedback["role"] == "user"
    assert "the note says 78450, the row has 87450.0" in feedback["content"]
    assert result.retry_count == 1
    assert result.verification_status == VERIFIED
    assert result.first_check.deterministic_passed == 1  # the draft, before the fix
    assert result.verification.deterministic_passed == 2


def test_regeneration_stops_at_the_retry_limit(con: Any, case: Case) -> None:
    """FR-4.5 and FR-4.7: still wrong after the limit -> released, explicitly failed."""
    wrong = json.dumps(make_note(GOOD_CLAIMS, policy_clauses=["SG-PP-9.9"]))
    model = ScriptedModel([reply(wrong), judgement(True, True)] * 3)
    result = verify(con, case, model, max_retries=2)

    assert result.retry_count == 2
    assert len([s for s in result.trace if s.kind == "check"]) == 3
    assert result.verification_status == FAILED_AFTER_RETRIES
    assert result.note is not None  # released, never silently dropped
    assert model.turns == []


def test_the_best_draft_is_released_not_the_last(con: Any, case: Case) -> None:
    one_error = make_note(GOOD_CLAIMS, policy_clauses=["SG-PP-9.9"])
    two_errors = make_note(
        [{"text": "Row 999 and 998.", "row_ids": [999, 998]}], policy_clauses=["SG-PP-9.9"]
    )
    model = ScriptedModel(
        [reply(json.dumps(one_error)), judgement(True, True),
         reply(json.dumps(two_errors)), judgement(False)]
    )  # fmt: skip
    result = verify(con, case, model, max_retries=1)
    assert result.verification.failures == 1
    assert result.note.claims[0].row_ids == [1, 2]


def test_a_revision_that_never_comes_keeps_the_original_note(con: Any, case: Case) -> None:
    wrong = json.dumps(make_note(GOOD_CLAIMS, policy_clauses=["SG-PP-9.9"]))
    model = ScriptedModel([reply(wrong), judgement(True, True)] + [reply("I cannot.")] * 3)
    result = verify(con, case, model, max_retries=1)
    assert result.note is not None and result.status == "completed"
    assert result.verification_status == FAILED_AFTER_RETRIES


def test_with_the_verifier_off_nothing_is_enforced_but_everything_is_measured(
    con: Any, case: Case
) -> None:
    """FR-7.8 ablation: no judge, no regeneration - but the deterministic numbers are recorded."""
    bad = make_note([{**GOOD_CLAIMS[0], "facts": [{"row_id": 1, "field": "amount", "value": 1}]}])
    model = ScriptedModel([reply(json.dumps(bad))])
    result = verify(con, case, model, enabled=False)

    assert result.verification_status == UNVERIFIED
    assert result.retry_count == 0
    assert len(model.requests) == 1  # no judge call
    assert result.verification.deterministic_passed == 1 and result.verification.checked == 2


def test_a_spent_quota_during_checking_releases_the_note_unverified(con: Any, case: Case) -> None:
    model = ScriptedModel(
        [reply(json.dumps(make_note(GOOD_CLAIMS))), LLMQuotaExhaustedError("tokens per day")]
    )
    result = verify(con, case, model)
    assert result.quota_exhausted
    assert result.note is not None
    assert result.verification_status == UNVERIFIED


# ------------------------------------------------------------------ the exit criterion


def test_a_note_with_three_planted_errors_is_caught_on_each_count(con: Any, case: Case) -> None:
    """Phase 7 exit criterion: a wrong amount, a nonexistent row, an unsupported claim."""
    planted = make_note([
        {"text": "Row 2 is for Rs 97,450.", "row_ids": [2],
         "facts": [{"row_id": 2, "field": "amount", "value": 97450.0}]},  # wrong amount
        {"text": "Row 4242 repeats it.", "row_ids": [4242]},  # no such row
        {"text": "The supplier is a new vendor.", "row_ids": [1]},  # unsupported
    ])  # fmt: skip
    model = ScriptedModel([judgement(True, True, False, reason="nothing shows when it was added")])
    result = _result_for(con, case, planted, model)
    report = Verifier(model, con, clause_ids=CLAUSES).check(result)

    by_claim = {c.claim_index: c for c in report.citations}
    assert by_claim[0].row_exists and not by_claim[0].values_match
    assert not by_claim[1].row_exists
    assert by_claim[2].deterministic_ok and by_claim[2].supports_claim is False
    assert report.citations_passed == 0
    assert release_status(report) == FAILED_AFTER_RETRIES


# ------------------------------------------------------------------ persistence


def test_the_badge_counts_and_every_citations_checks_are_stored(
    con: Any, case: Case, tmp_path: Path
) -> None:
    """FR-4.6 and FR-7.5: status, passed-of-checked, and the two numbers kept apart."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from spendguard.db.store import (
        AuditNoteRecord,
        CitationRecord,
        TraceRecord,
        get_engine,
        save_cases,
        save_investigation,
    )

    claims = [*GOOD_CLAIMS, {"text": "The supplier is new.", "row_ids": [1]}]
    model = ScriptedModel(
        [reply(json.dumps(make_note(claims))), judgement(True, True, False, reason="not shown")]
    )
    result = verify(con, case, model, max_retries=0)
    engine = get_engine(f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")
    save_cases(engine, "d", "ds", [case])
    save_investigation(engine, "inv-1", result)

    with Session(engine) as s:
        note = s.scalars(select(AuditNoteRecord)).one()
        citations = s.scalars(select(CitationRecord).order_by(CitationRecord.claim_index)).all()
        roles = {t.role for t in s.scalars(select(TraceRecord))}
    assert note.verification_status == FAILED_AFTER_RETRIES
    assert (note.citations_checked, note.deterministic_passed) == (5, 5)
    assert (note.semantic_passed, note.citations_passed) == (4, 4)
    assert note.retry_count == 0
    failed = citations[-1]
    assert failed.row_exists and failed.values_match and failed.supports_claim is False
    assert failed.failure_reason == "not supported: not shown"
    assert roles == {"investigator", "verifier"}


# ------------------------------------------------------------------ judge evidence


VENDOR_PROFILE = {  # the real shape that went wrong: the deciding fields come last
    "transactions": 193, "total_amount": 16934897.11, "first_seen": "2025-04-14",
    "last_seen": "2026-03-30", "distinct_amounts": 192, "officers": 15, "round_share": 0.0,
    "vendor_name": "Unique Traders Private Limited", "vendor_key": "unique", "found": True,
    "by_officer": [{"officer_id": f"WSD-{i:03d}", "transactions": 9, "total": 754384.42}
                   for i in range(5)],
    "by_category": [{"item_category": f"Plumbing and Water Supply / Item {i}",
                     "transactions": 71, "total": 7698078.12} for i in range(3)],
    "recurring_monthly_billing": [],
    "looks_like_fixed_contract": False,
}  # fmt: skip


def test_a_long_tool_result_keeps_its_summary_fields_when_shrunk() -> None:
    """Cut at 700 characters, a vendor profile lost looks_like_fixed_contract and the
    judge rejected a true claim. Whole list items go first; every scalar stays."""
    from spendguard.agent.investigator import fit_json

    text = fit_json(VENDOR_PROFILE, 700)
    shrunk = json.loads(text)  # still valid JSON
    assert len(text) <= 700
    assert shrunk["looks_like_fixed_contract"] is False
    assert shrunk["recurring_monthly_billing"] == []
    assert shrunk["transactions"] == 193
    assert "narrow the request" in shrunk["shown"]
    assert fit_json(VENDOR_PROFILE, 100_000) == json.dumps(
        VENDOR_PROFILE, separators=(",", ":"), ensure_ascii=False
    )  # small enough: untouched


def test_the_judge_sees_the_vendor_profile_fields_a_history_claim_rests_on(
    con: Any, case: Case
) -> None:
    model = ScriptedModel(
        [tools(("vendor_profile", {"vendor_key": "sharma"})),
         reply(json.dumps(make_note(GOOD_CLAIMS))), judgement(True, True)]
    )  # fmt: skip
    result = Investigator(model, con, policy_index=FakePolicyIndex()).investigate(case)
    result.trace[1].tool_result = VENDOR_PROFILE  # as the real tool returned it
    evidence = Verifier(model, con, clause_ids=CLAUSES).evidence_brief(result.note, result)
    assert '"looks_like_fixed_contract":false' in evidence
