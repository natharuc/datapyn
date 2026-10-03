import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { open, save } from "@tauri-apps/plugin-dialog";
import { Activity, ArrowDown, ArrowUp, Braces, Check, ChevronDown, ChevronRight, Circle, Code2, Copy, Database, FileCode2, FolderOpen, GripVertical, Keyboard, Layers3, LoaderCircle, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Play, Plus, RefreshCw, Save, Settings2, Square, Table2, Terminal, Trash2, Variable, X } from "lucide-react";
import logo from "./assets/datapyn-logo.svg";
import { errorText, isDesktop, runtime } from "./runtime";
import { WorkspaceController, encodeDocument, type Block, type SessionDocument, type WorkspaceStorage } from "./workspace";
import { MonacoBlock, disposeModel, focusEditor, insertInEditor, selectedCode, setCompletionContext } from "./MonacoBlock";
import { ResultGrid } from "./ResultGrid";
import { ConnectionDialog } from "./ConnectionDialog";
import { DEFAULT_SHORTCUTS, commandForEvent, shortcutConflicts, type Command } from "./shortcuts";

let storage: WorkspaceStorage | undefined;
try { storage = localStorage; } catch { /* Desktop still supports explicit save. */ }
export const workspace = new WorkspaceController(runtime, storage);
const reportMessage = (message: string) => workspace.message(message);
const statusLabel = { idle: "", queued: "Na fila", running: "Executando", cancelling: "Cancelando", succeeded: "Concluído", failed: "Erro", cancelled: "Cancelado" };
const commandLabels: Record<Command, string> = { run: "Executar bloco", runAdvance: "Executar e avançar", runAll: "Executar todos", addBlock: "Novo bloco", newSession: "Nova sessão", closeSession: "Fechar sessão", save: "Salvar .dpw", open: "Abrir .dpw", cancel: "Cancelar execução", settings: "Atalhos", copyHeaders: "Copiar com cabeçalhos", clearResults: "Limpar resultados" };
interface SchemaState {
  connection: NonNullable<SessionDocument["connection"]>; request: number;
  data?: Record<string, unknown>; loading: boolean; error: string;
}

function IconButton({ title, children, onClick, disabled = false, className = "" }: { title: string; children: React.ReactNode; onClick?: () => void; disabled?: boolean; className?: string }) {
  return <button type="button" className={`icon-button ${className}`} title={title} aria-label={title} onClick={onClick} disabled={disabled}>{children}</button>;
}

