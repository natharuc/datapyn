import { translate as t, useLocale } from "./i18n";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Braces, ChevronDown, ChevronRight, ChevronsRight, Code2, Copy, Database, FileCode2, Folder, KeyRound, LoaderCircle, RefreshCw, Search, Table2 } from "lucide-react";
import { runtime, errorText } from "./runtime";
import { ExplorerController, explorerRows, quoteIdentifier, quoteIdentifierPart,reloadExpanded, type ExplorerNode, type ExplorerContext, type ExplorerDetails } from "./explorer";
import { Modal } from "./PanelControls";
import "./explorer.css";

export interface ObjectExplorerProps {
  sessionId: string; connectionId?: string; database?: string; schema?: string; dbType?: string; connected?: boolean; refresh?: number;
  onInsert: (code: string, language?: "sql" | "python", newBlock?: boolean) => void;
  onContextChange?: (context: ExplorerContext) => Promise<void> | void;
  onError?: (message: string) => void; disabled?: boolean;
}
const objectKinds = new Set(["table", "view", "procedure", "function"]);
function NodeIcon({ node }: { node: ExplorerNode }) {
  if (["database", "catalog"].includes(node.kind)) return <Database size={14} />;
  if (node.kind === "column") return node.primary_key ? <KeyRound size={13} /> : <Braces size={13} />;
  if (node.kind === "table" || node.kind === "view") return <Table2 size={14} />;
  if (node.kind === "procedure" || node.kind === "function") return <FileCode2 size={14} />;
  return <Folder size={14} />;
}

