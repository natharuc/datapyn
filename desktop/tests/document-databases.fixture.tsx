import React,{useState} from "react";
import {createRoot} from "react-dom/client";
import {ConnectionDialog} from "../src/ConnectionDialog";
import {BlockScopePicker} from "../src/BlockScopePicker";
import {ObjectExplorer} from "../src/ObjectExplorer";
import {DatabaseIcon} from "../src/DatabaseIcon";
import {DataActions} from "../src/DataActions";
import {databaseCapabilities} from "../src/databaseCapabilities";
import {runtime} from "../src/runtime";
import {featureTranslate} from "../src/featureTranslations";
import {setLocale,translate} from "../src/i18n";
import type {ConnectionConfig} from "../src/workspace";
import "../src/styles.css";

const query=new URLSearchParams(location.search);setLocale(query.get("locale")==="en-US"?"en-US":"pt-BR");
document.documentElement.dataset.theme=query.get("theme")==="light"?"light":"dark";
const calls:Array<{method:string;params:Record<string,unknown>}>=[],saved:ConnectionConfig[]=[],contexts:unknown[]=[],inserts:string[]=[];
runtime.request=async <T,>(method:string,params:Record<string,unknown>={}):Promise<T>=>{
  calls.push({method,params});
  if(method==="connection.test")return {success:true} as T;
  if(method==="explorer.list")return {nodes:[{id:"orders",name:"orders",database:"analysis",kind:"table",has_children:false}]} as T;
  if(method==="explorer.query")return {code:"SELECT TOP 1000 * FROM c",container:"orders"} as T;
  if(method==="explorer.details")return {columns:[{name:"id",type:"string"},{name:"customer.name",type:"string"}]} as T;
  throw new Error(`Unexpected fixture request: ${method}`);
};
runtime.subscribe=async()=>()=>{};

function Fixture(){
  const [dialog,setDialog]=useState(query.get("screen")!=="workspace"),[container,setContainer]=useState("customers");
  Object.assign(window,{__DOCUMENT_DATABASES_TEST__:{calls,saved,contexts,inserts,translate,featureTranslate,open:()=>setDialog(true)}});
  return <>
    <div style={{padding:24,display:"flex",gap:18}}>{["elasticsearch","cosmosdb","mongodb"].map(dbType=><span key={dbType}><DatabaseIcon dbType={dbType} color="#dc8a35" size={24}/>{dbType}</span>)}</div>
    {dialog && <ConnectionDialog mode="save" onClose={()=>setDialog(false)} onConnect={async config=>{saved.push(config);}}/>}
    {!dialog && <div style={{display:"grid",gridTemplateColumns:"320px 1fr",height:500,padding:20,gap:20}}>
      <ObjectExplorer sessionId="s" blockId="b" dbType="cosmosdb" database="analysis" container={container} capabilities={databaseCapabilities("cosmosdb")} onInsert={code=>inserts.push(code)} onContextChange={context=>{contexts.push(context);setContainer(context.container ?? "");}}/>
      <div><BlockScopePicker sessionId="s" blockId="b" dbType="cosmosdb" database="analysis" container={container} onChange={context=>{contexts.push(context);setContainer(context.container ?? "");}}/>
        <DataActions sessionId="s" result={{result_id:"r",variable_name:"df",columns:[{name:"id",dtype:"str"}],row_count:10}} connectionType="cosmosdb" currentConnectionId="cosmos" availableConnections={[{id:"cosmos",name:"Cosmos",db_type:"cosmosdb"},{id:"mongo",name:"Mongo",db_type:"mongodb"},{id:"sql",name:"PostgreSQL",db_type:"postgresql",database:"target"}]} onImported={()=>{}} onChart={()=>{}} onMessage={()=>{}}/>
      </div>
    </div>}
  </>;
}
createRoot(document.getElementById("root")!).render(<Fixture/>);
