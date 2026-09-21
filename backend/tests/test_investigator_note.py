"""The audit note schema, how a model's reply is parsed into it, and the prompts."""

from __future__ import annotations

import json
from typing import Any

import pytest

from spendguard.agent.note import CHECKABLE_FIELDS, NoteParseError, Verdict, parse_note
from spendguard.agent.prompts import EXAMPLES, MAX_EVIDENCE_ROWS, case_brief, system_prompt
from spendguard.cases import AnomalyType, Case
from spendguard.config import settings


def note(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "verdict": "likely_true_positive",
        "finding": "Rows 1 and 2 record the same obligation twice, six days apart.",
        "claims": [
            {
                "text": "Both rows are for Rs 5,000.",
                "row_ids": [1, 2],
                "facts": [{"row_id": 1, "field": "amount", "value": 5000.0}],
            }
        ],
        "policy_clauses": ["SG-PP-4.4"],
        "recommended_action": "Hold payment on row 2 and confirm with the supplier.",
    }
    return {**base, **overrides}


# ------------------------------------------------------------------ parsing


def test_a_bare_json_note_is_parsed() -> None:
    parsed = parse_note(json.dumps(note()))
    assert parsed.verdict is Verdict.LIKELY_TRUE_POSITIVE
    assert parsed.cited_row_ids == [1, 2]


def test_reasoning_tags_are_ignored() -> None:
    """Qwen 3 thinks out loud in <think> tags, sometimes with braces inside."""
    reply = "<think>maybe {not this} ... </think>\n" + json.dumps(note())
    assert parse_note(reply).policy_clauses == ["SG-PP-4.4"]


def test_a_fenced_block_is_preferred_over_prose() -> None:
    reply = f"Here is my note {{draft}}:\n```json\n{json.dumps(note())}\n```\nDone."
    assert parse_note(reply).verdict is Verdict.LIKELY_TRUE_POSITIVE


def test_prose_around_the_object_is_tolerated() -> None:
    assert parse_note("Final answer: " + json.dumps(note()) + " Thanks.").claims


def test_braces_inside_strings_do_not_confuse_extraction() -> None:
    tricky = note(finding="The description reads {Premium} and the price is } unusual here.")
    assert "{Premium}" in parse_note("x " + json.dumps(tricky)).finding


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ("", "empty"),
        ("I think it is a duplicate.", "No JSON object"),
        ('{"verdict": "likely_true_positive",}', "malformed"),
    ],
)
def test_unusable_replies_say_what_is_wrong(reply: str, message: str) -> None:
    with pytest.raises(NoteParseError, match=message):
        parse_note(reply)


def test_a_claim_without_a_citation_is_rejected() -> None:
    """FR-3.5: no claim without a row citation."""
    bad = note(claims=[{"text": "It is a duplicate.", "row_ids": []}])
    with pytest.raises(NoteParseError, match="row_ids"):
        parse_note(json.dumps(bad))


def test_a_fact_about_a_row_the_claim_does_not_cite_is_rejected() -> None:
    bad = note(
        claims=[
            {
                "text": "Row 1 is Rs 5,000.",
                "row_ids": [1],
                "facts": [{"row_id": 9, "field": "amount", "value": 5000.0}],
            }
        ]
    )
    with pytest.raises(NoteParseError, match=r"rows \[9\]"):
        parse_note(json.dumps(bad))


def test_a_fact_may_only_name_a_checkable_field() -> None:
    bad = note(
        claims=[
            {
                "text": "Row 1 is injected.",
                "row_ids": [1],
                "facts": [{"row_id": 1, "field": "is_injected", "value": True}],
            }
        ]
    )
    with pytest.raises(NoteParseError, match="field must be one of"):
        parse_note(json.dumps(bad))
    assert "is_injected" not in CHECKABLE_FIELDS


@pytest.mark.parametrize("clause", ["4.4", "SG-PP-4", "Policy 4.4", "SGPP-4.4"])
def test_policy_clauses_must_be_real_clause_ids(clause: str) -> None:
    with pytest.raises(NoteParseError, match="SG-PP-4.4"):
        parse_note(json.dumps(note(policy_clauses=[clause])))


def test_an_unknown_verdict_is_rejected() -> None:
    with pytest.raises(NoteParseError, match="verdict"):
        parse_note(json.dumps(note(verdict="closed")))


def test_extra_keys_are_rejected_so_the_schema_cannot_drift() -> None:
    with pytest.raises(NoteParseError, match="confidence"):
        parse_note(json.dumps(note(confidence=0.9)))


def test_every_worked_example_is_itself_a_valid_note() -> None:
    """The model imitates the example; an invalid example teaches invalid notes."""
    for kind, example in EXAMPLES.items():
        assert parse_note(json.dumps(example)).claims, kind


# ------------------------------------------------------------------ prompts


def test_the_prompt_states_the_threshold_from_config() -> None:
    """Policy, config and prompt must agree on the number (convention 2)."""
    assert settings.money(settings.approval_threshold) in system_prompt(AnomalyType.SPLIT)


def test_only_the_example_for_the_case_type_is_shown() -> None:
    prompt = system_prompt(AnomalyType.INFLATION)
    assert "Premium Grade" in prompt
    assert "4471/2025" not in prompt  # the duplicate example


def test_the_prompt_uses_the_honest_wording() -> None:
    prompt = system_prompt(AnomalyType.DUPLICATE)
    assert "duplicate transaction record" in prompt
    assert "Never say a case is closed" in prompt


def test_a_large_case_brief_shows_a_sample_and_the_aggregate() -> None:
    rows = [
        {"row_id": i, "amount": 1000.0, "txn_date": f"2025-05-{i % 28 + 1:02d}"}
        for i in range(1, 41)
    ]
    case = Case.build(
        detector="d4",
        anomaly_type=AnomalyType.VENDOR_FLAG,
        row_ids=range(1, 41),
        detector_score=0.9,
        amount_at_risk=40_000,
        vendor_key="acme",
        metadata={"tests": ["round_numbers"]},
    )
    brief = case_brief(case, rows)
    assert f"{MAX_EVIDENCE_ROWS} of 40 shown" in brief
    assert settings.money(40_000) in brief
    assert "query_transactions" in brief
    assert brief.count('"row_id"') == MAX_EVIDENCE_ROWS
