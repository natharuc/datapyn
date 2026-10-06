import { AlertTriangle, LoaderCircle, X } from "lucide-react";
import { featureTranslate as t } from "./featureTranslations";
import { dataImportPending, importFileName, type DataImportState } from "./dataImport";
import "./dataImport.css";

export function DataImportStatus({state,onCancel,onDismiss}:{state?:DataImportState;onCancel?:()=>void;onDismiss?:()=>void}) {
  if(!state)return null;
  const pending=dataImportPending(state), failed=state.phase==="error";
  const label=t(state.phase==="preparing"?"Preparando importação…":state.phase==="registering"?"Preparando dados…":state.phase==="cancelling"?"Cancelando importação…":state.phase==="cancelled"?"Importação cancelada.":failed?"Falha ao importar arquivo":"Lendo arquivo…");
  const measured=/\.(csv|tsv|txt)$/i.test(state.path);
  const percent=state.phase==="reading"&&measured&&state.total>0?Math.min(100,Math.floor(state.current/state.total*100)):undefined;
  return <section className={`data-import-status${failed?" failed":""}`} role={failed?"alert":"status"} aria-live="polite" aria-busy={pending}>
    {failed?<AlertTriangle size={16} aria-hidden="true"/>:pending?<LoaderCircle size={16} className="spin" aria-hidden="true"/>:null}
    <div className="data-import-description"><strong>{label}</strong><span title={state.path}>{importFileName(state.path)}</span>{failed&&<p>{state.error}</p>}</div>
    {pending&&<div className="data-import-meter"><progress max={100} value={percent} aria-label={label}/>{percent!==undefined&&<span>{percent}%</span>}</div>}
    {pending&&onCancel&&<button disabled={state.phase==="cancelling"} onClick={onCancel}>{t("Cancelar")}</button>}
    {!pending&&onDismiss&&<button className="icon-button" aria-label={t("Fechar")} onClick={onDismiss}><X size={14}/></button>}
  </section>;
}
