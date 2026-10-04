import type { LanguageMarker } from "./editorLanguage";
import { errorText, runtime, type Language, type RuntimeTransport } from "./runtime";

export type DiagnosticStatus = "idle" | "scheduled" | "checking" | "complete" | "partial" | "unavailable";
export interface DiagnosticSnapshot {
  status: DiagnosticStatus; markers: LanguageMarker[]; message?: string; durationMs?: number;
}
export interface DiagnosticResponse {
  markers?: LanguageMarker[]; status?: "complete" | "partial"; message?: string; duration_ms?: number; superseded?: boolean;
}
export interface DiagnosticSource {
  code: string; language: Language; contextKey: string; ready: boolean; enabled: boolean; focused?: boolean;
  params: () => Record<string, unknown>;
}
interface DiagnosticJob {
  blockId: string; source: DiagnosticSource; id: string; readyAt: number; obsolete: boolean;
  params?: Record<string, unknown>; timeout?: ReturnType<typeof setTimeout>;
}
const EMPTY: DiagnosticSnapshot = { status: "idle", markers: [] };
const MAX_DOCUMENT_CHARS = 1024 * 1024;
const nonce = globalThis.crypto.randomUUID();
let sequence = 0;

/** One latest revision per block, two RPCs for the entire workspace, no work per keystroke. */
export class SyntaxDiagnostics {
  private readonly snapshots = new Map<string, DiagnosticSnapshot>();
  private readonly sources = new Map<string, DiagnosticSource>();
  private readonly pending = new Map<string, DiagnosticJob>();
  private readonly active = new Map<string, DiagnosticJob>();
  private readonly listeners = new Map<string, Set<() => void>>();
  private timer?: ReturnType<typeof setTimeout>;
  private timerAt?: number;
  constructor(private readonly transport: RuntimeTransport, private readonly delay = 450, private readonly concurrency = 2) {}

