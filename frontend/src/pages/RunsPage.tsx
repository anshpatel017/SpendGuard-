// Pipeline runs history and status page (P2).
import { useState } from "react";

import { useDemoReset, useRuns } from "../api/hooks";
import { Card, ErrorBanner, Loading } from "../components/common";
import { formatDateTime } from "../lib/format";

export function RunsPage() {
  const query = useRuns(100);
  const resetMutation = useDemoReset();
  const [resetConfirm, setResetConfirm] = useState(false);

  const runs = query.data ?? [];

  const handleReset = () => {
    resetMutation.mutate(undefined, {
      onSuccess: () => {
        setResetConfirm(false);
      },
    });
  };

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1>Pipeline Runs & History</h1>
          <div className="muted small">
            Operational log of all batch ingestion, deterministic detection, AI investigation, and evaluation runs.
          </div>
        </div>

        <div className="row" style={{ gap: 8 }}>
          {!resetConfirm ? (
            <button
              type="button"
              className="btn small"
              onClick={() => setResetConfirm(true)}
              title="Reset temporary demo data without touching raw datasets"
            >
              Reset Demo State
            </button>
          ) : (
            <div className="row" style={{ gap: 6, alignItems: "center" }}>
              <span className="small muted">Confirm reset?</span>
              <button
                type="button"
                className="btn primary small"
                disabled={resetMutation.isPending}
                onClick={handleReset}
              >
                {resetMutation.isPending ? "Resetting…" : "Yes, Reset Demo"}
              </button>
              <button
                type="button"
                className="btn small"
                onClick={() => setResetConfirm(false)}
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>

      {resetMutation.isSuccess && (
        <div className="chip ok" style={{ padding: "8px 12px", width: "fit-content" }}>
          Demo state reset successfully. Operational datasets and source CSVs were preserved.
        </div>
      )}

      {query.isPending && <Loading what="pipeline runs" />}
      {query.error && <ErrorBanner error={query.error} />}

      {runs.length > 0 && (
        <Card title={`Recorded Runs (${runs.length})`}>
          <div style={{ overflowX: "auto" }}>
            <table className="table" style={{ width: "100%", fontSize: "0.875rem" }}>
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th>Finished</th>
                  <th>Duration</th>
                  <th>Summary</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const start = new Date(r.started_at);
                  const end = r.finished_at ? new Date(r.finished_at) : null;
                  const durationSec = end ? Math.max(0, Math.round((end.getTime() - start.getTime()) / 1000)) : null;

                  return (
                    <tr key={r.run_id}>
                      <td className="mono small bold">{r.run_id}</td>
                      <td>
                        <span className="chip outline" style={{ textTransform: "capitalize" }}>
                          {r.kind}
                        </span>
                        {r.seed !== null && r.seed !== undefined && (
                          <span className="muted small mono" style={{ marginLeft: 6 }}>
                            seed={r.seed}
                          </span>
                        )}
                      </td>
                      <td>
                        <span
                          className={`chip ${
                            r.status === "completed" ? "ok" : r.status === "failed" ? "bad" : "warn"
                          }`}
                        >
                          {r.status}
                        </span>
                      </td>
                      <td className="small">{formatDateTime(r.started_at)}</td>
                      <td className="small">{r.finished_at ? formatDateTime(r.finished_at) : "—"}</td>
                      <td className="small mono">{durationSec !== null ? `${durationSec}s` : "in progress"}</td>
                      <td className="small">
                        {Object.entries(r.summary).length > 0 ? (
                          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                            {Object.entries(r.summary).map(([k, v]) => (
                              <span key={k} className="chip none small">
                                {k}: <strong>{String(v)}</strong>
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {runs.length === 0 && !query.isPending && (
        <Card>
          <div className="empty">
            No pipeline runs recorded in SQLite operational store yet. Run `spendguard ingest` or `spendguard detect` to record runs.
          </div>
        </Card>
      )}
    </div>
  );
}
