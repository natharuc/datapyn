import { useRef, useState } from "react";
import { Copy, LoaderCircle } from "lucide-react";
import { translate as t, useLocale } from "./i18n";
import { Modal } from "./PanelControls";
import { errorText } from "./runtime";
import { connectionStringFormats, formatConnectionString, type ConnectionStringFormat } from "./connectionStrings";
import type { ConnectionsController, SavedConnection } from "./connections";

export function ConnectionStringDialog({ connection, controller, onClose }: { connection: SavedConnection; controller: ConnectionsController; onClose: () => void }) {
  useLocale();
  const formats = connectionStringFormats(connection.config);
  const [format, setFormat] = useState<ConnectionStringFormat>(formats[0].id), [include, setInclude] = useState(false), [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [error, setError] = useState("");
  const preview = formatConnectionString(connection.config, format), textarea = useRef<HTMLTextAreaElement>(null);
  const passwordAuth = connection.config.db_type !== "sqlite" && connection.config.databricks_auth_mode !== "oauth" && !(connection.config.db_type === "sqlserver" && (connection.config.use_windows_auth || ["windows", "entra_mfa"].includes(connection.config.sqlserver_auth_mode ?? "")));
  async function copy() {
    setBusy(true); setMessage(""); setError("");
    try {
      const clipboard = textarea.current?.ownerDocument.defaultView?.navigator.clipboard;
      if (!clipboard) throw new Error(t("Área de transferência indisponível nesta janela."));
      // Never put plaintext credentials into React state, a preview, persistence or logs.
      const exported = include ? await controller.exportConfig(connection.id, true) : { config: connection.config, password_included: false };
      if (include && !exported.password_included) throw new Error(t("A senha salva não está disponível."));
      await clipboard.writeText(formatConnectionString(exported.config, format, include));
      setMessage(t("Copiado para a área de transferência."));
    } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  }
  return <Modal title={t("Copiar connection string")} className="connection-string-dialog" onClose={() => { if (!busy) onClose(); }}>
    <div className="connection-string-fields">
      <label className="field">{t("Formato")}<select value={format} disabled={busy} onChange={event => { setFormat(event.target.value as ConnectionStringFormat); setMessage(""); }}>{formats.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
      <label className="field">{t("Prévia sem senha")}<textarea ref={textarea} value={preview} readOnly spellCheck={false} rows={8} /></label>
      {connection.has_password && passwordAuth && <label className="checkbox-field"><input type="checkbox" disabled={busy} checked={include} onChange={event => { setInclude(event.target.checked); setMessage(""); }} />{t("Incluir senha salva ao copiar")}</label>}
      {!connection.has_password && passwordAuth && <p className="connection-string-hint">{t("Substitua <password> pela senha no destino.")}</p>}
      {(connection.config.ssh?.enabled || connection.config.ssh_tunnel_id) && <p className="connection-string-hint">{t("O túnel SSH é gerenciado pelo DataPyn e não está incluído nesta string.")}</p>}
      {connection.config.db_type === "sqlserver" && ["ntlm", "kerberos"].includes(connection.config.sqlserver_auth_mode ?? "") && <p className="connection-string-hint">{t("Credenciais de rede explícitas usam Python TDS/SPNEGO. O exemplo exige uma CA válida e as dependências NTLM/Kerberos no destino.")}</p>}
      {connection.config.db_type === "databricks" && connection.config.databricks_auth_mode === "oauth" && ["native", "csharp"].includes(format) && <p className="connection-string-hint">{t("Defina <refresh-token-encryption-password> para proteger o cache OAuth do driver ODBC.")}</p>}
      {message && <p className="connection-test-success" role="status">{message}</p>}
      {error && <p className="form-error" role="alert">{t(error)}</p>}
    </div>
    <footer className="modal-footer"><button className="secondary-button" disabled={busy} onClick={onClose}>{t("Fechar")}</button><button className="primary-button" disabled={busy} onClick={() => void copy()}>{busy ? <LoaderCircle size={14} className="spin" /> : <Copy size={14} />}{t("Copiar")}</button></footer>
  </Modal>;
}
