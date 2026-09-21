// Real responses from the API, captured from the seed-42 evaluation stores, must
// pass the runtime validators. Refresh the fixtures after a contract change.
import { describe, expect, it } from "vitest";

import caseInvestigated from "./fixtures/case-investigated.json";
import caseQueued from "./fixtures/case-queued.json";
import cases from "./fixtures/cases.json";
import evaluation from "./fixtures/evaluation.json";
import metrics from "./fixtures/metrics.json";
import { caseDetailSchema, caseListSchema, evaluationSchema, metricsSchema } from "./validate";

describe("the contract, on real responses", () => {
  it("accepts the metrics", () => {
    const m = metricsSchema.parse(metrics);
    expect(m.cases_flagged).toBe(m.cases_investigated + m.cases_queued);
  });

  it("accepts the case queue", () => {
    expect(caseListSchema.parse(cases).items.length).toBeGreaterThan(0);
  });

  it("accepts an investigated case with its note and trace", () => {
    const detail = caseDetailSchema.parse(caseInvestigated);
    expect(detail.audit_note).not.toBeNull();
    expect(detail.trace.length).toBeGreaterThan(0);
  });

  it("accepts a queued case, which has no note rather than an empty one", () => {
    const detail = caseDetailSchema.parse(caseQueued);
    expect(detail.audit_note).toBeNull();
    expect(detail.trace).toEqual([]);
  });

  it("accepts the evaluation", () => {
    expect(evaluationSchema.parse(evaluation).seed).toBe(42);
  });

  it("rejects money sent as a float", () => {
    const broken = { ...metrics, money_at_risk: 97698491.83 };
    expect(metricsSchema.safeParse(broken).success).toBe(false);
  });

  it("rejects a response with a field missing", () => {
    const { cases_queued: _dropped, ...broken } = metrics;
    expect(metricsSchema.safeParse(broken).success).toBe(false);
  });
});
