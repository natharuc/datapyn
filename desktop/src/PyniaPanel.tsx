import { translate as t, useLocale } from "./i18n";
import { memo, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Check, Code2, Copy, LoaderCircle, Paperclip, RefreshCw, Send, Settings2, Square, Trash2, X } from "lucide-react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { open } from "@tauri-apps/plugin-dialog";
import { openUrl } from "@tauri-apps/plugin-opener";
import { errorText, isDesktop, runtime } from "./runtime";
import { pynia, normalizePastedAttachment, advertisedPyniaDefaults, type PyniaDefaults, type PyniaAttachment, type PyniaMessage, type PyniaPermission, type PyniaSelector, type PyniaState, type PyniaAgent } from "./pynia";
import { Modal } from "./PanelControls";
import { AgentIcon } from "./AgentIcon";
import "./pynia.css";

export interface PyniaPanelProps {
  sessionId: string; sessionTitle: string; initialState?: Record<string, unknown>; context?: Record<string, unknown>;
  defaults?: PyniaDefaults;
  onInsert?: (code: string, language: "sql" | "python") => void; onState?: (state: PyniaState) => void; focusSignal?: number;
}
export function PyniaPanel({ sessionId, sessionTitle, initialState, context, defaults, onInsert, onState, focusSignal }: PyniaPanelProps) {
  useLocale();
  const snapshot = useSyncExternalStore(pynia.subscribe, pynia.getSnapshot), state = snapshot.sessions[sessionId];
  const [drafts, setDrafts] = useState<Record<string, string>>({}), [attachmentsBySession, setAttachments] = useState<Record<string, PyniaAttachment[]>>({});
  const [settings, setSettings] = useState(false), [clear, setClear] = useState(false), [pending, setPending] = useState(false), [error, setError] = useState(""), [messageCount, setMessageCount] = useState(40);
  const composer = useRef<HTMLTextAreaElement>(null), messages = useRef<HTMLDivElement>(null), nearBottom = useRef(true), changeCallback = useRef(onState); changeCallback.current = onState;
  const draft = drafts[sessionId] ?? "", attachments = attachmentsBySession[sessionId] ?? [];
  useEffect(() => { void pynia.catalog(); }, []);
  useEffect(() => { setError(""); setMessageCount(40); void pynia.attach(sessionId, initialState, defaults).catch((failure) => setError(errorText(failure))); }, [sessionId, defaults]);
  useEffect(() => { if (state && !state.busy) changeCallback.current?.(state); }, [state]);
  useEffect(() => { if (focusSignal != null) composer.current?.focus(); }, [focusSignal]);
  useEffect(() => { if (nearBottom.current && messages.current) messages.current.scrollTop = messages.current.scrollHeight; }, [state?.messages, state?.thinking, state?.tools]);
  async function action(task: () => Promise<unknown>) { setPending(true); setError(""); try { await task(); } catch (failure) { setError(errorText(failure)); } finally { setPending(false); } }
  async function send() {
    if (!state?.agent_id || state.busy || (!draft.trim() && !attachments.length)) return;
    const text = draft, items = attachments, id = sessionId;
    await action(async () => {
      await pynia.request("pynia.prompt", id, { text, attachments: items, context });
      setDrafts((previous) => ({ ...previous, [id]: "" })); setAttachments((previous) => ({ ...previous, [id]: [] }));
    });
    composer.current?.focus();
  }
  async function files() {
    if (!isDesktop()) throw new Error(t("Seleção de anexos está disponível no desktop."));
    const paths = await open({ multiple: true, filters: [{ name: "Anexos", extensions: ["png", "jpg", "jpeg", "gif", "webp", "bmp", "sql", "py", "txt", "csv", "json", "md", "log", "xml", "html", "tsv", "yaml", "yml"] }] });
    if (!paths) return;
    const result = await runtime.request<{ attachments: PyniaAttachment[] } | PyniaAttachment[]>("pynia.attach", { paths: typeof paths === "string" ? [paths] : paths });
    setAttachments((previous) => ({ ...previous, [sessionId]: [...(previous[sessionId] ?? []), ...(Array.isArray(result) ? result : result.attachments)].slice(0, 4) }));
  }
  async function clipboard(event: React.ClipboardEvent) {
    const files = Array.from(event.clipboardData.files);
    if (!files.length) return;
    event.preventDefault();
    try { const entries = await Promise.all(files.slice(0, 4 - attachments.length).map(normalizePastedAttachment)); setAttachments((previous) => ({ ...previous, [sessionId]: [...(previous[sessionId] ?? []), ...entries].slice(0, 4) })); }
    catch (failure) { setError(errorText(failure)); }
  }
  const activeAgent = snapshot.agents.find((agent) => agent.id === state?.agent_id);
  const advertisedDefaults = advertisedPyniaDefaults(defaults, state);
  return <section className="pynia-panel" aria-label={t("Pynia")}><header className="pynia-header"><AgentIcon agentId={state?.agent_id} size={17} /><strong>{activeAgent?.label ?? t("Pynia")}</strong><small title={sessionTitle}>{sessionTitle}</small><button className="icon-button" title={t("Novo chat desta aba")} aria-label={t("Novo chat desta aba")} disabled={state?.busy || pending} onClick={() => setClear(true)}><Trash2 size={14} /></button><button className="icon-button" title={t("Agentes e configuração")} aria-label={t("Agentes e configuração")} onClick={() => setSettings(true)}><Settings2 size={14} /></button></header>
    {(error || state?.error || snapshot.error) && <p className="pynia-error" role="alert">{t(error || state?.error || snapshot.error || "")}</p>}
    {!state?.agent_id ? <div className="pynia-picker"><p>{t("Escolha o agente para o chat desta aba.")}</p><div>{snapshot.agents.map((agent) => <button key={agent.id} disabled={pending || ["not_installed", "missing_runtime"].includes(agent.status)} onClick={() => void action(() => pynia.request("pynia.select_agent", sessionId, { agent_id: agent.id }, defaults))}><AgentIcon agentId={agent.id} size={23} /><strong>{agent.label}{defaults?.default_agent_id === agent.id && <Check size={12} aria-label={t("Padrão")} />}</strong><small>{agent.status === "ready" ? t("Disponível") : agent.status === "not_authenticated" ? t("Requer login") : agent.status === "not_installed" ? t("Não instalado") : t("Runtime não encontrado")}</small></button>)}</div><button className="secondary-button" onClick={() => setSettings(true)}>{t("Configurar agentes")}</button></div> : <div className="pynia-messages" ref={messages} onScroll={(event) => { nearBottom.current = event.currentTarget.scrollHeight - event.currentTarget.scrollTop - event.currentTarget.clientHeight < 60; }}>
      {state.messages.length > messageCount && <button className="pynia-history" onClick={() => setMessageCount((count) => count + 40)}>{t("Mostrar mensagens anteriores (")}{state.messages.length - messageCount})</button>}
      {state.messages.slice(-messageCount).map((message, index) => <ChatMessage key={`${state.messages.length - Math.min(state.messages.length, messageCount) + index}-${message.role}`} message={message} onInsert={onInsert} />)}
      {!state.messages.length && <div className="pynia-empty"><AgentIcon agentId={state.agent_id} size={30} /><p>{t("Peça ajuda com SQL, Python, dados ou blocos desta análise.")}</p><small>{t("O agente recebe o contexto da aba e usa as ferramentas do DataPyn.")}</small></div>}
      {(state.thinking || state.tools?.length) && <Activity thinking={state.thinking} tools={state.tools} />}{state.busy && <p className="pynia-working"><LoaderCircle size={13} className="spin" />{t("Pynia está trabalhando…")}</p>}
    </div>}
    {(state?.permissions ?? []).map((permission) => <PermissionCard key={permission.request_id} permission={permission} pending={pending} onAnswer={(params) => void action(() => pynia.request("pynia.answer_permission", sessionId, { request_id: permission.request_id, ...params }))} />)}
    <div className="pynia-composer">{attachments.length > 0 && <div className="pynia-attachments">{attachments.map((attachment, index) => <div key={`${attachment.name}-${index}`}>{attachment.kind === "image" && attachment.data && <img alt={attachment.name} src={`data:${attachment.mime};base64,${attachment.data}`} />}<span>{attachment.name}</span><button aria-label={t("Remover {name}",{name:attachment.name})} onClick={() => setAttachments((previous) => ({ ...previous, [sessionId]: attachments.filter((_, itemIndex) => itemIndex !== index) }))}><X size={12} /></button></div>)}</div>}
      <textarea ref={composer} value={draft} disabled={!state?.agent_id} aria-label={t("Mensagem para Pynia")} placeholder={state?.agent_id ? t("Pergunte à Pynia…") : t("Escolha um agente para começar")} onChange={(event) => setDrafts((previous) => ({ ...previous, [sessionId]: event.target.value }))} onPaste={(event) => void clipboard(event)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!pending) void send(); } }} />
      <div className="pynia-composer-controls"><button className="icon-button" aria-label={t("Anexar arquivo")} title={t("Anexar arquivo (até 4 anexos de 4 MB)")} disabled={pending || attachments.length >= 4 || !state?.agent_id} onClick={() => void action(files)}><Paperclip size={15} /></button>{state?.selectors?.model && <ConfigSelector selector={state.selectors.model} preferred={advertisedDefaults.model} kind="model" disabled={pending || state.busy} onChange={(value) => void action(() => pynia.request("pynia.config", sessionId, { config_id: state.selectors!.model!.id, kind: "model", value }))} />}{state?.selectors?.reasoning && <ConfigSelector selector={state.selectors.reasoning} preferred={advertisedDefaults.reasoning} kind="reasoning" disabled={pending || state.busy} onChange={(value) => void action(() => pynia.request("pynia.config", sessionId, { config_id: state.selectors!.reasoning!.id, kind: "reasoning", value }))} />}<span />{state?.busy ? <button className="pynia-send" title={t("Cancelar resposta")} aria-label={t("Cancelar resposta")} onClick={() => void action(() => pynia.request("pynia.cancel", sessionId))}><Square size={14} /></button> : <button className="pynia-send" title={t("Enviar mensagem")} aria-label={t("Enviar mensagem")} disabled={pending || !state?.agent_id || (!draft.trim() && !attachments.length)} onClick={() => void send()}>{pending ? <LoaderCircle size={14} className="spin" /> : <Send size={14} />}</button>}</div>
    </div>
    {settings && <AgentSettings sessionId={sessionId} agents={snapshot.agents} state={state} current={state?.agent_id} locked={state?.locked} onClose={() => setSettings(false)} onRefresh={() => void pynia.catalog()} onSelect={(agentId) => void action(async () => { await pynia.request("pynia.select_agent", sessionId, { agent_id: agentId }, defaults); setSettings(false); })} />}
    {clear && <Modal title={t("Novo chat da Pynia")} onClose={() => setClear(false)}><p className="catalog-modal-copy">{t("Limpar o histórico deste chat e escolher outro agente? Os blocos da análise serão mantidos.")}</p><footer className="modal-footer"><button className="secondary-button" onClick={() => setClear(false)}>{t("Cancelar")}</button><button className="primary-button" onClick={() => void action(async () => { await pynia.request("pynia.clear", sessionId, {}, defaults); setClear(false); })}>{t("Novo chat")}</button></footer></Modal>}
  </section>;
}

