import type { Language, RuntimeTransport } from "./runtime";

export interface CompletionContext {
  variables: Array<{ name: string; type: string; columns?: string[]; module?: string }>; tables: string[];
  sessionId?: string; blockId?: string; connectionId?: string; database?: string; schema?: string; dbType?: string; globalImports?: string;
  scopeInherited?: boolean;
  preamble?: string;
  schemaSnapshot?: { db_type?: string; database?: string; current_schema?: string; default_schema?: string; tables?: Record<string, { name?: string; schema?: string; catalog?: string; temporary?: boolean; columns?: Array<{ name: string; type?: string; data_type?: string }> }> };
  schemaVersion?: number; namespaceVersion?: number;
  siblings?: Array<{ name: string; code: string; language: Language; cellType?: string }>;
}
export interface LanguageCompletion { label: string; kind?: string; detail?: string; insert_text?: string; insertText?: string; documentation?: string; filterText?: string; sortText?: string; category?: string; is_snippet?: boolean; start_column?: number; end_column?: number }
export interface LanguageMarker { start_line: number; start_column: number; end_line: number; end_column: number; message: string; severity: string }
export interface LanguageParams { language: Language; code: string; line?: number; column?: number }
export function languageParams(context: CompletionContext | undefined, params: LanguageParams): Record<string, unknown> {
  return { ...params, session_id: context?.sessionId, block_id: context?.blockId, ...(context?.blockId || context?.scopeInherited!==undefined?{scope_inherited:Boolean(context?.scopeInherited)}:{}), connection_id: context?.connectionId, database: context?.database, schema: context?.schema, global_imports: context?.globalImports, preamble: context?.preamble };
}

/** Latest code and connection scope own suggestions; obsolete requests are discarded. */
export class LanguageRequestGate {
  private generation = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private pending?: CompletionRequest;
  private running?: CompletionRequest;
  private sequence = 0;
  private readonly instance = ++gateInstances;
  private readonly cache = new Map<string, { items: LanguageCompletion[]; expires: number }>();
  /** Cancel intent as well as queued work. A native inference job is cancelled by exact ID. */
  cancel() {
    ++this.generation;
    clearTimeout(this.timer); this.timer = undefined; this.pending = undefined;
    if (this.running && !this.running.cancelled) {
      this.running.cancelled = true;
      const { session_id, block_id, completion_id } = this.running.params ?? {};
      if (block_id) void this.running.transport.request("language.cancel", { session_id, block_id, completion_id }).catch(() => {});
    }
  }
  invalidate() { this.cancel(); this.cache.clear(); }
  async complete(transport: RuntimeTransport, params: Record<string, unknown>, valid: () => boolean): Promise<LanguageCompletion[]> {
    const generation = ++this.generation;
    const result = await transport.request<{ items: LanguageCompletion[] }>("language.complete", params);
    return generation === this.generation && valid() ? result.items ?? [] : [];
  }

  /** Never make the suggestion widget wait for Python, a busy kernel or metadata IO. */
  suggest(transport: RuntimeTransport, key: string, params: () => Record<string, unknown>, valid: () => boolean,
    ready: () => void, delay = 120): LanguageCompletion[] {
    const cached = this.cache.get(key);
    if (cached && cached.expires > Date.now()) {
      if ((this.pending && this.pending.key !== key) || (this.running && this.running.key !== key)) this.cancel();
      this.cache.delete(key); this.cache.set(key, cached);
      return cached.items;
    }
    if (this.pending?.key === key) {
      this.pending.valid = valid; this.pending.ready = ready;
      if (delay === 0 && this.timer !== undefined) { clearTimeout(this.timer); this.timer = setTimeout(() => { this.timer = undefined; this.start(); }, 0); }
      return [];
    }
    if (this.running?.key === key && !this.running.cancelled) { this.running.valid = valid; this.running.ready = ready; return []; }
    this.cancel();
    this.pending = { key, transport, makeParams: params, valid, ready, generation: this.generation, id: `${gateNonce}-${this.instance}-${++this.sequence}`, cancelled: false };
    this.timer = setTimeout(() => { this.timer = undefined; this.start(); }, delay);
    return [];
  }

