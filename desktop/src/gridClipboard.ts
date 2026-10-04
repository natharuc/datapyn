import type { Rectangle } from "@glideapps/glide-data-grid";
import type { Primitive } from "./runtime";
import type { ColumnFormats } from "./gridFormat";
import { formatCell } from "./gridFormat";
import { quoteIdentifier, quoteIdentifierPart } from "./explorer";

import { MAX_COPY_CELLS, utf8Bytes } from "./clipboardLimits";
export { MAX_COPY_CELLS, MAX_CLIPBOARD_BYTES } from "./clipboardLimits";
export interface CopyTable { columns: string[]; rows: Array<Array<Primitive | undefined>> }
export interface CopyOptions { headers?: boolean; separator?: string; nullDisplay?: string; formats?: ColumnFormats; raw?: boolean }
export type CopyFormat = "excel" | "plain" | "json" | "sql";

export function selectedLayout(rectangles: Rectangle[]) {
  const rowRanges: Array<[number,number]> = [], columnRanges: Array<[number,number]> = [];
  for (const r of rectangles) {
    if (![r.x, r.y, r.width, r.height, r.x+r.width, r.y+r.height].every(Number.isSafeInteger) || r.x < 0 || r.y < 0 || r.width <= 0 || r.height <= 0) throw new Error("Seleção inválida.");
    if (r.width * r.height > MAX_COPY_CELLS) throw new Error("Use a exportação para seleções com mais de 200 mil células.");
    rowRanges.push([r.y,r.y+r.height]); columnRanges.push([r.x,r.x+r.width]);
  }
  const merge = (ranges:Array<[number,number]>) => {
    ranges.sort((a,b)=>a[0]-b[0]); const merged:Array<[number,number]> = [];
    for(const range of ranges) { const last=merged.at(-1); if(last && last[1]>=range[0]) last[1]=Math.max(last[1],range[1]); else merged.push([...range]); }
    return merged;
  };
  const rows=merge(rowRanges), columns=merge(columnRanges), count=(ranges:Array<[number,number]>)=>ranges.reduce((total,[start,end])=>total+end-start,0);
  if(count(rows)*count(columns)>MAX_COPY_CELLS) throw new Error("Use a exportação para seleções com mais de 200 mil células.");
  const expand=(ranges:Array<[number,number]>)=>{const indices:number[]=[];for(const [start,end] of ranges)for(let index=start;index<end;index++)indices.push(index);return indices;};
  return { rows: expand(rows), columns: expand(columns) };
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
  utf8Bytes(value);
  return value;
}
