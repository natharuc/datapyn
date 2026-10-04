import { errorText, isRuntimeEvent, type ExecutionFinished, type Language, type ResultRef, type RuntimeEvent, type RuntimeInfo, type RuntimeTransport, type Variable,type RichOutput } from "./runtime";
import type { NativeDocumentRecord, NativeWorkspaceState } from "./nativeDrafts";
import { flushEditorViewStates,restoreEditorViewState, selectedCode, subscribeEditorViewStates } from "./editorRegistry";
import type { QueueCompletion } from "./executionNotifications";
import type { NotificationContext } from "./NotificationsDialog";

export type BlockStatus = "idle" | "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";
export interface Block {
  id: string; block_name: string; language: Language; code: string; is_active: boolean;
  status: BlockStatus; duration_ms?: number; error?: string; height?: number;
  connection_id?: string; database_name?: string; schema?: string; collapsed?: boolean;
  sql_parameters?: Record<string, unknown>[]; sql_parameters_enabled?: boolean;
  cell_type?: "code" | "markdown" | "raw";
  results?: ResultRef[];
  [key: string]: unknown;
}
export interface ConnectionConfig {
  db_type: "sqlserver" | "postgresql" | "mysql" | "mariadb" | "sqlite" | "databricks";
  name?: string; host: string; port: number; database: string; username: string; password?: string;
  schema?: string; http_path?: string; sqlserver_auth_mode?: string;
  use_windows_auth?: boolean; trust_server_certificate?: boolean;
  databricks_auth_mode?:"oauth"|"token";
}
export interface LogLine { id: string; time: string; stream: string; text: string; blockName: string }
export interface SessionDocument {
  id: string; title: string; blocks: Block[]; focusedBlockId: string;
  results: ResultRef[]; variables: Variable[]; images: Array<{ data: string; mime: string }>;
  richOutputs?:RichOutput[];
  logs: LogLine[]; busy: boolean; currentExecutionId?: string; currentBlockId?: string; resultRevision: number;
  connection?: ConnectionConfig; filePath?: string; modified: boolean;
  savedConnectionId?: string; database?: string; schema?: string; maximizedBlockId?: string;
  periodicSeconds?: number; executionStartedAt?: number; lastDurationMs?: number;
  notice?: string; runtimeError?: string; extras: Record<string, unknown>;
}
export interface WorkspaceState {
  sessions: SessionDocument[]; activeId: string; runtimeStatus: "connecting" | "ready" | "unavailable";
  runtimeInfo?: RuntimeInfo; message: string;
  documentRevision?: number;
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
export function decodeDocument(input: unknown, title = "Análise importada", restoreId = false): SessionDocument {
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
  const legacyCharts=(extras.result_view_state as {charts?:{configs?:Record<string,unknown>[]}})?.charts?.configs;
  if(!Array.isArray(extras.charts) && Array.isArray(legacyCharts))session.extras={...extras,charts:legacyCharts.map((config,index)=>({id:newId(),title:String(config.title || `Gráfico ${index+1}`),variable_name:String(config.source_label || "df"),config:{...config}}))};
  const desktop = document.desktop as Record<string, unknown> | undefined;
  if (restoreId && typeof desktop?.session_id === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(desktop.session_id)) session.id = desktop.session_id;
  session.savedConnectionId = typeof desktop?.connection_id === "string" ? desktop.connection_id : undefined;
  session.database = typeof document.database_context === "string" ? document.database_context : undefined;
  session.schema = typeof desktop?.schema === "string" ? desktop.schema : undefined;
  session.focusedBlockId = session.blocks.find(b => b.block_key === desktop?.focused_block_key)?.id ?? session.blocks[0].id;
  return session;
}

export function encodeDocument(session: SessionDocument): Record<string, unknown> {
  const charts=session.extras.charts as Array<{config:Record<string,unknown>;title:string;variable_name:string}>|undefined;
  const resultViewState=charts ? {...(session.extras.result_view_state as object),charts:{...((session.extras.result_view_state as {charts?:object})?.charts),configs:charts.map((chart,index)=>({...chart.config,...(chart.title !== String(chart.config.title || `Gráfico ${index+1}`)?{title:chart.title}:{}),...(chart.variable_name !== String(chart.config.source_label || "df")?{source_label:chart.variable_name}:{})}))}} : session.extras.result_view_state;
  return { ...session.extras, result_view_state:resultViewState, version: "1.0", database_context: session.database ?? session.extras.database_context,
    desktop: { ...(session.extras.desktop as object ?? {}), session_id:session.id, connection_id: session.savedConnectionId, schema: session.schema,
      focused_block_key: session.blocks.find(b => b.id === session.focusedBlockId)?.block_key ?? session.focusedBlockId },
    blocks: session.blocks.map(({ id, status, duration_ms, error, results, ...block }) => ({ ...block, block_key: block.block_key ?? id })) };
}

export function eventBelongsToSession(session: SessionDocument, event: RuntimeEvent): boolean {
  if (event.event === "backend.exited" || event.event === "language.context_updated" || event.event === "result.export_progress" || event.event === "notifications.delivery_finished") return false;
  if (event.payload.session_id !== session.id) return false;
  return event.event === "session.reset" || event.event === "session.error" || event.event === "session.ready" || event.event === "namespace.changed" || event.payload.execution_id === session.currentExecutionId;
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
  if (event.event === "backend.exited" || event.event === "language.context_updated" || event.event === "result.export_progress" || event.event === "notifications.delivery_finished") return session;
  if (!eventBelongsToSession(session, event)) return session;
  if (event.event === "session.ready") return session;
  if (event.event === "namespace.changed") return {...session,variables:event.payload.variables,results:event.payload.results,resultRevision:session.resultRevision+1};
  if (event.event === "session.error") {
    return { ...session, busy: false, currentExecutionId: undefined, currentBlockId: undefined,
      results: [], variables: [], images: [], richOutputs:[], connection: undefined, runtimeError: event.payload.error,
      notice: `Runtime desta sessão indisponível: ${event.payload.error}. Salve a análise, feche esta aba e reabra para criar uma nova sessão.`,
      blocks: session.blocks.map((block) => ["running", "queued", "cancelling"].includes(block.status) ? { ...block, results:undefined, status: "failed", error: event.payload.error } : {...block,results:undefined}),
      logs: appendLog(session, "stderr", event.payload.error + "\n") };
  }
  if (event.event === "session.reset") {
    return { ...session, results: [], variables: [], images: [], richOutputs:[], connection: undefined,
      notice: "Runtime da sessão reiniciado. Variáveis e conexão foram descartadas; reconecte antes de executar SQL.",
      blocks: session.blocks.map((block) => ["running", "queued", "cancelling"].includes(block.status) ? { ...block, results:undefined, status: "cancelled" } : {...block,results:undefined}),
      logs: appendLog(session, "system", "Sessão reiniciada: namespace e conexão descartados.\n") };
  }
  if (event.event === "execution.started") {
    return { ...session, blocks: session.blocks.map((block) => block.id === session.currentBlockId && block.status === "queued" ? { ...block, status: "running" } : block) };
  }
  if (event.event === "execution.output") {
    const running = session.blocks.find((block) => block.status === "running" || block.status === "cancelling");
    return { ...session, logs: appendLog(session, event.payload.stream, event.payload.text, running?.block_name ?? "") };
  }
  if (event.event === "execution.export_progress") return {...session,notice:`Download: ${event.payload.total_rows.toLocaleString()} linhas · ${(event.payload.size_bytes/1048576).toFixed(1)} MiB`};
  const payload = event.payload;
  const resultRefs = payload.results ?? [];
  return { ...session,
    results: payload.status === "failed" ? [] : resultRefs.length ? resultRefs : session.results,
    resultRevision: session.resultRevision + (payload.status === "succeeded" ? 1 : 0),
    // Cancelling a queued job does not restart the kernel. session.reset owns namespace invalidation.
    variables: payload.status === "cancelled" ? session.variables : payload.variables ?? session.variables,
    images: payload.status === "cancelled" ? session.images : payload.rich_outputs?.filter((item) => item.type === "image").map(({ data, mime }) => ({ data, mime })) ?? [],
    richOutputs:payload.status === "cancelled" ? session.richOutputs : payload.rich_outputs ?? [],
    notice:payload.export ? (payload.export.cancelled?"Download cancelado.":`Download concluído: ${payload.export.total_rows.toLocaleString()} linhas · ${payload.export.files.map(f=>f.path).join(", ")}`) : session.notice,
    logs: payload.error ? appendLog(session, "stderr", payload.error + "\n") : payload.export ? appendLog(session,"system",`Download: ${payload.export.files.map(f=>f.path).join(", ")}\n`) : session.logs,
  };
}

type Completion = { resolve: (value: ExecutionFinished) => void; reject: (error: unknown) => void; sessionId: string; blockId: string };
export interface WorkspaceStorage { getItem(key: string): string | null; setItem(key: string, value: string): void;removeItem?(key:string):void }
const STORAGE_KEY = "datapyn.desktop.documents.v1";
const STORAGE_INDEX_KEY = "datapyn.desktop.documents.v2";
const storageDocumentKey=(id:string)=>`${STORAGE_INDEX_KEY}.${id}`;
export interface WorkspaceControllerOptions {nativePersistence?:boolean}

function portableChanged(next:SessionDocument,previous:SessionDocument):boolean {
  if(next===previous)return false;
  if(next.extras!==previous.extras||next.savedConnectionId!==previous.savedConnectionId||next.database!==previous.database||next.schema!==previous.schema||next.blocks.length!==previous.blocks.length)return true;
  if(next.blocks===previous.blocks)return false;
  return next.blocks.some((block,index)=>{
    const before=previous.blocks[index];if(block===before)return false;
    return !before||block.id!==before.id||block.code!==before.code||block.block_name!==before.block_name||block.language!==before.language||block.is_active!==before.is_active||block.height!==before.height||block.collapsed!==before.collapsed||block.connection_id!==before.connection_id||block.database_name!==before.database_name||block.schema!==before.schema||block.sql_parameters!==before.sql_parameters||block.sql_parameters_enabled!==before.sql_parameters_enabled||block.cell_type!==before.cell_type||block.block_key!==before.block_key;
  });
}
function headerChanged(next:SessionDocument,previous:SessionDocument):boolean {
  return next.id!==previous.id||next.title!==previous.title||next.filePath!==previous.filePath||next.modified!==previous.modified||next.focusedBlockId!==previous.focusedBlockId||next.maximizedBlockId!==previous.maximizedBlockId;
}

export class WorkspaceController {
  private state: WorkspaceState;
  private readonly listeners = new Set<() => void>();
  private readonly runtimeSessions = new Set<string>();
  private readonly creatingSessions = new Map<string, Promise<void>>();
  private readonly completions = new Map<string, Completion>();
  private initialization?: Promise<void>;
  private runtimeGeneration = 0;
  private subscribed = false;
  private persistTimer?: ReturnType<typeof setTimeout>;
  private readonly cancelRequests = new Set<string>();
  private readonly periodicTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private sharedDelimiter = "{{name}}";
  private readonly nativeRecords=new Map<string,NativeDocumentRecord>();
  private readonly nativeSources=new Map<string,SessionDocument>();
  private readonly editorViews=new Map<string,Record<string,unknown>>();
  private readonly dirtyBrowserDocuments=new Set<string>();
  private readonly removedBrowserDocuments=new Set<string>();
  private readonly blockOwners=new Map<string,string>();
  private browserMigrationRead=false;
  private editingLocked=false;
  private workspaceIdentity?:string;
  setWorkspaceIdentity(id:string|undefined){this.workspaceIdentity=id;}
  setEditingLocked(locked:boolean){this.editingLocked=locked;}
  isEditingLocked(){return this.editingLocked;}
  private unsubscribeEditorViews?:()=>void;
  setSharedDelimiter(delimiter: string) { this.sharedDelimiter = delimiter; }
  onQueueFinished?: (session: SessionDocument, success: boolean, completion: QueueCompletion) => void;
  nativeSnapshot():NativeWorkspaceState {
    flushEditorViewStates();
    return {documents:this.state.sessions.map(session=>{
      const cached=this.nativeRecords.get(session.id),source=this.nativeSources.get(session.id),views=this.editorViews.get(session.id);
      if(cached&&source&&!portableChanged(session,source)&&!headerChanged(session,source)&&cached.editorViewState===views){this.nativeSources.set(session.id,session);return cached;}
      const document=cached&&source&&!portableChanged(session,source)?cached.document:encodeDocument(session);
      const ids=session.blocks.map(block=>block.id),blockIds=cached?.blockIds?.length===ids.length&&cached.blockIds.every((id,index)=>id===ids[index])?cached.blockIds:ids;
      const record:NativeDocumentRecord={...cached,title:session.title,filePath:session.filePath,modified:session.modified,sessionId:session.id,document,blockIds,focusedBlockId:session.focusedBlockId,maximizedBlockId:session.maximizedBlockId,editorViewState:views};
      this.nativeRecords.set(session.id,record);this.nativeSources.set(session.id,session);return record;
    }),activeIndex:Math.max(0,this.state.sessions.findIndex(session=>session.id===this.state.activeId))};
  }
  restoreSnapshot(snapshot: {documents?:NativeDocumentRecord[];activeIndex?:number}) {
    if(this.state.sessions.some(s=>s.busy))throw new Error("Aguarde ou cancele as execuções antes de trocar de workspace.");
    for(const timer of this.periodicTimers.values())clearTimeout(timer);this.periodicTimers.clear();
    this.runtimeGeneration++;this.runtimeSessions.clear();this.creatingSessions.clear();this.cancelRequests.clear();
    this.nativeRecords.clear();this.nativeSources.clear();this.editorViews.clear();
    const seenBlocks=new Set<string>(),seenSessions=new Set<string>();
    const sessions=(snapshot.documents ?? []).map(entry=>{
      const title=typeof entry.title==="string"?entry.title:"Análise";
      const s=decodeDocument(entry.document,title,true);s.title=title;s.filePath=typeof entry.filePath==="string"?entry.filePath:undefined;s.modified=entry.modified===true;
      if(entry.sessionId&&/^[A-Za-z0-9_-]{1,128}$/.test(entry.sessionId))s.id=entry.sessionId;
      if(seenSessions.has(s.id))s.id=newId();seenSessions.add(s.id);
      s.blocks=s.blocks.map((block,index)=>{const savedId=entry.blockIds?.[index];if(typeof savedId==="string"&&/^[A-Za-z0-9_-]{1,128}$/.test(savedId)&&!seenBlocks.has(savedId))block={...block,id:savedId};seenBlocks.add(block.id);return block;});
      if(entry.focusedBlockId&&s.blocks.some(block=>block.id===entry.focusedBlockId))s.focusedBlockId=entry.focusedBlockId;
      if(entry.maximizedBlockId&&s.blocks.some(block=>block.id===entry.maximizedBlockId))s.maximizedBlockId=entry.maximizedBlockId;
      if(entry.editorViewState&&typeof entry.editorViewState==="object"){
        const views:Record<string,unknown>={};for(const block of s.blocks){const saved=entry.editorViewState[block.id];if(saved&&restoreEditorViewState(block.id,saved))views[block.id]=saved;}
        if(Object.keys(views).length)this.editorViews.set(s.id,views);
      }
      this.nativeRecords.set(s.id,{...entry,title:s.title,filePath:s.filePath,sessionId:s.id,editorViewState:this.editorViews.get(s.id)});this.nativeSources.set(s.id,s);return s;
    });
    if(!sessions.length)sessions.push(newSession());
    this.setState({...this.state,sessions,activeId:sessions[snapshot.activeIndex ?? 0]?.id ?? sessions[0].id},true);
  }

