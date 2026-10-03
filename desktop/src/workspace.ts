import { errorText, isRuntimeEvent, type ExecutionFinished, type Language, type ResultRef, type RuntimeEvent, type RuntimeInfo, type RuntimeTransport, type Variable } from "./runtime";

export type BlockStatus = "idle" | "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";
export interface Block {
  id: string; block_name: string; language: Language; code: string; is_active: boolean;
  status: BlockStatus; duration_ms?: number; error?: string; height?: number;
  [key: string]: unknown;
}
export interface ConnectionConfig {
  db_type: "sqlserver" | "postgresql" | "mysql" | "mariadb" | "sqlite" | "databricks";
  name?: string; host: string; port: number; database: string; username: string; password?: string;
  schema?: string; http_path?: string; sqlserver_auth_mode?: string;
  use_windows_auth?: boolean; trust_server_certificate?: boolean;
}
export interface LogLine { id: string; time: string; stream: string; text: string; blockName: string }
export interface SessionDocument {
  id: string; title: string; blocks: Block[]; focusedBlockId: string;
  results: ResultRef[]; variables: Variable[]; images: Array<{ data: string; mime: string }>;
  logs: LogLine[]; busy: boolean; currentExecutionId?: string; currentBlockId?: string; resultRevision: number;
  connection?: ConnectionConfig; filePath?: string; modified: boolean;
  notice?: string; runtimeError?: string; extras: Record<string, unknown>;
}
export interface WorkspaceState {
  sessions: SessionDocument[]; activeId: string; runtimeStatus: "connecting" | "ready" | "unavailable";
  runtimeInfo?: RuntimeInfo; message: string;
}

export const newId = () => globalThis.crypto.randomUUID();
export const newBlock = (language: Language = "sql", code = ""): Block => ({
  id: newId(), block_name: "", language, code, is_active: true, status: "idle",
});
export const newSession = (title = "Análise 1"): SessionDocument => {
  const block = newBlock();
  return { id: newId(), title, blocks: [block], focusedBlockId: block.id,
    results: [], variables: [], images: [], logs: [], busy: false, resultRevision: 0, modified: false, extras: {} };
};

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Documento DataPyn inválido.");
  return value as Record<string, unknown>;
}

/** Reads the actual single-tab .dpw format. Unknown settings survive a round trip. */
export function decodeDocument(input: unknown, title = "Análise importada"): SessionDocument {
  const outer = object(input);
  const document = "document" in outer ? object(outer.document) : outer;
  if (!Array.isArray(document.blocks)) throw new Error("Este arquivo não contém uma aba DataPyn com blocos. Abra um arquivo .dpw de uma análise.");
  const session = newSession(typeof document.title === "string" ? document.title : title);
  session.blocks = document.blocks.map((raw) => {
    const block = object(raw);
    if (block.language !== "sql" && block.language !== "python") throw new Error(`Linguagem de bloco não suportada: ${String(block.language)}`);
    if (typeof block.code !== "string") throw new Error("Código de bloco inválido.");
    return { ...block, id: newId(), block_name: String(block.block_name ?? ""), language: block.language,
      code: block.code, is_active: block.is_active !== false, status: "idle" } as Block;
  });
  if (session.blocks.length === 0) session.blocks = [newBlock()];
  session.focusedBlockId = session.blocks[0].id;
  const { blocks: _blocks, version: _version, title: _title, ...extras } = document;
  session.extras = extras;
  return session;
}

export function encodeDocument(session: SessionDocument): Record<string, unknown> {
  return { ...session.extras, version: "1.0", blocks: session.blocks.map(({ id, status, duration_ms, error, ...block }) => ({ ...block, block_key: block.block_key ?? id })) };
}

export function eventBelongsToSession(session: SessionDocument, event: RuntimeEvent): boolean {
  if (event.event === "backend.exited") return false;
  if (event.payload.session_id !== session.id) return false;
  return event.event === "session.reset" || event.event === "session.error" || event.event === "session.ready" || event.payload.execution_id === session.currentExecutionId;
}

function appendLog(session: SessionDocument, stream: string, text: string, blockName = ""): LogLine[] {
  const last = session.logs.at(-1);
  if (last?.stream === stream && last.blockName === blockName && stream !== "system") {
    return [...session.logs.slice(-499, -1), { ...last, text: (last.text + text).slice(-200_000) }];
  }
  return [...session.logs.slice(-499), { id: newId(), time: new Date().toLocaleTimeString("pt-BR"), stream, text: text.slice(-200_000), blockName }];
}

