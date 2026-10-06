import type { RuntimeEvent } from "./runtime";

export interface DataImportOptions {
  delimiter?: string | null; encoding?: string; decimal?: string;
}
export interface DataImportState {
  operationId: string; path: string;
  phase: "preparing" | "reading" | "registering" | "cancelling" | "cancelled" | "error";
  current: number; total: number; error?: string;
}
export interface DataImportProgress {
  session_id: string; operation_id: string;
  phase: "reading" | "registering" | "completed" | "cancelled";
  current: number; total: number;
}
export function dataImportPending(state?: DataImportState) {
  return Boolean(state && !["cancelled", "error"].includes(state.phase));
}
export function importFileName(path: string) { return path.split(/[\\/]/).at(-1) || path; }
export function readImportProgress(event: RuntimeEvent): DataImportProgress | undefined {
  return event.event === "data.import_progress" ? event.payload : undefined;
}
