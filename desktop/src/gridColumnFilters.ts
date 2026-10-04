import type { ColumnFilter } from "./dataTypes";
import type { Column, ColumnValues, Primitive } from "./runtime";
import { getLocale, type Locale } from "./i18n";

export type GridColumnFilter = ColumnFilter;
export type ColumnValueSuggestions = ColumnValues;
export type ColumnFilterKind = ColumnValues["kind"];
export type ColumnFilterOperator = "between" | "contains" | "equals" | "starts_with" | "ends_with" | "gt" | "gte" | "lt" | "lte";
export interface ColumnFilterDraft {
  kind: ColumnFilterKind;
  presence: "value" | "is_null" | "not_null";
  operator: ColumnFilterOperator;
  value: string;
  valueTo: string;
  booleanValue: "any" | "true" | "false";
  /** Preserve persisted scalar/multiple rules until the user edits the draft. */
  original?: ColumnFilter[];
}
export type ColumnFilterBuild = { ok: true; filters: ColumnFilter[] } | { ok: false; field: "value" | "valueTo"; error: string };

const phrase = (locale: Locale, pt: string, en: string) => locale === "en-US" ? en : pt;

export function inferColumnFilterKind(dtype: string, suggestion?: ColumnFilterKind): ColumnFilterKind {
  if (suggestion) return suggestion;
  if (/bool/i.test(dtype)) return "bool";
  if (/date|timestamp/i.test(dtype)) return "date";
  if (/\b(?:u?int\d*|float\d*|double|decimal\d*|numeric|number|real)\b/i.test(dtype)) return "number";
  return "text";
}

export function columnFilterDraft(column: Column, filters: readonly ColumnFilter[], kind = inferColumnFilterKind(column.dtype)): ColumnFilterDraft {
  const original = filters.filter(filter => filter.column === column.name).map(filter => ({ ...filter }));
  const first = original[0];
  const operators: readonly string[] = ["between", "contains", "equals", "starts_with", "ends_with", "gt", "gte", "lt", "lte"];
  const boolean = String(first?.value ?? "").trim().toLocaleLowerCase();
  return {
    kind,
    presence: first?.operator === "is_null" || first?.operator === "not_null" ? first.operator : "value",
    operator: first?.operator && operators.includes(first.operator) ? first.operator as ColumnFilterOperator : kind === "number" || kind === "date" ? "between" : "contains",
    value: first?.value == null ? "" : String(first.value),
    valueTo: first?.value_to == null ? "" : String(first.value_to),
    booleanValue: ["true", "1", "t", "yes", "y", "sim", "s"].includes(boolean) ? "true" : ["false", "0", "f", "no", "n", "nao", "não"].includes(boolean) ? "false" : "any",
    original,
  };
}

/** Inputs cross the broker as strings; never round a Decimal/large integer. */
export function normalizeNumericFilter(value: string): string | undefined {
  const normalized = value.trim().replace(",", ".");
  if (normalized.length > 1024 || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(normalized)) return;
  const exponent = Number(normalized.match(/[eE]([+-]?\d+)$/)?.[1] ?? 0);
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 1000) return;
  return normalized;
}

/** Exact decimal ordering using digit strings; exponent size never allocates zeros. */
export function compareNumericFilters(left: string, right: string): number | undefined {
  const parse = (value: string) => {
    const normalized = normalizeNumericFilter(value);
    if (normalized === undefined) return;
    const match = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(normalized)!;
    const digits = (match[2] + (match[3] ?? "")).replace(/^0+/, "");
    return { sign: digits ? match[1] === "-" ? -1 : 1 : 0, digits, magnitude: digits.length - (match[3]?.length ?? 0) + Number(match[4] ?? 0) };
  };
  const a = parse(left), b = parse(right);
  if (!a || !b) return;
  if (a.sign !== b.sign) return Math.sign(a.sign - b.sign);
  if (!a.sign) return 0;
  if (a.magnitude !== b.magnitude) return Math.sign(a.magnitude - b.magnitude) * a.sign;
  for (let index = 0; index < Math.max(a.digits.length, b.digits.length); index++) {
    const delta = (a.digits.charCodeAt(index) || 48) - (b.digits.charCodeAt(index) || 48);
    if (delta) return Math.sign(delta) * a.sign;
  }
  return 0;
}