const ChatMessage = memo(function ChatMessage({ message, onInsert }: { message: PyniaMessage; onInsert?: (code: string, language: "sql" | "python") => void }) {
  useLocale();
  const content = useMemo(() => DOMPurify.sanitize(marked.parse(message.content ?? "", { gfm: true, breaks: true }), { USE_PROFILES: { html: true }, FORBID_TAGS: ["iframe", "style", "form", "input", "button", "video", "audio"], ADD_ATTR: ["target"], ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|[#/])/i }), [message.content]);
  const code = useMemo(() => [...(message.content ?? "").matchAll(/```(sql|python|py)?\s*\n([\s\S]*?)```/gi)].map((match) => ({ language: match[1]?.toLowerCase() === "sql" ? "sql" as const : "python" as const, code: match[2].replace(/\n$/, "") })), [message.content]);
  return <article className={`pynia-message ${message.role}`}><div className="pynia-message-role">{message.role === "user" ? t("Você") : message.role === "assistant" ? t("Pynia") : message.role}</div><div className="pynia-markdown" dangerouslySetInnerHTML={{ __html: content }} onClick={(event) => { const link = (event.target as HTMLElement).closest("a"); if (link) { event.preventDefault(); if (/^https?:/i.test(link.href)) void openUrl(link.href).catch(() => navigator.clipboard.writeText(link.href)); } }} />{message.attachments?.length ? <div className="pynia-attachments saved">{message.attachments.map((attachment, index) => <span key={index}>{attachment.name}</span>)}</div> : null}{code.length > 0 && <div className="pynia-code-actions">{code.map((item, index) => <div key={index}><span>{item.language.toUpperCase()} {code.length > 1 ? index + 1 : ""}</span><button title={t("Copiar código")} onClick={() => void navigator.clipboard.writeText(item.code)}><Copy size={12} />{t("Copiar")}</button>{onInsert && <button title={t("Criar bloco com este código")} onClick={() => onInsert(item.code, item.language)}><Code2 size={12} />{t("Novo bloco")}</button>}</div>)}</div>}{message.activity && <Activity thinking={message.activity.thinking} tools={message.activity.tools} />}</article>;
});

function Activity({ thinking, tools }: { thinking?: string; tools?: Array<{ id: string; title?: string; status?: string; error?: string }> }) {
  useLocale();
  return <details className="pynia-activity"><summary>{t("Atividade")}{tools?.length ? t(" · {count} ferramentas",{count:tools.length}) : ""}</summary>{thinking && <pre>{thinking}</pre>}{tools?.map((tool) => <div key={tool.id} className={`pynia-tool ${tool.status}`}>{["completed", "success", "done"].includes(tool.status ?? "") ? <Check size={12} /> : ["running", "pending", "in_progress"].includes(tool.status ?? "") ? <LoaderCircle size={12} className="spin" /> : <Code2 size={12} />}<span>{tool.title || tool.id}</span>{tool.error && <small>{tool.error}</small>}</div>)}</details>;
}
function ConfigSelector({ selector, preferred, kind, disabled, onChange }: { selector: PyniaSelector; preferred?: string; kind: string; disabled: boolean; onChange: (value: string) => void }) {
  useLocale();
  if (selector.hidden) return null;
  return <label className="pynia-config">{kind === "model" ? t("LLM") : t("Raciocínio")}<select aria-label={kind === "model" ? t("Modelo do agente") : t("Nível de raciocínio")} disabled={disabled || selector.loading} value={selector.current} onChange={(event) => onChange(event.target.value)}>{selector.loading ? <option>{t("Carregando…")}</option> : selector.values.map((value) => <option key={value.value} value={value.value} title={value.description}>{value.name}{value.value === preferred ? ` · ${t("Padrão")}` : ""}</option>)}</select></label>;
}
function PermissionCard({ permission, pending, onAnswer }: { permission: PyniaPermission; pending: boolean; onAnswer: (params: Record<string, unknown>) => void }) {
  useLocale();
  const params = permission.params, tool = params.toolCall && typeof params.toolCall === "object" ? params.toolCall as Record<string, unknown> : params;
  const options = Array.isArray(params.options) ? params.options as Array<{ optionId?: string; id?: string; name?: string; kind?: string }> : [];
  const questions = Array.isArray(params.questions) ? params.questions as Array<{ id?: string; question?: string; header?: string; options?: Array<{ label?: string; value?: string }> }> : [];
  const [answers, setAnswers] = useState<Record<string, string>>({});
  return <section className="pynia-permission" aria-label={t("Permissão solicitada pelo agente")}><strong>{String(tool.title ?? params.title ?? t("O agente precisa de uma resposta"))}</strong>{tool.rawInput != null && <pre>{typeof tool.rawInput === "string" ? tool.rawInput : JSON.stringify(tool.rawInput, null, 2)}</pre>}{questions.map((question, index) => <label key={question.id ?? index}>{question.question || question.header}<input value={answers[question.id ?? String(index)] ?? ""} list={`pynia-question-${permission.request_id}-${index}`} onChange={(event) => setAnswers((previous) => ({ ...previous, [question.id ?? String(index)]: event.target.value }))} /><datalist id={`pynia-question-${permission.request_id}-${index}`}>{question.options?.map((option, optionIndex) => <option key={optionIndex} value={option.value ?? option.label} />)}</datalist></label>)}<div>{questions.length ? <button disabled={pending} onClick={() => onAnswer({ answers })}>{t("Enviar respostas")}</button> : options.length ? options.map((option, index) => <button key={option.optionId ?? option.id ?? index} disabled={pending} onClick={() => onAnswer({ option_id: option.optionId ?? option.id })}>{option.name || option.kind || option.optionId || option.id}</button>) : <><button disabled={pending} onClick={() => onAnswer({ option_id: "reject-once" })}>{t("Recusar")}</button><button disabled={pending} onClick={() => onAnswer({ option_id: "allow-once" })}>{t("Permitir uma vez")}</button></>}</div></section>;
}
function AgentSettings({ sessionId, agents, state, current, locked, onClose, onRefresh, onSelect }: { sessionId: string; agents: PyniaAgent[]; state?: PyniaState; current?: string | null; locked?: boolean; onClose: () => void; onRefresh: () => void; onSelect: (id: string) => void }) {
  useLocale();
  const [message, setMessage] = useState("");
  const snapshot = useSyncExternalStore(pynia.subscribe, pynia.getSnapshot), [installing, setInstalling] = useState<string>();
  const authMethods = Array.isArray(state?.auth_methods) ? state.auth_methods as Array<{ id: string; name?: string; description?: string }> : [];
  async function install(id: string) { setInstalling(id); try { await runtime.request("pynia.install", { agent_id: id }); } catch (error) { setMessage(errorText(error)); setInstalling(undefined); } }
  useEffect(() => { if (installing && snapshot.installations[installing]?.running === false) setInstalling(undefined); }, [installing, snapshot.installations]);
  async function copy(text: string) { try { await navigator.clipboard.writeText(text); setMessage(t("Copiado para a área de transferência.")); } catch (error) { setMessage(errorText(error)); } }
  async function docs(url: string) { if (!/^https?:\/\//i.test(url)) return; try { await openUrl(url); } catch (error) { setMessage(errorText(error)); } }
  return <Modal title={t("Agentes Pynia")} className="pynia-agent-settings" onClose={onClose}><p className="catalog-modal-copy">{t("Use a instalação e o login do agente escolhido. O agente fica associado à conversa desta aba após o primeiro envio.")}</p><div className="pynia-agent-list">{agents.map((agent) => { const installation = snapshot.installations[agent.id]; return <section key={agent.id}><header><AgentIcon agentId={agent.id} size={18} /><strong>{agent.label}</strong><small>{agent.status}</small></header>{agent.detail && <p>{agent.detail}</p>}<div>{agent.install_command && <><button className="secondary-button" disabled={!!installing || installation?.running} onClick={() => void install(agent.id)}>{installation?.running ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />}{installation?.running ? t("Instalando…") : t("Instalar / atualizar")}</button><button className="secondary-button" onClick={() => void copy(agent.install_command!)}><Copy size={13} />{t("Copiar comando")}</button></>}{agent.login_command?.length ? <button className="secondary-button" onClick={() => void copy(agent.login_command!.join(" "))}>{t("Copiar comando de login")}</button> : null}{agent.docs_url && <button className="secondary-button" onClick={() => void docs(agent.docs_url!)}>{t("Abrir documentação")}</button>}<button className="primary-button" disabled={locked && current !== agent.id || ["not_installed", "missing_runtime"].includes(agent.status)} onClick={() => onSelect(agent.id)}>{current === agent.id ? t("Agente atual") : t("Usar agente")}</button>{current === agent.id && authMethods.map((method) => <button className="secondary-button" key={method.id} title={method.description} onClick={() => void pynia.request("pynia.authenticate", sessionId, { method_id: method.id }).catch((error) => setMessage(errorText(error)))}>{method.name || t("Autenticar")}</button>)}</div>{installation?.output && <pre className="pynia-install-output">{installation.output}</pre>}{installation?.error && <p className="pynia-error">{installation.error}</p>}{installation?.success && <p className="package-success">{t("Instalação concluída.")}</p>}</section>; })}</div>{message && <p className="catalog-modal-copy" role="status">{message}</p>}<footer className="modal-footer"><button className="secondary-button" onClick={onRefresh}><RefreshCw size={13} />{t("Verificar instalações")}</button><button className="primary-button" onClick={onClose}>{t("Fechar")}</button></footer></Modal>;
}
