import { runtime, errorText, type RuntimeTransport } from "./runtime";
import { subscribeServiceEvents, type ServiceEvent } from "./serviceEvents";
import {translate as t} from "./i18n";
export interface PyniaAgent { id: string; label: string; color?: string; status: string; detail?: string; install_command?: string; docs_url?: string; login_command?: string[] }
export interface PyniaAttachment { kind: "image" | "file"; name: string; mime: string; data?: string; text?: string; src?: string }
export interface PyniaToolActivity { id: string; title?: string; status?: string; error?: string }
export interface PyniaMessage { role: string; content: string; attachments?: PyniaAttachment[]; activity?: { thinking?: string; tools?: PyniaToolActivity[] }; [key: string]: unknown }
export interface PyniaSelector { id: string; label?: string; current: string; hidden?: boolean; loading?: boolean; values: Array<{ value: string; name: string; description?: string }> }
export interface PyniaPermission { request_id: string; params: Record<string, unknown> }
export interface PyniaState {
  agent_id?: string | null; acp_session_id?: string | null; locked: boolean; busy: boolean; messages: PyniaMessage[];
  selectors?: { model?: PyniaSelector; reasoning?: PyniaSelector }; permissions: PyniaPermission[]; error?: string;
  thinking?: string; tools?: PyniaToolActivity[]; [key: string]: unknown;
}
export interface AgentInstallation { running: boolean; output: string; error?: string; success?: boolean }
export interface PyniaSnapshot { agents: PyniaAgent[]; sessions: Record<string, PyniaState>; installations: Record<string, AgentInstallation>; error: string }
export const emptyPyniaState = (): PyniaState => ({ locked: false, busy: false, messages: [], permissions: [] });
type EventSubscribe = (callback: (event: ServiceEvent) => void) => Promise<() => void>;

