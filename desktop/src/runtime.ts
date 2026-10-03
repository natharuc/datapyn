import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type Language = "sql" | "python";
export type Primitive = null | string | number | boolean;
export interface Column { name: string; dtype: string }
export interface ResultRef { result_id: string; variable_name: string; columns: Column[]; row_count: number }
export interface Variable { name: string; type: string; preview: string }
export interface ResultPage { columns: Column[]; rows: Primitive[][]; total_rows: number; offset: number }
export interface RuntimeInfo { protocol_version: number; python_version: string; capabilities: Record<string, unknown> | string[] }
export interface ExecutionFinished {
  session_id: string; execution_id: string; status: "succeeded" | "failed" | "cancelled";
  duration_ms: number; error?: string; results: ResultRef[]; variables: Variable[];
  rich_outputs?: Array<{ type: "image"; data: string; mime: string }>;
}
export type RuntimeEvent =
  | { event: "execution.started"; payload: { session_id: string; execution_id: string } }
  | { event: "execution.output"; payload: { session_id: string; execution_id: string; stream: string; text: string } }
  | { event: "execution.finished"; payload: ExecutionFinished }
  | { event: "session.ready"; payload: { session_id: string } }
  | { event: "session.error"; payload: { session_id: string; error: string } }
  | { event: "session.reset"; payload: { session_id: string; reason?: string } }
  | { event: "backend.exited"; payload: { message: string } };

export function isRuntimeEvent(value: unknown): value is RuntimeEvent {
  if (!value || typeof value !== "object") return false;
  const { event, payload } = value as { event?: unknown; payload?: Record<string, unknown> };
  if (!payload || typeof payload !== "object") return false;
  if (event === "backend.exited") return typeof payload.message === "string";
  if (typeof payload.session_id !== "string") return false;
  if (event === "session.ready" || event === "session.reset") return true;
  if (event === "session.error") return typeof payload.error === "string";
  if (typeof payload.execution_id !== "string") return false;
  if (event === "execution.started") return true;
  if (event === "execution.output") return typeof payload.stream === "string" && typeof payload.text === "string";
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
