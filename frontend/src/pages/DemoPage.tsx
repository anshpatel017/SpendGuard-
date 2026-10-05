import {
  CheckCircle2,
  FlaskConical,
  Info,
  Play,
  RefreshCw,
  RotateCcw,
  XCircle,
} from "lucide-react";
import { useState } from "react";

import { useDemoInject, useDemoReset } from "../api/hooks";
import { DetectorBadge } from "../components/common/Badge";
import { ErrorBanner } from "../components/common";
import { useToast } from "../context/ToastContext";
import { formatCount, formatDate, formatMoney } from "../lib/format";

export function DemoPage() {
  const [count, setCount] = useState(3);
  const { showToast } = useToast();
  const demo = useDemoInject();
  const resetMutation = useDemoReset();
  const run = demo.data;

  const handleRunDemo = () => {
    demo.mutate(
      { count, seed: null },
      {
        onSuccess: (data) => {
          showToast(`Completed sandbox run: caught ${data.caught} of ${data.results.length} anomalies`);
        },
        onError: (err) => {
          showToast(err instanceof Error ? err.message : "Sandbox injection failed", "error");
        },
      }
    );
  };

  const handleReset = () => {
    resetMutation.mutate(undefined, {
      onSuccess: () => {
        showToast("Sandbox state reset successfully");
      },
    });
  };

  return (
    <div className="space-y-6">
      {/* 1. Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-xl sm:text-2xl font-bold text-[#0F172A] tracking-tight flex items-center gap-2.5">
            <FlaskConical className="w-6 h-6 text-black" />
            <span>Interactive Anomaly Sandbox</span>
          </h2>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Plant synthetic anomalies into an isolated temporary database slice to test real-time detector recall.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleReset}
            disabled={resetMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50 transition-colors shadow-2xs cursor-pointer"
          >
            <RotateCcw className="w-3.5 h-3.5 text-slate-400" />
            <span>Reset Demo State</span>
          </button>
        </div>
      </div>

      {/* 2. Isolated Sandbox Protocol Banner */}
      <div className="p-4 rounded-xl border border-indigo-200 bg-indigo-50/70 text-xs text-indigo-950 flex items-start gap-3 shadow-2xs">
        <div className="p-1 rounded-md bg-indigo-100 text-indigo-700 shrink-0 mt-0.5">
          <Info className="w-4 h-4" />
        </div>
        <div className="space-y-0.5">
          <h4 className="font-bold text-xs">
            Throwaway Sandbox Isolation Protocol
          </h4>
          <p className="text-indigo-900 text-[11px] leading-relaxed">
            The last 3 months of the clean dataset are cloned into a temporary database table. Anomalies (duplicate records, split orders, inflated unit prices) are dynamically planted with a random seed. The detectors scan every row, report caught vs missed anomalies, and the temporary table is purged. Raw ledger records are NEVER modified.
          </p>
        </div>
      </div>

      {/* 3. Injection Configuration Card */}
      <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs p-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <h3 className="text-sm font-bold text-slate-900">
              Injection Parameters
            </h3>
            <p className="text-xs text-slate-500">
              Select how many anomalies to plant across the recent transaction window.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-xs">
              <label className="font-semibold text-slate-700">Anomalies to Plant:</label>
              <select
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
                disabled={demo.isPending}
                className="py-1.5 px-3 bg-white border border-slate-300 rounded-lg text-xs font-semibold text-slate-800 focus:outline-none focus:ring-1 focus:ring-cyan-600 cursor-pointer"
              >
                {[1, 2, 3, 4, 5, 6].map((n) => (
                  <option key={n} value={n}>
                    {n} Anomalies
                  </option>
                ))}
              </select>
            </div>

            <button
              type="button"
              disabled={demo.isPending}
              onClick={handleRunDemo}
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-white bg-black hover:bg-neutral-800 disabled:bg-slate-300 rounded-lg transition-all shadow-xs cursor-pointer"
            >
              {demo.isPending ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>Planting & Scanning...</span>
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>Run Live Sandbox</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {demo.error && <ErrorBanner error={demo.error} />}

      {/* 4. Scanning State */}
      {demo.isPending && (
        <div className="p-12 bg-white rounded-xl border border-slate-200 shadow-xs text-center">
          <div className="w-12 h-12 rounded-full bg-cyan-50 flex items-center justify-center text-[#0E7490] mx-auto mb-3 animate-spin">
            <RefreshCw className="w-6 h-6" />
          </div>
          <h4 className="text-base font-bold text-slate-900">
            Scanning Injected Ledger Slice...
          </h4>
          <p className="text-xs text-slate-500 max-w-md mx-auto mt-1 leading-relaxed">
            Copying recent ledger rows, executing mathematical MAD robust z-scores, temporal clustering, and matching token distance rules...
          </p>
        </div>
      )}

      {/* 5. Results Section */}
      {run && !demo.isPending && (
        <div className="space-y-4">
          {/* Summary Banner with Test ID */}
          <div
            className="p-4 rounded-xl border border-emerald-200 bg-emerald-50/70 text-xs text-emerald-950 flex flex-col sm:flex-row sm:items-center justify-between gap-2 shadow-2xs"
            data-testid="demo-summary"
          >
            <div>
              <span className="font-bold text-sm">
                Caught {run.caught} of {run.results.length} planted anomalies
              </span>
              <span className="text-slate-600 ml-2">
                in {run.elapsed_seconds.toFixed(2)} seconds across {formatCount(run.dataset_rows)} transactions
              </span>
              <div className="text-[11px] text-emerald-800 mt-0.5">
                Window: {formatDate(run.window_start)} to {formatDate(run.window_end)} · Random Seed: {run.seed}
              </div>
            </div>

            <span className="self-start sm:self-auto px-2.5 py-1 rounded bg-white border border-emerald-300 font-mono text-emerald-900 font-bold">
              {Math.round((run.caught / (run.results.length || 1)) * 100)}% Recall
            </span>
          </div>

          {/* Results Table */}
          <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-200 bg-slate-50/70 flex items-center justify-between">
              <span className="text-xs font-bold text-slate-800">
                Planted Anomaly Evaluation Results
              </span>
              <span className="text-[11px] text-slate-500">
                {run.other_cases} additional organic case{run.other_cases === 1 ? "" : "s"} flagged in background
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#E2E8F0] text-[11px] font-semibold text-slate-500 uppercase tracking-wider bg-slate-50">
                    <th className="py-3 px-4">Planted Pattern</th>
                    <th className="py-3 px-4 text-right">Injected Rows</th>
                    <th className="py-3 px-4 text-right">Amount At Risk</th>
                    <th className="py-3 px-4">Result Status</th>
                    <th className="py-3 px-4">Caught By Detector</th>
                    <th className="py-3 px-4 text-right">Detector Score</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-xs text-slate-700">
                  {run.results.map((r) => (
                    <tr key={r.injection_group_id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-3.5 px-4 font-semibold text-slate-900">
                        <DetectorBadge anomalyType={r.anomaly_type} />
                      </td>

                      <td className="py-3.5 px-4 text-right font-mono text-slate-700 whitespace-nowrap">
                        {r.injected_row_ids.length} rows
                      </td>

                      <td className="py-3.5 px-4 text-right font-mono font-bold text-slate-900 whitespace-nowrap">
                        {formatMoney(r.amount_at_risk)}
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap">
                        {r.detected ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded text-xs font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
                            <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                            <span>Caught</span>
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded text-xs font-semibold bg-red-50 text-red-700 border border-red-200">
                            <XCircle className="w-3 h-3 text-red-600" />
                            <span>Missed</span>
                          </span>
                        )}
                      </td>

                      <td className="py-3.5 px-4 font-mono text-xs whitespace-nowrap">
                        {r.detected_by ? (
                          <span className="font-semibold text-slate-800">{r.detected_by.toUpperCase()}</span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>

                      <td className="py-3.5 px-4 text-right font-mono text-slate-700 whitespace-nowrap">
                        {r.detector_score !== null ? r.detector_score.toFixed(2) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="p-4 bg-slate-50 border-t border-slate-200 text-xs text-slate-500">
              <p className="leading-relaxed">
                A miss is shown transparently as a miss. This mirrors the measured recall from formal benchmarks: subtle inflation markups near normal price deviation bounds are intentionally sent to human review queues rather than trigger false alarms.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* 6. Initial Empty State */}
      {!run && !demo.isPending && !demo.error && (
        <div className="p-12 bg-white rounded-xl border border-slate-200 shadow-xs text-center">
          <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mx-auto mb-3">
            <FlaskConical className="w-6 h-6" />
          </div>
          <h4 className="text-base font-bold text-slate-900">
            Ready to Run Live Sandbox
          </h4>
          <p className="text-xs text-slate-500 max-w-md mx-auto mt-1 leading-relaxed">
            Click &ldquo;Run Live Sandbox&rdquo; above to copy recent transactions into a throwaway slice, inject random anomalies, and test detector algorithms.
          </p>
        </div>
      )}
    </div>
  );
}
