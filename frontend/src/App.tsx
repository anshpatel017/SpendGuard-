import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";

import { useHealth } from "./api/hooks";
import { DatasetBanner } from "./components/DatasetBanner";
import { CasePage } from "./pages/CasePage";
import { DataPage } from "./pages/DataPage";
import { DemoPage } from "./pages/DemoPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { QueuePage } from "./pages/QueuePage";
import { RunsPage } from "./pages/RunsPage";

function HealthIndicator() {
  const { data: health } = useHealth();
  const [open, setOpen] = useState(false);

  if (!health) return null;

  const isOk = health.status === "ok";

  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        className="chip outline small"
        style={{
          cursor: "pointer",
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          borderColor: isOk ? "var(--color-ok, #15803d)" : "var(--color-warn, #b45309)",
        }}
        onClick={() => setOpen(!open)}
        title="View System Health status"
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            backgroundColor: isOk ? "var(--color-ok, #15803d)" : "var(--color-warn, #b45309)",
          }}
        />
        <span>{isOk ? "System Healthy" : "System Degraded"}</span>
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            right: 0,
            top: "100%",
            marginTop: 6,
            zIndex: 100,
            background: "var(--card-bg, #ffffff)",
            border: "1px solid var(--border, #e2e8f0)",
            boxShadow: "0 4px 16px rgba(0,0,0,0.1)",
            borderRadius: 6,
            padding: 12,
            minWidth: 260,
          }}
        >
          <div className="small bold" style={{ marginBottom: 8 }}>
            SpendGuard System Health
          </div>
          <div className="stack" style={{ gap: 6, fontSize: "0.85rem" }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="muted">DuckDB Store:</span>
              <span className={health.duckdb ? "ok" : "bad"}>{health.duckdb ? "✓ Online" : "✗ Offline"}</span>
            </div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="muted">Case Store (SQLite):</span>
              <span className={health.case_store ? "ok" : "bad"}>{health.case_store ? "✓ Online" : "✗ Offline"}</span>
            </div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="muted">AI Provider:</span>
              <span className={health.llm_configured ? "ok" : "muted"}>
                {health.llm_configured ? `✓ ${health.llm_model ?? "Configured"}` : "Unconfigured"}
              </span>
            </div>
          </div>
          <button
            type="button"
            className="btn small"
            style={{ width: "100%", marginTop: 10 }}
            onClick={() => setOpen(false)}
          >
            Close
          </button>
        </div>
      )}
    </div>
  );
}

export function App() {
  return (
    <>
      <header className="topbar">
        <span className="brand">
          Spend<span>Guard</span>
        </span>
        <nav className="nav">
          <NavLink to="/" end>
            Case queue
          </NavLink>
          <NavLink to="/data">Data explorer</NavLink>
          <NavLink to="/runs">Pipeline runs</NavLink>
          <NavLink to="/evaluation">Evaluation</NavLink>
          <NavLink to="/demo">Live demo</NavLink>
        </nav>
        <span className="spacer" />
        <HealthIndicator />
        <a className="small" href="/docs" target="_blank" rel="noreferrer" style={{ marginLeft: 8 }}>
          API docs
        </a>
      </header>
      <main className="page stack">
        <DatasetBanner />
        <Routes>
          <Route path="/" element={<QueuePage />} />
          <Route path="/data" element={<DataPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/cases/:caseId" element={<CasePage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
          <Route path="/demo" element={<DemoPage />} />
          <Route
            path="*"
            element={
              <div className="empty">
                Nothing here. <NavLink to="/">Back to the case queue</NavLink>.
              </div>
            }
          />
        </Routes>
      </main>
    </>
  );
}

