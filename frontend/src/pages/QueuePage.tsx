import {
  AlertTriangle,
  ArrowUpDown,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  FileCheck2,
  RotateCcw,
  Search,
  ShieldAlert,
  SlidersHorizontal,
} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import type { CaseFilters } from "../api/client";
import { useCases, useMetrics } from "../api/hooks";
import type { CaseSummary, MetricsResponse } from "../api/types";
import {
  DetectorBadge,
  SeverityBadge,
  StatusBadge,
} from "../components/common/Badge";
import { ErrorBanner, Loading, VerificationBadge } from "../components/common";
import { useToast } from "../context/ToastContext";
import {
  ANOMALY_LABEL,
  STATUS_LABEL,
  VERDICT_LABEL,
  formatCount,
  formatMoney,
  formatMoneyShort,
} from "../lib/format";

const PAGE_SIZE = 50;
const FILTER_KEYS = [
  "anomaly_type",
  "detector",
  "severity_band",
  "severity",
  "status",
  "verdict",
  "verification_status",
  "investigated",
  "dismissed_by_agent",
  "search",
  "sort",
  "order",
] as const;

function KpiMetrics({ m }: { m: MetricsResponse }) {
  const openCasesCount = (m.by_status?.new ?? 0) + (m.by_status?.under_review ?? 0);
  const highRiskCount = m.by_severity_band?.high ?? 0;
  const aiInvestigatedCount = m.cases_investigated ?? 0;
  const confirmedCount = m.by_status?.confirmed ?? 0;
  const coveragePercent = m.cases_flagged > 0 ? Math.round((aiInvestigatedCount / m.cases_flagged) * 100) : 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Open Cases */}
        <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-500">
            <span className="text-xs font-medium">Open Cases</span>
            <div className="p-1.5 rounded-lg bg-sky-50 text-[#0E7490]">
              <ShieldAlert className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl sm:text-3xl font-bold text-[#0F172A] font-mono tabular-nums">
              {formatCount(openCasesCount)}
            </div>
            <div className="text-[11px] text-slate-500 mt-1">
              New & Under Review status
            </div>
          </div>
        </div>

        {/* Card 2: High Risk */}
        <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-500">
            <span className="text-xs font-medium">High / Critical Risk</span>
            <div className="p-1.5 rounded-lg bg-slate-100 text-black">
              <AlertTriangle className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl sm:text-3xl font-bold text-black font-mono tabular-nums">
              {formatCount(highRiskCount)}
            </div>
            <div className="text-[11px] text-slate-500 mt-1">
              Requires urgent escalation
            </div>
          </div>
        </div>

        {/* Card 3: AI Investigated */}
        <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-500">
            <span className="text-xs font-medium">AI Investigated</span>
            <div className="p-1.5 rounded-lg bg-slate-100 text-black">
              <FileCheck2 className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl sm:text-3xl font-bold text-black font-mono tabular-nums">
              {formatCount(aiInvestigatedCount)}
            </div>
            <div className="text-[11px] text-slate-600 font-medium mt-1">
              {coveragePercent}% coverage of queue
            </div>
          </div>
        </div>

        {/* Card 4: Confirmed */}
        <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-500">
            <span className="text-xs font-medium">Confirmed Cases</span>
            <div className="p-1.5 rounded-lg bg-slate-100 text-black">
              <CheckCircle2 className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl sm:text-3xl font-bold text-black font-mono tabular-nums">
              {formatCount(confirmedCount)}
            </div>
            <div className="text-[11px] text-slate-500 mt-1">
              {formatMoneyShort(m.money_at_risk_confirmed)} at risk confirmed
            </div>
          </div>
        </div>
      </div>

      {/* Coverage Banner (Contract item preserved for tests) */}
      <div
        className="p-4 rounded-xl border border-black bg-neutral-50 shadow-2xs text-xs text-slate-800 flex items-start gap-3 leading-relaxed"
        data-testid="coverage-line"
      >
        <ShieldAlert className="w-4 h-4 text-black shrink-0 mt-0.5" />
        <div className="flex-1 flex flex-col md:flex-row md:items-center md:justify-between gap-2">
          <span>
            <strong className="font-bold text-black">100% Audit Coverage:</strong> Scanned {formatMoneyShort(m.total_amount)} across procurement transactions.{" "}
            <strong>{formatCount(m.cases_flagged)}</strong> cases flagged ·{" "}
            <strong>{formatCount(m.cases_investigated)}</strong> investigated ·{" "}
            <strong>{formatCount(m.cases_queued)}</strong> queued for investigation, highest severity first.
          </span>
          <span className="text-[11px] font-mono text-slate-800 bg-white px-2 py-0.5 rounded border border-slate-300 whitespace-nowrap self-start md:self-auto font-semibold shadow-2xs">
            Risk Pool: {formatMoney(m.money_at_risk)}
          </span>
        </div>
      </div>
    </div>
  );
}

