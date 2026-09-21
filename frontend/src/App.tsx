import { NavLink, Route, Routes } from "react-router-dom";

import { DatasetBanner } from "./components/DatasetBanner";
import { CasePage } from "./pages/CasePage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { QueuePage } from "./pages/QueuePage";

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
          <NavLink to="/evaluation">Evaluation</NavLink>
        </nav>
        <span className="spacer" />
        <a className="small" href="/docs" target="_blank" rel="noreferrer">
          API docs
        </a>
      </header>
      <main className="page stack">
        <DatasetBanner />
        <Routes>
          <Route path="/" element={<QueuePage />} />
          <Route path="/cases/:caseId" element={<CasePage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
          <Route path="*" element={<div className="empty">Nothing here. <NavLink to="/">Back to the case queue</NavLink>.</div>} />
        </Routes>
      </main>
    </>
  );
}
