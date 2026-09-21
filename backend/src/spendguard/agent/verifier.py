"""The Verifier - checks every citation, and sends failures back for correction.

    check the draft note
        deterministic: every cited row exists, every stated value matches  (checks.py)
        semantic:      the cited evidence supports each claim               (LLM judge)
    if anything failed and retries remain:
        feed the failures back into the Investigator's conversation, get a revision
    release the best draft, with its verification status and counts

The judge is a **separate call with a fresh context**: it never sees the
Investigator's reasoning, only the claims, the rows they cite and the tool results
the Investigator obtained. It judges claims, not rows one at a time, because a
claim like "the three orders total Rs 3,60,000" is supported by its rows
together, not by any one of them.

The judge is the same model that wrote the note, which is why its number is
reported separately and labelled model-judged (D-13). The deterministic number
is the headline, because nothing about it is a judgement call.

A note is never released as verified unless both checks ran and passed. If the
judge could not run - quota spent, a reply that never parsed - the note is
released as ``unverified``. If failures remain after the retry limit it is
released as ``failed_after_retries``, with the best draft rather than the last:
a revision that made things worse should not replace one that was better.
"""

from __future__ import annotations

import json
import time
from typing import Any

import duckdb
from pydantic import BaseModel, ConfigDict, ValidationError

from spendguard.agent.checks import VerificationReport, check_citations, fetch_rows
from spendguard.agent.investigator import (
    ChatModel,
    InvestigationResult,
    Investigator,
    TraceStep,
    fit_json,
)
from spendguard.agent.llm import LLMCallError, LLMQuotaExhaustedError
from spendguard.agent.note import THINKING, InvestigatorNote, first_json_object
from spendguard.cases import Case
from spendguard.config import settings

VERIFIED = "verified"
UNVERIFIED = "unverified"
FAILED_AFTER_RETRIES = "failed_after_retries"

# How often an unparseable judgement is asked for again before the semantic check
# is declared unavailable for this draft.
MAX_JUDGE_ATTEMPTS = 2

# Tool results the judge may weigh, most useful first. A calculator result is the
# evidence for an arithmetic claim; a vendor profile for a claim about history.
JUDGE_TOOLS = ("calculator", "vendor_profile", "benford_stats", "find_similar_invoices")
MAX_RESULT_CHARS_EACH = 700

JUDGE_PROMPT = """\
You check an auditor's claims against the evidence they cite. You did not write them.

For each numbered claim decide whether the evidence below supports it:
- supported: the cited rows, with the tool results listed, show what the claim says.
- not supported: the evidence does not show it, or shows something different.

Rules:
- Judge only from the evidence given here. No outside knowledge, no benefit of the doubt.
- Be strict about specifics - amounts, dates, names, counts, "same" and "different" - \
and lenient about wording.
- Calculator results are correct; use them rather than doing arithmetic yourself.
- A claim about a supplier's history or pattern needs the tool results or the cited rows \
to show it.

Reply with one JSON object and nothing else:
{"claims":[{"index":0,"supported":true,"reason":"one short sentence"}]}
"""


class _Judgement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    supported: bool
    reason: str = ""


