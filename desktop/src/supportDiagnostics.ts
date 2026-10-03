import { getName, getVersion } from "@tauri-apps/api/app";
import { save } from "@tauri-apps/plugin-dialog";
import { runtime, isDesktop } from "./runtime";
import packageInfo from "../package.json";
import {featureTranslate as t} from "./featureTranslations";

export type IncidentKind = "react_render" | "javascript_error" | "unhandled_rejection" | "runtime_connection";
export interface SupportReport {report_version:number;report_id:string;created_at:string;application:{name:string;version:string|null;license:string;protocol_version:number};system:{os:string;os_release:string;architecture:string};runtime:{python:string;implementation:string;qt_loaded:boolean};packages:Array<{name:string;version:string|null;license:string}>;incident?:{kind:IncidentKind;component:string}}
export async function applicationIdentity() {
  if(isDesktop()) {const [name,version]=await Promise.all([getName(),getVersion()]);return{name,version};}
  return{name:"DataPyn Desktop",version:packageInfo.version};
}
export async function supportReport(kind?:IncidentKind):Promise<SupportReport> {
  const application=await applicationIdentity();
  return runtime.request<SupportReport>("diagnostics.info",{application,...(kind?{incident:{kind,component:"app"}}:{})});
}
export async function saveSupportReport(kind?:IncidentKind) {
  const path=await save({defaultPath:`datapyn-diagnostics-${new Date().toISOString().slice(0,10)}.json`,filters:[{name:t("Diagnóstico JSON"),extensions:["json"]}]});
  if(!path)return undefined;
  const application=await applicationIdentity();
  return runtime.request<{path:string;bytes:number;report_id:string}>("diagnostics.save",{path,application,...(kind?{incident:{kind,component:"app"}}:{})});
}
export async function copySupportReport(kind?:IncidentKind) {
  const report=await supportReport(kind);
  await navigator.clipboard.writeText(JSON.stringify(report,null,2));
  return report.report_id;
}
