// What the verification badge says. FR-6.9: the dashboard never presents an
// unverified note as verified - so "Verified" depends on the status alone, never
// on counts that happen to look complete. A note whose citations all passed the
// mechanical check but whose semantic check never ran is *unverified*, and says so.
import type { Citation, VerificationStatus } from "../api/types";

export type Tone = "ok" | "warn" | "bad" | "none";

export interface Badge {
  label: string;
  tone: Tone;
  explanation: string;
}

export function verificationBadge(
  status: VerificationStatus | null | undefined,
  passed: number | null | undefined,
  checked: number | null | undefined,
): Badge {
  const counted = checked !== null && checked !== undefined && checked > 0;
  const ratio = counted ? `${passed ?? 0}/${checked} citations` : null;
  switch (status) {
    case "verified":
      return {
        label: ratio ? `Verified · ${ratio}` : "Verified",
        tone: "ok",
        explanation: "Every citation exists, every stated value matches its row, and the evidence supports each claim.",
      };
    case "failed_after_retries":
      return {
        label: ratio ? `Failed checks · ${ratio} passed` : "Failed checks",
        tone: "bad",
        explanation: "Problems remained after the agent's revisions. Read the failures before relying on this note.",
      };
    case "unverified":
      return {
        label: ratio ? `Unverified · ${ratio} passed` : "Unverified",
        tone: "warn",
        explanation: "The checks did not all run, so this note has not been verified.",
      };
    default:
      return { label: "Not investigated", tone: "none", explanation: "No audit note yet." };
  }
}

export type CheckState = boolean | null;

export interface CitationChecks {
  exists: CheckState;
  values: CheckState;
  supported: CheckState;
  passed: CheckState;
}

/** A citation's three checks. `null` means the check did not run - shown as such, never as a pass. */
export function citationChecks(c: Citation): CitationChecks {
  const all = [c.row_exists, c.values_match, c.supports_claim];
  const passed = all.includes(false) ? false : all.includes(null) ? null : true;
  return { exists: c.row_exists, values: c.values_match, supported: c.supports_claim, passed };
}
