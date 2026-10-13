import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { FolderOpen, LoaderCircle, Pencil, Plus, Trash2 } from "lucide-react";
import { open } from "@tauri-apps/plugin-dialog";
import { connections, type ConnectionsController } from "./connections";
import { localizedSearch, useTranslation } from "./i18n";
import { Modal } from "./PanelControls";
import { errorText, isDesktop, runtime } from "./runtime";
import { saveSshTunnel, type SavedSshTunnel } from "./sshTunnels";
import type { SshConnectionOptions } from "./workspace";
import "./sshTunnels.css";

export function SshTunnelsSettings({ controller = connections, query = "" }: { controller?: ConnectionsController; query?: string }) {
  const { t } = useTranslation();
  const snapshot = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  const [editing, setEditing] = useState<SavedSshTunnel | "new">();
  const [deleting, setDeleting] = useState<SavedSshTunnel>();
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { void controller.ensureLoaded(); }, [controller]);
  const tunnels = (snapshot.catalog.ssh_tunnels ?? []).filter(item => localizedSearch(query, item.name, item.config.host, item.config.username, "Túneis SSH"));
  if (query && !tunnels.length && !localizedSearch(query, "Túneis SSH")) return null;
  return <section className="ssh-tunnels-settings" aria-label={t("Túneis SSH")}>
    <div className="ssh-tunnels-toolbar"><strong>{t("Túneis SSH")}</strong><button className="secondary-button" disabled={snapshot.loading} onClick={() => { setError(""); setEditing("new"); }}><Plus size={14} />{t("Novo túnel")}</button></div>
    {(error || snapshot.error) && <p role="alert" className="form-error">{error || snapshot.error}</p>}
    {snapshot.loading && <p role="status" className="ssh-tunnel-status"><LoaderCircle size={14} className="spin" />{t("Carregando…")}</p>}
    {!snapshot.loading && !tunnels.length && <p className="form-hint">{query ? t("Nenhum túnel encontrado.") : t("Nenhum túnel cadastrado.")}</p>}
    <ul className="ssh-tunnel-list">{tunnels.map(item => <li key={item.id}>
      <div><strong>{item.name}</strong><small>{item.config.username}@{item.config.host}:{item.config.port}</small></div>
      <span className="ssh-tunnel-auth">{item.config.auth_method === "private_key" ? t("Chave privada") : t("Senha")}</span>
      <button className="icon-button" title={t("Editar túnel {name}", { name: item.name })} aria-label={t("Editar túnel {name}", { name: item.name })} onClick={() => { setError(""); setEditing(item); }}><Pencil size={14} /></button>
      <button className="icon-button" title={t("Excluir túnel {name}", { name: item.name })} aria-label={t("Excluir túnel {name}", { name: item.name })} onClick={() => { setError(""); setDeleting(item); }}><Trash2 size={14} /></button>
    </li>)}</ul>
    {editing && <SshTunnelDialog initial={editing === "new" ? undefined : editing} onClose={() => setEditing(undefined)} onSave={(name, config) => saveSshTunnel(controller, name, config, editing === "new" ? undefined : editing.id)} />}
    {deleting && <Modal title={t("Excluir túnel SSH")} onClose={() => { if (!busy) setDeleting(undefined); }}><p className="catalog-modal-copy">{t("Excluir “{name}”?", { name: deleting.name })}</p>{error && <p role="alert" className="form-error ssh-tunnel-delete-error">{error}</p>}<footer className="modal-footer"><button className="secondary-button" disabled={busy} onClick={() => setDeleting(undefined)}>{t("Cancelar")}</button><button className="primary-button" disabled={busy} onClick={async () => { setBusy(true); setError(""); try { await controller.mutate("ssh.tunnels.delete", { tunnel_id: deleting.id }); setDeleting(undefined); } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); } }}>{t("Excluir")}</button></footer></Modal>}
  </section>;
}

