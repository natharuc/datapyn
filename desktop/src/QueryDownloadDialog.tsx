import { useState } from "react";
import { save } from "@tauri-apps/plugin-dialog";
import { Download } from "lucide-react";
import { DataModal } from "./DataActions";
import { featureTranslate as t } from "./featureTranslations";
import { errorText } from "./runtime";
import { normalizeExportSettings, type ExportSettings } from "./exportSettings";
import { queryDownloadDefaultPath, queryDownloadPath, type QueryDownloadFormat } from "./queryDownload";

export interface QueryDownloadRequest {
  sessionId: string; blockId: string; title: string; selection?: string;
  settings: ExportSettings; lastDirectory?: string; openFolder: boolean;
}
export function QueryDownloadDialog({request, onClose, onDownload}: {
  request: QueryDownloadRequest; onClose: () => void;
  onDownload: (path: string, format: QueryDownloadFormat, settings: ExportSettings) => void;
}) {
  const [format, setFormat] = useState<QueryDownloadFormat>("parquet");
  const [settings, setSettings] = useState(() => normalizeExportSettings({...request.settings,open_folder:request.openFolder}));
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const change = (patch: Partial<ExportSettings>) => setSettings(value => ({...value,...patch}));
  async function chooseDestination() {
    setBusy(true); setError("");
    try {
      const path = await save({defaultPath:queryDownloadDefaultPath(request.title,format,request.lastDirectory),filters:[{name:format === "csv" ? "CSV" : "Parquet",extensions:[format]}]});
      if (path) onDownload(queryDownloadPath(path,format),format,settings);
    } catch (failure) {setError(errorText(failure));} finally {setBusy(false);}
  }
  return <DataModal title={t("Executar e baixar consulta")} onClose={() => {if (!busy) onClose();}}>
    <div className="data-form">
      <p>{request.selection ? t("Executar a seleção SQL e baixar os resultados.") : t("Executar o bloco SQL e baixar os resultados.")}</p>
      <label>{t("Formato")}<select disabled={busy} value={format} onChange={event => setFormat(event.target.value as QueryDownloadFormat)}><option value="parquet">Parquet</option><option value="csv">CSV</option></select></label>
      {format === "csv" && <>
        <div className="data-field-row"><label>{t("Separador")}<select disabled={busy} value={settings.delimiter} onChange={event => change({delimiter:event.target.value})}><option value=";">;</option><option value=",">,</option><option value={"\t"}>TAB</option><option value="|">|</option></select></label><label>{t("Decimal")}<select disabled={busy} value={settings.decimal} onChange={event => change({decimal:event.target.value})}><option value=".">.</option><option value=",">,</option></select></label></div>
        <label>{t("Codificação")}<select disabled={busy} value={settings.encoding} onChange={event => change({encoding:event.target.value})}><option value="utf-8-sig">UTF-8 BOM</option><option value="utf-8">UTF-8</option><option value="cp1252">Windows-1252</option><option value="latin-1">Latin-1</option></select></label>
        <label className="data-check"><input disabled={busy} type="checkbox" checked={settings.include_header} onChange={event => change({include_header:event.target.checked})}/>{t("Incluir cabeçalho")}</label>
      </>}
      <label className="data-check"><input disabled={busy} type="checkbox" checked={settings.open_folder} onChange={event => change({open_folder:event.target.checked})}/>{t("Abrir pasta após exportar")}</label>
      <p className="data-hint">{t("Os resultados são gravados em lotes. A execução pode ser cancelada pelo bloco.")}</p>
      {error && <p className="data-error" role="alert">{error}</p>}
    </div>
    <footer><button disabled={busy} onClick={onClose}>{t("Cancelar")}</button><button className="primary-button" disabled={busy} onClick={() => void chooseDestination()}><Download size={13}/>{t("Escolher arquivo e executar")}</button></footer>
  </DataModal>;
}
