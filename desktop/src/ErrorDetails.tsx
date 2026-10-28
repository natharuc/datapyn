import {useRef,useState} from "react";
import {Check,Copy} from "lucide-react";
import {useTranslation} from "./i18n";
import type {RuntimeErrorInfo} from "./runtime";
import {errorDetailsText} from "./errorPresentation";
import "./errorDetails.css";

/** Error text stays selectable; diagnostic content is available on demand. */
export function ErrorDetails({info,showTitle=true}:{info:RuntimeErrorInfo;showTitle?:boolean}) {
  const {t}=useTranslation(),host=useRef<HTMLDivElement>(null),[copied,setCopied]=useState(false),[copyFailed,setCopyFailed]=useState(false);
  async function copy(){
    setCopied(false);setCopyFailed(false);
    try{
      const clipboard=host.current?.ownerDocument.defaultView?.navigator.clipboard;
      if(!clipboard)throw new Error("clipboard unavailable");
      await clipboard.writeText(errorDetailsText(info));setCopied(true);
    }catch{setCopyFailed(true);}
  }
  return <div className="error-details" ref={host}>
    {showTitle&&<strong className="error-details-title">{t(info.title)}</strong>}
    {info.message&&<p className="error-details-message">{t(info.message)}</p>}
    <div className="error-details-actions">
      {info.technical_details&&<details><summary>{t("Detalhes técnicos")}</summary><pre>{info.technical_details}</pre></details>}
      <button type="button" className="text-button" onClick={()=>void copy()} aria-label={t("Copiar detalhes")} title={t("Copiar detalhes")}>
        {copied?<Check size={12} aria-hidden="true"/>:<Copy size={12} aria-hidden="true"/>}{t(copied?"Copiado":"Copiar detalhes")}
      </button>
    </div>
    {copyFailed&&<span className="error-details-copy-status" role="status">{t("Não foi possível copiar. Selecione o texto para copiar manualmente.")}</span>}
  </div>;
}
