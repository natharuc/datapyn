import { translate as t, useLocale } from "./i18n";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Download, LoaderCircle, Package, Plus, RefreshCw, Search, Settings2, Trash2, X } from "lucide-react";
import { runtime, errorText } from "./runtime";
import { Modal } from "./PanelControls";
import "./packages.css";

export interface PackageInfo { name: string; version?: string; latest_version?: string; summary?: string; author?: string; installed?: boolean }
export interface PackageSource { id?: string; url: string; username?: string; password?: string; has_password?: boolean }
interface PackageList { packages: PackageInfo[]; environment?: { path: string; python: string; ready: boolean }; sources?: PackageSource[] }
interface OperationResult { success: boolean; message?: string; error?: string; operation_id?: string }
export function PackageManagerDialog({ onClose, onChanged, onError }: { onClose: () => void; onChanged?: () => void; onError?: (message: string) => void }) {
  useLocale();
  const [packages, setPackages] = useState<PackageInfo[]>([]), [searchResults, setSearchResults] = useState<PackageInfo[]>([]), [query, setQuery] = useState(""), [tab, setTab] = useState<"installed" | "search">("installed");
  const [loading, setLoading] = useState(false), [operation, setOperation] = useState<string>(), [message, setMessage] = useState(""), [error, setError] = useState(""), [environment, setEnvironment] = useState("");
  const [sourcesOpen, setSourcesOpen] = useState(false), [remove, setRemove] = useState<PackageInfo>(), [version, setVersion] = useState("");
  const [scroll, setScroll] = useState(0), revision = useRef(0);
  const load = useCallback(async () => {
    const generation = ++revision.current; setLoading(true); setError("");
    try { const result = await runtime.request<PackageList>("packages.list"); if (generation !== revision.current) return; setPackages(result.packages); setEnvironment(result.environment?.path ?? ""); }
    catch (failure) { if (generation === revision.current) setError(errorText(failure)); }
    finally { if (generation === revision.current) setLoading(false); }
  }, []);
  useEffect(() => { void load(); return () => { ++revision.current; }; }, [load]);
  async function search() {
    if (!query.trim()) return; const generation = ++revision.current; setLoading(true); setError(""); setTab("search");
    try { const result = await runtime.request<PackageInfo[] | { packages: PackageInfo[] }>("packages.search", { query: query.trim() }); if (generation === revision.current) setSearchResults(Array.isArray(result) ? result : result.packages); }
    catch (failure) { if (generation === revision.current) setError(errorText(failure)); } finally { if (generation === revision.current) setLoading(false); }
  }
  async function mutate(method: "install" | "update" | "uninstall", info: PackageInfo) {
    setOperation(info.name); setError(""); setMessage(""); setRemove(undefined);
    try {
      const result = await runtime.request<OperationResult>(`packages.${method}`, { name: info.name, version: method === "install" ? version.trim() : undefined });
      if (!result.success) throw new Error(result.error || result.message || t("A operação não foi concluída."));
      setMessage(result.message || `${info.name}: operação concluída.`); await load(); onChanged?.();
    } catch (failure) { const text = errorText(failure); setError(text); onError?.(text); } finally { setOperation(undefined); }
  }
  const list = useMemo(() => tab === "search" ? searchResults.map((item) => ({ ...item, installed: packages.some((entry) => entry.name.toLowerCase() === item.name.toLowerCase()), version: packages.find((entry) => entry.name.toLowerCase() === item.name.toLowerCase())?.version ?? item.version })) : packages.filter((item) => item.name.toLowerCase().includes(query.toLowerCase())), [tab, searchResults, packages, query]);
  const first = Math.max(0, Math.floor(scroll / 45) - 4), last = Math.min(list.length, first + 24);
  return <Modal title={t("Pacotes Python")} className="package-manager" onClose={() => { if (!operation) onClose(); }}><div className="package-manager-top"><p>{t("Instale bibliotecas no ambiente Python usado pelo DataPyn.")}</p>{environment && <code title={environment}>{environment}</code>}<div className="package-search"><Search size={15} /><input aria-label={t("Buscar pacote Python")} value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void search(); }} placeholder={t("Nome do pacote no PyPI ou fonte privada")} /><button className="secondary-button" disabled={loading || !!operation || !query.trim()} onClick={() => void search()}>{t("Buscar")}</button><button className="icon-button" title={t("Atualizar lista")} aria-label={t("Atualizar lista")} disabled={loading || !!operation} onClick={() => void load()}><RefreshCw size={15} /></button><button className="icon-button" title={t("Fontes de pacotes")} aria-label={t("Fontes de pacotes")} disabled={!!operation} onClick={() => setSourcesOpen(true)}><Settings2 size={15} /></button></div><div className="package-tabs"><button className={tab === "installed" ? "selected" : ""} onClick={() => setTab("installed")}>{t("Instalados (")}{packages.length})</button><button className={tab === "search" ? "selected" : ""} onClick={() => setTab("search")}>{t("Busca (")}{searchResults.length})</button>{tab === "search" && <label>{t("Versão")} <input aria-label={t("Versão a instalar (opcional)")} value={version} onChange={(event) => setVersion(event.target.value)} placeholder={t("Mais recente")} /></label>}</div></div>
    {error && <p role="alert" className="package-error">{t(error)}</p>}{message && <p role="status" className="package-success">{message}</p>}{operation && <p className="package-progress"><LoaderCircle size={15} className="spin" /> {t("Operação em andamento:")} {operation}{t("…")}</p>}
    <div className="package-list" onScroll={(event) => setScroll(event.currentTarget.scrollTop)}><div style={{ position: "relative", height: list.length * 45 }}>{list.slice(first, last).map((info, index) => <div className="package-row" key={info.name} style={{ position: "absolute", top: (first + index) * 45, height: 45 }}><Package size={17} /><div><strong>{info.name}</strong><small title={info.summary}>{info.summary || info.author || ""}</small></div><code>{info.version || info.latest_version}</code>{info.installed || tab === "installed" ? <><button className="icon-button" disabled={!!operation} title={`Atualizar ${info.name}`} aria-label={`Atualizar ${info.name}`} onClick={() => void mutate("update", info)}><RefreshCw size={15} /></button><button className="icon-button" disabled={!!operation} title={`Desinstalar ${info.name}`} aria-label={`Desinstalar ${info.name}`} onClick={() => setRemove(info)}><Trash2 size={15} /></button></> : <button className="secondary-button" disabled={!!operation} onClick={() => void mutate("install", info)}><Download size={14} />{t("Instalar")}</button>}</div>)}</div>{loading && <p className="package-progress"><LoaderCircle size={15} className="spin" />{t("Carregando…")}</p>}{!loading && !list.length && <p className="package-progress">{tab === "search" ? t("Pesquise pelo nome de um pacote para consultar as versões disponíveis.") : t("Nenhum pacote corresponde ao filtro.")}</p>}</div>
    <footer className="modal-footer"><span className="field-note">{t("Pacotes já importados podem exigir uma nova sessão Python.")}</span><button className="primary-button" disabled={!!operation} onClick={onClose}>{t("Fechar")}</button></footer>
    {sourcesOpen && <PackageSourcesDialog onClose={() => setSourcesOpen(false)} onError={setError} />}
    {remove && <Modal title={t("Desinstalar pacote")} onClose={() => setRemove(undefined)}><p className="catalog-modal-copy">{t("Desinstalar “")}{remove.name}{t("” do ambiente DataPyn? Outras bibliotecas podem depender dele.")}</p><footer className="modal-footer"><button className="secondary-button" onClick={() => setRemove(undefined)}>{t("Cancelar")}</button><button className="primary-button" onClick={() => void mutate("uninstall", remove)}>{t("Desinstalar")}</button></footer></Modal>}
  </Modal>;
}

