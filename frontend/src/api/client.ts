// The one place the frontend talks to the backend. Every response is validated;
// every error arrives as an ApiError carrying the API's own code and message.
<<<<<<< HEAD
import type { z } from "zod";
=======
import { z } from "zod";
>>>>>>> 890422049cb83dd44defa08113fbdf6cc4b832d1

import type { CaseStatus, DemoInjectRequest, StatusUpdateRequest } from "./types";
import {
  caseDetailSchema,
  caseListSchema,
<<<<<<< HEAD
=======
  caseReviewItemSchema,
>>>>>>> 890422049cb83dd44defa08113fbdf6cc4b832d1
  caseSchema,
  demoSchema,
  evaluationSchema,
  healthSchema,
<<<<<<< HEAD
  metricsSchema,
=======
  investigationJobResponseSchema,
  investigationStatusSchema,
  metricsSchema,
  runSummarySchema,
  transactionListSchema,
>>>>>>> 890422049cb83dd44defa08113fbdf6cc4b832d1
  transactionSchema,
} from "./validate";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, schema: z.ZodType<T>, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "unreachable", "The SpendGuard API is not reachable. Is `spendguard serve` running?");
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = (body as { detail?: { code?: string; message?: string } } | null)?.detail;
    throw new ApiError(response.status, detail?.code ?? "http_error", detail?.message ?? response.statusText);
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    const where = issue ? `${issue.path.join(".")}: ${issue.message}` : "unknown field";
    throw new ApiError(response.status, "contract_mismatch", `The API's reply to ${path} broke the contract (${where}).`);
  }
  return parsed.data;
}

export interface CaseFilters {
  anomaly_type?: string;
<<<<<<< HEAD
  severity_band?: string;
=======
  detector?: string;
  severity_band?: string;
  severity?: string;
>>>>>>> 890422049cb83dd44defa08113fbdf6cc4b832d1
  status?: string;
  verdict?: string;
  verification_status?: string;
  investigated?: string;
  dismissed_by_agent?: string;
<<<<<<< HEAD
=======
  search?: string;
>>>>>>> 890422049cb83dd44defa08113fbdf6cc4b832d1
  sort?: string;
  order?: string;
  page?: number;
  page_size?: number;
}

function query(filters: CaseFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

<<<<<<< HEAD
=======
export interface TransactionFilters {
  search?: string;
  vendor?: string;
  min_amount?: number;
  max_amount?: number;
  page?: number;
  page_size?: number;
}

>>>>>>> 890422049cb83dd44defa08113fbdf6cc4b832d1
export const api = {
  metrics: () => request("/metrics", metricsSchema),
  cases: (filters: CaseFilters) => request(`/cases${query(filters)}`, caseListSchema),
  caseDetail: (caseId: string) => request(`/cases/${encodeURIComponent(caseId)}`, caseDetailSchema),
<<<<<<< HEAD
  updateStatus: (caseId: string, status: CaseStatus, reviewerNote: string | null) =>
    request(`/cases/${encodeURIComponent(caseId)}/status`, caseSchema, {
      method: "PATCH",
      body: JSON.stringify({ status, reviewer_note: reviewerNote } satisfies StatusUpdateRequest),
    }),
  transaction: (rowId: number) => request(`/transactions/${rowId}`, transactionSchema),
=======
  updateStatus: (
    caseId: string,
    status: CaseStatus,
    reviewerNote: string | null,
    reviewer: string = "Demo Reviewer",
  ) =>
    request(`/cases/${encodeURIComponent(caseId)}/status`, caseSchema, {
      method: "PATCH",
      body: JSON.stringify({
        status,
        reviewer_note: reviewerNote,
        reviewer,
      } satisfies StatusUpdateRequest),
    }),
  triggerInvestigation: (caseId: string) =>
    request(`/cases/${encodeURIComponent(caseId)}/investigate`, investigationJobResponseSchema, {
      method: "POST",
    }),
  investigationStatus: (caseId: string) =>
    request(`/cases/${encodeURIComponent(caseId)}/investigate`, investigationStatusSchema),
  caseReviews: (caseId: string) =>
    request(`/cases/${encodeURIComponent(caseId)}/reviews`, z.array(caseReviewItemSchema)),
  exportReportUrl: (caseId: string, format: "markdown" | "html" = "markdown") =>
    `${BASE}/cases/${encodeURIComponent(caseId)}/export?format=${format}`,
  transactions: (filters: TransactionFilters = {}) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
    }
    const q = params.toString() ? `?${params.toString()}` : "";
    return request(`/transactions${q}`, transactionListSchema);
  },
  transaction: (rowId: number) => request(`/transactions/${rowId}`, transactionSchema),
  runs: (limit: number = 50) => request(`/runs?limit=${limit}`, z.array(runSummarySchema)),
>>>>>>> 890422049cb83dd44defa08113fbdf6cc4b832d1
  evaluation: (seed: number) => request(`/evaluation?seed=${seed}`, evaluationSchema),
  health: () => request("/health", healthSchema),
  demoInject: (anomalyCount: number, seed: number | null) =>
    request("/demo/inject", demoSchema, {
      method: "POST",
      body: JSON.stringify({ anomaly_count: anomalyCount, seed } satisfies DemoInjectRequest),
    }),
<<<<<<< HEAD
=======
  demoReset: () =>
    request<{ status: string; message: string }>("/demo/reset?confirm=true", z.object({ status: z.string(), message: z.string() }), {
      method: "POST",
    }),
>>>>>>> 890422049cb83dd44defa08113fbdf6cc4b832d1
};