function CaseRow({
  c,
  onOpen,
}: {
  c: CaseSummary;
  onOpen: () => void;
}) {
  return (
    <tr
      className="hover:bg-slate-50/80 transition-colors cursor-pointer group border-b border-slate-100 text-xs text-slate-700"
      onClick={onOpen}
    >
      {/* Severity */}
      <td className="py-3 px-4 whitespace-nowrap">
        <SeverityBadge severity={c.severity_band} />
      </td>

      {/* Type / Detector */}
      <td className="py-3 px-4 whitespace-nowrap">
        <DetectorBadge detector={c.detector} anomalyType={c.anomaly_type} />
      </td>

      {/* Supplier / Vendor */}
      <td className="py-3 px-4 font-medium text-slate-900 max-w-[180px] truncate">
        {c.vendor_key ?? "—"}
      </td>

      {/* Amount at risk */}
      <td className="py-3 px-4 text-right font-mono font-semibold text-slate-900 tabular-nums whitespace-nowrap">
        {formatMoney(c.amount_at_risk)}
      </td>

      {/* Score */}
      <td className="py-3 px-4 text-right font-mono text-slate-600 whitespace-nowrap">
        {c.detector_score.toFixed(2)}
      </td>

      {/* Status */}
      <td className="py-3 px-4 whitespace-nowrap">
        <StatusBadge status={c.status} />
      </td>

      {/* Agent Verdict */}
      <td className="py-3 px-4 whitespace-nowrap">
        {c.verdict ? (
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${
              c.verdict === "likely_false_positive"
                ? "bg-slate-100 text-slate-700 border border-slate-200"
                : "bg-cyan-50 text-cyan-800 border border-cyan-200"
            }`}
          >
            {VERDICT_LABEL[c.verdict]}
          </span>
        ) : (
          <span className="text-slate-400 text-[11px]">queued</span>
        )}
      </td>

      {/* Verification */}
      <td className="py-3 px-4 whitespace-nowrap">
        {c.investigated ? (
          <VerificationBadge
            status={c.verification_status}
            passed={c.citations_passed}
            checked={c.citations_checked}
          />
        ) : (
          <span className="text-slate-400 text-[11px]">—</span>
        )}
      </td>

      {/* Finding Excerpt */}
      <td className="py-3 px-4 text-slate-500 max-w-[220px] truncate text-[11px]">
        {c.finding_excerpt ?? "—"}
      </td>

      {/* Action */}
      <td className="py-3 px-4 text-center whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={onOpen}
          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold text-[#0E7490] hover:text-white hover:bg-[#0E7490] rounded border border-cyan-200 hover:border-cyan-600 transition-all shadow-2xs cursor-pointer"
        >
          <Eye className="w-3.5 h-3.5" />
          <span>View</span>
        </button>
      </td>
    </tr>
  );
}

export function QueuePage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const metrics = useMetrics();
  const { showToast } = useToast();

  const detectorVal = params.get("detector") || params.get("anomaly_type") || "";
  const severityVal = params.get("severity") || params.get("severity_band") || "";
  const searchVal = params.get("search") || "";
  const statusVal = params.get("status") || "";
  const investigatedVal = params.get("investigated") || "";
  const verdictVal = params.get("verdict") || "";
  const verificationVal = params.get("verification_status") || "";
  const dismissedVal = params.get("dismissed_by_agent") === "true";

  const filters: CaseFilters = {
    page: Number(params.get("page") ?? 1),
    page_size: PAGE_SIZE,
  };
  if (detectorVal) filters.detector = detectorVal;
  if (severityVal) filters.severity_band = severityVal;
  if (searchVal) filters.search = searchVal;

  for (const key of FILTER_KEYS) {
    const value = params.get(key);
    if (value && !(key in filters)) {
      (filters as Record<string, unknown>)[key] = value;
    }
  }

  const cases = useCases(filters);

  const isFiltered = Boolean(
    detectorVal ||
    severityVal ||
    searchVal ||
    statusVal ||
    investigatedVal ||
    verdictVal ||
    verificationVal ||
    dismissedVal ||
    params.get("sort")
  );

  const resetAllFilters = () => {
    setParams(new URLSearchParams());
    showToast("Filters reset to default");
  };

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  };

  const setDetector = (val: string) => {
    const next = new URLSearchParams(params);
    if (val) {
      next.set("detector", val);
      next.delete("anomaly_type");
    } else {
      next.delete("detector");
      next.delete("anomaly_type");
    }
    next.delete("page");
    setParams(next);
  };

  const setSeverity = (val: string) => {
    const next = new URLSearchParams(params);
    if (val) {
      next.set("severity", val);
      next.delete("severity_band");
    } else {
      next.delete("severity");
      next.delete("severity_band");
    }
    next.delete("page");
    setParams(next);
  };

  const sortBy = (key: string) => {
    const same = (params.get("sort") ?? "severity_prelim") === key;
    const next = new URLSearchParams(params);
    next.set("sort", key);
    next.set("order", same && params.get("order") !== "asc" ? "asc" : "desc");
    next.delete("page");
    setParams(next);
  };

  const page = filters.page ?? 1;
  const pages = cases.data ? Math.max(1, Math.ceil(cases.data.total / PAGE_SIZE)) : 1;
  const currentSearch = params.toString() ? `?${params.toString()}` : "";

  // CSV export function
  const handleExportCSV = () => {
    if (!cases.data || cases.data.items.length === 0) {
      showToast("No cases available to export", "error");
      return;
    }
    const headers = [
      "Case ID",
      "Detector",
      "Anomaly Type",
      "Supplier",
      "Amount At Risk",
      "Score",
      "Severity",
      "Status",
      "Verdict",
      "Verification Status",
      "Created At",
    ];
    const rows = cases.data.items.map((c) => [
      c.case_id,
      c.detector,
      c.anomaly_type,
      `"${c.vendor_key ?? ""}"`,
      c.amount_at_risk,
      c.detector_score.toFixed(2),
      c.severity_band,
      c.status,
      c.verdict ?? "",
      c.verification_status ?? "",
      c.created_at,
    ]);

    const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `SpendGuard_Queue_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    showToast(`Exported ${cases.data.items.length} cases to CSV`);
  };

  return (
    <div className="space-y-6">
      {/* 1. Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl sm:text-2xl font-bold text-[#0F172A] tracking-tight">
            Investigation Queue
          </h2>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Review detected procurement anomalies and prioritize cases requiring investigation.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {isFiltered && (
            <button
              onClick={resetAllFilters}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-300 rounded-md hover:bg-slate-50 transition-colors shadow-2xs cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5 text-slate-400" />
              <span>Reset Filters</span>
            </button>
          )}

          <button
            onClick={handleExportCSV}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50 transition-colors shadow-2xs cursor-pointer"
          >
            <Download className="w-3.5 h-3.5 text-slate-500" />
            <span>Export CSV</span>
          </button>
        </div>
      </div>

      {/* 2. KPI Metrics Section */}
      {metrics.error ? (
        <ErrorBanner error={metrics.error} />
      ) : metrics.data ? (
        <KpiMetrics m={metrics.data} />
      ) : (
        <Loading what="metrics" />
      )}

      {/* 3. Filter Bar */}
      <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs space-y-3">
        <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3">
          {/* Search Input */}
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              aria-label="Search"
              value={searchVal}
              onChange={(e) => setParam("search", e.target.value)}
              placeholder="Search supplier, case ID, or keyword..."
              className="w-full pl-9 pr-4 py-2 text-xs sm:text-sm bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-cyan-600 focus:bg-white transition-all text-slate-800 placeholder:text-slate-400"
            />
          </div>

          <div className="flex items-center gap-1.5 text-xs text-slate-500 shrink-0">
            <SlidersHorizontal className="w-3.5 h-3.5 text-slate-400" />
            <span>Filters</span>
          </div>
        </div>

        {/* Dropdowns Row */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5 pt-1">
          {/* Detector */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-500 mb-1">Detector</label>
            <select
              aria-label="Detector"
              value={detectorVal}
              onChange={(e) => setDetector(e.target.value)}
              className="w-full py-1.5 px-2 text-xs bg-white border border-slate-300 rounded-md focus:outline-none focus:ring-1 focus:ring-cyan-600 text-slate-700"
            >
              <option value="">All Detectors</option>
              {Object.entries(ANOMALY_LABEL).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          {/* Severity */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-500 mb-1">Severity</label>
            <select
              aria-label="Severity"
              value={severityVal}
              onChange={(e) => setSeverity(e.target.value)}
              className="w-full py-1.5 px-2 text-xs bg-white border border-slate-300 rounded-md focus:outline-none focus:ring-1 focus:ring-cyan-600 text-slate-700"
            >
              <option value="">All Severities</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>

          {/* Status */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-500 mb-1">Status</label>
            <select
              aria-label="Status"
              value={statusVal}
              onChange={(e) => setParam("status", e.target.value)}
              className="w-full py-1.5 px-2 text-xs bg-white border border-slate-300 rounded-md focus:outline-none focus:ring-1 focus:ring-cyan-600 text-slate-700"
            >
              <option value="">All Statuses</option>
              {Object.entries(STATUS_LABEL).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          {/* Investigation */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-500 mb-1">Investigation</label>
            <select
              aria-label="Investigation"
              value={investigatedVal}
              onChange={(e) => setParam("investigated", e.target.value)}
              className="w-full py-1.5 px-2 text-xs bg-white border border-slate-300 rounded-md focus:outline-none focus:ring-1 focus:ring-cyan-600 text-slate-700"
            >
              <option value="">All States</option>
              <option value="true">Investigated</option>
              <option value="false">Queued</option>
            </select>
          </div>

          {/* Verdict */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-500 mb-1">Verdict</label>
            <select
              aria-label="Verdict"
              value={verdictVal}
              onChange={(e) => setParam("verdict", e.target.value)}
              className="w-full py-1.5 px-2 text-xs bg-white border border-slate-300 rounded-md focus:outline-none focus:ring-1 focus:ring-cyan-600 text-slate-700"
            >
              <option value="">All Verdicts</option>
              {Object.entries(VERDICT_LABEL).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          {/* Verification */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-500 mb-1">Verification</label>
            <select
              aria-label="Verification"
              value={verificationVal}
              onChange={(e) => setParam("verification_status", e.target.value)}
              className="w-full py-1.5 px-2 text-xs bg-white border border-slate-300 rounded-md focus:outline-none focus:ring-1 focus:ring-cyan-600 text-slate-700"
            >
              <option value="">All Checks</option>
              <option value="verified">Verified</option>
              <option value="failed_after_retries">Failed checks</option>
              <option value="unverified">Unverified</option>
            </select>
          </div>
        </div>

        {/* Checkbox row */}
        <div className="pt-2 flex items-center justify-between border-t border-slate-100">
          <label className="inline-flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
            <input
              type="checkbox"
              checked={dismissedVal}
              onChange={(e) => setParam("dismissed_by_agent", e.target.checked ? "true" : "")}
              className="rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
            />
            <span>Include cases dismissed by agent</span>
          </label>
        </div>
      </div>

      {/* 4. Cases Table Card */}
      <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200 bg-slate-50/70 flex items-center justify-between">
          <div className="text-xs font-semibold text-slate-800">
            {cases.data ? `Detected Cases (${formatCount(cases.data.total)} total)` : "Loading cases..."}
          </div>
          <div className="text-[11px] text-slate-500">
            Sorted by severity and risk amount
          </div>
        </div>

        {cases.error && <div className="p-4"><ErrorBanner error={cases.error} /></div>}
        {cases.isPending && <div className="p-6"><Loading what="cases" /></div>}

        {cases.data && cases.data.items.length === 0 && (
          <div className="py-12 text-center text-slate-500">
            <div className="max-w-sm mx-auto flex flex-col items-center">
              <div className="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-3">
                <Search className="w-5 h-5" />
              </div>
              <h4 className="text-sm font-bold text-slate-800">No cases match these filters</h4>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                Try modifying your query or reset filters to display all cases.
              </p>
              {isFiltered && (
                <button
                  onClick={resetAllFilters}
                  className="mt-4 px-3.5 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50 transition-colors shadow-xs cursor-pointer"
                >
                  Reset All Filters
                </button>
              )}
            </div>
          </div>
        )}

        {cases.data && cases.data.items.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#E2E8F0] text-[11px] font-semibold text-slate-500 uppercase tracking-wider bg-slate-50">
                    <th
                      className="py-3 px-4 cursor-pointer hover:text-slate-900 transition-colors"
                      onClick={() => sortBy("severity_prelim")}
                    >
                      <div className="inline-flex items-center gap-1">
                        <span>Severity</span>
                        <ArrowUpDown className="w-3 h-3 text-slate-400" />
                      </div>
                    </th>
                    <th className="py-3 px-4">Type</th>
                    <th className="py-3 px-4">Supplier</th>
                    <th
                      className="py-3 px-4 text-right cursor-pointer hover:text-slate-900 transition-colors"
                      onClick={() => sortBy("amount_at_risk")}
                    >
                      <div className="inline-flex items-center gap-1 justify-end">
                        <span>At Risk</span>
                        <ArrowUpDown className="w-3 h-3 text-slate-400" />
                      </div>
                    </th>
                    <th className="py-3 px-4 text-right">Score</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4">Verdict</th>
                    <th className="py-3 px-4">Verification</th>
                    <th className="py-3 px-4">Finding</th>
                    <th className="py-3 px-4 text-center">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.data.items.map((c) => (
                    <CaseRow
                      key={c.case_id}
                      c={c}
                      onOpen={() =>
                        navigate(
                          { pathname: `/cases/${c.case_id}`, search: currentSearch },
                          { state: { returnSearch: currentSearch } },
                        )
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="px-4 py-3 border-t border-slate-200 bg-slate-50 flex items-center justify-between text-xs">
              <span className="text-slate-500">
                Page {page} of {pages}
                {cases.isFetching ? " · refreshing…" : ""}
              </span>

              <div className="flex items-center gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setParam("page", String(page - 1))}
                  className="flex items-center gap-1 px-3 py-1 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed shadow-2xs cursor-pointer"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                  <span>Previous</span>
                </button>
                <button
                  disabled={page >= pages}
                  onClick={() => setParam("page", String(page + 1))}
                  className="flex items-center gap-1 px-3 py-1 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed shadow-2xs cursor-pointer"
                >
                  <span>Next</span>
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
