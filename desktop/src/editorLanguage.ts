import type { Language, RuntimeTransport } from "./runtime";

export interface CompletionContext {
  variables: Array<{ name: string; type: string }>; tables: string[];
  sessionId?: string; connectionId?: string; database?: string; schema?: string; globalImports?: string;
  preamble?: string;
}
export interface LanguageCompletion { label: string; kind?: string; detail?: string; insert_text?: string; insertText?: string; documentation?: string }
export interface LanguageMarker { start_line: number; start_column: number; end_line: number; end_column: number; message: string; severity: string }
export interface LanguageParams { language: Language; code: string; line?: number; column?: number }
export function languageParams(context: CompletionContext | undefined, params: LanguageParams): Record<string, unknown> {
  return { ...params, session_id: context?.sessionId, connection_id: context?.connectionId, database: context?.database, schema: context?.schema, global_imports: context?.globalImports, preamble: context?.preamble };
}

/** Latest code and connection scope own suggestions; obsolete requests are discarded. */
export class LanguageRequestGate {
  private generation = 0;
  invalidate() { ++this.generation; }
  async complete(transport: RuntimeTransport, params: Record<string, unknown>, valid: () => boolean): Promise<LanguageCompletion[]> {
    const generation = ++this.generation;
    const result = await transport.request<{ items: LanguageCompletion[] }>("language.complete", params);
    return generation === this.generation && valid() ? result.items ?? [] : [];
  }
}

export function mergeCompletions(remote: LanguageCompletion[], local: LanguageCompletion[]): LanguageCompletion[] {
  const seen = new Set<string>();
  return [...remote, ...local].filter((item) => {
    if (!item.label) return false;
    const key = `${item.label}:${item.insert_text ?? item.insertText ?? item.label}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  }).slice(0, 1000);
}
