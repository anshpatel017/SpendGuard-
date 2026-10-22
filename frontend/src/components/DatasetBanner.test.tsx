import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DatasetBanner } from "./DatasetBanner";

// The banner is the only thing on screen that says which data is being shown.
// Both branches matter for honesty: an evaluation run carries planted anomalies
// that must never read as real findings, and a converted dataset shows rupee
// figures that were not rupees at source (FR-6.10).
const metrics = vi.hoisted(() => ({ value: null as unknown }));

vi.mock("../api/hooks", () => ({
  useMetrics: () => ({ data: metrics.value }),
}));

afterEach(() => {
  cleanup();
  metrics.value = null;
});

describe("<DatasetBanner> (FR-6.10)", () => {
  it("marks a converted dataset as converted, and names the source currency", () => {
    metrics.value = { evaluation_seed: null, converted_from: "USD" };
    render(<DatasetBanner />);
    const note = screen.getByText(/converted to/i);
    expect(note.textContent).toContain("USD");
    expect(note.textContent).toContain("pinned rate");
  });

  it("says nothing about conversion when the amounts were never converted", () => {
    metrics.value = { evaluation_seed: null, converted_from: null };
    render(<DatasetBanner />);
    expect(screen.queryByText(/converted to/i)).toBeNull();
  });

  it("warns that an evaluation dataset is not a set of real findings", () => {
    metrics.value = { evaluation_seed: 42, converted_from: null };
    render(<DatasetBanner />);
    const note = screen.getByText(/planted anomalies/i);
    expect(note.textContent).toContain("42");
    expect(note.textContent).toContain("not real findings");
  });

  it("shows both banners when an evaluation run is also converted", () => {
    metrics.value = { evaluation_seed: 7, converted_from: "USD" };
    render(<DatasetBanner />);
    expect(screen.getByText(/planted anomalies/i)).toBeTruthy();
    expect(screen.getByText(/converted to/i)).toBeTruthy();
  });

  it("renders nothing at all before the metrics arrive", () => {
    metrics.value = null;
    const { container } = render(<DatasetBanner />);
    expect(container.textContent).toBe("");
  });
});
