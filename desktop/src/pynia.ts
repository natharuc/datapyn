import { runtime, errorText, type RuntimeTransport } from "./runtime";
import { subscribeServiceEvents, type ServiceEvent } from "./serviceEvents";
import {translate as t} from "./i18n";
export interface PyniaAgent { id: string; label: string; color?: string; status: string; detail?: string; install_command?: string; docs_url?: string; login_command?: string[] }
export interface PyniaAttachment { kind: "image" | "file"; name: string; mime: string; data?: string; text?: string; src?: string }
export interface PyniaToolActivity { id: string; title?: string; status?: string; error?: string }
export interface PyniaMessage { role: string; content: string; attachments?: PyniaAttachment[]; activity?: { thinking?: string; tools?: PyniaToolActivity[] }; [key: string]: unknown }
export interface PyniaSelector { id: string; label?: string; current: string; hidden?: boolean; loading?: boolean; values: Array<{ value: string; name: string; description?: string }> }
export interface PyniaAgentPreferences { model_id?: string; thought_level?: string }
export interface PyniaDefaults extends PyniaAgentPreferences {
  default_agent_id?: string;
  agent_prefs?: Record<string, PyniaAgentPreferences>;
}
export interface PyniaPermission { request_id: string; params: Record<string, unknown> }
export interface PyniaState {
  agent_id?: string | null; acp_session_id?: string | null; locked: boolean; busy: boolean; messages: PyniaMessage[];
  selectors?: { model?: PyniaSelector; reasoning?: PyniaSelector }; permissions: PyniaPermission[]; error?: string;
  thinking?: string; tools?: PyniaToolActivity[]; [key: string]: unknown;
  fresh_conversation?: boolean; defaults_applied?: boolean; config_loading?: boolean;
}
export interface AgentInstallation { running: boolean; output: string; error?: string; success?: boolean }
export interface PyniaSnapshot { agents: PyniaAgent[]; sessions: Record<string, PyniaState>; installations: Record<string, AgentInstallation>; error: string }
export const emptyPyniaState = (): PyniaState => ({ locked: false, busy: false, messages: [], permissions: [] });
type EventSubscribe = (callback: (event: ServiceEvent) => void) => Promise<() => void>;

/** A restored agent/configuration is a conversation even before its first message. */
export function isFreshPyniaConversation(input?: unknown): boolean {
  if (input == null) return true;
  if (typeof input !== "object" || Array.isArray(input)) return false;
  const state = input as Record<string, unknown>;
  if (state.locked || state.busy || state.acp_session_id || Array.isArray(state.messages) && state.messages.length > 0) return false;
  if (state.config_snapshot && typeof state.config_snapshot === "object" && Object.keys(state.config_snapshot).length > 0) return false;
  if (state.fresh_conversation === false) return false;
  // The broker can select the global default without opening an ACP session.
  return state.fresh_conversation === true || !state.agent_id;
}

/** Legacy global model/reasoning preferences belong only to the default agent. */
export function pyniaAgentPreferences(defaults: PyniaDefaults | undefined, agentId?: string | null): PyniaAgentPreferences {
  if (!defaults || !agentId) return {};
  const stored = defaults.agent_prefs?.[agentId], useGlobal = defaults.default_agent_id === agentId;
  const model = stored?.model_id?.trim() || (useGlobal ? defaults.model_id?.trim() : "");
  const thought = stored?.thought_level?.trim() || (useGlobal && defaults.thought_level !== "auto" ? defaults.thought_level?.trim() : "");
  return { ...(model ? { model_id: model } : {}), ...(thought ? { thought_level: thought } : {}) };
}

/** Presentation only: never invent selector options or replace the live selection. */
export function advertisedPyniaDefaults(defaults: PyniaDefaults | undefined, state: PyniaState | undefined): { model?: string; reasoning?: string } {
  if (!state || state.locked || state.messages.length || !(state.fresh_conversation || state.defaults_applied)) return {};
  const preferences = pyniaAgentPreferences(defaults, state.agent_id);
  const offered = (selector: PyniaSelector | undefined, value: string | undefined) =>
    value && selector && !selector.hidden && !selector.loading && selector.values.some((option) => option.value === value) ? value : undefined;
  const model = offered(state.selectors?.model, preferences.model_id), reasoning = offered(state.selectors?.reasoning, preferences.thought_level);
  return { ...(model ? { model } : {}), ...(reasoning ? { reasoning } : {}) };
}

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
  async attach(sessionId: string, data?: unknown, defaults?: PyniaDefaults) {
    await this.ensureEvents();
    if (this.loaded.has(sessionId)) return;
    this.loaded.add(sessionId);
    const revision = this.revisions.get(sessionId) ?? 0;
    try { const state = await this.transport.request<PyniaState>("pynia.state", { session_id: sessionId, data, ...(defaults && isFreshPyniaConversation(data) ? { defaults } : {}) }); if ((this.revisions.get(sessionId) ?? 0) === revision) this.patch(sessionId, () => ({ ...emptyPyniaState(), ...state })); }
    catch (error) { this.loaded.delete(sessionId); this.patch(sessionId, (state) => ({ ...state, error: errorText(error) })); }
  }
  async request(method: string, sessionId: string, params: Record<string, unknown> = {}, defaults?: PyniaDefaults) {
    const useDefaults = defaults && (method === "pynia.clear" || method === "pynia.select_agent" && isFreshPyniaConversation(this.state.sessions[sessionId]));
    // Defaults are passed once at creation/explicit clear. The broker performs
    // the actual ACP negotiation, including advertised-value checks.
    try { return await this.transport.request(method, { ...params, session_id: sessionId, ...(useDefaults ? { defaults } : {}) }); }
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
