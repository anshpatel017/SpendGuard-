// The case queue: KPIs with the honest coverage line, then every flagged case,
// highest severity first. Filters live in the URL, so a filtered view can be
// shared, bookmarked and reached with the back button.
import { useNavigate, useSearchParams } from "react-router-dom";

import type { CaseFilters } from "../api/client";
import { useCases, useMetrics } from "../api/hooks";
import type { CaseSummary, MetricsResponse } from "../api/types";
import { Card, ErrorBanner, Loading, SeverityChip, VerificationBadge } from "../components/common";
import {
  ANOMALY_LABEL,
  STATUS_LABEL,
  VERDICT_LABEL,
  formatCount,
  formatMoney,
  formatMoneyShort,
} from "../lib/format";

const PAGE_SIZE = 50;
const FILTER_KEYS = [
  "anomaly_type",
  "severity_band",
  "status",
  "verdict",
  "verification_status",
  "investigated",
  "dismissed_by_agent",
  "sort",
  "order",
] as const;

function Kpis({ m }: { m: MetricsResponse }) {
  const verified = m.by_verification_status.verified ?? 0;
  return (
    <div className="stack">
      <div className="kpis">
        <div className="card kpi">
          <div className="label">Transactions audited</div>
          <div className="value">{formatCount(m.total_transactions)}</div>
          <div className="sub">{formatMoneyShort(m.total_amount)} in total · 100% scanned</div>
        </div>
        <div className="card kpi">
          <div className="label">Money at risk</div>
          <div className="value" title={formatMoney(m.money_at_risk)}>
            {formatMoneyShort(m.money_at_risk)}
          </div>
          <div className="sub">{formatMoneyShort(m.money_at_risk_confirmed)} confirmed by a reviewer</div>
        </div>
        <div className="card kpi">
          <div className="label">Cases flagged</div>
          <div className="value">{formatCount(m.cases_flagged)}</div>
          <div className="sub">
            {Object.entries(m.by_anomaly_type)
              .map(([kind, b]) => `${b.count} ${ANOMALY_LABEL[kind as keyof typeof ANOMALY_LABEL]?.toLowerCase() ?? kind}`)
              .join(" · ")}
          </div>
        </div>
        <div className="card kpi">
          <div className="label">Verified audit notes</div>
          <div className="value">{formatCount(verified)}</div>
          <div className="sub">of {formatCount(m.cases_investigated)} investigated</div>
        </div>
      </div>
      <div className="card coverage" data-testid="coverage-line">
        Detection covered <strong>100%</strong> of transactions: <strong>{formatCount(m.cases_flagged)}</strong> cases
        flagged · <strong>{formatCount(m.cases_investigated)}</strong> investigated ·{" "}
        <strong>{formatCount(m.cases_queued)}</strong> queued for investigation, highest severity first.
      </div>
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{label}: all</option>
      {options.map(([v, text]) => (
        <option key={v} value={v}>
          {text}
        </option>
      ))}
    </select>
  );
}

function CaseRow({ c, onOpen }: { c: CaseSummary; onOpen: () => void }) {
  return (
    <tr className="clickable" onClick={onOpen}>
      <td>
        <SeverityChip band={c.severity_band} value={c.severity_prelim} final={c.severity_final} />
      </td>
      <td>{ANOMALY_LABEL[c.anomaly_type]}</td>
      <td>{c.vendor_key ?? "—"}</td>
      <td className="num">{formatMoney(c.amount_at_risk)}</td>
      <td className="num">{c.detector_score.toFixed(2)}</td>
      <td>{STATUS_LABEL[c.status]}</td>
      <td>
        {c.verdict ? (
          <span className={`chip ${c.verdict === "likely_false_positive" ? "none" : "outline"}`}>
            {VERDICT_LABEL[c.verdict]}
          </span>
        ) : (
          <span className="muted small">queued</span>
        )}
      </td>
      <td>
        {c.investigated && (
          <VerificationBadge status={c.verification_status} passed={c.citations_passed} checked={c.citations_checked} />
        )}
      </td>
      <td className="excerpt small">{c.finding_excerpt}</td>
    </tr>
  );
}

