// Names for the generated API types. Never hand-edit schema.d.ts: it is produced
// from the backend's OpenAPI schema by `npm run gen:api` (API-CONTRACT section 4).
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Case = Schemas["Case"];
export type CaseSummary = Schemas["CaseSummary"];
export type CaseListResponse = Schemas["CaseListResponse"];
export type CaseDetailResponse = Schemas["CaseDetailResponse"];
export type AuditNote = Schemas["AuditNote"];
export type Citation = Schemas["Citation"];
export type TraceStep = Schemas["TraceStep"];
export type TransactionRow = Schemas["TransactionRow"];
export type MetricsResponse = Schemas["MetricsResponse"];
export type EvaluationResponse = Schemas["EvaluationResponse"];
export type DetectorMetrics = Schemas["DetectorMetrics"];
export type HealthResponse = Schemas["HealthResponse"];
export type StatusUpdateRequest = Schemas["StatusUpdateRequest"];
export type DemoInjectRequest = Schemas["DemoInjectRequest"];
export type DemoInjectResponse = Schemas["DemoInjectResponse"];

export type AnomalyType = Case["anomaly_type"];
export type CaseStatus = Case["status"];
export type SeverityBand = Case["severity_band"];
export type Verdict = AuditNote["verdict"];
export type VerificationStatus = AuditNote["verification_status"];
