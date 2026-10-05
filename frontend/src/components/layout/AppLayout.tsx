import { useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { useCases } from "../../api/hooks";

interface AppLayoutProps {
  children: ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const location = useLocation();
  const currentPath = location.pathname;
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem("spendguard_sidebar_collapsed") === "true";
    } catch {
      return false;
    }
  });

  const { data: casesData } = useCases({ page_size: 1 });
  const openCasesCount = casesData?.total || 0;

  const toggleSidebarCollapse = () => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("spendguard_sidebar_collapsed", String(next));
      } catch {}
      return next;
    });
  };

  // If on /landing, render marketing layout without sidebar
  if (currentPath === "/landing") {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex flex-col font-sans text-slate-800">
        <main className="flex-1">{children}</main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] flex font-sans text-slate-800 antialiased">
      {/* Sidebar */}
      <Sidebar
        mobileOpen={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
        collapsed={sidebarCollapsed}
        onToggleCollapse={toggleSidebarCollapse}
        openCasesCount={openCasesCount}
      />

      {/* Main Content Area */}
      <div
        className={`flex-1 flex flex-col min-w-0 transition-all duration-300 ease-in-out ${
          sidebarCollapsed ? "lg:pl-16" : "lg:pl-64"
        }`}
      >
        <Header
          onOpenMobileSidebar={() => setMobileSidebarOpen(true)}
          sidebarCollapsed={sidebarCollapsed}
          onToggleCollapse={toggleSidebarCollapse}
        />

        <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-[1600px] w-full mx-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
