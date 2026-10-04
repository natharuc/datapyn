import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { NotificationResult } from "./NotificationsDialog";

export type Language = "sql" | "python";
export type Primitive = null | string | number | boolean;
export interface Column { name: string; dtype: string }
export interface ResultRef { result_id: string; variable_name: string; columns: Column[]; row_count: number }
export interface Variable { name: string; type: string; preview: string }
export interface LanguageContextUpdate {
  session_id: string; connection_id?: string; database?: string; schema?: string; version: number;
  variables: Record<string, {type: string; module?: string; columns?: string[]}>;
  metadata_invalidated?: boolean;
  schema_snapshot?: {db_type?: string; tables?: Array<{key?: string; name: string; schema?: string; temporary?: boolean}>;
    columns?: Record<string, Array<{name: string; type?: string; data_type?: string}>>};
}
export interface ResultExportProgress {
  session_id: string; operation_id: string;
  phase: "preparing" | "writing" | "completed" | "cancelled";
  current: number; total: number;
}
export interface ResultPage { columns: Column[]; rows: Primitive[][]; total_rows: number; offset: number; column_offset?: number; total_columns?: number }
export interface ColumnValues { values: Primitive[]; kind: "text" | "number" | "bool" | "date"; sampled: boolean; scanned_rows: number; total_rows: number }
export interface RuntimeInfo { protocol_version: number; python_version: string; capabilities: Record<string, unknown> | string[] }
export type RichOutput = {artifact_id?:string;type:"image";data:string;mime:string}|{artifact_id?:string;type:"html";data:string}|{artifact_id?:string;type:"json"|"plotly";data:unknown};
export interface ExecutionFinished {
  session_id: string; execution_id: string; status: "succeeded" | "failed" | "cancelled";
  duration_ms: number; error?: string; results: ResultRef[]; variables: Variable[];
  rich_outputs?: RichOutput[];
  notification?: NotificationResult;
  notification_error?: string;
  export?: {files:Array<{path:string;rows:number;columns:number;size_bytes:number}>;total_rows:number;cancelled:boolean;errors:string[]};
}
export type RuntimeEvent =
  | { event: "notifications.delivery_finished"; payload: {session_id:string;execution_id:string;block_id?:string;workspace_id?:string;deliveries:Record<string,{status:string;error?:string}>} }
  | { event: "execution.started"; payload: { session_id: string; execution_id: string } }
  | { event: "execution.output"; payload: { session_id: string; execution_id: string; stream: string; text: string } }
  | { event: "execution.export_progress"; payload: {session_id:string;execution_id:string;path:string;rows:number;size_bytes:number;total_rows:number} }
  | { event: "execution.finished"; payload: ExecutionFinished }
  | { event: "session.ready"; payload: { session_id: string } }
  | { event: "session.error"; payload: { session_id: string; error: string } }
  | { event: "session.reset"; payload: { session_id: string; reason?: string } }
  | { event: "namespace.changed"; payload: {session_id:string;variables:Variable[];results:ResultRef[]} }
  | { event: "language.context_updated"; payload: LanguageContextUpdate }
  | { event: "result.export_progress"; payload: ResultExportProgress }
  | { event: "backend.exited"; payload: { message: string } };

export function isRuntimeEvent(value: unknown): value is RuntimeEvent {
  if (!value || typeof value !== "object") return false;
  const { event, payload } = value as { event?: unknown; payload?: Record<string, unknown> };
  if (!payload || typeof payload !== "object") return false;
  if (event === "backend.exited") return typeof payload.message === "string";
  if (typeof payload.session_id !== "string") return false;
  if (event === "session.ready" || event === "session.reset") return true;
  if (event === "session.error") return typeof payload.error === "string";
  if (event === "notifications.delivery_finished") return typeof payload.execution_id === "string" && Boolean(payload.deliveries && typeof payload.deliveries === "object");
  if (event === "namespace.changed") return Array.isArray(payload.variables) && Array.isArray(payload.results);
  if (event === "language.context_updated") return typeof payload.version === "number" && Number.isFinite(payload.version)
    && Boolean(payload.variables && typeof payload.variables === "object" && !Array.isArray(payload.variables));
  if (event === "result.export_progress") return typeof payload.operation_id === "string" && Boolean(payload.operation_id)
    && ["preparing", "writing", "completed", "cancelled"].includes(String(payload.phase))
    && typeof payload.current === "number" && Number.isFinite(payload.current) && payload.current >= 0
    && typeof payload.total === "number" && Number.isFinite(payload.total) && payload.total >= 0;
  if (typeof payload.execution_id !== "string") return false;
  if (event === "execution.started") return true;
  if (event === "execution.output") return typeof payload.stream === "string" && typeof payload.text === "string";
  if (event === "execution.export_progress") return typeof payload.path === "string" && typeof payload.rows === "number";
  return event === "execution.finished" && ["succeeded", "failed", "cancelled"].includes(String(payload.status));
}

export interface RuntimeTransport {
  request<T>(method: string, params?: Record<string, unknown>): Promise<T>;
  subscribe(callback: (event: RuntimeEvent) => void): Promise<() => void>;
}

export class BackendUnavailableError extends Error {
  constructor() { super("Execução indisponível no navegador. Abra o aplicativo DataPyn para usar o runtime Python."); }
}

export const runtime: RuntimeTransport = {
  async request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    if (!isTauri()) throw new BackendUnavailableError();
    return invoke<T>("backend_request", { method, params });
  },
  async subscribe(callback): Promise<UnlistenFn> {
    if (!isTauri()) return () => {};
    return listen<unknown>("runtime-event", ({ payload }) => { if (isRuntimeEvent(payload)) callback(payload); });
  },
};

export const isDesktop = () => isTauri();
export const errorText = (error: unknown) => error instanceof Error ? error.message : typeof error === "string" ? error : JSON.stringify(error);