export function SshTunnelDialog({ initial, onClose, onSave }: { initial?: SavedSshTunnel; onClose: () => void; onSave: (name: string, config: SshConnectionOptions) => Promise<unknown> }) {
  const { t } = useTranslation();
  const [name, setName] = useState(initial?.name ?? "");
  const [config, setConfig] = useState<SshConnectionOptions>(initial ? { ...initial.config, password: "", passphrase: "" } : { enabled: true, host: "", port: 22, username: "", auth_method: "password" });
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [message, setMessage] = useState("");
  const mounted = useRef(true), testId = useRef<string>();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; if (testId.current) void runtime.request("connection.test_cancel", { test_id: testId.current }).catch(() => {}); }; }, []);
  const field = <K extends keyof SshConnectionOptions>(key: K, value: SshConnectionOptions[K]) => { setConfig(previous => ({ ...previous, [key]: value })); setMessage(""); };
  const sameIdentity = initial && initial.config.host === config.host && initial.config.port === config.port && initial.config.username === config.username && initial.config.auth_method === config.auth_method && initial.config.private_key_path === config.private_key_path;
  function validated(): SshConnectionOptions {
    if (!config.host.trim() || !config.username.trim()) throw new Error(t("Informe o servidor e o usuário SSH."));
    if (!Number.isInteger(config.port) || config.port < 1 || config.port > 65535) throw new Error(t("Informe uma porta SSH entre 1 e 65535."));
    if (config.auth_method === "private_key" && !config.private_key_path?.trim()) throw new Error(t("Escolha a chave privada SSH."));
    return { ...config, enabled: true, host: config.host.trim(), username: config.username.trim() };
  }
  function cancelTest() { const id = testId.current; testId.current = undefined; if (id) void runtime.request("connection.test_cancel", { test_id: id }).catch(() => {}); setBusy(false); }
  function close() { if (testId.current) { cancelTest(); onClose(); } else if (!busy) onClose(); }
  async function test() {
    const id = crypto.randomUUID(); testId.current = id; setBusy(true); setError(""); setMessage("");
    try { const result = await runtime.request<{ success: boolean; message?: string }>("ssh.tunnels.test", { test_id: id, tunnel_id: initial?.id, config: validated() }); if (!mounted.current || testId.current !== id) return; if (!result.success) throw new Error(result.message ?? t("A conexão SSH não foi estabelecida.")); setMessage(result.message ?? t("Conexão SSH testada com sucesso.")); }
    catch (failure) { if (mounted.current && testId.current === id) setError(errorText(failure)); }
    finally { if (mounted.current && testId.current === id) { testId.current = undefined; setBusy(false); } }
  }
  return <Modal title={initial ? t("Editar túnel SSH") : t("Novo túnel SSH")} className="connection-dialog ssh-tunnel-dialog" onClose={close}><form onSubmit={async event => { event.preventDefault(); setBusy(true); setError(""); try { if (!name.trim()) throw new Error(t("Informe o nome do túnel.")); await onSave(name, validated()); onClose(); } catch (failure) { if (mounted.current) setError(errorText(failure)); } finally { if (mounted.current) setBusy(false); } }}>
    <fieldset className="connection-fields" disabled={busy}>
      <label className="field">{t("Nome")}<input required autoFocus value={name} onChange={event => setName(event.target.value)} /></label>
      <div className="field-row"><label className="field grow">{t("Servidor SSH")}<input required autoComplete="off" value={config.host} onChange={event => field("host", event.target.value)} placeholder="ssh.example.com" /></label><label className="field port">{t("Porta SSH")}<input required type="number" min={1} max={65535} value={config.port} onChange={event => field("port", Number(event.target.value))} /></label></div>
      <label className="field">{t("Usuário SSH")}<input required autoComplete="off" value={config.username} onChange={event => field("username", event.target.value)} /></label>
      <label className="field">{t("Autenticação SSH")}<select value={config.auth_method} onChange={event => setConfig(previous => ({ ...previous, auth_method: event.target.value as SshConnectionOptions["auth_method"], password: "", passphrase: "" }))}><option value="password">{t("Senha")}</option><option value="private_key">{t("Chave privada")}</option></select></label>
      {config.auth_method === "password" ? <label className="field">{t("Senha SSH")}<input type="password" autoComplete="new-password" value={config.password ?? ""} placeholder={sameIdentity && initial.has_password ? t("Deixe em branco para manter a senha salva") : undefined} onChange={event => field("password", event.target.value)} /></label> : <>
        <label className="field">{t("Chave privada SSH")}<div className="field-input-row"><input required autoComplete="off" value={config.private_key_path ?? ""} onChange={event => field("private_key_path", event.target.value)} /><button type="button" className="icon-button" title={t("Escolher chave privada SSH")} aria-label={t("Escolher chave privada SSH")} onClick={async () => { try { if (!isDesktop()) throw new Error(t("Seleção de arquivos está disponível no aplicativo desktop.")); const path = await open({ multiple: false, title: t("Escolher chave privada SSH") }); if (typeof path === "string") field("private_key_path", path); } catch (failure) { setError(errorText(failure)); } }}><FolderOpen size={16} /></button></div></label>
        <label className="field">{t("Passphrase (opcional)")}<input type="password" autoComplete="new-password" value={config.passphrase ?? ""} placeholder={sameIdentity && initial.has_passphrase ? t("Deixe em branco para manter a passphrase salva") : undefined} onChange={event => field("passphrase", event.target.value)} /></label>
      </>}
      <p className="connection-ssh-note">{t("A senha SSH e a passphrase são salvas no armazenamento seguro do sistema.")}</p>
    </fieldset>
    {error && <p role="alert" className="form-error">{error}</p>}{message && <p role="status" className="connection-test-success">{message}</p>}
    <footer className="modal-footer"><button type="button" className="secondary-button" disabled={busy && !testId.current} onClick={() => testId.current ? cancelTest() : void test()}>{testId.current ? <LoaderCircle size={14} className="spin" /> : null}{testId.current ? t("Cancelar teste") : t("Testar túnel")}</button><span className="toolbar-spacer" /><button type="button" className="secondary-button" onClick={close}>{t("Cancelar")}</button><button type="submit" className="primary-button" disabled={busy}>{t("Salvar")}</button></footer>
  </form></Modal>;
}