export function applyRuntimeEvent(session: SessionDocument, event: RuntimeEvent): SessionDocument {
  if (!isRuntimeEvent(event)) return session;
  if (event.event === "backend.exited") return session;
  if (!eventBelongsToSession(session, event)) return session;
  if (event.event === "session.ready") return session;
  if (event.event === "session.error") {
    return { ...session, busy: false, currentExecutionId: undefined, currentBlockId: undefined,
      results: [], variables: [], images: [], connection: undefined, runtimeError: event.payload.error,
      notice: `Runtime desta sessão indisponível: ${event.payload.error}. Salve a análise, feche esta aba e reabra para criar uma nova sessão.`,
      blocks: session.blocks.map((block) => ["running", "queued", "cancelling"].includes(block.status) ? { ...block, status: "failed", error: event.payload.error } : block),
      logs: appendLog(session, "stderr", event.payload.error + "\n") };
  }
  if (event.event === "session.reset") {
    return { ...session, results: [], variables: [], images: [], connection: undefined,
      notice: "Runtime da sessão reiniciado. Variáveis e conexão foram descartadas; reconecte antes de executar SQL.",
      blocks: session.blocks.map((block) => ["running", "queued", "cancelling"].includes(block.status) ? { ...block, status: "cancelled" } : block),
      logs: appendLog(session, "system", "Sessão reiniciada: namespace e conexão descartados.\n") };
  }
  if (event.event === "execution.started") {
    return { ...session, blocks: session.blocks.map((block) => block.id === session.currentBlockId && block.status === "queued" ? { ...block, status: "running" } : block) };
  }
  if (event.event === "execution.output") {
    const running = session.blocks.find((block) => block.status === "running" || block.status === "cancelling");
    return { ...session, logs: appendLog(session, event.payload.stream, event.payload.text, running?.block_name ?? "") };
  }
  const payload = event.payload;
  const resultRefs = payload.results ?? [];
  return { ...session,
    results: payload.status === "failed" ? [] : resultRefs.length ? resultRefs : session.results,
    resultRevision: session.resultRevision + (payload.status === "succeeded" ? 1 : 0),
    // Cancelling a queued job does not restart the kernel. session.reset owns namespace invalidation.
    variables: payload.status === "cancelled" ? session.variables : payload.variables ?? session.variables,
    images: payload.status === "cancelled" ? session.images : payload.rich_outputs?.filter((item) => item.type === "image").map(({ data, mime }) => ({ data, mime })) ?? [],
    logs: payload.error ? appendLog(session, "stderr", payload.error + "\n") : session.logs,
  };
}

type Completion = { resolve: (value: ExecutionFinished) => void; reject: (error: unknown) => void; sessionId: string; blockId: string };
export interface WorkspaceStorage { getItem(key: string): string | null; setItem(key: string, value: string): void }
const STORAGE_KEY = "datapyn.desktop.documents.v1";

export class WorkspaceController {
  private state: WorkspaceState;
  private readonly listeners = new Set<() => void>();
  private readonly runtimeSessions = new Set<string>();
  private readonly completions = new Map<string, Completion>();
  private initialization?: Promise<void>;
  private runtimeGeneration = 0;
  private subscribed = false;
  private persistTimer?: ReturnType<typeof setTimeout>;
  private readonly cancelRequests = new Set<string>();

