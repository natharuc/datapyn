import { useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { Database, FolderOpen, LoaderCircle, X } from "lucide-react";
import { isDesktop, errorText } from "./runtime";
import type { ConnectionConfig } from "./workspace";

const DRIVERS = [
  { id: "sqlserver", name: "SQL Server", port: 1433 }, { id: "postgresql", name: "PostgreSQL", port: 5432 },
  { id: "mysql", name: "MySQL", port: 3306 }, { id: "mariadb", name: "MariaDB", port: 3306 },
  { id: "sqlite", name: "SQLite", port: 0 }, { id: "databricks", name: "Databricks", port: 443 },
] as const;

interface Props { initial?: ConnectionConfig; onConnect: (config: ConnectionConfig) => Promise<void>; onClose: () => void }
export function ConnectionDialog({ initial, onConnect, onClose }: Props) {
  const [config, setConfig] = useState<ConnectionConfig>(initial ?? {
    db_type: "sqlite", host: "", port: 0, database: ":memory:", username: "", password: "", name: "",
    sqlserver_auth_mode: "sql_password", schema: "", http_path: "", trust_server_certificate: false,
  });
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  function field<K extends keyof ConnectionConfig>(key: K, value: ConnectionConfig[K]) { setConfig((previous) => ({ ...previous, [key]: value })); }
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const connection = { ...config, use_windows_auth: config.sqlserver_auth_mode === "windows" };
      if (!connection.database.trim() && connection.db_type !== "databricks") throw new Error("Informe o banco ou arquivo SQLite.");
      await onConnect(connection); onClose();
    } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  }
  async function chooseSQLite() {
    try {
      if (!isDesktop()) throw new Error("Seleção de arquivos está disponível no aplicativo desktop.");
      const path = await open({ multiple: false, filters: [{ name: "SQLite", extensions: ["db", "sqlite", "sqlite3"] }, { name: "Todos", extensions: ["*"] }] });
      if (typeof path === "string") field("database", path);
    } catch (failure) { setError(errorText(failure)); }
  }
  const server = config.db_type !== "sqlite", windows = config.db_type === "sqlserver" && config.sqlserver_auth_mode !== "sql_password";
  return <div className="modal-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="modal connection-dialog" role="dialog" aria-modal="true" aria-labelledby="connection-title">
      <header className="modal-header"><Database size={18} /><div><h2 id="connection-title">Conectar ao banco</h2><p>Conexão desta sessão</p></div><button className="icon-button" aria-label="Fechar diálogo" onClick={onClose} disabled={busy}><X size={17} /></button></header>
      <form onSubmit={(event) => void submit(event)}>
        <div className="driver-options" role="group" aria-label="Tipo do banco">
          {DRIVERS.map((driver) => <button type="button" className={config.db_type === driver.id ? "selected" : ""} key={driver.id}
            onClick={() => setConfig((previous) => ({ ...previous, db_type: driver.id, port: driver.port, database: driver.id === "sqlite" ? ":memory:" : "", schema: driver.id === "postgresql" ? "public" : "", host: driver.id === "sqlite" ? "" : previous.host || "localhost" }))}>{driver.name}</button>)}
        </div>
        <label className="field">Nome da conexão <input value={config.name ?? ""} onChange={(event) => field("name", event.target.value)} placeholder="Ex.: Análise local" /></label>
        {server && <div className="field-row"><label className="field grow">Servidor <input required value={config.host} onChange={(event) => field("host", event.target.value)} placeholder={config.db_type === "databricks" ? "adb-….azuredatabricks.net" : "localhost"} /></label><label className="field port">Porta <input type="number" min={1} max={65535} required value={config.port} onChange={(event) => field("port", Number(event.target.value))} /></label></div>}
        <label className="field">{config.db_type === "sqlite" ? "Arquivo SQLite ou :memory:" : config.db_type === "databricks" ? "Catalog" : "Banco"}
          <div className="field-input-row"><input value={config.database} onChange={(event) => field("database", event.target.value)} placeholder={config.db_type === "sqlite" ? ":memory:" : "Nome do banco"} />
            {config.db_type === "sqlite" && <button type="button" className="icon-button" title="Escolher arquivo SQLite" onClick={() => void chooseSQLite()}><FolderOpen size={16} /></button>}</div>
        </label>
        {config.db_type === "sqlserver" && <label className="field">Autenticação <select value={config.sqlserver_auth_mode || "sql_password"} onChange={(event) => field("sqlserver_auth_mode", event.target.value)}><option value="sql_password">Usuário e senha SQL</option><option value="windows">Windows integrada</option><option value="entra_mfa">Microsoft Entra MFA</option></select></label>}
        {server && !windows && <div className="field-row"><label className="field grow">{config.db_type === "databricks" ? "Usuário (token)" : "Usuário"}<input autoComplete="username" value={config.username} onChange={(event) => field("username", event.target.value)} placeholder={config.db_type === "databricks" ? "token" : "Usuário"} /></label><label className="field grow">{config.db_type === "databricks" ? "Access token" : "Senha"}<input autoComplete="current-password" type="password" value={config.password ?? ""} onChange={(event) => field("password", event.target.value)} /></label></div>}
        {windows && config.sqlserver_auth_mode === "entra_mfa" && <label className="field">Conta Microsoft (opcional)<input value={config.username} onChange={(event) => field("username", event.target.value)} placeholder="usuario@empresa.com" /></label>}
        {["postgresql", "databricks"].includes(config.db_type) && <label className="field">Schema <input value={config.schema ?? ""} onChange={(event) => field("schema", event.target.value)} placeholder={config.db_type === "postgresql" ? "public" : "default"} /></label>}
        {config.db_type === "databricks" && <label className="field">HTTP path <input required value={config.http_path ?? ""} onChange={(event) => field("http_path", event.target.value)} placeholder="/sql/1.0/warehouses/…" /></label>}
        {config.db_type === "sqlserver" && <label className="checkbox-field"><input type="checkbox" checked={!!config.trust_server_certificate} onChange={(event) => field("trust_server_certificate", event.target.checked)} /> Confiar no certificado do servidor</label>}
        <p className="field-note">A senha é usada para conectar e não é salva no rascunho da interface.</p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <footer className="modal-footer"><button type="button" className="secondary-button" onClick={onClose} disabled={busy}>Cancelar</button><button type="submit" className="primary-button" disabled={busy}>{busy ? <LoaderCircle size={15} className="spin" /> : <Database size={15} />}{busy ? "Conectando…" : "Conectar"}</button></footer>
      </form>
    </section>
  </div>;
}
