import { describe, expect, it } from "vitest";

import type { Citation } from "../api/types";
import { citationChecks, verificationBadge } from "./verification";

describe("verification badge (FR-6.9)", () => {
  it("says verified only for a verified note, with its counts", () => {
    expect(verificationBadge("verified", 8, 8)).toMatchObject({ label: "Verified · 8/8 citations", tone: "ok" });
  });

  it("never says verified when the status is not verified, even if every citation passed", () => {
    for (const status of ["unverified", "failed_after_retries", null] as const) {
      const badge = verificationBadge(status, 8, 8);
      expect(badge.label).not.toMatch(/^Verified/);
      expect(badge.tone).not.toBe("ok");
    }
  });

  it("marks failed checks as bad and unfinished checks as a warning", () => {
    expect(verificationBadge("failed_after_retries", 3, 5).tone).toBe("bad");
    expect(verificationBadge("unverified", null, null)).toMatchObject({ label: "Unverified", tone: "warn" });
    expect(verificationBadge(null, null, null).label).toBe("Not investigated");
  });
});

describe("citation checks", () => {
  const base: Citation = {
    citation_id: "c1",
    claim_index: 0,
    claim_text: "Both rows are for Rs 87,450.",
    row_id: 1,
    asserted: {},
    row_exists: true,
    values_match: true,
    supports_claim: true,
    failure_reason: null,
  };

  it("passes only when all three checks passed", () => {
    expect(citationChecks(base).passed).toBe(true);
    expect(citationChecks({ ...base, values_match: false }).passed).toBe(false);
  });

  it("treats a check that did not run as unknown, not as a pass", () => {
    expect(citationChecks({ ...base, supports_claim: null }).passed).toBeNull();
  });
});
