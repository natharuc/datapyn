import type { Rectangle } from "@glideapps/glide-data-grid";
import type { Primitive } from "./runtime";
import type { ColumnFormats } from "./gridFormat";
import { formatCell } from "./gridFormat";
import { quoteIdentifier, quoteIdentifierPart } from "./explorer";

export const MAX_COPY_CELLS = 200_000;
export const MAX_CLIPBOARD_BYTES = 16 * 1024 * 1024;
export interface CopyTable { columns: string[]; rows: Array<Array<Primitive | undefined>> }
export interface CopyOptions { headers?: boolean; separator?: string; nullDisplay?: string; formats?: ColumnFormats; raw?: boolean }
export type CopyFormat = "excel" | "plain" | "json" | "sql";

export function selectedLayout(rectangles: Rectangle[]) {
  const rowSet = new Set<number>(), columnSet = new Set<number>();
  for (const r of rectangles) {
    if (![r.x, r.y, r.width, r.height].every(Number.isSafeInteger) || r.x < 0 || r.y < 0 || r.width <= 0 || r.height <= 0) throw new Error("Seleção inválida.");
    if (r.width * r.height > MAX_COPY_CELLS) throw new Error("Use a exportação para seleções com mais de 200 mil células.");
    for (let y = r.y; y < r.y + r.height; y++) rowSet.add(y);
    for (let x = r.x; x < r.x + r.width; x++) columnSet.add(x);
    if (rowSet.size * columnSet.size > MAX_COPY_CELLS) throw new Error("Use a exportação para seleções com mais de 200 mil células.");
  }
  return { rows: [...rowSet].sort((a, b) => a - b), columns: [...columnSet].sort((a, b) => a - b) };
}
export function cellSelected(x: number, y: number, rectangles: Rectangle[]) { return rectangles.some(r => x >= r.x && x < r.x + r.width && y >= r.y && y < r.y + r.height); }
function escapedHtml(value: string) { return value.replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]!); }
function csvCell(value: string, separator: string) { return value.includes(separator) || /[\r\n"]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value; }
function textCell(value: Primitive | undefined, name: string, options: CopyOptions) {
  if (value === undefined) return "";
  return options.raw ? value === null ? options.nullDisplay ?? "" : String(value) : formatCell(value, options.formats?.[name], options.nullDisplay ?? "");
}
export function plainClipboard(table: CopyTable, options: CopyOptions = {}): string {
  const separator = options.separator ?? "\t", rows = table.rows.map(row => row.map((value, index) => textCell(value, table.columns[index], options)));
  if (options.headers) rows.unshift(table.columns);
  return rows.map(row => row.map(value => csvCell(value, separator)).join(separator)).join("\r\n");
}
export function htmlClipboard(table: CopyTable, options: CopyOptions = {}): string {
  const header = options.headers ? `<thead><tr>${table.columns.map(name => `<th>${escapedHtml(name)}</th>`).join("")}</tr></thead>` : "";
  const body = table.rows.map(row => `<tr>${row.map((value, index) => `<td style='mso-number-format:"\\@";white-space:pre-wrap'>${escapedHtml(textCell(value, table.columns[index], options))}</td>`).join("")}</tr>`).join("");
  return `<!doctype html><html><head><meta charset="utf-8"></head><body><table>${header}<tbody>${body}</tbody></table></body></html>`;
}
export function jsonClipboard(table: CopyTable): string {
  if (new Set(table.columns).size !== table.columns.length) return JSON.stringify({ columns: table.columns, rows: table.rows.map(row => row.map(value => value ?? null)) }, null, 2);
  return JSON.stringify(table.rows.map(row => Object.fromEntries(table.columns.map((name, index) => [name, row[index] ?? null]))), null, 2);
}
function sqlValue(value: Primitive | undefined, dialect: string): string {
  if (value === undefined || value === null) return "NULL";
  if (typeof value === "boolean") return /^(postgresql|postgres|duckdb)$/.test(dialect) ? String(value).toUpperCase() : value ? "1" : "0";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "NULL";
  return "'" + value.replace(/'/g, "''") + "'";
}
export function sqlClipboard(table: CopyTable, tableName: string, dialect = "postgresql"): string {
  if (!tableName.trim() || /[\0\r\n]/.test(tableName)) throw new Error("Informe um nome de tabela válido.");
  const target = quoteIdentifier(tableName.trim(), dialect), columns = table.columns.map(name => quoteIdentifierPart(name, dialect)).join(", ");
  return table.rows.map(row => `INSERT INTO ${target} (${columns}) VALUES (${row.map(value => sqlValue(value, dialect)).join(", ")});`).join("\n");
}
export function boundedClipboard(value: string) {
  if (new TextEncoder().encode(value).byteLength > MAX_CLIPBOARD_BYTES) throw new Error("A cópia excede 16 MB. Reduza a seleção ou use a exportação.");
  return value;
}
