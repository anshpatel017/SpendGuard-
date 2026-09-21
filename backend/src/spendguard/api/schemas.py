"""Request and response bodies (docs/API-CONTRACT.md). The frontend's types are generated from these.

Money is ``Decimal`` so it serializes as a string - a float would round a
rupee amount on its way to the browser. Nulls are explicit: a field that does
not apply is ``null``, never an empty string or a zero standing in for missing.

Where this differs from the written contract it is additive (extra fields the
dashboard needs) or it replaces something the stack does not have; each such
field says so.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

AnomalyTypeName = Literal["duplicate", "split", "inflation", "vendor_flag"]
StatusName = Literal["new", "under_review", "confirmed", "dismissed"]
BandName = Literal["high", "medium", "low"]
VerdictName = Literal["likely_true_positive", "likely_false_positive", "inconclusive"]
VerificationName = Literal["verified", "unverified", "failed_after_retries"]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail


# ------------------------------------------------------------------ cases


class CaseBase(BaseModel):
    case_id: UUID
    run_id: str
    anomaly_type: AnomalyTypeName
    detector: str
    row_ids: list[int]
    vendor_key: str | None
    detector_score: float
    amount_at_risk: Decimal
    severity_prelim: float
    severity_final: float | None
    severity_band: BandName
    status: StatusName
    investigated: bool
    dismissed_by_agent: bool
    reviewer_note: str | None
    created_at: datetime
    updated_at: datetime


class Case(CaseBase):
    metadata: dict[str, Any]


class CaseSummary(CaseBase):
    """A queue row: the case, plus enough of its note to triage from the list."""

    verdict: VerdictName | None
    verification_status: VerificationName | None  # null until investigated
    citations_checked: int | None
    citations_passed: int | None
    finding_excerpt: str | None


class CaseListResponse(BaseModel):
    items: list[CaseSummary]
    total: int
    page: int
    page_size: int
    currency: str  # additive: money in the items is in this currency


class Citation(BaseModel):
    citation_id: UUID
    claim_index: int  # additive: groups citations back into their claim
    claim_text: str
    row_id: int
    asserted: dict[str, Any]  # additive: the values the claim states about this row
    row_exists: bool | None  # null only on notes stored before the Verifier existed
    values_match: bool | None
    supports_claim: bool | None  # null when the model judge did not run
    failure_reason: str | None


class TraceStep(BaseModel):
    step_index: int
    role: Literal["investigator", "verifier"]
    # additive: model, tool, parse_error, context_trim, forced_final, failed, check, judge
    kind: str
    tool_name: str | None
    tool_args: dict[str, Any] | None
    tool_result: Any
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    detail: str | None  # additive: what the step did, in words
    error: str | None


class AuditNote(BaseModel):
    note_id: UUID
    case_id: UUID
    finding: str
    recommended_action: str
    verdict: VerdictName
    policy_clauses: list[str]  # additive
    verification_status: VerificationName
    citations: list[Citation]
    citations_checked: int | None
    citations_passed: int | None
    deterministic_passed: int | None
    semantic_passed: int | None  # null when the judge did not run: model-judged, reported apart
    retry_count: int
    model_name: str
    created_at: datetime


class TransactionRow(BaseModel):
    row_id: int
    vendor_name: str
    vendor_key: str
    invoice_no: str | None
    amount: Decimal
    txn_date: date
    officer_id: str | None
    item_desc: str | None
    item_category: str | None
    quantity: float | None
    unit_price: Decimal | None
    in_case: bool
    cited: bool  # additive: the audit note cites this row


class CaseDetailResponse(BaseModel):
    case: Case
    audit_note: AuditNote | None  # null when not yet investigated, never a note full of nulls
    evidence_rows: list[TransactionRow]
    evidence_total: int  # additive: the case may have more rows than returned; see /evidence
    context_rows: list[TransactionRow]  # rows the note cites outside the case, then nearby rows
    trace: list[TraceStep]
    currency: str


class EvidenceResponse(BaseModel):
    case_id: UUID
    rows: list[TransactionRow]
    total: int


class StatusUpdateRequest(BaseModel):
    status: StatusName
    reviewer_note: str | None = Field(default=None, max_length=4000)


# ------------------------------------------------------------------ overview


class AnomalyBreakdown(BaseModel):
    count: int
    amount_at_risk: Decimal


class MetricsResponse(BaseModel):
    dataset: str | None  # additive: which dataset the dashboard is showing
    # additive: set when the dataset is an evaluation copy with planted anomalies
    evaluation_seed: int | None
    total_transactions: int
    total_amount: Decimal
    currency: str
    converted_from: str | None  # additive: source currency when amounts were converted (FR-6.10)

    cases_flagged: int
    cases_investigated: int
    cases_queued: int  # flagged minus investigated

    money_at_risk: Decimal
    money_at_risk_confirmed: Decimal

    by_anomaly_type: dict[str, AnomalyBreakdown]
    by_severity_band: dict[str, int]
    by_status: dict[str, int]
    by_verdict: dict[str, int]  # additive
    by_verification_status: dict[str, int]  # additive

    last_run_id: str | None
    last_run_at: datetime | None


class RunSummary(BaseModel):
    run_id: str
    kind: Literal["ingest", "detect", "investigate", "evaluate"]
    status: Literal["running", "completed", "failed"]
    seed: int | None
    started_at: datetime
    finished_at: datetime | None
    summary: dict[str, Any]


class DetectorMetrics(BaseModel):
    detector: str
    anomaly_type: str  # additive: the contract's table is per detector *and* type
    granularity: Literal["case", "row"]
    precision: float
    recall: float
    f1: float
    pr_auc: float | None
    tp: int
    fp: int
    fn: int


class AgentMetrics(BaseModel):
    """Null where nothing has been measured yet - never a zero standing in for missing."""

    notes: int
    citation_validity_deterministic: float | None
    citation_validity_semantic: float | None  # model-judged
    triage_accuracy: float | None  # decisive verdicts only; see the report for the full table
    avg_tool_calls: float | None
    avg_tokens: float | None
    avg_latency_seconds: float | None  # model and tool time, excluding rate-limit waits
    notes_regenerated: int
    notes_failed_after_retries: int


class AblationRow(BaseModel):
    ablation_name: str
    configuration: str
    citation_validity_deterministic: float | None
    citation_validity_semantic: float | None
    triage_accuracy: float | None
    note_quality_score: float | None


class EvaluationResponse(BaseModel):
    run_id: str | None
    seed: int
    dataset: str | None
    injected_anomaly_count: int | None
    detector_metrics: list[DetectorMetrics]
    baseline_metrics: list[DetectorMetrics]
    agent_metrics: AgentMetrics
    ablations: list[AblationRow]
    generated_at: datetime | None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    duckdb: bool
    case_store: bool  # replaces the contract's "postgres": the store is SQLite (D-09)
    # Configured, not probed: probing spends the free tier's daily request quota
    # every time the dashboard checks health. `spendguard check-llm` probes.
    llm_configured: bool
    llm_model: str | None
