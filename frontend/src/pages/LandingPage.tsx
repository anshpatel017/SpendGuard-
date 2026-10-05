import {
  ArrowRight,
  ChevronRight,
  Copy,
  FileCheck2,
  Scale,
  Scissors,
  Search,
  ShieldAlert,
  TrendingUp,
  Building2,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import InvestigationArchitectureFlow from "../components/landing/InvestigationArchitectureFlow";
import LineWaves from "../components/landing/LineWaves";

export function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="bg-[#F8FAFC] text-slate-800 font-sans selection:bg-cyan-100 selection:text-cyan-900 min-h-screen">
      {/* 1. Marketing Header */}
      <header className="sticky top-0 z-30 bg-white/95 backdrop-blur-md border-b border-[#E2E8F0] px-6 lg:px-12 py-3.5 flex items-center justify-between">
        {/* Zone 1: Single text element wordmark */}
        <Link to="/landing" className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-lg bg-black flex items-center justify-center font-bold text-white shadow-xs group-hover:bg-neutral-800 transition-colors">
            <ShieldAlert className="w-4 h-4 text-white" />
          </div>
          <span className="text-lg font-bold tracking-tight text-black">
            SpendGuard
          </span>
        </Link>

        {/* Zone 2: Navigation links */}
        <nav className="hidden md:flex items-center gap-7 text-xs font-medium text-slate-600">
          <a href="#flow" className="hover:text-slate-900 transition-colors">Workflow</a>
          <a href="#detectors" className="hover:text-slate-900 transition-colors">Detectors</a>
          <a href="#trust" className="hover:text-slate-900 transition-colors">Architecture</a>
          <Link to="/evaluation" className="hover:text-slate-900 transition-colors">Evaluation Benchmarks</Link>
          <Link to="/demo" className="hover:text-slate-900 transition-colors">Interactive Sandbox</Link>
        </nav>

        {/* Zone 3: Primary action button */}
        <div className="flex items-center gap-3">
          <Link
            to="/demo"
            className="hidden sm:inline-flex px-3.5 py-1.5 text-xs font-medium text-slate-700 hover:text-slate-900 border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
          >
            Try Demo
          </Link>
          <button
            onClick={() => navigate("/")}
            className="px-4 py-2 text-xs font-semibold text-white bg-black hover:bg-neutral-800 rounded-lg transition-colors shadow-xs flex items-center gap-1.5"
          >
            <span>Open Dashboard</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </header>

      {/* 2. Hero Section with LineWaves Background Effect */}
      <section className="relative w-full overflow-hidden border-b border-slate-200 bg-white">
        <div style={{ width: "100%", height: "600px", position: "relative" }}>
          <LineWaves
            speed={0.3}
            innerLineCount={32}
            outerLineCount={36}
            warpIntensity={1}
            rotation={-45}
            edgeFadeWidth={0}
            colorCycleSpeed={1}
            brightness={0.2}
            color1="#000000"
            color2="#000000"
            color3="#000000"
            enableMouseInteraction
            mouseInfluence={2}
            lightMode={true}
          />

          {/* Hero Content overlaid on LineWaves background */}
          <div className="absolute inset-0 flex flex-col items-center justify-center px-4 sm:px-6 lg:px-12 text-center pointer-events-none z-10">
            <div className="pointer-events-auto max-w-3xl mx-auto rounded-3xl p-7 sm:p-11 bg-white/55 backdrop-blur-xl backdrop-saturate-150 border border-white/80 shadow-[0_20px_50px_rgba(0,0,0,0.08),0_1px_3px_rgba(0,0,0,0.04),inset_0_1px_1px_rgba(255,255,255,0.9)]">
              <div className="inline-flex items-center gap-2 px-3.5 py-1 rounded-full bg-white/70 backdrop-blur-md border border-white/80 text-black text-xs font-semibold mb-6 shadow-[0_2px_8px_rgba(0,0,0,0.04),inset_0_1px_0_rgba(255,255,255,0.9)]">
                <ShieldAlert className="w-3.5 h-3.5 text-black" />
                <span>Procurement Intelligence & Integrity Platform</span>
              </div>

              <h1 className="text-3xl sm:text-5xl font-extrabold text-black tracking-tight leading-[1.15] max-w-2xl mx-auto text-balance">
                AI-Assisted Procurement Anomaly Detection
              </h1>

              <p className="mt-4 sm:mt-5 text-base sm:text-lg text-neutral-800 max-w-2xl mx-auto leading-relaxed font-medium">
                Detect suspicious procurement patterns, investigate them with grounded evidence,
                verify AI-generated findings, and keep the final decision in human hands.
              </p>

              <div className="mt-7 sm:mt-8 flex flex-wrap items-center justify-center gap-4">
                <button
                  onClick={() => navigate("/")}
                  className="px-6 py-3 text-sm font-semibold text-white bg-black hover:bg-neutral-800 rounded-xl shadow-md hover:shadow-lg transition-all flex items-center gap-2"
                >
                  <span>Open Investigation Dashboard</span>
                  <ArrowRight className="w-4 h-4" />
                </button>

                <button
                  onClick={() => navigate("/demo")}
                  className="px-6 py-3 text-sm font-semibold text-black bg-white/70 hover:bg-white/90 backdrop-blur-md border border-white/80 rounded-xl shadow-[0_2px_8px_rgba(0,0,0,0.04),inset_0_1px_0_rgba(255,255,255,0.9)] transition-all flex items-center gap-2"
                >
                  <span>Try Interactive Demo</span>
                  <ChevronRight className="w-4 h-4 text-neutral-600" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 3. Hero Visual: End-to-End Investigation Architecture */}
      <section id="flow" className="w-full bg-white border-y border-slate-200">
        <InvestigationArchitectureFlow />
      </section>

      {/* 4. Feature Cards Section */}
      <section id="features" className="py-16 px-6 lg:px-12 bg-white border-y border-slate-200">
        <div className="max-w-6xl mx-auto">
          <div className="text-center max-w-2xl mx-auto mb-12">
            <span className="text-xs font-semibold uppercase tracking-wider text-black">
              Operational Pillars
            </span>
            <h2 className="text-2xl sm:text-3xl font-bold text-slate-900 mt-2">
              Engineered for Compliance Integrity
            </h2>
            <p className="text-sm text-slate-600 mt-2">
              Every component adheres to rigorous auditability standards required by financial controllers.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {/* 01 Detect */}
            <div className="p-6 rounded-xl border border-slate-200 bg-[#F8FAFC]">
              <div className="text-xs font-mono font-bold text-cyan-700">01 — Detect</div>
              <h3 className="text-base font-bold text-slate-900 mt-2">Deterministic Anomaly Detectors</h3>
              <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                Deterministic anomaly detectors identify suspicious procurement patterns using rigorous mathematical rules rather than unconstrained generation.
              </p>
              <div className="mt-4 pt-3 border-t border-slate-200/80 text-[11px] text-slate-500">
                Signals: Threshold avoidance, date proximity, SKU deviations
              </div>
            </div>

            {/* 02 Investigate */}
            <div className="p-6 rounded-xl border border-slate-200 bg-[#F8FAFC]">
              <div className="text-xs font-mono font-bold text-indigo-700">02 — Investigate</div>
              <h3 className="text-base font-bold text-slate-900 mt-2">Structured Tool Agent</h3>
              <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                The AI investigator uses structured, read-only tools to examine transactions, vendors, policies, and similar invoices without write access.
              </p>
              <div className="mt-4 pt-3 border-t border-slate-200/80 text-[11px] text-slate-500">
                Tools: Query DB, Levenshtein, policy matcher, calculators
              </div>
            </div>

            {/* 03 Verify */}
            <div className="p-6 rounded-xl border border-slate-200 bg-[#F8FAFC]">
              <div className="text-xs font-mono font-bold text-emerald-700">03 — Verify</div>
              <h3 className="text-base font-bold text-slate-900 mt-2">Independent Verification Layer</h3>
              <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                AI findings are checked against evidence and policy references before being presented as verified. Unsubstantiated claims are flagged or rejected.
              </p>
              <div className="mt-4 pt-3 border-t border-slate-200/80 text-[11px] text-slate-500">
                Checks: Row existence, numerical parity, active policy
              </div>
            </div>

            {/* 04 Review */}
            <div className="p-6 rounded-xl border border-slate-200 bg-[#F8FAFC]">
              <div className="text-xs font-mono font-bold text-slate-800">04 — Review</div>
              <h3 className="text-base font-bold text-slate-900 mt-2">Human-in-the-Loop Decision</h3>
              <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                A human reviewer confirms or dismisses the case. The AI never changes the final legal or compliance status of an employee or supplier.
              </p>
              <div className="mt-4 pt-3 border-t border-slate-200/80 text-[11px] text-slate-500">
                Outcomes: Confirm fraud, dismiss false positive, escalate
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 5. Trust Section */}
      <section id="trust" className="py-16 px-6 lg:px-12 max-w-6xl mx-auto">
        <div className="text-center max-w-3xl mx-auto mb-12">
          <span className="text-xs font-semibold uppercase tracking-wider text-black">
            Core Philosophy
          </span>
          <h2 className="text-2xl sm:text-4xl font-extrabold text-black mt-2">
            AI recommends. Evidence verifies. Humans decide.
          </h2>
          <p className="text-sm text-slate-600 mt-2">
            SpendGuard explicitly enforces boundaries between automated detection, AI analysis, mathematical verification, and human authority.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="p-6 rounded-xl bg-white border border-slate-200 shadow-xs">
            <div className="w-10 h-10 rounded-lg bg-neutral-100 flex items-center justify-center text-black mb-4">
              <Search className="w-5 h-5" />
            </div>
            <h3 className="text-base font-bold text-slate-900">Deterministic Detection</h3>
            <p className="text-xs text-slate-600 mt-2 leading-relaxed">
              Anomaly detection relies on reproducible algorithms—MAD robust z-scores, temporal clustering, and Levenshtein token distances—with ground-truth benchmarks.
            </p>
          </div>

          <div className="p-6 rounded-xl bg-white border border-slate-200 shadow-xs">
            <div className="w-10 h-10 rounded-lg bg-emerald-50 flex items-center justify-center text-emerald-600 mb-4">
              <FileCheck2 className="w-5 h-5" />
            </div>
            <h3 className="text-base font-bold text-slate-900">Evidence-Backed AI</h3>
            <p className="text-xs text-slate-600 mt-2 leading-relaxed">
              Every assertion made during an investigation is mapped to specific primary source rows. The AI cannot make unverifiable assumptions or generalize without citations.
            </p>
          </div>

          <div className="p-6 rounded-xl bg-white border border-slate-200 shadow-xs">
            <div className="w-10 h-10 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600 mb-4">
              <Scale className="w-5 h-5" />
            </div>
            <h3 className="text-base font-bold text-slate-900">Human-in-the-Loop</h3>
            <p className="text-xs text-slate-600 mt-2 leading-relaxed">
              Compliance officers maintain ultimate decision rights. All confirmations, dismissals, and audit memos are recorded with human attribution and timestamps.
            </p>
          </div>
        </div>
      </section>

      {/* 6. Detector Section */}
      <section id="detectors" className="py-16 px-6 lg:px-12 bg-slate-50 border-y border-slate-200">
        <div className="max-w-6xl mx-auto">
          <div className="flex flex-col md:flex-row md:items-end justify-between mb-10">
            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-black">
                Core Detector Suite
              </span>
              <h2 className="text-2xl sm:text-3xl font-bold text-black mt-1">
                Active Anomaly Detectors
              </h2>
            </div>
            <Link
              to="/evaluation"
              className="mt-3 md:mt-0 text-xs font-semibold text-black hover:text-neutral-700 flex items-center gap-1"
            >
              <span>View full benchmark matrix</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Detector 1: Duplicate Purchases */}
            <div className="p-5 bg-white rounded-xl border border-slate-200 shadow-xs">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="w-9 h-9 rounded-lg bg-neutral-100 text-black flex items-center justify-center">
                    <Copy className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">Duplicate Purchases</h3>
                    <span className="text-[11px] font-medium text-slate-500">Detector #DET-01</span>
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-red-50 text-red-700 border border-red-200">
                  Critical Risk
                </span>
              </div>
              <p className="text-xs text-slate-600 mt-3 leading-relaxed">
                Flags duplicate invoices or identical charges disbursed through dual channels (such as automated ACH and corporate purchasing cards) within a sliding time window.
              </p>
              <div className="mt-4 p-2.5 rounded bg-slate-50 border border-slate-200 text-xs font-mono text-slate-700">
                <span className="text-slate-400">Signal:</span> Exact amount match with suffix &apos;-R&apos; within 34h
              </div>
            </div>

            {/* Detector 2: Split Purchases */}
            <div className="p-5 bg-white rounded-xl border border-slate-200 shadow-xs">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="w-9 h-9 rounded-lg bg-amber-50 text-amber-700 flex items-center justify-center">
                    <Scissors className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">Split Purchases</h3>
                    <span className="text-[11px] font-medium text-slate-500">Detector #DET-02</span>
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-50 text-amber-800 border border-amber-200">
                  Policy Violation
                </span>
              </div>
              <p className="text-xs text-slate-600 mt-3 leading-relaxed">
                Identifies sequential requisitions issued right below statutory single-signature caps by the same purchasing officer to avoid competitive bids.
              </p>
              <div className="mt-4 p-2.5 rounded bg-slate-50 border border-slate-200 text-xs font-mono text-slate-700">
                <span className="text-slate-400">Signal:</span> Multiple orders right below single-signature limit in close proximity
              </div>
            </div>

            {/* Detector 3: Price Inflation */}
            <div className="p-5 bg-white rounded-xl border border-slate-200 shadow-xs">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="w-9 h-9 rounded-lg bg-rose-50 text-rose-700 flex items-center justify-center">
                    <TrendingUp className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">Price Inflation</h3>
                    <span className="text-[11px] font-medium text-slate-500">Detector #DET-03</span>
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-orange-50 text-orange-800 border border-orange-200">
                  Statistical Outlier
                </span>
              </div>
              <p className="text-xs text-slate-600 mt-3 leading-relaxed">
                Computes robust median absolute deviation (MAD) benchmarks across historical catalog SKUs to isolate transactions where unit pricing wildly exceeds peer averages.
              </p>
              <div className="mt-4 p-2.5 rounded bg-slate-50 border border-slate-200 text-xs font-mono text-slate-700">
                <span className="text-slate-400">Signal:</span> Unit price deviation with robust z-score &gt; 3.0 vs catalog peer median
              </div>
            </div>

            {/* Detector 4: Vendor Risk */}
            <div className="p-5 bg-white rounded-xl border border-slate-200 shadow-xs">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="w-9 h-9 rounded-lg bg-purple-50 text-purple-700 flex items-center justify-center">
                    <Building2 className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">Vendor Risk</h3>
                    <span className="text-[11px] font-medium text-slate-500">Detector #DET-04</span>
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-red-50 text-red-700 border border-red-200">
                  Integrity Threat
                </span>
              </div>
              <p className="text-xs text-slate-600 mt-3 leading-relaxed">
                Detects newly formed shell corporations, abrupt routing changes immediately prior to invoice disbursement, and employee residential address overlaps.
              </p>
              <div className="mt-4 p-2.5 rounded bg-slate-50 border border-slate-200 text-xs font-mono text-slate-700">
                <span className="text-slate-400">Signal:</span> Recently formed vendor entity; high-value retainer without competitive RFP
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 7. CTA Section */}
      <section className="bg-black text-white py-16 px-6 lg:px-12 text-center border-t border-neutral-900">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-2xl sm:text-4xl font-bold tracking-tight">
            Ready to investigate procurement risk?
          </h2>
          <p className="mt-3 text-slate-300 text-sm sm:text-base leading-relaxed">
            Examine active anomaly queues, inspect ground-truth citations, or test detectors in the interactive sandbox.
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <button
              onClick={() => navigate("/")}
              className="px-6 py-3 text-sm font-semibold text-white bg-black hover:bg-neutral-800 rounded-lg transition-colors shadow-sm flex items-center gap-2 border border-neutral-700"
            >
              <span>Open SpendGuard</span>
              <ArrowRight className="w-4 h-4" />
            </button>

            <button
              onClick={() => navigate("/demo")}
              className="px-6 py-3 text-sm font-semibold text-white bg-neutral-900 hover:bg-neutral-800 border border-neutral-700 rounded-lg transition-colors"
            >
              Try Interactive Sandbox
            </button>
          </div>
        </div>
      </section>

      {/* 8. Footer */}
      <footer className="bg-white border-t border-slate-200 py-10 px-6 lg:px-12 text-xs text-slate-500">
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-black flex items-center justify-center text-white font-bold text-xs">
              <ShieldAlert className="w-3.5 h-3.5" />
            </div>
            <span className="font-bold text-slate-900">SpendGuard</span>
            <span className="text-slate-300">|</span>
            <span>Procurement Anomaly Investigation Platform</span>
          </div>

          <div className="flex flex-wrap items-center gap-6 font-medium text-slate-600">
            <Link to="/" className="hover:text-slate-900 transition-colors">Dashboard</Link>
            <Link to="/demo" className="hover:text-slate-900 transition-colors">Demo</Link>
            <Link to="/evaluation" className="hover:text-slate-900 transition-colors">Evaluation</Link>
            <Link to="/data" className="hover:text-slate-900 transition-colors">Data Explorer</Link>
            <Link to="/runs" className="hover:text-slate-900 transition-colors">Pipeline Runs</Link>
            <Link to="/health" className="hover:text-slate-900 transition-colors">Health</Link>
          </div>

          <div className="text-[11px] text-slate-400">
            Release v1.0.0 (Semester Review Edition)
          </div>
        </div>
      </footer>
    </div>
  );
}
