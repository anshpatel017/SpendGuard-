import {
  Activity,
  BarChart3,
  CheckCircle2,
  ChevronRight,
  Clock,
  Database,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  Terminal,
  X,
  XCircle,
} from "lucide-react";
import { useState } from "react";

import { useDemoReset, useRuns } from "../api/hooks";
import type { RunSummary } from "../api/types";
import { ErrorBanner, Loading } from "../components/common";
import { useToast } from "../context/ToastContext";
import { formatDateTime } from "../lib/format";

export function RunsPage() {
  const query = useRuns(100);
  const resetMutation = useDemoReset();
  const { showToast } = useToast();

  const [resetConfirm, setResetConfirm] = useState(false);
  const [selectedRun, setSelectedRun] = useState<RunSummary | null>(null);
  const [typeFilter, setTypeFilter] = useState("All");

  const RUN_TYPES = ["All", "detect", "investigate", "ingest", "evaluate"];

  const runs = query.data ?? [];

  const handleReset = () => {
    resetMutation.mutate(undefined, {
      onSuccess: () => {
        setResetConfirm(false);
        showToast("Demo state reset successfully", "success");
      },
      onError: (err) => {
        showToast(err instanceof Error ? err.message : "Failed to reset demo state", "error");
      },
    });
  };

  const filteredRuns = runs.filter((r) => {
    if (typeFilter !== "All" && r.kind.toLowerCase() !== typeFilter.toLowerCase()) {
      return false;
    }
    return true;
  });

  const getRunIcon = (kind: string) => {
    const norm = kind.toLowerCase();
    if (norm.includes("detect")) {
      return <Search className="w-3.5 h-3.5 text-[#0E7490]" />;
    }
    if (norm.includes("investig")) {
      return <Sparkles className="w-3.5 h-3.5 text-indigo-600" />;
    }
    if (norm.includes("ingest")) {
      return <Database className="w-3.5 h-3.5 text-cyan-600" />;
    }
    if (norm.includes("eval")) {
      return <BarChart3 className="w-3.5 h-3.5 text-emerald-600" />;
    }
    return <Activity className="w-3.5 h-3.5 text-slate-600" />;
  };

  return (
    <div className="space-y-6">
      {/* 1. Header & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-xl sm:text-2xl font-bold text-[#0F172A] tracking-tight">
            Runs & Pipeline Operations
          </h2>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Operational telemetry and execution audit trail for batch detection, ingestion, and evaluation.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {!resetConfirm ? (
            <button
              onClick={() => setResetConfirm(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50 transition-colors shadow-2xs cursor-pointer"
              title="Reset temporary demo data without modifying raw records"
            >
              <RotateCcw className="w-3.5 h-3.5 text-slate-400" />
              <span>Reset Demo State</span>
            </button>
          ) : (
            <div className="flex items-center gap-2 bg-amber-50 p-1.5 rounded-lg border border-amber-200 text-xs">
              <span className="text-amber-900 font-semibold px-1">Confirm reset?</span>
              <button
                disabled={resetMutation.isPending}
                onClick={handleReset}
                className="px-2.5 py-1 text-xs font-semibold text-white bg-red-600 hover:bg-red-700 rounded transition-colors shadow-xs cursor-pointer"
              >
                {resetMutation.isPending ? "Resetting…" : "Yes, Reset"}
              </button>
              <button
                onClick={() => setResetConfirm(false)}
                className="px-2 py-1 text-xs font-medium text-slate-600 hover:text-slate-900 cursor-pointer"
              >
                Cancel
              </button>
            </div>
          )}

          <button
            onClick={() => query.refetch()}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50 transition-colors shadow-2xs cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-slate-500 ${query.isFetching ? "animate-spin" : ""}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* 2. Run Status Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
          <span className="text-xs font-medium text-slate-500">Pipeline Status</span>
          <div className="mt-2 flex items-center gap-2">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
            </span>
            <span className="text-sm font-bold text-slate-900">Operational</span>
          </div>
          <span className="text-[11px] text-slate-400 mt-1 block">Daemon & scheduler active</span>
        </div>

        <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
          <span className="text-xs font-medium text-slate-500">Recorded Runs</span>
          <div className="mt-2 text-2xl font-bold text-slate-900 font-mono tabular-nums">
            {runs.length}
          </div>
          <span className="text-[11px] text-slate-400 mt-1 block">Telemetry retention window</span>
        </div>

        <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
          <span className="text-xs font-medium text-slate-500">Active Pipeline Types</span>
          <div className="mt-2 text-2xl font-bold text-slate-900 font-mono tabular-nums">
            4 Types
          </div>
          <span className="text-[11px] text-slate-400 mt-1 block">Detection, Ingestion, Eval, AI</span>
        </div>

        <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
          <span className="text-xs font-medium text-slate-500">Fastest Engine</span>
          <div className="mt-2 text-2xl font-bold text-emerald-700 font-mono tabular-nums">
            DuckDB OLAP
          </div>
          <span className="text-[11px] text-slate-400 mt-1 block">Sub-100ms vectorized execution</span>
        </div>
      </div>

      {/* 3. Filter Tabs */}
      <div className="flex items-center gap-1.5 p-1 bg-slate-100 rounded-lg w-fit text-xs font-medium">
        {RUN_TYPES.map((t) => (
          <button
            key={t}
            onClick={() => setTypeFilter(t)}
            className={`px-3 py-1.5 rounded-md capitalize transition-colors cursor-pointer ${
              typeFilter.toLowerCase() === t.toLowerCase()
                ? "bg-white text-slate-900 font-semibold shadow-2xs"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {query.isPending && (
        <div className="p-8">
          <Loading what="pipeline runs" />
        </div>
      )}
      {query.error && <ErrorBanner error={query.error} />}

      {/* 4. Runs Table */}
      <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200 bg-slate-50/70 flex items-center justify-between">
          <div className="text-xs font-semibold text-slate-800">
            Pipeline Execution History ({filteredRuns.length} runs)
          </div>
          <div className="text-[11px] text-slate-500">
            Most recent operations first
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-[#E2E8F0] text-[11px] font-semibold text-slate-500 uppercase tracking-wider bg-slate-50">
                <th className="py-3 px-4">Run ID</th>
                <th className="py-3 px-4">Type</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Started</th>
                <th className="py-3 px-4">Finished</th>
                <th className="py-3 px-4">Duration</th>
                <th className="py-3 px-4 text-center">Inspect</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs text-slate-700">
              {filteredRuns.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500">
                    <div className="max-w-sm mx-auto flex flex-col items-center">
                      <div className="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-3">
                        <Terminal className="w-5 h-5" />
                      </div>
                      <h4 className="text-sm font-bold text-slate-800">No runs recorded</h4>
                      <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                        Trigger a detection or evaluation pipeline run from the CLI or sandbox.
                      </p>
                    </div>
                  </td>
                </tr>
              ) : (
                filteredRuns.map((r) => {
                  const start = new Date(r.started_at);
                  const end = r.finished_at ? new Date(r.finished_at) : null;
                  const durationSec = end ? Math.max(0, Math.round((end.getTime() - start.getTime()) / 1000)) : null;

                  const isSuccess = r.status.toLowerCase() === "completed" || r.status.toLowerCase() === "success";
                  const isFailed = r.status.toLowerCase() === "failed";

                  return (
                    <tr
                      key={r.run_id}
                      onClick={() => setSelectedRun(r)}
                      className="hover:bg-slate-50/80 transition-colors cursor-pointer group"
                    >
                      <td className="py-3.5 px-4 font-mono font-medium text-slate-900 whitespace-nowrap">
                        <span className="text-cyan-800 group-hover:underline">
                          {r.run_id}
                        </span>
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap">
                        <div className="inline-flex items-center gap-1.5">
                          {getRunIcon(r.kind)}
                          <span className="font-semibold text-slate-800 capitalize">
                            {r.kind}
                          </span>
                        </div>
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap">
                        <span
                          className={`inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-semibold rounded-md ${
                            isSuccess
                              ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                              : isFailed
                              ? "bg-red-50 text-red-700 border border-red-200"
                              : "bg-sky-50 text-sky-700 border border-sky-200"
                          }`}
                        >
                          {isSuccess ? (
                            <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                          ) : isFailed ? (
                            <XCircle className="w-3 h-3 text-red-600" />
                          ) : (
                            <Clock className="w-3 h-3 text-sky-600" />
                          )}
                          <span className="capitalize">{r.status}</span>
                        </span>
                      </td>

                      <td className="py-3.5 px-4 text-slate-600 whitespace-nowrap text-[11px]">
                        {formatDateTime(r.started_at)}
                      </td>

                      <td className="py-3.5 px-4 text-slate-600 whitespace-nowrap text-[11px]">
                        {r.finished_at ? formatDateTime(r.finished_at) : "In progress..."}
                      </td>

                      <td className="py-3.5 px-4 font-mono text-slate-700 whitespace-nowrap">
                        {durationSec !== null ? `${durationSec}s` : "—"}
                      </td>

                      <td className="py-3.5 px-4 text-center whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => setSelectedRun(r)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-slate-700 hover:text-slate-900 bg-white hover:bg-slate-50 border border-slate-300 rounded shadow-2xs cursor-pointer"
                        >
                          <span>Inspect</span>
                          <ChevronRight className="w-3 h-3 text-slate-400" />
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 5. Run Details Modal / Slide-over */}
      {selectedRun && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-xs">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-2xl w-full max-h-[85vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-slate-50">
              <div className="flex items-center gap-2.5">
                {getRunIcon(selectedRun.kind)}
                <div>
                  <h3 className="text-base font-bold text-slate-900">
                    Run #{selectedRun.run_id}
                  </h3>
                  <p className="text-xs text-slate-500 capitalize">
                    {selectedRun.kind} Operation Telemetry
                  </p>
                </div>
              </div>

              <button
                onClick={() => setSelectedRun(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-4 overflow-y-auto text-xs">
              <div className="grid grid-cols-2 gap-4 p-4 rounded-xl bg-slate-50 border border-slate-200">
                <div>
                  <span className="text-[11px] font-medium text-slate-500 block">Status</span>
                  <span className="font-semibold text-slate-900 capitalize text-sm">{selectedRun.status}</span>
                </div>
                <div>
                  <span className="text-[11px] font-medium text-slate-500 block">Operation Kind</span>
                  <span className="font-semibold text-slate-900 capitalize text-sm">{selectedRun.kind}</span>
                </div>
                <div>
                  <span className="text-[11px] font-medium text-slate-500 block">Started At</span>
                  <span className="text-slate-700 font-mono">{formatDateTime(selectedRun.started_at)}</span>
                </div>
                <div>
                  <span className="text-[11px] font-medium text-slate-500 block">Finished At</span>
                  <span className="text-slate-700 font-mono">
                    {selectedRun.finished_at ? formatDateTime(selectedRun.finished_at) : "Active"}
                  </span>
                </div>
              </div>

              <div>
                <h4 className="font-bold text-slate-900 text-xs mb-1.5 flex items-center gap-1.5">
                  <Terminal className="w-3.5 h-3.5 text-slate-500" />
                  <span>Execution Summary & Metadata</span>
                </h4>
                <pre className="p-3 bg-slate-900 text-slate-100 rounded-lg text-[11px] font-mono overflow-x-auto leading-relaxed">
                  {JSON.stringify(
                    {
                      run_id: selectedRun.run_id,
                      kind: selectedRun.kind,
                      seed: selectedRun.seed,
                      summary: selectedRun.summary,
                    },
                    null,
                    2
                  )}
                </pre>
              </div>
            </div>

            <div className="px-6 py-3 border-t border-slate-200 bg-slate-50 flex justify-end">
              <button
                onClick={() => setSelectedRun(null)}
                className="px-4 py-1.5 text-xs font-semibold text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-100 transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