function parsedDateFilter(value: string, endOfDay = false): { instant: bigint; zoned: boolean } | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|[+-]\d{2}:\d{2})?)?$/.exec(value);
  if (!match) return;
  const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
  if (year < 1 || month < 1 || month > 12 || day < 1) return;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  if (day > [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]) return;
  if (Number(match[4] ?? 0) > 23 || Number(match[5] ?? 0) > 59 || Number(match[6] ?? 0) > 59) return;
  if (match[8] && match[8] !== "Z" && (Number(match[8].slice(1, 3)) > 23 || Number(match[8].slice(4, 6)) > 59)) return;
  const dateOnly = !match[4];
  const date = `${match[1]}-${match[2]}-${match[3]}`;
  const clock = dateOnly && endOfDay ? "23:59:59" : `${match[4] ?? "00"}:${match[5] ?? "00"}:${match[6] ?? "00"}`;
  const epoch = Date.parse(`${date}T${clock}${match[8] ?? "Z"}`);
  if (!Number.isFinite(epoch)) return;
  const fraction = dateOnly && endOfDay ? "999999999" : (match[7] ?? "").padEnd(9, "0");
  return { instant: BigInt(epoch) * 1_000_000n + BigInt(fraction), zoned: Boolean(match[8]) };
}

export function validDateFilter(value: string): boolean {
  return parsedDateFilter(value) !== undefined;
}

export function compareDateFilters(lower: string, upper: string): number | undefined {
  const a = parsedDateFilter(lower), b = parsedDateFilter(upper, true);
  // A naive bound is localized by the broker to the column's timezone. Only the
  // broker can order a mixed naive/zoned pair; avoid a false browser rejection.
  if (!a || !b || a.zoned !== b.zoned) return;
  return a.instant === b.instant ? 0 : a.instant > b.instant ? 1 : -1;
}

export function draftToColumnFilters(column: string, draft: ColumnFilterDraft, locale: Locale = getLocale()): ColumnFilterBuild {
  if (draft.original) return { ok: true, filters: draft.original.map(filter => ({ ...filter })) };
  if (draft.presence !== "value") return { ok: true, filters: [{ column, operator: draft.presence }] };
  if (draft.kind === "bool") return { ok: true, filters: draft.booleanValue === "any" ? [] : [{ column, operator: "equals", value: draft.booleanValue === "true" }] };
  const textOperator = ["contains", "starts_with", "ends_with"].includes(draft.operator);
  if (draft.kind === "text" || textOperator) {
    if (draft.value.length > 1000 || draft.valueTo.length > 1000) return { ok: false, field: draft.value.length > 1000 ? "value" : "valueTo", error: phrase(locale, "Use até 1.000 caracteres no filtro.", "Use up to 1,000 characters in the filter.") };
    if (draft.operator === "between") return { ok: true, filters: !draft.value && !draft.valueTo ? [] : [{ column, operator: "between", ...(draft.value ? { value: draft.value } : {}), ...(draft.valueTo ? { value_to: draft.valueTo } : {}) }] };
    return { ok: true, filters: !draft.value && draft.operator !== "equals" ? [] : [{ column, operator: draft.operator, value: draft.value }] };
  }
  const range = draft.operator === "between";
  const rawMin = draft.value.trim(), rawMax = range ? draft.valueTo.trim() : "";
  if (!rawMin && !rawMax) return { ok: true, filters: [] };
  let value: string | undefined, valueTo: string | undefined;
  for (const [field, raw] of [["value", rawMin], ["valueTo", rawMax]] as const) {
    if (!raw) continue;
    const normalized = draft.kind === "number" ? normalizeNumericFilter(raw) : validDateFilter(raw) ? raw : undefined;
    if (normalized === undefined) return { ok: false, field, error: draft.kind === "number"
      ? phrase(locale, "Digite um número válido, como 12,5 ou 1.2e3, sem separador de milhar.", "Enter a valid number, such as 12.5 or 1.2e3, without thousands separators.")
      : phrase(locale, "Digite uma data válida (AAAA-MM-DD) ou data/hora ISO, ou use o calendário.", "Enter a valid date (YYYY-MM-DD) or ISO timestamp, or use the calendar.") };
    if (field === "value") value = normalized; else valueTo = normalized;
  }
  if (range && value !== undefined && valueTo !== undefined && (draft.kind === "number" ? compareNumericFilters(value, valueTo)! > 0 : (compareDateFilters(value, valueTo) ?? 0) > 0)) {
    return { ok: false, field: "valueTo", error: phrase(locale, "O limite final deve ser maior ou igual ao inicial.", "The upper bound must be greater than or equal to the lower bound.") };
  }
  return { ok: true, filters: [{ column, operator: draft.operator, ...(value === undefined ? {} : { value }), ...(valueTo === undefined ? {} : { value_to: valueTo }) }] };
}

