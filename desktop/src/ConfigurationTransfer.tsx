import {useState} from "react";
import {open} from "@tauri-apps/plugin-dialog";
import {Download,FolderOpen,LoaderCircle,Upload} from "lucide-react";
import {errorText,isDesktop} from "./runtime";
import {useTranslation} from "./i18n";
import type {ConfigurationDefaults} from "./configurationDefaults";

export interface ConfigurationFile {name:string;category:string;bytes:number}
export interface ConfigurationPreview {
  preview_token:string;files:ConfigurationFile[];excluded_files:string[];warnings:string[];
  preferences?:Record<string,unknown>;shortcuts?:Record<string,string>;
  defaults?:ConfigurationDefaults;
  connections?:number;groups?:number;
}
export interface ConfigurationTransferActions {
  busy?:boolean;
  inspect:(path:string)=>Promise<ConfigurationPreview>;
  import:(path:string,preview:ConfigurationPreview)=>Promise<void>;
  export:(path:string)=>Promise<{files:ConfigurationFile[];warnings?:string[]}>;
}

export function ConfigurationTransfer({actions}:{actions:ConfigurationTransferActions}) {
  const {t}=useTranslation();
  const [preview,setPreview]=useState<{path:string;value:ConfigurationPreview}>();
  const [working,setWorking]=useState(false),[error,setError]=useState("");
  const [message,setMessage]=useState(""),[warnings,setWarnings]=useState<string[]>([]);
  const disabled=working || actions.busy || !isDesktop();
  const action=async(work:()=>Promise<void>)=>{
    setWorking(true);setError("");setMessage("");setWarnings([]);
    try{await work();}catch(failure){setError(errorText(failure));}finally{setWorking(false);}
  };
  const choose=async(importing:boolean)=>{
    const path=await open({directory:true,multiple:false,title:t(importing ? "Importar pasta de configurações PyQt6" : "Exportar configurações para uma pasta vazia")});
    if(typeof path !== "string")return;
    if(importing){const value=await actions.inspect(path);setPreview({path,value});}
    else{const result=await actions.export(path);setPreview(undefined);setWarnings(result.warnings ?? []);setMessage(t("Configurações exportadas: {count} arquivos.",{count:result.files.length}));}
  };
  return <section className="configuration-transfer">
    <p>{t("Importe a pasta do workspace do PyQt6 ou exporte os arquivos compatíveis para uma pasta vazia.")}</p>
    <p className="form-hint">{t("O JSON de conexões continua disponível em Gerenciar conexões. Senhas permanecem no cofre do sistema; sessões são restauradas automaticamente ao abrir o aplicativo.")}</p>
    <div className="configuration-actions">
      <button className="secondary-button" disabled={disabled} onClick={()=>void action(()=>choose(true))}><Upload size={14}/>{t("Importar configurações")}</button>
      <button className="secondary-button" disabled={disabled} onClick={()=>void action(()=>choose(false))}><Download size={14}/>{t("Exportar configurações")}</button>
      {working && <LoaderCircle size={16} className="spin"/>}
    </div>
    {actions.busy && <p className="form-hint">{t("Finalize as execuções antes de transferir configurações.")}</p>}
    {!isDesktop() && <p className="form-hint">{t("Importação e exportação estão disponíveis no desktop.")}</p>}
    {preview && <div className="configuration-preview">
      <h3><FolderOpen size={16}/>{t("Revisar importação")}</h3><code>{preview.path}</code>
      <ul>{preview.value.files.map(file=><li key={file.name}><span>{file.name}</span><small>{(file.bytes/1024).toLocaleString(undefined,{maximumFractionDigits:1})} KiB</small></li>)}</ul>
      {preview.value.warnings.length>0 && <ul className="form-hint">{preview.value.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul>}
      {preview.value.excluded_files.length>0 && <p className="form-hint">{t("Arquivos de sessões e dados ficam fora da transferência de configurações.")}</p>}
      <p>{t("A importação aplica estas configurações ao workspace atual.")}</p>
      <div className="configuration-actions"><button className="secondary-button" disabled={working} onClick={()=>setPreview(undefined)}>{t("Cancelar")}</button><button className="primary-button" disabled={disabled || !preview.value.files.length} onClick={()=>void action(async()=>{await actions.import(preview.path,preview.value);setPreview(undefined);setMessage(t("Configurações importadas e aplicadas."));})}>{t("Confirmar importação")}</button></div>
    </div>}
    {message && <p role="status" className="form-hint">{message}</p>}
    {warnings.length>0 && <ul className="form-hint">{warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul>}
    {error && <p role="alert" className="form-error">{error}</p>}
  </section>;
}