export function App() {
  const state = useSyncExternalStore(workspace.subscribe, workspace.getSnapshot);
  const session = state.sessions.find((item) => item.id === state.activeId)!;
  const [leftVisible, setLeftVisible] = useState(true), [rightVisible, setRightVisible] = useState(true);
  const [connectionDialog, setConnectionDialog] = useState(false), [settingsDialog, setSettingsDialog] = useState(false);
  const [closingId, setClosingId] = useState<string>(), [editingTitle, setEditingTitle] = useState<string>();
  const [titleDraft, setTitleDraft] = useState("");
  const [panel, setPanel] = useState<"results" | "output">("results"), [resultHeight, setResultHeight] = useState(310);
  const [activeResult, setActiveResult] = useState<Record<string, string>>({}), [copySignal, setCopySignal] = useState(0);
  const [shortcuts, setShortcuts] = useState<Record<Command, string>>(() => {
    try { return { ...DEFAULT_SHORTCUTS, ...JSON.parse(localStorage.getItem("datapyn.desktop.shortcuts.v1") ?? "{}") }; } catch { return DEFAULT_SHORTCUTS; }
  });
  const [schemaBySession, setSchemaBySession] = useState<Record<string, SchemaState>>({});
  const schemaRequest = useRef(0);
  const [schemaFilter, setSchemaFilter] = useState("");
  const codeArea = useRef<HTMLDivElement>(null);
  const activeSessionRef = useRef(session); activeSessionRef.current = session;

  useEffect(() => { void workspace.initialize(); const persist = () => workspace.persist(); window.addEventListener("beforeunload", persist); return () => window.removeEventListener("beforeunload", persist); }, []);
  const run = useCallback((task: Promise<unknown>) => { void task.catch((failure) => reportMessage(errorText(failure))); }, []);
  const runCurrent = useCallback((advance = false) => {
    const current = workspace.session(); if (!current) return;
    const id = current.focusedBlockId;
    const task = workspace.runBlock(current.id, id, advance ? undefined : selectedCode(id), advance);
    run(task.then(() => { if (advance) requestAnimationFrame(() => focusEditor(workspace.session(current.id)?.focusedBlockId ?? id)); }));
  }, [run]);
  const addBlock = useCallback((language?: "sql" | "python") => {
    const current = workspace.session(); if (!current) return;
    const focused = current.blocks.find((block) => block.id === current.focusedBlockId);
    const block = workspace.addBlock(current.id, language ?? focused?.language ?? "sql", "", current.focusedBlockId);
    requestAnimationFrame(() => { document.querySelector(`[data-block-id="${block.id}"]`)?.scrollIntoView({ block: "nearest" }); focusEditor(block.id); });
  }, []);
  const refreshSchema = useCallback(async (sessionId = workspace.getSnapshot().activeId) => {
    const connection = workspace.session(sessionId)?.connection;
    if (!connection) return;
    const request = ++schemaRequest.current;
    setSchemaBySession((previous) => ({ ...previous, [sessionId]: { connection, request, loading: true, error: "",
      data: previous[sessionId]?.connection === connection ? previous[sessionId].data : undefined } }));
    const update = (patch: Partial<SchemaState>) => setSchemaBySession((previous) => {
      const current = previous[sessionId];
      if (current?.request !== request || workspace.session(sessionId)?.connection !== connection) return previous;
      return { ...previous, [sessionId]: { ...current, ...patch } };
    });
    try { update({ data: await workspace.schema(sessionId), loading: false, error: "" }); }
    catch (failure) { update({ loading: false, error: errorText(failure) }); }
  }, []);

  const openDocument = useCallback(async () => {
    if (!isDesktop()) throw new Error("Abrir arquivos está disponível no aplicativo desktop.");
    const path = await open({ multiple: false, filters: [{ name: "DataPyn Workspace", extensions: ["dpw"] }] });
    if (typeof path !== "string") return;
    const document = await runtime.request<unknown>("workspace.read", { path });
    workspace.importDocument(document, path.split(/[\\/]/).at(-1) ?? "Análise", path);
  }, []);
  const saveDocument = useCallback(async (saveAs = false, sessionId?: string) => {
    const current = workspace.session(sessionId); if (!current) return;
    if (!isDesktop()) throw new Error("Salvar arquivos está disponível no aplicativo desktop. Seu rascunho permanece neste navegador.");
    const path = !saveAs && current.filePath ? current.filePath : await save({ defaultPath: `${current.title.replace(/\.dpw$/i, "")}.dpw`, filters: [{ name: "DataPyn Workspace", extensions: ["dpw"] }] });
    if (!path) return;
    const document = encodeDocument(current);
    await runtime.request("workspace.write", { path, document });
    workspace.saved(current.id, path, document);
  }, []);
  const closeSession = useCallback(async (id: string) => {
    const current = workspace.session(id); if (!current) return;
    if (current.busy) throw new Error("Cancele a execução antes de fechar esta aba.");
    if (current.modified) { setClosingId(id); return; }
    await workspace.closeSession(id); current.blocks.forEach((block) => disposeModel(block.id));
  }, []);
  const closeConfirmed = useCallback(async (shouldSave: boolean) => {
    if (!closingId) return;
    const current = workspace.session(closingId); if (!current) return;
    if (shouldSave) { await saveDocument(false, closingId); if (workspace.session(closingId)?.modified) return; }
    await workspace.closeSession(closingId); current.blocks.forEach((block) => disposeModel(block.id)); setClosingId(undefined);
  }, [closingId, saveDocument]);

  const commands = useRef<(command: Command) => void>(() => {});
  commands.current = (command) => {
    const current = workspace.session(); if (!current) return;
    switch (command) {
      case "run": runCurrent(); break;
      case "runAdvance": runCurrent(true); break;
      case "runAll": run(workspace.runAll(current.id)); break;
      case "addBlock": addBlock(); break;
      case "newSession": workspace.createSession(); break;
      case "closeSession": run(closeSession(current.id)); break;
      case "save": run(saveDocument()); break;
      case "open": run(openDocument()); break;
      case "cancel": if (current.busy) run(workspace.cancel(current.id)); break;
      case "settings": setSettingsDialog(true); break;
      case "copyHeaders": if (panel === "results") setCopySignal((value) => value + 1); break;
      case "clearResults": workspace.clearResults(current.id); break;
    }
  };
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if (connectionDialog || settingsDialog || closingId) {
        if (event.key === "Escape") { event.preventDefault(); setSettingsDialog(false); if (!connectionDialog) setClosingId(undefined); }
        return;
      }
      if (event.key === "Escape") {
        // Keep Escape available to Monaco's completion/find widgets.
        if (document.activeElement?.closest(".monaco-editor") || !activeSessionRef.current.busy) return;
      }
      const command = commandForEvent(event.repeat ? { key: event.key, ctrlKey: event.ctrlKey, metaKey: event.metaKey, altKey: event.altKey, shiftKey: event.shiftKey, repeat: false } : event, shortcuts); if (!command) return;
      event.preventDefault(); event.stopPropagation(); if (!event.repeat) commands.current(command);
    };
    window.addEventListener("keydown", handle, true); return () => window.removeEventListener("keydown", handle, true);
  }, [shortcuts, connectionDialog, settingsDialog, closingId]);
  useEffect(() => { if (session.blocks.some((block) => block.status === "failed")) setPanel("output"); }, [session.blocks]);
  useEffect(() => { if (session.results.length) setPanel("results"); }, [session.results]);
  useEffect(() => {
    setSchemaBySession((previous) => {
      const connections = new Map(state.sessions.map((item) => [item.id, item.connection]));
      const entries = Object.entries(previous).filter(([id, item]) => connections.get(id) === item.connection);
      return entries.length === Object.keys(previous).length ? previous : Object.fromEntries(entries);
    });
  }, [state.sessions]);
  useEffect(() => {
    const schema = schemaBySession[session.id]?.connection === session.connection ? schemaBySession[session.id]?.data : undefined;
    const tables = Array.isArray(schema?.tables) ? schema.tables.map((raw) => { const table = typeof raw === "string" ? { name: raw } : raw as Record<string, unknown>; return `${table.schema ? `${table.schema}.` : ""}${table.name ?? table.table_name ?? ""}`; }) : [];
    session.blocks.forEach((block) => setCompletionContext(block.id, { variables: session.variables, tables }));
  }, [session.id, session.blocks, session.variables, schemaBySession]);
  useEffect(() => { if (session.images.length) { setPanel("results"); setActiveResult((previous) => ({ ...previous, [session.id]: "__images__" })); } }, [session.images, session.id]);

  const result = activeResult[session.id] === "__images__" && session.images.length ? undefined : session.results.find((item) => item.result_id === activeResult[session.id]) ?? session.results.at(-1);
  const schemaState = schemaBySession[session.id]?.connection === session.connection ? schemaBySession[session.id] : undefined;
  const schema = schemaState?.data, schemaLoading = schemaState?.loading ?? false, schemaError = schemaState?.error ?? "";
  const focusedBlock = session.blocks.find((block) => block.id === session.focusedBlockId);
  function resizeResults(event: React.PointerEvent) {
    event.preventDefault(); const initialY = event.clientY, initialHeight = resultHeight;
    const move = (pointer: PointerEvent) => setResultHeight(Math.max(170, Math.min(window.innerHeight - 290, initialHeight + initialY - pointer.clientY)));
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up, { once: true });
  }
  const runDisabled = session.busy || state.runtimeStatus !== "ready" || Boolean(session.runtimeError);
  return <div className="app-shell">
    <header className="app-header">
      <div className="brand"><img src={logo} alt="" /><span>DataPyn</span><span className="brand-divider" /><span className="brand-caption">SQL + Python</span></div>
      <nav className="app-menu" aria-label="Arquivos e configurações">
        <button onClick={() => run(openDocument())}>Abrir <kbd>Ctrl O</kbd></button>
        <button onClick={() => run(saveDocument())}>Salvar <kbd>Ctrl S</kbd></button>
        <button onClick={() => run(saveDocument(true))}>Salvar como</button>
        <button onClick={() => setSettingsDialog(true)}>Atalhos</button>
      </nav>
      <div className={`runtime-chip ${state.runtimeStatus}`}><span className="connection-dot" />{state.runtimeStatus === "ready" ? `Python ${state.runtimeInfo?.python_version}` : state.runtimeStatus === "connecting" ? "Iniciando Python" : "Runtime indisponível"}</div>
    </header>
    <div className="session-bar" role="tablist" aria-label="Sessões">
      {state.sessions.map((item) => <div key={item.id} className={`session-tab ${session.id === item.id ? "active" : ""}`}>
        {editingTitle === item.id ? <input autoFocus className="tab-title-input" value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)} onBlur={() => { workspace.renameSession(item.id, titleDraft); setEditingTitle(undefined); }} onKeyDown={(event) => { if (event.key === "Enter") { workspace.renameSession(item.id, titleDraft); setEditingTitle(undefined); } if (event.key === "Escape") setEditingTitle(undefined); }} /> : <button role="tab" aria-selected={session.id === item.id} onClick={() => workspace.activate(item.id)} onDoubleClick={() => { setEditingTitle(item.id); setTitleDraft(item.title); }}>
          {item.busy ? <LoaderCircle size={13} className="spin" /> : <FileCode2 size={13} />}<span>{item.title}{item.modified ? " •" : ""}</span></button>}
        <IconButton title={`Fechar ${item.title}`} onClick={() => run(closeSession(item.id))}><X size={12} /></IconButton>
      </div>)}
      <IconButton title="Nova sessão (Ctrl+N / Ctrl+T)" onClick={() => workspace.createSession()} className="new-session"><Plus size={17} /></IconButton>
    </div>
    <div className="workspace-toolbar">
      <IconButton title={leftVisible ? "Ocultar conexões" : "Mostrar conexões"} onClick={() => setLeftVisible(!leftVisible)}>{leftVisible ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}</IconButton>
      <button className="connection-button" onClick={() => setConnectionDialog(true)}><Database size={14} /><span>{session.connection?.name || session.connection?.database || "Conectar ao banco"}</span><ChevronDown size={12} /></button>
      {session.connection?.schema && <span className="context-chip">{session.connection.schema}</span>}
      <span className="toolbar-divider" />
      <button className="primary-button run-button" disabled={runDisabled} onClick={() => runCurrent()} title="Executar bloco ou seleção (F5 / Ctrl+Enter)"><Play size={14} fill="currentColor" />Executar <kbd>F5</kbd></button>
      <button className="text-button" disabled={runDisabled} onClick={() => run(workspace.runAll(session.id))} title="Executar todos os blocos ativos (Ctrl+F5)"><Layers3 size={15} /> Executar todos</button>
      <button className="text-button stop-button" disabled={!session.busy} onClick={() => run(workspace.cancel(session.id))} title="Interromper esta sessão e descartar seu namespace"><Square size={13} fill="currentColor" /> Cancelar</button>
      <span className="toolbar-spacer" />
      <span className="toolbar-hint">{session.blocks.length} blocos</span>
      <IconButton title={rightVisible ? "Ocultar variáveis" : "Mostrar variáveis"} onClick={() => setRightVisible(!rightVisible)}>{rightVisible ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}</IconButton>
    </div>
    {state.runtimeStatus === "unavailable" && <div className="runtime-banner"><Activity size={14} /><span>{isDesktop() ? state.message : "Prévia da interface. O runtime Python está disponível no aplicativo desktop."}</span>{isDesktop() && <button className="text-button" onClick={() => run(workspace.retryRuntime())}><RefreshCw size={12} /> Reconectar</button>}</div>}
    <main className="workbench">
      {leftVisible && <aside className="explorer-panel">
        <div className="panel-heading"><span>CONEXÃO</span><IconButton title="Configurar conexão" onClick={() => setConnectionDialog(true)}><Plus size={14} /></IconButton></div>
        <button className={`saved-connection ${session.connection ? "connected" : ""}`} onClick={() => setConnectionDialog(true)}><Database size={19} /><span><strong>{session.connection?.name || session.connection?.db_type || "Nenhuma conexão"}</strong><small>{session.connection?.database || "Escolha um banco para consultar"}</small></span>{session.connection && <span className="connection-dot" />}</button>
        <div className="panel-heading explorer-heading"><span>OBJECT EXPLORER</span><IconButton title="Atualizar schema" disabled={!session.connection || schemaLoading} onClick={() => void refreshSchema()}><RefreshCw size={13} className={schemaLoading ? "spin" : ""} /></IconButton></div>
        <label className="explorer-search"><input aria-label="Buscar tabelas" placeholder="Buscar tabelas…" value={schemaFilter} onChange={(event) => setSchemaFilter(event.target.value)} /></label>
        <div className="schema-tree">
          {schemaError ? <p className="explorer-empty error-text">{schemaError}</p> : schemaLoading ? <p className="explorer-empty"><LoaderCircle size={16} className="spin" /> Buscando schema…</p> : !schema ? <div className="explorer-empty"><Table2 size={26} /><p>{session.connection ? "Carregue as tabelas desta conexão." : "O schema aparece aqui depois de conectar."}</p>{session.connection && <button className="text-button" onClick={() => void refreshSchema()}>Carregar tabelas</button>}</div> : <SchemaTree schema={schema} filter={schemaFilter} dbType={session.connection?.db_type} onInsert={(text) => insertInEditor(session.focusedBlockId, text)} onQuery={(code) => { const block = workspace.addBlock(session.id, "sql", code); requestAnimationFrame(() => focusEditor(block.id)); }} />}
        </div>
        <div className="explorer-footnote"><Database size={12} /><span>{session.connection ? "Conexão local · sessão isolada" : "6 tipos de banco suportados"}</span></div>
      </aside>}
      <section className="center-workspace">
        <div className="editor-area" ref={codeArea}>
          {session.notice && <div className="session-notice" role="status">{session.notice}</div>}
          <div className="document-heading"><span className="eyebrow">ANÁLISE</span><span className="document-title">{session.title}</span><span className="document-subtitle">Blocos independentes. Um namespace Python.</span></div>
          {session.blocks.map((block, index) => <BlockCard key={block.id} block={block} index={index} count={session.blocks.length} session={session} disabled={runDisabled}
            onRun={() => run(workspace.runBlock(session.id, block.id, selectedCode(block.id)))} />)}
          <div className="add-block-row"><button onClick={() => addBlock("sql")}><Plus size={14} /><span className="sql-color">SQL</span></button><button onClick={() => addBlock("python")}><Plus size={14} /><span className="python-color">Python</span></button><span>Novo bloco <kbd>{shortcuts.addBlock}</kbd></span></div>
        </div>
        <div className="results-resizer" onPointerDown={resizeResults} role="separator" aria-label="Redimensionar resultados" aria-orientation="horizontal" />
        <section className="results-panel" style={{ height: resultHeight }}>
          <div className="bottom-tabs"><button className={panel === "results" ? "active" : ""} onClick={() => setPanel("results")}><Table2 size={14} />Resultados {session.results.length > 0 && <span className="count-badge">{session.results.length}</span>}</button><button className={panel === "output" ? "active" : ""} onClick={() => setPanel("output")}><Terminal size={14} />Saída {session.logs.some((line) => line.stream === "stderr") && <span className="error-dot" />}</button><span className="toolbar-spacer" /><IconButton title="Limpar resultados e saída (Ctrl+Shift+L)" onClick={() => workspace.clearResults(session.id)}><Trash2 size={13} /></IconButton></div>
          {panel === "output" ? <OutputPanel session={session} /> : <>
            {(session.results.length > 1 || session.images.length > 0) && <div className="result-tabs">{session.results.map((item) => <button key={item.result_id} className={result?.result_id === item.result_id ? "active" : ""} onClick={() => setActiveResult((previous) => ({ ...previous, [session.id]: item.result_id }))}><Table2 size={12} />{item.variable_name || "Resultado"}<span>{item.row_count.toLocaleString("pt-BR")}</span></button>)}{session.images.length > 0 && <button className={!result ? "active" : ""} onClick={() => setActiveResult((previous) => ({ ...previous, [session.id]: "__images__" }))}>Gráficos Python <span>{session.images.length}</span></button>}</div>}
            {result ? <ResultGrid key={`${session.id}:${result.result_id}:${session.resultRevision}`} sessionId={session.id} result={result} transport={runtime} onMessage={reportMessage} copySignal={copySignal} /> : session.images.length ? <div className="figure-results">{session.images.map((image, index) => <img key={index} src={`data:${image.mime};base64,${image.data}`} alt={`Gráfico Python ${index + 1}`} />)}</div> : <div className="empty-results"><div className="empty-grid-icon"><Table2 size={25} /></div><strong>{session.busy ? "Executando análise…" : "Seus resultados aparecem aqui"}</strong><p>Execute um bloco SQL ou retorne um DataFrame em Python.</p><span><kbd>F5</kbd> executar bloco <span className="bullet">·</span><kbd>Ctrl F5</kbd> executar todos</span></div>}
          </>}
        </section>
      </section>
      {rightVisible && <aside className="variables-panel"><div className="panel-heading"><span>VARIÁVEIS</span><span className="count-badge">{session.variables.length}</span></div>
        <div className="namespace-heading"><Braces size={14} /><span>Namespace da sessão</span></div>
        {session.variables.length ? <div className="variable-list">{session.variables.map((variable) => <button className="variable-item" key={variable.name} title={`${variable.name}: ${variable.type}\n${variable.preview}`} onClick={() => insertInEditor(session.focusedBlockId, variable.name)}><div><Variable size={13} /><strong>{variable.name}</strong><small>{variable.type}</small></div><p>{variable.preview}</p></button>)}</div> : <div className="variables-empty"><Code2 size={23} /><p>Os resultados SQL e suas variáveis Python ficam disponíveis entre os blocos desta aba.</p><span className="namespace-example">SQL → df → Python</span></div>}
        <div className="session-summary"><div><span>Bloco focado</span><strong>{focusedBlock ? session.blocks.indexOf(focusedBlock) + 1 : "—"}</strong></div><div><span>Linguagem</span><strong className={focusedBlock?.language === "sql" ? "sql-color" : "python-color"}>{focusedBlock?.language.toUpperCase()}</strong></div><div><span>Estado</span><strong>{session.busy ? "Executando" : "Pronto"}</strong></div></div>
        <div className="keyboard-footnote"><Keyboard size={14} /><span><kbd>Shift Enter</kbd> executar e avançar</span></div>
      </aside>}
    </main>
    <footer className="statusbar"><span className={`status-runtime ${state.runtimeStatus}`}><Circle size={7} fill="currentColor" />{state.runtimeStatus === "ready" ? "Runtime conectado" : "Runtime offline"}</span><span className="status-message" role="status" title={state.message}>{state.message}</span><span className="status-file" title={session.filePath}>{session.filePath?.split(/[\\/]/).at(-1) || "Rascunho local"}</span><span className="status-language">{focusedBlock?.language.toUpperCase()}</span><IconButton title="Configurar atalhos" onClick={() => setSettingsDialog(true)}><Settings2 size={12} /></IconButton></footer>
    {connectionDialog && <ConnectionDialog initial={session.connection} onClose={() => setConnectionDialog(false)} onConnect={async (config) => { await workspace.connect(session.id, config); void refreshSchema(session.id); }} />}
    {settingsDialog && <ShortcutDialog current={shortcuts} onClose={() => setSettingsDialog(false)} onSave={(next) => { setShortcuts(next); try { localStorage.setItem("datapyn.desktop.shortcuts.v1", JSON.stringify(next)); } catch { reportMessage("Atalhos aplicados. Não foi possível persistir nesta máquina."); } setSettingsDialog(false); }} />}
    {closingId && <div className="modal-overlay"><section className="modal confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="close-title"><header className="modal-header"><Save size={18} /><div><h2 id="close-title">Salvar alterações?</h2><p>{workspace.session(closingId)?.title}</p></div></header><p className="confirm-copy">Salve a análise em um arquivo .dpw antes de fechar a aba.</p><footer className="modal-footer"><button className="secondary-button" onClick={() => setClosingId(undefined)}>Voltar</button><button className="secondary-button" onClick={() => run(closeConfirmed(false))}>Descartar</button><button className="primary-button" onClick={() => run(closeConfirmed(true))}>Salvar e fechar</button></footer></section></div>}
  </div>;
}

