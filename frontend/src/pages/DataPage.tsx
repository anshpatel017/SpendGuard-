// Read-only transaction explorer (P2). Reuses the DuckDB audit view without exposing injected flags.
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useTransactions } from "../api/hooks";
import { Card, ErrorBanner, Loading } from "../components/common";
import { formatDate, formatMoney } from "../lib/format";

export function DataPage() {
  const [params, setParams] = useSearchParams();
  const search = params.get("search") ?? "";
  const page = Math.max(1, Number(params.get("page") ?? 1));
  const pageSize = Number(params.get("page_size") ?? 50);

  const [searchInput, setSearchInput] = useState(search);

  const query = useTransactions({
    search: search || undefined,
    page,
    page_size: pageSize,
  });

  const onSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams(params);
    if (searchInput.trim()) {
      next.set("search", searchInput.trim());
    } else {
      next.delete("search");
    }
    next.set("page", "1");
    setParams(next);
  };

  const setPage = (nextPage: number) => {
    const next = new URLSearchParams(params);
    next.set("page", String(nextPage));
    setParams(next);
  };

  const data = query.data;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>Procurement Data Explorer</h1>
        <div className="muted small">
          Direct read-only inspection of normalized procurement transactions from analytical storage (DuckDB).
        </div>
      </div>

      {data && (
        <div className="grid-4">
          <div className="kpi">
            <span className="label">Dataset</span>
            <span className="value" style={{ fontSize: "1.2rem", wordBreak: "break-all" }}>
              {data.dataset ?? "synthetic_inr_seed42"}
            </span>
            <span className="sub">Normalized analytical store</span>
          </div>
          <div className="kpi">
            <span className="label">Transactions</span>
            <span className="value">{data.total.toLocaleString()}</span>
            <span className="sub">
              {data.date_min && data.date_max ? `${formatDate(data.date_min)} — ${formatDate(data.date_max)}` : "All records"}
            </span>
          </div>
          <div className="kpi">
            <span className="label">Active Suppliers</span>
            <span className="value">{data.vendor_count.toLocaleString()}</span>
            <span className="sub">Distinct vendor entities</span>
          </div>
          <div className="kpi">
            <span className="label">Total Procurement Spend</span>
            <span className="value">{formatMoney(data.total_amount)}</span>
            <span className="sub">Currency: {data.currency}</span>
          </div>
        </div>
      )}

      <Card>
        <form onSubmit={onSearchSubmit} className="row" style={{ gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <input
            type="search"
            className="input"
            style={{ minWidth: 260, flex: 1, padding: "8px 12px" }}
            placeholder="Search vendor, description, invoice, or officer ID…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
          <button type="submit" className="btn primary">
            Search
          </button>
          {search && (
            <button
              type="button"
              className="btn"
              onClick={() => {
                setSearchInput("");
                const next = new URLSearchParams(params);
                next.delete("search");
                next.set("page", "1");
                setParams(next);
              }}
            >
              Clear
            </button>
          )}
          <span className="muted small" style={{ marginLeft: "auto" }}>
            Showing {data ? `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, data.total)} of ${data.total.toLocaleString()}` : "..."}
          </span>
        </form>
      </Card>

      {query.isPending && <Loading what="transactions" />}
      {query.error && <ErrorBanner error={query.error} />}

      {data && (
        <Card>
          <div style={{ overflowX: "auto" }}>
            <table className="table" style={{ width: "100%", fontSize: "0.875rem" }}>
              <thead>
                <tr>
                  <th style={{ width: 80 }}>Row ID</th>
                  <th>Date</th>
                  <th>Supplier</th>
                  <th>Invoice No</th>
                  <th>Description / Category</th>
                  <th>Officer</th>
                  <th style={{ textAlign: "right" }}>Qty</th>
                  <th style={{ textAlign: "right" }}>Unit Price</th>
                  <th style={{ textAlign: "right" }}>Total Amount</th>
                </tr>
              </thead>
              <tbody>
                {data.items.length === 0 ? (
                  <tr>
                    <td colSpan={9} style={{ textAlign: "center", padding: "2rem" }}>
                      <div className="empty">No transactions match your search filter.</div>
                    </td>
                  </tr>
                ) : (
                  data.items.map((row) => (
                    <tr key={row.row_id}>
                      <td className="mono muted">#{row.row_id}</td>
                      <td>{formatDate(row.txn_date)}</td>
                      <td>
                        <strong>{row.vendor_name || row.vendor_key}</strong>
                        {row.vendor_name && row.vendor_key && (
                          <div className="muted small mono">{row.vendor_key}</div>
                        )}
                      </td>
                      <td className="mono small">{row.invoice_no ?? "—"}</td>
                      <td>
                        <div>{row.item_desc ?? "—"}</div>
                        {row.item_category && (
                          <div className="muted small">{row.item_category}</div>
                        )}
                      </td>
                      <td className="mono small">{row.officer_id ?? "—"}</td>
                      <td style={{ textAlign: "right" }}>{row.quantity?.toLocaleString() ?? "—"}</td>
                      <td style={{ textAlign: "right" }} className="mono">
                        {row.unit_price ? formatMoney(row.unit_price) : "—"}
                      </td>
                      <td style={{ textAlign: "right" }} className="mono bold">
                        {formatMoney(row.amount)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div className="pager" style={{ marginTop: 16 }}>
            <span className="muted small">
              Page {page} of {Math.max(1, Math.ceil(data.total / pageSize))}
              {query.isFetching ? " · updating…" : ""}
            </span>
            <button className="btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              Previous
            </button>
            <button
              className="btn"
              disabled={page >= Math.max(1, Math.ceil(data.total / pageSize))}
              onClick={() => setPage(page + 1)}
            >
              Next
            </button>
          </div>
        </Card>
      )}
    </div>
  );
}