export function QueuePage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const metrics = useMetrics();

  const filters: CaseFilters = { page: Number(params.get("page") ?? 1), page_size: PAGE_SIZE };
  for (const key of FILTER_KEYS) {
    const value = params.get(key);
    if (value) filters[key] = value;
  }
  const cases = useCases(filters);

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  };
  const sortBy = (key: string) => {
    const same = (params.get("sort") ?? "severity_prelim") === key;
    const next = new URLSearchParams(params);
    next.set("sort", key);
    next.set("order", same && params.get("order") !== "asc" ? "asc" : "desc");
    next.delete("page");
    setParams(next);
  };
  const arrow = (key: string) =>
    (params.get("sort") ?? "severity_prelim") === key ? (params.get("order") === "asc" ? " ▲" : " ▼") : "";

  const page = filters.page ?? 1;
  const pages = cases.data ? Math.max(1, Math.ceil(cases.data.total / PAGE_SIZE)) : 1;

  return (
    <div className="stack">
      {metrics.error ? <ErrorBanner error={metrics.error} /> : metrics.data ? <Kpis m={metrics.data} /> : <Loading what="metrics" />}

      <Card
        title={`Case queue${cases.data ? ` · ${formatCount(cases.data.total)}` : ""}`}
        actions={
          <div className="filters">
            <Select label="Type" value={params.get("anomaly_type") ?? ""} onChange={(v) => set("anomaly_type", v)}
              options={Object.entries(ANOMALY_LABEL)} />
            <Select label="Severity" value={params.get("severity_band") ?? ""} onChange={(v) => set("severity_band", v)}
              options={[["high", "High"], ["medium", "Medium"], ["low", "Low"]]} />
            <Select label="Status" value={params.get("status") ?? ""} onChange={(v) => set("status", v)}
              options={Object.entries(STATUS_LABEL)} />
            <Select label="Investigation" value={params.get("investigated") ?? ""} onChange={(v) => set("investigated", v)}
              options={[["true", "Investigated"], ["false", "Queued"]]} />
            <Select label="Verdict" value={params.get("verdict") ?? ""} onChange={(v) => set("verdict", v)}
              options={Object.entries(VERDICT_LABEL)} />
            <Select label="Verification" value={params.get("verification_status") ?? ""}
              onChange={(v) => set("verification_status", v)}
              options={[["verified", "Verified"], ["failed_after_retries", "Failed checks"], ["unverified", "Unverified"]]} />
            <label className="check">
              <input type="checkbox" checked={params.get("dismissed_by_agent") === "true"}
                onChange={(e) => set("dismissed_by_agent", e.target.checked ? "true" : "")} />
              Dismissed by agent
            </label>
          </div>
        }
      >
        {cases.error && <ErrorBanner error={cases.error} />}
        {cases.isPending && <Loading what="cases" />}
        {cases.data && cases.data.items.length === 0 && <div className="empty">No cases match these filters.</div>}
        {cases.data && cases.data.items.length > 0 && (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th className="sortable" onClick={() => sortBy("severity_prelim")}>Severity{arrow("severity_prelim")}</th>
                    <th>Type</th>
                    <th>Supplier</th>
                    <th className="num sortable" onClick={() => sortBy("amount_at_risk")}>At risk{arrow("amount_at_risk")}</th>
                    <th className="num">Score</th>
                    <th>Status</th>
                    <th>Agent verdict</th>
                    <th>Verification</th>
                    <th>Finding</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.data.items.map((c) => (
                    <CaseRow key={c.case_id} c={c} onOpen={() => navigate(`/cases/${c.case_id}`)} />
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pager">
              <span className="muted small">
                Page {page} of {pages}
                {cases.isFetching ? " · updating…" : ""}
              </span>
              <button className="btn" disabled={page <= 1} onClick={() => set("page", String(page - 1))}>Previous</button>
              <button className="btn" disabled={page >= pages} onClick={() => set("page", String(page + 1))}>Next</button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