export function ObjectExplorer({ sessionId, connectionId, database, schema, dbType = "sqlserver", connected = true, refresh = 0, onInsert, onContextChange, onError, disabled = false }: ObjectExplorerProps) {
  useLocale();
  const controller = useRef(new ExplorerController());
  const [roots, setRoots] = useState<ExplorerNode[]>([]), [children, setChildren] = useState<Record<string, ExplorerNode[]>>({}), [expanded, setExpanded] = useState(new Set<string>()), [loading, setLoading] = useState(new Set<string>());
  const [error, setError] = useState(""), [query, setQuery] = useState(""), [selected, setSelected] = useState<string>(), [menu, setMenu] = useState<ExplorerNode>();
  const [details, setDetails] = useState<{ node: ExplorerNode; data?: ExplorerDetails; error?: string }>(), [scroll, setScroll] = useState(0), [height, setHeight] = useState(400);
  const generation = useRef(0), viewport = useRef<HTMLDivElement>(null), tree = useRef<HTMLDivElement>(null);
  const load = useCallback(async (node?: ExplorerNode, force = false) => {
    const key = node?.id ?? "$root", revision = generation.current;
    setLoading((prior) => new Set([...prior, key])); setError("");
    try {
      const nodes = await controller.current.list(node, force);
      if (revision !== generation.current) return;
      if (node) setChildren((prior) => ({ ...prior, [node.id]: nodes })); else setRoots(nodes);
    } catch (failure) { if (revision === generation.current) setError(errorText(failure)); }
    finally { if (revision === generation.current) setLoading((prior) => { const next = new Set(prior); next.delete(key); return next; }); }
  }, []);
  useEffect(() => {
    previousRefresh.current=refresh;
    ++generation.current; controller.current.setScope({ session_id: sessionId, connection_id: connectionId, database, schema }); controller.current.clear();
    setRoots([]); setChildren({}); setExpanded(new Set()); setSelected(undefined); setMenu(undefined); setDetails(undefined); setLoading(new Set()); setError("");
    if (connected) void load();
    return () => { ++generation.current; };
  }, [sessionId, connectionId, database, schema, connected, load]);
  async function refreshTree(){const revision=++generation.current;setLoading(new Set(["$root"]));setError("");setMenu(undefined);setDetails(undefined);
    try{const fresh=await reloadExpanded(controller.current,expanded,()=>revision===generation.current);if(fresh){setRoots(fresh.roots);setChildren(fresh.children);setExpanded(fresh.expanded);}}
    catch(failure){if(revision===generation.current)setError(errorText(failure));}
    finally{if(revision===generation.current)setLoading(new Set());}
  }
  const previousRefresh=useRef(refresh);
  useEffect(()=>{if(previousRefresh.current!==refresh){previousRefresh.current=refresh;if(connected)void refreshTree();}},[refresh]);
  useEffect(() => { const target = viewport.current; if (!target) return; const observer = new ResizeObserver(([entry]) => setHeight(entry.contentRect.height)); observer.observe(target); return () => observer.disconnect(); }, []);
  const rows = useMemo(() => explorerRows(roots, children, expanded, query), [roots, children, expanded, query]);
  const rowHeight = 29, first = Math.max(0, Math.floor(scroll / rowHeight) - 6), end = Math.min(rows.length, Math.ceil((scroll + height) / rowHeight) + 6);
  function toggle(node: ExplorerNode) {
    if (!node.has_children||loading.has("$root")) return;
    const opening = !expanded.has(node.id);
    setExpanded((prior) => { const next = new Set(prior); if (opening) next.add(node.id); else next.delete(node.id); return next; });
    if (opening && !children[node.id]) void load(node);
  }
  const qualified = (node: ExplorerNode) => node.qualified_name || (node.schema && objectKinds.has(node.kind) ? `${node.schema}.${node.name}` : node.name);
  const quoted = (node: ExplorerNode) => node.qualified_name ? quoteIdentifier(node.qualified_name, dbType) : objectKinds.has(node.kind)&&node.schema?`${quoteIdentifierPart(node.schema,dbType)}.${quoteIdentifierPart(node.name,dbType)}`:quoteIdentifierPart(node.name, dbType);
  const insert = (node: ExplorerNode) => onInsert(quoted(node));
  async function action(task: () => Promise<unknown> | unknown) { setMenu(undefined); try { await task(); } catch (failure) { const message = errorText(failure); setError(message); onError?.(message); } }
  const nodeParams = (node: ExplorerNode) => ({ session_id: sessionId, connection_id: connectionId, database: node.database || database, schema: node.schema || schema, name: node.name, kind: node.kind });
  async function showDetails(node: ExplorerNode) {
    const revision = generation.current; setDetails({ node });
    try { const data = await runtime.request<ExplorerDetails>("explorer.details", nodeParams(node)); if (revision === generation.current) setDetails((prior) => prior?.node.id === node.id ? { node, data } : prior); }
    catch (failure) { if (revision === generation.current) setDetails((prior) => prior?.node.id === node.id ? { node, error: errorText(failure) } : prior); }
  }
  async function copy(text: string) { await navigator.clipboard.writeText(text); }
  async function selectQuery(node: ExplorerNode) { const { code } = await runtime.request<{ code: string }>("explorer.query", { ...nodeParams(node), limit: 1000 }); onInsert(code, "sql", true); }
  async function allColumns(node: ExplorerNode) {
    const info = await runtime.request<ExplorerDetails>("explorer.details", nodeParams(node)), columns = info.columns ?? [];
    const names = columns.map((column) => quoteIdentifierPart(String(column.name), dbType)).join(",\n       ");
    if (!names) throw new Error(t("Não há metadados de colunas disponíveis para este objeto."));
    onInsert(dbType === "sqlserver" ? `SELECT TOP 1000 ${names}\nFROM ${quoted(node)};` : `SELECT ${names}\nFROM ${quoted(node)}\nLIMIT 1000;`, "sql", true);
  }
  async function definition(node: ExplorerNode, drop = false) {
    const info = await runtime.request<ExplorerDetails>("explorer.details", nodeParams(node));
    if (!info.definition) throw new Error(t("O driver não disponibilizou a definição deste objeto."));
    onInsert(`${drop ? `DROP ${node.kind.toUpperCase()} ${quoted(node)};\n\n` : ""}${info.definition}`, "sql", true);
  }
  async function useContext(node: ExplorerNode) {
    const context = { database: ["database", "catalog"].includes(node.kind) ? node.name : node.database || database, schema: node.kind === "schema" ? node.name : schema };
    if (onContextChange) await onContextChange(context);
    else await runtime.request("explorer.use_database", { session_id: sessionId, connection_id: connectionId, ...context });
  }
  function keyboard(event: React.KeyboardEvent) {
    const index = rows.findIndex((row) => row.node.id === selected), node = rows[index]?.node;
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1 : Math.max(0, Math.min(rows.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)));
      setSelected(rows[next]?.node.id); if (viewport.current) { if (next * rowHeight < scroll) viewport.current.scrollTop = next * rowHeight; else if ((next + 1) * rowHeight > scroll + height) viewport.current.scrollTop = (next + 1) * rowHeight - height; }
    } else if (node && ["ArrowLeft", "ArrowRight"].includes(event.key)) { event.preventDefault(); if (expanded.has(node.id) !== (event.key === "ArrowRight")) toggle(node); }
    else if (node && event.key === "Enter") { event.preventDefault(); if (event.ctrlKey || event.metaKey) insert(node); else toggle(node); }
    else if (node && event.shiftKey && event.key === "F10") { event.preventDefault(); setMenu(node); }
  }
  return <section className="object-explorer" aria-label="Object Explorer"><div className="explorer-toolbar"><strong>Object Explorer</strong><button className="icon-button" title={t("Atualizar metadados")} aria-label={t("Atualizar metadados")} disabled={!connected || loading.has("$root")} onClick={() => void refreshTree()}><RefreshCw size={14} /></button></div>
    <div className="explorer-search"><Search size={14} /><input aria-label={t("Filtrar objetos carregados")} value={query} placeholder={t("Filtrar objetos…")} onChange={(event) => { setQuery(event.target.value); if (viewport.current) viewport.current.scrollTop = 0; }} /></div>
    {query && <p className="explorer-hint">{t("Filtro sobre os metadados carregados. Expanda os grupos para carregar outros objetos.")}</p>}{error && <p className="catalog-error" role="alert">{t(error)}</p>}
    {!connected && <p className="explorer-hint">{t("Conecte a sessão para explorar objetos do banco.")}</p>}{loading.has("$root") && <p className="explorer-hint"><LoaderCircle size={14} className="spin" /> {t("Carregando metadados…")}</p>}
    <div ref={viewport} className="explorer-viewport" onScroll={(event) => setScroll(event.currentTarget.scrollTop)}><div role="tree" ref={tree} tabIndex={0} aria-label={t("Objetos do banco de dados")} aria-activedescendant={selected ? `explorer-row-${selected}` : undefined} style={{ position: "relative", height: rows.length * rowHeight }} onKeyDown={keyboard}>
      {rows.slice(first, end).map(({ node, depth }, offset) => <div key={node.id} id={`explorer-row-${node.id}`} role="treeitem" aria-level={depth + 1} aria-selected={selected === node.id} aria-expanded={node.has_children ? expanded.has(node.id) : undefined} className={`explorer-row ${selected === node.id ? "selected" : ""} ${node.kind}`} style={{ position: "absolute", top: (first + offset) * rowHeight, height: rowHeight, paddingLeft: 7 + depth * 13 }} title={`${qualified(node)}${node.data_type ? `\n${node.data_type}` : ""}`} onClick={() => { setSelected(node.id); tree.current?.focus(); }} onDoubleClick={() => toggle(node)} onContextMenu={(event) => { event.preventDefault(); setSelected(node.id); setMenu(node); }} draggable={objectKinds.has(node.kind) || ["database", "catalog", "schema", "column"].includes(node.kind)} onDragStart={(event) => { event.dataTransfer.setData("text/plain", quoted(node)); if (["database", "catalog", "schema"].includes(node.kind)) event.dataTransfer.setData("application/x-datapyn-context", JSON.stringify({ connection_id: connectionId, database: ["database", "catalog"].includes(node.kind) ? node.name : node.database || database, schema: node.kind === "schema" ? node.name : schema })); }}>
        <button className="explorer-toggle" tabIndex={-1} title={expanded.has(node.id) ? "Recolher" : "Expandir"} onClick={(event) => { event.stopPropagation(); toggle(node); }} disabled={!node.has_children}>{loading.has(node.id) ? <LoaderCircle size={12} className="spin" /> : node.has_children ? expanded.has(node.id) ? <ChevronDown size={12} /> : <ChevronRight size={12} /> : null}</button><NodeIcon node={node} /><span>{node.name}</span>{node.data_type && <small>{node.data_type}</small>}
        {node.kind !== "category" && <button className="explorer-insert" aria-label={t("Inserir {name} no editor",{name:node.name})} title={t("Inserir no bloco em foco")} disabled={disabled} onMouseDown={(event) => event.preventDefault()} onClick={(event) => { event.stopPropagation(); insert(node); }}><ChevronsRight size={14} /></button>}
      </div>)}
    </div>{connected && !rows.length && !loading.size && !error && <p className="explorer-hint">{query ? t("Nenhum objeto carregado corresponde ao filtro.") : t("Nenhum objeto disponível neste contexto.")}</p>}</div>
    {menu && <Modal title={menu.name} className="connection-action-menu" onClose={() => setMenu(undefined)}><div className="connection-actions">
      {menu.kind !== "category" && <button onClick={() => { insert(menu); setMenu(undefined); }}><ChevronsRight size={14} />{t("Inserir nome no bloco em foco")}</button>}<button onClick={() => void action(() => copy(menu.name))}><Copy size={14} />{t("Copiar nome")}</button>{menu.qualified_name && <button onClick={() => void action(() => copy(menu.qualified_name!))}><Copy size={14} />{t("Copiar nome qualificado")}</button>}
      {objectKinds.has(menu.kind) && <><button onClick={() => void action(() => showDetails(menu))}><Braces size={14} />{t("Detalhes, colunas e índices")}</button><button onClick={() => void action(() => definition(menu))}><Code2 size={14} />{t("Definição / CREATE")}</button></>}
      {["table", "view"].includes(menu.kind) && <><button onClick={() => void action(() => selectQuery(menu))}><Table2 size={14} />{t("SELECT primeiras 1000 linhas")}</button><button onClick={() => void action(() => allColumns(menu))}><Table2 size={14} />{t("SELECT com todas as colunas")}</button><button onClick={() => { onInsert(`SELECT COUNT(*) FROM ${quoted(menu)};`, "sql", true); setMenu(undefined); }}><Table2 size={14} />COUNT(*)</button>{menu.kind === "table" && <button onClick={() => void action(() => definition(menu, true))}><Code2 size={14} />{t("Script DROP e CREATE")}</button>}</>}
      {menu.kind === "column" && <>{["WHERE", "GROUP BY", "ORDER BY"].map((clause) => <button key={clause} onClick={() => { onInsert(`${clause} ${quoteIdentifierPart(menu.name, dbType)}${clause === "WHERE" ? " = " : ""}`); setMenu(undefined); }}>{clause}</button>)}</>}
      {["database", "catalog", "schema"].includes(menu.kind) && <button disabled={disabled} onClick={() => void action(() => useContext(menu))}><Database size={14} />{t("Usar")} {menu.kind === "schema" ? "schema" : t("banco / catálogo")} {t("no bloco")}</button>}
      {menu.has_children && <button onClick={() => void action(() => load(menu, true))}><RefreshCw size={14} />{t("Atualizar este grupo")}</button>}
    </div></Modal>}
    {details && <Modal title={t("Detalhes · {name}",{name:qualified(details.node)})} className="explorer-details" onClose={() => setDetails(undefined)}>{details.error ? <p className="catalog-error">{t(details.error)}</p> : !details.data ? <p className="explorer-hint">{t("Carregando detalhes…")}</p> : <><div className="explorer-detail-tables">{(details.data.row_count != null || !!details.data.size_pretty) && <p className="explorer-hint">{details.data.row_count != null ? t("{count} linhas",{count:String(details.data.row_count)}) : ""}{details.data.size_pretty ? ` · ${String(details.data.size_pretty)}` : ""}</p>}{["columns", "indexes", "keys", "primary_key", "foreign_keys", "parameters"].map((key) => { const raw = details.data![key]; const data = Array.isArray(raw) ? raw as Array<Record<string, unknown>> : raw && typeof raw === "object" ? [raw as Record<string, unknown>] : []; if (!data.length) return null; const names = [...new Set(data.flatMap((row) => Object.keys(row)))]; const labels: Record<string,string> = { columns: t("Colunas"), indexes: t("Índices"), keys: t("Chaves"), primary_key: t("Chave primária"), foreign_keys: t("Chaves estrangeiras"), parameters: t("Parâmetros") }; return <section key={key}><h3>{labels[key]}</h3><table><thead><tr>{names.map((name) => <th key={name}>{name}</th>)}</tr></thead><tbody>{data.map((row, index) => <tr key={index}>{names.map((name) => <td key={name}>{typeof row[name] === "object" ? JSON.stringify(row[name]) : String(row[name] ?? "")}</td>)}</tr>)}</tbody></table></section>; })}{details.data.definition && <section><h3>{t("Definição")}</h3><pre>{details.data.definition}</pre></section>}{!details.data.definition && !details.data.columns?.length && !details.data.indexes?.length && !details.data.keys?.length && <p className="explorer-hint">{t("O driver não retornou detalhes deste objeto.")}</p>}</div><footer className="modal-footer">{details.data.definition && <button className="secondary-button" onClick={() => { onInsert(details.data!.definition!, "sql", true); setDetails(undefined); }}>{t("Abrir definição em novo bloco")}</button>}<button className="primary-button" onClick={() => setDetails(undefined)}>{t("Fechar")}</button></footer></>}</Modal>}
  </section>;
}