export function replaceColumnFilters(filters: readonly ColumnFilter[], column: string, replacements: readonly ColumnFilter[]): ColumnFilter[] {
  const first = filters.findIndex(filter => filter.column === column);
  const result = filters.filter(filter => filter.column !== column).map(filter => ({ ...filter }));
  result.splice(first < 0 ? result.length : first, 0, ...replacements.filter(filter => filter.column === column).map(filter => ({ ...filter })));
  return result;
}

export function filterSummary(filters: readonly ColumnFilter[], locale: Locale = getLocale()): string {
  const display = (value: Primitive | undefined) => value === true ? phrase(locale, "Verdadeiro", "True") : value === false ? phrase(locale, "Falso", "False") : value === null ? "NULL" : String(value ?? "");
  return filters.map(filter => {
    const value = display(filter.value), upper = display(filter.value_to);
    switch (filter.operator ?? "contains") {
      case "is_null": return `${filter.column}: NULL`;
      case "not_null": return `${filter.column}: ${phrase(locale, "não nulo", "not null")}`;
      case "between": return filter.value === undefined ? `${filter.column} ≤ ${upper}` : filter.value_to === undefined ? `${filter.column} ≥ ${value}` : `${filter.column}: ${value} … ${upper}`;
      case "equals": return `${filter.column} = ${value === "" ? '""' : value}`;
      case "gt": return `${filter.column} > ${value}`;
      case "gte": return `${filter.column} ≥ ${value}`;
      case "lt": return `${filter.column} < ${value}`;
      case "lte": return `${filter.column} ≤ ${value}`;
      case "starts_with": return `${filter.column}: ${phrase(locale, "começa com", "starts with")} ${value}`;
      case "ends_with": return `${filter.column}: ${phrase(locale, "termina com", "ends with")} ${value}`;
      default: return `${filter.column}: ${phrase(locale, "contém", "contains")} ${value}`;
    }
  }).join("; ");
}

export interface HeaderPopupAnchor { x: number; y: number; width: number; height: number }
export function headerPopupPosition(anchor: HeaderPopupAnchor, size: { width: number; height: number }, viewport: { width: number; height: number }, margin = 8): { left: number; top: number } {
  const availableX = Math.max(margin, viewport.width - size.width - margin);
  const below = anchor.y + anchor.height + 4;
  const top = below + size.height <= viewport.height - margin ? below : Math.max(margin, anchor.y - size.height - 4);
  return { left: Math.min(Math.max(margin, anchor.x + anchor.width - size.width), availableX), top: Math.min(top, Math.max(margin, viewport.height - size.height - margin)) };
}
