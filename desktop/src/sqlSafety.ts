import type { Language } from "./runtime";

export interface SqlSafetyRisk {
  statement: number;
  operation: string;
  target?: string;
  has_where?: boolean;
  unfiltered?: boolean;
  preview: string;
}

export interface SqlSafetyReview {
  confirmation_required: boolean;
  confirmation_token?: string;
  connection_name?: string;
  risks: SqlSafetyRisk[];
}

export interface SqlExecutionReview extends SqlSafetyReview {
  session_id: string;
  block_id?: string;
  execution_id?: string;
  code?: string;
  language?: Language;
  tab_name?: string;
  block_name?: string;
  connection_name?: string;
  database?: string;
  schema?: string;
}

export function sqlSafetyReview(value: unknown): SqlSafetyReview {
  if (!value || typeof value !== "object") throw new Error("Não foi possível validar a segurança do SQL.");
  const review = value as Partial<SqlSafetyReview>;
  if (typeof review.confirmation_required !== "boolean" || !Array.isArray(review.risks)
    || review.risks.some(risk => !risk || typeof risk.operation !== "string" || typeof risk.preview !== "string")
    || review.confirmation_required && (!review.risks.length || typeof review.confirmation_token !== "string" || !review.confirmation_token)) {
    throw new Error("Não foi possível validar a segurança do SQL.");
  }
  return review as SqlSafetyReview;
}

/** The application must return an explicit true; disposal/cancel always wins. */
export async function confirmSqlExecution(review: SqlExecutionReview, signal: AbortSignal,
  confirm?: (review: SqlExecutionReview, signal: AbortSignal) => Promise<boolean>): Promise<boolean> {
  if (signal.aborted || !confirm) return false;
  let detach = () => {};
  const aborted = new Promise<boolean>(resolve => {
    const cancel = () => resolve(false);
    signal.addEventListener("abort", cancel, { once: true });
    detach = () => signal.removeEventListener("abort", cancel);
  });
  try { return await Promise.race([Promise.resolve().then(() => signal.aborted ? false : confirm(review, signal)).then(value => value === true), aborted]) && !signal.aborted; }
  finally { detach(); }
}

export async function waitForSqlReview<T>(request: Promise<T>, signal: AbortSignal): Promise<T | undefined> {
  if (signal.aborted) return;
  let detach = () => {};
  const aborted = new Promise<undefined>(resolve => {
    const cancel = () => resolve(undefined);
    signal.addEventListener("abort", cancel, { once: true });
    detach = () => signal.removeEventListener("abort", cancel);
  });
  try { return await Promise.race([request, aborted]); }
  finally { detach(); }
}