function PackageSourcesDialog({ onClose, onError }: { onClose: () => void; onError: (message: string) => void }) {
  useLocale();
  const [sources, setSources] = useState<PackageSource[]>([]), [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { let active = true; void runtime.request<PackageSource[]>("packages.sources").then((result) => { if (active) setSources(result); }, (failure) => { if (active) setError(errorText(failure)); }); return () => { active = false; }; }, []);
  function field(index: number, key: keyof PackageSource, value: string) { setSources((previous) => previous.map((source, i) => i === index ? { ...source, [key]: value } : source)); }
  async function saveSources() {
    setBusy(true); setError("");
    try { await runtime.request("packages.sources", { sources: sources.map((source) => ({ ...source, password: source.password || undefined, save_password: source.has_password || !!source.password })) }); onClose(); } catch (failure) { const text = errorText(failure); setError(text); onError(text); } finally { setBusy(false); }
  }
  return <Modal title={t("Fontes de pacotes")} className="package-sources" onClose={() => { if (!busy) onClose(); }}><p className="catalog-modal-copy">{t("PyPI é a fonte padrão. Adicione URLs de índices privados e, se necessário, as credenciais.")}</p><div className="package-source-list">{sources.map((source, index) => <div className="package-source" key={source.id ?? index}><label className="field">{t("URL do índice")}<input type="url" value={source.url} placeholder="https://…/simple" onChange={(event) => field(index, "url", event.target.value)} /></label><div className="field-row"><label className="field grow">{t("Usuário")}<input value={source.username ?? ""} onChange={(event) => field(index, "username", event.target.value)} /></label><label className="field grow">{t("Senha/token")}<input type="password" value={source.password ?? ""} placeholder={source.has_password ? t("Senha salva (deixe em branco para manter)") : t("Opcional")} onChange={(event) => field(index, "password", event.target.value)} /></label><button className="icon-button" title={t("Remover fonte")} aria-label={t("Remover fonte")} onClick={() => setSources((previous) => previous.filter((_, i) => i !== index))}><X size={15} /></button></div></div>)}<button className="secondary-button" onClick={() => setSources((previous) => [...previous, { url: "", username: "", password: "" }])}><Plus size={15} />{t("Adicionar fonte")}</button></div>{error && <p className="package-error">{t(error)}</p>}<footer className="modal-footer"><button className="secondary-button" disabled={busy} onClick={onClose}>{t("Cancelar")}</button><button className="primary-button" disabled={busy} onClick={() => void saveSources()}>{t("Salvar fontes")}</button></footer></Modal>;
}
