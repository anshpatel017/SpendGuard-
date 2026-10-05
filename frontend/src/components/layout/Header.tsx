import { Link, useLocation } from "react-router-dom";
import { Menu, PanelLeft, Database, ExternalLink, RefreshCw } from "lucide-react";
import { useHealth, useMetrics } from "../../api/hooks";
import { useToast } from "../../context/ToastContext";

interface HeaderProps {
  onOpenMobileSidebar: () => void;
  sidebarCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

export function Header({
  onOpenMobileSidebar,
  sidebarCollapsed,
  onToggleCollapse,
}: HeaderProps) {
  const location = useLocation();
  const currentPath = location.pathname;
  const { data: health } = useHealth();
  const { data: metrics, refetch: refetchMetrics } = useMetrics();
  const { showToast } = useToast();

  let breadcrumb = "SpendGuard";
  let pageTitle = "Investigation Queue";

  if (currentPath === "/dashboard" || currentPath === "/queue" || currentPath === "/") {
    breadcrumb = "Operations";
    pageTitle = "Investigation Queue";
  } else if (currentPath.startsWith("/cases")) {
    breadcrumb = "Investigation Queue";
    const parts = currentPath.split("/");
    const id = parts[2] ? `${parts[2].slice(0, 8)}…` : "Detail";
    pageTitle = `Case ${id}`;
  } else if (currentPath === "/evaluation") {
    breadcrumb = "Analytics";
    pageTitle = "Detection Evaluation";
  } else if (currentPath === "/demo") {
    breadcrumb = "Sandbox";
    pageTitle = "Interactive Anomaly Demo";
  } else if (currentPath === "/data") {
    breadcrumb = "Data Lake";
    pageTitle = "Data Explorer";
  } else if (currentPath === "/runs") {
    breadcrumb = "Pipeline";
    pageTitle = "Pipeline Runs History";
  } else if (currentPath === "/health") {
    breadcrumb = "Infrastructure";
    pageTitle = "System Health Status";
  }

  const isHealthy = health?.status === "ok";

  const handleRefresh = async () => {
    await refetchMetrics();
    showToast("Refreshed system metrics and case queue telemetry", "info");
  };

  return (
    <header className="sticky top-0 z-30 h-16 bg-white border-b border-[#E2E8F0] px-4 sm:px-6 flex items-center justify-between shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
      {/* Left side: Mobile menu toggle + Desktop sidebar toggle + Breadcrumbs & Title */}
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenMobileSidebar}
          className="lg:hidden p-1.5 -ml-1 text-slate-600 hover:text-slate-900 rounded-md hover:bg-slate-100"
          aria-label="Toggle mobile menu"
        >
          <Menu className="w-5 h-5" />
        </button>

        {onToggleCollapse && (
          <button
            onClick={onToggleCollapse}
            className="hidden lg:flex p-1.5 -ml-1 text-slate-500 hover:text-slate-900 rounded-md hover:bg-slate-100 transition-colors"
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <PanelLeft className="w-4 h-4" />
          </button>
        )}

        <div className="flex flex-col">
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <Link to="/dashboard" className="hover:text-slate-900 transition-colors">
              {breadcrumb}
            </Link>
            <span className="text-slate-300">/</span>
            <span className="text-slate-700 font-medium">{pageTitle}</span>
          </div>
          <h1 className="text-base sm:text-lg font-bold text-[#0F172A] tracking-tight leading-tight">
            {pageTitle}
          </h1>
        </div>
      </div>

      {/* Right side: Dataset Indicator + Health status + Refresh button */}
      <div className="flex items-center gap-2.5 sm:gap-3">
        {/* Dataset Indicator */}
        <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md bg-[#F1F5F9] border border-[#CBD5E1] text-[#334155]">
          <Database className="w-3.5 h-3.5 text-[#0E7490]" />
          <span>Dataset:</span>
          <span className="font-mono text-[11px] font-semibold text-[#0F172A]">
            {metrics?.total_transactions ? `${metrics.total_transactions} txns` : "Connected"}
          </span>
        </div>

        {/* System Health Indicator */}
        <Link
          to="/health"
          className={`hidden sm:flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md border transition-colors ${
            isHealthy
              ? "bg-emerald-50 border-emerald-200 text-emerald-800 hover:bg-emerald-100"
              : "bg-amber-50 border-amber-200 text-amber-800 hover:bg-amber-100"
          }`}
          title="View system services health"
        >
          <span
            className={`w-2 h-2 rounded-full ${
              isHealthy ? "bg-emerald-500" : "bg-amber-500"
            }`}
          />
          <span className="font-medium">{isHealthy ? "Healthy" : "Degraded"}</span>
        </Link>

        {/* Refresh button */}
        <button
          onClick={handleRefresh}
          className="p-1.5 text-slate-500 hover:text-slate-900 hover:bg-slate-100 rounded-md transition-colors"
          title="Refresh metrics and telemetry"
          aria-label="Refresh metrics"
        >
          <RefreshCw className="w-4 h-4" />
        </button>

        {/* API Docs link */}
        <a
          href="/docs"
          target="_blank"
          rel="noreferrer"
          className="hidden sm:inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-900 transition-colors ml-1"
        >
          <span>API Docs</span>
          <ExternalLink className="w-3 h-3" />
        </a>
      </div>
    </header>
  );
}
