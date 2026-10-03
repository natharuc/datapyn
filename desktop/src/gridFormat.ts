import type { Primitive } from "./runtime";

export interface ColumnFormat {
  type: "default" | "number" | "currency" | "percent" | "date" | "datetime";
  decimals?: number;
  prefix?: string;
  suffix?: string;
}
export type ColumnFormats = Record<string, ColumnFormat>;

/** Decimal strings from the Python broker can exceed JavaScript's numeric precision. */
export function decimalDisplay(value: Primitive, decimals = 2, percent = false): string | undefined {
  const text = String(value), match = /^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text);
  if (!match || text.length > 1024) return;
  const places = Number.isFinite(decimals) ? Math.max(0, Math.min(8, Math.trunc(decimals))) : 2, exponent = Number(match[4] ?? 0);
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 1000) return;
  const digits = BigInt(match[2] + (match[3] ?? "")), scale = (match[3]?.length ?? 0) - exponent - (percent ? 2 : 0);
  let rounded: bigint;
  if (scale <= places) rounded = digits * 10n ** BigInt(places - scale);
  else { const divisor = 10n ** BigInt(scale - places); rounded = digits / divisor + (digits % divisor * 2n >= divisor ? 1n : 0n); }
  const padded = rounded.toString().padStart(places + 1, "0"), whole = places ? padded.slice(0, -places) : padded;
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${match[1] === "-" ? "-" : ""}${grouped}${places ? "." + padded.slice(-places) : ""}`;
}

/** Keep the database wall clock when displaying ISO timestamps instead of applying a browser timezone. */
export function dateDisplay(value: Primitive, includeTime: boolean): string | undefined {
  if (typeof value === "string") {
    const iso = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2}))?/.exec(value);
    if (iso) return includeTime ? `${iso[1]} ${iso[2] ?? "00:00:00"}` : iso[1];
  }
  const epoch = typeof value === "number" ? value : typeof value === "string" && /^\d+(?:\.\d+)?$/.test(value) ? Number(value) : NaN;
  if (!Number.isFinite(epoch) || epoch < 1e9) return;
  const milliseconds = epoch >= 1e17 ? epoch / 1e6 : epoch >= 1e14 ? epoch / 1e3 : epoch >= 1e11 ? epoch : epoch * 1000;
  const date = new Date(milliseconds), year = date.getUTCFullYear();
  if (!Number.isFinite(date.getTime()) || year < 1970 || year > 2100) return;
  const iso = date.toISOString(); return includeTime ? iso.slice(0, 19).replace("T", " ") : iso.slice(0, 10);
}

export function formatCell(value: Primitive, format?: ColumnFormat, nullDisplay = "∅"): string {
  if (value === null) return nullDisplay;
  if (!format || format.type === "default") return String(value);
  if (format.type === "date" || format.type === "datetime") return dateDisplay(value, format.type === "datetime") ?? String(value);
  const number = decimalDisplay(value, format.decimals ?? 2, format.type === "percent");
  return number === undefined ? String(value) : `${format.prefix ?? (format.type === "currency" ? "$ " : "")}${number}${format.suffix ?? (format.type === "percent" ? "%" : "")}`;
}
