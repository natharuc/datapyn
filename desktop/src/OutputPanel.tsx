import {useEffect,useRef} from "react";
import {Terminal} from "lucide-react";
import {useTranslation} from "./i18n";
import {ErrorDetails} from "./ErrorDetails";
import {errorInfoFor,technicalErrorText} from "./errorPresentation";
import type {SessionDocument} from "./workspace";

export function OutputPanel({session}:{session:SessionDocument}) {
  const {t}=useTranslation(),end=useRef<HTMLDivElement>(null);
  useEffect(()=>{end.current?.scrollIntoView({block:"nearest"});},[session.logs]);
  return <div className="output-panel" aria-label={t("Saída")}>
    {session.logs.length?session.logs.map(line=>{
      const info=line.errorInfo??(line.stream==="stderr"&&technicalErrorText(line.text)?errorInfoFor(line.text):undefined);
      return <div key={line.id} className={`output-entry ${line.stream}${info?" output-error":""}`} data-execution-id={line.executionId}>
        <span>{line.time}</span><span className="output-stream">{line.stream==="stderr"?"ERR":line.stream==="system"?"SYS":"OUT"}</span>
        {info?<div className="error-details-owner">{line.blockName&&<div className="output-block-name">{line.blockName}</div>}<ErrorDetails info={info}/></div>:<pre>{line.text}</pre>}
      </div>;
    }):<div className="output-empty"><Terminal size={19}/><span>{t("Sem saída.")}</span></div>}
    <div ref={end}/>
  </div>;
}