class _Judgements(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claims: list[_Judgement]


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def known_clause_ids() -> set[str]:
    from spendguard.agent.policy import parse_clauses

    return {c.clause_id for c in parse_clauses()}


class Verifier:
    def __init__(
        self,
        llm: ChatModel,
        con: duckdb.DuckDBPyConnection,
        *,
        clause_ids: set[str] | None = None,
        semantic: bool | None = None,
    ) -> None:
        self.llm = llm
        self.con = con
        self.clause_ids = clause_ids if clause_ids is not None else known_clause_ids()
        self.semantic = settings.verifier_semantic_check if semantic is None else semantic

    # ------------------------------------------------------------ one draft

    def check(
        self, result: InvestigationResult, *, semantic: bool | None = None
    ) -> VerificationReport:
        """Both checks on the current note; each is recorded in the trace as a verifier step."""
        assert result.note is not None
        started = time.perf_counter()
        report = check_citations(self.con, result.note, self.clause_ids)
        self._record(
            result,
            kind="check",
            latency_ms=int((time.perf_counter() - started) * 1000),
            tool_result={
                "checked": report.checked,
                "deterministic_passed": report.deterministic_passed,
                "problems": [c.failure_reason for c in report.citations if c.failure_reason]
                + report.note_problems,
            },
            note=f"{report.deterministic_passed}/{report.checked} citations exist and match",
        )
        if self.semantic if semantic is None else semantic:
            self._judge(result, report)
        return report

    def _judge(self, result: InvestigationResult, report: VerificationReport) -> None:
        note = result.note
        assert note is not None
        messages = [
            {"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": self.evidence_brief(note, result)},
        ]
        for attempt in range(1, MAX_JUDGE_ATTEMPTS + 1):
            try:
                reply = self.llm.chat(
                    messages, temperature=settings.verifier_temperature, max_tokens=None
                )
            except LLMCallError as exc:
                report.judge_error = str(exc)
                result.quota_exhausted = result.quota_exhausted or isinstance(
                    exc, LLMQuotaExhaustedError
                )
                self._record(result, kind="judge", error=report.judge_error)
                return
            verdicts, problem = self._parse(reply.content, len(note.claims))
            self._record(
                result,
                kind="judge",
                latency_ms=int(reply.latency_seconds * 1000),
                prompt_tokens=reply.prompt_tokens,
                completion_tokens=reply.completion_tokens,
                tool_result={i: {"supported": s, "reason": r} for i, (s, r) in verdicts.items()},
                note=(
                    f"{sum(s for s, _ in verdicts.values())}/{len(note.claims)} claims supported"
                    if problem is None
                    else None
                ),
                error=problem,
            )
            if problem is None:
                break
            if attempt < MAX_JUDGE_ATTEMPTS:
                messages += [
                    {"role": "assistant", "content": reply.content},
                    {"role": "user", "content": f"{problem} Reply with the JSON object only."},
                ]
        else:
            report.judge_error = problem
            return

        report.semantic_ran = True
        for check in report.citations:
            supported, reason = verdicts[check.claim_index]
            check.supports_claim = supported
            if not supported:
                check.problems.append(f"not supported: {reason}")
                report.unsupported[check.claim_index] = reason

    @staticmethod
    def _parse(content: str, n_claims: int) -> tuple[dict[int, tuple[bool, str]], str | None]:
        text = THINKING.sub("", content or "")
        candidate = first_json_object(text)
        if candidate is None:
            return {}, "No JSON object in the reply."
        try:
            parsed = _Judgements.model_validate(json.loads(candidate))
        except (json.JSONDecodeError, ValidationError) as exc:
            return {}, f"The JSON is invalid: {str(exc).splitlines()[0]}"
        verdicts = {
            j.index: (j.supported, j.reason.strip() or "no reason given") for j in parsed.claims
        }
        missing = sorted(set(range(n_claims)) - set(verdicts))
        if missing:
            return verdicts, f"Judge every claim; missing claim indexes {missing}."
        return verdicts, None

    def evidence_brief(self, note: InvestigatorNote, result: InvestigationResult) -> str:
        """What the judge sees: the claims, the rows they cite, the tool results obtained."""
        lines = ["Claims:"]
        for i, claim in enumerate(note.claims):
            lines.append(f"[{i}] {claim.text} (cites rows {', '.join(map(str, claim.row_ids))})")

        cited = list(dict.fromkeys(r for claim in note.claims for r in claim.row_ids))
        rows = fetch_rows(self.con, cited[: settings.verifier_max_rows])
        lines += ["", "Cited rows:"]
        lines += [_compact(rows[r]) for r in cited if r in rows]
        missing = [r for r in cited[: settings.verifier_max_rows] if r not in rows]
        if missing:
            lines.append(f"Rows {missing} do not exist.")
        if len(cited) > settings.verifier_max_rows:
            lines.append(f"({len(cited) - settings.verifier_max_rows} more cited rows not shown.)")

        context = self._tool_context(result)
        if context:
            lines += ["", "Tool results the auditor obtained:", *context]
        return "\n".join(lines)

    @staticmethod
    def _tool_context(result: InvestigationResult) -> list[str]:
        steps = [
            s
            for s in result.trace
            if s.kind == "tool" and s.tool_name in JUDGE_TOOLS and not s.error
        ]
        steps.sort(key=lambda s: JUDGE_TOOLS.index(s.tool_name or ""))
        lines: list[str] = []
        budget = settings.verifier_context_chars
        for step in steps:
            text = fit_json(step.tool_result, MAX_RESULT_CHARS_EACH)
            line = f"{step.tool_name}({_compact(step.tool_args or {})}) -> {text}"
            if len(line) > budget:
                break
            lines.append(line)
            budget -= len(line)
        return lines

    @staticmethod
    def _record(result: InvestigationResult, **kwargs: Any) -> None:
        result.trace.append(TraceStep(step_index=len(result.trace), role="verifier", **kwargs))


# ------------------------------------------------------------------ the loop


def investigate_and_verify(
    investigator: Investigator,
    verifier: Verifier | None,
    case: Case,
    *,
    max_retries: int | None = None,
    enabled: bool | None = None,
) -> InvestigationResult:
    """Investigate one case, then verify and regenerate until it passes or retries run out.

    With the Verifier disabled (the FR-7.8 ablation) the note is released as
    ``unverified`` and never regenerated - but the deterministic check still
    runs, so the ablation's citation validity is measured the same way.
    """
    enabled = settings.verifier_enabled if enabled is None else enabled
    max_retries = settings.verifier_max_retries if max_retries is None else max_retries

    result = investigator.investigate(case)
    if result.note is None or verifier is None:
        return result

    report = verifier.check(result, semantic=None if enabled else False)
    result.first_check = report
    drafts: list[tuple[InvestigatorNote, VerificationReport]] = [(result.note, report)]

    while (
        enabled
        and not report.passed
        and result.retry_count < max_retries
        and not result.quota_exhausted
    ):
        result.retry_count += 1
        revised = investigator.revise(case, result, report.feedback())
        if revised is None:
            break
        result.note = revised
        report = verifier.check(result)
        drafts.append((revised, report))

    # Fewest failures wins; among equals, the latest draft.
    best = min(range(len(drafts)), key=lambda i: (drafts[i][1].failures, -i))
    result.note, result.verification = drafts[best]
    investigator.finalize(case, result)

    result.verification_status = release_status(result.verification, enabled=enabled)
    return result


def release_status(report: VerificationReport, *, enabled: bool = True) -> str:
    """The badge a released note carries (FR-4.6, FR-4.7).

    Verifier off                      -> unverified (the ablation; nothing was enforced)
    anything known to be wrong        -> failed_after_retries, however many retries ran
    nothing wrong, and the judge ran  -> verified
    nothing wrong, judge off/failed   -> unverified: only half the checking happened
    """
    if not enabled:
        return UNVERIFIED
    if report.failures:
        return FAILED_AFTER_RETRIES
    return VERIFIED if report.semantic_ran else UNVERIFIED
