import {translate as translateUi} from "./i18n";
import {useEffect,useState} from "react";
import {Modal} from "./PanelControls";
import {runtime,errorText} from "./runtime";
import {identifierParts,type ExplorerDetails,type ExplorerScope} from "./explorer";

export function EntityInfoDialog({identifier,scope,onClose}:{identifier:string;scope:ExplorerScope;onClose:()=>void}) {
  const [details,setDetails]=useState<ExplorerDetails>(),[error,setError]=useState("");
  useEffect(()=>{let active=true;const parts=identifierParts(identifier);void runtime.request<ExplorerDetails>("explorer.details",{...scope,name:parts.at(-1),schema:parts.length>1?parts.at(-2):scope.schema,database:parts.length>2?parts.at(-3):scope.database}).then(result=>{if(active)setDetails(result);},failure=>{if(active)setError(errorText(failure));});return()=>{active=false;};},[identifier,scope.session_id,scope.connection_id,scope.database,scope.schema]);
  return <Modal title={`Informações: ${identifier}`} onClose={onClose} className="entity-info"><div className="entity-info-content">{error?<p role="alert" className="error-text">{error}</p>:!details?<p>{translateUi("Carregando metadados…")}</p>:<>{(details.columns?.length ?? 0)>0 && <table><thead><tr><th>{translateUi("Coluna")}</th><th>{translateUi("Tipo")}</th><th>{translateUi("Nulo")}</th></tr></thead><tbody>{details.columns!.map((c,index)=><tr key={index}><td>{String(c.name)}</td><td>{String(c.type ?? c.data_type ?? "")}</td><td>{c.nullable === false ? "Não" : "Sim"}</td></tr>)}</tbody></table>}{Object.entries(details).filter(([key])=>key !== "columns" && key !== "definition").map(([key,value])=><details key={key}><summary>{key}</summary><pre>{JSON.stringify(value,null,2)}</pre></details>)}{details.definition && <details open><summary>{translateUi("Definição")}</summary><pre>{details.definition}</pre></details>}</>}</div></Modal>;
}
