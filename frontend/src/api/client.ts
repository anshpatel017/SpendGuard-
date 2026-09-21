// The one place the frontend talks to the backend. Every response is validated;
// every error arrives as an ApiError carrying the API's own code and message.
import type { z } from "zod";

import type { CaseStatus, DemoInjectRequest, StatusUpdateRequest } from "./types";
import {
  caseDetailSchema,
  caseListSchema,
  caseSchema,
  demoSchema,
  evaluationSchema,
  healthSchema,
  metricsSchema,
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
  severity_band?: string;
  status?: string;
  verdict?: string;
  verification_status?: string;
  investigated?: string;
  dismissed_by_agent?: string;
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

export const api = {
  metrics: () => request("/metrics", metricsSchema),
  cases: (filters: CaseFilters) => request(`/cases${query(filters)}`, caseListSchema),
  caseDetail: (caseId: string) => request(`/cases/${encodeURIComponent(caseId)}`, caseDetailSchema),
  updateStatus: (caseId: string, status: CaseStatus, reviewerNote: string | null) =>
    request(`/cases/${encodeURIComponent(caseId)}/status`, caseSchema, {
      method: "PATCH",
      body: JSON.stringify({ status, reviewer_note: reviewerNote } satisfies StatusUpdateRequest),
    }),
  transaction: (rowId: number) => request(`/transactions/${rowId}`, transactionSchema),
  evaluation: (seed: number) => request(`/evaluation?seed=${seed}`, evaluationSchema),
  health: () => request("/health", healthSchema),
  demoInject: (anomalyCount: number, seed: number | null) =>
    request("/demo/inject", demoSchema, {
      method: "POST",
      body: JSON.stringify({ anomaly_count: anomalyCount, seed } satisfies DemoInjectRequest),
    }),
};
