"""The Investigator - a hand-written tool-calling loop (decision D-11).

    brief the model on the case and hand it the six tools
    repeat, at most AGENT_MAX_STEPS times:
        the model either calls tools   -> run them, feed the results back
        or replies with a note         -> parse and validate it; done
        or replies with something else -> say what was wrong, let it retry
    out of steps without a note        -> one last turn with tools switched off

Before every turn the conversation is fitted to a token budget: every turn
resends everything, so a long investigation eventually exceeds what the endpoint
accepts. The oldest tool results are trimmed first, down to the row ids they
contained, so the model keeps track of what it has seen.

No framework. Every step is a few lines that can be read, stepped through in a
debugger, and explained under questioning - which is the reason for writing it
by hand. Every step is also recorded in a trace: what the model asked for, what
it got back, how long it took and what it cost.

The Investigator never writes to the case store and never closes a case. It
returns a result; what happens to that result is decided elsewhere, and the
final decision is always a person's (D-04).
"""

from __future__ import annotations

import contextlib
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import duckdb

from spendguard.agent.llm import (
    LLMCallError,
    LLMQuotaExhaustedError,
    LLMRequestTooLargeError,
    LLMResponse,
    ToolCall,
)
from spendguard.agent.note import InvestigatorNote, NoteParseError, Verdict, parse_note
from spendguard.agent.prompts import case_brief, system_prompt
from spendguard.agent.tools import ToolBox
from spendguard.cases import Case
from spendguard.config import SeverityBand, settings
from spendguard.db.duck import AUDIT_FIELDS, AUDIT_VIEW

if TYPE_CHECKING:
    from spendguard.agent.checks import VerificationReport

# How many times a malformed note is sent back for correction before giving up.
MAX_PARSE_RETRIES = 2
# How many times a refused-as-too-large request is shrunk and retried.
MAX_SHRINKS = 2
# Starting guess for characters per token, corrected from the first real reply.
# Deliberately low (compact JSON tokenizes densely) so the first estimate errs high.
INITIAL_CHARS_PER_TOKEN = 3.0
MAX_ELIDED_ROW_IDS = 30


class ContextFullError(LLMCallError):
    """Even with old results trimmed, the next turn would not fit the budget."""


class ChatModel(Protocol):
    """Anything that can take a turn. LLMClient in production, a script in tests."""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: str = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...


@dataclass
class TraceStep:
    """One entry in the investigation trace (docs/DATA-SCHEMA.md 2.4)."""

    step_index: int
    kind: str  # "model", "tool", "parse_error", "context_trim", "forced_final", "failed",
    #            and for the Verifier: "check", "judge"
    latency_ms: int = 0
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    note: str | None = None
    error: str | None = None
    role: str = "investigator"  # or "verifier"


@dataclass
class InvestigationResult:
    case_id: str
    anomaly_type: str
    status: str  # "completed" or "failed"
    model: str
    note: InvestigatorNote | None = None
    severity_final: float | None = None
    severity_band: str | None = None
    trace: list[TraceStep] = field(default_factory=list)
    seen_row_ids: set[int] = field(default_factory=set)
    error: str | None = None
    seconds: float = 0.0
    quota_exhausted: bool = False  # stopped by the provider's quota, not by the case
    # The conversation so far, kept so the Verifier's objections can continue it.
    # Not persisted: the trace is the durable record.
    messages: list[dict[str, Any]] = field(default_factory=list, repr=False)
    # Set by the Verifier (Phase 7). "unverified" until a check has run to completion.
    verification: VerificationReport | None = None
    first_check: VerificationReport | None = None  # the first draft's report, for reporting
    verification_status: str = "unverified"
    retry_count: int = 0

    @property
    def verdict(self) -> Verdict | None:
        return self.note.verdict if self.note else None

    @property
    def dismissed_by_agent(self) -> bool:
        return self.verdict is Verdict.LIKELY_FALSE_POSITIVE

    @property
    def tool_calls(self) -> int:
        return sum(1 for s in self.trace if s.kind == "tool")

    @property
    def prompt_tokens(self) -> int:
        return sum(s.prompt_tokens for s in self.trace)

    @property
    def completion_tokens(self) -> int:
        return sum(s.completion_tokens for s in self.trace)

    @property
    def unseen_citations(self) -> list[int]:
        """Rows the note cites that never appeared in the brief or a tool result.

        Not proof of fabrication - the model may have inferred a real id - but the
        first thing the Verifier should look at, and a number worth reporting.
        """
        if not self.note:
            return []
        return sorted(set(self.note.cited_row_ids) - self.seen_row_ids)


