import React, { useEffect, useRef, useState } from 'react';
import { Database, Search, Sparkles, CheckCircle2, Scale } from 'lucide-react';

interface StepItem {
  id: string;
  stepNumber: string;
  title: string;
  description: string;
  tag: string;
  icon: React.ComponentType<{ className?: string }>;
  accentColor: string;
  badgeBg: string;
}

const FLOW_STEPS: StepItem[] = [
  {
    id: 'step-1',
    stepNumber: 'STEP 01',
    title: 'Procurement Data',
    description: 'Invoices, purchase orders, P-card slips, and vendor contracts.',
    tag: 'ERP / SAP ingest',
    icon: Database,
    accentColor: '#94A3B8',
    badgeBg: 'bg-slate-800/80 text-slate-300 border-slate-700/60',
  },
  {
    id: 'step-2',
    stepNumber: 'STEP 02',
    title: 'Anomaly Detection',
    description: 'Deterministic detectors flag split buys, duplicate invoices, and outliers.',
    tag: 'Strict rules & scores',
    icon: Search,
    accentColor: '#67E8F9',
    badgeBg: 'bg-cyan-950/80 text-cyan-300 border-cyan-800/60',
  },
  {
    id: 'step-3',
    stepNumber: 'STEP 03',
    title: 'AI Investigation',
    description: 'Read-only tools inspect vendor profiles, manifests, and historical peers.',
    tag: 'Structured citations',
    icon: Sparkles,
    accentColor: '#A78BFA',
    badgeBg: 'bg-indigo-950/80 text-indigo-300 border-indigo-800/60',
  },
  {
    id: 'step-4',
    stepNumber: 'STEP 04',
    title: 'Evidence Verification',
    description: 'Independent logic validates row existence, claims, and policies.',
    tag: 'Zero hallucinations',
    icon: CheckCircle2,
    accentColor: '#34D399',
    badgeBg: 'bg-emerald-950/80 text-emerald-300 border-emerald-800/60',
  },
  {
    id: 'step-5',
    stepNumber: 'STEP 05',
    title: 'Human Review',
    description: 'Analyst reviews verified findings and makes final case determination.',
    tag: 'Human-in-the-loop',
    icon: Scale,
    accentColor: '#38BDF8',
    badgeBg: 'bg-sky-950/80 text-sky-300 border-sky-800/60',
  },
];

interface PathData {
  d: string;
  length: number;
}

