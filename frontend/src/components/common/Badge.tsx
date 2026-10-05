import React from "react";
import {
  Copy,
  Scissors,
  TrendingUp,
  Building2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  HelpCircle,
} from "lucide-react";

export function StatusBadge({ status }: { status?: string | null }) {
  const norm = (status || "").toLowerCase().replace(/\s+/g, "_");

  const labelMap: Record<string, string> = {
    new: "New",
    under_review: "Under Review",
    confirmed: "Confirmed",
    dismissed: "Dismissed",
  };

  const styleMap: Record<string, string> = {
    new: "bg-sky-50 text-sky-700 border border-sky-200",
    under_review: "bg-amber-50 text-amber-800 border border-amber-200",
    confirmed: "bg-emerald-50 text-emerald-800 border border-emerald-200",
    dismissed: "bg-slate-100 text-slate-700 border border-slate-300",
  };

  const iconMap: Record<string, React.ReactNode> = {
    new: <Clock className="w-3 h-3 shrink-0" />,
    under_review: <AlertTriangle className="w-3 h-3 shrink-0" />,
    confirmed: <CheckCircle2 className="w-3 h-3 shrink-0" />,
    dismissed: <XCircle className="w-3 h-3 shrink-0" />,
  };

  const text = labelMap[norm] || status || "Unknown";
  const style = styleMap[norm] || "bg-slate-100 text-slate-700 border border-slate-200";
  const icon = iconMap[norm] || <Clock className="w-3 h-3 shrink-0" />;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 text-xs font-semibold rounded-md whitespace-nowrap shadow-2xs ${style}`}>
      {icon}
      <span>{text}</span>
    </span>
  );
}

export function SeverityBadge({ severity }: { severity?: string | null }) {
  const norm = (severity || "").toLowerCase();

  const labelMap: Record<string, string> = {
    critical: "Critical",
    high: "High",
    medium: "Medium",
    low: "Low",
  };

  const styleMap: Record<string, string> = {
    critical: "bg-red-50 text-red-700 border border-red-200",
    high: "bg-orange-50 text-orange-700 border border-orange-200",
    medium: "bg-amber-50 text-amber-700 border border-amber-200",
    low: "bg-sky-50 text-sky-700 border border-sky-200",
  };

  const text = labelMap[norm] || severity || "—";
  const style = styleMap[norm] || "bg-slate-100 text-slate-600 border border-slate-200";

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 text-xs font-semibold rounded-md whitespace-nowrap shadow-2xs ${style}`}>
      {text}
    </span>
  );
}

export function VerificationBadge({ status }: { status?: string | null }) {
  if (!status) {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-medium rounded-md whitespace-nowrap text-slate-400 bg-slate-50 border border-slate-200">
        <Clock className="w-3 h-3 shrink-0" />
        <span>Pending</span>
      </span>
    );
  }

  const norm = status.toLowerCase();

  if (norm.includes("verified")) {
    const isRegen = norm.includes("regenerated");
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-semibold rounded-md whitespace-nowrap bg-emerald-50 text-emerald-800 border border-emerald-200 shadow-2xs">
        <CheckCircle2 className="w-3.5 h-3.5 shrink-0 text-emerald-600" />
        <span>{isRegen ? "Verified (Rev)" : "Verified"}</span>
      </span>
    );
  }

  if (norm.includes("failed")) {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-semibold rounded-md whitespace-nowrap bg-red-50 text-red-700 border border-red-200 shadow-2xs">
        <XCircle className="w-3.5 h-3.5 shrink-0 text-red-600" />
        <span>Failed Check</span>
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-medium rounded-md whitespace-nowrap bg-amber-50 text-amber-800 border border-amber-200 shadow-2xs">
      <Clock className="w-3 h-3 shrink-0 text-amber-600" />
      <span>{status}</span>
    </span>
  );
}

export function AIStatusBadge({
  investigated,
  status,
}: {
  investigated?: boolean;
  status?: string | null;
}) {
  const norm = (status || "").toLowerCase();

  if (investigated || norm.includes("completed") || norm.includes("verified")) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700">
        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
        <span>Investigated</span>
      </span>
    );
  }

  if (norm.includes("investigating") || norm.includes("verifying") || norm.includes("queued")) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-sky-700 animate-pulse">
        <span className="w-2 h-2 rounded-full bg-sky-500 animate-ping" />
        <span className="capitalize">{status}...</span>
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500">
      <Clock className="w-3.5 h-3.5 text-slate-400" />
      <span>Pending</span>
    </span>
  );
}

export function DetectorBadge({
  detector,
  anomalyType,
}: {
  detector?: string | null;
  anomalyType?: string | null;
}) {
  const key = (anomalyType || detector || "").toLowerCase();

  let name = detector || anomalyType || "Anomaly";
  let icon = <HelpCircle className="w-3.5 h-3.5 text-slate-500" />;

  if (key.includes("dup")) {
    name = "Duplicate";
    icon = <Copy className="w-3.5 h-3.5 text-[#0E7490]" />;
  } else if (key.includes("split")) {
    name = "Split Purchase";
    icon = <Scissors className="w-3.5 h-3.5 text-[#B45309]" />;
  } else if (key.includes("infl") || key.includes("price")) {
    name = "Price Inflation";
    icon = <TrendingUp className="w-3.5 h-3.5 text-[#DC2626]" />;
  } else if (key.includes("vendor")) {
    name = "Vendor Risk";
    icon = <Building2 className="w-3.5 h-3.5 text-[#7C3AED]" />;
  }

  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-800">
      {icon}
      <span>{name}</span>
    </span>
  );
}