function BlockCard({ block, index, count, session, disabled, onRun }: { block: Block; index: number; count: number; session: SessionDocument; disabled: boolean; onRun: () => void }) {
  const [height, setHeight] = useState(typeof block.height === "number" ? Math.max(130, block.height) : block.language === "sql" ? 210 : 190);
  return <article className={`code-block ${block.language} ${session.focusedBlockId === block.id ? "focused" : ""}`} data-block-id={block.id}>
    <div className="block-header"><GripVertical className="block-grip" size={13} /><span className="block-index">{String(index + 1).padStart(2, "0")}</span><select className={`language-select ${block.language}`} aria-label={`Linguagem do bloco ${index + 1}`} value={block.language} disabled={session.busy} onChange={(event) => workspace.updateBlock(session.id, block.id, { language: event.target.value as "sql" | "python" })}><option value="sql">SQL</option><option value="python">Python</option></select>
      <input className="block-name" value={block.block_name} placeholder={block.language === "sql" ? "Nome do resultado (df)" : "Nome do bloco"} aria-label={`Nome do bloco ${index + 1}`} onChange={(event) => workspace.updateBlock(session.id, block.id, { block_name: event.target.value })} />
      <span className={`block-status ${block.status}`}>{block.status === "running" || block.status === "cancelling" ? <LoaderCircle size={12} className="spin" /> : block.status === "succeeded" ? <Check size={12} /> : block.status === "failed" ? <X size={12} /> : null}{statusLabel[block.status]}{block.duration_ms !== undefined && ["succeeded", "failed"].includes(block.status) && <span>{(block.duration_ms / 1000).toFixed(2)}s</span>}</span>
      <IconButton title={block.is_active ? "Desativar na execução de todos" : "Ativar na execução de todos"} className={block.is_active ? "block-active" : ""} disabled={session.busy} onClick={() => workspace.updateBlock(session.id, block.id, { is_active: !block.is_active })}><Circle size={10} fill={block.is_active ? "currentColor" : "none"} /></IconButton>
      <IconButton title="Mover bloco para cima" disabled={index === 0 || session.busy} onClick={() => workspace.moveBlock(session.id, block.id, -1)}><ArrowUp size={13} /></IconButton><IconButton title="Mover bloco para baixo" disabled={index === count - 1 || session.busy} onClick={() => workspace.moveBlock(session.id, block.id, 1)}><ArrowDown size={13} /></IconButton>
      <IconButton title="Duplicar bloco" onClick={() => { const copy = workspace.addBlock(session.id, block.language, block.code, block.id); workspace.updateBlock(session.id, copy.id, { block_name: block.block_name ? `${block.block_name}_copy` : "" }); }}><Copy size={12} /></IconButton>
      <IconButton title="Excluir bloco" disabled={session.busy} onClick={() => { workspace.removeBlock(session.id, block.id); disposeModel(block.id); }}><Trash2 size={12} /></IconButton>
      <button className="block-run" disabled={disabled} onClick={onRun} title="Executar bloco ou seleção"><Play size={12} fill="currentColor" /></button>
    </div>
    <MonacoBlock id={block.id} code={block.code} language={block.language} height={height} onChange={(code) => workspace.updateBlock(session.id, block.id, { code })} onFocus={() => workspace.focusBlock(session.id, block.id)} />
    {!block.code.trim() && <div className="block-placeholder" aria-hidden="true">{block.language === "sql" ? "Escreva uma consulta SQL…" : "Explore seus dados em Python…"}</div>}
    <div className="block-resizer" onPointerDown={(event) => { event.preventDefault(); const startY = event.clientY, startHeight = height; let nextHeight = height;
      const move = (pointer: PointerEvent) => { nextHeight = Math.max(130, Math.min(900, startHeight + pointer.clientY - startY)); setHeight(nextHeight); };
      const up = () => { workspace.updateBlock(session.id, block.id, { height: nextHeight }); window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
      window.addEventListener("pointermove", move); window.addEventListener("pointerup", up, { once: true }); }} />
  </article>;
}

function OutputPanel({ session }: { session: SessionDocument }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [session.logs]);
  return <div className="output-panel">{session.logs.length ? session.logs.map((line) => <div key={line.id} className={`output-entry ${line.stream}`}><span>{line.time}</span><span className="output-stream">{line.stream === "stderr" ? "ERR" : line.stream === "system" ? "SYS" : "OUT"}</span><pre>{line.text}</pre></div>) : <div className="output-empty"><Terminal size={19} /><span>Prints, mensagens e erros de execução aparecem aqui.</span></div>}<div ref={end} /></div>;
}

