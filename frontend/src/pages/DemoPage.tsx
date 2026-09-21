// The live demo (FR-5.10): plant anomalies nobody has seen in a throwaway copy
// of the last few months, run the detectors, show what was caught. Misses are
// shown as misses - they match the recall the evaluation reports.
import { useState } from "react";

import { useDemoInject } from "../api/hooks";
import { Card, ErrorBanner } from "../components/common";
import { ANOMALY_LABEL, formatCount, formatDate, formatMoney } from "../lib/format";

export function DemoPage() {
  const [count, setCount] = useState(3);
  const demo = useDemoInject();
  const run = demo.data;

  return (
    <div className="stack">
      <h1>Live demo</h1>
      <Card
        title="Plant anomalies, watch them get caught"
        actions={
          <div className="row">
            <label className="check">
              Anomalies
              <select value={count} onChange={(e) => setCount(Number(e.target.value))} disabled={demo.isPending}>
                {[1, 2, 3, 4, 5, 6].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn primary" disabled={demo.isPending}
              onClick={() => demo.mutate({ count, seed: null })}>
              {demo.isPending ? "Planting and detecting…" : "Run live demo"}
            </button>
          </div>
        }
      >
        <p className="muted small" style={{ marginTop: 0 }}>
          The last three months of the clean dataset are copied into a temporary database. Duplicate records,
          split purchases and inflated prices are planted in the copy with a fresh random seed, the detectors
          scan every row, and the copy is deleted. The data this dashboard shows is never touched.
        </p>
        {demo.error && <ErrorBanner error={demo.error} />}
        {!run && !demo.isPending && !demo.error && <div className="empty">Press “Run live demo”. It takes a few seconds.</div>}
        {demo.isPending && <div className="empty">Copying recent months, planting anomalies, scanning every row…</div>}
        {run && !demo.isPending && (
          <div className="stack" style={{ gap: 12 }}>
            <div className="coverage" data-testid="demo-summary">
              Caught <strong>{run.caught}</strong> of <strong>{run.results.length}</strong> planted anomalies in{" "}
              <strong>{run.elapsed_seconds.toFixed(1)} s</strong>, scanning {formatCount(run.dataset_rows)} transactions
              ({formatDate(run.window_start)} to {formatDate(run.window_end)}), seed {run.seed}.
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Planted</th><th className="num">Rows</th><th className="num">Value planted</th>
                    <th>Result</th><th>Caught by</th><th className="num">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {run.results.map((r) => (
                    <tr key={r.injection_group_id}>
                      <td>{ANOMALY_LABEL[r.anomaly_type]}</td>
                      <td className="num">{r.injected_row_ids.length}</td>
                      <td className="num">{formatMoney(r.amount_at_risk)}</td>
                      <td>{r.detected ? <span className="chip ok">✓ Caught</span> : <span className="chip bad">✗ Missed</span>}</td>
                      <td>{r.detected_by ? <code>{r.detected_by.toUpperCase()}</code> : "—"}</td>
                      <td className="num">{r.detector_score === null ? "—" : r.detector_score.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted small">
              A miss is shown as a miss. It is what the measured recall predicts: small price markups are the
              hardest to separate from honest premium purchases. The detectors also raised {run.other_cases} case
              {run.other_cases === 1 ? "" : "s"} on the copy's real rows, flags the demo does not count either way.
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}