  constructor(private readonly transport: RuntimeTransport, private readonly storage?: WorkspaceStorage,private readonly options:WorkspaceControllerOptions={}) {
    const sessions=[newSession()];
    this.state = { sessions, activeId: sessions[0].id, runtimeStatus: "connecting", message: "Iniciando runtime Python…" };
    this.state.sessions.forEach(session=>{this.dirtyBrowserDocuments.add(session.id);session.blocks.forEach(block=>this.blockOwners.set(block.id,session.id));});
    if(!options.nativePersistence){const snapshot=this.readBrowserSnapshot();if(snapshot?.documents){try{this.restoreSnapshot(snapshot);}catch{/* Preserve the unreadable source without blocking preview startup. */}}}
    this.unsubscribeEditorViews=subscribeEditorViewStates((blockId,view)=>{
      const sessionId=this.blockOwners.get(blockId);if(!sessionId)return;
      const before=this.editorViews.get(sessionId)??{};
      this.editorViews.set(sessionId,{...before,[blockId]:view});this.dirtyBrowserDocuments.add(sessionId);
      this.state={...this.state,documentRevision:(this.state.documentRevision??0)+1};this.listeners.forEach(listener=>listener());
      if(!this.options.nativePersistence&&this.storage){clearTimeout(this.persistTimer);this.persistTimer=setTimeout(()=>this.persist(),500);}
    });
  }

