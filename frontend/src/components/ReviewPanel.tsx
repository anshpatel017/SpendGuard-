// The human decision (FR-6.7). The only thing on this page that changes data, and
// only when the reviewer presses Save: choosing a status alone changes nothing.
import { useEffect, useState } from "react";

import { useUpdateStatus } from "../api/hooks";
import type { Case, CaseStatus } from "../api/types";
import { STATUS_LABEL, formatDateTime } from "../lib/format";
import { Card, ErrorBanner } from "./common";

const CHOICES: CaseStatus[] = ["under_review", "confirmed", "dismissed", "new"];

export function ReviewPanel({ c }: { c: Case }) {
  const [status, setStatus] = useState<CaseStatus>(c.status);
  const [note, setNote] = useState(c.reviewer_note ?? "");
  const save = useUpdateStatus(c.case_id);

  // A saved change refetches the case; start again from what the server holds.
  useEffect(() => {
    setStatus(c.status);
    setNote(c.reviewer_note ?? "");
  }, [c.status, c.reviewer_note]);

  const dirty = status !== c.status || note !== (c.reviewer_note ?? "");
  return (
    <Card title="Review">
      <div className="stack" style={{ gap: 10 }}>
        <div className="small">
          Current status: <strong>{STATUS_LABEL[c.status]}</strong>
          <span className="muted"> · updated {formatDateTime(c.updated_at)}</span>
        </div>
        <div className="row" role="radiogroup" aria-label="New status">
          {CHOICES.map((choice) => (
            <button key={choice} type="button" role="radio" aria-checked={status === choice}
              className={`btn ${status === choice ? "selected" : ""}`} onClick={() => setStatus(choice)}>
              {STATUS_LABEL[choice]}
            </button>
          ))}
        </div>
        <textarea aria-label="Reviewer note" placeholder="Reviewer note - what you checked and why you decided"
          value={note} maxLength={4000} onChange={(e) => setNote(e.target.value)} />
        <div className="row">
          <button type="button" className="btn primary" disabled={!dirty || save.isPending}
            onClick={() => save.mutate({ status, note: note.trim() ? note.trim() : null })}>
            {save.isPending ? "Saving…" : "Save decision"}
          </button>
          {save.isSuccess && !dirty && <span className="chip ok">Saved</span>}
        </div>
        {save.error && <ErrorBanner error={save.error} />}
        <div className="muted small">
          The agent's verdict is a recommendation. The case changes only when you save a decision here.
        </div>
      </div>
    </Card>
  );
}