  private start() {
    const job = this.pending;
    if (!job || this.running || this.timer !== undefined) return;
    this.pending = undefined;
    if (job.generation !== this.generation || !job.valid()) return;
    this.running = job;
    try { job.params = { ...job.makeParams(), completion_id: job.id }; }
    catch { this.running = undefined; return; }
    void job.transport.request<{ items?: LanguageCompletion[]; superseded?: boolean }>("language.complete", job.params)
      .then(result => {
        if (job.cancelled || job.generation !== this.generation || !job.valid() || result.superseded) return;
        this.remember(job.key, mergeCompletions(result.items ?? [], []), 60_000);
        job.ready();
      }).catch(() => {
        // An unavailable service must not make repeated manual invocations flood IPC.
        if (!job.cancelled && job.generation === this.generation && job.valid()) this.remember(job.key, [], 1_000);
      }).finally(() => {
        if (this.running === job) this.running = undefined;
        this.start();
      });
  }

  private remember(key: string, items: LanguageCompletion[], lifetime: number) {
    this.cache.delete(key); this.cache.set(key, { items, expires: Date.now() + lifetime });
    while (this.cache.size > 8) this.cache.delete(this.cache.keys().next().value!);
  }
}
let gateInstances = 0;
const gateNonce = globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
interface CompletionRequest {
  key: string; transport: RuntimeTransport; makeParams: () => Record<string, unknown>; valid: () => boolean; ready: () => void;
  generation: number; id: string; cancelled: boolean; params?: Record<string, unknown>;
}

interface CancellationSignal { isCancellationRequested: boolean; onCancellationRequested(listener:()=>void): { dispose():void } }
interface InlineJob {
  key:string; transport:RuntimeTransport; params:()=>Record<string,unknown>; valid:()=>boolean;
  done:(value:string)=>void; cancellation?:{dispose():void}; cancelled:boolean;
}
/** One ACP request and one latest intent per model; cancelled pauses never enter IPC. */
export class InlineRequestGate {
  private timer?:ReturnType<typeof setTimeout>;
  private pending?:InlineJob;
  private running?:InlineJob;
  private cached?:{key:string;text:string;expires:number};
  cancel() {
    clearTimeout(this.timer);this.timer=undefined;
    if(this.pending){this.pending.cancelled=true;this.pending.cancellation?.dispose();this.pending.done("");this.pending=undefined;}
    if(this.running){this.running.cancelled=true;this.running.done("");}
  }
  complete(transport:RuntimeTransport,key:string,params:()=>Record<string,unknown>,valid:()=>boolean,token:CancellationSignal,delay=350):Promise<string> {
    this.cancel();
    if(token.isCancellationRequested||!valid())return Promise.resolve("");
    return new Promise(resolve=>{
      const job:InlineJob={key,transport,params,valid,done:resolve,cancelled:false};this.pending=job;
      job.cancellation=token.onCancellationRequested(()=>{
        job.cancelled=true;job.done("");job.cancellation?.dispose();
        if(this.pending===job){clearTimeout(this.timer);this.timer=undefined;this.pending=undefined;}
      });
      this.timer=setTimeout(()=>{this.timer=undefined;this.start();},delay);
    });
  }
  private start() {
    const job=this.pending;if(!job||this.running||this.timer!==undefined)return;
    this.pending=undefined;
    if(job.cancelled||!job.valid()){job.cancellation?.dispose();job.done("");return;}
    if(this.cached?.key===job.key&&this.cached.expires>Date.now()){job.cancellation?.dispose();job.done(this.cached.text);return;}
    this.running=job;
    let params:Record<string,unknown>;
    try{params=job.params();}catch{this.running=undefined;job.cancellation?.dispose();job.done("");return;}
    void job.transport.request<{text:string}>("pynia.inline",params).then(result=>{this.cached={key:job.key,text:result.text??"",expires:Date.now()+(result.text?60_000:1_000)};job.done(!job.cancelled&&job.valid()?result.text??"":"");},()=>job.done(""))
      .finally(()=>{job.cancellation?.dispose();if(this.running===job)this.running=undefined;this.start();});
  }
}

export function mergeCompletions(remote: LanguageCompletion[], local: LanguageCompletion[], language?: Language): LanguageCompletion[] {
  const seen = new Set<string>();
  return [...remote, ...local].filter((item) => {
    if (!item.label) return false;
    const kind = (item.kind ?? item.category ?? "").toLowerCase();
    // Quoted identifiers can distinguish Id from id. Only SQL keywords fold
    // case; dataframe field labels identify the same column before escaping.
    const key = language === "sql" && kind === "keyword" ? `keyword:${item.label.toLowerCase()}`
      : language === "python" && ["field", "column"].includes(kind) ? `${item.label}:${item.label}`
      : `${item.label}:${item.insert_text ?? item.insertText ?? item.label}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  }).slice(0, 1000);
}