function SchemaTree({ schema, filter, dbType, onInsert, onQuery }: { schema: Record<string, unknown>; filter: string; dbType?: string; onInsert: (text: string) => void; onQuery: (code: string) => void }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const tables = Array.isArray(schema.tables) ? schema.tables.map((raw) => typeof raw === "string" ? { name: raw, schema: "" } : raw as Record<string, unknown>) : [];
  const matching = tables.filter((table) => `${table.schema ?? ""}.${table.name ?? table.table_name ?? ""}`.toLowerCase().includes(filter.toLowerCase()));
  const quote = (value: string) => dbType === "sqlserver" ? `[${value.replace(/]/g, "]]")}]` : dbType === "mysql" || dbType === "mariadb" || dbType === "databricks" ? `\`${value.replace(/`/g, "``")}\`` : `"${value.replace(/"/g, '""')}"`;
  if (!matching.length) return <p className="explorer-empty">{filter ? "Nenhuma tabela encontrada." : "Nenhuma tabela neste contexto."}</p>;
  return <>{matching.map((table, index) => {
    const name = String(table.name ?? table.table_name ?? ""), namespace = String(table.schema ?? ""), key = `${namespace}.${name}.${index}`;
    const qualified = namespace ? `${quote(namespace)}.${quote(name)}` : quote(name);
    const columnMap = schema.columns as Record<string, unknown[]> | undefined;
    const columns = Array.isArray(table.columns) ? table.columns : columnMap?.[`${namespace}.${name}`] ?? columnMap?.[name] ?? [];
    return <div className="schema-table" key={key}><div className="schema-table-row"><button className="schema-expand" aria-label={`Expandir ${name}`} onClick={() => setExpanded((previous) => { const next = new Set(previous); if (next.has(key)) next.delete(key); else next.add(key); return next; })}>{expanded.has(key) ? <ChevronDown size={12} /> : <ChevronRight size={12} />}</button><button className="schema-name" title={`Inserir ${qualified}`} onClick={() => onInsert(qualified)}><Table2 size={13} /><span>{namespace && <small>{namespace}.</small>}{name}</span></button><IconButton title={`Criar SELECT de ${name}`} onClick={() => onQuery(dbType === "sqlserver" ? `SELECT TOP 1000 *\nFROM ${qualified};` : `SELECT *\nFROM ${qualified}\nLIMIT 1000;`)}><Plus size={12} /></IconButton></div>
      {expanded.has(key) && <div className="schema-columns">{columns.length ? columns.map((raw, columnIndex) => { const column = typeof raw === "string" ? { name: raw } : raw as Record<string, unknown>; const columnName = String(column.name ?? column.column_name ?? ""); return <button key={`${columnName}:${columnIndex}`} onClick={() => onInsert(quote(columnName))}><span>{columnName}</span><small>{String(column.data_type ?? column.dtype ?? "")}</small></button>; }) : <p>Sem metadados de colunas neste resultado.</p>}</div>}
    </div>;
  })}</>;
}