  private readBrowserSnapshot():({sessions?:Array<Record<string,unknown>>}&Partial<NativeWorkspaceState>)|undefined {
    try{
      const index=JSON.parse(this.storage?.getItem(STORAGE_INDEX_KEY)??"null");
      if(index?.version===2&&Array.isArray(index.order)){
        const documents=index.order.map((id:unknown)=>typeof id==="string"?JSON.parse(this.storage?.getItem(storageDocumentKey(id))??"null"):null).filter((record:NativeDocumentRecord|null)=>record?.document);
        return{documents,activeIndex:Math.max(0,documents.findIndex((record:NativeDocumentRecord)=>record.sessionId===index.activeId))};
      }
      const old=JSON.parse(this.storage?.getItem(STORAGE_KEY)??"null");
      if(Array.isArray(old?.sessions))return{documents:old.sessions,activeIndex:old.activeIndex??0,sessions:old.sessions};
    }catch{/* Preserve an unreadable legacy recovery file and allow startup. */}
  }
  /** Read browser recovery only when the native profile has no authoritative state. */
  restoreBrowserDraftMigration():boolean {
    if(this.browserMigrationRead)return false;this.browserMigrationRead=true;
    const saved=this.readBrowserSnapshot();if(!saved?.documents?.length)return false;
    this.restoreSnapshot({documents:saved.documents,activeIndex:saved.activeIndex});return true;
  }
  dispose(){this.unsubscribeEditorViews?.();this.unsubscribeEditorViews=undefined;if(this.persistTimer)clearTimeout(this.persistTimer);for(const timer of this.periodicTimers.values())clearTimeout(timer);this.periodicTimers.clear();}

  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private setState(next: WorkspaceState,restore=false) {
    const previousById=new Map(this.state.sessions.map(session=>[session.id,session]));
    const changed = next.sessions.length !== this.state.sessions.length || next.activeId !== this.state.activeId || next.sessions.some((s,i)=>{
      const before=this.state.sessions[i];if(!before)return true;
      if(s===before)return false;
      return headerChanged(s,before)||portableChanged(s,before);
    });
    if(this.editingLocked && changed && !restore)return;
    next={...next,documentRevision:(this.state.documentRevision ?? 0)+(changed?1:0)};
    this.state = next;
    if(changed){
      for(const session of next.sessions){
        const before=previousById.get(session.id);previousById.delete(session.id);
        if(!before||headerChanged(session,before)||portableChanged(session,before))this.dirtyBrowserDocuments.add(session.id);
        if(before?.blocks!==session.blocks){
          before?.blocks.forEach(block=>this.blockOwners.delete(block.id));
          session.blocks.forEach(block=>this.blockOwners.set(block.id,session.id));
        }
      }
      previousById.forEach(session=>{
        session.blocks.forEach(block=>this.blockOwners.delete(block.id));this.removedBrowserDocuments.add(session.id);this.dirtyBrowserDocuments.delete(session.id);
        this.nativeRecords.delete(session.id);this.nativeSources.delete(session.id);this.editorViews.delete(session.id);
      });
    }
    this.listeners.forEach((listener) => listener());
    if (this.storage && changed&&!this.options.nativePersistence) {
      clearTimeout(this.persistTimer);
      this.persistTimer = setTimeout(() => this.persist(), 500);
    }
  }
  persist() {
    if(this.options.nativePersistence||!this.storage)return;
    if(this.persistTimer){clearTimeout(this.persistTimer);this.persistTimer=undefined;}
    try {
      const snapshot=this.nativeSnapshot();
      for(const record of snapshot.documents){if(!this.dirtyBrowserDocuments.has(record.sessionId!))continue;this.storage.setItem(storageDocumentKey(record.sessionId!),JSON.stringify(record));this.dirtyBrowserDocuments.delete(record.sessionId!);}
      this.storage.setItem(STORAGE_INDEX_KEY,JSON.stringify({version:2,order:snapshot.documents.map(record=>record.sessionId),activeId:this.state.activeId}));
      for(const id of this.removedBrowserDocuments){this.storage.removeItem?.(storageDocumentKey(id));this.removedBrowserDocuments.delete(id);}
    }
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
  importDocuments(input: unknown, title: string, path?: string) {
    const outer = object(input), document = "document" in outer ? object(outer.document) : outer;
    const tabs = document.tabs ?? document.sessions;
    if (!Array.isArray(tabs)) return [this.importDocument(document,title,path)];
    return tabs.map((tab,index) => this.importDocument(tab, String(object(tab).title ?? `${title} ${index+1}`)));
  }
  duplicateSession(id: string) {
    const original = this.session(id); if (!original) return;
    const copy = this.importDocument(encodeDocument(original),`${original.title} (cópia)`);
    this.patchSession(copy.id,s=>({...s,title:`${original.title} (cópia)`,modified:true}));return copy;
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
    this.stopPeriodic(id);
    if (this.runtimeSessions.has(id)) await this.transport.request("session.close", { session_id: id });
    this.runtimeSessions.delete(id);
    let sessions = this.state.sessions.filter((session) => session.id !== id);
    if (!sessions.length) sessions = [newSession()];
    this.setState({ ...this.state, sessions, activeId: this.state.activeId === id ? sessions[0].id : this.state.activeId });
  }
  reorderBlock(sessionId: string, blockId: string, beforeId: string) {
    this.patchSession(sessionId, session => {
      if (session.busy || blockId === beforeId) return session;
      const source = session.blocks.find(b => b.id === blockId); if (!source) return session;
      const blocks = session.blocks.filter(b => b.id !== blockId), index = blocks.findIndex(b => b.id === beforeId);
      blocks.splice(index < 0 ? blocks.length : index, 0, source);
      return { ...session, blocks, modified: true };
    });
  }
  duplicateBlock(sessionId: string, blockId: string) {
    const source = this.session(sessionId)?.blocks.find(b => b.id === blockId); if (!source) return;
    const copy = this.addBlock(sessionId, source.language, source.code, blockId);
    const { id: _id, status: _status, error: _error, duration_ms: _duration, results: _results, ...definition } = source;
    this.updateBlock(sessionId, copy.id, { ...definition, block_key: copy.id, block_name: source.block_name ? `${source.block_name}_copy` : "" });
    return copy;
  }
  maximizeBlock(sessionId: string, blockId?: string) { this.patchSession(sessionId, s => ({ ...s, maximizedBlockId: s.maximizedBlockId === blockId ? undefined : blockId })); }
  async connectSaved(sessionId: string, connectionId: string) {
    if (this.session(sessionId)?.busy) throw new Error("Aguarde a execução para trocar a conexão.");
    await this.ensureSession(sessionId);
    const response = await this.transport.request<{ connection?: ConnectionConfig; config?: ConnectionConfig; database?: string; schema?: string }>("connection.connect", { session_id: sessionId, connection_id: connectionId });
    this.patchSession(sessionId, s => ({ ...s, savedConnectionId: connectionId, connection: response.config ?? response.connection,
      database: response.database ?? response.config?.database ?? response.connection?.database, schema: response.schema, notice: undefined }));
    return response;
  }
  async disconnect(sessionId: string) {
    if (this.session(sessionId)?.busy) throw new Error("Aguarde a execução antes de desconectar.");
    await this.ensureSession(sessionId); await this.transport.request("connection.disconnect", { session_id: sessionId });
    this.patchSession(sessionId, s => ({ ...s, connection: undefined, savedConnectionId: undefined, database: undefined, schema: undefined,extras:{...s.extras,connection_name:undefined,connection_group:undefined} }));
  }
  setContext(sessionId: string, context: { database?: string; schema?: string }, blockId?: string) {
    if (blockId && this.session(sessionId)?.blocks[0].id !== blockId) { this.updateBlock(sessionId, blockId, { database_name: context.database, schema: context.schema }); return; }
    this.patchSession(sessionId, s => ({ ...s, ...context }));
  }
  async startPeriodic(sessionId: string, seconds: number) {
    if (!Number.isFinite(seconds) || seconds < 1) throw new Error("Informe um intervalo de pelo menos um segundo.");
    this.stopPeriodic(sessionId);
    this.patchSession(sessionId, s => ({ ...s, periodicSeconds: seconds }));
    await this.runAll(sessionId);
  }
  stopPeriodic(sessionId: string) {
    clearTimeout(this.periodicTimers.get(sessionId)); this.periodicTimers.delete(sessionId);
    this.patchSession(sessionId, s => ({ ...s, periodicSeconds: undefined }));
  }
  private schedulePeriodic(sessionId: string) {
    clearTimeout(this.periodicTimers.get(sessionId));
    const seconds = this.session(sessionId)?.periodicSeconds; if (!seconds) return;
    this.periodicTimers.set(sessionId, setTimeout(() => {
      if (!this.session(sessionId)?.periodicSeconds) return;
      if (this.session(sessionId)?.busy) { this.schedulePeriodic(sessionId); return; }
      void this.runAll(sessionId).catch(error => { this.message(errorText(error)); this.stopPeriodic(sessionId); });
    }, seconds * 1000));
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
  ensureSession(sessionId: string): Promise<void> {
    const pending = this.creatingSessions.get(sessionId); if (pending) return pending;
    const creating = this.createRuntimeSession(sessionId).finally(() => this.creatingSessions.delete(sessionId));
    this.creatingSessions.set(sessionId, creating);
    return creating;
  }
  private async createRuntimeSession(sessionId: string) {
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
    this.patchSession(sessionId, (session) => ({ ...session, connection: safeConfig, savedConnectionId: undefined, database: config.database, schema: config.schema, notice: undefined,extras:{...session.extras,connection_name:undefined,connection_group:undefined} }));
    this.message(`Conectado: ${config.name || config.database || config.db_type}`);
  }
  async schema(sessionId: string): Promise<Record<string, unknown>> {
    await this.ensureSession(sessionId);
    return this.transport.request("schema.get", { session_id: sessionId });
  }
  async runBlock(sessionId: string, blockId: string, selection?: string, advance = false) {
    const session = this.session(sessionId), block = session?.blocks.find((item) => item.id === blockId);
    if (!session || !block) return;
    // Capture before awaiting: blur and advancing focus must not change what runs.
    const code = selection ?? selectedCode(blockId, block.code) ?? block.code;
    await this.runQueue(sessionId, [{ ...block, code }]);
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
  async runToFile(sessionId:string,blockId:string,exportOptions:{path:string;format:"csv"|"parquet";options?:Record<string,unknown>},selection?:string) {
    const block=this.session(sessionId)?.blocks.find(b=>b.id === blockId);
    if(!block || block.language !== "sql")throw new Error("O download direto requer um bloco SQL.");
    return this.runQueue(sessionId,[{...block,code:selection ?? block.code,export:exportOptions}]);
  }
  private async runQueue(sessionId: string, queue: Block[]) {
    const workspaceId = this.workspaceIdentity;
    const session = this.session(sessionId);
    if (session?.runtimeError) throw new Error(session.notice ?? session.runtimeError);
    if (this.session(sessionId)?.busy) throw new Error("Esta aba já tem uma execução em andamento.");
    const runnable = queue.filter((block) => block.code.trim() && (!block.cell_type || block.cell_type === "code"));
    if (!runnable.length) { this.message("Escreva código no bloco antes de executar."); return; }
    this.cancelRequests.delete(sessionId);
    this.patchSession(sessionId, (session) => ({ ...session, busy: true, executionStartedAt: Date.now(), notice: undefined,
      blocks: session.blocks.map((block) => runnable.some((item) => item.id === block.id) ? { ...block, status: "queued", error: undefined } : block) }));
    let succeeded = true, failedError: string | undefined, cancelled = false;
    let lastBlock = runnable[0], lastExecutionId = newId();
    let lastContext: NotificationContext = { tab_name: session?.title, block_name: lastBlock.block_name, blocks: 0,
      type: lastBlock.language === "sql" ? "SQL" : "Python", rows: 0 };
    let completed:ExecutionFinished|undefined;
    let queueResult:{result_id:string;rows:number}|undefined;
    try {
      await this.ensureSession(sessionId);
      for (const [index, block] of runnable.entries()) {
        if (this.cancelRequests.has(sessionId)) {succeeded=false;cancelled=true;break;}
        lastBlock = block; if (index) lastExecutionId = newId();
        lastContext = { tab_name: session?.title, block_name: block.block_name, blocks: index + 1,
          type: block.language === "sql" ? "SQL" : "Python", rows: 0, connection: String(block.connection_name ?? session?.extras.connection_name ?? session?.connection?.name ?? ""), database: block.database_name ?? session?.database };
        const result = await this.runOne(sessionId, block, lastExecutionId, {
          config: session?.extras.notification_config, context: { ...lastContext, block_id: block.id, workspace_id: workspaceId }, queue_result:queueResult, emit_notification: index === runnable.length - 1,
        });
        completed = result;
        const frame = result.results.at(-1);
        if(frame)queueResult={result_id:frame.result_id,rows:frame.row_count};
        lastContext = { ...lastContext, success: result.status === "succeeded", error: result.error,
          result_id: frame?.result_id ?? (result.status === "succeeded" ? queueResult?.result_id : undefined), rows: result.export?.total_rows ?? frame?.row_count ?? (result.status === "succeeded" ? queueResult?.rows ?? 0 : 0) };
        if (result.status !== "succeeded") { succeeded = false; cancelled = result.status === "cancelled"; this.message(result.status === "failed" ? "Fila interrompida após erro." : "Execução cancelada."); break; }
      }
    } catch (error) { succeeded = false; failedError = errorText(error); this.message(failedError); throw error; }
    finally {
      this.cancelRequests.delete(sessionId);
      this.patchSession(sessionId, (session) => ({ ...session, busy: false, lastDurationMs: session.executionStartedAt ? Date.now() - session.executionStartedAt : undefined, executionStartedAt: undefined, currentExecutionId: undefined, currentBlockId: undefined,
        blocks: session.blocks.map((block) => ["queued", "running", "cancelling"].includes(block.status) ? { ...block, status: "cancelled" } : block) }));
      this.schedulePeriodic(sessionId);
      const current = this.session(sessionId);
      const status = cancelled ? "cancelled" : succeeded ? "succeeded" : "failed";
      if(current) try { this.onQueueFinished?.(current,succeeded,{ blockId: lastBlock.id, executionId: lastExecutionId, workspaceId,
        status,
        context: { ...lastContext, success: succeeded, error: failedError ?? (cancelled ? "Execução cancelada." : lastContext.error) },
        notification: !failedError && completed?.execution_id === lastExecutionId && completed.status === status ? completed.notification : undefined }); }
      catch(error) { this.message(errorText(error)); }
    }
    return completed;
  }
  private async runOne(sessionId: string, block: Block, executionId: string, notification: Record<string, unknown>): Promise<ExecutionFinished> {
    const completion = new Promise<ExecutionFinished>((resolve, reject) => this.completions.set(executionId, { resolve, reject, sessionId, blockId: block.id }));
    // The event channel may report failure before execution.run's request acknowledgement.
    void completion.catch(() => {});
    this.patchSession(sessionId, (session) => ({ ...session, currentExecutionId: executionId, currentBlockId: block.id,
      blocks: session.blocks.map((item) => item.id === block.id ? { ...item, status: "running", error: undefined } : item) }));
    const acknowledged = this.transport.request("execution.run", { session_id: sessionId, execution_id: executionId,
      language: block.language, code: block.code,
      ...(block.language === "sql" ? { variable_name: block.block_name || undefined } : {}),
      connection_id: block.connection_id ?? this.session(sessionId)?.savedConnectionId,
      database: block.database_name ?? this.session(sessionId)?.database, schema: block.schema ?? this.session(sessionId)?.schema,
      sql_parameters: block.sql_parameters_enabled === false ? [] : block.sql_parameters ?? [],
      connection_name: block.connection_id ? undefined : block.connection_name ?? this.session(sessionId)?.extras.connection_name,
      connection_group: block.connection_id ? undefined : block.connection_group ?? this.session(sessionId)?.extras.connection_group,
      shared_parameters: this.session(sessionId)?.extras.shared_parameters_enabled === false ? [] : this.session(sessionId)?.extras.shared_parameters ?? [],
      shared_delimiter: this.sharedDelimiter,
      export: block.export,
      notification,
    }).then(() => completion).catch((error) => {
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
    this.stopPeriodic(sessionId); this.cancelRequests.add(sessionId);
    this.patchSession(sessionId, (item) => ({ ...item, notice: "Cancelamento reinicia somente esta sessão e descarta suas variáveis e conexão.",
      blocks: item.blocks.map((block) => block.status === "running" ? { ...block, status: "cancelling" } : block) }));
    if (session.currentExecutionId) await this.transport.request("execution.cancel", { session_id: sessionId, execution_id: session.currentExecutionId });
  }
  onRuntimeEvent(event: RuntimeEvent) {
    if (!isRuntimeEvent(event)) return;
    if (event?.event === "backend.exited") {
      const message = event.payload.message || "O runtime Python foi encerrado.";
      for (const timer of this.periodicTimers.values()) clearTimeout(timer); this.periodicTimers.clear();
      this.runtimeGeneration++; this.initialization = undefined; this.runtimeSessions.clear();
      for (const completion of this.completions.values()) completion.reject(new Error(message));
      this.completions.clear();
      this.setState({ ...this.state, runtimeStatus: "unavailable", runtimeInfo: undefined, message,
        sessions: this.state.sessions.map((session) => ({ ...session, busy: false, currentExecutionId: undefined, currentBlockId: undefined,
          connection: undefined, variables: [], results: [], images: [], richOutputs:[], periodicSeconds:undefined, runtimeError: undefined, notice: "Runtime encerrado. As variáveis e conexões foram descartadas.",
          blocks: session.blocks.map((block) => block.status === "running" || block.status === "cancelling" ? { ...block, results:undefined, status: "failed", error: message } : block.status === "queued" ? { ...block, results:undefined, status: "cancelled" } : {...block,results:undefined}) })) });
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
      blocks: session.blocks.map((block) => block.id === completion.blockId ? { ...block, status: event.payload.status, duration_ms: event.payload.duration_ms, error: event.payload.error, results: event.payload.results } : block) }));
    completion.resolve(event.payload);
  }
  clearResults(sessionId: string) { this.patchSession(sessionId, (session) => ({ ...session, results: [], images: [],richOutputs:[], logs: [],blocks:session.blocks.map(b=>({...b,results:undefined})) })); }
  closeResult(sessionId:string,resultId:string) {
    this.patchSession(sessionId,s=>({...s,results:s.results.filter(r=>r.result_id !== resultId),blocks:s.blocks.map(b=>({...b,results:b.results?.filter(r=>r.result_id !== resultId)}))}));
    void this.transport.request("result.release",{session_id:sessionId,result_id:resultId}).catch(error=>this.message(errorText(error)));
  }
}