def final_severity(prelim: float, verdict: Verdict) -> tuple[float, SeverityBand]:
    """Stage-2 severity after investigation (decision D-08; open issue O-04).

    ``likely_false_positive`` drops the case to Low, ``inconclusive`` caps it at
    Medium, ``likely_true_positive`` keeps its preliminary severity.

    The *number* moves with the band - capped just below the band edge - rather
    than only the label changing. That keeps sorting by severity and filtering by
    band in agreement, and preserves the relative order of cases within a band.
    This is the recommended resolution of O-04, isolated here so it is one
    function to change if the decision goes the other way.
    """
    if verdict is Verdict.LIKELY_FALSE_POSITIVE:
        value = min(prelim, settings.severity_band_medium - 0.01)
    elif verdict is Verdict.INCONCLUSIVE:
        value = min(prelim, settings.severity_band_high - 0.01)
    else:
        value = prelim
    value = round(max(value, 0.0), 2)
    return value, settings.band_for(value)


def _record(result: InvestigationResult, **kwargs: Any) -> None:
    result.trace.append(TraceStep(step_index=len(result.trace), **kwargs))


def _row_ids_in(value: Any, found: set[int]) -> None:
    """Collect every row_id mentioned anywhere in a tool result."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "row_id" and isinstance(item, int):
                found.add(item)
            else:
                _row_ids_in(item, found)
    elif isinstance(value, list):
        for item in value:
            _row_ids_in(item, found)


def _dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str, ensure_ascii=False)


def fit_json(value: Any, limit: int) -> str:
    """A tool result as compact JSON of at most ``limit`` characters, cut by whole list items.

    Lists are shortened one item at a time, the bulkiest first, and every scalar
    field is kept. Cutting the text mid-way was tried twice and failed twice:
    the Investigator re-ran queries it could not see the end of, and the
    Verifier's judge lost a vendor profile's ``looks_like_fixed_contract``
    field - it sat past the cut - and rejected a true claim. Only a result with
    no lists left to shorten is cut as text.
    """
    text = _dump(value)
    if len(text) <= limit or not isinstance(value, dict):
        return text if len(text) <= limit else text[:limit] + ' ..."(truncated)"'
    trimmed = dict(value)
    totals = {k: len(v) for k, v in value.items() if isinstance(v, list) and v}
    while len(text) > limit:
        candidates = [k for k in totals if trimmed[k]]
        if not candidates:
            return text[:limit] + ' ..."(truncated)"'
        key = max(candidates, key=lambda k: len(_dump(trimmed[k])))
        trimmed[key] = trimmed[key][:-1]
        shown = ", ".join(
            f"{len(trimmed[k])} of {n} {k}" for k, n in totals.items() if len(trimmed[k]) < n
        )
        text = _dump({**trimmed, "shown": f"{shown}; narrow the request to see the rest"})
    return text


def _chars(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> int:
    """Size of a request as sent - the measure the token estimate is calibrated on."""
    return len(json.dumps(messages, default=str)) + len(json.dumps(tools or []))


def _elided(content: str) -> str:
    """What a trimmed tool result becomes: a marker and the rows it mentioned."""
    found: set[int] = set()
    with contextlib.suppress(json.JSONDecodeError):  # a truncated result is not valid JSON
        _row_ids_in(json.loads(content), found)
    ids = sorted(found)
    summary: dict[str, Any] = {"elided": "older tool result removed to fit the context budget"}
    if ids:
        summary["row_ids"] = ids[:MAX_ELIDED_ROW_IDS]
        if len(ids) > MAX_ELIDED_ROW_IDS:
            summary["more_rows"] = len(ids) - MAX_ELIDED_ROW_IDS
    return json.dumps(summary, separators=(",", ":"))


def _assistant_message(reply: LLMResponse) -> dict[str, Any]:
    """Echo the model's tool request back into the conversation, in API format."""
    return {
        "role": "assistant",
        "content": reply.content or None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": call.raw_arguments or json.dumps(call.arguments),
                },
            }
            for call in reply.tool_calls
        ],
    }


