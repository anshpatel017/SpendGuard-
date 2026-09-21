// Display formatting. Money arrives from the API as a decimal string and is
// formatted as a string, never through a float, so the rupees shown are exactly
// the rupees stored. Indian digit grouping (lakh, crore) mirrors the backend's
// settings.money(): 1234567.5 -> Rs 12,34,567.50 (FR-6.10).
import type { AnomalyType, CaseStatus, SeverityBand, Verdict } from "../api/types";

const DASH = "—";

export function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const tail = digits.slice(-3);
  let head = digits.slice(0, -3);
  const groups: string[] = [];
  while (head.length > 2) {
    groups.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) groups.unshift(head);
  return [...groups, tail].join(",");
}

export function formatMoney(value: string | null | undefined, symbol = "₹"): string {
  if (value === null || value === undefined || value === "") return DASH;
  const match = /^(-?)(\d*)(?:\.(\d*))?$/.exec(value.trim());
  if (!match) return value;
  const [, sign = "", whole = "0", fraction = ""] = match;
  const paise = (fraction + "00").slice(0, 2);
  const isZero = /^0*$/.test(whole) && /^0*$/.test(paise);
  const digits = whole.replace(/^0+(?=\d)/, "") || "0";
  return `${sign && !isZero ? "-" : ""}${symbol}${groupIndian(digits)}.${paise}`;
}

/** Large amounts in words an Indian auditor reads at a glance: "₹9.77 crore". */
export function formatMoneyShort(value: string | null | undefined): string {
  if (!value) return DASH;
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  if (Math.abs(amount) >= 1e7) return `₹${(amount / 1e7).toFixed(2)} crore`;
  if (Math.abs(amount) >= 1e5) return `₹${(amount / 1e5).toFixed(2)} lakh`;
  return formatMoney(value);
}

export function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined ? DASH : groupIndian(String(Math.trunc(value)));
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  return value === null || value === undefined ? DASH : `${(value * 100).toFixed(digits)}%`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2024-08-21" -> "21 Aug 2024". Parsed by hand: `new Date` would shift a date-only string by timezone. */
export function formatDate(value: string | null | undefined): string {
  const match = value ? /^(\d{4})-(\d{2})-(\d{2})/.exec(value) : null;
  if (!match) return value ?? DASH;
  const [, year, month, day] = match;
  return `${day} ${MONTHS[Number(month) - 1] ?? month} ${year}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return DASH;
  const date = new Date(value.endsWith("Z") || value.includes("+") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

// Wording discipline (CLAUDE.md): a duplicate is a duplicate *transaction record*.
export const ANOMALY_LABEL: Record<AnomalyType, string> = {
  duplicate: "Duplicate record",
  split: "Split purchase",
  inflation: "Price inflation",
  vendor_flag: "Vendor red flag",
};

export const STATUS_LABEL: Record<CaseStatus, string> = {
  new: "New",
  under_review: "Under review",
  confirmed: "Confirmed",
  dismissed: "Dismissed",
};

export const VERDICT_LABEL: Record<Verdict, string> = {
  likely_true_positive: "Likely genuine",
  likely_false_positive: "Likely false positive",
  inconclusive: "Inconclusive",
};

export const BAND_LABEL: Record<SeverityBand, string> = { high: "High", medium: "Medium", low: "Low" };
