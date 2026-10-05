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

import LineWaves from "../components/landing/LineWaves";
import InvestigationArchitectureFlow from "../components/landing/InvestigationArchitectureFlow";

export function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="bg-[#F8FAFC] text-slate-800 font-sans selection:bg-cyan-100 selection:text-cyan-900 min-h-screen">
      {/* 1. Marketing Header (Image 1) */}
      <header className="sticky top-0 z-30 bg-white/95 backdrop-blur-md border-b border-[#E2E8F0] px-6 lg:px-12 py-3.5 flex items-center justify-between">
        {/* Wordmark logo */}
        <Link to="/" className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-lg bg-black flex items-center justify-center font-bold text-white shadow-xs group-hover:bg-neutral-800 transition-colors">
            <ShieldAlert className="w-4 h-4 text-white" />
          </div>
          <span className="text-lg font-bold tracking-tight text-black">
            SpendGuard
          </span>
        </Link>

        {/* Navigation links */}
        <nav className="hidden md:flex items-center gap-8 text-xs font-medium text-slate-600">
          <a href="#workflow" className="hover:text-slate-900 transition-colors">Workflow</a>
          <a href="#detectors" className="hover:text-slate-900 transition-colors">Detectors</a>
          <a href="#architecture" className="hover:text-slate-900 transition-colors">Architecture</a>
          <Link to="/evaluation" className="hover:text-slate-900 transition-colors">Evaluation Benchmarks</Link>
          <Link to="/demo" className="hover:text-slate-900 transition-colors">Interactive Sandbox</Link>
        </nav>

        {/* Action buttons */}
        <div className="flex items-center gap-3">
          <Link
            to="/demo"
            className="hidden sm:inline-flex px-3.5 py-1.5 text-xs font-medium text-slate-700 hover:text-slate-900 border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
          >
            Try Demo
          </Link>
          <button
            onClick={() => navigate("/dashboard")}
            className="px-4 py-2 text-xs font-semibold text-white bg-black hover:bg-neutral-800 rounded-lg transition-colors shadow-xs flex items-center gap-1.5 cursor-pointer"
          >
            <span>Open Dashboard</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </header>

      {/* 2. Hero Section with LineWaves Background Effect (Image 1) */}
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
                  onClick={() => navigate("/dashboard")}
                  className="px-6 py-3 text-sm font-semibold text-white bg-black hover:bg-neutral-800 rounded-xl shadow-md hover:shadow-lg transition-all flex items-center gap-2 cursor-pointer"
                >
                  <span>Open Investigation Dashboard</span>
                  <ArrowRight className="w-4 h-4" />
                </button>

                <button
                  onClick={() => navigate("/demo")}
                  className="px-6 py-3 text-sm font-semibold text-black bg-white/70 hover:bg-white/90 backdrop-blur-md border border-white/80 rounded-xl shadow-[0_2px_8px_rgba(0,0,0,0.04),inset_0_1px_0_rgba(255,255,255,0.9)] transition-all flex items-center gap-2 cursor-pointer"
                >
                  <span>Try Interactive Demo</span>
                  <ChevronRight className="w-4 h-4 text-neutral-600" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 2b. Hero Visual: End-to-End Investigation Architecture with Scroll-Follow Glow Black Lines */}
      <section id="architecture" className="w-full bg-white border-y border-slate-200">
        <InvestigationArchitectureFlow />
      </section>

      {/* 3. Operational Pillars Section (Image 2) */}
      <section id="workflow" className="py-20 px-6 lg:px-12 bg-[#F8FAFC]">
        <div className="max-w-6xl mx-auto">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-800">
              OPERATIONAL PILLARS
            </span>
            <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900 mt-2">
              Engineered for Compliance Integrity
            </h2>
            <p className="text-xs sm:text-sm text-slate-600 mt-2">
              Every component adheres to rigorous auditability standards required by financial controllers.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {/* 01 Detect */}
            <div className="p-6 rounded-2xl border border-slate-200/80 bg-white/70 backdrop-blur-xs flex flex-col justify-between shadow-2xs">
              <div>
                <div className="text-xs font-mono font-bold text-cyan-600">01 — Detect</div>
                <h3 className="text-base font-bold text-slate-900 mt-2">Deterministic Anomaly Detectors</h3>
                <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                  Deterministic anomaly detectors identify suspicious procurement patterns using rigorous mathematical rules rather than unconstrained generation.
                </p>
              </div>
              <div className="mt-5 pt-3.5 border-t border-slate-200/80 text-[11px] text-slate-500">
                Signals: Threshold avoidance, date proximity, SKU deviations
              </div>
            </div>

            {/* 02 Investigate */}
            <div className="p-6 rounded-2xl border border-slate-200/80 bg-white/70 backdrop-blur-xs flex flex-col justify-between shadow-2xs">
              <div>
                <div className="text-xs font-mono font-bold text-indigo-600">02 — Investigate</div>
                <h3 className="text-base font-bold text-slate-900 mt-2">Structured Tool Agent</h3>
                <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                  The AI investigator uses structured, read-only tools to examine transactions, vendors, policies, and similar invoices without write access.
                </p>
              </div>
              <div className="mt-5 pt-3.5 border-t border-slate-200/80 text-[11px] text-slate-500">
                Tools: Query DB, Levenshtein, policy matcher, calculators
              </div>
            </div>

            {/* 03 Verify */}
            <div className="p-6 rounded-2xl border border-slate-200/80 bg-white/70 backdrop-blur-xs flex flex-col justify-between shadow-2xs">
              <div>
                <div className="text-xs font-mono font-bold text-emerald-600">03 — Verify</div>
                <h3 className="text-base font-bold text-slate-900 mt-2">Independent Verification Layer</h3>
                <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                  AI findings are checked against evidence and policy references before being presented as verified. Unsubstantiated claims are flagged or rejected.
                </p>
              </div>
              <div className="mt-5 pt-3.5 border-t border-slate-200/80 text-[11px] text-slate-500">
                Checks: Row existence, numerical parity, active policy
              </div>
            </div>

            {/* 04 Review */}
            <div className="p-6 rounded-2xl border border-slate-200/80 bg-white/70 backdrop-blur-xs flex flex-col justify-between shadow-2xs">
              <div>
                <div className="text-xs font-mono font-bold text-slate-700">04 — Review</div>
                <h3 className="text-base font-bold text-slate-900 mt-2">Human-in-the-Loop Decision</h3>
                <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                  A human reviewer confirms or dismisses the case. The AI never changes the final legal or compliance status of an employee or supplier.
                </p>
              </div>
              <div className="mt-5 pt-3.5 border-t border-slate-200/80 text-[11px] text-slate-500">
                Outcomes: Confirm fraud, dismiss false positive, escalate
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 4. Core Philosophy Section (Image 3) */}
      <section id="architecture" className="py-20 px-6 lg:px-12 bg-white border-t border-slate-200/80">
        <div className="max-w-6xl mx-auto">
          <div className="text-center max-w-3xl mx-auto mb-12">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-900">
              CORE PHILOSOPHY
            </span>
            <h2 className="text-2xl sm:text-4xl font-extrabold text-black mt-2">
              AI recommends. Evidence verifies. Humans decide.
            </h2>
            <p className="text-xs sm:text-sm text-slate-600 mt-2 leading-relaxed max-w-2xl mx-auto">
              SpendGuard explicitly enforces boundaries between automated detection, AI analysis, mathematical verification, and human authority.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-5xl mx-auto mt-10">
            {/* Deterministic Detection */}
            <div className="p-7 rounded-2xl bg-white border border-slate-200/80 shadow-xs">
              <div className="w-10 h-10 rounded-xl bg-slate-100 flex items-center justify-center text-slate-900 mb-4">
                <Search className="w-5 h-5" />
              </div>
              <h3 className="text-base font-bold text-slate-900">Deterministic Detection</h3>
              <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                Anomaly detection relies on reproducible algorithms—MAD robust z-scores, temporal clustering, and Levenshtein token distances—with ground-truth benchmarks.
              </p>
            </div>

            {/* Evidence-Backed AI */}
            <div className="p-7 rounded-2xl bg-white border border-slate-200/80 shadow-xs">
              <div className="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center text-emerald-600 mb-4">
                <FileCheck2 className="w-5 h-5" />
              </div>
              <h3 className="text-base font-bold text-slate-900">Evidence-Backed AI</h3>
              <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                Every assertion made during an investigation is mapped to specific primary source rows. The AI cannot make unverifiable assumptions or generalize without citations.
              </p>
            </div>

            {/* Human-in-the-Loop */}
            <div className="p-7 rounded-2xl bg-white border border-slate-200/80 shadow-xs">
              <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center text-indigo-600 mb-4">
                <Scale className="w-5 h-5" />
              </div>
              <h3 className="text-base font-bold text-slate-900">Human-in-the-Loop</h3>
              <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                Compliance officers maintain ultimate decision rights. All confirmations, dismissals, and audit memos are recorded with human attribution and timestamps.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 5. Core Detector Suite Section (Image 4) */}
      <section id="detectors" className="py-20 px-6 lg:px-12 bg-white border-t border-slate-200/80">
        <div className="max-w-6xl mx-auto">
          <div className="flex flex-col sm:flex-row sm:items-end justify-between mb-8 gap-4">
            <div>
              <span className="text-xs font-bold uppercase tracking-wider text-slate-900">
                CORE DETECTOR SUITE
              </span>
              <h2 className="text-2xl sm:text-3xl font-extrabold text-black mt-1">
                Active Anomaly Detectors
              </h2>
            </div>
            <Link
              to="/evaluation"
              className="text-xs font-semibold text-slate-900 hover:text-slate-600 flex items-center gap-1 group"
            >
              <span>View full benchmark matrix</span>
              <ChevronRight className="w-3.5 h-3.5 text-slate-500 group-hover:text-slate-900" />
            </Link>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Detector 1: Duplicate Purchases */}
            <div className="p-6 bg-white rounded-2xl border border-slate-200/80 shadow-xs">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-slate-100 text-slate-800 flex items-center justify-center">
                    <Copy className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">Duplicate Purchases</h3>
                    <span className="text-[11px] font-medium text-slate-500">Detector #DET-01</span>
                  </div>
                </div>
                <span className="px-2.5 py-0.5 rounded text-[11px] font-semibold bg-red-50 text-red-700 border border-red-200">
                  Critical Risk
                </span>
              </div>
              <p className="text-xs text-slate-600 mt-3 leading-relaxed">
                Flags duplicate invoices or identical charges disbursed through dual channels (such as automated ACH and corporate purchasing cards) within a sliding time window.
              </p>
              <div className="mt-4 p-3 rounded-lg bg-slate-50/80 border border-slate-200/80 text-xs font-mono text-slate-700">
                <span className="text-cyan-700 font-semibold">Signal:</span> Exact amount match ($18,450.00) with suffix &apos;-R&apos; within 34h
              </div>
            </div>

            {/* Detector 2: Split Purchases */}
            <div className="p-6 bg-white rounded-2xl border border-slate-200/80 shadow-xs">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-amber-50 text-amber-700 flex items-center justify-center">
                    <Scissors className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">Split Purchases</h3>
                    <span className="text-[11px] font-medium text-slate-500">Detector #DET-02</span>
                  </div>
                </div>
                <span className="px-2.5 py-0.5 rounded text-[11px] font-semibold bg-amber-50 text-amber-800 border border-amber-200">
                  Policy Violation
                </span>
              </div>
              <p className="text-xs text-slate-600 mt-3 leading-relaxed">
                Identifies sequential requisitions issued right below statutory single-signature caps ($5,000 threshold) by the same purchasing officer to avoid competitive bids.
              </p>
              <div className="mt-4 p-3 rounded-lg bg-slate-50/80 border border-slate-200/80 text-xs font-mono text-slate-700">
                <span className="text-cyan-700 font-semibold">Signal:</span> 3 orders ($4,920, $4,880, $4,950) totaling $14,750 in 72h
              </div>
            </div>

            {/* Detector 3: Price Inflation */}
            <div className="p-6 bg-white rounded-2xl border border-slate-200/80 shadow-xs">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-rose-50 text-rose-700 flex items-center justify-center">
                    <TrendingUp className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">Price Inflation</h3>
                    <span className="text-[11px] font-medium text-slate-500">Detector #DET-03</span>
                  </div>
                </div>
                <span className="px-2.5 py-0.5 rounded text-[11px] font-semibold bg-orange-50 text-orange-800 border border-orange-200">
                  Statistical Outlier
                </span>
              </div>
              <p className="text-xs text-slate-600 mt-3 leading-relaxed">
                Computes robust median absolute deviation (MAD) benchmarks across historical catalog SKUs to isolate transactions where unit pricing wildly exceeds peer averages.
              </p>
              <div className="mt-4 p-3 rounded-lg bg-slate-50/80 border border-slate-200/80 text-xs font-mono text-slate-700">
                <span className="text-cyan-700 font-semibold">Signal:</span> $1,260/spool vs peer median $520 (+142.3% robust z-score: 3.82)
              </div>
            </div>

            {/* Detector 4: Vendor Risk */}
            <div className="p-6 bg-white rounded-2xl border border-slate-200/80 shadow-xs">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-purple-50 text-purple-700 flex items-center justify-center">
                    <Building2 className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">Vendor Risk</h3>
                    <span className="text-[11px] font-medium text-slate-500">Detector #DET-04</span>
                  </div>
                </div>
                <span className="px-2.5 py-0.5 rounded text-[11px] font-semibold bg-red-50 text-red-700 border border-red-200">
                  Integrity Threat
                </span>
              </div>
              <p className="text-xs text-slate-600 mt-3 leading-relaxed">
                Detects newly formed shell corporations, abrupt routing changes immediately prior to invoice disbursement, and employee residential address overlaps.
              </p>
              <div className="mt-4 p-3 rounded-lg bg-slate-50/80 border border-slate-200/80 text-xs font-mono text-slate-700">
                <span className="text-cyan-700 font-semibold">Signal:</span> Entity age 14 days; sole-source $32,000 retainer without RFP
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 6. Dark CTA Section (Image 5) */}
      <section className="bg-black text-white py-20 px-6 lg:px-12 text-center border-t border-neutral-900">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white">
            Ready to investigate procurement risk?
          </h2>
          <p className="mt-4 text-slate-300 text-sm sm:text-base leading-relaxed max-w-xl mx-auto">
            Examine active anomaly queues, inspect ground-truth citations, or test detectors in the interactive sandbox.
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <button
              onClick={() => navigate("/dashboard")}
              className="px-6 py-3 text-sm font-semibold text-white bg-black hover:bg-neutral-800 rounded-lg transition-colors shadow-xs flex items-center gap-2 border border-neutral-700 cursor-pointer"
            >
              <span>Open SpendGuard</span>
              <ArrowRight className="w-4 h-4" />
            </button>

            <button
              onClick={() => navigate("/demo")}
              className="px-6 py-3 text-sm font-semibold text-white bg-[#18181B] hover:bg-neutral-800 border border-neutral-700 rounded-lg transition-colors cursor-pointer"
            >
              Try Interactive Sandbox
            </button>
          </div>
        </div>
      </section>

      {/* 7. Footer (Image 5) */}
      <footer className="bg-white border-t border-slate-200 py-8 px-6 lg:px-12 text-xs text-slate-500">
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
            <Link to="/dashboard" className="hover:text-slate-900 transition-colors">Dashboard</Link>
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
