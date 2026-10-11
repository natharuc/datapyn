import {useState,useSyncExternalStore} from "react";
import {ArrowDownToLine,RefreshCw,X} from "lucide-react";
import {useTranslation} from "./i18n";
import type {UpdateController} from "./updater";
import "./updater.css";

/** App-wide update notice; execution notifications keep their own focus rules. */
export function UpdateNotice({controller,onOpen}:{controller:UpdateController;onOpen:()=>void}) {
  const {t}=useTranslation(),state=useSyncExternalStore(controller.subscribe,controller.getSnapshot);
  const [dismissed,setDismissed]=useState<string>();
  const key=`${state.version}:${state.phase}`;
  if(!state.version || !["available","downloaded","failed"].includes(state.phase) || dismissed===key)return null;
  const ready=state.phase==="downloaded",failed=state.phase==="failed";
  return <article className={`notification-card update-notice${failed?" failure":""}`}>
    <button className="notification-open" onClick={()=>{if(!ready)void controller.download();onOpen();}}>
      {ready?<RefreshCw size={18}/>:<ArrowDownToLine size={18}/>}<div>
        <strong>{t(ready?"Atualização pronta":"Nova versão disponível")}: {state.version}</strong>
        {failed && <p>{t("Não foi possível baixar a atualização.")}</p>}
        <small>{t(ready?"Abrir atualização":failed?"Tentar download novamente":"Clique para baixar")}</small>
      </div>
    </button>
    <button className="notification-close" aria-label={t("Fechar notificação")} onClick={()=>setDismissed(key)}><X size={15}/></button>
  </article>;
}
