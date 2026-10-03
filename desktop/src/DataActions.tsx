import { featureTranslate as t } from "./featureTranslations";
import { useLocale } from "./i18n";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {createPortal} from "react-dom";
import { open, save } from "@tauri-apps/plugin-dialog";
import {revealItemInDir} from "@tauri-apps/plugin-opener";
import { BarChart3, Download, FileUp, LoaderCircle, Sigma, X } from "lucide-react";
import { runtime, errorText, type ResultRef, type Variable } from "./runtime";
import type { DataView, ResultSummary } from "./dataTypes";
import {normalizeExportSettings, type ExportSettings} from "./exportSettings";
import {importedDataCode} from "./importCode";
import {getFocusedDocument} from "./documentWindows";
import "./dataActions.css";

export interface DataActionsProps {
  sessionId: string; result?: ResultRef; connectionType?: string; disabled?: boolean; view?: DataView;
  onImported: (result: ResultRef, variables: Variable[], generatedCode?: string) => void;
  onChart: () => void; onMessage: (message: string) => void;
  initialExportSettings?: Partial<ExportSettings>; onExportSettingsChange?: (settings: ExportSettings) => void;
  defaultOpenFolder?:boolean;onOpenFolderChange?:(openFolder:boolean)=>void;
}
export function DataModal({ title, children, onClose }: {title: string; children: React.ReactNode; onClose: () => void}) {
  useLocale();
  const container = useRef<HTMLElement>(null), close = useRef(onClose); close.current = onClose;
  const [host] = useState(() => {const owner = getFocusedDocument(); return {owner, previous: owner.activeElement as HTMLElement | null};});
  useLayoutEffect(() => {
    const panel = container.current, owner = host.owner, view = owner.defaultView;
    let unloading = false;
    const focusables = () => Array.from(panel?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]') ?? []).filter(element => element.getClientRects().length);
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
export function DataActions({sessionId, result, connectionType, disabled, view, onImported, onChart, onMessage, initialExportSettings, onExportSettingsChange,defaultOpenFolder=true,onOpenFolderChange}: DataActionsProps) {
  useLocale();
  const [dialog, setDialog] = useState<"import" | "export" | "table" | "summary">();
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [path, setPath] = useState(""), [variableName, setVariableName] = useState("");
  const initialOptions = normalizeExportSettings(initialExportSettings);
  const [delimiter, setDelimiter] = useState(initialOptions.delimiter), [encoding, setEncoding] = useState(initialOptions.encoding), [decimal, setDecimal] = useState(initialOptions.decimal);
  const [includeHeader, setIncludeHeader] = useState(initialOptions.include_header), [openFolder, setOpenFolder] = useState(initialOptions.open_folder), [overwrite, setOverwrite] = useState(false);
  const [format, setFormat] = useState("csv"), [table, setTable] = useState("data"), [schema, setSchema] = useState("");
  const [ifExists, setIfExists] = useState("fail"), [chunksize, setChunksize] = useState(1000);
  const [selected, setSelected] = useState(false), [summary, setSummary] = useState<ResultSummary>();
  useEffect(() => { setDialog(undefined); setError(""); setSummary(undefined); }, [sessionId, result?.result_id]);
  useEffect(() => {const options = normalizeExportSettings(initialExportSettings); setDelimiter(options.delimiter); setDecimal(options.decimal); setEncoding(options.encoding); setIncludeHeader(options.include_header); setOpenFolder(format === "csv" ? options.open_folder : defaultOpenFolder);}, [sessionId,initialExportSettings?.delimiter,initialExportSettings?.decimal,initialExportSettings?.encoding,initialExportSettings?.include_header,initialExportSettings?.open_folder,defaultOpenFolder]);
  const close = () => { if (!busy) setDialog(undefined); };
  function begin(next: typeof dialog) { setError(""); setDialog(next); setSelected(false); setSummary(undefined); }
  async function action(task: () => Promise<void>) { setBusy(true); setError(""); try { await task(); } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); } }
  const source = () => ({ session_id: sessionId, result_id: result?.result_id, filter: view?.filter, sort: view?.sort, ...(selected && view?.scope ? {scope: view.scope} : {}) });
  async function chooseImport() {
    const chosen = await open({multiple: false, filters: [{name: t("Dados"), extensions: ["csv", "tsv", "json", "xlsx", "xls", "parquet"]}]});
    if (typeof chosen === "string") { setPath(chosen); setVariableName(chosen.split(/[\\/]/).at(-1)?.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^\p{L}\p{N}_]+/gu, "_") ?? "df"); if (chosen.toLowerCase().endsWith(".tsv")) setDelimiter("\t"); }
  }
  async function importFile() {
    const imported = await runtime.request<{result: ResultRef; variables: Variable[]}>("data.import", {session_id: sessionId, path, variable_name: variableName || undefined, overwrite, options: {delimiter: delimiter || null, encoding, decimal}});
    onImported(imported.result, imported.variables, importedDataCode(path, imported.result.variable_name, {delimiter: delimiter || null, encoding, decimal})); onMessage(t("Arquivo importado: {name} · {rows} linhas", {name: imported.result.variable_name, rows: imported.result.row_count.toLocaleString()})); setDialog(undefined);
  }
  async function exportFile() {
    if (!result) return;
    const chosen = await save({defaultPath: `${result.variable_name}.${format}`, filters: [{name: format.toUpperCase(), extensions: [format]}]});
    if (!chosen) return;
    if(format === "csv")onExportSettingsChange?.({delimiter, decimal, encoding, include_header: includeHeader, open_folder: openFolder});
    else onOpenFolderChange?.(openFolder);
    const exported = await runtime.request<{path: string; row_count: number}>("result.export", {...source(), path: chosen, format, options: {delimiter, decimal, encoding, include_header: includeHeader, table_name: table, schema_name: schema, db_type: connectionType || "sqlserver"}});
    onMessage(t("{rows} linhas exportadas para {path}", {rows: exported.row_count.toLocaleString(), path: exported.path})); setDialog(undefined);
    if (openFolder) {try {await revealItemInDir(exported.path);} catch {onMessage(t("Arquivo salvo. Não foi possível abrir a pasta: {path}", {path: exported.path}));}}
  }
  async function exportTable() {
    const exported = await runtime.request<{row_count: number}>("result.export_table", {...source(), table, schema: schema || undefined, if_exists: ifExists, chunksize});
    onMessage(t("{rows} linhas exportadas para {path}", {rows: exported.row_count.toLocaleString(), path: `${schema ? `${schema}.` : ""}${table}`})); setDialog(undefined);
  }
  return <div className="data-actions">
    <button disabled={disabled || busy} onClick={() => {begin("import"); setPath("");}}><FileUp size={13}/>{t("Importar dados")}</button>
    <button disabled={disabled || busy || !result} onClick={() => begin("export")}><Download size={13}/>{t("Exportar")}</button>
    <button disabled={disabled || busy || !result || !connectionType} onClick={() => begin("table")}>{t("Para tabela")}</button>
    <button disabled={disabled || busy || !result} onClick={() => begin("summary")}><Sigma size={13}/>{t("Resumo")}</button>
    <button disabled={disabled || busy || !result} onClick={onChart}><BarChart3 size={13}/>{t("Gráfico")}</button>
    {dialog && <DataModal title={t(dialog === "import" ? "Importar arquivo de dados" : dialog === "table" ? "Exportar para tabela" : dialog === "summary" ? "Resumo dos dados" : "Exportar resultado")} onClose={close}>
      <div className="data-form">
        {dialog === "import" ? <><label>{t("Arquivo")}<div className="data-path"><input value={path} onChange={(event) => setPath(event.target.value)} placeholder={t("Escolha um arquivo…")}/><button disabled={busy} onClick={() => void action(chooseImport)}>{t("Escolher")}</button></div></label><label>{t("Nome da variável")}<input value={variableName} onChange={(event) => setVariableName(event.target.value)} placeholder={t("df")}/></label><label className="data-check"><input type="checkbox" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)}/>{t("Substituir variável existente")}</label></> : <>
          <p className="data-source">{result?.variable_name} {t("·")} {result?.row_count.toLocaleString()} {t("linhas ·")} {result?.columns.length} {t("colunas")}</p>
          {view?.scope && <label className="data-check"><input type="checkbox" checked={selected} onChange={(event) => {setSelected(event.target.checked); setSummary(undefined);}}/>{t("Usar somente a seleção da grade")}</label>}
          {Boolean(view?.filter || view?.sort) && <small>{t("O filtro e a ordenação atuais da grade serão aplicados.")}</small>}
        </>}
        {dialog === "export" && <label>{t("Formato")}<select value={format} onChange={(event) => {setFormat(event.target.value);setOpenFolder(event.target.value === "csv" ? normalizeExportSettings(initialExportSettings).open_folder : defaultOpenFolder);}}>{["csv", "xlsx", "json", "parquet", "sql"].map((item) => <option key={item} value={item}>{item.toUpperCase()}</option>)}</select></label>}
        {(dialog === "import" && /\.(csv|tsv)$/i.test(path) || dialog === "export" && format === "csv") && <div className="data-field-row"><label>{t("Separador")}<select value={delimiter} onChange={(event) => setDelimiter(event.target.value)}><option value=";">{t("Ponto e vírgula (;)")}</option><option value=",">{t("Vírgula (,)")}</option><option value="\t">{t("Tabulação")}</option><option value="|">{t("Barra vertical (|)")}</option>{dialog === "import" && <option value="">{t("Detectar automaticamente")}</option>}</select></label><label>{t("Decimal")}<select value={decimal} onChange={(event) => setDecimal(event.target.value)}><option value=".">{t("Ponto (.)")}</option><option value=",">{t("Vírgula (,)")}</option></select></label><label>{t("Encoding")}<select value={encoding} onChange={(event) => setEncoding(event.target.value)}><option value="utf-8-sig">{t("UTF-8 com BOM")}</option><option value="utf-8">{t("UTF-8")}</option><option value="cp1252">{t("Windows 1252")}</option><option value="latin-1">{t("Latin-1")}</option></select></label></div>}
        {dialog === "export" && format === "csv" && <label className="data-check"><input type="checkbox" checked={includeHeader} onChange={(event) => setIncludeHeader(event.target.checked)}/>{t("Incluir cabeçalhos")}</label>}
        {dialog === "export" && <label className="data-check"><input type="checkbox" checked={openFolder} onChange={event => setOpenFolder(event.target.checked)}/>{t("Abrir pasta após exportar")}</label>}
        {(dialog === "table" || dialog === "export" && format === "sql") && <><div className="data-field-row"><label>{t("Tabela")}<input value={table} onChange={(event) => setTable(event.target.value)}/></label><label>{t("Schema")}<input value={schema} onChange={(event) => setSchema(event.target.value)} placeholder={t("Padrão da conexão")}/></label></div>{dialog === "table" && <><div className="data-field-row"><label>{t("Se a tabela existir")}<select value={ifExists} onChange={(event) => setIfExists(event.target.value)}><option value="fail">{t("Falhar")}</option><option value="append">{t("Acrescentar")}</option><option value="replace">{t("Substituir")}</option></select></label><label>{t("Linhas por lote")}<input type="number" min={100} max={100000} value={chunksize} onChange={(event) => setChunksize(Number(event.target.value))}/></label></div>{ifExists === "replace" && <p className="data-operation-note">{t("Substituir remove a tabela existente e grava os dados deste resultado.")}</p>}</>}</>}
        {dialog === "summary" && summary && <div className="data-summary"><p>{summary.row_count.toLocaleString()} {t("linhas ·")} {summary.column_count} {t("colunas")}{summary.columns_truncated && ` · ${t("primeiras 200 colunas")}`}</p>{summary.columns.map((column) => <article key={column.name}><strong>{column.name} <small>{column.dtype}</small></strong><dl>{Object.entries(column).filter(([key]) => ["count", "null_count", "distinct", "min", "max", "sum", "mean", "median", "std"].includes(key)).map(([key, value]) => <div key={key}><dt>{t({count: "Linhas", null_count: "Nulos", distinct: "Distintos", min: "Mínimo", max: "Máximo", sum: "Soma", mean: "Média", median: "Mediana", std: "Desvio padrão"}[key] ?? key)}</dt><dd>{value === null ? "—" : String(value)}</dd></div>)}</dl>{column.sampled && <small>{t("Estatísticas de texto calculadas sobre as primeiras")} {column.sample_rows?.toLocaleString()} {t("linhas.")}</small>}{column.top && <p className="data-top-values">{column.top.map((item) => `${item.value}: ${item.count}`).join(" · ")}</p>}</article>)}</div>}
        {error && <p className="data-error" role="alert">{error}</p>}
      </div>
      <footer><button disabled={busy} onClick={close}>{t("Fechar")}</button><button className="primary-button" disabled={busy || dialog === "import" && !path || dialog === "table" && !table.trim()} onClick={() => void action(dialog === "import" ? importFile : dialog === "export" ? exportFile : dialog === "table" ? exportTable : async () => setSummary(await runtime.request<ResultSummary>("result.summary", source())))}>{busy ? <LoaderCircle size={14} className="spin"/> : null}{t(dialog === "import" ? "Importar" : dialog === "summary" ? "Calcular" : "Exportar")}</button></footer>
    </DataModal>}
  </div>;
}

export async function chooseAndExportScript(sessionId: string, blocks: Array<Record<string, unknown>>, defaultName: string) {
  const path = await save({defaultPath: `${defaultName}.py`, filters: [{name: "Python", extensions: ["py"]}, {name: "SQL", extensions: ["sql"]}, {name: "Jupyter", extensions: ["ipynb"]}]});
  if (!path) return undefined;
  return runtime.request<{path: string}>("document.script_export", {session_id: sessionId, path, blocks});
}
