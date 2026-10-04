// The human decision (FR-6.7). The only thing on this page that changes data, and
// only when the reviewer presses Save: choosing a status alone changes nothing.
import { useEffect, useState } from "react";

import { useUpdateStatus } from "../api/hooks";
import type { Case, CaseReviewItem, CaseStatus } from "../api/types";
import { STATUS_LABEL, formatDateTime } from "../lib/format";
import { Card, ErrorBanner } from "./common";

const CHOICES: CaseStatus[] = ["under_review", "confirmed", "dismissed", "new"];

const VALID_NEXT: Record<CaseStatus, CaseStatus[]> = {
  new: ["under_review", "confirmed", "dismissed"],
  under_review: ["confirmed", "dismissed"],
  confirmed: ["under_review"],
  dismissed: ["under_review"],
};

export function ReviewPanel({ c, reviews = [] }: { c: Case; reviews?: CaseReviewItem[] }) {
  const [status, setStatus] = useState<CaseStatus>(c.status);
  const [note, setNote] = useState(c.reviewer_note ?? "");
  const [reviewer, setReviewer] = useState("Demo Reviewer");
  const save = useUpdateStatus(c.case_id);

  // A saved change refetches the case; start again from what the server holds.
  useEffect(() => {
    setStatus(c.status);
    setNote(c.reviewer_note ?? "");
  }, [c.status, c.reviewer_note]);

  const allowed = VALID_NEXT[c.status] ?? [];
  const dirty = status !== c.status || note !== (c.reviewer_note ?? "");

  return (
    <Card title="Human Review & Decision">
      <div className="stack" style={{ gap: 10 }}>
        <div className="small">
          Current status: <strong>{STATUS_LABEL[c.status]}</strong>
          <span className="muted"> · updated {formatDateTime(c.updated_at)}</span>
        </div>

        <div className="row" role="radiogroup" aria-label="New status">
          {CHOICES.map((choice) => {
            const isCurrent = choice === c.status;
            const isPermitted = isCurrent || allowed.includes(choice);
            return (
              <button
                key={choice}
                type="button"
                role="radio"
                aria-checked={status === choice}
                disabled={!isPermitted}
                title={!isPermitted ? `Cannot transition directly from ${STATUS_LABEL[c.status]} to ${STATUS_LABEL[choice]}. Move to Under Review first.` : undefined}
                className={`btn ${status === choice ? "selected" : ""} ${!isPermitted ? "disabled" : ""}`}
                onClick={() => setStatus(choice)}
              >
                {STATUS_LABEL[choice]}
              </button>
            );
          })}
        </div>

        {(c.status === "confirmed" || c.status === "dismissed") && (
          <div className="muted small" style={{ color: "var(--color-warn, #b45309)" }}>
            To modify a finalized decision ({STATUS_LABEL[c.status]}), return the case to <strong>Under Review</strong> first.
          </div>
        )}

        <div className="row" style={{ alignItems: "center", gap: 8 }}>
          <label htmlFor="reviewer-name-input" className="small muted">Reviewer Identity:</label>
          <input
            id="reviewer-name-input"
            type="text"
            className="input small"
            style={{ maxWidth: 200, padding: "4px 8px", fontSize: "0.85rem", border: "1px solid var(--border)", borderRadius: 4 }}
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            placeholder="Demo Reviewer"
          />
        </div>

        <textarea
          aria-label="Reviewer note"
          placeholder="Reviewer note - what you checked and why you decided"
          value={note}
          maxLength={4000}
          onChange={(e) => setNote(e.target.value)}
        />

        <div className="row">
          <button
            type="button"
            className="btn primary"
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate({ status, note: note.trim(), reviewer: reviewer.trim() || "Demo Reviewer" })}
          >
            {save.isPending ? "Saving…" : "Save decision"}
          </button>
          {save.isSuccess && !dirty && <span className="chip ok">Saved</span>}
        </div>
        {save.error && <ErrorBanner error={save.error} />}

        <div className="muted small">
          The AI's verdict is a recommendation. The case changes only when a human reviewer saves a decision here.
        </div>

        {reviews.length > 0 && (
          <div className="stack" style={{ marginTop: 12, borderTop: "1px solid var(--border, #e2e8f0)", paddingTop: 10, gap: 6 }}>
            <div className="small" style={{ fontWeight: 600 }}>Review History ({reviews.length})</div>
            <div className="stack" style={{ gap: 6, maxHeight: 180, overflowY: "auto" }}>
              {reviews.map((r) => (
                <div
                  key={r.id}
                  className="small"
                  style={{
                    backgroundColor: "rgba(0,0,0,0.02)",
                    padding: "6px 8px",
                    borderRadius: 4,
                    border: "1px solid var(--border, #e2e8f0)",
                  }}
                >
                  <div className="row" style={{ justifyContent: "space-between", marginBottom: 2 }}>
                    <span>
                      <strong>{r.reviewer}</strong>: {STATUS_LABEL[r.previous_status as CaseStatus] ?? r.previous_status} → <strong>{STATUS_LABEL[r.new_status as CaseStatus] ?? r.new_status}</strong>
                    </span>
                    <span className="muted" style={{ fontSize: "0.75rem" }}>{formatDateTime(r.created_at)}</span>
                  </div>
                  {r.note && <div className="muted" style={{ fontStyle: "italic" }}>"{r.note}"</div>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
