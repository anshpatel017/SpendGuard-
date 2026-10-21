import {
  Eye,
  FlaskConical,
  Info,
  Play,
  RotateCcw,
  Sparkles,
  X,
} from "lucide-react";
import { useState } from "react";

import { useDemoInject, useDemoReset } from "../api/hooks";
import Scanner from "../components/common/Scanner";
import { useToast } from "../context/ToastContext";
import { missExplanation } from "../lib/demo";
import { ANOMALY_LABEL, formatCount, formatMoney } from "../lib/format";

interface DemoItem {
  id: string;
  caught: boolean;
  detectedBy: string | null;
  amount: string | null;
  score: number | null;
  triggerSignal: string;
  detector: string;
}

export function DemoPage() {
  const [count, setCount] = useState(3);
  const [selectedInspectItem, setSelectedInspectItem] = useState<DemoItem | null>(null);

  const { showToast } = useToast();
  const demoMutation = useDemoInject();
  const resetMutation = useDemoReset();

  const isRunning = demoMutation.isPending;
  const runData = demoMutation.data;
  // Named rather than assumed: the explanation must describe the miss that
  // happened, not a fixed one. A sentence that contradicts the table above it
  // is the worst place for this to sit (D-34).
  const missed = (runData?.results ?? [])
    .filter((r) => !r.detected)
    .map((r) => r.anomaly_type);

  const handleRunDetection = () => {
    demoMutation.mutate(
      { count, seed: null },
      {
        onSuccess: (data) => {
          showToast(`Completed sandbox run: caught ${data.caught} of ${data.results.length} anomalies`, "info");
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
        setSelectedInspectItem(null);
      },
    });
  };

  // Every field here comes from the run. An earlier version substituted a
  // vendor name, an amount and a score whenever the real ones were null, and
  // rendered two invented cases when there was no run at all - fabricated
  // detector output on the page the walkthrough demonstrates live (D-34).
  const displayResults: DemoItem[] = (runData?.results ?? []).map((r, i) => ({
    id: `ANOM-DEMO-${String(i + 1).padStart(2, "0")}`,
    caught: r.detected,
    detectedBy: r.detected_by,
    amount: r.amount_at_risk ?? null,
    score: r.detector_score,
    triggerSignal: `${ANOMALY_LABEL[r.anomaly_type] || r.anomaly_type} planted across ${r.injected_row_ids.length} row${r.injected_row_ids.length === 1 ? "" : "s"}`,
    detector: ANOMALY_LABEL[r.anomaly_type] || r.anomaly_type,
  }));

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
            <RotateCcw className="w-3.5 h-3.5 text-slate-500" />
            <span>Reset Demo State</span>
          </button>
        </div>
      </div>

      {/* 2. Isolated Sandbox Protocol Notice Banner */}
      <div className="p-4 rounded-xl border border-black bg-neutral-50 flex items-start gap-3 text-xs leading-relaxed shadow-2xs">
        <Info className="w-4 h-4 text-black shrink-0 mt-0.5" />
        <div>
          <strong className="font-semibold block text-black">
            Isolated Sandbox Protocol
          </strong>
          <span className="text-slate-600">
            Anomalies are planted into a temporary copy of the data, never the served
            dataset, and the copy is dropped when the run ends. A test hashes the
            served data before and after a run and fails if a single byte moved.
          </span>
        </div>
      </div>

      {/* 3. High-Tech Scanning Radar Visual Banner */}
      <div className="relative rounded-2xl overflow-hidden border border-slate-200 bg-black text-white shadow-md">
        <div className="h-44 sm:h-52 w-full relative">
          <Scanner
            color1="#000000"
            color2="#38BDF8"
            color3="#818CF8"
            speed={0.6}
            sweepSpeed={0.3}
            bandDensity={14}
            glow={0.35}
            scale={1.3}
            opacity={0.85}
          />
          <div className="absolute inset-0 bg-gradient-to-r from-black/90 via-black/50 to-transparent flex flex-col justify-center px-6 sm:px-10 z-10 pointer-events-none">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-cyan-950/80 border border-cyan-500/30 text-cyan-300 text-[11px] font-semibold tracking-wide uppercase w-fit mb-2">
              <Sparkles className="w-3 h-3 text-cyan-400" />
              <span>Real-Time Anomaly Radar</span>
            </div>
            <h3 className="text-xl sm:text-2xl font-black text-white tracking-tight">
              Deterministic Statistical Scanning
            </h3>
            <p className="text-xs sm:text-sm text-slate-300 max-w-lg mt-1 leading-relaxed">
              Every row of the copy is scanned by the same four detectors that run in
              production: Fellegi-Sunter record linkage, minimal split runs, robust
              z-scores against category medians, and peer tests combined by Fisher.
            </p>
          </div>
        </div>
      </div>

      {/* 4. Input Controls & Detector Selector */}
      <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs p-5 space-y-5">
        {/* The one parameter POST /demo/inject takes. A dataset batch and a
            detector used to sit here; the endpoint accepts neither, and the
            three batches on offer were not real datasets. */}
        <div>
          <label
            htmlFor="demo-count"
            className="block text-xs font-bold text-slate-800 uppercase tracking-wider mb-2"
          >
            Anomalies to plant
          </label>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <input
              id="demo-count"
              type="number"
              min={1}
              max={10}
              value={count}
              onChange={(e) =>
                setCount(Math.max(1, Math.min(10, Number(e.target.value) || 1)))
              }
              className="w-20 px-3 py-2 text-sm font-mono rounded-lg border border-slate-200 bg-slate-50 text-slate-800 focus:outline-none focus:ring-1 focus:ring-cyan-600 focus:bg-white"
            />
            <p className="text-[11px] text-slate-500 leading-relaxed flex-1 min-w-0">
              Duplicates, split runs and price inflation are planted into a temporary copy
              of the last three months of the clean dataset. Vendor flags are excluded:
              they need months of a supplier&apos;s history. All four detectors then scan
              every row of the copy, which is dropped afterwards.
            </p>
          </div>
        </div>

        {/* Action Button */}
        <div className="pt-2 flex items-center gap-3">
          <button
            onClick={handleRunDetection}
            disabled={isRunning}
            className="px-5 py-2.5 text-xs font-bold text-white bg-black hover:bg-neutral-800 disabled:bg-slate-300 rounded-lg transition-all shadow-xs flex items-center gap-2 cursor-pointer"
          >
            {isRunning ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/60 border-t-white rounded-full animate-spin" />
                <span>Injecting & Analyzing Sandbox Batch...</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Plant {count} anomal{count === 1 ? "y" : "ies"} and run detection</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* 5. Results Section */}
      <div className="space-y-4">
        {/* Telemetry Bar */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-white p-4 rounded-xl border border-slate-200 text-xs [&>*]:min-w-0">
          <div>
            <span className="text-slate-500 block text-[11px]">Transactions Analyzed</span>
            <span className="font-mono font-bold text-slate-900 text-base tabular-nums">
              {runData ? formatCount(runData.dataset_rows) : "—"}
            </span>
          </div>

          <div>
            <span className="text-slate-500 block text-[11px]">Anomalies Caught</span>
            <span className="font-mono font-bold text-red-600 text-base tabular-nums">
              {runData ? `${runData.caught} / ${runData.results.length}` : "—"}
            </span>
          </div>

          <div>
            <span className="text-slate-500 block text-[11px]">Scan time</span>
            <span className="font-mono font-bold text-slate-900 text-base tabular-nums">
              {runData ? `${runData.elapsed_seconds.toFixed(1)}s` : "—"}
            </span>
          </div>

          <div>
            <span className="text-slate-500 block text-[11px]">Caught this run</span>
            <span className="font-mono font-bold text-emerald-700 text-base tabular-nums">
              {runData && runData.results.length > 0
                ? `${Math.round((runData.caught / runData.results.length) * 100)}%`
                : "—"}
            </span>
          </div>
        </div>

        {/* Results Table */}
        <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <span className="text-xs font-bold text-slate-800">
              Sandbox Detected Cases ({displayResults.length})
            </span>
            <span className="text-[11px] text-slate-500 font-mono">
              Live anomaly detection verified
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-[#E2E8F0] text-[11px] font-semibold text-slate-500 uppercase tracking-wider bg-slate-50">
                  <th className="py-2.5 px-3">Sandbox ID</th>
                  <th className="py-2.5 px-3">Detected by</th>
                  <th className="py-2.5 px-3 text-right">Suspicious Amount</th>
                  <th className="py-2.5 px-3 text-center">Score</th>
                  <th className="py-2.5 px-3">Detection Signal</th>
                  <th className="py-2.5 px-3">Result</th>
                  <th className="py-2.5 px-3 text-center">Inspect</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {displayResults.map((item) => (
                  <tr key={item.id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="py-2.5 px-3 font-mono font-semibold text-slate-800">
                      {item.id}
                    </td>
                    <td className="py-2.5 px-3 font-mono font-medium text-slate-900 uppercase">
                      {item.detectedBy ?? <span className="text-slate-500">&mdash;</span>}
                    </td>
                    <td className="py-2.5 px-3 text-right font-mono font-bold text-slate-900 tabular-nums">
                      {formatMoney(item.amount)}
                    </td>
                    <td className="py-2.5 px-3 text-center font-mono font-semibold text-cyan-800 tabular-nums">
                      {item.score === null ? (
                        <span className="text-slate-500">&mdash;</span>
                      ) : (
                        item.score.toFixed(2)
                      )}
                    </td>
                    <td className="py-2.5 px-3 text-slate-600 text-[11px]">
                      {item.triggerSignal}
                    </td>
                    <td className="py-2.5 px-3">
                      {item.caught ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
                          Caught
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold bg-red-50 text-red-700 border border-red-200">
                          Missed
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 px-3 text-center">
                      <button
                        onClick={() => setSelectedInspectItem(item)}
                        className="p-1 rounded text-slate-500 hover:text-black hover:bg-slate-100 transition-colors cursor-pointer"
                        title="Inspect transaction anomaly"
                      >
                        <Eye className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {displayResults.length === 0 && (
              <p className="px-4 py-8 text-center text-xs text-slate-500">
                No run yet. Inject anomalies to see what the detectors catch and
                what they miss.
              </p>
            )}
          </div>

          {runData && (
            <div className="p-4 bg-slate-50 border-t border-slate-200 text-xs text-slate-500">
              <p className="leading-relaxed" data-testid="demo-explanation">
                {missExplanation(missed)}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* 6. Inspection Modal Drawer */}
      {selectedInspectItem && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-200 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <div className="flex items-center gap-2">
                <FlaskConical className="w-4 h-4 text-black" />
                <h3 className="text-sm font-bold text-slate-900">
                  Sandbox Anomaly Inspection: {selectedInspectItem.id}
                </h3>
              </div>
              <button
                onClick={() => setSelectedInspectItem(null)}
                className="p-1 text-slate-500 hover:text-slate-800 rounded-md transition-colors cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-3 p-3 bg-slate-50 rounded-lg">
                <div>
                  <span className="text-slate-500 block text-[11px]">Detected by</span>
                  <span className="font-bold text-slate-900 uppercase">
                    {selectedInspectItem.detectedBy ?? "not detected"}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[11px]">Flagged Amount</span>
                  <span className="font-mono font-bold text-slate-900">
                    {formatMoney(selectedInspectItem.amount)}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[11px]">Detector</span>
                  <span className="font-semibold text-slate-800">{selectedInspectItem.detector}</span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[11px]">Confidence Score</span>
                  <span className="font-mono font-bold text-cyan-800">
                    {selectedInspectItem.score === null
                      ? "—"
                      : selectedInspectItem.score.toFixed(2)}
                  </span>
                </div>
              </div>

              <div>
                <span className="text-slate-500 font-semibold block mb-1">Signal Justification:</span>
                <p className="p-3 rounded-lg bg-amber-50/70 border border-amber-200/80 text-amber-950 font-mono text-[11px] leading-relaxed">
                  {selectedInspectItem.triggerSignal}
                </p>
              </div>
            </div>

            <div className="pt-2 flex justify-end">
              <button
                onClick={() => setSelectedInspectItem(null)}
                className="px-4 py-2 text-xs font-semibold text-white bg-black hover:bg-neutral-800 rounded-lg transition-colors cursor-pointer"
              >
                Close Inspector
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
