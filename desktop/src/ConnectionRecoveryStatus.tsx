import {useEffect,useState} from "react";
import {AlertTriangle,LoaderCircle,RefreshCw,X} from "lucide-react";
import {useTranslation} from "./i18n";
import {Modal} from "./PanelControls";
import type {ConnectionRecoveryState} from "./runtime";
import "./connectionRecoveryStatus.css";

export function ConnectionRecoveryStatus({state,disabled=false,compact=false,onRecover,onDismiss,onError}:{
  state?:ConnectionRecoveryState;disabled?:boolean;compact?:boolean;
  onRecover:(acknowledge:boolean)=>Promise<void>;onDismiss?:()=>void;onError:(message:string)=>void;
}) {
  const {t}=useTranslation(),[confirming,setConfirming]=useState<string>(),[pending,setPending]=useState(false);
  useEffect(()=>{if(confirming!==state?.recovery_id)setConfirming(undefined);},[state?.recovery_id,confirming]);
  // A new physical socket does not imply lost user state. Routine automatic
  // recovery is quiet once ready; only an acknowledged state loss needs notice.
  if(!state || state.phase==="ready"&&state.state_loss_acknowledged!==true)return null;
  const recovering=state.phase==="recovering",ready=state.phase==="ready";
  const label=recovering?"Reconectando…":ready?"Conexão recuperada":"Reconectar";
  const warning=recovering?label:ready?"A sessão física anterior foi perdida. Recrie tabelas temporárias se necessário. O código não foi executado novamente.":state.acknowledgement_required?"O resultado da execução anterior pode ser desconhecido. Revise antes de reconectar.":state.error??"Não foi possível recuperar a conexão. Tente novamente quando a rede estiver disponível.";
  const recover=async(acknowledge:boolean)=>{
    setConfirming(undefined);setPending(true);
    try{await onRecover(acknowledge);}catch(error){onError(error instanceof Error?error.message:String(error));}finally{setPending(false);}
  };
  return <>
    <span className={`connection-recovery-status${compact?" compact":""}${ready?" recovered":""}`} role={recovering?"status":undefined} title={t(warning)}>
      {recovering?<><LoaderCircle size={12} className="spin" aria-hidden="true"/><span>{t(label)}</span></>:ready?<><AlertTriangle size={12} aria-hidden="true"/><span>{t(label)}</span>{!compact&&<span className="connection-recovery-detail">{t(warning)}</span>}{onDismiss&&<button className="icon-button" title={t("Dispensar aviso")} aria-label={t("Dispensar aviso")} onClick={onDismiss}><X size={12}/></button>}</>:<>
        {!compact&&<span className="connection-recovery-detail">{t(warning)}</span>}
        <button disabled={disabled||pending} onClick={()=>state.acknowledgement_required?setConfirming(state.recovery_id):void recover(false)}><RefreshCw size={12} aria-hidden="true"/>{t(label)}</button>
      </>}
    </span>
    {confirming===state.recovery_id&&<Modal title={t("Reconectar este bloco?")} onClose={()=>setConfirming(undefined)}>
      <div className="confirm-copy"><p>{t("O resultado de comandos anteriores pode ser desconhecido. Transações e tabelas temporárias da conexão anterior não serão restauradas.")}</p><p>{t("A reconexão mantém os códigos e DataFrames desta aba. Nenhum código será executado novamente.")}</p></div>
      <footer className="modal-footer"><button onClick={()=>setConfirming(undefined)}>{t("Cancelar")}</button><button className="primary-button" disabled={disabled||pending} onClick={()=>void recover(true)}>{t("Reconectar")}</button></footer>
    </Modal>}
  </>;
}
