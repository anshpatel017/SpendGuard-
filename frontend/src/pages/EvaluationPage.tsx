import {
  Info,
  Sparkles,
} from "lucide-react";
import { useMemo, useState } from "react";

import { useEvaluation } from "../api/hooks";
import type { DetectorMetrics } from "../api/types";
import { ErrorBanner, Loading } from "../components/common";
import {
  ANOMALY_LABEL,
  formatCount,
  formatDateTime,
  formatPercent,
} from "../lib/format";

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

  const e = evaluation.data;
  const a = e?.agent_metrics;

  // Macro metrics computed from detector_metrics
  const macroStats = useMemo(() => {
    if (!e || e.detector_metrics.length === 0) return null;
    const cases = e.detector_metrics.filter((m) => m.granularity === "case" && m.anomaly_type !== "all");
    if (cases.length === 0) return null;

    const avgP = cases.reduce((acc, m) => acc + (m.precision ?? 0), 0) / cases.length;
    const avgR = cases.reduce((acc, m) => acc + (m.recall ?? 0), 0) / cases.length;
    const avgF = cases.reduce((acc, m) => acc + (m.f1 ?? 0), 0) / cases.length;
    const avgA = cases.reduce((acc, m) => acc + (m.pr_auc ?? 0), 0) / cases.length;

    return { avgP, avgR, avgF, avgA };
  }, [e]);

  return (
    <div className="space-y-6">
      {/* 1. Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl sm:text-2xl font-bold text-[#0F172A] tracking-tight">
            Detection & Investigation Evaluation
          </h2>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Evaluate deterministic anomaly detectors and autonomous agent verification against ground-truth benchmarks.
          </p>
        </div>

        {/* Seed Selector */}
        <div className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-lg border border-slate-300 shadow-2xs text-xs">
          <span className="font-semibold text-slate-600">Benchmark Seed:</span>
          <select
            value={seed}
            onChange={(evt) => setSeed(Number(evt.target.value))}
            className="bg-transparent font-mono font-semibold text-slate-900 focus:outline-none cursor-pointer"
          >
            {SEEDS.map((s) => (
              <option key={s} value={s}>
                Seed {s} {s === 42 ? "(Development Benchmark)" : "(Held-out Test)"}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* 2. Context Note Banner */}
      <div className="p-4 rounded-xl border border-cyan-200 bg-cyan-50/70 text-xs text-cyan-950 flex items-start gap-3 shadow-2xs">
        <div className="p-1 rounded-md bg-cyan-100 text-[#0E7490] shrink-0 mt-0.5">
          <Info className="w-4 h-4" />
        </div>
        <div className="space-y-0.5">
          <h4 className="font-bold text-xs">
            Evaluation Against Ground Truth
          </h4>
          <p className="text-cyan-900 text-[11px] leading-relaxed">
            Detectors are evaluated on reproducibility, precision, and recall against planted anomalies with mathematically verified labels.
            Agent verification citations are tested deterministically without model hallucination.
          </p>
        </div>
      </div>

      {evaluation.isPending && (
        <div className="p-8">
          <Loading what="evaluation metrics" />
        </div>
      )}
      {evaluation.error && <ErrorBanner error={evaluation.error} />}

      {e && (
        <>
          {/* 3. Macro KPI Cards */}
          {macroStats && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
                <span className="text-xs font-medium text-slate-500">Macro Precision</span>
                <div className="mt-2 text-2xl font-bold text-slate-900 font-mono tabular-nums">
                  {formatPercent(macroStats.avgP, 1)}
                </div>
                <span className="text-[11px] text-slate-400 mt-1 block">Low false positive rate</span>
              </div>

              <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
                <span className="text-xs font-medium text-slate-500">Macro Recall</span>
                <div className="mt-2 text-2xl font-bold text-slate-900 font-mono tabular-nums">
                  {formatPercent(macroStats.avgR, 1)}
                </div>
                <span className="text-[11px] text-slate-400 mt-1 block">Anomalies caught</span>
              </div>

              <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
                <span className="text-xs font-medium text-slate-500">Mean F1 Score</span>
                <div className="mt-2 text-2xl font-bold text-black font-mono tabular-nums">
                  {formatPercent(macroStats.avgF, 1)}
                </div>
                <span className="text-[11px] text-slate-400 mt-1 block">Balanced harmonic mean</span>
              </div>

              <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
                <span className="text-xs font-medium text-slate-500">Mean PR-AUC</span>
                <div className="mt-2 text-2xl font-bold text-slate-900 font-mono tabular-nums">
                  {macroStats.avgA.toFixed(3)}
                </div>
                <span className="text-[11px] text-slate-400 mt-1 block">Ranking performance</span>
              </div>
            </div>
          )}

          {/* 4. Detector Benchmark Table */}
          <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-200 bg-slate-50/70 flex items-center justify-between">
              <div>
                <span className="text-xs font-bold text-slate-800">
                  Detector Suite vs Statistical Baseline
                </span>
                <span className="text-[11px] text-slate-400 ml-2">
                  {e.injected_anomaly_count !== null ? `${formatCount(e.injected_anomaly_count)} planted anomalies` : "No run yet"}
                  {e.generated_at && ` · ${formatDateTime(e.generated_at)}`}
                </span>
              </div>
              <span className="text-[11px] font-mono text-slate-500">Granularity: Case-Level</span>
            </div>

            {e.detector_metrics.length === 0 ? (
              <div className="p-8 text-center text-slate-500 text-xs">
                No detector evaluation metrics recorded for seed {seed}.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-[#E2E8F0] text-[11px] font-semibold text-slate-500 uppercase tracking-wider bg-slate-50">
                      <th className="py-3 px-4">Anomaly Class</th>
                      <th className="py-3 px-4">Detector ID</th>
                      <th className="py-3 px-4 text-right">Baseline F1</th>
                      <th className="py-3 px-4 text-right">Model F1</th>
                      <th className="py-3 px-4 text-right">Precision</th>
                      <th className="py-3 px-4 text-right">Recall</th>
                      <th className="py-3 px-4 text-right">Baseline PR-AUC</th>
                      <th className="py-3 px-4 text-right">Model PR-AUC</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs text-slate-700">
                    {TYPES.map((type) => {
                      const d = pick(e.detector_metrics, type);
                      const b = pick(e.baseline_metrics, type);
                      if (!d) return null;
                      const better = b ? d.f1 >= b.f1 : true;

                      return (
                        <tr key={type} className="hover:bg-slate-50/80 transition-colors">
                          <td className="py-3.5 px-4 font-semibold text-slate-900">
                            {type === "all" ? "All Types (Macro)" : ANOMALY_LABEL[type]}
                          </td>
                          <td className="py-3.5 px-4 font-mono text-slate-600 text-[11px]">
                            <code>{d.detector}</code>
                          </td>
                          <td className="py-3.5 px-4 text-right font-mono text-slate-500 tabular-nums">
                            {num(b?.f1)}
                          </td>
                          <td className="py-3.5 px-4 text-right font-mono font-bold tabular-nums">
                            <span className={better ? "text-emerald-700" : "text-amber-700"}>
                              {num(d.f1)}
                            </span>
                          </td>
                          <td className="py-3.5 px-4 text-right font-mono text-slate-800 tabular-nums">
                            {num(d.precision)}
                          </td>
                          <td className="py-3.5 px-4 text-right font-mono text-slate-800 tabular-nums">
                            {num(d.recall)}
                          </td>
                          <td className="py-3.5 px-4 text-right font-mono text-slate-500 tabular-nums">
                            {num(b?.pr_auc)}
                          </td>
                          <td className="py-3.5 px-4 text-right font-mono font-semibold text-slate-900 tabular-nums">
                            {num(d.pr_auc)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* 5. Agent Verification Telemetry KPIs */}
          {a && (
            <div>
              <h3 className="text-sm font-bold text-slate-900 mb-3 flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-cyan-700" />
                <span>AI Agent Verification Quality Metrics</span>
              </h3>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
                  <span className="text-xs font-medium text-slate-500">Deterministic Citation Validity</span>
                  <div className="mt-2 text-2xl font-bold text-emerald-700 font-mono tabular-nums">
                    {formatPercent(a.citation_validity_deterministic, 1)}
                  </div>
                  <span className="text-[11px] text-slate-400 mt-1 block">
                    Verified mathematically against row ledger
                  </span>
                </div>

                <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
                  <span className="text-xs font-medium text-slate-500">Semantic Evidence Support</span>
                  <div className="mt-2 text-2xl font-bold text-indigo-700 font-mono tabular-nums">
                    {formatPercent(a.citation_validity_semantic, 1)}
                  </div>
                  <span className="text-[11px] text-slate-400 mt-1 block">
                    Independent model claim check
                  </span>
                </div>

                <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
                  <span className="text-xs font-medium text-slate-500">Triage Decision Accuracy</span>
                  <div className="mt-2 text-2xl font-bold text-slate-900 font-mono tabular-nums">
                    {formatPercent(a.triage_accuracy, 0)}
                  </div>
                  <span className="text-[11px] text-slate-400 mt-1 block">
                    Against answer key ({a.notes} notes tested)
                  </span>
                </div>

                <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
                  <span className="text-xs font-medium text-slate-500">Tool Calls & Latency</span>
                  <div className="mt-2 text-2xl font-bold text-slate-900 font-mono tabular-nums">
                    {a.avg_tool_calls === null ? "—" : `${a.avg_tool_calls.toFixed(1)} tools`}
                  </div>
                  <span className="text-[11px] text-slate-400 mt-1 block truncate">
                    {a.avg_latency_seconds ? `${a.avg_latency_seconds.toFixed(0)}s latency` : "Fast runtime"} · {a.notes_regenerated} retried
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* 6. Ablation Experiments */}
          <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-200 bg-slate-50/70 flex items-center justify-between">
              <span className="text-xs font-bold text-slate-800">
                Ablation Studies & Architecture Variations
              </span>
              <span className="text-[11px] text-slate-400">Comparing verifier-off vs template models</span>
            </div>

            {e.ablations.length === 0 ? (
              <div className="p-6 text-center text-slate-500 text-xs">
                No ablation runs recorded for seed {seed}.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-[#E2E8F0] text-[11px] font-semibold text-slate-500 uppercase tracking-wider bg-slate-50">
                      <th className="py-3 px-4">Ablation Variant</th>
                      <th className="py-3 px-4">Configuration Description</th>
                      <th className="py-3 px-4 text-right">Citations Valid</th>
                      <th className="py-3 px-4 text-right">Semantic Support</th>
                      <th className="py-3 px-4 text-right">Triage Accuracy</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-xs text-slate-700">
                    {e.ablations.map((row) => (
                      <tr key={row.ablation_name} className="hover:bg-slate-50/80 transition-colors">
                        <td className="py-3.5 px-4 font-semibold text-slate-900">{row.ablation_name}</td>
                        <td className="py-3.5 px-4 text-slate-500 text-[11px] max-w-sm">{row.configuration}</td>
                        <td className="py-3.5 px-4 text-right font-mono font-medium tabular-nums">
                          {formatPercent(row.citation_validity_deterministic, 1)}
                        </td>
                        <td className="py-3.5 px-4 text-right font-mono tabular-nums">
                          {formatPercent(row.citation_validity_semantic, 1)}
                        </td>
                        <td className="py-3.5 px-4 text-right font-mono font-bold text-slate-900 tabular-nums">
                          {formatPercent(row.triage_accuracy, 0)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
