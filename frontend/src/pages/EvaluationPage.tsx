// Detectors against the baseline, the agent's own numbers, and the ablations
// (FR-6.8). What has not been measured shows as a dash, never as zero.
import { useState } from "react";

import { useEvaluation } from "../api/hooks";
import type { DetectorMetrics } from "../api/types";
import { Card, ErrorBanner, Loading } from "../components/common";
import { ANOMALY_LABEL, formatCount, formatDateTime, formatPercent } from "../lib/format";

const SEEDS = [42, 7, 2026];
const TYPES = ["duplicate", "split", "inflation", "vendor_flag", "all"] as const;

function pick(rows: DetectorMetrics[], type: string): DetectorMetrics | undefined {
  return rows.find((m) => m.anomaly_type === type && m.granularity === "case");
}

function num(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(3);
}

export function EvaluationPage() {
  const [seed, setSeed] = useState(42);
  const evaluation = useEvaluation(seed);

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Evaluation</h1>
        <label className="check">
          Seed
          <select value={seed} onChange={(e) => setSeed(Number(e.target.value))}>
            {SEEDS.map((s) => (
              <option key={s} value={s}>
                {s}
                {s === 42 ? " (development)" : " (held out)"}
              </option>
            ))}
          </select>
        </label>
      </div>
      {evaluation.error && <ErrorBanner error={evaluation.error} />}
      {evaluation.isPending && <Loading what="evaluation" />}
      {evaluation.data && (() => {
        const e = evaluation.data;
        const a = e.agent_metrics;
        return (
          <>
            <Card
              title="Detectors against the rule baseline · per case"
              actions={
                <span className="muted small">
                  {e.injected_anomaly_count !== null ? `${formatCount(e.injected_anomaly_count)} planted anomalies` : "no run yet"}
                  {e.generated_at && ` · ${formatDateTime(e.generated_at)}`}
                </span>
              }
            >
              {e.detector_metrics.length === 0 ? (
                <div className="empty">No detector evaluation for seed {seed}. Run <code>spendguard evaluate --seed {seed}</code>.</div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Anomaly</th><th>Detector</th>
                        <th className="num">Baseline F1</th><th className="num">F1</th>
                        <th className="num">Precision</th><th className="num">Recall</th>
                        <th className="num">Baseline PR-AUC</th><th className="num">PR-AUC</th>
                      </tr>
                    </thead>
                    <tbody>
                      {TYPES.map((type) => {
                        const d = pick(e.detector_metrics, type);
                        const b = pick(e.baseline_metrics, type);
                        if (!d) return null;
                        const better = b ? d.f1 > b.f1 : true;
                        return (
                          <tr key={type}>
                            <td>{type === "all" ? <strong>All types</strong> : ANOMALY_LABEL[type]}</td>
                            <td><code>{d.detector}</code></td>
                            <td className="num">{num(b?.f1)}</td>
                            <td className="num"><strong style={{ color: better ? "var(--ok)" : "var(--warn)" }}>{num(d.f1)}</strong></td>
                            <td className="num">{num(d.precision)}</td>
                            <td className="num">{num(d.recall)}</td>
                            <td className="num">{num(b?.pr_auc)}</td>
                            <td className="num">{num(d.pr_auc)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <p className="muted small">
                    A detector below the baseline on F1 is shown as it is. Price inflation ties the baseline on F1 and
                    wins on ranking (PR-AUC): honest premium purchases share its price band, which is why cases are
                    investigated rather than trusted.
                  </p>
                </div>
              )}
            </Card>

            <div className="kpis">
              <div className="card kpi">
                <div className="label">Citations exist and match</div>
                <div className="value">{formatPercent(a.citation_validity_deterministic, 1)}</div>
                <div className="sub">Checked by rule, no model involved · the headline</div>
              </div>
              <div className="card kpi">
                <div className="label">Evidence supports claims</div>
                <div className="value">{formatPercent(a.citation_validity_semantic, 1)}</div>
                <div className="sub">Model-judged · reported separately</div>
              </div>
              <div className="card kpi">
                <div className="label">Triage accuracy</div>
                <div className="value">{formatPercent(a.triage_accuracy, 0)}</div>
                <div className="sub">Decisive verdicts against the answer key · {a.notes} note{a.notes === 1 ? "" : "s"}</div>
              </div>
              <div className="card kpi">
                <div className="label">Per investigation</div>
                <div className="value">{a.avg_tool_calls === null ? "—" : a.avg_tool_calls.toFixed(1)} tools</div>
                <div className="sub">
                  {a.avg_tokens === null ? "—" : formatCount(a.avg_tokens)} tokens ·{" "}
                  {a.avg_latency_seconds === null ? "—" : `${a.avg_latency_seconds.toFixed(0)} s`} of model time ·{" "}
                  {a.notes_regenerated} regenerated · {a.notes_failed_after_retries} failed checks
                </div>
              </div>
            </div>
            {a.notes > 0 && a.notes < 20 && (
              <div className="banner">
                Agent numbers rest on {a.notes} note{a.notes === 1 ? "" : "s"} so far - too few to read as a rate. The
                evaluation sample grows by about ten investigations a day on the free LLM tier.
              </div>
            )}

            <Card title="Ablations">
              {e.ablations.length === 0 ? (
                <div className="empty">No ablation runs yet. <code>spendguard investigate --no-verify</code> produces the Verifier-off arm.</div>
              ) : (
                <table>
                  <thead>
                    <tr><th>Ablation</th><th className="num">Citations valid</th><th className="num">Supported (model-judged)</th><th className="num">Triage</th></tr>
                  </thead>
                  <tbody>
                    {e.ablations.map((row) => (
                      <tr key={row.ablation_name}>
                        <td>{row.ablation_name}</td>
                        <td className="num">{formatPercent(row.citation_validity_deterministic, 1)}</td>
                        <td className="num">{formatPercent(row.citation_validity_semantic, 1)}</td>
                        <td className="num">{formatPercent(row.triage_accuracy, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </>
        );
      })()}
    </div>
  );
}