export class PyniaController {
  private state: PyniaSnapshot = { agents: [], sessions: {}, installations: {}, error: "" };
  private listeners = new Set<() => void>();
  private subscribed?: Promise<void>; private unsubscribe?: () => void;
  private loaded = new Set<string>(); private revisions = new Map<string, number>();
  private chunks = new Map<string, string>(); private chunkTimer?: ReturnType<typeof setTimeout>;
  constructor(private transport: RuntimeTransport = runtime, private events: EventSubscribe = subscribeServiceEvents) {}
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private update(next: PyniaSnapshot) { this.state = next; this.listeners.forEach((listener) => listener()); }
  private patch(id: string, updater: (state: PyniaState) => PyniaState) { this.update({ ...this.state, sessions: { ...this.state.sessions, [id]: updater(this.state.sessions[id] ?? emptyPyniaState()) } }); }
  private async ensureEvents() {
    if (!this.subscribed) this.subscribed = this.events((event) => this.onEvent(event)).then((unsubscribe) => { this.unsubscribe = unsubscribe; });
    await this.subscribed;
  }
  async catalog() {
    try { await this.ensureEvents(); const result = await this.transport.request<{ agents: PyniaAgent[] }>("pynia.catalog"); this.update({ ...this.state, agents: result.agents, error: "" }); }
    catch (error) { this.update({ ...this.state, error: errorText(error) }); }
  }
  async attach(sessionId: string, data?: unknown) {
    await this.ensureEvents();
    if (this.loaded.has(sessionId)) return;
    this.loaded.add(sessionId);
    const revision = this.revisions.get(sessionId) ?? 0;
    try { const state = await this.transport.request<PyniaState>("pynia.state", { session_id: sessionId, data }); if ((this.revisions.get(sessionId) ?? 0) === revision) this.patch(sessionId, () => ({ ...emptyPyniaState(), ...state })); }
    catch (error) { this.loaded.delete(sessionId); this.patch(sessionId, (state) => ({ ...state, error: errorText(error) })); }
  }
  async request(method: string, sessionId: string, params: Record<string, unknown> = {}) {
    try { return await this.transport.request(method, { ...params, session_id: sessionId }); }
    catch (error) { this.patch(sessionId, (state) => ({ ...state, error: errorText(error) })); throw error; }
  }
  onEvent(event: ServiceEvent) {
    if(event.event==="session.ready"&&typeof event.payload.session_id==="string"&&!this.loaded.has(event.payload.session_id)&&this.state.sessions[event.payload.session_id]){void this.attach(event.payload.session_id,this.state.sessions[event.payload.session_id]).catch(()=>{});return;}
    if(event.event==="backend.exited") {
      clearTimeout(this.chunkTimer);this.chunkTimer=undefined;this.chunks.clear();this.loaded.clear();
      const sessions=Object.fromEntries(Object.entries(this.state.sessions).map(([id,state])=>[id,{...state,busy:false,permissions:[],error:t("O runtime foi encerrado. Reinicie o runtime para continuar o chat.")} ]));
      this.update({...this.state,sessions});return;
    }
    if (!event.event.startsWith("pynia.")) return;
    if (event.event.startsWith("pynia.install_") && typeof event.payload.agent_id === "string") {
      const id = event.payload.agent_id, previous = this.state.installations[id] ?? { running: true, output: "" };
      this.update({ ...this.state, installations: { ...this.state.installations, [id]: event.event === "pynia.install_output" ? { ...previous, running: true, output: (previous.output + String(event.payload.text ?? "")).slice(-100000) } : { ...previous, running: false, success: event.payload.success === true, error: event.payload.error ? String(event.payload.error) : undefined } } });
      if (event.event === "pynia.install_finished") void this.catalog();
      return;
    }
    const id = event.payload.session_id;
    if (typeof id !== "string") return;
    this.revisions.set(id, (this.revisions.get(id) ?? 0) + 1);
    const payload = event.payload;
    if (event.event === "pynia.state" && payload.state && typeof payload.state === "object") {
      this.chunks.delete(id); this.patch(id, () => ({ ...emptyPyniaState(), ...payload.state as PyniaState }));
    } else if (event.event === "pynia.chunk" && typeof payload.text === "string") {
      this.chunks.set(id, (this.chunks.get(id) ?? "") + payload.text);
      if (!this.chunkTimer) this.chunkTimer = setTimeout(() => this.flushChunks(), 32);
    } else if (event.event === "pynia.thinking" && typeof payload.text === "string") this.patch(id, (state) => ({ ...state, thinking: ((state.thinking ?? "") + payload.text).slice(-8000) }));
    else if (event.event === "pynia.tool" && payload.payload && typeof payload.payload === "object") this.patch(id, (state) => ({ ...state, tools: mergeToolActivity(state.tools ?? [], payload.payload as Record<string, unknown>) }));
    else if (event.event === "pynia.permission" && typeof payload.request_id === "string") this.patch(id, (state) => ({ ...state, permissions: [...(state.permissions ?? []).filter((permission) => permission.request_id !== payload.request_id), { request_id: payload.request_id as string, params: (payload.params ?? {}) as Record<string, unknown> }] }));
    else if (event.event === "pynia.error" && typeof payload.error === "string") this.patch(id, (state) => ({ ...state, error: payload.error as string, busy: false }));
    else if (event.event === "pynia.turn_ended") { this.flushChunks(); this.patch(id, (state) => ({ ...state, busy: false })); }
  }
  flushChunks() {
    clearTimeout(this.chunkTimer); this.chunkTimer = undefined;
    for (const [id, text] of this.chunks) this.patch(id, (state) => {
      const messages = [...state.messages], previous = messages.at(-1);
      if (previous?.role === "assistant") messages[messages.length - 1] = { ...previous, content: previous.content + text };
      else messages.push({ role: "assistant", content: text });
      return { ...state, messages, busy: true };
    });
    this.chunks.clear();
  }
  dispose() { this.unsubscribe?.(); this.unsubscribe = undefined; this.subscribed = undefined; clearTimeout(this.chunkTimer); this.chunkTimer = undefined; this.chunks.clear(); }
}
export const pynia = new PyniaController();

export function mergeToolActivity(previous: PyniaToolActivity[], payload: Record<string, unknown>): PyniaToolActivity[] {
  const nested = payload.toolCall && typeof payload.toolCall === "object" ? payload.toolCall as Record<string, unknown> : {};
  const id = String(payload.toolCallId ?? nested.toolCallId ?? payload.id ?? nested.id ?? payload.title ?? "tool");
  const title = String(payload.title ?? nested.title ?? "").replace(/^datapyn[-/.](?=datapyn_)/i, "");
  const status = String(payload.status ?? nested.status ?? (payload.sessionUpdate === "tool_call_update" ? "completed" : "running"));
  const card: PyniaToolActivity = { id, status, ...(title ? { title } : {}), ...(payload.error ? { error: String(payload.error) } : {}) };
  const exists = previous.find((tool) => tool.id === id);
  return exists ? previous.map((tool) => tool.id === id ? { ...tool, ...card } : tool) : [...previous, card].slice(-80);
}

export function normalizePastedAttachment(file: File): Promise<PyniaAttachment> {
  if (file.size > 4 * 1024 * 1024) return Promise.reject(new Error(t("Cada anexo deve ter até 4 MB.")));
  const image = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"].includes(file.type);
  return new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onerror = () => reject(new Error(t("Não foi possível ler o anexo.")));
    reader.onload = () => { const value = String(reader.result ?? ""); resolve(image ? { kind: "image", name: file.name || "clipboard.png", mime: file.type, data: value.split(",")[1] } : { kind: "file", name: file.name, mime: file.type || "text/plain", text: value.slice(0, 24000) }); };
    if (image) reader.readAsDataURL(file); else reader.readAsText(file);
  });
}
