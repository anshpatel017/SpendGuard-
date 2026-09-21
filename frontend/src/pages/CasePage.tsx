// One case, everything needed to decide it: the verified note and its citations,
// the evidence rows, the agent's trace, and the review controls.
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useCaseDetail } from "../api/hooks";
import type { Case } from "../api/types";
import { Card, ErrorBanner, Loading, SeverityChip } from "../components/common";
import { EvidenceTable } from "../components/EvidenceTable";
import { NotePanel } from "../components/NotePanel";
import { ReviewPanel } from "../components/ReviewPanel";
import { TraceTimeline } from "../components/TraceTimeline";
import { ANOMALY_LABEL, STATUS_LABEL, formatMoney } from "../lib/format";

function Facts({ c }: { c: Case }) {
  const metadata = Object.entries(c.metadata).filter(([, v]) => typeof v !== "object" || v === null);
  return (
    <Card title="Why the detector flagged it">
      <dl className="kv small">
        <dt>Detector</dt>
        <dd>
          <code>{c.detector}</code> · score {c.detector_score.toFixed(2)}
        </dd>
        <dt>Rows</dt>
        <dd>{c.row_ids.length}</dd>
        {metadata.slice(0, 12).map(([key, value]) => (
          <div key={key} style={{ display: "contents" }}>
            <dt>{key.replaceAll("_", " ")}</dt>
            <dd className="mono">{typeof value === "number" ? Number(value.toFixed(4)) : String(value)}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

export function CasePage() {
  const { caseId = "" } = useParams();
  const detail = useCaseDetail(caseId);
  const [highlight, setHighlight] = useState<number | null>(null);

  if (detail.isPending) return <Loading what="case" />;
  if (detail.error) {
    const missing = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <div className="stack">
        <Link to="/">← Case queue</Link>
        {missing ? <div className="empty">No case with id {caseId}.</div> : <ErrorBanner error={detail.error} />}
      </div>
    );
  }

  const { case: c, audit_note: note } = detail.data;
  const inspect = (rowId: number) => {
    setHighlight(null);
    requestAnimationFrame(() => setHighlight(rowId)); // re-trigger the highlight on a repeat click
  };

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="stack" style={{ gap: 6 }}>
          <Link to="/" className="small">← Case queue</Link>
          <h1>
            {ANOMALY_LABEL[c.anomaly_type]} · {c.vendor_key ?? "unknown supplier"}
          </h1>
          <div className="row">
            <SeverityChip band={c.severity_band} value={c.severity_prelim} final={c.severity_final} />
            <span className="chip outline">{formatMoney(c.amount_at_risk)} at risk</span>
            <span className="chip outline">{STATUS_LABEL[c.status]}</span>
            {c.dismissed_by_agent && <span className="chip none">Agent recommends dismissal</span>}
            <span className="muted small mono">{c.case_id}</span>
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div className="stack">
          {note ? (
            <NotePanel note={note} onInspect={inspect} />
          ) : (
            <Card title="Audit note">
              <div className="empty">
                Not yet investigated. Detection flagged this case; investigation runs on the highest-severity cases
                first, and this one is still queued.
              </div>
            </Card>
          )}
          <EvidenceTable evidence={detail.data.evidence_rows} total={detail.data.evidence_total}
            context={detail.data.context_rows} highlight={highlight} />
        </div>
        <div className="stack">
          <ReviewPanel c={c} />
          <Facts c={c} />
        </div>
      </div>

      {note && <TraceTimeline trace={detail.data.trace} />}
    </div>
  );
}
