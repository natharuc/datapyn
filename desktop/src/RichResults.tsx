import {translate as translateUi} from "./i18n";
import {useEffect,useRef,useState} from "react";
import {save} from "@tauri-apps/plugin-dialog";
import DOMPurify from "dompurify";
import type {Data,Layout} from "plotly.js";
import {runtime,errorText,type RichOutput} from "./runtime";
import {artifactExportTarget} from "./richExport";

function JsonTree({value,name="JSON",depth=0}:{value:unknown;name?:string;depth?:number}) {
  const [open,setOpen]=useState(depth===0),[limit,setLimit]=useState(50);
  if(value===null || typeof value !== "object")return <div className="json-value"><b>{name}: </b><span>{JSON.stringify(value)}</span></div>;
  const entries=Object.entries(value);
  return <details open={open} onToggle={e=>setOpen(e.currentTarget.open)}><summary>{name} · {Array.isArray(value)?"Array":"Object"} ({entries.length})</summary>{open && <div className="json-children">{entries.slice(0,limit).map(([key,item])=><JsonTree key={key} value={item} name={key} depth={depth+1}/>)}{entries.length>limit && <button onClick={()=>setLimit(n=>n+100)}>{translateUi("Mostrar mais")}</button>}</div>}</details>;
}
function PlotlyResult({data}:{data:unknown}) {
  const node=useRef<HTMLDivElement>(null),[error,setError]=useState("");
  useEffect(()=>{let active=true;const container=node.current!;let plotly:typeof import("plotly.js")|undefined;
    const figure=data as {data:Data[];layout:Partial<Layout>},basic=new Set(["bar","scatter","pie"]),loader=figure.data.every(trace=>basic.has(String(trace.type ?? "scatter")))?import("plotly.js-basic-dist-min"):import("plotly.js-dist-min");
    void loader.then(async module=>{plotly=module.default;if(active)await plotly.newPlot(container,figure.data,{...figure.layout,autosize:true},{responsive:true,displaylogo:false});}).catch(failure=>{if(active)setError(errorText(failure));});
    const resize=new ResizeObserver(()=>{if(active && plotly)void plotly.Plots.resize(container);});resize.observe(container);return()=>{active=false;resize.disconnect();plotly?.purge(container);};
  },[data]);
  return <>{error && <p role="alert">{error}</p>}<div ref={node} style={{height:400,width:"100%"}}/></>;
}
export function RichResults({outputs,sessionId,onMessage}:{outputs:RichOutput[];sessionId:string;onMessage:(message:string)=>void}) {
  async function exportArtifact(output:RichOutput,index:number){try{const format=output.type === "image"?"png":output.type === "json"?"json":"html",filters=output.type === "image"?[{name:"PNG",extensions:["png"]},{name:"JPEG",extensions:["jpg","jpeg"]}]:output.type === "plotly"?[{name:"HTML",extensions:["html"]},{name:"JSON",extensions:["json"]}]:[{name:format.toUpperCase(),extensions:[format]}],chosen=await save({defaultPath:`resultado-${index+1}.${format}`,filters});if(chosen){const target=artifactExportTarget(output.type,chosen);await runtime.request("result.artifact_write",{session_id:sessionId,artifact_id:output.artifact_id,...target});onMessage(`Resultado salvo: ${target.path}`);}}catch(failure){onMessage(errorText(failure));}}
  return <div className="rich-results">{outputs.map((output,index)=><section key={output.artifact_id ?? index}><header><strong>{output.type.toUpperCase()} {index+1}</strong><button disabled={!output.artifact_id} onClick={()=>void exportArtifact(output,index)}>{translateUi("Salvar resultado")}</button></header>{output.type === "image"?<img src={`data:${output.mime};base64,${output.data}`} alt={`Resultado Python ${index+1}`}/>:output.type === "html"?<iframe title={`HTML Python ${index+1}`} sandbox="" srcDoc={`<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:;"><style>body{font:14px sans-serif;}table{border-collapse:collapse;}td,th{padding:6px;border:1px solid #8884;}</style>${DOMPurify.sanitize(output.data)}`}/>:output.type === "plotly"?<PlotlyResult data={output.data}/>:<JsonTree value={output.data}/>}</section>)}</div>;
}
