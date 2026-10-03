import {invoke,isTauri} from "@tauri-apps/api/core";
import {listen} from "@tauri-apps/api/event";
import {acceptStartupSnapshot,INITIAL_STARTUP,STARTUP_MESSAGES,type StartupPhase,type StartupSnapshot} from "./splashProtocol";

let snapshot=INITIAL_STARTUP;
let fatal=false;
const subscribers=new Set<()=>void>();
const pending=new Map<string,Promise<void>>();
function update(next:StartupSnapshot){const accepted=acceptStartupSnapshot(snapshot,next);if(accepted !== snapshot){snapshot=accepted;subscribers.forEach(fn=>fn());}}
export const subscribeStartup=(fn:()=>void)=>{subscribers.add(fn);return()=>{subscribers.delete(fn);};};
export const getStartupSnapshot=()=>snapshot;

/** Installed before importing React so bundle/render failures can still be retried. */
export async function initializeStartup(){
  if(!isTauri())return;
  await listen<StartupSnapshot>("splash-retry",event=>{update(event.payload);if(fatal)window.location.reload();});
  update(await invoke<StartupSnapshot>("splash_state"));
}

export function publishStartup(phase:StartupPhase,message=STARTUP_MESSAGES[phase]):Promise<void> {
  if(!isTauri() || snapshot.phase === "ready" || snapshot.phase === "error" || (fatal && phase !== "error"))return Promise.resolve();
  if(snapshot.phase === phase && snapshot.message === message)return Promise.resolve();
  const attempt=snapshot.attempt,key=JSON.stringify([attempt,phase,message]);
  const existing=pending.get(key);if(existing)return existing;
  const publishing=invoke<StartupSnapshot>("splash_publish",{phase,message,attempt}).then(update).finally(()=>pending.delete(key));
  pending.set(key,publishing);return publishing;
}

export function startupFailed(){
  fatal=true;
  void publishStartup("error","A interface encontrou um erro ao iniciar. Tente novamente para recuperar suas análises salvas.").catch(()=>{});
}
