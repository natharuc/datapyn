import type { DataView } from "./dataTypes";
import type { ExportSettings } from "./exportSettings";
import type { RuntimeTransport } from "./runtime";

export const EXPORT_FORMATS = ["csv", "tsv", "txt", "xlsx", "json", "parquet", "sql"] as const;
export type ExportFormat = typeof EXPORT_FORMATS[number];
export type ExportDestination = "file" | "clipboard";
export type SqlExportMode = "insert" | "create" | "create_insert";
export interface ExportConnection { id: string; name: string; db_type: string; database?: string }
export interface FormatExportSettings {
  includeIndex: boolean; sheetName: string; jsonOrient: "records" | "split" | "index" | "columns" | "values" | "table";
  jsonIndent: number; jsonLines: boolean; compression: "snappy" | "gzip" | "zstd" | "none";
  sqlMode: SqlExportMode; sqlDialect: string; sqlBatchSize: number; sqlTransaction: boolean; sqlGo: boolean;
}
export const DEFAULT_FORMAT_EXPORT_SETTINGS: FormatExportSettings = {
  includeIndex: false, sheetName: "DataPyn", jsonOrient: "records", jsonIndent: 2, jsonLines: false,
  compression: "snappy", sqlMode: "insert", sqlDialect: "sqlserver", sqlBatchSize: 1, sqlTransaction: false, sqlGo: false,
};
export interface ExportProgress {
  session_id: string; operation_id: string; phase: "preparing" | "writing" | "completed" | "cancelled";
  current: number; total: number;
}
export interface ExportTextResult { text: string; row_count: number; column_count: number; format: string }
export function exportSource(sessionId: string, resultId: string | undefined, view?: DataView, selected = false): Record<string, unknown> {
  return { session_id: sessionId, result_id: resultId, filter: view?.filter, sort: view?.sort,
    ...(selected && view?.scope ? { scope: view.scope } : {}) };
}
/** SQL uses original kernel values, retaining Decimal, bigint and binary precision. */
export async function requestSqlText(transport: Pick<RuntimeTransport,"request">, source: Record<string,unknown>, tableName: string, dbType: string, isCurrent: () => boolean): Promise<ExportTextResult> {
  if (!tableName.trim()) throw new Error("Informe um nome de tabela válido.");
  const exported = await transport.request<ExportTextResult>("result.export_text", {...source,format:"sql",options:{table_name:tableName,db_type:dbType,sql_mode:"insert",batch_size:1}});
  if (!isCurrent()) throw new Error("Os resultados mudaram durante a cópia. Selecione novamente.");
  if (typeof exported.text !== "string") throw new Error("Resposta de resultados inválida.");
  return exported;
}
export function clipboardFormat(format: ExportFormat): string {
  if (format === "parquet") throw new Error("Parquet requer um arquivo de destino.");
  return format === "xlsx" ? "excel" : format;
}
export function exportPath(path: string, format: ExportFormat): string {
  return path.toLowerCase().endsWith(`.${format}`) ? path : `${path}.${format}`;
}
export function exportOptions(format: ExportFormat, csv: ExportSettings, settings: FormatExportSettings, table: string, schema: string): Record<string, unknown> {
  const common = { include_header: csv.include_header, index: settings.includeIndex };
  if (["csv", "tsv", "txt"].includes(format)) return { ...common, delimiter: format === "tsv" ? "\t" : csv.delimiter, decimal: csv.decimal, encoding: csv.encoding };
  if (format === "xlsx") return { ...common, sheet_name: settings.sheetName.trim() || "DataPyn" };
  if (format === "json") return { index: settings.includeIndex, orient: settings.jsonOrient, indent: settings.jsonIndent, lines: settings.jsonLines && settings.jsonOrient === "records" };
  if (format === "parquet") return { index: settings.includeIndex, compression: settings.compression === "none" ? null : settings.compression };
  return { table_name: table.trim(), table_name_literal: true, schema_name: schema.trim() || undefined, db_type: settings.sqlDialect,
    sql_mode: settings.sqlMode, batch_size: settings.sqlBatchSize, include_transaction: settings.sqlTransaction && (settings.sqlDialect !== "databricks" || settings.sqlMode === "insert"),
    include_go: settings.sqlGo && ["sqlserver", "mssql"].includes(settings.sqlDialect) };
}
export function temporaryTableName(table: string, temporary: boolean, dialect?: string): string {
  const value = table.trim();
  return temporary && ["sqlserver", "mssql"].includes(dialect ?? "") && !value.startsWith("#") ? `#${value}` : value;
}
export function readExportProgress(event: unknown): ExportProgress | undefined {
  if (!event || typeof event !== "object") return;
  const { event: name, payload } = event as { event?: unknown; payload?: Partial<ExportProgress> };
  if (name !== "result.export_progress" || !payload || typeof payload.session_id !== "string" || typeof payload.operation_id !== "string"
    || !["preparing", "writing", "completed", "cancelled"].includes(String(payload.phase))
    || typeof payload.current !== "number" || !Number.isFinite(payload.current) || payload.current < 0
    || typeof payload.total !== "number" || !Number.isFinite(payload.total) || payload.total < 0) return;
  return payload as ExportProgress;
}
export function exportProgressPercent(progress: ExportProgress | undefined): number | undefined {
  if (!progress || progress.total <= 0) return;
  return Math.min(100, Math.max(0, Math.floor(progress.current / progress.total * 100)));
}
