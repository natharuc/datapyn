import { AlertTriangle, LoaderCircle, RefreshCw } from "lucide-react";
import { useTranslation } from "./i18n";
import type { SessionConnectionState } from "./workspace";
import "./sessionConnectionStatus.css";

export function connectionPending(state?: SessionConnectionState) {
  return state?.phase === "preparing" || state?.phase === "connecting";
}

export function SessionConnectionStatus({state,onRetry,retryLabel="Tentar novamente"}:{state?:SessionConnectionState;onRetry?:()=>void;retryLabel?:string}) {
  const {t}=useTranslation();
  if(!state||state.phase==="ready")return null;
  const failed=state.phase==="error";
  return <section className={`session-connection-status${failed?" failed":""}`} role={failed?"alert":"status"} aria-busy={!failed}>
    {failed?<AlertTriangle size={18} aria-hidden="true"/>:<LoaderCircle size={18} className="spin" aria-hidden="true"/>}
    <div><strong>{t(failed?"Falha ao abrir a conexão":state.phase==="preparing"?"Preparando sessão…":"Conectando e autenticando…")}{state.name&&<span> · {state.name}</span>}</strong>
      {failed&&state.error&&<p>{state.error}</p>}
    </div>
    {failed&&onRetry&&<button className="secondary-button" onClick={onRetry}><RefreshCw size={13} aria-hidden="true"/>{t(retryLabel)}</button>}
  </section>;
}
