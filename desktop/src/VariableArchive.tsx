import {useEffect, useMemo, useRef, useState} from "react";
import {open, save} from "@tauri-apps/plugin-dialog";
import {Archive, Download, FileUp, FolderOpen, LoaderCircle, Search} from "lucide-react";
import {featureTranslate as t} from "./featureTranslations";
import {useLocale} from "./i18n";
import {DataModal} from "./DataActions";
import {errorText, runtime, type ResultRef, type Variable} from "./runtime";
import {exportProgressPercent, readExportProgress, type ExportProgress} from "./dataExport";
import "./variableArchive.css";

interface ArchiveVariable {name: string; type: string; kind: string; row_count: number; column_count: number}
interface ArchiveInventory {variables: ArchiveVariable[]; total: number}
interface ImportResult {names: string[]; count: number; results: ResultRef[]; variables: Variable[]}
export interface VariableArchiveProps {
  sessionId: string;
  disabled?: boolean;
  onImported: (results: ResultRef[], variables: Variable[]) => void | Promise<void>;
  onMessage: (message: string) => void;
}

/** Public packages are portable and independent of the automatic session cache. */
export function VariableArchive({sessionId, disabled, onImported, onMessage}: VariableArchiveProps) {
  useLocale();
  const [dialog, setDialog] = useState<"export" | "import">();
  const [inventory, setInventory] = useState<ArchiveInventory>(), [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState(""), [limit, setLimit] = useState(200), [kind, setKind] = useState("folder");
  const [path, setPath] = useState(""), [variableName, setVariableName] = useState("");
  const [overwrite, setOverwrite] = useState(false), [busy, setBusy] = useState(false), [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState(""), [progress, setProgress] = useState<ExportProgress>();
  const mounted = useRef(true), generation = useRef(0), busyRef = useRef(false);
  const owner = useRef(sessionId); owner.current = sessionId;
  const operation = useRef<{id: string; sessionId: string; cancellable: boolean}>();
  useEffect(() => {mounted.current = true; return () => {mounted.current = false;};}, []);
  useEffect(() => {++generation.current; setDialog(undefined); setInventory(undefined); setSelected(new Set()); setPath(""); setProgress(undefined); setError("");}, [sessionId]);
  useEffect(() => {
    let active = true, stop: (() => void) | undefined;
    void runtime.subscribe(event => {
      const incoming = readExportProgress(event), current = operation.current;
      if (active && incoming && current?.id === incoming.operation_id && current.sessionId === incoming.session_id) setProgress(incoming);
    }).then(unsubscribe => {if (active) stop = unsubscribe; else unsubscribe();}).catch(() => {});
    return () => {active = false; stop?.();};
  }, []);
  const filtered = useMemo(() => (inventory?.variables ?? []).filter(variable => variable.name.toLocaleLowerCase().includes(query.toLocaleLowerCase())), [inventory, query]);
  const close = () => {if (!busyRef.current) setDialog(undefined);};
  async function action(work: (id: string, current: () => boolean) => Promise<void>) {
    if (busyRef.current) return;
    const id = crypto.randomUUID(), origin = sessionId, revision = generation.current;
    const current = () => mounted.current && owner.current === origin && generation.current === revision;
    busyRef.current = true; operation.current = {id, sessionId: origin, cancellable: false};
    setBusy(true); setCancelling(false); setProgress(undefined); setError("");
    try {await work(id, current);} catch (failure) {if (current()) setError(errorText(failure)); else onMessage(errorText(failure));}
    finally {if (operation.current?.id === id) operation.current = undefined; busyRef.current = false; if (mounted.current) {setBusy(false); setCancelling(false);}}
  }
  function begin(mode: "export" | "import") {
    setDialog(mode); setError(""); setOverwrite(false); setQuery(""); setLimit(200); setVariableName(""); setProgress(undefined);
    if (mode === "import") {setPath(""); return;}
    setInventory(undefined); setKind("folder");
    void action(async (_, current) => {
      const value = await runtime.request<ArchiveInventory>("variable.archive.list", {session_id: sessionId});
      if (current()) {setInventory(value); setSelected(new Set(value.variables.map(variable => variable.name)));}
    });
  }
  async function exportPackage(id: string, current: () => boolean) {
    const names = inventory?.variables.filter(variable => selected.has(variable.name)).map(variable => variable.name) ?? [];
    const singleFile = kind === "file" && names.length === 1;
    const chosen = singleFile
      ? await save({defaultPath: `${names[0]}.parquet`, filters: [{name: "Parquet", extensions: ["parquet"]}]})
      : await open({directory: true, multiple: false, title: t("Escolher pasta do pacote")});
    if (typeof chosen !== "string" || !current()) return;
    const destination = singleFile && !/\.parquet$/i.test(chosen) ? `${chosen}.parquet` : chosen;
    operation.current!.cancellable = true;
    const result = await runtime.request<{count: number; path: string}>("variable.archive.export", {session_id: sessionId, operation_id: id, names, path: destination, overwrite});
    onMessage(t("{count} variáveis exportadas para {path}", {count: result.count, path: result.path}));
    if (current()) setDialog(undefined);
  }
  async function chooseImport(directory: boolean, current: () => boolean) {
    const chosen = await open(directory ? {directory: true, multiple: false} : {multiple: false, filters: [{name: "Parquet", extensions: ["parquet"]}]});
    if (typeof chosen === "string" && current()) {setPath(chosen); setVariableName("");}
  }
  async function importPackage(id: string, current: () => boolean) {
    operation.current!.cancellable = true;
    const result = await runtime.request<ImportResult>("variable.archive.import", {session_id: sessionId, operation_id: id, path, overwrite, variable_name: /\.parquet$/i.test(path) ? variableName.trim() || undefined : undefined});
    if (current()) {await onImported(result.results, result.variables); setDialog(undefined);}
    onMessage(t("{count} variáveis importadas.", {count: result.count}));
  }
  async function cancel() {
    const current = operation.current;
    if (!current?.cancellable || cancelling) return;
    setCancelling(true);
    try {await runtime.request("result.export_cancel", {session_id: current.sessionId, operation_id: current.id});}
    catch (failure) {setError(errorText(failure)); setCancelling(false);}
  }
  const percent = exportProgressPercent(progress);
  return <div className="variable-archive-actions">
    <button disabled={disabled || busy} onClick={() => begin("export")} title={t("Exportar várias variáveis em Parquet")}><Download size={13}/>{t("Exportar variáveis")}</button>
    <button disabled={disabled || busy} onClick={() => begin("import")} title={t("Importar arquivo ou pasta de variáveis")}><FileUp size={13}/>{t("Importar pacote")}</button>
    {dialog && <DataModal title={t(dialog === "export" ? "Exportar variáveis em Parquet" : "Importar variáveis em Parquet")} onClose={close}>
      <div className="data-form variable-archive-form">
        <p className="data-source"><Archive size={15}/>{t("Pastas compatíveis com o PyQt6 preservam os nomes das variáveis.")}</p>
        {dialog === "export" ? <>
          <div className="variable-archive-selection"><strong>{selected.size} {t("variáveis selecionadas")}</strong><button disabled={busy} onClick={() => setSelected(new Set(inventory?.variables.map(variable => variable.name)))}>{t("Selecionar todas")}</button><button disabled={busy} onClick={() => setSelected(new Set())}>{t("Limpar seleção")}</button></div>
          <label className="variable-archive-search"><Search size={13}/><input aria-label={t("Filtrar variáveis")} placeholder={t("Filtrar variáveis…")} value={query} onChange={event => {setQuery(event.target.value); setLimit(200);}}/></label>
          <div className="variable-archive-list">{filtered.slice(0, limit).map(variable => <label className="variable-archive-entry" key={variable.name}><input type="checkbox" disabled={busy} checked={selected.has(variable.name)} onChange={event => {const checked = event.target.checked; setSelected(previous => {const next = new Set(previous); if (checked) next.add(variable.name); else next.delete(variable.name); return next;});}}/><span><strong>{variable.name}</strong><small>{variable.type} · {variable.row_count.toLocaleString()} {t("linhas")} · {variable.column_count} {t("colunas")}</small></span></label>)}{filtered.length > limit && <button onClick={() => setLimit(value => value + 200)}>{t("Mostrar mais")}</button>}{inventory && !filtered.length && <p className="data-empty">{t(inventory.total ? "Nenhuma variável corresponde ao filtro." : "Execute Python ou SQL para visualizar as variáveis.")}</p>}</div>
          <label>{t("Destino")}<select disabled={busy} value={selected.size === 1 ? kind : "folder"} onChange={event => setKind(event.target.value)}><option value="folder">{t("Pasta com várias variáveis")}</option>{selected.size === 1 && <option value="file">{t("Arquivo Parquet único")}</option>}</select></label>
          <small className="data-source">{t("A pasta recebe um arquivo Parquet por variável e um manifest.json. Os dados são exportados completos, sem o limite da grade.")}</small>
        </> : <>
          <label>{t("Arquivo ou pasta")}<div className="data-path"><input readOnly value={path} placeholder={t("Escolha um arquivo ou uma pasta…")}/><button disabled={busy} onClick={() => void action(async (_, current) => chooseImport(false, current))}><FileUp size={13}/>{t("Arquivo")}</button><button disabled={busy} onClick={() => void action(async (_, current) => chooseImport(true, current))}><FolderOpen size={13}/>{t("Pasta")}</button></div></label>
          {/\.parquet$/i.test(path) && <label>{t("Nome da variável")}<input disabled={busy} value={variableName} onChange={event => setVariableName(event.target.value)} placeholder={t("Usar o nome do arquivo")}/></label>}
        </>}
        <label className="data-check"><input type="checkbox" disabled={busy} checked={overwrite} onChange={event => setOverwrite(event.target.checked)}/>{t(dialog === "export" ? "Substituir arquivos existentes do pacote" : "Substituir variáveis existentes")}</label>
        {busy && <div className="variable-archive-progress" role="status"><LoaderCircle size={14} className="spin"/>{t(cancelling ? "Cancelando…" : progress ? "Processando variáveis…" : "Carregando…")}{progress && <><progress max={100} value={percent} aria-label={t("Progresso do pacote")}/><span>{progress.current}/{progress.total}</span></>}</div>}
        {error && <p className="data-error" role="alert">{error}</p>}
      </div>
      <footer><button disabled={busy} onClick={close}>{t("Fechar")}</button>{busy && operation.current?.cancellable && <button disabled={cancelling} onClick={() => void cancel()}>{t("Cancelar")}</button>}<button className="primary-button" disabled={busy || disabled || (dialog === "export" ? !inventory || !selected.size : !path)} onClick={() => void action(dialog === "export" ? exportPackage : importPackage)}>{t(dialog === "export" ? "Exportar" : "Importar")}</button></footer>
    </DataModal>}
  </div>;
}
