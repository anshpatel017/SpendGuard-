import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup } from "@testing-library/react";

import { VerificationBadge } from "./common";

afterEach(cleanup);

describe("<VerificationBadge> (FR-6.9)", () => {
  it("renders a verified note as verified, with its counts", () => {
    render(<VerificationBadge status="verified" passed={8} checked={8} />);
    expect(screen.getByTestId("verification-badge").textContent).toBe("✓ Verified · 8/8 citations");
  });

  it("does not render an unverified note as verified, even with every citation passing", () => {
    render(<VerificationBadge status="unverified" passed={8} checked={8} />);
    const badge = screen.getByTestId("verification-badge");
    expect(badge.textContent).not.toContain("Verified");
    expect(badge.className).toContain("warn");
  });

  it("renders failed checks as a failure", () => {
    render(<VerificationBadge status="failed_after_retries" passed={3} checked={5} />);
    expect(screen.getByTestId("verification-badge").className).toContain("bad");
  });
});