  constructor(private readonly transport: RuntimeTransport, private readonly storage?: WorkspaceStorage) {
    let sessions: SessionDocument[] = [];
    try {
      const saved = JSON.parse(storage?.getItem(STORAGE_KEY) ?? "null");
      if (Array.isArray(saved?.sessions)) sessions = saved.sessions.map((entry: Record<string, unknown>) => {
        const session = decodeDocument(entry.document, String(entry.title ?? "Análise"));
        session.title = String(entry.title ?? session.title);
        session.filePath = typeof entry.filePath === "string" ? entry.filePath : undefined;
        session.modified = entry.modified === true;
        return session;
      });
    } catch { /* An unreadable local draft must not stop startup. */ }
    if (!sessions.length) sessions = [newSession()];
    this.state = { sessions, activeId: sessions[0].id, runtimeStatus: "connecting", message: "Iniciando runtime Python…" };
  }

  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private setState(next: WorkspaceState) {
    this.state = next;
    this.listeners.forEach((listener) => listener());
    if (this.storage) {
      clearTimeout(this.persistTimer);
      this.persistTimer = setTimeout(() => this.persist(), 500);
    }
  }
  persist() {
    try { this.storage?.setItem(STORAGE_KEY, JSON.stringify({ sessions: this.state.sessions.map((session) => ({ title: session.title, filePath: session.filePath, modified: session.modified, document: encodeDocument(session) })) })); }
    catch {
      // Reporting quota failure must not schedule another failing disk write.
      this.state = { ...this.state, message: "Não foi possível salvar o rascunho local. Salve sua análise como .dpw." };
      this.listeners.forEach((listener) => listener());
    }
  }
  patchSession(id: string, update: (session: SessionDocument) => SessionDocument) {
    this.setState({ ...this.state, sessions: this.state.sessions.map((session) => session.id === id ? update(session) : session) });
  }
  message(message: string) { this.setState({ ...this.state, message }); }
  session(id = this.state.activeId) { return this.state.sessions.find((session) => session.id === id); }
  activate(id: string) { if (this.session(id)) this.setState({ ...this.state, activeId: id }); }
  focusBlock(sessionId: string, blockId: string) { this.patchSession(sessionId, (session) => session.focusedBlockId === blockId ? session : { ...session, focusedBlockId: blockId }); }
  updateBlock(sessionId: string, id: string, update: Partial<Block>) {
    this.patchSession(sessionId, (session) => ({ ...session, modified: true, blocks: session.blocks.map((block) => block.id === id ? { ...block, ...update } : block) }));
  }
  renameSession(id: string, title: string) { if (title.trim()) this.patchSession(id, (session) => ({ ...session, title: title.trim(), modified: true })); }
  createSession() {
    const session = newSession(`Análise ${this.state.sessions.length + 1}`);
    this.setState({ ...this.state, sessions: [...this.state.sessions, session], activeId: session.id });
    return session;
  }
  importDocument(document: unknown, title: string, path?: string) {
    const session = decodeDocument(document, title); session.filePath = path;
    this.setState({ ...this.state, sessions: [...this.state.sessions, session], activeId: session.id });
    this.message(`Aberto: ${title}`);
    return session;
  }
  saved(id: string, path: string, savedDocument: Record<string, unknown>) {
    this.patchSession(id, (session) => ({ ...session, filePath: path, title: path.split(/[\\/]/).at(-1) ?? session.title,
      modified: JSON.stringify(encodeDocument(session)) !== JSON.stringify(savedDocument) }));
    this.message(this.session(id)?.modified ? `Arquivo salvo; há alterações mais recentes ainda não salvas: ${path}` : `Salvo: ${path}`);
  }
  addBlock(sessionId: string, language: Language = "sql", code = "", afterId?: string) {
    const block = newBlock(language, code);
    this.patchSession(sessionId, (session) => {
      const blocks = [...session.blocks];
      const index = afterId ? blocks.findIndex((item) => item.id === afterId) + 1 : blocks.length;
      blocks.splice(index < 0 ? blocks.length : index, 0, block);
      return { ...session, blocks, focusedBlockId: block.id, modified: true };
    });
    return block;
  }
  removeBlock(sessionId: string, blockId: string) {
    this.patchSession(sessionId, (session) => {
      if (session.busy) return session;
      let blocks = session.blocks.filter((block) => block.id !== blockId);
      if (!blocks.length) blocks = [newBlock()];
      return { ...session, blocks, focusedBlockId: session.focusedBlockId === blockId ? blocks[0].id : session.focusedBlockId, modified: true };
    });
  }
  moveBlock(sessionId: string, blockId: string, direction: -1 | 1) {
    this.patchSession(sessionId, (session) => {
      if (session.busy) return session;
      const blocks = [...session.blocks], index = blocks.findIndex((block) => block.id === blockId), target = index + direction;
      if (index < 0 || target < 0 || target >= blocks.length) return session;
      [blocks[index], blocks[target]] = [blocks[target], blocks[index]];
      return { ...session, blocks, modified: true };
    });
  }
  async closeSession(id: string) {
    if (this.session(id)?.busy) throw new Error("Cancele a execução antes de fechar esta aba.");
    if (this.runtimeSessions.has(id)) await this.transport.request("session.close", { session_id: id });
    this.runtimeSessions.delete(id);
    let sessions = this.state.sessions.filter((session) => session.id !== id);
    if (!sessions.length) sessions = [newSession()];
    this.setState({ ...this.state, sessions, activeId: this.state.activeId === id ? sessions[0].id : this.state.activeId });
  }
  initialize() {
    if (!this.initialization) this.initialization = (async () => {
      const generation = this.runtimeGeneration;
      try {
        if (!this.subscribed) { await this.transport.subscribe((event) => this.onRuntimeEvent(event)); this.subscribed = true; }
        const runtimeInfo = await this.transport.request<RuntimeInfo>("system.info");
        if (generation !== this.runtimeGeneration) return;
        if (runtimeInfo.protocol_version !== 1) throw new Error("Versão incompatível do protocolo Python.");
        this.setState({ ...this.state, runtimeStatus: "ready", runtimeInfo, message: `Python ${runtimeInfo.python_version} pronto` });
      } catch (error) { if (generation === this.runtimeGeneration) this.setState({ ...this.state, runtimeStatus: "unavailable", message: errorText(error) }); }
    })();
    return this.initialization;
  }
  async retryRuntime() {
    if (this.state.sessions.some((session) => session.busy)) throw new Error("Aguarde a execução antes de reiniciar o runtime.");
    this.initialization = undefined;
    this.setState({ ...this.state, runtimeStatus: "connecting", message: "Reconectando ao runtime Python…" });
    await this.initialize();
  }
  private async ensureSession(sessionId: string) {
    await this.initialize();
    if (this.state.runtimeStatus !== "ready") throw new Error(this.state.message);
    if (this.session(sessionId)?.runtimeError) throw new Error(this.session(sessionId)!.notice ?? this.session(sessionId)!.runtimeError);
    if (this.runtimeSessions.has(sessionId)) return;
    const generation = this.runtimeGeneration;
    await this.transport.request("session.create", { session_id: sessionId });
    if (generation !== this.runtimeGeneration) throw new Error("O runtime Python foi encerrado durante a criação da sessão.");
    this.runtimeSessions.add(sessionId);
    if (this.session(sessionId)?.runtimeError) throw new Error(this.session(sessionId)!.notice ?? this.session(sessionId)!.runtimeError);
  }
  async connect(sessionId: string, config: ConnectionConfig) {
    if (this.session(sessionId)?.busy) throw new Error("Aguarde a execução para trocar a conexão.");
    await this.ensureSession(sessionId);
    await this.transport.request("connection.connect", { session_id: sessionId, config });
    const { password: _password, ...safeConfig } = config;
    this.patchSession(sessionId, (session) => ({ ...session, connection: safeConfig, notice: undefined }));
    this.message(`Conectado: ${config.name || config.database || config.db_type}`);
  }
  async schema(sessionId: string): Promise<Record<string, unknown>> {
    await this.ensureSession(sessionId);
    return this.transport.request("schema.get", { session_id: sessionId });
  }
  async runBlock(sessionId: string, blockId: string, selectedCode?: string, advance = false) {
    const session = this.session(sessionId), block = session?.blocks.find((item) => item.id === blockId);
    if (!session || !block) return;
    await this.runQueue(sessionId, [{ ...block, code: selectedCode ?? block.code }]);
    if (advance) {
      const latest = this.session(sessionId); if (!latest) return;
      const index = latest.blocks.findIndex((item) => item.id === blockId);
      const next = latest.blocks[index + 1] ?? this.addBlock(sessionId, block.language);
      this.focusBlock(sessionId, next.id);
    }
  }
  async runAll(sessionId: string) {
    const session = this.session(sessionId); if (!session) return;
    const queue = session.blocks.filter((block) => block.is_active && block.code.trim()).map((block) => ({ ...block }));
    await this.runQueue(sessionId, queue);
  }
  private async runQueue(sessionId: string, queue: Block[]) {
    const session = this.session(sessionId);
    if (session?.runtimeError) throw new Error(session.notice ?? session.runtimeError);
    if (this.session(sessionId)?.busy) throw new Error("Esta aba já tem uma execução em andamento.");
    const runnable = queue.filter((block) => block.code.trim());
    if (!runnable.length) { this.message("Escreva código no bloco antes de executar."); return; }
    this.cancelRequests.delete(sessionId);
    this.patchSession(sessionId, (session) => ({ ...session, busy: true, notice: undefined,
      blocks: session.blocks.map((block) => runnable.some((item) => item.id === block.id) ? { ...block, status: "queued", error: undefined } : block) }));
    try {
      await this.ensureSession(sessionId);
      for (const block of runnable) {
        if (this.cancelRequests.has(sessionId)) break;
        const result = await this.runOne(sessionId, block);
        if (result.status !== "succeeded") { this.message(result.status === "failed" ? "Fila interrompida após erro." : "Execução cancelada."); break; }
      }
    } catch (error) { this.message(errorText(error)); throw error; }
    finally {
      this.cancelRequests.delete(sessionId);
      this.patchSession(sessionId, (session) => ({ ...session, busy: false, currentExecutionId: undefined, currentBlockId: undefined,
        blocks: session.blocks.map((block) => ["queued", "running", "cancelling"].includes(block.status) ? { ...block, status: "cancelled" } : block) }));
    }
  }
  private async runOne(sessionId: string, block: Block): Promise<ExecutionFinished> {
    const executionId = newId();
    const completion = new Promise<ExecutionFinished>((resolve, reject) => this.completions.set(executionId, { resolve, reject, sessionId, blockId: block.id }));
    // The event channel may report failure before execution.run's request acknowledgement.
    void completion.catch(() => {});
    this.patchSession(sessionId, (session) => ({ ...session, currentExecutionId: executionId, currentBlockId: block.id,
      blocks: session.blocks.map((item) => item.id === block.id ? { ...item, status: "running", error: undefined } : item) }));
    const acknowledged = this.transport.request("execution.run", { session_id: sessionId, execution_id: executionId,
      language: block.language, code: block.code, variable_name: block.block_name || undefined }).then(() => completion).catch((error) => {
        // A terminal event is authoritative even if its request acknowledgement arrives later.
        if (this.completions.delete(executionId)) {
          this.patchSession(sessionId, (session) => ({ ...session, blocks: session.blocks.map((item) => item.id === block.id ? { ...item, status: "failed", error: errorText(error) } : item) }));
        }
        throw error;
      });
    return Promise.race([acknowledged, completion]);
  }
  async cancel(sessionId: string) {
    const session = this.session(sessionId); if (!session?.busy) return;
    this.cancelRequests.add(sessionId);
    this.patchSession(sessionId, (item) => ({ ...item, notice: "Cancelamento reinicia somente esta sessão e descarta suas variáveis e conexão.",
      blocks: item.blocks.map((block) => block.status === "running" ? { ...block, status: "cancelling" } : block) }));
    if (session.currentExecutionId) await this.transport.request("execution.cancel", { session_id: sessionId, execution_id: session.currentExecutionId });
  }
  onRuntimeEvent(event: RuntimeEvent) {
    if (!isRuntimeEvent(event)) return;
    if (event?.event === "backend.exited") {
      const message = event.payload.message || "O runtime Python foi encerrado.";
      this.runtimeGeneration++; this.initialization = undefined; this.runtimeSessions.clear();
      for (const completion of this.completions.values()) completion.reject(new Error(message));
      this.completions.clear();
      this.setState({ ...this.state, runtimeStatus: "unavailable", runtimeInfo: undefined, message,
        sessions: this.state.sessions.map((session) => ({ ...session, busy: false, currentExecutionId: undefined, currentBlockId: undefined,
          connection: undefined, variables: [], results: [], images: [], runtimeError: undefined, notice: "Runtime encerrado. As variáveis e conexões foram descartadas.",
          blocks: session.blocks.map((block) => block.status === "running" || block.status === "cancelling" ? { ...block, status: "failed", error: message } : block.status === "queued" ? { ...block, status: "cancelled" } : block) })) });
      return;
    }
    if (!event || !event.payload?.session_id) return;
    this.patchSession(event.payload.session_id, (session) => applyRuntimeEvent(session, event));
    if (event.event === "session.error") {
      this.cancelRequests.add(event.payload.session_id);
      for (const [id, completion] of this.completions) {
        if (completion.sessionId !== event.payload.session_id) continue;
        this.completions.delete(id); completion.reject(new Error(event.payload.error));
      }
      this.message(`Runtime da sessão indisponível: ${event.payload.error}`);
      return;
    }
    if (event.event === "session.reset") {
      this.cancelRequests.add(event.payload.session_id);
      for (const [id, completion] of this.completions) {
        if (completion.sessionId !== event.payload.session_id) continue;
        this.completions.delete(id);
        completion.resolve({ session_id: completion.sessionId, execution_id: id, status: "cancelled", duration_ms: 0, results: [], variables: [] });
      }
    }
    if (event.event !== "execution.finished") return;
    const completion = this.completions.get(event.payload.execution_id);
    if (!completion || completion.sessionId !== event.payload.session_id) return;
    this.completions.delete(event.payload.execution_id);
    this.patchSession(completion.sessionId, (session) => ({ ...session,
      blocks: session.blocks.map((block) => block.id === completion.blockId ? { ...block, status: event.payload.status, duration_ms: event.payload.duration_ms, error: event.payload.error } : block) }));
    completion.resolve(event.payload);
  }
  clearResults(sessionId: string) { this.patchSession(sessionId, (session) => ({ ...session, results: [], images: [], logs: [] })); }
}
