"""The audit note the Investigator writes, and how its reply is parsed.

A note is built for two readers:

* an **auditor**, who reads ``finding`` first and ``recommended_action`` last;
* the **Verifier** (Phase 7), which checks every claim against the rows it cites.

So each claim is structured rather than prose with inline markers: a sentence,
the row ids it rests on, and optionally the exact field values it asserts. Facts
like ``{"row_id": 2847, "field": "amount", "value": 87450}`` can be checked
deterministically; the sentence itself needs a semantic check. That split is
decision D-13, and it is why a claim carries both.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# Fields a fact may assert about a row - exactly what the audit view exposes.
CHECKABLE_FIELDS: tuple[str, ...] = (
    "vendor_name",
    "vendor_key",
    "invoice_no",
    "amount",
    "txn_date",
    "officer_id",
    "item_desc",
    "item_category",
    "quantity",
    "unit_price",
)


class Verdict(StrEnum):
    """Decision D-04: the agent filters as well as reports, but never closes a case."""

    LIKELY_TRUE_POSITIVE = "likely_true_positive"
    LIKELY_FALSE_POSITIVE = "likely_false_positive"
    INCONCLUSIVE = "inconclusive"


class Fact(BaseModel):
    """One field value the claim asserts about one row. Deterministically checkable."""

    model_config = ConfigDict(extra="forbid")

    row_id: int
    field: str
    value: Any

    @field_validator("field")
    @classmethod
    def _known_field(cls, v: str) -> str:
        if v not in CHECKABLE_FIELDS:
            raise ValueError(f"field must be one of {list(CHECKABLE_FIELDS)}, got {v!r}")
        return v


class Claim(BaseModel):
    """One sentence of the finding and the evidence behind it."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=3)
    row_ids: list[int] = Field(min_length=1)  # FR-3.5: no claim without a citation
    facts: list[Fact] = Field(default_factory=list)

    @field_validator("facts")
    @classmethod
    def _facts_cite_claimed_rows(cls, v: list[Fact], info: Any) -> list[Fact]:
        cited = set(info.data.get("row_ids") or [])
        stray = sorted({f.row_id for f in v} - cited)
        if stray:
            raise ValueError(f"facts refer to rows {stray} that the claim does not cite")
        return v


class InvestigatorNote(BaseModel):
    """What the model must return. Validated before anything is stored."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    finding: str = Field(min_length=20)
    claims: list[Claim] = Field(min_length=1)
    policy_clauses: list[str] = Field(default_factory=list)
    recommended_action: str = Field(min_length=5)

    @field_validator("policy_clauses")
    @classmethod
    def _clause_ids(cls, v: list[str]) -> list[str]:
        bad = [c for c in v if not re.fullmatch(r"SG-PP-\d+\.\d+", c.strip())]
        if bad:
            raise ValueError(f"policy clauses must look like SG-PP-4.4, got {bad}")
        return [c.strip() for c in v]

    @property
    def cited_row_ids(self) -> list[int]:
        return sorted({r for claim in self.claims for r in claim.row_ids})

    def citations(self) -> list[Citation]:
        """Every (claim, cited row) pair, with what the claim asserts about that row (FR-4.1).

        A row cited twice by one claim is one citation; a row cited by two claims
        is two, because each claim can be right or wrong about it independently.
        """
        out = []
        for index, claim in enumerate(self.claims):
            for row_id in dict.fromkeys(claim.row_ids):
                asserted = {f.field: f.value for f in claim.facts if f.row_id == row_id}
                out.append(Citation(index, claim.text, row_id, asserted))
        return out


@dataclass(frozen=True)
class Citation:
    claim_index: int
    claim_text: str
    row_id: int
    asserted: dict[str, Any]


# The shape shown to the model. Kept beside the schema so the two cannot drift.
NOTE_TEMPLATE = {
    "verdict": "likely_true_positive | likely_false_positive | inconclusive",
    "finding": "2-5 sentences an auditor reads first: what happened and why it matters",
    "claims": [
        {
            "text": "one factual sentence",
            "row_ids": ["every row this sentence rests on"],
            "facts": [{"row_id": "a cited row", "field": "amount", "value": "its exact value"}],
        }
    ],
    "policy_clauses": ["SG-PP-x.y"],
    "recommended_action": "what a human should do next",
}


class NoteParseError(ValueError):
    """The model's reply could not be turned into a valid note."""


THINKING = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def first_json_object(text: str) -> str | None:
    """The first balanced {...} in text, respecting strings."""
    start = text.find("{")
    while start != -1:
        depth, in_string, escaped = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None


def parse_note(content: str) -> InvestigatorNote:
    """Extract and validate the note from a reply.

    Tolerates the ways models wrap JSON: reasoning in ``<think>`` tags (Qwen 3
    emits these), a fenced code block, or prose around the object. Anything that
    is not a valid note raises :class:`NoteParseError` with a message the model
    can act on, because the Investigator feeds it straight back.
    """
    text = THINKING.sub("", content or "").strip()
    if not text:
        raise NoteParseError("The reply was empty. Reply with the JSON note only.")

    fenced = _FENCED.search(text)
    candidate = fenced.group(1) if fenced else first_json_object(text)
    if candidate is None:
        raise NoteParseError("No JSON object found. Reply with the JSON note only.")

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise NoteParseError(f"The JSON is malformed: {exc.msg} at position {exc.pos}.") from exc

    try:
        return InvestigatorNote.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'note'}: {e['msg']}" for e in exc.errors()
        )
        raise NoteParseError(f"The note is invalid - {problems}") from exc
