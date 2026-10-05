import { NavLink, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/layout/AppLayout";
import { ToastProvider } from "./context/ToastContext";
import { CasePage } from "./pages/CasePage";
import { DataPage } from "./pages/DataPage";
import { DemoPage } from "./pages/DemoPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { HealthPage } from "./pages/HealthPage";
import { LandingPage } from "./pages/LandingPage";
import { QueuePage } from "./pages/QueuePage";
import { RunsPage } from "./pages/RunsPage";

export function App() {
  return (
    <ToastProvider>
      <AppLayout>
        <Routes>
          <Route path="/" element={<QueuePage />} />
          <Route path="/landing" element={<LandingPage />} />
          <Route path="/cases/:caseId" element={<CasePage />} />
          <Route path="/data" element={<DataPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
          <Route path="/demo" element={<DemoPage />} />
          <Route path="/health" element={<HealthPage />} />
          <Route
            path="*"
            element={
              <div className="p-12 text-center bg-white rounded-xl border border-slate-200 shadow-xs max-w-md mx-auto my-12">
                <h3 className="text-base font-bold text-slate-900">Page Not Found</h3>
                <p className="text-xs text-slate-500 mt-1">
                  The requested page does not exist in SpendGuard.
                </p>
                <div className="mt-4">
                  <NavLink
                    to="/"
                    className="inline-flex px-3.5 py-1.5 text-xs font-semibold text-white bg-black hover:bg-neutral-800 rounded-md transition-colors"
                  >
                    Back to Queue
                  </NavLink>
                </div>
              </div>
            }
          />
        </Routes>
      </AppLayout>
    </ToastProvider>
  );
}
