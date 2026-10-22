import React from "react";
import {createRoot} from "react-dom/client";
import {runtime,type RuntimeEvent} from "../src/runtime";
import {models,focusEditor} from "../src/editorRegistry";
import {translate} from "../src/i18n";
import "../src/styles.css";

// The real App/Monaco/Dockview run against an isolated in-memory IPC fixture.
// No Tauri window, backend process, user profile or database is accessed.
const locale=new URLSearchParams(location.search).get("locale")==="en-US"?"en-US":"pt-BR";
const calls:Array<{method:string;params:Record<string,unknown>}>=[];
const failures:string[]=[];
const listeners=new Set<(event:RuntimeEvent)=>void>();
runtime.subscribe=async callback=>{listeners.add(callback);return()=>{listeners.delete(callback);};};
runtime.request=async<T,>(method:string,params:Record<string,unknown>={}):Promise<T>=>{
  calls.push({method,params});
  const responses:Record<string,unknown>={
    "system.info":{protocol_version:1,capabilities:{}},
    "workspace.profiles.state":{active_id:"closed-tabs-fixture",profile:{id:"closed-tabs-fixture",name:"Closed tabs fixture",path:"memory://fixture",created_at:0},state:{documents:[],activeIndex:0,preferences:{locale,theme:"dark",maximizeFirstBlock:false},shortcuts:{reloadSchema:"Ctrl+Shift+T"}}},
    "connections.list":{groups:[],connections:[]},
    "configurations.defaults.get":{defaults:{}},
    "transactions.settings.get":{automatic_transactions:true},
    "sql.safety.settings.get":{confirm_destructive_sql:true},
    "notifications.settings.get":{settings:{enabled:false,sound:false}},
    "system.flush_workspace":{sessions:[]},
    "language.diagnostics":{markers:[],status:"complete"},
    "language.complete":{items:[]},
    "parameters.scan":{sql_parameters:[],shared_parameters:[]},
    "pynia.catalog":{agents:[]},
    "pynia.state":{},
  };
  if(method==="session.create")return {session_id:params.session_id} as T;
  if(method==="session.close" || method==="workspace.profiles.patch" || method==="connection.idle_timeout" || method==="language.diagnostics.cancel" || method==="language.prepare")return {} as T;
  if(Object.hasOwn(responses,method))return structuredClone(responses[method]) as T;
  failures.push(method);throw new Error(`Unexpected fixture RPC: ${method}`);
};

const {App,workspace}=await import("../src/App");
const test={
  calls,
  failures,
  snapshot:workspace.getSnapshot,
  translate:(text:string)=>translate(text,{},locale),
  current:()=>workspace.session(),
  seed(title:string,code:string,modified=false){
    const current=workspace.session()!;
    workspace.updateBlock(current.id,current.focusedBlockId,{code});
    workspace.patchSession(current.id,session=>({...session,title,modified}));
    return current.id;
  },
  saved(){const current=workspace.session()!;workspace.patchSession(current.id,session=>({...session,modified:false}));},
  select(line:number,column:number,endLine=line,endColumn=column){
    const current=workspace.session()!,editor=models.get(current.focusedBlockId)!.editor!;
    editor.setSelection({startLineNumber:line,startColumn:column,endLineNumber:endLine,endColumn});
    editor.revealLineInCenter(line);focusEditor(current.focusedBlockId);
    return editor.saveViewState();
  },
  editor(){
    const current=workspace.session()!,editor=models.get(current.focusedBlockId)?.editor;
    return editor?{code:editor.getValue(),selection:editor.getSelection(),scrollTop:editor.getScrollTop(),focused:editor.hasTextFocus()}:undefined;
  },
};
(window as unknown as {__CLOSED_TABS_TEST__:typeof test}).__CLOSED_TABS_TEST__=test;
createRoot(document.getElementById("root")!).render(<App/>);
