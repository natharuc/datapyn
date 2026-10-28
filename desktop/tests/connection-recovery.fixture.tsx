import React from "react";
import {createRoot} from "react-dom/client";
import {runtime,type ConnectionRecoveryState,type RuntimeEvent} from "../src/runtime";
import {models} from "../src/editorRegistry";
import {translate} from "../src/i18n";
import "../src/styles.css";

// Actual App/Monaco, with all IPC kept in memory. No user profiles or databases.
const locale=new URLSearchParams(location.search).get("locale")==="en-US"?"en-US":"pt-BR";
const calls:Array<{method:string;params:Record<string,unknown>}>=[],failures:string[]=[],listeners=new Set<(event:RuntimeEvent)=>void>();
let mode:"ready"|"error"="ready",recoveryNumber=0;
const send=(event:RuntimeEvent)=>listeners.forEach(listener=>listener(event));
runtime.subscribe=async callback=>{listeners.add(callback);return()=>{listeners.delete(callback);};};
runtime.request=async<T,>(method:string,params:Record<string,unknown>={}):Promise<T>=>{
  calls.push({method,params});
  const responses:Record<string,unknown>={
    "system.info":{protocol_version:1,capabilities:{}},
    "workspace.profiles.state":{active_id:"connection-recovery-fixture",profile:{id:"connection-recovery-fixture",name:"Recovery fixture",path:"memory://fixture",created_at:0},state:{documents:[],activeIndex:0,preferences:{locale,theme:"dark",maximizeFirstBlock:false}}},
    "connections.list":{groups:[],connections:[]},"configurations.defaults.get":{defaults:{}},"transactions.settings.get":{automatic_transactions:true},"sql.safety.settings.get":{confirm_destructive_sql:true},"notifications.settings.get":{settings:{enabled:false,sound:false}},
    "system.flush_workspace":{sessions:[]},"language.diagnostics":{markers:[],status:"complete"},"language.complete":{items:[]},"parameters.scan":{sql_parameters:[],shared_parameters:[]},"pynia.catalog":{agents:[]},"pynia.state":{},
  };
  if(method==="connection.recover"){
    const state:ConnectionRecoveryState={session_id:String(params.session_id),block_id:params.block_id as string|undefined,scope_inherited:params.scope_inherited as boolean,automatic_transactions:params.automatic_transactions!==false,requested_scope:{connection_id:params.connection_id as string|undefined,database:params.database as string|undefined,schema:params.schema as string|undefined},recovery_id:`manual-${++recoveryNumber}`,phase:"recovering"};
    send({event:"connection.recovery",payload:state});
    await new Promise(resolve=>setTimeout(resolve,150));
    const outcome=mode==="ready"?{phase:"ready" as const,session_state_lost:true,state_loss_acknowledged:params.acknowledge_state_loss===true,transaction_state:{automatic_transactions:params.automatic_transactions!==false,pending:false,state:"idle" as const}}:{phase:"error" as const,error:"Network unavailable",acknowledgement_required:false};
    send({event:"connection.recovery",payload:{...state,...outcome}});return {...outcome,recovery_id:state.recovery_id} as T;
  }
  if(method==="session.create")return {session_id:params.session_id} as T;
  if(["session.close","workspace.profiles.patch","connection.idle_timeout","language.diagnostics.cancel","language.prepare"].includes(method))return {} as T;
  if(Object.hasOwn(responses,method))return structuredClone(responses[method]) as T;
  failures.push(method);throw new Error(`Unexpected fixture RPC: ${method}`);
};
const {App,workspace}=await import("../src/App");
const test={calls,failures,snapshot:workspace.getSnapshot,translate:(text:string)=>translate(text,{},locale),
  seed(){const session=workspace.session()!;workspace.updateBlock(session.id,session.focusedBlockId,{code:"SELECT * FROM important_report;",status:"failed",transactionState:{automatic_transactions:true,pending:null,state:"unknown"}});workspace.patchSession(session.id,s=>({...s,variables:[{name:"df",type:"DataFrame",preview:"5000000 rows"}]}));},
  emit(phase:ConnectionRecoveryState["phase"],id="network-loss",acknowledgement_required=false){const session=workspace.session()!;send({event:"connection.recovery",payload:{session_id:session.id,block_id:session.focusedBlockId,scope_inherited:true,automatic_transactions:true,requested_scope:{},recovery_id:id,phase,acknowledgement_required,session_state_lost:phase==="ready"}});},
  mode(value:typeof mode){mode=value;},
  editor(){return models.get(workspace.session()!.focusedBlockId)?.editor?.getValue();},
};
(window as unknown as {__CONNECTION_RECOVERY_TEST__:typeof test}).__CONNECTION_RECOVERY_TEST__=test;
createRoot(document.getElementById("root")!).render(<App/>);
