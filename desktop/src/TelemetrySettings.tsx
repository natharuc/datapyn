import {useEffect, useState} from "react";
import {runtime, errorText} from "./runtime";
import {useTranslation, localizedSearch} from "./i18n";

interface TelemetryStatus {
  enabled: boolean; endpoint: string; provider: string;
  queued: number; sent: number; dropped: number; last_status: string;
}

export function TelemetrySettings({query = ""}: {query?: string}) {
  const {t} = useTranslation();
  const [status, setStatus] = useState<TelemetryStatus>(), [enabled, setEnabled] = useState(false), [endpoint, setEndpoint] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [saved, setSaved] = useState(false);
  useEffect(() => {
    let current = true;
    void runtime.request<TelemetryStatus>("telemetry.settings.get").then(value => {
      if (current) {setStatus(value); setEnabled(value.enabled); setEndpoint(value.endpoint);}
    }, failure => {if (current) setError(errorText(failure));});
    return () => {current = false;};
  }, []);
  if (!localizedSearch(query, "Telemetria", "Enviar diagnósticos de falhas e desempenho", "Endpoint HTTPS")) return null;
  return <section className="settings-fields telemetry-settings" aria-label={t("Telemetria")}>
    <label className="checkbox-label"><input type="checkbox" checked={enabled} disabled={!status || busy} onChange={event => {setEnabled(event.target.checked); setSaved(false);}}/>{t("Enviar diagnósticos de falhas e desempenho")}</label>
    <p className="form-hint">{t("Opcional. Envia versão, sistema operacional, tipo de banco, tempos e categorias de erro. Não envia SQL, dados, nomes de servidores, arquivos ou credenciais.")}</p>
    <label>{t("Endpoint HTTPS")}<input type="url" autoComplete="off" value={endpoint} disabled={!status || busy} onChange={event => {setEndpoint(event.target.value); setSaved(false);}}/></label>
    <p className="form-hint">{t("O envio ocorre em segundo plano. Desativar apaga a fila local. A telemetria não altera suas consultas.")}</p>
    {status && <p className="form-hint">{t("Na fila")}: {status.queued} · {t("Enviados")}: {status.sent}</p>}
    {error && <p role="alert" className="form-error">{error}</p>}
    {saved && <p role="status">{t("Telemetria salva.")}</p>}
    <div><button type="button" disabled={!status || busy} onClick={async () => {
      setBusy(true); setError(""); setSaved(false);
      try {setStatus(await runtime.request<TelemetryStatus>("telemetry.settings.set", {enabled, endpoint})); setSaved(true);}
      catch (failure) {setError(errorText(failure));}
      finally {setBusy(false);}
    }}>{t("Salvar telemetria")}</button></div>
  </section>;
}
