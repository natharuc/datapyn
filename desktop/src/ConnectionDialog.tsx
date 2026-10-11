import { translate as t, useLocale } from "./i18n";
import { useEffect, useRef, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { FolderOpen, LoaderCircle } from "lucide-react";
import { isDesktop, errorText, runtime } from "./runtime";
import type { ConnectionConfig } from "./workspace";
import { groupHierarchy, type ConnectionGroup } from "./connections";
import { parseConnectionString } from "./connectionStrings";
import { Modal } from "./PanelControls";
import "./connections.css";

const DRIVERS = [
  { id: "sqlserver", name: t("SQL Server"), port: 1433 }, { id: "postgresql", name: t("PostgreSQL"), port: 5432 },
  { id: "mysql", name: t("MySQL"), port: 3306 }, { id: "mariadb", name: t("MariaDB"), port: 3306 },
  { id: "sqlite", name: "SQLite", port: 0 }, { id: "databricks", name: t("Databricks"), port: 443 },
] as const;

interface Props {
  initial?: ConnectionConfig; onConnect: (config: ConnectionConfig, metadata?: { group_id: string | null; color: string; save_password: boolean; save_ssh_credentials: boolean; use_saved_database_password: boolean }) => Promise<void>; onClose: () => void;
  mode?: "connect" | "save"; groups?: ConnectionGroup[]; initialGroupId?: string | null; initialColor?: string; hasPassword?: boolean; hasSshPassword?: boolean; hasSshPassphrase?: boolean; connectionId?:string;
}
export function ConnectionDialog({ initial, onConnect, onClose, mode = "connect", groups = [], initialGroupId = null, initialColor = "", hasPassword = false,hasSshPassword = false,hasSshPassphrase = false,connectionId }: Props) {
  useLocale();
  const [config, setConfig] = useState<ConnectionConfig>(initial ?? {
    db_type: "sqlite", host: "", port: 0, database: ":memory:", username: "", password: "", name: "",
    sqlserver_auth_mode: "sql_password", schema: "", http_path: "", trust_server_certificate: false,
  });
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [stringInput, setStringInput] = useState(""), importedString = useRef(false);
  const [databricksAuth,setDatabricksAuth]=useState<"oauth"|"token">((initial as ConnectionConfig&{databricks_auth_mode?:string})?.databricks_auth_mode==="oauth"?"oauth":initial?.password||hasPassword?"token":"oauth");
  const [groupId, setGroupId] = useState<string | null>(initialGroupId), [color, setColor] = useState(initialColor), [savePassword, setSavePassword] = useState(hasPassword), [testMessage, setTestMessage] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  const testId=useRef<string>(),mounted=useRef(true);
  useEffect(() => {
    formRef.current?.querySelector<HTMLInputElement>("input")?.focus();
    mounted.current=true;
    return () => {mounted.current=false;if(testId.current)void runtime.request("connection.test_cancel",{test_id:testId.current}).catch(()=>{});};
  }, []);
  function field<K extends keyof ConnectionConfig>(key: K, value: ConnectionConfig[K]) { setConfig((previous) => ({ ...previous, [key]: value })); }
  function sshField<K extends keyof NonNullable<ConnectionConfig["ssh"]>>(key: K, value: NonNullable<ConnectionConfig["ssh"]>[K]) {
    setConfig(previous => ({ ...previous, ssh: { enabled: false, host: "", port: 22, username: "", auth_method: "password", ...previous.ssh, [key]: value } }));
  }
  function connectionConfig(): ConnectionConfig {
    const connection = { ...config, use_windows_auth: config.sqlserver_auth_mode === "windows",...(config.db_type==="databricks"?{databricks_auth_mode:databricksAuth,username:"",password:databricksAuth==="oauth"?"":config.password}: {}) };
    if (connection.ssh?.enabled && !["sqlite", "databricks"].includes(connection.db_type)) {
      if (!connection.ssh.host.trim()) throw new Error(t("Informe o servidor SSH."));
      if (!connection.ssh.username.trim()) throw new Error(t("Informe o usuário SSH."));
      if (!Number.isInteger(connection.ssh.port) || connection.ssh.port < 1 || connection.ssh.port > 65535) throw new Error(t("Informe uma porta SSH entre 1 e 65535."));
      if (connection.ssh.auth_method === "private_key" && !connection.ssh.private_key_path?.trim()) throw new Error(t("Escolha a chave privada SSH."));
    }
    return connection;
  }
  function importString() {
    try {
      const imported = parseConnectionString(stringInput, config.db_type);
      setConfig({ ...imported, name: config.name, ssh: config.ssh ? { ...config.ssh, enabled: config.ssh.enabled && !["sqlite", "databricks"].includes(imported.db_type) } : undefined });
      importedString.current = true; setSavePassword(false);
      setDatabricksAuth(imported.databricks_auth_mode ?? "oauth"); setStringInput(""); setError(""); setTestMessage("");
    } catch (failure) { setError(errorText(failure)); }
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const connection = connectionConfig();
      if (mode === "save" && !connection.name?.trim()) throw new Error(t("Informe o nome da conexão."));
      if (!connection.database.trim() && connection.db_type !== "databricks") throw new Error(t("Informe o banco ou arquivo SQLite."));
      await onConnect(connection, { group_id: groupId, color, save_password: config.db_type==="databricks"&&databricksAuth==="oauth"?false:savePassword, save_ssh_credentials: Boolean(connection.ssh?.enabled && !["sqlite", "databricks"].includes(connection.db_type)), use_saved_database_password: !importedString.current }); onClose();
    } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  }
  async function testConnection() {
    const id=crypto.randomUUID();testId.current=id;
    setBusy(true); setError(""); setTestMessage("");
    try {
      const result = await runtime.request<{ success: boolean; message?: string }>("connection.test", { test_id:id,connection_id:connectionId,resolve_database_password:!importedString.current,config: connectionConfig() });
      if(!mounted.current||testId.current!==id)return;
      if (!result.success) throw new Error(result.message ?? t("A conexão não foi estabelecida."));
      setTestMessage(result.message ?? t("Conexão testada com sucesso."));
    } catch (failure) { if(mounted.current&&testId.current===id)setError(errorText(failure)); } finally { if(mounted.current&&testId.current===id){testId.current=undefined;setBusy(false);} }
  }
  function cancelTest(){const id=testId.current;if(!id)return;testId.current=undefined;setBusy(false);void runtime.request("connection.test_cancel",{test_id:id}).catch(failure=>{if(mounted.current)setError(errorText(failure));});}
  function closeDialog() { if (testId.current) { cancelTest(); onClose(); } else if (!busy) onClose(); }
  async function chooseSQLite() {
    try {
      if (!isDesktop()) throw new Error(t("Seleção de arquivos está disponível no aplicativo desktop."));
      const path = await open({ multiple: false, filters: [{ name: "SQLite", extensions: ["db", "sqlite", "sqlite3"] }, { name: t("Todos"), extensions: ["*"] }] });
      if (typeof path === "string") field("database", path);
    } catch (failure) { setError(errorText(failure)); }
  }
  async function chooseSshKey() {
    try {
      if (!isDesktop()) throw new Error(t("Seleção de arquivos está disponível no aplicativo desktop."));
      const path = await open({ multiple: false, title: t("Escolher chave privada SSH") });
      if (typeof path === "string") sshField("private_key_path", path);
    } catch (failure) { setError(errorText(failure)); }
  }
  async function chooseTlsCa() {
    try {
      if (!isDesktop()) throw new Error(t("Seleção de arquivos está disponível no aplicativo desktop."));
      const path = await open({ multiple: false, title: t("Escolher certificado CA") });
      if (typeof path === "string") field("sslrootcert", path);
    } catch (failure) { setError(errorText(failure)); }
  }
  const server = config.db_type !== "sqlite", windows = config.db_type === "sqlserver" && config.sqlserver_auth_mode !== "sql_password";
  const sshSupported = !["sqlite", "databricks"].includes(config.db_type);
  const ssh = config.ssh;
  const sameSshIdentity = Boolean(initial?.ssh && ssh && initial.ssh.host === ssh.host && initial.ssh.port === ssh.port && initial.ssh.username === ssh.username && initial.ssh.auth_method === ssh.auth_method && initial.ssh.private_key_path === ssh.private_key_path);
  const passwordOption = mode === "save" && !windows && server && (config.db_type !== "databricks" || databricksAuth === "token");
  return <Modal title={mode === "save" ? initial ? t("Editar conexão") : t("Nova conexão") : t("Conectar ao banco")} className="connection-dialog" onClose={closeDialog}>
      <form ref={formRef} onSubmit={(event) => void submit(event)}>
        <fieldset className="connection-fields" disabled={busy}>
        <details className="connection-string-import"><summary>{t("Colar connection string")}</summary><label className="field">{t("URI ou string .NET/ODBC")}<textarea value={stringInput} onChange={event => setStringInput(event.target.value)} rows={3} spellCheck={false} autoComplete="off" /></label><button type="button" className="secondary-button" disabled={!stringInput.trim()} onClick={importString}>{t("Preencher campos")}</button></details>
        <label className="field">{t("Tipo do banco")}<select value={config.db_type} onChange={event => {
          const driver = DRIVERS.find(item => item.id === event.target.value);
          if (driver) setConfig(previous => ({ ...previous, db_type: driver.id, port: driver.port, database: driver.id === "sqlite" ? ":memory:" : "", schema: driver.id === "postgresql" ? "public" : "", host: driver.id === "sqlite" ? "" : previous.host || "localhost", ...(previous.ssh && ["sqlite", "databricks"].includes(driver.id) ? { ssh: { ...previous.ssh, enabled: false } } : {}) }));
        }}>{DRIVERS.map(driver => <option key={driver.id} value={driver.id}>{t(driver.name)}</option>)}</select></label>
        <label className="field">{t("Nome")} <input required={mode === "save"} value={config.name ?? ""} onChange={(event) => field("name", event.target.value)} /></label>
        {mode === "save" && <><div className="field-row"><label className="field grow">{t("Grupo")}<select aria-label={t("Grupo")} value={groupId ?? ""} onChange={(event) => setGroupId(event.target.value || null)}><option value="">{t("Sem grupo")}</option>{groupHierarchy(groups).map(({ group, label }) => <option key={group.id} value={group.id}>{label}</option>)}</select></label><label className="field connection-color">{t("Cor")}<input type="color" disabled={!color} value={color||"#80a3ff"} onChange={(event) => setColor(event.target.value)} /></label></div><label className="checkbox-field"><input type="checkbox" checked={!color} onChange={event=>setColor(event.target.checked?"":"#80a3ff")}/>{t("Herdar cor do grupo")}</label></>}
        {server && <div className="field-row"><label className="field grow">{t("Servidor")} <input required value={config.host} onChange={(event) => field("host", event.target.value)} placeholder={config.db_type === "databricks" ? "adb-….azuredatabricks.net" : "localhost"} /></label><label className="field port">{t("Porta")} <input type="number" min={1} max={65535} required value={config.port} onChange={(event) => field("port", Number(event.target.value))} /></label></div>}
        <label className="field">{config.db_type === "sqlite" ? t("Arquivo SQLite") : config.db_type === "databricks" ? t("Catalog") : t("Banco")}
          <div className="field-input-row"><input title={config.db_type === "sqlite" ? t("Arquivo SQLite ou :memory:") : undefined} value={config.database} onChange={(event) => field("database", event.target.value)} placeholder={config.db_type === "sqlite" ? ":memory:" : t("Nome do banco")} />
            {config.db_type === "sqlite" && <button type="button" className="icon-button" title={t("Escolher arquivo SQLite")} onClick={() => void chooseSQLite()}><FolderOpen size={16} /></button>}</div>
        </label>
        {config.db_type === "sqlserver" && <label className="field">{t("Autenticação")} <select value={config.sqlserver_auth_mode || "sql_password"} onChange={(event) => field("sqlserver_auth_mode", event.target.value)}><option value="sql_password">{t("Usuário e senha SQL")}</option><option value="windows">{t("Windows integrada")}</option><option value="entra_mfa">Microsoft Entra MFA</option></select></label>}
        {config.db_type==="databricks"&&<label className="field">{t("Autenticação")}<select value={databricksAuth} onChange={event=>{const mode=event.target.value as "oauth"|"token";setDatabricksAuth(mode);if(mode==="oauth"){field("password","");setSavePassword(false);}}}><option value="oauth">{t("OAuth no navegador")}</option><option value="token">Access token · PAT</option></select></label>}
        {server && !windows && (config.db_type!=="databricks"||databricksAuth==="token") && <div className="field-row"><label className="field grow" style={{display:config.db_type==="databricks"?"none":undefined}}>{config.db_type === "databricks" ? t("Usuário (token)") : t("Usuário")}<input autoComplete="username" value={config.username} onChange={(event) => field("username", event.target.value)} placeholder={config.db_type === "databricks" ? "token" : t("Usuário")} /></label><label className="field grow">{config.db_type === "databricks" ? "Access token" : t("Senha")}<input autoComplete="current-password" type="password" value={config.password ?? ""} onChange={(event) => field("password", event.target.value)} /></label></div>}
        {windows && config.sqlserver_auth_mode === "entra_mfa" && <label className="field">{t("Conta Microsoft (opcional)")}<input value={config.username} onChange={(event) => field("username", event.target.value)} placeholder="usuario@empresa.com" /></label>}
        {["postgresql", "databricks"].includes(config.db_type) && <label className="field">{t("Schema")} <input value={config.schema ?? ""} onChange={(event) => field("schema", event.target.value)} placeholder={config.db_type === "postgresql" ? "public" : "default"} /></label>}
        {config.db_type === "databricks" && <label className="field">HTTP path <input required value={config.http_path ?? ""} onChange={(event) => field("http_path", event.target.value)} placeholder="/sql/1.0/warehouses/…" /></label>}
        {config.db_type === "sqlserver" && <label className="checkbox-field"><input type="checkbox" checked={!!config.trust_server_certificate} onChange={(event) => field("trust_server_certificate", event.target.checked)} /> {t("Confiar no certificado do servidor")}</label>}
        {config.db_type === "postgresql" && <details className="connection-tls-fields"><summary>TLS PostgreSQL</summary>
          <label className="field">{t("Modo TLS")}<select value={config.sslmode ?? "prefer"} onChange={event => field("sslmode", event.target.value as ConnectionConfig["sslmode"])}><option value="disable">disable</option><option value="allow">allow</option><option value="prefer">prefer</option><option value="require">require</option><option value="verify-ca">verify-ca</option><option value="verify-full">verify-full</option></select></label>
          <label className="field">{t("Certificado CA (opcional)")}<div className="field-input-row"><input autoComplete="off" value={config.sslrootcert ?? ""} onChange={event => field("sslrootcert", event.target.value)} /><button type="button" className="icon-button" title={t("Escolher certificado CA")} aria-label={t("Escolher certificado CA")} onClick={() => void chooseTlsCa()}><FolderOpen size={16} /></button></div></label>
        </details>}
        {passwordOption && <label className="checkbox-field" title={hasPassword && !config.password ? t("(deixe em branco para manter a senha salva)") : undefined}><input type="checkbox" checked={savePassword} onChange={(event) => setSavePassword(event.target.checked)} />{t("Salvar senha")}</label>}
        {sshSupported && <section className="connection-ssh-fields" aria-label={t("Túnel SSH")}>
          <label className="checkbox-field"><input type="checkbox" checked={Boolean(ssh?.enabled)} onChange={event => sshField("enabled", event.target.checked)} />{t("Usar túnel SSH")}</label>
          {ssh?.enabled && <>
            <div className="field-row"><label className="field grow">{t("Servidor SSH")}<input required autoComplete="off" value={ssh.host} onChange={event => sshField("host", event.target.value)} placeholder="ssh.example.com" /></label><label className="field port">{t("Porta SSH")}<input required type="number" min={1} max={65535} value={ssh.port} onChange={event => sshField("port", Number(event.target.value))} /></label></div>
            <label className="field">{t("Usuário SSH")}<input required autoComplete="off" value={ssh.username} onChange={event => sshField("username", event.target.value)} /></label>
            <label className="field">{t("Autenticação SSH")}<select value={ssh.auth_method} onChange={event => setConfig(previous => ({ ...previous, ssh: { ...previous.ssh!, auth_method: event.target.value as "password" | "private_key", password: "", passphrase: "" } }))}><option value="password">{t("Senha")}</option><option value="private_key">{t("Chave privada")}</option></select></label>
            {ssh.auth_method === "password" ? <label className="field">{t("Senha SSH")}<input type="password" autoComplete="new-password" value={ssh.password ?? ""} placeholder={hasSshPassword && sameSshIdentity ? t("Deixe em branco para manter a senha salva") : undefined} onChange={event => sshField("password", event.target.value)} /></label> : <>
              <label className="field">{t("Chave privada SSH")}<div className="field-input-row"><input required autoComplete="off" value={ssh.private_key_path ?? ""} onChange={event => sshField("private_key_path", event.target.value)} /><button type="button" className="icon-button" title={t("Escolher chave privada SSH")} aria-label={t("Escolher chave privada SSH")} onClick={() => void chooseSshKey()}><FolderOpen size={16} /></button></div></label>
              <label className="field">{t("Passphrase (opcional)")}<input type="password" autoComplete="new-password" value={ssh.passphrase ?? ""} placeholder={hasSshPassphrase && sameSshIdentity ? t("Deixe em branco para manter a passphrase salva") : undefined} onChange={event => sshField("passphrase", event.target.value)} /></label>
            </>}
            <p className="connection-ssh-note">{t("O servidor e a porta do banco são acessados a partir do servidor SSH. Nomes Docker só funcionam se resolverem nesse servidor.")}</p>
            {mode === "save" && <p className="connection-ssh-note">{t("A senha SSH e a passphrase são salvas no armazenamento seguro do sistema.")}</p>}
          </>}
        </section>}
        </fieldset>
        {(passwordOption || config.db_type === "databricks" && databricksAuth === "oauth") && <details className="connection-help"><summary tabIndex={0}>{t("Ajuda")}</summary>
          {config.db_type === "databricks" && databricksAuth === "oauth" && <p>{t("Ao conectar ou testar, o driver abre o navegador para login quando o token OAuth não está em cache. Tokens salvos serão removidos ao salvar esta conexão em modo OAuth.")}</p>}
          {passwordOption && <p>{t("A senha permanece no runtime e nunca entra no rascunho ou na exportação de conexões.")}</p>}
          {passwordOption && hasPassword && !config.password && <p>{t("(deixe em branco para manter a senha salva)")}</p>}
        </details>}
        {testMessage && <p className="connection-test-success" role="status">{t(testMessage)}</p>}
        {error && <p className="form-error" role="alert">{t(error)}</p>}
        <footer className="modal-footer"><button type="button" className="secondary-button" onClick={testId.current?cancelTest:onClose} disabled={busy&&!testId.current}>{testId.current?t("Cancelar teste"):t("Cancelar")}</button><button type="button" className="secondary-button" onClick={() => void testConnection()} disabled={busy}>{t("Testar conexão")}</button><button type="submit" className="primary-button" disabled={busy}>{busy && <LoaderCircle size={15} className="spin" />}{busy ? t("Aguarde…") : mode === "save" ? t("Salvar") : t("Conectar")}</button></footer>
      </form>
  </Modal>;
}
