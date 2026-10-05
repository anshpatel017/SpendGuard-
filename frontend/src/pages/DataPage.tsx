import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Database,
  Download,
  Info,
  Search,
  X,
} from "lucide-react";
import React, { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useTransactions } from "../api/hooks";
import { ErrorBanner, Loading } from "../components/common";
import { useToast } from "../context/ToastContext";
import { formatDate, formatMoney } from "../lib/format";

export function DataPage() {
  const [params, setParams] = useSearchParams();
  const { showToast } = useToast();

  const search = params.get("search") ?? "";
  const page = Math.max(1, Number(params.get("page") ?? 1));
  const pageSize = Number(params.get("page_size") ?? 50);

  const [searchInput, setSearchInput] = useState(search);

  const query = useTransactions({
    search: search || undefined,
    page,
    page_size: pageSize,
  });

  const data = query.data;

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

  const clearSearch = () => {
    setSearchInput("");
    const next = new URLSearchParams(params);
    next.delete("search");
    next.set("page", "1");
    setParams(next);
  };

  const setPage = (nextPage: number) => {
    const next = new URLSearchParams(params);
    next.set("page", String(nextPage));
    setParams(next);
  };

  // CSV export handler
  const handleExportData = () => {
    if (!data || data.items.length === 0) {
      showToast("No transaction records available to export", "error");
      return;
    }

    const headers = [
      "Row ID",
      "Date",
      "Supplier",
      "Supplier Key",
      "Invoice No",
      "Description",
      "Category",
      "Officer ID",
      "Quantity",
      "Unit Price",
      "Total Amount",
    ];

    const rows = data.items.map((r) => [
      r.row_id,
      r.txn_date,
      `"${r.vendor_name || ""}"`,
      `"${r.vendor_key || ""}"`,
      `"${r.invoice_no || ""}"`,
      `"${r.item_desc || ""}"`,
      `"${r.item_category || ""}"`,
      `"${r.officer_id || ""}"`,
      r.quantity ?? "",
      r.unit_price ?? "",
      r.amount,
    ]);

    const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `SpendGuard_Ledger_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    showToast(`Exported ${data.items.length} transaction records to CSV`);
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;

  return (
    <div className="space-y-6">
      {/* 1. Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-xl sm:text-2xl font-bold text-[#0F172A] tracking-tight">
            Data Explorer
          </h2>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Inspect, filter, and audit normalized procurement transaction ledgers in DuckDB.
          </p>
        </div>

        <button
          onClick={handleExportData}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50 transition-colors shadow-2xs self-start sm:self-auto cursor-pointer"
        >
          <Download className="w-3.5 h-3.5 text-slate-500" />
          <span>Export Ledger CSV</span>
        </button>
      </div>

      {/* 2. Active Dataset Banner */}
      <div className="bg-black text-white p-5 rounded-xl border border-neutral-800 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-neutral-400 text-xs font-semibold uppercase tracking-wider">
            <Database className="w-4 h-4 text-cyan-400" />
            <span>Active Normalized Dataset</span>
          </div>
          <h3 className="text-lg font-bold text-white mt-1">
            {data?.dataset ?? "Procurement_FY26_Q1"}
          </h3>
          <p className="text-xs text-slate-300 mt-0.5">
            Analytical columnar store partition managed via DuckDB read-only connection
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-6 text-xs font-mono border-t md:border-t-0 md:border-l border-neutral-800 pt-3 md:pt-0 md:pl-6">
          <div>
            <span className="text-slate-400 block text-[10px] uppercase font-sans">Total Ledger Size</span>
            <span className="text-white font-bold tabular-nums">
              {data ? `${data.total.toLocaleString()} Records` : "Loading..."}
            </span>
          </div>
          <div>
            <span className="text-slate-400 block text-[10px] uppercase font-sans">Date Range</span>
            <span className="text-slate-300">
              {data?.date_min && data?.date_max
                ? `${formatDate(data.date_min)} — ${formatDate(data.date_max)}`
                : "Active period"}
            </span>
          </div>
          <div>
            <span className="text-slate-400 block text-[10px] uppercase font-sans">Mount Status</span>
            <span className="inline-flex items-center gap-1 text-emerald-400 font-bold">
              <CheckCircle2 className="w-3 h-3" />
              <span>Mounted</span>
            </span>
          </div>
        </div>
      </div>

      {/* 2b. Audit Context Banner */}
      <div className="p-4 rounded-xl border border-black bg-neutral-50 flex items-start gap-3 text-xs leading-relaxed shadow-2xs">
        <Info className="w-4 h-4 text-black shrink-0 mt-0.5" />
        <div>
          <strong className="font-semibold block text-black">
            Deterministic Columnar Ledger Isolation
          </strong>
          <span className="text-slate-600">
            DuckDB executes analytical queries in read-only mode directly over normalized procurement parquet files. Zero write-mutation is permitted to guarantee tamper-proof auditability.
          </span>
        </div>
      </div>

      {/* 3. Summary KPI Cards */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
            <span className="text-xs font-medium text-slate-500">Total Transactions</span>
            <div className="mt-2 text-2xl font-bold text-slate-900 font-mono tabular-nums">
              {data.total.toLocaleString()}
            </div>
            <span className="text-[11px] text-slate-400 mt-1 block">Full analytical slice</span>
          </div>

          <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
            <span className="text-xs font-medium text-slate-500">Date Span</span>
            <div className="mt-2 text-base font-bold text-slate-900 font-mono truncate">
              {data.date_min && data.date_max
                ? `${formatDate(data.date_min)} – ${formatDate(data.date_max)}`
                : "Continuous"}
            </div>
            <span className="text-[11px] text-slate-400 mt-1 block">Transaction window</span>
          </div>

          <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
            <span className="text-xs font-medium text-slate-500">Active Suppliers</span>
            <div className="mt-2 text-2xl font-bold text-slate-900 font-mono tabular-nums">
              {data.vendor_count.toLocaleString()}
            </div>
            <span className="text-[11px] text-slate-400 mt-1 block">Distinct entities</span>
          </div>

          <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
            <span className="text-xs font-medium text-slate-500">Total Spend Pool</span>
            <div className="mt-2 text-2xl font-bold text-black font-mono tabular-nums">
              {formatMoney(data.total_amount)}
            </div>
            <span className="text-[11px] text-slate-400 mt-1 block">Currency: {data.currency}</span>
          </div>
        </div>
      )}

      {/* 4. Search Filter Card */}
      <div className="p-4 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
        <form onSubmit={onSearchSubmit} className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              className="w-full pl-9 pr-4 py-2 text-xs sm:text-sm bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-cyan-600 focus:bg-white transition-all text-slate-800 placeholder:text-slate-400"
              placeholder="Search vendor name, description, invoice number, or officer ID..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
          </div>

          <div className="flex items-center gap-2">
            <button
              type="submit"
              className="px-4 py-2 text-xs font-semibold text-white bg-black hover:bg-neutral-800 rounded-lg transition-colors shadow-xs cursor-pointer"
            >
              Search
            </button>

            {search && (
              <button
                type="button"
                onClick={clearSearch}
                className="flex items-center gap-1 px-3 py-2 text-xs font-medium text-slate-600 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors shadow-2xs cursor-pointer"
              >
                <X className="w-3.5 h-3.5 text-slate-400" />
                <span>Clear</span>
              </button>
            )}

            <span className="text-[11px] text-slate-400 hidden lg:inline-block ml-2">
              {data
                ? `Showing ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, data.total)} of ${data.total.toLocaleString()} rows`
                : ""}
            </span>
          </div>
        </form>
      </div>

      {query.isPending && (
        <div className="p-8">
          <Loading what="transactions" />
        </div>
      )}
      {query.error && <ErrorBanner error={query.error} />}

      {/* 5. Transactions Table */}
      {data && (
        <div className="bg-white rounded-xl border border-[#E2E8F0] shadow-xs overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 bg-slate-50/70 flex items-center justify-between">
            <div className="text-xs font-semibold text-slate-800">
              Procurement Ledger Entries ({data.items.length} rows on this page)
            </div>
            <div className="text-[11px] text-slate-500 font-mono">
              Page {page} of {totalPages}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-[#E2E8F0] text-[11px] font-semibold text-slate-500 uppercase tracking-wider bg-slate-50">
                  <th className="py-3 px-4">Row ID</th>
                  <th className="py-3 px-4">Date</th>
                  <th className="py-3 px-4">Supplier</th>
                  <th className="py-3 px-4">Invoice No</th>
                  <th className="py-3 px-4">Description / Category</th>
                  <th className="py-3 px-4">Officer</th>
                  <th className="py-3 px-4 text-right">Qty</th>
                  <th className="py-3 px-4 text-right">Unit Price</th>
                  <th className="py-3 px-4 text-right">Total Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs text-slate-700">
                {data.items.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-12 text-center text-slate-500">
                      <div className="max-w-sm mx-auto flex flex-col items-center">
                        <div className="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-3">
                          <Search className="w-5 h-5" />
                        </div>
                        <h4 className="text-sm font-bold text-slate-800">No records match this query</h4>
                        <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                          Try searching for another supplier name or clear the query.
                        </p>
                        <button
                          onClick={clearSearch}
                          className="mt-4 px-3.5 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50 transition-colors shadow-xs cursor-pointer"
                        >
                          Clear Search Filter
                        </button>
                      </div>
                    </td>
                  </tr>
                ) : (
                  data.items.map((row) => (
                    <tr key={row.row_id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-3 px-4 font-mono text-cyan-800 font-semibold whitespace-nowrap">
                        #{row.row_id}
                      </td>
                      <td className="py-3 px-4 whitespace-nowrap text-slate-600">
                        {formatDate(row.txn_date)}
                      </td>
                      <td className="py-3 px-4 font-medium text-slate-900 max-w-[180px] truncate">
                        <div>{row.vendor_name || row.vendor_key}</div>
                        {row.vendor_name && row.vendor_key && (
                          <div className="text-[10px] text-slate-400 font-mono">{row.vendor_key}</div>
                        )}
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-600 whitespace-nowrap">
                        {row.invoice_no ?? "—"}
                      </td>
                      <td className="py-3 px-4 max-w-[220px]">
                        <div className="truncate text-slate-800">{row.item_desc ?? "—"}</div>
                        {row.item_category && (
                          <div className="text-[10px] text-slate-400 uppercase tracking-wider mt-0.5">
                            {row.item_category}
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-500 text-[11px] whitespace-nowrap">
                        {row.officer_id ?? "—"}
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-slate-700 tabular-nums whitespace-nowrap">
                        {row.quantity?.toLocaleString() ?? "—"}
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-slate-600 tabular-nums whitespace-nowrap">
                        {row.unit_price ? formatMoney(row.unit_price) : "—"}
                      </td>
                      <td className="py-3 px-4 text-right font-mono font-semibold text-slate-900 tabular-nums whitespace-nowrap">
                        {formatMoney(row.amount)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="px-4 py-3 border-t border-slate-200 bg-slate-50 flex items-center justify-between text-xs">
            <span className="text-slate-500">
              Page {page} of {totalPages}
              {query.isFetching ? " · updating…" : ""}
            </span>

            <div className="flex items-center gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
                className="flex items-center gap-1 px-3 py-1 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed shadow-2xs cursor-pointer"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
                <span>Previous</span>
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
                className="flex items-center gap-1 px-3 py-1 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed shadow-2xs cursor-pointer"
              >
                <span>Next</span>
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
