// Runtime validation of API responses (API-CONTRACT section 4).
//
// Each schema is declared `satisfies z.ZodType<GeneratedType>`, so the two
// defences cover each other: if the backend adds or renames a field, the
// generated type changes and these no longer compile; if a response ever
// arrives in the wrong shape anyway, parsing fails with a visible error
// instead of a blank screen or a silently wrong number.
import { z } from "zod";

import type {
  AuditNote,
  Case,
  CaseDetailResponse,
  CaseListResponse,
  CaseSummary,
  Citation,
  DetectorMetrics,
  EvaluationResponse,
  HealthResponse,
  MetricsResponse,
  TraceStep,
  TransactionRow,
} from "./types";

const money = z.string().regex(/^-?\d+(\.\d+)?$/, "money must be a decimal string");
const anomalyType = z.enum(["duplicate", "split", "inflation", "vendor_flag"]);
const status = z.enum(["new", "under_review", "confirmed", "dismissed"]);
const band = z.enum(["high", "medium", "low"]);
const verdict = z.enum(["likely_true_positive", "likely_false_positive", "inconclusive"]);
const verification = z.enum(["verified", "unverified", "failed_after_retries"]);
const record = z.record(z.string(), z.unknown());
// Any JSON value. Not z.unknown(): zod makes an unknown-typed key optional, and the
// contract says tool_result is always present (null when there is none).
const json = z.union([record, z.array(z.unknown()), z.string(), z.number(), z.boolean(), z.null()]);

const caseBase = {
  case_id: z.string(),
  run_id: z.string(),
  anomaly_type: anomalyType,
  detector: z.string(),
  row_ids: z.array(z.number()),
  vendor_key: z.string().nullable(),
  detector_score: z.number(),
  amount_at_risk: money,
  severity_prelim: z.number(),
  severity_final: z.number().nullable(),
  severity_band: band,
  status,
  investigated: z.boolean(),
  dismissed_by_agent: z.boolean(),
  reviewer_note: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
};

export const caseSchema = z.object({ ...caseBase, metadata: record }) satisfies z.ZodType<Case>;

export const caseSummarySchema = z.object({
  ...caseBase,
  verdict: verdict.nullable(),
  verification_status: verification.nullable(),
  citations_checked: z.number().nullable(),
  citations_passed: z.number().nullable(),
  finding_excerpt: z.string().nullable(),
}) satisfies z.ZodType<CaseSummary>;

export const caseListSchema = z.object({
  items: z.array(caseSummarySchema),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
  currency: z.string(),
}) satisfies z.ZodType<CaseListResponse>;

const citationSchema = z.object({
  citation_id: z.string(),
  claim_index: z.number(),
  claim_text: z.string(),
  row_id: z.number(),
  asserted: record,
  row_exists: z.boolean().nullable(),
  values_match: z.boolean().nullable(),
  supports_claim: z.boolean().nullable(),
  failure_reason: z.string().nullable(),
}) satisfies z.ZodType<Citation>;

const noteSchema = z.object({
  note_id: z.string(),
  case_id: z.string(),
  finding: z.string(),
  recommended_action: z.string(),
  verdict,
  policy_clauses: z.array(z.string()),
  verification_status: verification,
  citations: z.array(citationSchema),
  citations_checked: z.number().nullable(),
  citations_passed: z.number().nullable(),
  deterministic_passed: z.number().nullable(),
  semantic_passed: z.number().nullable(),
  retry_count: z.number(),
  model_name: z.string(),
  created_at: z.string(),
}) satisfies z.ZodType<AuditNote>;

const traceSchema = z.object({
  step_index: z.number(),
  role: z.enum(["investigator", "verifier"]),
  kind: z.string(),
  tool_name: z.string().nullable(),
  tool_args: record.nullable(),
  tool_result: json,
  latency_ms: z.number(),
  prompt_tokens: z.number().nullable(),
  completion_tokens: z.number().nullable(),
  detail: z.string().nullable(),
  error: z.string().nullable(),
}) satisfies z.ZodType<TraceStep>;

export const transactionSchema = z.object({
  row_id: z.number(),
  vendor_name: z.string(),
  vendor_key: z.string(),
  invoice_no: z.string().nullable(),
  amount: money,
  txn_date: z.string(),
  officer_id: z.string().nullable(),
  item_desc: z.string().nullable(),
  item_category: z.string().nullable(),
  quantity: z.number().nullable(),
  unit_price: money.nullable(),
  in_case: z.boolean(),
  cited: z.boolean(),
}) satisfies z.ZodType<TransactionRow>;

export const caseDetailSchema = z.object({
  case: caseSchema,
  audit_note: noteSchema.nullable(),
  evidence_rows: z.array(transactionSchema),
  evidence_total: z.number(),
  context_rows: z.array(transactionSchema),
  trace: z.array(traceSchema),
  currency: z.string(),
}) satisfies z.ZodType<CaseDetailResponse>;

const count = z.record(z.string(), z.number());

export const metricsSchema = z.object({
  dataset: z.string().nullable(),
  evaluation_seed: z.number().nullable(),
  total_transactions: z.number(),
  total_amount: money,
  currency: z.string(),
  converted_from: z.string().nullable(),
  cases_flagged: z.number(),
  cases_investigated: z.number(),
  cases_queued: z.number(),
  money_at_risk: money,
  money_at_risk_confirmed: money,
  by_anomaly_type: z.record(z.string(), z.object({ count: z.number(), amount_at_risk: money })),
  by_severity_band: count,
  by_status: count,
  by_verdict: count,
  by_verification_status: count,
  last_run_id: z.string().nullable(),
  last_run_at: z.string().nullable(),
}) satisfies z.ZodType<MetricsResponse>;

const detectorMetricsSchema = z.object({
  detector: z.string(),
  anomaly_type: z.string(),
  granularity: z.enum(["case", "row"]),
  precision: z.number(),
  recall: z.number(),
  f1: z.number(),
  pr_auc: z.number().nullable(),
  tp: z.number(),
  fp: z.number(),
  fn: z.number(),
}) satisfies z.ZodType<DetectorMetrics>;

const rate = z.number().nullable();

export const evaluationSchema = z.object({
  run_id: z.string().nullable(),
  seed: z.number(),
  dataset: z.string().nullable(),
  injected_anomaly_count: z.number().nullable(),
  detector_metrics: z.array(detectorMetricsSchema),
  baseline_metrics: z.array(detectorMetricsSchema),
  agent_metrics: z.object({
    notes: z.number(),
    citation_validity_deterministic: rate,
    citation_validity_semantic: rate,
    triage_accuracy: rate,
    avg_tool_calls: rate,
    avg_tokens: rate,
    avg_latency_seconds: rate,
    notes_regenerated: z.number(),
    notes_failed_after_retries: z.number(),
  }),
  ablations: z.array(
    z.object({
      ablation_name: z.string(),
      configuration: z.string(),
      citation_validity_deterministic: rate,
      citation_validity_semantic: rate,
      triage_accuracy: rate,
      note_quality_score: rate,
    }),
  ),
  generated_at: z.string().nullable(),
}) satisfies z.ZodType<EvaluationResponse>;

export const healthSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  duckdb: z.boolean(),
  case_store: z.boolean(),
  llm_configured: z.boolean(),
  llm_model: z.string().nullable(),
}) satisfies z.ZodType<HealthResponse>;
