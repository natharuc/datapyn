import React,{useState} from "react";
import {createRoot} from "react-dom/client";
import {SettingsDialog} from "../src/SettingsDialog";
import {DEFAULT_SHORTCUTS} from "../src/shortcuts";
import {loadPreferences,savePreferences} from "../src/preferences";
import {applySqlSafetyPreferences} from "../src/safetySettings";
import type {RuntimeTransport} from "../src/runtime";
import {setLocale,translate} from "../src/i18n";
import "../src/styles.css";

setLocale(new URLSearchParams(location.search).get("locale")==="en-US" ? "en-US" : "pt-BR");
const calls:Array<{method:string;params:Record<string,unknown>}>=[];
const transport={request:async<T,>(method:string,params:Record<string,unknown>={})=>{
  calls.push({method,params});
  if(method==="sql.safety.settings.set")localStorage.setItem("sql-safety-fixture-global",String(params.confirm_destructive_sql));
  return {confirm_destructive_sql:localStorage.getItem("sql-safety-fixture-global")!=="false"} as T;
},subscribe:async()=>()=>{}} as RuntimeTransport;

function Fixture(){
  const [preferences,setPreferences]=useState(loadPreferences),[saved,setSaved]=useState(0),[open,setOpen]=useState(true);
  Object.assign(window,{__SQL_SAFETY_SETTINGS_TEST__:{preferences,saved,calls,translate}});
  return <main><button id="open" onClick={()=>setOpen(true)}>Settings</button>{open&&<SettingsDialog preferences={preferences} shortcuts={DEFAULT_SHORTCUTS} initialTab="general" onClose={()=>setOpen(false)} onSave={async(next,_shortcuts,changed)=>{
    const applied=await applySqlSafetyPreferences(transport,next,changed?.has("confirmDestructiveSql")===true);
    savePreferences(applied);setPreferences(applied);setSaved(value=>value+1);setOpen(false);
  }}/>}</main>;
}
createRoot(document.getElementById("root")!).render(<Fixture/>);