export default function InvestigationArchitectureFlow() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [paths, setPaths] = useState<PathData[]>([]);
  const [scrollProgress, setScrollProgress] = useState<number>(0);

  // Measure card positions and compute connecting cubic Bezier curves
  const updatePaths = () => {
    const container = containerRef.current;
    if (!container) return;

    const containerRect = container.getBoundingClientRect();
    const newPaths: PathData[] = [];

    for (let i = 0; i < FLOW_STEPS.length - 1; i++) {
      const cardA = cardRefs.current[i];
      const cardB = cardRefs.current[i + 1];
      if (!cardA || !cardB) continue;

      const rectA = cardA.getBoundingClientRect();
      const rectB = cardB.getBoundingClientRect();

      const isAOnLeft = i % 2 === 0;

      let startX = 0;
      let startY = 0;
      let endX = 0;
      let endY = 0;

      if (isAOnLeft) {
        // From left card to right card:
        // Leaves bottom of card A, goes down, turns 90° right, runs horizontally,
        // turns 90° down, and points vertically down into top of card B
        startX = rectA.left + rectA.width * 0.65 - containerRect.left;
        startY = rectA.bottom - containerRect.top;

        endX = rectB.left + rectB.width * 0.35 - containerRect.left;
        endY = rectB.top - containerRect.top;

        const midY = startY + (endY - startY) * 0.5;
        const r = Math.min(32, Math.max(12, (endX - startX) * 0.25, (endY - startY) * 0.25));

        const d = `M ${startX.toFixed(1)} ${startY.toFixed(1)} ` +
          `L ${startX.toFixed(1)} ${(midY - r).toFixed(1)} ` +
          `Q ${startX.toFixed(1)} ${midY.toFixed(1)}, ${(startX + r).toFixed(1)} ${midY.toFixed(1)} ` +
          `L ${(endX - r).toFixed(1)} ${midY.toFixed(1)} ` +
          `Q ${endX.toFixed(1)} ${midY.toFixed(1)}, ${endX.toFixed(1)} ${(midY + r).toFixed(1)} ` +
          `L ${endX.toFixed(1)} ${endY.toFixed(1)}`;

        const length = (endY - startY) + Math.abs(endX - startX) + 10;
        newPaths.push({ d, length });
      } else {
        // From right card to left card:
        // Leaves bottom of card A, goes down, turns 90° left, runs horizontally,
        // turns 90° down, and connects directly into top of card B
        startX = rectA.left + rectA.width * 0.35 - containerRect.left;
        startY = rectA.bottom - containerRect.top;

        endX = rectB.left + rectB.width * 0.65 - containerRect.left;
        endY = rectB.top - containerRect.top;

        const midY = startY + (endY - startY) * 0.5;
        const r = Math.min(32, Math.max(12, (startX - endX) * 0.25, (endY - startY) * 0.25));

        const d = `M ${startX.toFixed(1)} ${startY.toFixed(1)} ` +
          `L ${startX.toFixed(1)} ${(midY - r).toFixed(1)} ` +
          `Q ${startX.toFixed(1)} ${midY.toFixed(1)}, ${(startX - r).toFixed(1)} ${midY.toFixed(1)} ` +
          `L ${(endX + r).toFixed(1)} ${midY.toFixed(1)} ` +
          `Q ${endX.toFixed(1)} ${midY.toFixed(1)}, ${endX.toFixed(1)} ${(midY + r).toFixed(1)} ` +
          `L ${endX.toFixed(1)} ${endY.toFixed(1)}`;

        const length = (endY - startY) + Math.abs(startX - endX) + 10;
        newPaths.push({ d, length });
      }
    }

    setPaths(newPaths);
  };

  useEffect(() => {
    updatePaths();
    const handleResize = () => updatePaths();
    window.addEventListener('resize', handleResize);

    const handleScroll = () => {
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const viewportHeight = window.innerHeight;

      // Start progressing when section starts entering bottom of screen
      // Complete when section is near top/middle
      const enterPoint = viewportHeight * 0.85;
      const exitPoint = viewportHeight * 0.15;
      const totalDistance = rect.height + (enterPoint - exitPoint);
      const currentScroll = enterPoint - rect.top;

      const progress = Math.max(0, Math.min(1, currentScroll / totalDistance));
      setScrollProgress(progress);
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();

    // Recheck after initial renders
    const timer = setTimeout(updatePaths, 300);

    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('scroll', handleScroll);
      clearTimeout(timer);
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="relative max-w-5xl mx-auto py-16 px-4 sm:px-8 text-slate-900 select-none"
    >
      {/* Header */}
      <div className="text-center mb-16">
        <div className="inline-flex items-center gap-2 px-3.5 py-1 rounded-full bg-neutral-100 border border-neutral-300 text-black text-xs font-semibold uppercase tracking-wider mb-3 shadow-2xs">
          <Sparkles className="w-3.5 h-3.5 text-black" />
          <span>Interactive Architecture</span>
        </div>
        <h2 className="text-2xl sm:text-4xl font-extrabold tracking-tight text-black">
          End-to-End Investigation Architecture
        </h2>
        <p className="mt-2 text-xs sm:text-sm text-slate-600 max-w-xl mx-auto font-medium">
          Scroll down to trace the verified data flow from raw ERP ingestion to definitive human audit sign-off.
        </p>
      </div>

      {/* SVG Connecting Flow Lines with Scroll Follow */}
      <svg
        className="pointer-events-none absolute inset-0 w-full h-full z-0 overflow-visible"
        xmlns="http://www.w3.org/2000/svg"
      >
        {paths.map((p, idx) => {
          // Each path corresponds to 1/4 of total scroll progress
          const segmentStart = idx * 0.22;
          const segmentEnd = segmentStart + 0.25;
          const segmentProgress = Math.max(
            0,
            Math.min(1, (scrollProgress - segmentStart) / (segmentEnd - segmentStart))
          );

          const strokeDashoffset = p.length * (1 - segmentProgress);

          return (
            <g key={idx}>
              {/* Dim underlying guide line */}
              <path
                d={p.d}
                fill="none"
                stroke="#E2E8F0"
                strokeWidth="2"
                strokeDasharray="5 5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />

              {/* Animated active scroll-follow line: Clean Normal Black */}
              <path
                d={p.d}
                fill="none"
                stroke="#000000"
                strokeWidth="2.5"
                strokeDasharray={p.length}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
                strokeLinejoin="round"
                className="transition-all duration-75"
              />
            </g>
          );
        })}
      </svg>

      {/* Alternating Zigzag Cards Layout */}
      <div className="relative z-10 flex flex-col space-y-12 sm:space-y-16">
        {FLOW_STEPS.map((step, idx) => {
          const isLeft = idx % 2 === 0;
          const Icon = step.icon;
          // Step is activated when scroll reaches its approximate position
          const stepThreshold = idx * 0.2;
          const isActivated = scrollProgress >= stepThreshold;

          return (
            <div
              key={step.id}
              ref={(el) => {
                cardRefs.current[idx] = el;
              }}
              className={`w-full sm:w-[85%] md:w-[48%] ${
                isLeft ? 'self-start' : 'self-end'
              } transition-all duration-500`}
            >
              <div
                className={`relative rounded-2xl p-6 sm:p-7 backdrop-blur-md transition-all duration-300 shadow-sm ${
                  isActivated
                    ? 'bg-white border-2 border-black shadow-[0_12px_32px_rgba(0,0,0,0.08)] ring-1 ring-black/10'
                    : 'bg-white/95 border border-slate-200 hover:border-slate-300'
                }`}
              >
                {/* Header row */}
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div
                      className={`w-10 h-10 rounded-xl flex items-center justify-center transition-colors duration-300 ${
                        isActivated
                          ? 'bg-neutral-100 text-black border border-neutral-300 shadow-xs'
                          : 'bg-slate-100 text-slate-600 border border-slate-200'
                      }`}
                    >
                      <Icon className="w-5 h-5" />
                    </div>
                    <div>
                      <span className="text-[11px] font-mono font-bold tracking-wider text-black">
                        {step.stepNumber}
                      </span>
                      <h3 className="text-base sm:text-lg font-bold text-slate-900 tracking-tight">
                        {step.title}
                      </h3>
                    </div>
                  </div>

                  <span
                    className={`text-[10px] font-mono px-2 py-0.5 rounded border transition-colors ${
                      isActivated
                        ? 'bg-neutral-100 text-black border-neutral-300 font-semibold'
                        : 'bg-slate-50 text-slate-400 border-slate-200'
                    }`}
                  >
                    Active
                  </span>
                </div>

                {/* Description */}
                <p className="text-xs sm:text-sm text-slate-600 leading-relaxed font-normal">
                  {step.description}
                </p>

                {/* Tag pill at bottom */}
                <div className="mt-5 pt-3 border-t border-slate-100 flex items-center justify-between">
                  <span className="text-[11px] font-mono text-slate-500">
                    {step.tag}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        isActivated ? 'bg-emerald-500 animate-pulse' : 'bg-slate-300'
                      }`}
                    />
                    <span
                      className={`text-[10px] font-medium ${
                        isActivated ? 'text-emerald-700 font-semibold' : 'text-slate-400'
                      }`}
                    >
                      {isActivated ? 'Verified' : 'Pending'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
