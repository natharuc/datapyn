import React,{useState} from "react";
import {createRoot} from "react-dom/client";
import {OutputPanel} from "../src/OutputPanel";
import {SessionConnectionStatus} from "../src/SessionConnectionStatus";
import {BlockExecutionStatus} from "../src/BlockExecutionStatus";
import {ConnectionDialog} from "../src/ConnectionDialog";
import {applyRuntimeEvent,newSession,type SessionDocument} from "../src/workspace";
import {RuntimeRequestError,runtime,type RuntimeErrorInfo} from "../src/runtime";
import {setLocale,translate} from "../src/i18n";
import "../src/styles.css";

const search=new URLSearchParams(location.search),locale=search.get("locale")==="en-US"?"en-US":"pt-BR";
setLocale(locale);document.documentElement.dataset.theme=search.get("theme")==="light"?"light":"dark";
const missing:RuntimeErrorInfo={category:"not_found",title:"Objeto não encontrado",message:"Invalid object name 'missing_view'.",technical_details:'ProgrammingError: 42S02 / 208\n  File "kernel.py", line 20, in execute\n<diagnostic-marker>'};
const network:RuntimeErrorInfo={category:"network",title:"Execução interrompida",message:"A conexão foi restabelecida. A execução interrompida não foi repetida.",technical_details:'ConnectionLostError: 08S01\n  File "driver.py", line 15, in execute'};
const auth:RuntimeErrorInfo={category:"authentication",title:"Falha de autenticação",message:"Login failed for user.",technical_details:'InterfaceError: SQLSTATE 28000 (18456)\n  File "driver.py", line 8, in connect'};
let sequence=0,copyFailure=false;
const copied:string[]=[],calls:string[]=[];
Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async(text:string)=>{if(copyFailure)throw new Error("synthetic clipboard rejection");copied.push(text);}}});
runtime.request=async<T,>(method:string):Promise<T>=>{
  calls.push(method);
  if(method==="system.info")return {protocol_version:1,capabilities:{platform:"win32"}} as T;
  if(method==="connection.test")throw new RuntimeRequestError("authentication_failed","Authentication failed",undefined,auth);
  throw new Error(`Unexpected fixture RPC: ${method}`);
};
function failed(session:SessionDocument,info:RuntimeErrorInfo){
  const execution_id=`failure-${++sequence}`;
  session={...session,currentExecutionId:execution_id,currentBlockId:session.focusedBlockId,blocks:session.blocks.map(block=>({...block,status:"running"}))};
  return applyRuntimeEvent(session,{event:"execution.finished",payload:{session_id:session.id,execution_id,status:"failed",duration_ms:20,error:info.message,error_info:info,results:[],variables:[]}});
}
function initial(){
  let value=newSession();value.blocks[0].block_name="analysis";
  value.currentExecutionId="python-output";value.currentBlockId=value.focusedBlockId;
  value=applyRuntimeEvent(value,{event:"execution.output",payload:{session_id:value.id,execution_id:"python-output",stream:"stdout",text:"Python output: 2 rows\n"}});
  return failed(failed(value,network),missing);
}
function Fixture(){
  const [session,setSession]=useState(initial),[dialog,setDialog]=useState(false),[connection,setConnection]=useState(true);
  Object.assign(window,{__RUNTIME_ERRORS_TEST__:{copied,calls,missing,auth,translate:(text:string)=>translate(text,{},locale),snapshot:()=>session,
    fail:()=>setSession(value=>failed(value,missing)),clipboardFailure:(value:boolean)=>{copyFailure=value;},openConnectionDialog:()=>setDialog(true)}});
  return <main style={{height:"100%",padding:24,display:"flex",flexDirection:"column",gap:12}}>
    {connection&&<SessionConnectionStatus state={{phase:"error",name:"Shared",error:auth.message,errorInfo:auth}} onRetry={()=>setConnection(false)}/>}
    <section style={{flex:1,minHeight:0,border:"1px solid var(--border)",display:"flex",flexDirection:"column"}}>
      <header style={{padding:"10px 14px",borderBottom:"1px solid var(--border)",display:"flex",alignItems:"center",justifyContent:"space-between"}}><span>{translate("Saída")}</span><BlockExecutionStatus block={session.blocks[0]}/></header>
      <OutputPanel session={session}/>
    </section>
    {dialog&&<ConnectionDialog initial={{db_type:"sqlserver",host:"fixture.invalid",port:1433,database:"ESIM",username:"fixture",name:"Shared",sqlserver_auth_mode:"sql_password"}} mode="save" onClose={()=>setDialog(false)} onConnect={async()=>{throw new RuntimeRequestError("authentication_failed","Authentication failed",undefined,auth);}}/>}
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture/>);
