import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  ShieldAlert,
  BarChart3,
  FlaskConical,
  Database,
  Activity,
  HeartPulse,
  ExternalLink,
  ChevronRight,
  ChevronLeft,
} from "lucide-react";
import { useHealth } from "../../api/hooks";

interface SidebarProps {
  mobileOpen?: boolean;
  onCloseMobile?: () => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  openCasesCount?: number;
}

export function Sidebar({
  mobileOpen,
  onCloseMobile,
  collapsed = false,
  onToggleCollapse,
  openCasesCount = 0,
}: SidebarProps) {
  const location = useLocation();
  const currentPath = location.pathname;
  const { data: health } = useHealth();

  const isHealthy = health?.status === "ok";

  const navItems = [
    {
      name: "Overview & Queue",
      path: "/",
      icon: LayoutDashboard,
      badge: openCasesCount > 0 ? `${openCasesCount}` : undefined,
    },
    {
      name: "Data Explorer",
      path: "/data",
      icon: Database,
    },
    {
      name: "Pipeline Runs",
      path: "/runs",
      icon: Activity,
    },
    {
      name: "Evaluation",
      path: "/evaluation",
      icon: BarChart3,
    },
    {
      name: "Interactive Demo",
      path: "/demo",
      icon: FlaskConical,
    },
    {
      name: "System Health",
      path: "/health",
      icon: HeartPulse,
    },
  ];

  return (
    <>
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-900/60 lg:hidden"
          onClick={onCloseMobile}
        />
      )}

      <aside
        className={`fixed top-0 bottom-0 left-0 z-40 ${
          collapsed ? "w-16" : "w-64"
        } bg-white text-slate-800 flex flex-col justify-between transition-all duration-300 ease-in-out lg:translate-x-0 ${
          mobileOpen ? "translate-x-0 w-64" : "-translate-x-full lg:translate-x-0"
        } border-r border-[#E2E8F0] shadow-xs`}
      >
        {/* Top: Brand Header */}
        <div>
          <div
            className={`h-16 flex items-center border-b border-[#E2E8F0] bg-white transition-all ${
              collapsed ? "justify-center px-2" : "justify-between px-4"
            }`}
          >
            {collapsed ? (
              <button
                type="button"
                onClick={onToggleCollapse}
                className="w-10 h-10 rounded-lg bg-black flex items-center justify-center font-bold text-white shadow-xs hover:bg-neutral-800 transition-all group"
                title="Expand sidebar"
                aria-label="Expand sidebar"
              >
                <ShieldAlert className="w-5 h-5 text-white group-hover:scale-110 transition-transform" />
              </button>
            ) : (
              <>
                <Link to="/" className="flex items-center gap-2.5 group overflow-hidden">
                  <div className="w-8 h-8 rounded-lg bg-black flex items-center justify-center font-bold text-white shadow-xs group-hover:bg-neutral-800 transition-colors shrink-0">
                    <ShieldAlert className="w-4 h-4 text-white" />
                  </div>
                  <div className="overflow-hidden">
                    <span className="text-base font-bold tracking-tight text-slate-900 flex items-center gap-1.5 truncate">
                      SpendGuard
                    </span>
                    <p className="text-[11px] font-semibold text-slate-500 tracking-wide uppercase truncate">
                      Procurement Intelligence
                    </p>
                  </div>
                </Link>

                {onToggleCollapse && (
                  <button
                    type="button"
                    onClick={onToggleCollapse}
                    className="p-1.5 text-slate-400 hover:text-slate-900 hover:bg-slate-100 rounded-md transition-colors"
                    title="Collapse sidebar"
                    aria-label="Collapse sidebar"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                )}
              </>
            )}
          </div>

          {/* Navigation Links */}
          <nav className="p-2 space-y-1">
            {!collapsed && (
              <div className="px-3 pt-3 pb-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                Investigation Platform
              </div>
            )}

            {navItems.map((item) => {
              const isActive =
                item.path === "/"
                  ? currentPath === "/" || currentPath.startsWith("/cases")
                  : currentPath.startsWith(item.path);

              const Icon = item.icon;

              return (
                <Link
                  key={item.path}
                  to={item.path}
                  onClick={onCloseMobile}
                  className={`group relative flex items-center ${
                    collapsed ? "justify-center p-2.5" : "justify-between px-3 py-2"
                  } text-xs font-medium rounded-lg transition-colors ${
                    isActive
                      ? "bg-slate-100 text-black border border-slate-200/80 shadow-2xs font-semibold"
                      : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                  title={collapsed ? item.name : undefined}
                >
                  <div className={`flex items-center ${collapsed ? "justify-center" : "gap-3"}`}>
                    <Icon
                      className={`w-4 h-4 shrink-0 ${
                        isActive ? "text-black" : "text-slate-400 group-hover:text-slate-700"
                      }`}
                    />
                    {!collapsed && <span>{item.name}</span>}
                  </div>

                  {collapsed && item.badge && (
                    <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-black ring-2 ring-white" />
                  )}

                  {!collapsed && item.badge && (
                    <span className="px-1.5 py-0.2 text-[10px] font-bold rounded bg-slate-200 text-slate-900 border border-slate-300 tabular-nums">
                      {item.badge}
                    </span>
                  )}

                  {/* Collapsed floating tooltip */}
                  {collapsed && (
                    <div className="absolute left-full ml-3 px-2.5 py-1.5 bg-slate-900 text-white text-xs rounded-md shadow-xl border border-slate-700 whitespace-nowrap z-50 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-2">
                      <span className="font-semibold">{item.name}</span>
                      {item.badge && (
                        <span className="px-1.5 py-0.5 text-[10px] font-mono bg-neutral-800 rounded border border-neutral-700 text-cyan-300 font-bold">
                          {item.badge}
                        </span>
                      )}
                    </div>
                  )}
                </Link>
              );
            })}

            {!collapsed && (
              <div className="pt-4 pb-1 px-3 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                External & Showcase
              </div>
            )}

            <Link
              to="/landing"
              onClick={onCloseMobile}
              className={`group relative flex items-center ${
                collapsed ? "justify-center p-2.5" : "justify-between px-3 py-2"
              } text-xs font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 rounded-lg transition-colors ${
                collapsed ? "mt-3" : ""
              }`}
              title={collapsed ? "Product Landing Page" : undefined}
            >
              <div className={`flex items-center ${collapsed ? "justify-center" : "gap-3"}`}>
                <ExternalLink className="w-4 h-4 text-slate-400 group-hover:text-slate-700 shrink-0" />
                {!collapsed && <span>Product Landing Page</span>}
              </div>
              {!collapsed && (
                <ChevronRight className="w-3.5 h-3.5 text-slate-400 group-hover:text-slate-600" />
              )}

              {collapsed && (
                <div className="absolute left-full ml-3 px-2.5 py-1.5 bg-slate-900 text-white text-xs rounded-md shadow-xl border border-slate-700 whitespace-nowrap z-50 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1.5">
                  <span className="font-semibold">Product Landing Page</span>
                  <ExternalLink className="w-3 h-3 text-neutral-400" />
                </div>
              )}
            </Link>
          </nav>
        </div>

        {/* Bottom Sidebar: System Status */}
        {collapsed ? (
          <div className="p-3 border-t border-[#E2E8F0] bg-slate-50/70 flex flex-col items-center gap-2 group relative">
            <Link
              to="/health"
              className="p-2 rounded-lg hover:bg-slate-100 transition-colors"
              title={isHealthy ? "System Operational" : "System Degraded"}
            >
              <span className="relative flex h-2.5 w-2.5">
                <span
                  className={`animate-ping absolute inline-flex h-full w-full rounded-full ${
                    isHealthy ? "bg-emerald-400" : "bg-amber-400"
                  } opacity-75`}
                />
                <span
                  className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
                    isHealthy ? "bg-emerald-500" : "bg-amber-500"
                  }`}
                />
              </span>
            </Link>

            <div className="absolute left-full bottom-3 ml-3 px-3 py-2 bg-slate-900 text-white text-xs rounded-md shadow-xl border border-slate-700 whitespace-nowrap z-50 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity">
              <div
                className={`font-bold flex items-center gap-1.5 ${
                  isHealthy ? "text-emerald-400" : "text-amber-400"
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full inline-block ${
                    isHealthy ? "bg-emerald-400" : "bg-amber-400"
                  }`}
                />
                {isHealthy ? "System Operational" : "System Degraded"}
              </div>
              <div className="text-[10px] text-neutral-400 mt-1 font-mono">
                Store: {health?.duckdb ? "DuckDB Online" : "Offline"}
              </div>
            </div>
          </div>
        ) : (
          <div className="p-4 border-t border-[#E2E8F0] bg-slate-50/70">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="relative flex h-2 w-2">
                  <span
                    className={`animate-ping absolute inline-flex h-full w-full rounded-full ${
                      isHealthy ? "bg-emerald-400" : "bg-amber-400"
                    } opacity-75`}
                  />
                  <span
                    className={`relative inline-flex rounded-full h-2 w-2 ${
                      isHealthy ? "bg-emerald-500" : "bg-amber-500"
                    }`}
                  />
                </span>
                <span className="text-xs font-semibold text-slate-800">
                  {isHealthy ? "System Operational" : "System Degraded"}
                </span>
              </div>
              <Link
                to="/health"
                className="text-[11px] text-slate-500 hover:text-slate-900 font-medium transition-colors"
              >
                Health
              </Link>
            </div>
            <div className="mt-2 text-[11px] text-slate-500 flex items-center justify-between">
              <span>Case Store:</span>
              <span className="font-mono text-slate-800 text-[10px] bg-white px-1.5 py-0.5 rounded border border-slate-200 shadow-2xs">
                {health?.case_store ? "SQLite Connected" : "Unavailable"}
              </span>
            </div>
          </div>
        )}
      </aside>
    </>
  );
}
