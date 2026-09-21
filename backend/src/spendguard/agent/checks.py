"""The Verifier's deterministic checks - no model involved (FR-4.1 to FR-4.3, D-13).

For every citation in a note (one per claim and cited row):

    does the row exist?                       row_exists
    does every value the claim states match?  values_match

and for the note as a whole:

    does every cited policy clause exist?
    does it avoid the wording the project forbids?

These are the headline citation-validity number because nothing about them is a
judgement call: the same note and the same database give the same answer every
time. The semantic check - does the row actually *support* the sentence - is
model-judged, lives in ``verifier.py``, and is reported as a separate number.

**How a stated value "matches".** A number matches if it equals the row's value
rounded to the precision the note stated it at: ``259463`` and ``259463.4`` both
match ``259463.41``, but ``260000`` does not - the prompt asks for exact values,
and a figure rounded to the thousand is a different figure. Dates match in any
common format; text matches ignoring case and spacing. Everything else is a miss.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import duckdb

from spendguard.agent.note import InvestigatorNote
from spendguard.db.duck import AUDIT_FIELDS, AUDIT_VIEW

NUMERIC_FIELDS = frozenset({"amount", "quantity", "unit_price"})
DATE_FIELDS = frozenset({"txn_date"})
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y")

# The anomaly is a duplicate *transaction record*: on purchase-order data "duplicate
# payment" is a false statement (CLAUDE.md wording discipline). The policy's own
# "duplicate-payment register" is a proper name and may be quoted.
FORBIDDEN_WORDING = (
    (
        re.compile(r"\bduplicate[\s-]payments?\b(?![\s-]register)", re.IGNORECASE),
        'Say "duplicate transaction record", never "duplicate payment": these records may '
        "be purchase orders.",
    ),
)

_CURRENCY = re.compile(r"(₹|\bRs\.?|\bINR\b|,|\s)", re.IGNORECASE)


@dataclass
class CitationCheck:
    """One citation's verdict. ``supports_claim`` is filled by the semantic check."""

    claim_index: int
    claim_text: str
    row_id: int
    asserted: dict[str, Any]
    row_exists: bool
    values_match: bool
    supports_claim: bool | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def deterministic_ok(self) -> bool:
        return self.row_exists and self.values_match

    @property
    def passed(self) -> bool:
        return self.deterministic_ok and self.supports_claim is not False

    @property
    def failure_reason(self) -> str | None:
        return "; ".join(self.problems) or None


@dataclass
class VerificationReport:
    citations: list[CitationCheck]
    note_problems: list[str] = field(default_factory=list)
    semantic_ran: bool = False  # the judge answered for every claim
    judge_error: str | None = None
    unsupported: dict[int, str] = field(default_factory=dict)  # claim index -> judge's reason

    @property
    def checked(self) -> int:
        return len(self.citations)

    @property
    def deterministic_passed(self) -> int:
        return sum(1 for c in self.citations if c.deterministic_ok)

    @property
    def semantic_passed(self) -> int | None:
        if not self.semantic_ran:
            return None
        return sum(1 for c in self.citations if c.supports_claim)

    @property
    def citations_passed(self) -> int:
        return sum(1 for c in self.citations if c.passed)

    @property
    def failures(self) -> int:
        """Everything wrong with the note, for choosing the best of several drafts."""
        return sum(1 for c in self.citations if not c.passed) + len(self.note_problems)

    @property
    def passed(self) -> bool:
        return self.failures == 0

    def feedback(self) -> str:
        """The objections, phrased for the model that wrote the note (FR-4.5)."""
        lines = [
            "The Verifier rejected your note. Fix every problem below, then reply with the "
            "corrected JSON note only. You may call tools if you need more evidence."
        ]
        for c in self.citations:
            if not c.deterministic_ok:
                lines.append(f"- Claim {c.claim_index}: {c.failure_reason}")
        for index, reason in sorted(self.unsupported.items()):
            lines.append(
                f"- Claim {index} is not supported by the rows it cites ({reason}). Cite the "
                "rows that show it, or remove or correct the claim."
            )
        lines += [f"- {problem}" for problem in self.note_problems]
        return "\n".join(lines)


# ------------------------------------------------------------------ value matching


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    text = _CURRENCY.sub("", str(value)) if isinstance(value, str) else repr(value)
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _numbers_match(asserted: Any, actual: Any) -> bool:
    stated = _decimal(asserted)
    if stated is None:
        return False
    places = max(-stated.as_tuple().exponent, 0)  # type: ignore[operator]
    quantum = Decimal(1).scaleb(-places)
    truth = Decimal(repr(float(actual))).quantize(quantum, rounding=ROUND_HALF_UP)
    return stated.quantize(quantum, rounding=ROUND_HALF_UP) == truth


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _normalized(value: Any) -> str:
    return " ".join(str(value).casefold().split()).strip(" .'\"")


def value_matches(field_name: str, asserted: Any, actual: Any) -> bool:
    """Does what the note states about a field equal what the row holds?"""
    if actual is None:
        return asserted is None or _normalized(asserted) in ("", "null", "none")
    if asserted is None:
        return False
    if field_name in NUMERIC_FIELDS:
        return _numbers_match(asserted, actual)
    if field_name in DATE_FIELDS:
        stated = _as_date(asserted)
        return stated is not None and stated == _as_date(actual)
    return _normalized(asserted) == _normalized(actual)


def _show(value: Any) -> str:
    return value.isoformat() if isinstance(value, date) else repr(value)


# ------------------------------------------------------------------ the checks


def fetch_rows(con: duckdb.DuckDBPyConnection, row_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Re-fetch cited rows from the same view the agent read (FR-4.2)."""
    if not row_ids:
        return {}
    rows = (
        con.execute(
            f"SELECT {', '.join(AUDIT_FIELDS)} FROM {AUDIT_VIEW} "
            "WHERE row_id IN (SELECT unnest(?)) ORDER BY row_id",
            [sorted(set(row_ids))],
        )
        .pl()
        .to_dicts()
    )
    return {int(r["row_id"]): r for r in rows}


def check_citations(
    con: duckdb.DuckDBPyConnection, note: InvestigatorNote, known_clauses: set[str]
) -> VerificationReport:
    """Every deterministic check on one note. Pure: the same inputs, the same report."""
    citations = note.citations()
    rows = fetch_rows(con, [c.row_id for c in citations])

    checks = []
    for c in citations:
        row = rows.get(c.row_id)
        check = CitationCheck(
            c.claim_index, c.claim_text, c.row_id, c.asserted, row is not None, row is not None
        )
        if row is None:
            check.problems.append(
                f"row {c.row_id} does not exist. Cite only rows you have seen in the case "
                "evidence or a tool result."
            )
        else:
            for name, stated in c.asserted.items():
                if not value_matches(name, stated, row.get(name)):
                    check.values_match = False
                    check.problems.append(
                        f"row {c.row_id} {name}: the note says {_show(stated)}, the row has "
                        f"{_show(row.get(name))}. State exact values."
                    )
        checks.append(check)

    problems = [
        f"Policy clause {clause} does not exist. Cite only clauses policy_lookup returned."
        for clause in note.policy_clauses
        if clause not in known_clauses
    ]
    text = " ".join([note.finding, note.recommended_action, *(c.text for c in note.claims)])
    problems += [message for pattern, message in FORBIDDEN_WORDING if pattern.search(text)]
    return VerificationReport(citations=checks, note_problems=problems)
