// Every step the agents took (FR-6.6): what the Investigator asked for and got
// back, then what the Verifier checked. Tool results are folded away; open one to
// see exactly what the model saw.
import type { TraceStep } from "../api/types";
import { formatCount } from "../lib/format";
import { Card } from "./common";

const KIND_LABEL: Record<string, string> = {
  model: "Model turn",
  tool: "Tool call",
  parse_error: "Malformed note, sent back",
  context_trim: "Context trimmed",
  forced_final: "Final note, tools off",
  failed: "Failed",
  check: "Deterministic check",
  judge: "Semantic check (model-judged)",
};

function Step({ step }: { step: TraceStep }) {
  const tokens = (step.prompt_tokens ?? 0) + (step.completion_tokens ?? 0);
  const hasResult = step.tool_result !== null && step.tool_result !== undefined;
  return (
    <li className={`step ${step.role} ${step.error ? "error" : ""}`}>
      <div className="dot">{step.step_index + 1}</div>
      <div>
        <div className="row" style={{ gap: 8 }}>
          <strong>{KIND_LABEL[step.kind] ?? step.kind}</strong>
          {step.tool_name && <code>{step.tool_name}({step.tool_args ? JSON.stringify(step.tool_args) : ""})</code>}
          <span className="chip outline small">{step.role === "verifier" ? "Verifier" : "Investigator"}</span>
        </div>
        {step.detail && <div className="small">{step.detail}</div>}
        {step.error && <div className="failure">{step.error}</div>}
        <div className="meta">
          {step.latency_ms > 0 && `${formatCount(step.latency_ms)} ms`}
          {tokens > 0 && ` · ${formatCount(tokens)} tokens`}
        </div>
        {hasResult && (
          <details>
            <summary>{step.kind === "tool" ? "Result the model saw" : "Details"}</summary>
            <pre>{JSON.stringify(step.tool_result, null, 2)}</pre>
          </details>
        )}
      </div>
    </li>
  );
}

export function TraceTimeline({ trace }: { trace: TraceStep[] }) {
  const tools = trace.filter((s) => s.kind === "tool").length;
  const tokens = trace.reduce((sum, s) => sum + (s.prompt_tokens ?? 0) + (s.completion_tokens ?? 0), 0);
  return (
    <Card
      title="Agent trace"
      actions={
        <span className="muted small">
          {trace.length} steps · {tools} tool calls · {formatCount(tokens)} tokens
        </span>
      }
    >
      {trace.length === 0 ? (
        <div className="empty">No trace recorded.</div>
      ) : (
        <ol className="timeline">
          {trace.map((step) => (
            <Step key={step.step_index} step={step} />
          ))}
        </ol>
      )}
    </Card>
  );
}
