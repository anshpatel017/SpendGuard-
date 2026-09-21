// Small building blocks shared by every page.
import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import type { SeverityBand, VerificationStatus } from "../api/types";
import { BAND_LABEL } from "../lib/format";
import { verificationBadge } from "../lib/verification";

export function SeverityChip({ band, value, final }: { band: SeverityBand; value: number; final?: number | null }) {
  const moved = final !== null && final !== undefined && final !== value;
  return (
    <span className={`chip ${band}`} title={moved ? `Preliminary ${value.toFixed(1)}, after investigation ${final.toFixed(1)}` : undefined}>
      {BAND_LABEL[band]} {moved ? `${value.toFixed(0)} → ${final.toFixed(0)}` : value.toFixed(0)}
    </span>
  );
}

export function VerificationBadge({
  status,
  passed,
  checked,
}: {
  status: VerificationStatus | null | undefined;
  passed: number | null | undefined;
  checked: number | null | undefined;
}) {
  const badge = verificationBadge(status, passed, checked);
  return (
    <span className={`chip badge ${badge.tone}`} title={badge.explanation} data-testid="verification-badge">
      {badge.tone === "ok" ? "✓ " : badge.tone === "bad" ? "✗ " : badge.tone === "warn" ? "! " : ""}
      {badge.label}
    </span>
  );
}

export function Loading({ what }: { what: string }) {
  return <div className="empty">Loading {what}…</div>;
}

export function ErrorBanner({ error }: { error: unknown }) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : "Something went wrong.";
  return (
    <div className="banner error" role="alert">
      {message}
    </div>
  );
}

export function Card({ title, actions, children }: { title?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}
