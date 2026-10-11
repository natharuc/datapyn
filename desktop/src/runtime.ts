import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { NotificationResult } from "./NotificationsDialog";
import type { DataImportProgress } from "./dataImport";
import { cancelSshHostTrust, requestSshHostTrust, SshHostTrustCancelledError, type SshHostKeyDetails } from "./sshHostTrust";

export type Language = "sql" | "python";
export type Primitive = null | string | number | boolean;
export interface Column { name: string; dtype: string }
export interface ResultRef { result_id: string; variable_name: string; columns: Column[]; row_count: number }
export interface SqlCommandResult { statement_index: number; command: string; rows_affected: number | null }
export interface Variable { name: string; type: string; preview: string }
export interface LanguageContextUpdate {
  session_id: string; block_id?: string; connection_id?: string; database?: string; schema?: string; version: number;
  scope_inherited?: boolean;
  variables: Record<string, {type: string; module?: string; columns?: string[]}>;
  metadata_invalidated?: boolean;
  metadata_invalidation_scope?: "connection" | "block";
  metadata_state?: "ready" | "error";
  schema_error?: string | null;
  requested_scope?: {connection_id?:string|null;database?:string|null;schema?:string|null};
  schema_snapshot?: {db_type?: string; database?: string; current_schema?: string; default_schema?: string; tables?: Array<{key?: string; name: string; schema?: string; catalog?: string; temporary?: boolean}>;
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
export interface SqlContextScope { db_type?: string; database?: string | null; schema?: string | null }
export interface ExecutionContextChange {
  previous: SqlContextScope;
  current: SqlContextScope;
  connection_id?: string | null;
  requested_scope: { connection_id?: string | null; database?: string | null; schema?: string | null };
}
export interface ExecutionFinished {
  session_id: string; execution_id: string; block_id?: string; status: "succeeded" | "failed" | "cancelled";
  scope_inherited?: boolean;
  duration_ms: number; error?: string; results: ResultRef[]; variables: Variable[];
  rich_outputs?: RichOutput[];
  command_results?: SqlCommandResult[];
  context_change?: ExecutionContextChange;
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
  | { event: "data.import_progress"; payload: DataImportProgress }
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
  if (event === "data.import_progress") return typeof payload.operation_id === "string" && Boolean(payload.operation_id)
    && ["reading", "registering", "completed", "cancelled"].includes(String(payload.phase))
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

export class RuntimeRequestError extends Error {
  constructor(readonly code: string, message: string, readonly details?: Record<string, unknown>) { super(message); }
}

export function runtimeRequestError(error: unknown): Error {
  if (error instanceof Error) return error;
  if (error && typeof error === "object" && !Array.isArray(error)) {
    const value = error as Record<string, unknown>;
    if (typeof value.message === "string") return new RuntimeRequestError(typeof value.code === "string" ? value.code : "runtime_error", value.message,
      value.details && typeof value.details === "object" && !Array.isArray(value.details) ? value.details as Record<string, unknown> : undefined);
  }
  return new Error(typeof error === "string" ? error : "O runtime não concluiu a solicitação.");
}

function hostKeyDetails(value?: Record<string, unknown>): SshHostKeyDetails | undefined {
  if (!value || typeof value.host !== "string" || !value.host || value.host.length > 256
    || !Number.isInteger(value.port) || Number(value.port) < 1 || Number(value.port) > 65535
    || typeof value.key_type !== "string" || !/^ssh-|^ecdsa-/.test(value.key_type)
    || typeof value.public_key !== "string" || value.public_key.length > 32768 || !/^[A-Za-z0-9+/]+={0,2}$/.test(value.public_key)
    || typeof value.fingerprint !== "string" || !/^SHA256:[A-Za-z0-9+/]{43}=?$/.test(value.fingerprint)) return;
  return { host: value.host, port: Number(value.port), key_type: value.key_type, public_key: value.public_key, fingerprint: value.fingerprint };
}

/** Cancellation also invalidates a challenge that arrives after a tab/test closes. */
export function createRuntimeRequester(call: <T>(method: string, params: Record<string, unknown>) => Promise<T>) {
  const pending = new Set<{ key?: string; cancelled: boolean }>();
  const key = (params: Record<string, unknown>) => typeof params.test_id === "string" ? `test:${params.test_id}`
    : typeof params.session_id === "string" ? `session:${params.session_id}` : undefined;
  const cancel = (operationKey?: string) => {
    for (const operation of pending) if (operationKey === undefined || operation.key === operationKey) operation.cancelled = true;
    cancelSshHostTrust(operationKey);
  };
  async function request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    if (["connection.test_cancel", "session.close", "connection.disconnect", "execution.cancel"].includes(method)) cancel(key(params));
    else if (method === "workspace.profiles.select") cancel();
    const operation = { key: key(params), cancelled: false };
    pending.add(operation);
    const current = () => { if (operation.cancelled) throw new SshHostTrustCancelledError(); };
    try {
      try {
        const result=await call<T>(method, params);
        if(method==="connection.connect" || method==="connection.test")current();
        return result;
      }
      catch (failure) {
        const error = runtimeRequestError(failure);
        const details = error instanceof RuntimeRequestError && error.code === "ssh_host_key_unknown" ? hostKeyDetails(error.details) : undefined;
        if (!details || method === "ssh.host_key.trust") throw error;
        current();
        await requestSshHostTrust(details, { operationKey: operation.key });
        current();
        await call("ssh.host_key.trust", { details });
        current();
        const result=await call<T>(method, params);
        current();
        return result;
      }
    } catch (error) { throw runtimeRequestError(error); }
    finally { pending.delete(operation); }
  }
  const receiveEvent=(event:RuntimeEvent)=>{
    if(event.event==="backend.exited")cancel();
    else if(event.event==="session.reset" || event.event==="session.error")cancel(`session:${event.payload.session_id}`);
  };
  return { request, cancel,receiveEvent };
}

const requester = createRuntimeRequester(<T>(method: string, params: Record<string, unknown>) => invoke<T>("backend_request", { method, params }));

export const runtime: RuntimeTransport = {
  async request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    if (!isTauri()) throw new BackendUnavailableError();
    return requester.request<T>(method, params);
  },
  async subscribe(callback): Promise<UnlistenFn> {
    if (!isTauri()) return () => {};
    return listen<unknown>("runtime-event", ({ payload }) => { if (isRuntimeEvent(payload)) { requester.receiveEvent(payload); callback(payload); } });
  },
};

export const isDesktop = () => isTauri();
export const errorText = (error: unknown) => error instanceof Error ? error.message : typeof error === "string" ? error : JSON.stringify(error);
