// The audit note (FR-6.3, FR-6.5). Each claim shows the rows it cites; each
// citation shows whether it passed the Verifier's checks and, if not, why.
// Clicking a citation highlights the row in the evidence table below.
import type { AuditNote, Citation } from "../api/types";
import { VERDICT_LABEL, formatDateTime, formatPercent } from "../lib/format";
import { citationChecks } from "../lib/verification";
import { Card, VerificationBadge } from "./common";

function mark(state: boolean | null): string {
  return state === true ? "✓" : state === false ? "✗" : "–";
}

function CitationChip({ c, onInspect }: { c: Citation; onInspect: (rowId: number) => void }) {
  const checks = citationChecks(c);
  const tone = checks.passed === false ? "bad" : checks.passed === null ? "warn" : "";
  const title = [
    `row exists ${mark(checks.exists)}`,
    `values match ${mark(checks.values)}`,
    `supports the claim ${mark(checks.supported)} (model-judged)`,
    ...Object.entries(c.asserted).map(([k, v]) => `states ${k} = ${String(v)}`),
  ].join("\n");
  return (
    <button type="button" className={`cite ${tone}`} title={title} onClick={() => onInspect(c.row_id)}>
      #{c.row_id} {mark(checks.passed)}
    </button>
  );
}

export function NotePanel({ note, onInspect }: { note: AuditNote; onInspect: (rowId: number) => void }) {
  const claims = new Map<number, Citation[]>();
  for (const c of note.citations) claims.set(c.claim_index, [...(claims.get(c.claim_index) ?? []), c]);
  const checked = note.citations_checked ?? 0;

  return (
    <Card
      title="Audit note"
      actions={
        <div className="row">
          <span className={`chip ${note.verdict === "likely_false_positive" ? "none" : "outline"}`}>
            Agent recommends: {VERDICT_LABEL[note.verdict]}
          </span>
          <VerificationBadge status={note.verification_status} passed={note.citations_passed} checked={note.citations_checked} />
        </div>
      }
    >
      <p className="finding">{note.finding}</p>

      <ol className="claims">
        {[...claims.entries()].map(([index, citations]) => {
          const failures = citations.filter((c) => c.failure_reason);
          return (
            <li key={index} className={`claim ${failures.length ? "failed" : ""}`}>
              <div>{citations[0]?.claim_text}</div>
              <div className="cites">
                <span className="muted small">Cites</span>
                {citations.map((c) => (
                  <CitationChip key={c.citation_id} c={c} onInspect={onInspect} />
                ))}
              </div>
              {failures.map((c) => (
                <div key={c.citation_id} className="failure">
                  Row {c.row_id}: {c.failure_reason}
                </div>
              ))}
            </li>
          );
        })}
      </ol>

      {note.policy_clauses.length > 0 && (
        <div className="row" style={{ marginTop: 12 }}>
          <span className="muted small">Policy</span>
          {note.policy_clauses.map((clause) => (
            <span key={clause} className="chip outline mono">{clause}</span>
          ))}
        </div>
      )}

      <div className="recommendation">
        <strong>Recommended action.</strong> {note.recommended_action}
        <div className="muted small">The agent recommends; a person decides.</div>
      </div>

      <dl className="kv small" style={{ marginTop: 14 }}>
        <dt>Citations exist and match</dt>
        <dd>
          {note.deterministic_passed ?? "–"}/{checked || "–"} ({formatPercent(checked ? (note.deterministic_passed ?? 0) / checked : null)})
          · checked by rule, no model involved
        </dd>
        <dt>Evidence supports claims</dt>
        <dd>
          {note.semantic_passed === null
            ? "not checked"
            : `${note.semantic_passed}/${checked} (${formatPercent(checked ? note.semantic_passed / checked : null)})`}{" "}
          · model-judged
        </dd>
        <dt>Revisions</dt>
        <dd>{note.retry_count === 0 ? "none needed" : `${note.retry_count} after the Verifier objected`}</dd>
        <dt>Written by</dt>
        <dd>
          {note.model_name} · {formatDateTime(note.created_at)}
        </dd>
      </dl>
    </Card>
  );
}
