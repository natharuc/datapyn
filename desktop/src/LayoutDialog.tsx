import {useState} from "react";
import {ExternalLink,Layers3,LayoutDashboard,LoaderCircle,RotateCcw,Save} from "lucide-react";
import {Modal} from "./PanelControls";
import {useTranslation} from "./i18n";
import {errorText} from "./runtime";
import {PANEL_IDS,type DockDirection,type DockingControls,type PanelId} from "./dockingLayout";
import "./layoutDialog.css";

const titles:Record<PanelId,string>={editor:"Análise",connections:"Conexões",explorer:"Object Explorer",results:"Resultados",summary:"Resumo",output:"Saída",pyniaOutput:"Pynia Output",variables:"Variáveis",pynia:"Pynia"};
const descriptions:Record<PanelId,string>={editor:"Blocos SQL e Python",connections:"Conexões e grupos",explorer:"Bancos, tabelas e colunas",results:"Tabelas e gráficos",summary:"Estatísticas dos dados",output:"Mensagens da execução",pyniaOutput:"Atividade e ferramentas do agente",variables:"Namespace da análise",pynia:"Chat com o agente"};
interface Props {controls:DockingControls;visiblePanels:readonly PanelId[];restoreShortcut:string;resetShortcut:string;onRestore:()=>void;onReset:()=>void;onSave:()=>Promise<void>;canSave:boolean;onClose:()=>void;onMessage?:(message:string)=>void}
export function LayoutDialog({controls,visiblePanels,restoreShortcut,resetShortcut,onRestore,onReset,onSave,canSave,onClose,onMessage}:Props){
  const {t}=useTranslation(),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const action=(work:()=>void)=>{setError("");try{work();}catch(failure){setError(errorText(failure));}};
  async function save(){setBusy(true);setError("");try{await onSave();onClose();}catch(failure){setError(errorText(failure));}finally{setBusy(false);}}
  return <Modal title={t("Painéis e layout")} onClose={()=>{if(!busy)onClose();}} className="layout-dialog">
    <div className="layout-intro"><LayoutDashboard size={21}/><div><p>{t("Organize seu espaço de trabalho.")}</p><small>{t("Arraste as abas para mover, dividir ou agrupar painéis. Arraste as divisórias para redimensionar.")}</small></div></div>
    <div className="layout-panels">{PANEL_IDS.map(id=>{const visible=visiblePanels.includes(id);return <div className="layout-panel-row" key={id}>
      <label><input type="checkbox" checked={visible} disabled={id === "editor" || busy} onChange={event=>action(()=>event.target.checked ? controls.show(id) : controls.hide(id))}/><span><strong>{t(titles[id])}</strong><small>{t(descriptions[id])}</small></span></label>
      <div className="layout-panel-actions"><select aria-label={`${t("Mover painel")}: ${t(titles[id])}`} disabled={busy || !visible} value="" onChange={event=>action(()=>controls.move(id,event.target.value as DockDirection))}>
        <option value="" disabled>{t("Mover para…")}</option><option value="left">{t("Esquerda")}</option><option value="right">{t("Direita")}</option><option value="above">{t("Acima")}</option><option value="below">{t("Abaixo")}</option><option value="within">{t("Agrupar em abas")}</option>
      </select><button type="button" className="icon-button" disabled={busy || !visible} title={`${t("Flutuar painel")}: ${t(titles[id])}`} aria-label={`${t("Flutuar painel")}: ${t(titles[id])}`} onClick={()=>action(()=>{onClose();controls.float(id);})}><Layers3 size={15}/></button>
      <button type="button" className="icon-button" disabled={busy || !visible} title={`${t("Abrir painel em outra janela")}: ${t(titles[id])}`} aria-label={`${t("Abrir painel em outra janela")}: ${t(titles[id])}`} onClick={()=>{onClose();void controls.popout(id).then(opened=>{if(!opened)onMessage?.(t("Não foi possível destacar este painel. Ele permanece na janela atual."));}).catch(failure=>onMessage?.(errorText(failure)));}}><ExternalLink size={15}/></button></div>
    </div>;})}</div>
    <div className="layout-restore"><button disabled={busy} onClick={()=>action(controls.dockAll)}><Layers3 size={14}/>{t("Acoplar todas as janelas")}</button>
      <button disabled={busy} onClick={()=>action(onRestore)}><RotateCcw size={14}/>{t("Restaurar disposição padrão")}<kbd>{restoreShortcut}</kbd></button>
      <button disabled={busy} onClick={()=>action(onReset)}>{t("Redefinir layout e tamanhos")}<kbd>{resetShortcut}</kbd></button></div>
    <p className="layout-save-note">{t("A disposição é salva automaticamente neste workspace.")}</p>
    {error && <p className="layout-error" role="alert">{error}</p>}
    <footer className="modal-footer"><button disabled={busy} onClick={onClose}>{t("Fechar")}</button><button className="primary-button" disabled={busy || !canSave} onClick={()=>void save()}>{busy ? <LoaderCircle size={14} className="spin"/> : <Save size={14}/>} {t("Salvar layout agora")}</button></footer>
  </Modal>;
}
