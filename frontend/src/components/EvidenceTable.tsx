// The rows behind the case (FR-6.4): the case's own rows first, visually marked,
// then context - rows the note cites beyond the case, and the supplier's rows
// nearest in time. The row a citation points at is highlighted and scrolled to.
import { useEffect } from "react";

import type { TransactionRow } from "../api/types";
import { formatDate, formatMoney } from "../lib/format";
import { Card } from "./common";

function Rows({ rows, highlight }: { rows: TransactionRow[]; highlight: number | null }) {
  return (
    <>
      {rows.map((r) => (
        <tr key={`${r.in_case}-${r.row_id}`} id={`row-${r.row_id}`}
          className={[r.in_case ? "in-case" : "", highlight === r.row_id ? "highlight" : ""].join(" ")}>
          <td className="mono">
            {r.row_id}
            {r.cited && <span className="chip outline" style={{ marginLeft: 6 }} title="The audit note cites this row">cited</span>}
          </td>
          <td>{formatDate(r.txn_date)}</td>
          <td>{r.vendor_name}</td>
          <td className="mono">{r.invoice_no ?? "—"}</td>
          <td>{r.item_desc ?? "—"}</td>
          <td className="num">{r.quantity ?? "—"}</td>
          <td className="num">{formatMoney(r.unit_price)}</td>
          <td className="num"><strong>{formatMoney(r.amount)}</strong></td>
          <td className="mono">{r.officer_id ?? "—"}</td>
        </tr>
      ))}
    </>
  );
}

export function EvidenceTable({
  evidence,
  total,
  context,
  highlight,
}: {
  evidence: TransactionRow[];
  total: number;
  context: TransactionRow[];
  highlight: number | null;
}) {
  useEffect(() => {
    if (highlight !== null) document.getElementById(`row-${highlight}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlight]);

  return (
    <Card
      title={`Evidence · ${total} row${total === 1 ? "" : "s"} in the case`}
      actions={<span className="muted small">Shaded rows are the case; the rest are context for comparison.</span>}
    >
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Row</th><th>Date</th><th>Supplier</th><th>Invoice</th><th>Item</th>
              <th className="num">Qty</th><th className="num">Unit price</th><th className="num">Amount</th><th>Officer</th>
            </tr>
          </thead>
          <tbody>
            <Rows rows={evidence} highlight={highlight} />
            {context.length > 0 && (
              <tr>
                <td colSpan={9} className="muted small" style={{ background: "var(--surface-2)" }}>
                  Context: rows the note cites outside the case, then the same supplier's rows nearest in time
                </td>
              </tr>
            )}
            <Rows rows={context} highlight={highlight} />
          </tbody>
        </table>
      </div>
      {evidence.length < total && (
        <div className="muted small" style={{ marginTop: 8 }}>
          Showing the first {evidence.length} of {total} case rows.
        </div>
      )}
    </Card>
  );
}
