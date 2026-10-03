import {useEffect,useRef,useState,useSyncExternalStore} from "react";
import {isTauri} from "@tauri-apps/api/core";
import {getStartupSnapshot,publishStartup,subscribeStartup} from "./startupBridge";
import {startupPhase} from "./splashProtocol";

interface Readiness {runtime:"connecting"|"ready"|"unavailable";runtimeError:string;profileError:string;profile:boolean;layout:boolean;editor:boolean;files:boolean;onRetry:()=>void}
export function useStartupSplash(input:Readiness){
  const snapshot=useSyncExternalStore(subscribeStartup,getStartupSnapshot);
  const [handledAttempt,setHandledAttempt]=useState(snapshot.attempt);
  const retry=useRef(input.onRetry);retry.current=input.onRetry;
  useEffect(()=>{if(snapshot.attempt !== handledAttempt){retry.current();setHandledAttempt(snapshot.attempt);}},[snapshot.attempt,handledAttempt]);
  const phase=startupPhase({runtime:input.runtime,error:input.profileError,profile:input.profile,layout:input.layout,editor:input.editor,files:input.files});
  const error=input.profileError ? `Não foi possível restaurar seu workspace. ${input.profileError}` : `Não foi possível iniciar o ambiente Python. ${input.runtimeError}`;
  useEffect(()=>{
    if(snapshot.attempt !== handledAttempt || snapshot.phase === "error" || snapshot.phase === "ready")return;
    void publishStartup(phase,phase === "error" ? error : undefined).catch(()=>{});
  },[phase,error,snapshot.attempt,snapshot.phase,handledAttempt]);
  return isTauri() && snapshot.phase !== "ready";
}
