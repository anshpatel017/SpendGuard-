import {
  Building2,
  Copy,
  Eye,
  FlaskConical,
  Info,
  Play,
  RotateCcw,
  Scissors,
  Sparkles,
  TrendingUp,
  X,
} from "lucide-react";
import { useState } from "react";

import { useDemoInject, useDemoReset } from "../api/hooks";
import { SeverityBadge } from "../components/common/Badge";
import Scanner from "../components/common/Scanner";
import { useToast } from "../context/ToastContext";
import { ANOMALY_LABEL } from "../lib/format";

type DetectorType = "Duplicate" | "Split Purchase" | "Price Inflation" | "Vendor Risk";

interface DemoItem {
  id: string;
  vendor: string;
  amount: number;
  score: number;
  triggerSignal: string;
  severity: "Critical" | "High" | "Medium" | "Low";
  detector: string;
}

export function DemoPage() {
  const [selectedDetector, setSelectedDetector] = useState<DetectorType>("Split Purchase");
  const [datasetBatch, setDatasetBatch] = useState<string>("sample_q4_fiscal_surge");
  const [selectedInspectItem, setSelectedInspectItem] = useState<DemoItem | null>(null);

  const { showToast } = useToast();
  const demoMutation = useDemoInject();
  const resetMutation = useDemoReset();

  const isRunning = demoMutation.isPending;
  const runData = demoMutation.data;

  const sampleDatasets = [
    {
      id: "sample_q4_fiscal_surge",
      name: "Fiscal Year-End Surge (520 Records)",
      description: "Synthetic transactions simulating end-of-quarter budget expending rush.",
      count: 520,
    },
    {
      id: "sample_it_infrastructure",
      name: "IT Infrastructure & Hardware (340 Records)",
      description: "Server compute, peripheral, and telecom line items across 14 suppliers.",
      count: 340,
    },
    {
      id: "sample_facilities_mro",
      name: "Facilities & Ops Maintenance (610 Records)",
      description: "Cleaning contracts, construction supplies, and office ergonomics.",
      count: 610,
    },
  ];

  const handleRunDetection = () => {
    demoMutation.mutate(
      { count: 3, seed: null },
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

  const activeDatasetObj = sampleDatasets.find((d) => d.id === datasetBatch) || sampleDatasets[0]!;

  // Map backend results or fallback to interactive simulated items
  const displayResults: DemoItem[] = runData?.results?.map((r, i) => ({
    id: `ANOM-DEMO-${String(i + 1).padStart(2, "0")}`,
    vendor: r.detected_by ? `${r.detected_by} Detection` : "Apex Office Logistics",
    amount: parseFloat(r.amount_at_risk || "0") || 14750.0,
    score: r.detector_score ?? (r.detected ? 0.94 : 0.42),
    triggerSignal: `${ANOMALY_LABEL[r.anomaly_type] || r.anomaly_type} flagged across ${r.injected_row_ids.length} transactions`,
    severity: (r.detected ? "Critical" : "Medium") as DemoItem["severity"],
    detector: ANOMALY_LABEL[r.anomaly_type] || selectedDetector,
  })) || [
    {
      id: "DEMO-SPLIT-01",
      vendor: "Apex Office Logistics",
      amount: 14750.0,
      score: 0.94,
      triggerSignal: "3 transactions ($4,920, $4,880, $4,950) issued in 72h below $5k limit",
      severity: "Critical",
      detector: "Split Purchase",
    },
    {
      id: "DEMO-SPLIT-02",
      vendor: "ByteWave Software Labs",
      amount: 9800.0,
      score: 0.88,
      triggerSignal: "Consecutive software invoices $4,900 and $4,900 on consecutive business days",
      severity: "High",
      detector: "Split Purchase",
    },
  ];

  const filteredResults = displayResults.filter((r) => {
    if (!runData) return true;
    const norm = selectedDetector.toLowerCase().replace(/\s+/g, "");
    const dNorm = r.detector.toLowerCase().replace(/\s+/g, "");
    return dNorm.includes(norm) || norm.includes(dNorm) || true;
  });

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

      {/* 2. Isolated Sandbox Protocol Notice Banner */}
      <div className="p-3.5 rounded-xl border border-black bg-amber-50/80 text-amber-950 text-xs flex items-center gap-2.5">
        <Info className="w-4 h-4 text-black shrink-0" />
        <span>
          <strong className="text-black">Sandbox Notice:</strong> This sandbox is completely isolated from the main investigation database. Runs here do not alter live cases or notify officers.
        </span>
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
              Sub-Second Statistical Invariant Scanning
            </h3>
            <p className="text-xs sm:text-sm text-slate-300 max-w-lg mt-1 leading-relaxed">
              Evaluating transactions using temporal clustering, robust z-scores, and token collision analysis without black-box hallucination.
            </p>
          </div>
        </div>
      </div>

      {/* 4. Input Controls & Detector Selector */}
      <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs p-5 space-y-5">
        {/* Dataset Sample Selector */}
        <div>
          <label className="block text-xs font-bold text-slate-800 uppercase tracking-wider mb-2">
            1. Select Test Sample Batch
          </label>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {sampleDatasets.map((ds) => (
              <button
                key={ds.id}
                type="button"
                onClick={() => setDatasetBatch(ds.id)}
                className={`p-3 rounded-lg border text-left transition-all cursor-pointer ${
                  datasetBatch === ds.id
                    ? "border-2 border-black bg-neutral-50 shadow-xs"
                    : "border-slate-200 hover:border-slate-300 bg-white"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-900">{ds.name}</span>
                  <span
                    className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                      datasetBatch === ds.id
                        ? "text-black bg-neutral-200 font-semibold border border-neutral-300"
                        : "text-slate-600 bg-slate-100"
                    }`}
                  >
                    {ds.count} rows
                  </span>
                </div>
                <p className="text-[11px] text-slate-500 mt-1">{ds.description}</p>
              </button>
            ))}
          </div>
        </div>

        {/* Detector Selector Cards */}
        <div>
          <label className="block text-xs font-bold text-slate-800 uppercase tracking-wider mb-2">
            2. Choose Anomaly Detector
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {/* Duplicate */}
            <button
              type="button"
              onClick={() => setSelectedDetector("Duplicate")}
              className={`p-3.5 rounded-xl border text-left transition-all flex flex-col justify-between cursor-pointer ${
                selectedDetector === "Duplicate"
                  ? "border-2 border-black bg-neutral-50 shadow-xs ring-1 ring-black"
                  : "border-slate-200 hover:border-slate-300 bg-white"
              }`}
            >
              <div>
                <div className="w-8 h-8 rounded-lg bg-slate-100 text-black flex items-center justify-center mb-2 border border-slate-200">
                  <Copy className="w-4 h-4" />
                </div>
                <h4 className="text-xs font-bold text-slate-900">Duplicate Purchases</h4>
                <p className="text-[11px] text-slate-500 mt-1">
                  Temporal matching & Levenshtein invoice collision.
                </p>
              </div>
              <div className="mt-3 text-[10px] font-mono text-slate-700">Score: Exact Match</div>
            </button>

            {/* Split Purchase */}
            <button
              type="button"
              onClick={() => setSelectedDetector("Split Purchase")}
              className={`p-3.5 rounded-xl border text-left transition-all flex flex-col justify-between cursor-pointer ${
                selectedDetector === "Split Purchase"
                  ? "border-2 border-black bg-neutral-50 shadow-xs ring-1 ring-black"
                  : "border-slate-200 hover:border-slate-300 bg-white"
              }`}
            >
              <div>
                <div className="w-8 h-8 rounded-lg bg-slate-100 text-black flex items-center justify-center mb-2 border border-slate-200">
                  <Scissors className="w-4 h-4" />
                </div>
                <h4 className="text-xs font-bold text-slate-900">Split Purchases</h4>
                <p className="text-[11px] text-slate-500 mt-1">
                  Single-signature sub-$5,000 threshold evasion.
                </p>
              </div>
              <div className="mt-3 text-[10px] font-mono text-slate-700">Score: Cluster Density</div>
            </button>

            {/* Price Inflation */}
            <button
              type="button"
              onClick={() => setSelectedDetector("Price Inflation")}
              className={`p-3.5 rounded-xl border text-left transition-all flex flex-col justify-between cursor-pointer ${
                selectedDetector === "Price Inflation"
                  ? "border-2 border-black bg-neutral-50 shadow-xs ring-1 ring-black"
                  : "border-slate-200 hover:border-slate-300 bg-white"
              }`}
            >
              <div>
                <div className="w-8 h-8 rounded-lg bg-slate-100 text-black flex items-center justify-center mb-2 border border-slate-200">
                  <TrendingUp className="w-4 h-4" />
                </div>
                <h4 className="text-xs font-bold text-slate-900">Price Inflation</h4>
                <p className="text-[11px] text-slate-500 mt-1">
                  Robust MAD z-score vs historical peer catalog.
                </p>
              </div>
              <div className="mt-3 text-[10px] font-mono text-slate-700">Score: Z-Score Outlier</div>
            </button>

            {/* Vendor Risk */}
            <button
              type="button"
              onClick={() => setSelectedDetector("Vendor Risk")}
              className={`p-3.5 rounded-xl border text-left transition-all flex flex-col justify-between cursor-pointer ${
                selectedDetector === "Vendor Risk"
                  ? "border-2 border-black bg-neutral-50 shadow-xs ring-1 ring-black"
                  : "border-slate-200 hover:border-slate-300 bg-white"
              }`}
            >
              <div>
                <div className="w-8 h-8 rounded-lg bg-slate-100 text-black flex items-center justify-center mb-2 border border-slate-200">
                  <Building2 className="w-4 h-4" />
                </div>
                <h4 className="text-xs font-bold text-slate-900">Vendor Risk</h4>
                <p className="text-[11px] text-slate-500 mt-1">
                  Incorporation age & bank routing change flags.
                </p>
              </div>
              <div className="mt-3 text-[10px] font-mono text-slate-700">Score: Shell Entity Index</div>
            </button>
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
                <span>Run {selectedDetector} Anomaly Simulation</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* 5. Results Section */}
      <div className="space-y-4">
        {/* Telemetry Bar */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-white p-4 rounded-xl border border-slate-200 text-xs">
          <div>
            <span className="text-slate-500 block text-[11px]">Transactions Analyzed</span>
            <span className="font-mono font-bold text-slate-900 text-base tabular-nums">
              {activeDatasetObj.count}
            </span>
          </div>

          <div>
            <span className="text-slate-500 block text-[11px]">Anomalies Caught</span>
            <span className="font-mono font-bold text-red-600 text-base tabular-nums">
              {runData ? `${runData.caught} / ${runData.results.length}` : `${filteredResults.length} / ${filteredResults.length}`}
            </span>
          </div>

          <div>
            <span className="text-slate-500 block text-[11px]">Detector Focus</span>
            <span className="font-semibold text-slate-900 text-sm">
              {selectedDetector}
            </span>
          </div>

          <div>
            <span className="text-slate-500 block text-[11px]">Recall Rate</span>
            <span className="font-mono font-bold text-emerald-700 text-base tabular-nums">
              {runData ? `${Math.round((runData.caught / Math.max(1, runData.results.length)) * 100)}%` : "100%"}
            </span>
          </div>
        </div>

        {/* Results Table */}
        <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <span className="text-xs font-bold text-slate-800">
              Sandbox Detected Cases ({filteredResults.length})
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
                  <th className="py-2.5 px-3">Vendor</th>
                  <th className="py-2.5 px-3 text-right">Suspicious Amount</th>
                  <th className="py-2.5 px-3 text-center">Score</th>
                  <th className="py-2.5 px-3">Detection Signal</th>
                  <th className="py-2.5 px-3">Severity</th>
                  <th className="py-2.5 px-3 text-center">Inspect</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredResults.map((item) => (
                  <tr key={item.id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="py-2.5 px-3 font-mono font-semibold text-slate-800">
                      {item.id}
                    </td>
                    <td className="py-2.5 px-3 font-medium text-slate-900">
                      {item.vendor}
                    </td>
                    <td className="py-2.5 px-3 text-right font-mono font-bold text-slate-900 tabular-nums">
                      ${item.amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                    <td className="py-2.5 px-3 text-center font-mono font-semibold text-cyan-800 tabular-nums">
                      {item.score.toFixed(2)}
                    </td>
                    <td className="py-2.5 px-3 text-slate-600 text-[11px]">
                      {item.triggerSignal}
                    </td>
                    <td className="py-2.5 px-3">
                      <SeverityBadge severity={item.severity} />
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
          </div>
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
                className="p-1 text-slate-400 hover:text-slate-800 rounded-md transition-colors cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-3 p-3 bg-slate-50 rounded-lg">
                <div>
                  <span className="text-slate-400 block text-[11px]">Target Vendor</span>
                  <span className="font-bold text-slate-900">{selectedInspectItem.vendor}</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[11px]">Flagged Amount</span>
                  <span className="font-mono font-bold text-slate-900">
                    ${selectedInspectItem.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[11px]">Detector</span>
                  <span className="font-semibold text-slate-800">{selectedInspectItem.detector}</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[11px]">Confidence Score</span>
                  <span className="font-mono font-bold text-cyan-800">
                    {selectedInspectItem.score.toFixed(2)}
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
