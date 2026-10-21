import {
  AlertTriangle,
  ArrowLeft,
  Download,
  FileSearch,
  FileText,
  Info,
  RefreshCw,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { useCaseDetail, useInvestigationStatus, useTriggerInvestigation } from "../api/hooks";
import type { Case } from "../api/types";
import {
  DetectorBadge,
  SeverityBadge,
  StatusBadge,
} from "../components/common/Badge";
import { Loading } from "../components/common";
import { EvidenceTable } from "../components/EvidenceTable";
import { NotePanel } from "../components/NotePanel";
import { ReviewPanel } from "../components/ReviewPanel";
import { TraceTimeline } from "../components/TraceTimeline";
import { useToast } from "../context/ToastContext";
import { ANOMALY_LABEL, formatDateTime, formatMoney } from "../lib/format";

function FactsCard({ c }: { c: Case }) {
  const metadata = Object.entries(c.metadata).filter(([, v]) => typeof v !== "object" || v === null);

  return (
    <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs p-5 space-y-4">
      <div className="flex items-center gap-2 pb-3 border-b border-slate-100">
        <FileSearch className="w-4 h-4 text-cyan-700" />
        <h3 className="text-sm font-bold text-slate-900">Detection Parameters & Facts</h3>
      </div>

      <dl className="grid grid-cols-2 gap-3 text-xs">
        <div>
          <dt className="text-[11px] font-medium text-slate-500">Detector</dt>
          <dd className="font-mono text-slate-900 font-semibold mt-0.5">{c.detector}</dd>
        </div>
        <div>
          <dt className="text-[11px] font-medium text-slate-500">Anomaly Score</dt>
          <dd className="font-mono text-cyan-700 font-semibold mt-0.5">{c.detector_score.toFixed(3)}</dd>
        </div>
        <div>
          <dt className="text-[11px] font-medium text-slate-500">Evidence Rows</dt>
          <dd className="font-mono text-slate-900 font-semibold mt-0.5">{c.row_ids.length} rows</dd>
        </div>
        <div>
          <dt className="text-[11px] font-medium text-slate-500">Amount At Risk</dt>
          <dd className="font-mono text-slate-900 font-semibold mt-0.5">{formatMoney(c.amount_at_risk)}</dd>
        </div>

        {metadata.slice(0, 10).map(([key, value]) => (
          <div key={key} className="col-span-2 sm:col-span-1 pt-1 border-t border-slate-100/60">
            <dt className="text-[11px] font-medium text-slate-500 capitalize">{key.replaceAll("_", " ")}</dt>
            <dd className="font-mono text-slate-800 text-[11px] mt-0.5 break-all">
              {typeof value === "number" ? Number(value.toFixed(4)) : String(value)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function CasePage() {
  const { caseId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { showToast } = useToast();

  const returnSearch = location.search || (location.state as { returnSearch?: string } | null)?.returnSearch || "";
  const backUrl = returnSearch ? `/dashboard${returnSearch.startsWith("?") ? returnSearch : `?${returnSearch}`}` : "/dashboard";

  const detail = useCaseDetail(caseId);
  const [highlight, setHighlight] = useState<number | null>(null);
  const trigger = useTriggerInvestigation(caseId);

  const initialStatus = detail.data?.investigation_status;
  const isJobActive =
    initialStatus?.state === "queued" ||
    initialStatus?.state === "investigating" ||
    initialStatus?.state === "verifying";
  const statusQuery = useInvestigationStatus(caseId, isJobActive || trigger.isSuccess);
  const activeStatus = statusQuery.data ?? initialStatus;

  const isInvestigating =
    trigger.isPending ||
    activeStatus?.state === "queued" ||
    activeStatus?.state === "investigating" ||
    activeStatus?.state === "verifying";

  const handleTrigger = () => {
    trigger.mutate(undefined, {
      onSuccess: () => {
        showToast("Autonomous investigation job queued", "info");
      },
      onError: (err) => {
        showToast(err instanceof Error ? err.message : "Failed to trigger investigation", "error");
      },
    });
  };

  const inspect = (rowId: number) => {
    setHighlight(null);
    requestAnimationFrame(() => setHighlight(rowId));
  };

  if (detail.isPending) {
    return (
      <div className="p-8">
        <Loading what="case details" />
      </div>
    );
  }

  if (detail.error) {
    const missing = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <div className="p-12 text-center bg-white rounded-xl border border-slate-200 shadow-xs max-w-lg mx-auto mt-8">
        <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mx-auto mb-3">
          <ShieldAlert className="w-6 h-6" />
        </div>
        <h3 className="text-base font-bold text-slate-900">
          {missing ? "Case Not Found" : "Error Loading Case"}
        </h3>
        <p className="text-xs text-slate-500 mt-1">
          {missing ? (
            <>
              The case <code className="font-mono bg-slate-100 px-1 py-0.5 rounded">#{caseId}</code> does not exist in the active dataset.
            </>
          ) : (
            detail.error.message
          )}
        </p>
        <button
          onClick={() => navigate(backUrl)}
          className="mt-5 px-4 py-2 text-xs font-semibold text-white bg-black hover:bg-neutral-800 rounded-lg transition-colors inline-flex items-center gap-2 cursor-pointer"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Return to Queue</span>
        </button>
      </div>
    );
  }

  const { case: c, audit_note: note } = detail.data;

  return (
    <div className="space-y-6">
      {/* 1. Header Navigation & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <button
            onClick={() => navigate(backUrl)}
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition-colors cursor-pointer"
            title="Return to queue"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center gap-1.5 text-xs text-slate-500">
              <Link to={backUrl} className="hover:text-slate-900 transition-colors">
                Investigation Queue
              </Link>
              <span>/</span>
              <span className="font-mono text-slate-800 font-semibold">{c.case_id}</span>
            </div>
            <h1 className="text-xl sm:text-2xl font-bold text-[#0F172A] tracking-tight flex items-center gap-3 mt-0.5">
              <span>{ANOMALY_LABEL[c.anomaly_type]}</span>
              <span className="text-slate-400 font-normal">·</span>
              <span className="text-slate-700 font-semibold">{c.vendor_key ?? "Unknown Supplier"}</span>
            </h1>
          </div>
        </div>

        {/* Action Buttons & Status */}
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={api.exportReportUrl(c.case_id, "markdown")}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50 transition-colors shadow-2xs"
            title="Download full audit memo in Markdown format"
          >
            <Download className="w-3.5 h-3.5 text-slate-500" />
            <span>Export (MD)</span>
          </a>

          <a
            href={api.exportReportUrl(c.case_id, "html")}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50 transition-colors shadow-2xs"
            title="Open formatted case report in HTML"
          >
            <FileText className="w-3.5 h-3.5 text-slate-500" />
            <span>Export (HTML)</span>
          </a>

          <button
            type="button"
            disabled={isInvestigating}
            onClick={handleTrigger}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-black hover:bg-neutral-800 disabled:bg-slate-300 rounded-md transition-all shadow-xs cursor-pointer"
          >
            {isInvestigating ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Sparkles className="w-3.5 h-3.5 text-cyan-300" />
            )}
            <span>
              {trigger.isPending
                ? "Queuing…"
                : activeStatus?.state === "investigating"
                ? "Investigating…"
                : activeStatus?.state === "verifying"
                ? "Verifying Claims…"
                : activeStatus?.state === "queued"
                ? "Queued…"
                : activeStatus?.state === "failed"
                ? "Retry AI Investigation"
                : note
                ? "Re-investigate with AI"
                : "Investigate with AI"}
            </span>
          </button>
        </div>
      </div>

      {/* 2. Top Summary Card */}
      <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs p-5">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-4 divide-y md:divide-y-0 md:divide-x divide-slate-100 text-xs">
          <div className="pr-3">
            <span className="text-[11px] font-medium text-slate-500 block">Detector Type</span>
            <div className="mt-1">
              <DetectorBadge detector={c.detector} anomalyType={c.anomaly_type} />
            </div>
          </div>

          <div className="pt-2 md:pt-0 md:px-3">
            <span className="text-[11px] font-medium text-slate-500 block">Vendor / Supplier</span>
            <span className="font-semibold text-slate-900 text-sm mt-0.5 block truncate">
              {c.vendor_key ?? "—"}
            </span>
          </div>

          <div className="pt-2 md:pt-0 md:px-3">
            <span className="text-[11px] font-medium text-slate-500 block">Amount At Risk</span>
            <span className="font-mono font-bold text-slate-900 text-sm mt-0.5 block tabular-nums">
              {formatMoney(c.amount_at_risk)}
            </span>
          </div>

          <div className="pt-2 md:pt-0 md:px-3">
            <span className="text-[11px] font-medium text-slate-500 block">Detection Score</span>
            <span className="font-mono font-semibold text-[#0E7490] text-sm mt-0.5 block tabular-nums">
              {c.detector_score.toFixed(2)}
            </span>
          </div>

          <div className="pt-2 md:pt-0 md:px-3">
            <span className="text-[11px] font-medium text-slate-500 block">Severity Level</span>
            <div className="mt-1">
              <SeverityBadge severity={c.severity_band} />
            </div>
          </div>

          <div className="pt-2 md:pt-0 md:pl-3">
            <span className="text-[11px] font-medium text-slate-500 block">Review Status</span>
            <div className="mt-1">
              <StatusBadge status={c.status} />
            </div>
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-slate-100 text-xs text-slate-600 flex items-start gap-2">
          <Info className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
          <span>
            Case flagged on {formatDateTime(c.created_at)}. {c.row_ids.length} transactions included in initial anomaly cluster.
            {c.dismissed_by_agent && " Agent preliminary triage indicates likely false positive."}
          </span>
        </div>
      </div>

      {/* 2b. Audit Context Banner */}
      <div className="p-4 rounded-xl border border-black bg-neutral-50 flex items-start gap-3 text-xs leading-relaxed shadow-2xs">
        <ShieldAlert className="w-4 h-4 text-black shrink-0 mt-0.5" />
        <div>
          <strong className="font-semibold block text-black">
            Forensic Evidence Grounding Protocol
          </strong>
          <span className="text-slate-600">
            All AI findings, citations, and claim verifications are derived strictly from primary source DuckDB rows. Final compliance determinations remain under exclusive human authority.
          </span>
        </div>
      </div>

      {/* 3. Investigation Live Status Banner (if active or failed) */}
      {activeStatus && activeStatus.state !== "not_investigated" && activeStatus.state !== "completed" && (
        <div
          className={`p-4 rounded-xl border text-xs shadow-2xs ${
            activeStatus.state === "failed"
              ? "bg-red-50/70 border-red-200"
              : "bg-sky-50/70 border-sky-200"
          }`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              {activeStatus.state === "failed" ? (
                <AlertTriangle className="w-4 h-4 text-red-600 shrink-0" />
              ) : (
                <RefreshCw className="w-4 h-4 text-cyan-700 animate-spin shrink-0" />
              )}
              <div>
                <span className="font-bold text-slate-900 capitalize">
                  {activeStatus.state === "investigating"
                    ? "AI Investigator Running"
                    : activeStatus.state === "verifying"
                    ? "Mathematical Verifier Checking Claims"
                    : activeStatus.state === "queued"
                    ? "Investigation Queued"
                    : "Investigation Error"}
                </span>
                <span className="text-slate-600 ml-2">
                  {activeStatus.stage ?? "Querying DuckDB ledger and evaluating policy benchmarks..."}
                </span>
              </div>
            </div>

            <span className="font-mono text-[11px] text-slate-500">
              State: {activeStatus.state}
            </span>
          </div>

          {activeStatus.error && (
            <div className="mt-2.5 pt-2.5 border-t border-red-200 text-red-800 text-[11px]">
              <strong>Provider Notice:</strong> {activeStatus.error}
            </div>
          )}
        </div>
      )}

      {/* 4. Two-Column Grid: Investigation & Review */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: AI Note, Evidence Table, Citations (7 cols) */}
        <div className="lg:col-span-7 space-y-6">
          {note ? (
            <NotePanel note={note} onInspect={inspect} />
          ) : (
            <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs p-6 text-center">
              <div className="w-10 h-10 rounded-full bg-cyan-50 flex items-center justify-center text-[#0E7490] mx-auto mb-3">
                <Sparkles className="w-5 h-5" />
              </div>
              <h4 className="text-sm font-semibold text-slate-900">Not Investigated by AI Yet</h4>
              <p className="text-xs text-slate-500 max-w-md mx-auto mt-1 leading-relaxed">
                Deterministic detectors flagged this case based on mathematical rules. Click &ldquo;Investigate with AI&rdquo; to launch autonomous evidence collection and claim verification.
              </p>
              <button
                type="button"
                disabled={isInvestigating}
                onClick={handleTrigger}
                className="mt-4 px-4 py-2 text-xs font-semibold text-white bg-black hover:bg-neutral-800 disabled:bg-slate-300 rounded-lg transition-colors shadow-xs inline-flex items-center gap-1.5 cursor-pointer"
              >
                <Sparkles className="w-3.5 h-3.5 text-cyan-300" />
                <span>Investigate with AI</span>
              </button>
            </div>
          )}

          <EvidenceTable
            evidence={detail.data.evidence_rows}
            total={detail.data.evidence_total}
            context={detail.data.context_rows}
            highlight={highlight}
          />

          {note && <TraceTimeline trace={detail.data.trace} />}
        </div>

        {/* Right Column: Human Review & Facts (5 cols) */}
        <div className="lg:col-span-5 space-y-6">
          <ReviewPanel c={c} reviews={detail.data.reviews} />
          <FactsCard c={c} />
        </div>
      </div>
    </div>
  );
}