  snapshot = (id: string): DiagnosticSnapshot => this.snapshots.get(id) ?? EMPTY;
  subscribe(id: string, listener: () => void) {
    const listeners = this.listeners.get(id) ?? new Set<() => void>();
    listeners.add(listener); this.listeners.set(id, listeners);
    return () => { listeners.delete(listener); if (!listeners.size) this.listeners.delete(id); };
  }
  update(id: string, source: DiagnosticSource, force = false) {
    const previous = this.sources.get(id);
    this.sources.set(id, source);
    if (!force && previous && previous.code === source.code && previous.language === source.language && previous.contextKey === source.contextKey && previous.ready === source.ready && previous.enabled === source.enabled) {
      const pending = this.pending.get(id); if (pending) pending.source = source;
      return;
    }
    this.cancel(id);
    if (!source.enabled || !source.code.length) { this.publish(id, EMPTY); return; }
    if (!source.ready) { this.publish(id, { status: "unavailable", markers: [], message: "Aguardando o serviço de validação." }); return; }
    if (source.code.length > MAX_DOCUMENT_CHARS) {
      this.publish(id, { status: "partial", markers: [], message: "Este bloco excede o limite de 1 MiB da validação automática." }); return;
    }
    if (!/\S/.test(source.code)) { this.publish(id, EMPTY); return; }
    this.publish(id, { status: "scheduled", markers: [] });
    const readyAt = Date.now() + this.delay;
    this.pending.set(id, { blockId: id, source, id: `${nonce}-${++sequence}`, readyAt, obsolete: false });
    // Initial notebook validation schedules one timer; never sorts the notebook per keystroke.
    if (this.active.size < this.concurrency && (this.timerAt === undefined || readyAt < this.timerAt)) this.arm(readyAt);
  }
  refresh(id: string) { const source = this.sources.get(id); if (source) this.update(id, source, true); }
  remove(id: string) { this.cancel(id); this.sources.delete(id); this.publish(id, EMPTY); this.snapshots.delete(id); }
  dispose() {
    for (const id of this.sources.keys()) this.cancel(id);
    clearTimeout(this.timer); this.timer = undefined; this.timerAt = undefined; this.sources.clear(); this.snapshots.clear(); this.listeners.clear();
  }
  private publish(id: string, value: DiagnosticSnapshot) { this.snapshots.set(id, value); this.listeners.get(id)?.forEach(listener => listener()); }
  private cancel(id: string) {
    this.pending.delete(id);
    for (const job of this.active.values()) if (job.blockId === id && !job.obsolete) {
      job.obsolete = true;
      this.cancelRemote(job);
    }
  }
  private cancelRemote(job: DiagnosticJob) {
    void this.transport.request("language.diagnostics.cancel", { session_id: job.params?.session_id, block_id: job.blockId, diagnostic_id: job.id }).catch(() => {});
  }
  private pump() {
    clearTimeout(this.timer); this.timer = undefined; this.timerAt = undefined;
    if (this.active.size >= this.concurrency || !this.pending.size) return;
    const now = Date.now();
    const jobs = [...this.pending.values()].sort((a, b) => Number(Boolean(b.source.focused)) - Number(Boolean(a.source.focused)) || a.readyAt - b.readyAt);
    for (const job of jobs) {
      if (this.active.size >= this.concurrency) break;
      if (job.readyAt > now) continue;
      this.pending.delete(job.blockId); this.start(job);
    }
    if (this.active.size < this.concurrency && this.pending.size) {
      const next = Math.min(...[...this.pending.values()].map(job => job.readyAt));
      this.arm(next);
    }
  }
  private arm(at: number) { clearTimeout(this.timer); this.timerAt = at; this.timer = setTimeout(() => this.pump(), Math.max(0, at - Date.now())); }
  private start(job: DiagnosticJob) {
    this.active.set(job.id, job); this.publish(job.blockId, { status: "checking", markers: [] });
    let timedOut = false;
    const valid = () => !job.obsolete && this.sources.get(job.blockId)?.code === job.source.code && this.sources.get(job.blockId)?.contextKey === job.source.contextKey;
    try { job.params = { ...job.source.params(), code: job.source.code, language: job.source.language, block_id: job.blockId, diagnostic_id: job.id }; }
    catch (error) { this.failed(job, error); this.active.delete(job.id); this.pump(); return; }
    const timeout = new Promise<never>((_, reject) => { job.timeout = setTimeout(() => { timedOut = true; this.cancelRemote(job); reject(new Error("A validação demorou demais. Tente novamente.")); }, 15_000); });
    void Promise.race([this.transport.request<DiagnosticResponse>("language.diagnostics", job.params), timeout]).then(result => {
      if (!valid()) return;
      if (result.superseded) { this.publish(job.blockId, { status: "unavailable", markers: [], message: "Esta revisão foi substituída. Tente validar novamente." }); return; }
      this.publish(job.blockId, { status: result.status === "partial" ? "partial" : "complete", markers: normalizeLanguageMarkers(result.markers ?? []), message: result.message, durationMs: result.duration_ms });
    }).catch(error => { if (valid()) this.failed(job, error); }).finally(() => {
      clearTimeout(job.timeout); if (timedOut) job.obsolete = true;
      this.active.delete(job.id); this.pump();
    });
  }
  private failed(job: DiagnosticJob, error: unknown) { if (!job.obsolete) this.publish(job.blockId, { status: "unavailable", markers: [], message: errorText(error) }); }
}

/** Keep malformed/large server payloads out of the editor and preserve Monaco's UTF-16 ranges. */
export function normalizeLanguageMarkers(markers: LanguageMarker[]): LanguageMarker[] {
  return markers.slice(0, 200).filter(marker => marker && typeof marker.message === "string" && [marker.start_line, marker.start_column, marker.end_line, marker.end_column].every(value => Number.isFinite(value) && value >= 1)
    && (marker.end_line > marker.start_line || marker.end_line === marker.start_line && marker.end_column >= marker.start_column)).map(marker => ({
    ...marker, message: marker.message.slice(0, 1000), severity: ["error", "warning", "info"].includes(marker.severity) ? marker.severity : "error",
    start_line: Math.floor(marker.start_line), start_column: Math.floor(marker.start_column), end_line: Math.floor(marker.end_line), end_column: Math.floor(marker.end_column),
  }));
}
export const syntaxDiagnostics = new SyntaxDiagnostics(runtime);
