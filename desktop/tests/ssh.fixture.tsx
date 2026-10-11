import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { ConnectionDialog } from "../src/ConnectionDialog";
import { SshHostTrustDialog } from "../src/SshHostTrustDialog";
import { ConnectionsController, type ConnectionCatalog } from "../src/connections";
import { createRuntimeRequester, runtime } from "../src/runtime";
import { sshHostTrust } from "../src/sshHostTrust";
import type { ConnectionConfig } from "../src/workspace";
import "../src/styles.css";

const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
const trusted = new Set<string>();
let holdTests = false;
const pendingTests = new Map<string, (error: unknown) => void>();
const catalog: ConnectionCatalog = { version: 1, groups: [], connections: [] };
const requester = createRuntimeRequester(async <T,>(method: string, params: Record<string, unknown>): Promise<T> => {
  calls.push({ method, params });
  if (method === "ssh.host_key.trust") { trusted.add((params.details as { host: string }).host); return {} as T; }
  if (method === "connection.test") {
    const config = params.config as ConnectionConfig;
    if (config.ssh?.enabled && config.ssh.auth_method === "private_key" && !config.ssh.passphrase && params.connection_id !== "saved") throw new Error("Saved SSH passphrase lookup missing");
    if (config.ssh?.enabled && !trusted.has(config.ssh.host)) throw { code: "ssh_host_key_unknown", message: "Servidor SSH ainda não confirmado.", details: { host: config.ssh.host, port: config.ssh.port, key_type: "ssh-ed25519", public_key: "YWJj", fingerprint: "SHA256:" + "a".repeat(43) } };
    if (holdTests) return await new Promise<T>((_resolve, reject) => pendingTests.set(String(params.test_id), reject));
    return { success: true, message: "Conexão SSH e banco testados com sucesso." } as T;
  }
  if (method === "connection.test_cancel") { pendingTests.get(String(params.test_id))?.({ code: "cancelled", message: "Teste cancelado." }); pendingTests.delete(String(params.test_id)); return {} as T; }
  if (method === "connections.list") return catalog as T;
  if (method === "connections.save") return { ...(params.connection as object), has_ssh_password: Boolean(params.ssh_password), has_ssh_passphrase: Boolean(params.ssh_passphrase) } as T;
  throw new Error("Unsupported SSH fixture request");
});
runtime.request = requester.request;
const controller = new ConnectionsController(runtime);
Object.assign(window, { isTauri: true, __TAURI_INTERNALS__: { invoke: async (command: string) => {
  if (command === "plugin:dialog|open") return "/keys/id_ed25519";
  throw new Error("Unsupported SSH fixture native call");
} }, __SSH_TEST__: { calls, trusted, resetTrust: () => trusted.clear(), cancel: () => requester.cancel(), holdTests: () => { holdTests = true; }, get pendingTestCount() { return pendingTests.size; }, get challenge() { return sshHostTrust.getSnapshot(); } } });

function Fixture() {
  const [open, setOpen] = useState(true), [initial, setInitial] = useState<ConnectionConfig>();
  Object.assign(window, { __SSH_OPEN_EDIT__: () => { setInitial({ db_type: "postgresql", name: "DocFis", host: "pg.internal", port: 5432, database: "docfis", username: "app", sslmode: "verify-full", sslrootcert: "/certs/ca.pem", ssh: { enabled: true, host: "vps.example", port: 22, username: "deploy", auth_method: "private_key", private_key_path: "/keys/id_ed25519" } }); setOpen(true); }, __SSH_CLOSE__: () => setOpen(false) });
  return <><button onClick={() => { setInitial(undefined); setOpen(true); }}>New</button>
    {open && <ConnectionDialog mode="save" initial={initial} connectionId={initial ? "saved" : undefined} hasSshPassphrase={Boolean(initial)} onClose={() => setOpen(false)} onConnect={async (config, metadata) => { await controller.save({ id: initial ? "saved" : undefined, name: config.name!, config }, config.password, metadata?.save_password, metadata?.save_ssh_credentials); }} />}
    <SshHostTrustDialog />
  </>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