class Investigator:
    def __init__(
        self,
        llm: ChatModel,
        con: duckdb.DuckDBPyConnection,
        *,
        policy_index: Any | None = None,
        max_steps: int | None = None,
        model_name: str | None = None,
    ) -> None:
        self.llm = llm
        self.con = con
        self.policy_index = policy_index
        self.max_steps = max_steps or settings.agent_max_steps
        self.model_name = model_name or str(getattr(llm, "model", "unknown"))
        self.context_tokens = settings.agent_context_tokens
        self.chars_per_token = INITIAL_CHARS_PER_TOKEN

    def evidence(self, case: Case) -> list[dict[str, Any]]:
        """The case's own rows, from the same view the tools read."""
        return (
            self.con.execute(
                f"SELECT {', '.join(AUDIT_FIELDS)} FROM {AUDIT_VIEW} "
                "WHERE row_id IN (SELECT unnest(?)) ORDER BY txn_date, row_id",
                [list(case.row_ids)],
            )
            .pl()
            .to_dicts()
        )

    def estimate_tokens(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> int:
        return int(_chars(messages, tools) / self.chars_per_token)

    def fit_to_budget(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        budget: int,
        *,
        keep_latest: bool = True,
    ) -> tuple[int, bool]:
        """Trim earlier tool results until the request fits. Returns (trimmed, fits).

        The bulkiest results go first: a 50-row query is the cost, while a vendor
        profile or a calculator result is small and dense, and when trimmed the
        model simply asked for it again. The system prompt and the case brief are
        never touched, and neither is the latest turn unless ``keep_latest`` is
        off: while investigating, the model needs the results it just asked for.
        """
        last_assistant = max(
            (i for i, m in enumerate(messages) if m["role"] == "assistant"), default=0
        )
        protect_from = last_assistant if keep_latest else len(messages)
        candidates = sorted(
            (
                i
                for i, m in enumerate(messages[:protect_from])
                if m["role"] == "tool" and '"elided"' not in m["content"]
            ),
            key=lambda i: -len(messages[i]["content"]),
        )
        trimmed = 0
        for i in candidates:
            if self.estimate_tokens(messages, tools) <= budget:
                break
            messages[i] = {**messages[i], "content": _elided(messages[i]["content"])}
            trimmed += 1
        return trimmed, self.estimate_tokens(messages, tools) <= budget

    def _turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        record: Any,
        *,
        tool_choice: str = "auto",
        final: bool = False,
    ) -> LLMResponse:
        """One model call, fitted to the budget, shrinking further if still refused."""
        budget = self.context_tokens
        for shrink in range(MAX_SHRINKS + 1):
            trimmed, fits = self.fit_to_budget(messages, tools, budget, keep_latest=not final)
            if trimmed:
                record(
                    kind="context_trim",
                    note=f"trimmed {trimmed} older tool result(s) to fit {budget} tokens",
                )
            if not fits:
                raise ContextFullError(
                    f"The conversation does not fit in {budget} tokens even with old results "
                    "trimmed."
                )
            sent = _chars(messages, tools)
            try:
                reply = self.llm.chat(messages, tools=tools, tool_choice=tool_choice)
            except LLMRequestTooLargeError:
                if shrink == MAX_SHRINKS:
                    raise
                budget = int(budget * 0.75)
                continue
            if reply.prompt_tokens > 0:  # calibrate the estimate on what the API counted
                self.chars_per_token = sent / reply.prompt_tokens
            return reply
        raise AssertionError("unreachable")

    def _result_payload(self, result: dict[str, Any]) -> str:
        """A tool result as the model sees it: cut to size by whole rows (see fit_json)."""
        return fit_json(result, settings.agent_tool_result_chars)

    def investigate(self, case: Case) -> InvestigationResult:
        started = time.perf_counter()
        rows = self.evidence(case)
        result = InvestigationResult(
            case_id=case.case_id,
            anomaly_type=case.anomaly_type.value,
            status="failed",
            model=self.model_name,
            seen_row_ids={int(r["row_id"]) for r in rows},
        )
        result.messages = [
            {"role": "system", "content": system_prompt(case.anomaly_type)},
            {"role": "user", "content": case_brief(case, rows)},
        ]
        try:
            result.note, result.error = self._gather(result)
        except LLMCallError as exc:
            self._fail(result, exc)
        if result.note is None and result.error and result.trace[-1].kind != "failed":
            _record(result, kind="failed", error=result.error)

        self.finalize(case, result)
        result.seconds = round(time.perf_counter() - started, 2)
        return result

    def revise(
        self, case: Case, result: InvestigationResult, feedback: str
    ) -> InvestigatorNote | None:
        """Continue the same conversation with the Verifier's objections (FR-4.5).

        Cheaper than investigating again - the evidence is already in the
        conversation - and the model can still call tools if the objection means
        it needs more. Returns the corrected note, or None if none came back; the
        caller keeps the previous note in that case, so a failed revision never
        loses a note that existed.
        """
        started = time.perf_counter()
        result.messages.append({"role": "user", "content": feedback})
        try:
            note, error = self._gather(result)
        except LLMCallError as exc:
            self._fail(result, exc)
            note, error = None, None
        if note is None and error:
            _record(result, kind="failed", error=f"revision: {error}")
        result.seconds = round(result.seconds + time.perf_counter() - started, 2)
        return note

    def finalize(self, case: Case, result: InvestigationResult) -> None:
        """Status and final severity follow whichever note stands."""
        if result.note is None:
            result.status = "failed"
            return
        result.status = "completed"
        result.error = None
        result.severity_final, band = final_severity(case.severity_prelim, result.note.verdict)
        result.severity_band = band.value

    @staticmethod
    def _fail(result: InvestigationResult, exc: LLMCallError) -> None:
        result.error = str(exc)
        result.quota_exhausted = isinstance(exc, LLMQuotaExhaustedError)
        _record(result, kind="failed", error=result.error)  # persisted with the trace

    def _gather(self, result: InvestigationResult) -> tuple[InvestigatorNote | None, str | None]:
        """The loop: tool calls until a valid note. Returns (note, reason if none).

        Provider failures propagate as LLMCallError; everything else - malformed
        notes, running out of steps or context - ends here with a reason.
        """
        messages = result.messages
        box = ToolBox(self.con, policy_index=self.policy_index)
        tools = box.schemas()
        parse_failures = 0

        def record(**kwargs: Any) -> None:
            _record(result, **kwargs)

        for _ in range(self.max_steps):
            try:
                reply = self._turn(messages, tools, record)
            except ContextFullError:
                record(kind="context_trim", note="context budget reached; writing the note")
                break
            record(
                kind="model",
                latency_ms=int(reply.latency_seconds * 1000),
                prompt_tokens=reply.prompt_tokens,
                completion_tokens=reply.completion_tokens,
                note=(
                    f"requested {', '.join(c.name for c in reply.tool_calls)}"
                    if reply.wants_tool
                    else "replied with a note"
                ),
            )

            if reply.wants_tool:
                messages.append(_assistant_message(reply))
                for call in reply.tool_calls:
                    self._run_tool(call, box, messages, record, result)
                continue

            messages.append({"role": "assistant", "content": reply.content})
            try:
                return parse_note(reply.content), None
            except NoteParseError as exc:
                parse_failures += 1
                record(kind="parse_error", error=str(exc))
                if parse_failures > MAX_PARSE_RETRIES:
                    return None, f"Gave up after {parse_failures} malformed notes: {exc}"
                messages.append({"role": "user", "content": f"{exc} Fix it and reply again."})

        note = self._forced_final(messages, tools, record)
        return (note, None) if note else (None, "No valid note within the step limit.")

    def _run_tool(
        self,
        call: ToolCall,
        box: ToolBox,
        messages: list[dict[str, Any]],
        record: Any,
        result: InvestigationResult,
    ) -> None:
        began = time.perf_counter()
        output = box.run(call.name, call.arguments)
        _row_ids_in(output, result.seen_row_ids)
        record(
            kind="tool",
            latency_ms=int((time.perf_counter() - began) * 1000),
            tool_name=call.name,
            tool_args=call.arguments,
            tool_result=output,
            error=output.get("error") if isinstance(output, dict) else None,
        )
        messages.append(
            {"role": "tool", "tool_call_id": call.id, "content": self._result_payload(output)}
        )

    def _forced_final(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], record: Any
    ) -> InvestigatorNote | None:
        """Out of steps or out of room: tools off, one last chance to write the note."""
        messages.append(
            {
                "role": "user",
                "content": (
                    "Stop gathering evidence: the step or context limit is reached. Using only "
                    "the evidence you already have, reply now with the JSON note and nothing else."
                ),
            }
        )
        reply = self._turn(messages, tools, record, tool_choice="none", final=True)
        usage = {
            "latency_ms": int(reply.latency_seconds * 1000),
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
        }
        messages.append({"role": "assistant", "content": reply.content})
        try:
            note = parse_note(reply.content)
        except NoteParseError as exc:
            record(kind="forced_final", error=str(exc), **usage)
            return None
        record(kind="forced_final", note="note written with tools switched off", **usage)
        return note
