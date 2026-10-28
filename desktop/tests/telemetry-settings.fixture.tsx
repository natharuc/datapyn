import React from "react";
import {createRoot} from "react-dom/client";
import {SettingsDialog} from "../src/SettingsDialog";
import {DEFAULT_PREFERENCES} from "../src/preferences";
import {DEFAULT_SHORTCUTS} from "../src/shortcuts";
import {runtime} from "../src/runtime";
import {setLocale,translate} from "../src/i18n";
import "../src/styles.css";

const parameters=new URLSearchParams(location.search),locale=parameters.get("locale")==="en-US"?"en-US":"pt-BR";
setLocale(locale);
const calls:Array<{method:string;params:Record<string,unknown>}>=[];
let status={enabled:false,endpoint:"https://telemetry.datapyn.com/v1/events",provider:"cloudflare",queued:0,sent:0,dropped:0,last_status:"disabled"};
runtime.request=async<T,>(method:string,params:Record<string,unknown>={}):Promise<T>=>{
  calls.push({method,params});
  if(method==="telemetry.settings.get"){
    if(parameters.get("fail")==="load")throw new Error("Diagnostics settings unavailable");
    return structuredClone(status) as T;
  }
  if(method==="telemetry.settings.set"){
    if(!String(params.endpoint).startsWith("https://"))throw new Error("HTTPS required");
    status={...status,enabled:params.enabled===true,endpoint:String(params.endpoint),queued:0,last_status:params.enabled?"idle":"disabled"};
    return structuredClone(status) as T;
  }
  throw new Error(`Unexpected fixture RPC: ${method}`);
};
(window as unknown as {__TELEMETRY_TEST__:unknown}).__TELEMETRY_TEST__={calls,status:()=>status,t:(text:string)=>translate(text,{},locale)};
createRoot(document.getElementById("root")!).render(<SettingsDialog initialTab="telemetry" preferences={DEFAULT_PREFERENCES} shortcuts={DEFAULT_SHORTCUTS} onSave={()=>{throw new Error("Unrelated preferences must not be saved");}} onClose={()=>{}}/>);
