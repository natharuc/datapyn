import { featureTranslate as t } from "./featureTranslations";
import { useLocale } from "./i18n";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import {createPortal} from "react-dom";
import { open, save } from "@tauri-apps/plugin-dialog";
import {revealItemInDir} from "@tauri-apps/plugin-opener";
import { BarChart3, Clipboard, Code2, Database, Download, FileUp, LoaderCircle, Sigma, X } from "lucide-react";
import { runtime, errorText, type ResultRef, type Variable } from "./runtime";
import type { DataView, ResultSummary } from "./dataTypes";
import {normalizeExportSettings, type ExportSettings} from "./exportSettings";
import {importedDataCode} from "./importCode";
import {getFocusedDocument} from "./documentWindows";
import { clipboardFormat, DEFAULT_FORMAT_EXPORT_SETTINGS, EXPORT_FORMATS, exportOptions, exportPath, exportProgressPercent, exportSource, readExportProgress, temporaryTableName,
  type ExportConnection, type ExportDestination, type ExportFormat, type ExportProgress, type ExportTextResult, type FormatExportSettings } from "./dataExport";
import "./dataActions.css";

export interface DataActionsProps {
  sessionId: string; result?: ResultRef; connectionType?: string; disabled?: boolean; view?: DataView;
  onImported: (result: ResultRef, variables: Variable[], generatedCode?: string) => void;
  onChart: () => void; onMessage: (message: string) => void;
  initialExportSettings?: Partial<ExportSettings>; onExportSettingsChange?: (settings: ExportSettings) => void;
  defaultOpenFolder?:boolean;onOpenFolderChange?:(openFolder:boolean)=>void;
  availableConnections?: ExportConnection[]; currentConnectionId?: string; currentDatabase?: string; currentSchema?: string;
  onInsertSql?: (code: string) => void;
  hideImport?: boolean; hideChart?: boolean; hideResultActions?: boolean; onTableExported?: () => void;
}
export function DataModal({ title, children, onClose }: {title: string; children: React.ReactNode; onClose: () => void}) {
  useLocale();
  const container = useRef<HTMLElement>(null), close = useRef(onClose); close.current = onClose;
  const [host] = useState(() => {const owner = getFocusedDocument(); return {owner, previous: owner.activeElement as HTMLElement | null};});
  useLayoutEffect(() => {
    const panel = container.current, owner = host.owner, view = owner.defaultView;
    let unloading = false;
    const focusables = () => Array.from(panel?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]:not(:disabled)') ?? []).filter(element => element.getClientRects().length);
    (focusables()[0] ?? panel)?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape") {event.preventDefault(); event.stopPropagation(); close.current();}
      if (event.key === "Tab") {
        const items = focusables(), index = items.indexOf(owner.activeElement as HTMLElement);
        if (!items.length) {event.preventDefault(); panel?.focus();}
        else if ((event.shiftKey && index <= 0) || (!event.shiftKey && (index < 0 || index === items.length - 1))) {event.preventDefault(); items[event.shiftKey ? items.length - 1 : 0].focus();}
      }
    };
    const unload = () => {unloading = true; close.current();};
    panel?.addEventListener("keydown", handle);
    view?.addEventListener("pagehide", unload); view?.addEventListener("unload", unload);
    return () => {panel?.removeEventListener("keydown", handle); view?.removeEventListener("pagehide", unload); view?.removeEventListener("unload", unload); if (!unloading && !view?.closed && host.previous?.isConnected) host.previous.focus();};
  }, [host]);
  return createPortal(<div className="data-modal-backdrop" onPointerDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={container} tabIndex={-1} className="data-modal" role="dialog" aria-modal="true" aria-label={title}><header><strong>{title}</strong><button aria-label={t("Fechar")} onClick={onClose}><X size={16}/></button></header>{children}</section>
  </div>, host.owner.body);
}
export function DataActions({sessionId, result, connectionType, disabled, view, onImported, onChart, onMessage, initialExportSettings, onExportSettingsChange,
  defaultOpenFolder=true, onOpenFolderChange, availableConnections=[], currentConnectionId, currentDatabase, currentSchema, onInsertSql, hideImport=false, hideChart=false, hideResultActions=false, onTableExported}: DataActionsProps) {
  useLocale();
  const formId = useId();
  const [dialog, setDialog] = useState<"import" | "export" | "table" | "sql" | "summary">();
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [path, setPath] = useState(""), [variableName, setVariableName] = useState("");
  const initialOptions = normalizeExportSettings(initialExportSettings);
  const [delimiter, setDelimiter] = useState(initialOptions.delimiter), [encoding, setEncoding] = useState(initialOptions.encoding), [decimal, setDecimal] = useState(initialOptions.decimal);
  const [includeHeader, setIncludeHeader] = useState(initialOptions.include_header), [openFolder, setOpenFolder] = useState(initialOptions.open_folder), [overwrite, setOverwrite] = useState(false);
  const [format, setFormat] = useState<ExportFormat>("csv"), [destination, setDestination] = useState<ExportDestination>("file");
  const [formatOptions, setFormatOptions] = useState<FormatExportSettings>({...DEFAULT_FORMAT_EXPORT_SETTINGS, sqlDialect: connectionType || "sqlserver"});
  const [table, setTable] = useState(result?.variable_name || "data"), [schema, setSchema] = useState(currentSchema || "");
  const [destinationConnection, setDestinationConnection] = useState(currentConnectionId || ""), [database, setDatabase] = useState(currentDatabase || ""), [temporary, setTemporary] = useState(false);
  const [ifExists, setIfExists] = useState("fail"), [chunksize, setChunksize] = useState(1000);
  const [selected, setSelected] = useState(false), [summary, setSummary] = useState<ResultSummary>(), [sqlPreview, setSqlPreview] = useState<ExportTextResult>();
  const [progress, setProgress] = useState<ExportProgress>(), [cancelling, setCancelling] = useState(false);
  const operation = useRef<{id: string; sessionId: string; cancellable: boolean; cancelled?: boolean}>();
  const owner = useRef({sessionId, resultId: result?.result_id}); owner.current = {sessionId, resultId: result?.result_id};
  const mounted = useRef(true), busyRef = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { setDialog(undefined); setError(""); setSummary(undefined); setSqlPreview(undefined); setTable(result?.variable_name || "data"); }, [sessionId, result?.result_id]);
  useEffect(() => {
    const options = normalizeExportSettings(initialExportSettings);
    setDelimiter(options.delimiter); setDecimal(options.decimal); setEncoding(options.encoding); setIncludeHeader(options.include_header);
    setOpenFolder(format === "csv" ? options.open_folder : defaultOpenFolder);
  }, [sessionId,initialExportSettings?.delimiter,initialExportSettings?.decimal,initialExportSettings?.encoding,initialExportSettings?.include_header,initialExportSettings?.open_folder,defaultOpenFolder]);
  useEffect(() => {
    setDestinationConnection(currentConnectionId || ""); setDatabase(currentDatabase || ""); setSchema(currentSchema || "");
    setFormatOptions(prior => ({...prior, sqlDialect: connectionType || "sqlserver"}));
  }, [sessionId,currentConnectionId,currentDatabase,currentSchema,connectionType]);
  useEffect(() => {
    let disposed = false, cleanup: (() => void) | undefined;
    void runtime.subscribe(event => {
      const update = readExportProgress(event), active = operation.current;
      if (update && active?.id === update.operation_id && active.sessionId === update.session_id && mounted.current) {active.cancelled = update.phase === "cancelled"; setProgress(update);}
    }).then(unsubscribe => { if (disposed) unsubscribe(); else cleanup = unsubscribe; }).catch(() => {});
    return () => { disposed = true; cleanup?.(); };
  }, []);
  useEffect(() => setSqlPreview(undefined), [table,schema,formatOptions,selected,view?.filter,view?.sort,view?.scope]);
  const close = () => { if (!busyRef.current) setDialog(undefined); };
  function begin(next: typeof dialog) {
    setError(""); setDialog(next); setSelected(false); setSummary(undefined); setSqlPreview(undefined); setProgress(undefined);
    if (next === "table" && !connectionType && !currentConnectionId && availableConnections.length) {
      setDestinationConnection(availableConnections[0].id); setDatabase(availableConnections[0].database || ""); setSchema("");
    }
  }
  function setting<K extends keyof FormatExportSettings>(key: K, value: FormatExportSettings[K]) { setFormatOptions(prior => ({...prior, [key]: value})); }
  const csvSettings = (): ExportSettings => ({delimiter,decimal,encoding,include_header:includeHeader,open_folder:openFolder});
  const source = () => exportSource(sessionId,result?.result_id,view,selected);
  const options = (kind: ExportFormat) => exportOptions(kind,csvSettings(),formatOptions,table,schema);
  const activeConnection = availableConnections.find(item => item.id === destinationConnection);
  const targetDialect = activeConnection?.db_type || connectionType || "sqlserver";
  const targetName = temporaryTableName(table,temporary,targetDialect);
  const effectiveTemporary = temporary || (["sqlserver","mssql"].includes(targetDialect) && table.startsWith("#"));
  async function action(task: (operationId: string) => Promise<void>) {
    if (busyRef.current) return;
    const id = crypto.randomUUID(), origin = owner.current;
    busyRef.current = true; operation.current = {id,sessionId,cancellable:false};
    setBusy(true); setError(""); setCancelling(false); setProgress(undefined);
    try { await task(id); }
    catch (failure) {
      if (operation.current?.cancelled || /\bexport cancelled\b/i.test(errorText(failure))) {
        if (mounted.current) {setError("");setProgress(prior=>prior?{...prior,phase:"cancelled"}:undefined);}
        onMessage(t("Exportação cancelada."));
      } else if (mounted.current && owner.current.sessionId === origin.sessionId && owner.current.resultId === origin.resultId) {setProgress(undefined);setError(errorText(failure));}
      else onMessage(errorText(failure));
    }
    finally { if (operation.current?.id === id) operation.current = undefined; busyRef.current = false; if (mounted.current) {setBusy(false);setCancelling(false);} }
  }
  function startProgress() {
    const active = operation.current;
    if (active) { active.cancellable = true; setProgress({session_id:active.sessionId,operation_id:active.id,phase:"preparing",current:0,total:0}); }
  }
  async function cancelExport() {
    const active = operation.current;
    if (!active?.cancellable || cancelling) return;
    setCancelling(true);
    try { await runtime.request("result.export_cancel", {session_id:active.sessionId,operation_id:active.id}); }
    catch (failure) {setError(errorText(failure)); setCancelling(false);}
  }
  async function chooseImport() {
    const chosen = await open({multiple: false, filters: [{name: t("Dados"), extensions: ["csv", "tsv", "txt", "json", "xlsx", "xls", "parquet"]}]});
    if (typeof chosen === "string") { setPath(chosen); setVariableName(chosen.split(/[\\/]/).at(-1)?.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^\p{L}\p{N}_]+/gu, "_") ?? "df"); if (chosen.toLowerCase().endsWith(".tsv")) setDelimiter("\t"); }
  }
  async function importFile() {
    const imported = await runtime.request<{result: ResultRef; variables: Variable[]}>("data.import", {session_id: sessionId, path, variable_name: variableName || undefined, overwrite, options: {delimiter: delimiter || null, encoding, decimal}});
    onImported(imported.result, imported.variables, importedDataCode(path, imported.result.variable_name, {delimiter: delimiter || null, encoding, decimal}));
    onMessage(t("Arquivo importado: {name} · {rows} linhas", {name: imported.result.variable_name, rows: imported.result.row_count.toLocaleString()})); setDialog(undefined);
  }
  async function writeClipboard(text: string) {
    const clipboard = getFocusedDocument().defaultView?.navigator.clipboard;
    if (!clipboard) throw new Error(t("Área de transferência indisponível nesta janela."));
    await clipboard.writeText(text);
  }
  async function exportFile(operationId: string) {
    if (!result) return;
    const kind = dialog === "sql" ? "sql" : format;
    const chosen = await save({defaultPath: `${result.variable_name}.${kind}`, filters: [{name: kind.toUpperCase(), extensions: [kind]}]});
    if (!chosen) return;
    if(kind === "csv") onExportSettingsChange?.(csvSettings()); else onOpenFolderChange?.(openFolder);
    startProgress();
    const exported = await runtime.request<{path: string; row_count: number}>("result.export", {...source(),operation_id:operationId,path:exportPath(chosen,kind),format:kind,options:options(kind)});
    onMessage(t("{rows} linhas exportadas para {path}", {rows: exported.row_count.toLocaleString(), path: exported.path})); setDialog(undefined);
    if (openFolder) {try {await revealItemInDir(exported.path);} catch {onMessage(t("Arquivo salvo. Não foi possível abrir a pasta: {path}", {path: exported.path}));}}
  }
  async function exportClipboard(operationId: string) {
    if (!result) return;
    if (format === "csv") onExportSettingsChange?.(csvSettings());
    startProgress();
    const exported = await runtime.request<ExportTextResult>("result.export_text", {...source(),operation_id:operationId,format:clipboardFormat(format),options:options(format)});
    await writeClipboard(exported.text); onMessage(t("{rows} linhas copiadas como {format}",{rows:exported.row_count.toLocaleString(),format:format.toUpperCase()})); setDialog(undefined);
  }
  async function previewSql(operationId: string) {
    startProgress();
    const generated = await runtime.request<ExportTextResult>("result.export_text", {...source(),operation_id:operationId,format:"sql",options:options("sql")});
    setSqlPreview(generated);
  }
  async function exportTable(operationId: string) {
    startProgress();
    const exported = await runtime.request<{row_count: number}>("result.export_table", {...source(),operation_id:operationId,connection_id:destinationConnection || undefined,connection_schema:destinationConnection===(currentConnectionId||"")?currentSchema:undefined,database:database || undefined,table:targetName,schema:effectiveTemporary ? undefined : schema || undefined,temporary:effectiveTemporary,if_exists:ifExists,chunksize});
    onTableExported?.(); onMessage(t("{rows} linhas exportadas para {path}", {rows: exported.row_count.toLocaleString(), path: `${effectiveTemporary || !schema ? "" : `${schema}.`}${targetName}`})); setDialog(undefined);
  }
  const sqlForm = dialog === "sql" || dialog === "export" && format === "sql";
  const csvForm = dialog === "import" && /\.(csv|tsv|txt)$/i.test(path) || dialog === "export" && ["csv","tsv","txt"].includes(format);
  const canSubmit = !busy && !(dialog === "import" && !path) && !((dialog === "table" || sqlForm) && !table.trim()) && !(dialog === "export" && format === "parquet" && destination === "clipboard");
  const percent = exportProgressPercent(progress);
  const submit = (operationId: string) => dialog === "import" ? importFile() : dialog === "table" ? exportTable(operationId) : dialog === "sql" ? previewSql(operationId) : dialog === "export" ? destination === "clipboard" ? exportClipboard(operationId) : exportFile(operationId) : runtime.request<ResultSummary>("result.summary",source()).then(setSummary);
  return <div className="data-actions">
    {!hideImport&&<button disabled={disabled || busy} onClick={() => {begin("import");setPath("");}}><FileUp size={13}/>{t("Importar dados")}</button>}
    {!hideResultActions && <><button disabled={disabled || busy || !result} onClick={() => begin("export")}><Download size={13}/>{t("Exportar")}</button>
    <button disabled={disabled || busy || !result || (!connectionType && !availableConnections.length)} onClick={() => begin("table")}><Database size={13}/>{t("Para tabela")}</button>
    <button disabled={disabled || busy || !result} onClick={() => begin("sql")}><Code2 size={13}/>{t("Gerar SQL")}</button>
    <button disabled={disabled || busy || !result} onClick={() => begin("summary")}><Sigma size={13}/>{t("Resumo")}</button>
    {!hideChart&&<button disabled={disabled || busy || !result} onClick={onChart}><BarChart3 size={13}/>{t("Gráfico")}</button>}</>}
    {dialog && <DataModal title={t(dialog === "import" ? "Importar arquivo de dados" : dialog === "table" ? "Exportar para tabela" : dialog === "sql" ? "Gerar script SQL" : dialog === "summary" ? "Resumo dos dados" : "Exportar resultado")} onClose={close}>
      <form id={formId} className="data-form" onSubmit={event => {event.preventDefault();if(canSubmit)void action(submit);}}>
        <fieldset disabled={busy} className="data-fieldset">
          {dialog === "import" ? <><label>{t("Arquivo")}<div className="data-path"><input value={path} onChange={event=>setPath(event.target.value)} placeholder={t("Escolha um arquivo…")}/><button type="button" onClick={()=>void action(chooseImport)}>{t("Escolher")}</button></div></label><label>{t("Nome da variável")}<input value={variableName} onChange={event=>setVariableName(event.target.value)} placeholder="df"/></label><label className="data-check"><input type="checkbox" checked={overwrite} onChange={event=>setOverwrite(event.target.checked)}/>{t("Substituir variável existente")}</label></> : <>
            <div className="data-source-card"><strong>{result?.variable_name}</strong><span>{result?.row_count.toLocaleString()} {t("linhas")} · {result?.columns.length} {t("colunas")}</span></div>
            {view?.scope && <label className="data-check"><input type="checkbox" checked={selected} onChange={event=>{setSelected(event.target.checked);setSummary(undefined);}}/>{t("Usar somente a seleção da grade")}</label>}
            {Boolean(view?.filter || view?.sort) && <small className="data-hint">{t("O filtro e a ordenação atuais da grade serão aplicados.")}</small>}
          </>}
          {dialog === "export" && <><div className="data-field-row"><label>{t("Formato")}<select value={format} onChange={event=>{const next=event.target.value as ExportFormat;setFormat(next);if(next==="parquet")setDestination("file");setOpenFolder(next==="csv"?normalizeExportSettings(initialExportSettings).open_folder:defaultOpenFolder);}}>{EXPORT_FORMATS.map(item=><option key={item} value={item}>{item==="xlsx"?"Excel (.xlsx)":item.toUpperCase()}</option>)}</select></label><label>{t("Destino")}<div className="data-destination"><button type="button" aria-pressed={destination==="file"} onClick={()=>setDestination("file")}><Download size={14}/>{t("Arquivo")}</button><button type="button" aria-pressed={destination==="clipboard"} disabled={format==="parquet"} onClick={()=>setDestination("clipboard")}><Clipboard size={14}/>{t("Área de transferência")}</button></div></label></div>{format==="parquet"&&<small className="data-hint">{t("Parquet preserva os tipos dos dados em um arquivo binário.")}</small>}</>}
          {csvForm && <div className="data-field-row"><label>{t("Separador")}<select value={dialog==="export"&&format==="tsv"?"\t":delimiter} disabled={dialog==="export"&&format==="tsv"} onChange={event=>setDelimiter(event.target.value)}><option value=";">{t("Ponto e vírgula (;)")}</option><option value=",">{t("Vírgula (,)")}</option><option value={"\t"}>{t("Tabulação")}</option><option value="|">{t("Barra vertical (|)")}</option>{dialog==="import"&&<option value="">{t("Detectar automaticamente")}</option>}</select></label><label>{t("Decimal")}<select value={decimal} onChange={event=>setDecimal(event.target.value)}><option value=".">{t("Ponto (.)")}</option><option value=",">{t("Vírgula (,)")}</option></select></label><label>{t("Encoding")}<select value={encoding} onChange={event=>setEncoding(event.target.value)}><option value="utf-8-sig">{t("UTF-8 com BOM")}</option><option value="utf-8">UTF-8</option><option value="cp1252">Windows 1252</option><option value="latin-1">Latin-1</option></select></label></div>}
          {dialog==="export"&&["csv","tsv","txt","xlsx"].includes(format)&&<div className="data-check-row"><label className="data-check"><input type="checkbox" checked={includeHeader} onChange={event=>setIncludeHeader(event.target.checked)}/>{t("Incluir cabeçalhos")}</label><label className="data-check"><input type="checkbox" checked={formatOptions.includeIndex} onChange={event=>setting("includeIndex",event.target.checked)}/>{t("Incluir índice")}</label></div>}
          {dialog==="export"&&format==="xlsx"&&<><label>{t("Nome da planilha")}<input value={formatOptions.sheetName} maxLength={31} onChange={event=>setting("sheetName",event.target.value)} placeholder="DataPyn"/></label>{destination==="clipboard"&&<small className="data-hint">{t("Para colar no Excel, os dados serão separados por tabulação.")}</small>}</>}
          {dialog==="export"&&format==="json"&&<><div className="data-field-row"><label>{t("Estrutura JSON")}<select value={formatOptions.jsonOrient} onChange={event=>setting("jsonOrient",event.target.value as FormatExportSettings["jsonOrient"])}>{["records","split","index","columns","values","table"].map(item=><option key={item} value={item}>{item}</option>)}</select></label><label>{t("Indentação")}<input type="number" min={0} max={8} value={formatOptions.jsonIndent} onChange={event=>setting("jsonIndent",Number(event.target.value))}/></label></div>{formatOptions.jsonOrient==="records"&&<label className="data-check"><input type="checkbox" checked={formatOptions.jsonLines} onChange={event=>setting("jsonLines",event.target.checked)}/>{t("Um registro JSON por linha")}</label>}</>}
          {dialog==="export"&&format==="parquet"&&<label>{t("Compressão")}<select value={formatOptions.compression} onChange={event=>setting("compression",event.target.value as FormatExportSettings["compression"])}><option value="snappy">Snappy</option><option value="zstd">Zstandard</option><option value="gzip">Gzip</option><option value="none">{t("Sem compressão")}</option></select></label>}
          {dialog==="table"&&<><label>{t("Conexão de destino")}<select value={destinationConnection} onChange={event=>{const next=availableConnections.find(item=>item.id===event.target.value);setDestinationConnection(event.target.value);setDatabase(next?next.database??"":currentDatabase||"");setSchema(event.target.value===(currentConnectionId||"")?currentSchema||"":"");setTemporary(false);}}>{!currentConnectionId&&connectionType&&<option value="">{t("Conexão da análise")}</option>}{currentConnectionId&&!availableConnections.some(item=>item.id===currentConnectionId)&&<option value={currentConnectionId}>{t("Conexão da análise")}</option>}{availableConnections.map(item=><option key={item.id} value={item.id}>{item.name} · {item.db_type}{item.database?` · ${item.database}`:""}</option>)}</select></label><label>{t("Banco de destino")}<input value={database} onChange={event=>setDatabase(event.target.value)} placeholder={t("Padrão da conexão")}/></label></>}
          {(dialog==="table"||sqlForm)&&<><div className="data-field-row"><label>{t("Tabela")}<input value={table} onChange={event=>setTable(event.target.value)} placeholder={dialog==="table"&&targetDialect==="sqlserver"?"tabela ou #temporaria":"tabela"}/></label><label>{t("Schema")}<input disabled={dialog==="table"&&effectiveTemporary} value={schema} onChange={event=>setSchema(event.target.value)} placeholder={t("Padrão da conexão")}/></label></div>
            {dialog==="table"?<><label className="data-check"><input type="checkbox" checked={effectiveTemporary} onChange={event=>{setTemporary(event.target.checked);if(!event.target.checked&&["sqlserver","mssql"].includes(targetDialect))setTable(value=>value.replace(/^#{1,2}/,""));}}/>{t("Tabela temporária")}</label>{effectiveTemporary&&<small className="data-hint">{t(targetDialect==="sqlserver"||targetDialect==="mssql"?"Use #nome para uma tabela local ou ##nome para uma tabela global. A conexão permanece disponível para os próximos blocos.":targetDialect==="databricks"?"Requer Databricks Runtime 18.1 ou SQL warehouse compatível.":"A tabela temporária permanece na conexão de destino durante esta sessão.")}</small>}<div className="data-field-row"><label>{t("Se a tabela existir")}<select value={ifExists} onChange={event=>setIfExists(event.target.value)}><option value="fail">{t("Falhar")}</option><option value="append">{t("Acrescentar")}</option><option value="replace">{t("Substituir")}</option></select></label><label>{t("Linhas por lote")}<input type="number" min={100} max={100000} value={chunksize} onChange={event=>setChunksize(Number(event.target.value))}/></label></div>{ifExists==="replace"&&<p className="data-operation-note">{t("Substituir remove a tabela existente e grava os dados deste resultado.")}</p>}</>:<><div className="data-field-row"><label>{t("Dialeto SQL")}<select value={formatOptions.sqlDialect} onChange={event=>setting("sqlDialect",event.target.value)}>{["sqlserver","postgresql","mysql","mariadb","sqlite","databricks"].map(item=><option key={item} value={item}>{item}</option>)}</select></label><label>{t("Comandos")}<select value={formatOptions.sqlMode} onChange={event=>setting("sqlMode",event.target.value as FormatExportSettings["sqlMode"])}><option value="insert">INSERT</option><option value="create">CREATE TABLE</option><option value="create_insert">CREATE TABLE + INSERT</option></select></label></div>{formatOptions.sqlMode!=="create"&&<label>{t("Linhas por INSERT")}<input type="number" min={1} max={1000} value={formatOptions.sqlBatchSize} onChange={event=>setting("sqlBatchSize",Number(event.target.value))}/></label>}<div className="data-check-row"><label className="data-check"><input type="checkbox" disabled={formatOptions.sqlDialect==="databricks"&&formatOptions.sqlMode!=="insert"} checked={formatOptions.sqlTransaction&&(formatOptions.sqlDialect!=="databricks"||formatOptions.sqlMode==="insert")} onChange={event=>setting("sqlTransaction",event.target.checked)}/>{t("Incluir transação")}</label>{formatOptions.sqlDialect==="sqlserver"&&<label className="data-check"><input type="checkbox" checked={formatOptions.sqlGo} onChange={event=>setting("sqlGo",event.target.checked)}/>{t("Separar comandos com GO")}</label>}</div></>}
          </>}
          {(dialog==="export"&&destination==="file"||dialog==="sql")&&<label className="data-check"><input type="checkbox" checked={openFolder} onChange={event=>setOpenFolder(event.target.checked)}/>{t("Abrir pasta após exportar")}</label>}
        </fieldset>
        {dialog==="sql"&&sqlPreview&&<div className="data-sql-preview"><div><strong>{t("Prévia SQL")}</strong><span>{sqlPreview.row_count.toLocaleString()} {t("linhas")}</span></div><textarea readOnly aria-label={t("Prévia SQL")} value={sqlPreview.text.slice(0,64000)} spellCheck={false}/>{sqlPreview.text.length>64000&&<small>{t("A prévia mostra os primeiros 64 mil caracteres. Copiar, salvar e inserir usam o script completo.")}</small>}<div className="data-preview-actions"><button type="button" disabled={busy} onClick={()=>void action(async()=>{await writeClipboard(sqlPreview.text);onMessage(t("Script SQL copiado."));})}><Clipboard size={13}/>{t("Copiar SQL")}</button><button type="button" disabled={busy} onClick={()=>void action(exportFile)}><Download size={13}/>{t("Salvar SQL…")}</button>{onInsertSql&&<button type="button" disabled={busy} onClick={()=>{onInsertSql(sqlPreview.text);setDialog(undefined);}}><Code2 size={13}/>{t("Inserir em novo bloco")}</button>}</div></div>}
        {dialog === "summary" && summary && <div className="data-summary"><p>{summary.row_count.toLocaleString()} {t("linhas ·")} {summary.column_count} {t("colunas")}{summary.columns_truncated && ` · ${t("primeiras 200 colunas")}`}</p>{summary.columns.map(column=><article key={column.name}><strong>{column.name} <small>{column.dtype}</small></strong><dl>{Object.entries(column).filter(([key])=>["count","null_count","distinct","min","max","sum","mean","median","std"].includes(key)).map(([key,value])=><div key={key}><dt>{t({count:"Linhas",null_count:"Nulos",distinct:"Distintos",min:"Mínimo",max:"Máximo",sum:"Soma",mean:"Média",median:"Mediana",std:"Desvio padrão"}[key]??key)}</dt><dd>{value===null?"—":String(value)}</dd></div>)}</dl>{column.sampled&&<small>{t("Estatísticas de texto calculadas sobre as primeiras")} {column.sample_rows?.toLocaleString()} {t("linhas.")}</small>}{column.top&&<p className="data-top-values">{column.top.map(item=>`${item.value}: ${item.count}`).join(" · ")}</p>}</article>)}</div>}
        {progress&&<div className="data-export-progress" role="status" aria-live="polite"><div><span>{t(cancelling?"Cancelando exportação…":progress.phase==="preparing"?"Preparando exportação…":progress.phase==="cancelled"?"Exportação cancelada.":progress.phase==="completed"?"Exportação concluída.":"Exportando…")}</span><span>{progress.total?`${progress.current.toLocaleString()} / ${progress.total.toLocaleString()}${percent===undefined?"":` · ${percent}%`}`:""}</span></div><progress max={100} value={percent}/></div>}
        {error&&<p className="data-error" role="alert">{t(error)}</p>}
      </form>
      <footer>{busy&&operation.current?.cancellable?<button disabled={cancelling} onClick={()=>void cancelExport()}>{t(cancelling?"Cancelando…":"Cancelar exportação")}</button>:<button disabled={busy} onClick={close}>{t("Fechar")}</button>}<button type="submit" form={formId} className="primary-button" disabled={!canSubmit}>{busy&&<LoaderCircle size={14} className="spin"/>}{t(dialog==="import"?"Importar":dialog==="summary"?"Calcular":dialog==="sql"?"Gerar prévia":dialog==="export"&&destination==="clipboard"?"Copiar":"Exportar")}</button></footer>
    </DataModal>}
  </div>;
}

export async function chooseAndExportScript(sessionId: string, blocks: Array<Record<string, unknown>>, defaultName: string) {
  const path = await save({defaultPath: `${defaultName}.py`, filters: [{name: "Python", extensions: ["py"]}, {name: "SQL", extensions: ["sql"]}, {name: "Jupyter", extensions: ["ipynb"]}]});
  if (!path) return undefined;
  return runtime.request<{path: string}>("document.script_export", {session_id: sessionId, path, blocks});
}