function ShortcutDialog({ current, onSave, onClose }: { current: Record<Command, string>; onSave: (shortcuts: Record<Command, string>) => void; onClose: () => void }) {
  const [draft, setDraft] = useState(current), [error, setError] = useState("");
  return <div className="modal-overlay"><section className="modal shortcut-dialog" role="dialog" aria-modal="true" aria-labelledby="shortcuts-title"><header className="modal-header"><Keyboard size={18} /><div><h2 id="shortcuts-title">Atalhos do DataPyn</h2><p>F5 e Ctrl+T também permanecem disponíveis.</p></div><IconButton title="Fechar atalhos" onClick={onClose}><X size={16} /></IconButton></header><div className="shortcut-list">{(Object.entries(commandLabels) as [Command, string][]).map(([command, label]) => <label key={command}><span>{label}</span><input aria-label={`Atalho ${label}`} value={draft[command]} onChange={(event) => setDraft((previous) => ({ ...previous, [command]: event.target.value }))} /></label>)}</div>{error && <p role="alert" className="form-error">{error}</p>}<footer className="modal-footer"><button className="secondary-button" onClick={() => setDraft(DEFAULT_SHORTCUTS)}>Restaurar padrões</button><span className="toolbar-spacer" /><button className="primary-button" onClick={() => { const conflicts = shortcutConflicts(draft); if (conflicts.length) { setError(conflicts.join("; ")); return; } onSave(draft); }}>Salvar atalhos</button></footer></section></div>;
}
