import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import * as monaco from "monaco-editor/editor/editor.api.js";
import { MonacoBlock } from "../src/MonacoBlock";
import { models, setCompletionContext, triggerLocalSuggestions,forceAutocomplete } from "../src/editorRegistry";
import { runtime, type Language, type RuntimeTransport } from "../src/runtime";
import type { CompletionContext, LanguageCompletion } from "../src/editorLanguage";
import type { EditorPreferences } from "../src/editorRegistry";
import "../src/docking.css";
import "../src/styles.css";
import { SessionCompletionIndex, SessionLanguageContexts } from "../src/sessionCompletion";
import { newSession, type ConnectionConfig } from "../src/workspace";
import { BlockScopePicker } from "../src/BlockScopePicker";
import type { ExplorerContext } from "../src/explorer";

// A deliberately controlled IPC boundary, with the production Monaco component,
// providers, registry and request gates running unchanged in a real browser.
const calls: Array<{ method: string; params?: Record<string, unknown>; resolved?: boolean; resolve?: (value: unknown) => void }> = [];
runtime.request = ((method: string, params?: Record<string, unknown>) => {
  const call = { method, params } as typeof calls[number]; calls.push(call);
  if (method === "language.complete") return new Promise(resolve => { call.resolve = resolve; });
  if (method === "explorer.list") {
    const schema=Boolean(params?.node),names=schema?["public","finance","reports"]:["main","analytics","legacy","Produção Financeiro"];
    return Promise.resolve({nodes:names.map(name=>({id:name,name,kind:schema?"schema":"database",has_children:true})),context:{database:params?.database,schema:params?.schema}});
  }
  return Promise.resolve({});
}) as RuntimeTransport["request"];

interface Configuration { language: Language; code: string; preferences?: EditorPreferences; context?:CompletionContext; picker?:boolean }
let configure: (value: Configuration) => void;
function Fixture() {
  const [configuration, update] = useState<Configuration>({language:"sql",code:"",preferences:{autocomplete:true}});
  configure = update;
  async function selectScope(context:ExplorerContext) {
    test.scopeChanges.push(context);
    const current=configuration.context!,database=context.database ?? current.database,schema=context.schema ?? "public";
    const cold={...current,database,schema,tables:[],schemaSnapshot:undefined};
    setCompletionContext("completion-test",cold);update(value=>({...value,context:cold}));
    await new Promise(resolve=>setTimeout(resolve,30));
    const name=schema==="finance"?"finance_id":database==="analytics"?"analytics_id":"customer_id",key=`${schema}.customers`;
    const resolved={...cold,tables:[key],schemaSnapshot:{db_type:current.dbType,database,current_schema:schema,tables:{[key]:{name:"customers",schema,columns:[{name,type:"INTEGER"}]}}}};
    setCompletionContext("completion-test",resolved);update(value=>({...value,context:resolved}));
  }
  return <>
    {configuration.picker && <div className="block-header"><span className="block-index">01</span><span className="language-select">SQL</span><input className="block-name" aria-label="Test block name" value="customers" readOnly/>
      <BlockScopePicker sessionId="test-session" connectionId={configuration.context?.connectionId} dbType={configuration.context?.dbType} database={configuration.context?.database} schema={configuration.context?.schema} onChange={selectScope} />
    </div>}
    <MonacoBlock id="completion-test" language={configuration.language} code={configuration.code} preferences={configuration.preferences} height={250} onChange={code=>update(value=>({...value,code}))} onFocus={()=>{}} onReady={()=>{test.ready=true;}} />
  </>;
}
const test = {
  ready: false, calls, monaco,scopeChanges:[] as ExplorerContext[],
  editor: () => models.get("completion-test")!.editor!,
  async configure({code,language="sql",context,preferences={autocomplete:true},picker=false}:{code:string;language?:Language;context:CompletionContext;preferences?:EditorPreferences;picker?:boolean}) {
    this.editor().trigger("test","hideSuggestWidget",{});
    const cursor=code.indexOf("|");
    if(cursor<0)throw new Error("Fixture source must include | to mark the cursor");
    setCompletionContext("completion-test",context);
    configure({language,code:code.slice(0,cursor)+code.slice(cursor+1),preferences,context,picker});
    await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));
    // A Windows model normalizes LF to CRLF. Set the cursor by line/UTF-16
    // column so the fixture exercises multiline source with the same offsets.
    const preceding=code.slice(0,cursor).split(/\r\n|\r|\n/);
    const editor=this.editor(); editor.focus(); editor.setPosition({lineNumber:preceding.length,column:preceding.at(-1)!.length+1});
  },
  context(context:CompletionContext){setCompletionContext("completion-test",context);},
  async defaultScope({dbType,database,schema,transient=false}:{dbType:ConnectionConfig["db_type"];database:string;schema:string;transient?:boolean}) {
    const session=newSession();session.id="default-scope";session.blocks[0].id="completion-test";
    if(transient)session.connection={db_type:dbType,database,host:"",username:"",port:0};
    else session.savedConnectionId="saved-connection";
    const contexts=new SessionLanguageContexts(),index=new SessionCompletionIndex();
    const cold=index.context(session,"completion-test",contexts)!;
    await this.configure({code:"SELECT c.| FROM customers c",context:cold});
    return {deliver:()=>{
      const key=`${schema}.customers`;
      contexts.accept({event:"language.context_updated",payload:{session_id:session.id,version:1,connection_id:transient?"transient":session.savedConnectionId,database,schema,variables:{},metadata_state:"ready",requested_scope:{connection_id:cold.connectionId ?? null,database:cold.database ?? null,schema:cold.schema ?? null},schema_snapshot:{db_type:dbType,database,current_schema:schema,tables:[{key,name:"customers",schema}],columns:{[key]:[{name:"resolved_default_id",type:"INTEGER"}]}}}});
      const resolved=index.context(session,"completion-test",contexts)!;
      this.context(resolved);return {database:resolved.schemaSnapshot?.database,schema:resolved.schemaSnapshot?.current_schema,tables:resolved.tables};
    }};
  },
  suggest(){triggerLocalSuggestions("completion-test");},
  force(){forceAutocomplete("completion-test");},
  reply(index:number,items:LanguageCompletion[]){const call=calls[index];if(!call.resolve)throw new Error("Not a completion request");call.resolved=true;call.resolve({items});},
  labels(){
    return [...document.querySelectorAll<HTMLElement>(".suggest-widget .monaco-list-row")].filter(row=>row.checkVisibility()).map(row=>row.querySelector(".label-name")?.textContent??"");
  },
};
declare global { interface Window { completionTest:typeof test } }
window.completionTest=test;
createRoot(document.getElementById("root")!).render(<Fixture />);
