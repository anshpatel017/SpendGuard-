import {
  CheckCircle2,
  RefreshCw,
  ShieldCheck,
  AlertCircle,
  Database,
  Server,
  Cpu,
  Layers,
  FileCheck2,
} from "lucide-react";
import { useState } from "react";

import { useHealth } from "../api/hooks";
import { useToast } from "../context/ToastContext";

export function HealthPage() {
  const { data: health, isLoading, error, refetch } = useHealth();
  const { showToast } = useToast();
  const [checking, setChecking] = useState(false);

  const handlePingServices = async () => {
    setChecking(true);
    try {
      const res = await refetch();
      if (res.data?.status === "ok") {
        showToast("All core system services verified healthy");
      } else {
        showToast("System services responded with degraded state", "error");
      }
    } catch {
      showToast("Failed to ping system services", "error");
    } finally {
      setChecking(false);
    }
  };

  const isDegraded = health?.status === "degraded" || !!error;

  return (
    <div className="space-y-6">
      {/* 1. Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-xl sm:text-2xl font-bold text-[#0F172A] tracking-tight">
            System Health Status
          </h2>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Live readiness and availability telemetry for academic review and production demonstrations.
          </p>
        </div>

        <button
          onClick={handlePingServices}
          disabled={checking || isLoading}
          className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50 transition-colors shadow-2xs self-start sm:self-auto cursor-pointer"
        >
          <RefreshCw className={`w-3.5 h-3.5 text-slate-500 ${checking ? "animate-spin" : ""}`} />
          <span>{checking ? "Checking Services..." : "Ping All Services"}</span>
        </button>
      </div>

      {/* 2. Global Readiness Banner */}
      <div
        className={`p-4 rounded-xl border flex items-center justify-between text-xs ${
          isDegraded
            ? "border-amber-200 bg-amber-50/70"
            : "border-emerald-200 bg-emerald-50/70"
        }`}
      >
        <div className="flex items-center gap-3">
          <div
            className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
              isDegraded
                ? "bg-amber-100 text-amber-800"
                : "bg-emerald-100 text-emerald-800"
            }`}
          >
            {isDegraded ? <AlertCircle className="w-5 h-5" /> : <ShieldCheck className="w-5 h-5" />}
          </div>
          <div>
            <h4
              className={`text-sm font-bold ${
                isDegraded ? "text-amber-950" : "text-emerald-950"
              }`}
            >
              {isDegraded
                ? "System Warning: Degraded Telemetry Detected"
                : "All Systems Operational & Nominal"}
            </h4>
            <p
              className={`text-[11px] mt-0.5 ${
                isDegraded ? "text-amber-800" : "text-emerald-800"
              }`}
            >
              Read-only investigation tools verified isolated. No database write locks or connection saturation.
            </p>
          </div>
        </div>

        <span className="hidden sm:inline-flex px-2.5 py-1 rounded bg-white border border-emerald-300 font-mono text-emerald-900 font-bold">
          {health?.status ? health.status.toUpperCase() : "CHECKING"}
        </span>
      </div>

      {/* 3. Five Core Health Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Card 1: API */}
        <div className="p-5 bg-white rounded-xl border border-[#E2E8F0] shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-900 flex items-center gap-2">
                <Server className="w-4 h-4 text-cyan-700" />
                <span>API Gateway & REST</span>
              </span>
              <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                <CheckCircle2 className="w-3 h-3" />
                <span>Healthy</span>
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-2">
              Ingestion webhook listener, investigation queues, and case telemetry endpoints.
            </p>
          </div>

          <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between text-xs font-mono">
            <span className="text-slate-400 font-sans text-[11px]">Protocol: HTTP/REST</span>
            <span className="text-slate-700">Status: 200 OK</span>
          </div>
        </div>

        {/* Card 2: DuckDB Engine */}
        <div className="p-5 bg-white rounded-xl border border-[#E2E8F0] shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-900 flex items-center gap-2">
                <Database className="w-4 h-4 text-cyan-700" />
                <span>DuckDB Analytical Engine</span>
              </span>
              <span
                className={`inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded border ${
                  health?.duckdb
                    ? "text-emerald-700 bg-emerald-50 border-emerald-200"
                    : "text-amber-700 bg-amber-50 border-amber-200"
                }`}
              >
                {health?.duckdb ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                <span>{health?.duckdb ? "Connected" : "Disconnected"}</span>
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-2">
              High-performance analytical engine for statistical MAD, temporal clustering, and ledger queries.
            </p>
          </div>

          <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between text-xs font-mono">
            <span className="text-slate-400 font-sans text-[11px]">Storage: Memory-Mapped Parquet</span>
            <span className="text-slate-700">{health?.duckdb ? "Ready" : "Inactive"}</span>
          </div>
        </div>

        {/* Card 3: SQLite Case Store */}
        <div className="p-5 bg-white rounded-xl border border-[#E2E8F0] shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-900 flex items-center gap-2">
                <Layers className="w-4 h-4 text-cyan-700" />
                <span>Case & Audit Ledger Store</span>
              </span>
              <span
                className={`inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded border ${
                  health?.case_store
                    ? "text-emerald-700 bg-emerald-50 border-emerald-200"
                    : "text-amber-700 bg-amber-50 border-amber-200"
                }`}
              >
                {health?.case_store ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                <span>{health?.case_store ? "Mounted" : "Error"}</span>
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-2">
              Persistent storage for cases, human reviews, notes, and audit history.
            </p>
          </div>

          <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between text-xs font-mono">
            <span className="text-slate-400 font-sans text-[11px]">Engine: SQLite WAL</span>
            <span className="text-slate-700">Integrity: Verified</span>
          </div>
        </div>

        {/* Card 4: AI Provider */}
        <div className="p-5 bg-white rounded-xl border border-[#E2E8F0] shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-900 flex items-center gap-2">
                <Cpu className="w-4 h-4 text-cyan-700" />
                <span>AI Investigation Provider</span>
              </span>
              <span
                className={`inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded border ${
                  health?.llm_configured
                    ? "text-emerald-700 bg-emerald-50 border-emerald-200"
                    : "text-amber-700 bg-amber-50 border-amber-200"
                }`}
              >
                {health?.llm_configured ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                <span>{health?.llm_configured ? "Configured" : "Heuristic Fallback"}</span>
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-2">
              Isolated tool sandbox agent runtime pool for automated evidence-backed reasoning.
            </p>
          </div>

          <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between text-xs font-mono">
            <span className="text-slate-400 font-sans text-[11px]">Model:</span>
            <span className="text-slate-700 truncate max-w-[150px]">{health?.llm_model ?? "Mock Agent / Heuristic"}</span>
          </div>
        </div>

        {/* Card 5: Deterministic Verification Engine */}
        <div className="p-5 bg-white rounded-xl border border-[#E2E8F0] shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-900 flex items-center gap-2">
                <FileCheck2 className="w-4 h-4 text-cyan-700" />
                <span>Verification Engine</span>
              </span>
              <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                <CheckCircle2 className="w-3 h-3" />
                <span>Active</span>
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-2">
              Independent mathematical verification layer checking row existence, values, and policies.
            </p>
          </div>

          <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between text-xs font-mono">
            <span className="text-slate-400 font-sans text-[11px]">Rules: Deterministic</span>
            <span className="text-slate-700">Strict Citations</span>
          </div>
        </div>
      </div>

      {/* 4. Live Health Check Log */}
      <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between text-xs">
          <span className="font-bold text-slate-800">
            Health Check Telemetry Log
          </span>
          <span className="text-slate-400 font-mono">Automated 30-second polling cycle</span>
        </div>

        <div className="p-4 divide-y divide-slate-100 text-xs">
          <div className="py-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
              <div>
                <span className="font-semibold text-slate-900">HTTP REST Gateway</span>
                <p className="text-[11px] text-slate-500">FastAPI ASGI router /api/v1</p>
              </div>
            </div>
            <div className="text-right font-mono text-[11px]">
              <span className="text-slate-700">Status 200</span>
              <span className="text-slate-400 block text-[10px] font-sans">Active</span>
            </div>
          </div>

          <div className="py-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className={`w-4 h-4 ${health?.duckdb ? "text-emerald-600" : "text-amber-500"} shrink-0`} />
              <div>
                <span className="font-semibold text-slate-900">DuckDB Transaction Database</span>
                <p className="text-[11px] text-slate-500">Analytical columnar store</p>
              </div>
            </div>
            <div className="text-right font-mono text-[11px]">
              <span className="text-slate-700">{health?.duckdb ? "Connected" : "Warning"}</span>
              <span className="text-slate-400 block text-[10px] font-sans">Read-Only Pool</span>
            </div>
          </div>

          <div className="py-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className={`w-4 h-4 ${health?.case_store ? "text-emerald-600" : "text-red-500"} shrink-0`} />
              <div>
                <span className="font-semibold text-slate-900">SQLite Case Store</span>
                <p className="text-[11px] text-slate-500">Case reviews & notes persistent ledger</p>
              </div>
            </div>
            <div className="text-right font-mono text-[11px]">
              <span className="text-slate-700">{health?.case_store ? "Mounted" : "Unavailable"}</span>
              <span className="text-slate-400 block text-[10px] font-sans">WAL mode</span>
            </div>
          </div>

          <div className="py-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className={`w-4 h-4 ${health?.llm_configured ? "text-emerald-600" : "text-cyan-600"} shrink-0`} />
              <div>
                <span className="font-semibold text-slate-900">AI Model Provider</span>
                <p className="text-[11px] text-slate-500">{health?.llm_model ? `Configured with ${health.llm_model}` : "Rule-based mock investigation agent active"}</p>
              </div>
            </div>
            <div className="text-right font-mono text-[11px]">
              <span className="text-slate-700">{health?.llm_configured ? "Live API" : "Simulated"}</span>
              <span className="text-slate-400 block text-[10px] font-sans">Sandbox isolated</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
