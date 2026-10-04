import { describe, expect, it } from "vitest";

import { missExplanation } from "./demo";

describe("the live demo's explanation of its own result (D-34)", () => {
  it("names what was actually missed, rather than assuming it was a price markup", () => {
    // The bug this pins: the sentence was fixed text about "small price markups"
    // whatever had been missed. On a run that caught the inflation and missed a
    // duplicate it contradicted the table printed directly above it.
    const text = missExplanation(["duplicate"]);
    expect(text).toContain("duplicate record");
    expect(text).not.toContain("price markup");
    expect(text).toContain("this is a case");
  });

  it("lists every missed type when more than one got away", () => {
    const text = missExplanation(["duplicate", "inflation"]);
    expect(text).toContain("duplicate record");
    expect(text).toContain("price inflation");
    expect(text).toContain("these are cases");
  });

  it("does not claim a miss when nothing was missed", () => {
    const text = missExplanation([]);
    expect(text).toContain("Everything planted was caught");
    expect(text).not.toContain("Missed here");
  });

  it("still refuses to promise a clean sweep next time", () => {
    // Showing misses as misses is the demo's whole credibility (DEMO.md), so a
    // lucky run must not read as a guarantee.
    expect(missExplanation([])).toContain("not guaranteed");
  });

  it("points at the measured recall instead of inventing a cause", () => {
    const text = missExplanation(["split"]);
    expect(text).toContain("measured recall");
    expect(text).toContain("Evaluation");
  });
});
