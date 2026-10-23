import { AlertTriangle, CheckCircle2, FileUp, Info, Loader2 } from "lucide-react";
import { useRef, useState } from "react";

import type { components } from "../api/schema";

type Preview = components["schemas"]["DatasetPreviewResponse"];
type Ingested = components["schemas"]["DatasetIngestResponse"];

const REQUIRED = ["vendor_name", "amount", "txn_date"] as const;
const OPTIONAL = [
  "invoice_no",
  "officer_id",
  "item_desc",
  "item_category",
  "quantity",
  "unit_price",
] as const;

const FIELD_HELP: Record<string, string> = {
  vendor_name: "Who was paid. Normalised so spelling variants group together.",
  amount: "The value of the line. Drives money at risk and severity.",
  txn_date: "When it happened. Duplicate and split detection both need it.",
  invoice_no: "Strengthens duplicate detection when present.",
  officer_id: "Who raised it. Split-purchase detection groups on this.",
  item_desc: "Shown to a reviewer as evidence.",
  item_category: "Lets price inflation compare like with like.",
  quantity: "Used with unit price.",
  unit_price: "What price inflation is measured on.",
};

/** Bringing a new procurement export into the system.
 *
 * Deliberately two steps. The preview writes nothing, so a file can be checked
 * before anyone commits to it; only the second step ingests, and only ever into
 * a new dataset of its own. There is no step that edits an existing row - a
 * correction is a fresh ingestion, which leaves the original intact.
 */
