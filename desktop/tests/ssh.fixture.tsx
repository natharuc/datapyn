import React, { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { ConnectionDialog } from "../src/ConnectionDialog";
import { SettingsDialog } from "../src/SettingsDialog";
import { SshHostTrustDialog } from "../src/SshHostTrustDialog";
import { connections, type ConnectionCatalog, type SavedConnection } from "../src/connections";
import { DEFAULT_PREFERENCES } from "../src/preferences";
import { DEFAULT_SHORTCUTS } from "../src/shortcuts";
import { createRuntimeRequester, runtime } from "../src/runtime";
import { sshHostTrust } from "../src/sshHostTrust";
import type { SavedSshTunnel } from "../src/sshTunnels";
import type { ConnectionConfig, SshConnectionOptions } from "../src/workspace";
import { hasLocalShortcutDialog, hasVisibleShortcutDialog } from "../src/shortcutModalGuard";
import "../src/styles.css";

const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
const trusted = new Set<string>(), privateSecrets = new Map<string, { identity: string; password?: string; passphrase?: string }>();
let holdTests = false, holdSaves = false, counter = 0, connectionCounter = 0, platform = "windows";
const pendingTests = new Map<string, (error: unknown) => void>();
const pendingSaves: Array<() => void> = [];
const catalog: ConnectionCatalog = { version: 2, groups: [], connections: [], ssh_tunnels: [] };
const identity = (config: SshConnectionOptions) => JSON.stringify([config.host, config.port, config.username, config.auth_method, config.private_key_path]);
const publicTunnel = (value: SavedSshTunnel) => ({ ...value, config: { ...value.config } });
const publicCatalog = () => ({ ...catalog, groups: [...catalog.groups], connections: catalog.connections.map(item => ({ ...item, config: { ...item.config } })), ssh_tunnels: catalog.ssh_tunnels!.map(publicTunnel) });
function sshConfig(params: Record<string, unknown>, tunnelTest: boolean) {
  const config = params.config as SshConnectionOptions | ConnectionConfig;
  const id = tunnelTest ? params.tunnel_id : (config as ConnectionConfig).ssh_tunnel_id;
  const saved = catalog.ssh_tunnels!.find(item => item.id === id);
  if (!tunnelTest && id && !saved) throw new Error("Túnel SSH indisponível");
  const ssh = tunnelTest ? config as SshConnectionOptions : saved?.config;
  if (!ssh) return;
  const secrets = saved ? privateSecrets.get(saved.id) : undefined;
  const bound = secrets?.identity === identity(ssh) ? secrets : undefined;
  if (ssh.auth_method === "private_key" && !ssh.passphrase && !bound?.passphrase) throw new Error("Passphrase SSH ausente");
  if (ssh.auth_method === "password" && !ssh.password && !bound?.password) throw new Error("Senha SSH ausente");
  return ssh;
}
const requester = createRuntimeRequester(async <T,>(method: string, params: Record<string, unknown>): Promise<T> => {
  calls.push({ method, params });
  if (method === "ssh.host_key.trust") { trusted.add((params.details as { host: string }).host); return {} as T; }
  if (method === "ssh.tunnels.test" || method === "connection.test") {
    const ssh = sshConfig(params, method === "ssh.tunnels.test");
    if (ssh && !trusted.has(ssh.host)) throw { code: "ssh_host_key_unknown", message: "Servidor SSH ainda não confirmado.", details: { host: ssh.host, port: ssh.port, key_type: "ssh-ed25519", public_key: "YWJj", fingerprint: "SHA256:" + "a".repeat(43) } };
    if (holdTests) return await new Promise<T>((_resolve, reject) => pendingTests.set(String(params.test_id), reject));
    return { success: true, message: method === "ssh.tunnels.test" ? "Conexão SSH testada com sucesso." : ssh ? "Conexão SSH e banco testados com sucesso." : "Conexão testada com sucesso." } as T;
  }
  if (method === "connection.test_cancel") { pendingTests.get(String(params.test_id))?.({ code: "cancelled", message: "Teste cancelado." }); pendingTests.delete(String(params.test_id)); return {} as T; }
  if (method === "connections.list") return publicCatalog() as T;
  if (method === "ssh.tunnels.list") return { tunnels: catalog.ssh_tunnels!.map(publicTunnel) } as T;
  if (method === "ssh.tunnels.save") {
    if (holdSaves) await new Promise<void>(resolve => pendingSaves.push(resolve));
    const draft = params.tunnel as SavedSshTunnel;
    if (draft.config.password || draft.config.passphrase) throw new Error("Tunnel secret leaked into public config");
    const id = draft.id || `tunnel-${++counter}`, previous = privateSecrets.get(id);
    const same = previous?.identity === identity(draft.config);
    privateSecrets.set(id, { identity: identity(draft.config), password: String(params.password || (same ? previous.password || "" : "")), passphrase: String(params.passphrase || (same ? previous.passphrase || "" : "")) });
    const stored = privateSecrets.get(id)!, value = { ...draft, id, has_password: Boolean(stored.password), has_passphrase: Boolean(stored.passphrase) };
    catalog.ssh_tunnels = [...catalog.ssh_tunnels!.filter(item => item.id !== id), value];
    return publicTunnel(value) as T;
  }
  if (method === "ssh.tunnels.delete") {
    if (catalog.connections.some(item => item.config.ssh_tunnel_id === params.tunnel_id)) throw new Error("O túnel SSH está em uso por conexões. Remova as referências antes de excluí-lo.");
    catalog.ssh_tunnels = catalog.ssh_tunnels!.filter(item => item.id !== params.tunnel_id); privateSecrets.delete(String(params.tunnel_id)); return {} as T;
  }
  if (method === "connections.save") {
    const draft = params.connection as SavedConnection;
    if (draft.config.ssh || draft.config.password) throw new Error("Connection config contains SSH details or database password");
    const value = { group_id: null, color: "", favorite: false, order: 0, ...draft, id: draft.id || `connection-${++connectionCounter}`, has_password: Boolean(params.password && params.save_password) };
    catalog.connections = [...catalog.connections.filter(item => item.id !== value.id), value]; return { ...value, config: { ...value.config } } as T;
  }
  if (method === "system.info") return { platform, capabilities: { sqlserver_authentication: { platform, modes: ["sql_password", ...(platform === "windows" ? ["windows"] : []), "ntlm", "kerberos", "entra_mfa"], kerberos_available: true, network_tls_ca_field: "ssl_ca" } } } as T;
  throw new Error(`Unsupported SSH fixture request: ${method}`);
});
runtime.request = requester.request;
Object.assign(window, { isTauri: true, __TAURI_INTERNALS__: { invoke: async (command: string) => {
  if (command === "plugin:dialog|open") return "/keys/id_ed25519";
  throw new Error(`Unsupported SSH fixture native call: ${command}`);
} }, __SSH_TEST__: { calls, trusted, publicCatalog, resetTrust: () => trusted.clear(), cancel: () => requester.cancel(),
  setPlatform: (value: string) => { platform = value; }, holdTests: () => { holdTests = true; }, releaseTests: () => { holdTests = false; }, holdSaves: () => { holdSaves = true; }, releaseSaves: () => { holdSaves = false; pendingSaves.splice(0).forEach(resolve => resolve()); }, get pendingSaveCount() { return pendingSaves.length; }, get pendingTestCount() { return pendingTests.size; }, get challenge() { return sshHostTrust.getSnapshot(); },
} });

function Fixture() {
  const [connectionOpen, setConnectionOpen] = useState(false), [settingsOpen, setSettingsOpen] = useState(false), [initialTab, setInitialTab] = useState("appearance"), [editing, setEditing] = useState<string>(), [draft, setDraft] = useState<ConnectionConfig>();
  const [legacyOpen, setLegacyOpen] = useState(false), hosts = useRef(new Set<Window>([window])), capture = useRef<(event: KeyboardEvent) => void>();
  const snapshot = useSyncExternalStore(connections.subscribe, connections.getSnapshot), saved = snapshot.catalog.connections.find(item => item.id === editing);
  const manage = () => { setInitialTab("ssh"); setSettingsOpen(true); };
  useEffect(() => {
    // Match App's capture path, including legacy dialogs without a local Modal handler.
    const handle = (event: KeyboardEvent) => {
      const owner = (event.target as Node | null)?.ownerDocument ?? document;
      if (owner.activeElement?.closest('[role="menu"]')) return;
      if (connectionOpen || settingsOpen || legacyOpen || hasVisibleShortcutDialog(document) || (owner !== document && hasVisibleShortcutDialog(owner))) {
        if (event.key === "Escape" && !hasLocalShortcutDialog(owner) && !connectionOpen) { event.preventDefault(); setLegacyOpen(false); }
      }
    };
    capture.current = handle; hosts.current.forEach(host => host.addEventListener("keydown", handle, true));
    return () => { hosts.current.forEach(host => host.removeEventListener("keydown", handle, true)); if (capture.current === handle) capture.current = undefined; };
  }, [connectionOpen, settingsOpen, legacyOpen]);
  Object.assign(window, { __SSH_ATTACH_WINDOW__: (host: Window) => { hosts.current.add(host); if (capture.current) host.addEventListener("keydown", capture.current, true); }, __SSH_OPEN_LEGACY__: () => setLegacyOpen(true), __SSH_OPEN_EDIT__: (id: string) => { setDraft(undefined); setEditing(id); setConnectionOpen(true); }, __SSH_OPEN_CONFIG__: (config: ConnectionConfig) => { setEditing(undefined); setDraft(config); setConnectionOpen(true); }, __SSH_CLOSE__: () => { setSettingsOpen(false); setConnectionOpen(false); } });
  return <><button onClick={() => { setInitialTab("appearance"); setSettingsOpen(true); }}>Configurações</button><button onClick={() => { setEditing(undefined); setDraft(undefined); setConnectionOpen(true); }}>Nova conexão</button>
    {connectionOpen && <ConnectionDialog mode="save" initial={saved?.config ?? draft} connectionId={saved?.id} hasPassword={saved?.has_password} tunnels={snapshot.catalog.ssh_tunnels} onManageTunnels={manage} onClose={() => setConnectionOpen(false)}
      onConnect={async (config, metadata) => { await connections.save({ id: saved?.id, name: config.name!, config }, config.password, metadata?.save_password, metadata?.save_ssh_credentials); }} />}
    {settingsOpen && <SettingsDialog initialTab={initialTab} preferences={DEFAULT_PREFERENCES} shortcuts={DEFAULT_SHORTCUTS} onSave={async () => {}} onClose={() => setSettingsOpen(false)} />}
    <SshHostTrustDialog />
    {legacyOpen && <section id="legacy-confirm" role="dialog" aria-modal="true">Legacy confirmation</section>}
  </>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