export function IntakePage() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [dataset, setDataset] = useState("");
  const [dateFormat, setDateFormat] = useState("");
  const [busy, setBusy] = useState<"preview" | "ingest" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Ingested | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function onPick(picked: File) {
    setFile(picked);
    setPreview(null);
    setDone(null);
    setError(null);
    setBusy("preview");
    setDataset(picked.name.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9]+/g, "_"));

    const body = new FormData();
    body.append("file", picked);
    try {
      const res = await fetch("/api/v1/datasets/preview", { method: "POST", body });
      const json = await res.json();
      if (!res.ok) {
        setError(json?.detail?.message ?? "The file could not be read.");
        return;
      }
      setPreview(json as Preview);
      const guessed: Record<string, string> = {};
      for (const [field, column] of Object.entries((json as Preview).suggested)) {
        if (column) guessed[field] = column;
      }
      setMapping(guessed);
      const fits = (json as Preview).date_formats;
      setDateFormat(fits.length === 1 ? (fits[0] ?? "") : "");
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(null);
    }
  }

  async function onIngest() {
    if (!file) return;
    setBusy("ingest");
    setError(null);
    const body = new FormData();
    body.append("file", file);
    body.append("dataset", dataset);
    for (const [field, column] of Object.entries(mapping)) {
      if (column) body.append(field, column);
    }
    if (dateFormat) body.append("date_format", dateFormat);
    try {
      const res = await fetch("/api/v1/datasets", { method: "POST", body });
      const json = await res.json();
      if (!res.ok) {
        setError(json?.detail?.message ?? "Ingestion failed.");
        return;
      }
      setDone(json as Ingested);
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(null);
    }
  }

  // A usable preview is not enough: an ambiguous date column leaves the caller
  // to choose, and 01-04-2024 under the wrong format mis-dates every row.
  const ready =
    preview != null &&
    preview.rows > 0 &&
    REQUIRED.every((f) => mapping[f]) &&
    dateFormat !== "" &&
    /^[a-z0-9_]+$/.test(dataset);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-bold text-slate-900">Add data</h2>
        <p className="mt-1 text-sm text-slate-600">
          Upload a CSV export from your finance or procurement system. It is checked first and
          nothing is written until you confirm the columns.
        </p>
      </div>

      <div className="p-4 rounded-xl border border-black bg-neutral-50 flex items-start gap-3 text-xs leading-relaxed shadow-2xs">
        <Info className="w-4 h-4 text-black shrink-0 mt-0.5" />
        <div>
          <strong className="font-semibold block text-black">Each upload is its own dataset</strong>
          <span className="text-slate-600">
            Ingestion replaces a dataset entirely, so a new file is never loaded over one already
            in use — the earlier data stays intact and the two remain comparable. Transactions
            cannot be edited here or anywhere else; a correction is a fresh upload.
          </span>
        </div>
      </div>

      <div className="p-5 bg-white rounded-xl border border-[#E2E8F0] shadow-xs">
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => {
            const picked = e.target.files?.[0];
            if (picked) void onPick(picked);
          }}
        />
        <button
          type="button"
          onClick={() => input.current?.click()}
          className="w-full py-8 rounded-lg border-2 border-dashed border-slate-300 hover:border-slate-500 hover:bg-slate-50 transition-colors flex flex-col items-center gap-2"
        >
          {busy === "preview" ? (
            <Loader2 className="w-6 h-6 text-slate-500 animate-spin" />
          ) : (
            <FileUp className="w-6 h-6 text-slate-500" />
          )}
          <span className="text-sm font-medium text-slate-700">
            {file ? file.name : "Choose a CSV file"}
          </span>
          <span className="text-xs text-slate-500">
            {busy === "preview" ? "Reading…" : "Nothing is written until you confirm"}
          </span>
        </button>
      </div>

      {error && (
        <div className="p-4 rounded-xl border border-red-300 bg-red-50 flex items-start gap-3 text-sm">
          <AlertTriangle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
          <span className="text-red-800">{error}</span>
        </div>
      )}

      {preview && !done && (
        <>
          <div className="p-5 bg-white rounded-xl border border-[#E2E8F0] shadow-xs space-y-4">
            <div className="flex items-center gap-2">
              {preview.usable ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              ) : (
                <AlertTriangle className="w-4 h-4 text-amber-600" />
              )}
              <h3 className="text-sm font-bold text-slate-900">
                {preview.rows.toLocaleString()} rows · {preview.headers.length} columns
              </h3>
            </div>

            {preview.problems.length > 0 && (
              <ul className="space-y-1 text-xs text-amber-800 list-disc pl-5">
                {preview.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            )}

            {preview.date_formats.length !== 1 && (
              <div className="p-3 rounded-lg bg-amber-50 border border-amber-200">
                <label
                  htmlFor="date-format"
                  className="block text-xs font-medium text-amber-900"
                >
                  Date format
                </label>
                <p className="mt-0.5 text-[11px] text-amber-800">
                  {preview.date_formats.length === 0
                    ? "No known format fits this column. Every row would be dropped."
                    : "This column reads as more than one date. 01-04-2024 is 1 April or 4 January — pick the right one."}
                </p>
                <select
                  id="date-format"
                  value={dateFormat}
                  onChange={(e) => setDateFormat(e.target.value)}
                  className="mt-2 text-xs border border-amber-300 rounded-md px-2 py-1.5 bg-white font-mono"
                >
                  <option value="">— choose —</option>
                  {preview.date_formats.map((f) => (
                    <option key={f} value={f}>
                      {f === "%d-%m-%Y" ? `${f}  (day first)` : f === "%m-%d-%Y" ? `${f}  (month first)` : f}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div className="space-y-3">
              {[...REQUIRED, ...OPTIONAL].map((field) => {
                const required = (REQUIRED as readonly string[]).includes(field);
                return (
                  <div key={field} className="grid grid-cols-1 sm:grid-cols-3 gap-2 items-center">
                    <label htmlFor={`map-${field}`} className="text-xs">
                      <span className="font-mono font-medium text-slate-900">{field}</span>
                      {required && <span className="ml-1 text-red-600">*</span>}
                      <span className="block text-slate-500">{FIELD_HELP[field]}</span>
                    </label>
                    <select
                      id={`map-${field}`}
                      value={mapping[field] ?? ""}
                      onChange={(e) =>
                        setMapping((m) => ({ ...m, [field]: e.target.value }))
                      }
                      className="sm:col-span-2 text-xs border border-slate-300 rounded-md px-2 py-1.5 bg-white"
                    >
                      <option value="">
                        {required ? "— choose a column —" : "— not in this file —"}
                      </option>
                      {preview.headers.map((h) => (
                        <option key={h} value={h}>
                          {h}
                        </option>
                      ))}
                    </select>
                  </div>
                );
              })}
            </div>
          </div>

          {preview.sample.length > 0 && (
            <div className="p-5 bg-white rounded-xl border border-[#E2E8F0] shadow-xs overflow-x-auto">
              <h3 className="text-sm font-bold text-slate-900 mb-3">First rows of your file</h3>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-slate-500">
                    {preview.headers.slice(0, 8).map((h) => (
                      <th key={h} className="pr-4 pb-2 font-medium whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.sample.map((row, i) => (
                    <tr key={i} className="border-t border-slate-100">
                      {preview.headers.slice(0, 8).map((h) => (
                        <td key={h} className="pr-4 py-1.5 text-slate-700 whitespace-nowrap">
                          {row[h] ?? ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="p-5 bg-white rounded-xl border border-[#E2E8F0] shadow-xs flex flex-wrap items-end gap-3">
            <div>
              <label htmlFor="dataset" className="block text-xs font-medium text-slate-700">
                Name this dataset
              </label>
              <input
                id="dataset"
                value={dataset}
                onChange={(e) => setDataset(e.target.value)}
                className="mt-1 text-xs font-mono border border-slate-300 rounded-md px-2 py-1.5"
                placeholder="q1_2026_purchases"
              />
              <span className="block mt-1 text-[11px] text-slate-500">
                Lowercase letters, numbers and underscores.
              </span>
            </div>
            <button
              type="button"
              disabled={!ready || busy !== null}
              onClick={() => void onIngest()}
              className="px-4 py-2 rounded-md bg-slate-900 text-white text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-2"
            >
              {busy === "ingest" && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Load {preview.rows.toLocaleString()} rows
            </button>
          </div>
        </>
      )}

      {done && (
        <div className="p-5 bg-white rounded-xl border border-emerald-300 shadow-xs space-y-3">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            <h3 className="text-sm font-bold text-slate-900">
              Loaded {done.rows_loaded.toLocaleString()} of {done.rows_read.toLocaleString()} rows
            </h3>
          </div>
          {done.rows_dropped > 0 && (
            <p className="text-xs text-slate-600">
              {done.rows_dropped.toLocaleString()} rows were dropped:{" "}
              {Object.entries(done.dropped)
                .map(([reason, n]) => `${n.toLocaleString()} ${reason.replace(/_/g, " ")}`)
                .join(", ")}
              .
            </p>
          )}
          <p className="text-xs text-slate-600">
            Stored as <span className="font-mono">{done.dataset}</span>, checksum{" "}
            <span className="font-mono">{done.source_sha256.slice(0, 12)}…</span>. Detection does
            not run inside a web request, so run these next:
          </p>
          <pre className="text-[11px] bg-slate-900 text-slate-100 rounded-md p-3 overflow-x-auto">
            {done.next_steps.join("\n")}
          </pre>
        </div>
      )}
    </div>
  );
}
