import {useCallback,useEffect,useRef,useState} from "react";
import {isTauri} from "@tauri-apps/api/core";
import {availableMonitors,getCurrentWindow,PhysicalPosition,PhysicalSize} from "@tauri-apps/api/window";
import type {UnlistenFn} from "@tauri-apps/api/event";
import {sameWindowLayout,WindowLayoutController,type MainWindowLayout} from "./windowLayout";

let controller:WindowLayoutController|undefined;
let startupRestore:Promise<MainWindowLayout|undefined>|undefined;
function nativeController(){
  if(!controller){
    const native=getCurrentWindow();
    controller=new WindowLayoutController({
      bounds:async()=>{
        const [position,size,outerSize,scaleFactor]=await Promise.all([
          native.outerPosition(),native.innerSize(),native.outerSize(),native.scaleFactor()]);
        // Read state last so maximize/minimize resize events cannot persist transient bounds.
        const [maximized,minimized]=await Promise.all([native.isMaximized(),native.isMinimized()]);
        return {position,size,outerSize,scaleFactor,maximized,minimized};
      },
      monitors:availableMonitors,
      apply:async(plan)=>{
        // Remove maximization first; setSize targets the restored client area.
        if(await native.isMaximized())await native.unmaximize();
        await native.setMinSize(new PhysicalSize(plan.minimum.width,plan.minimum.height));
        await native.setSize(new PhysicalSize(plan.layout.size.width,plan.layout.size.height));
        await native.setPosition(new PhysicalPosition(plan.layout.position.x,plan.layout.position.y));
        if(plan.layout.maximized)await native.maximize();
      },
    });
  }
  return controller;
}

/** Restore once per app startup; switching workspaces keeps the current native window. */
export function useWindowLayout(initial:unknown,profileKey:string|undefined,onChange:(layout:MainWindowLayout)=>void){
  const desktop=isTauri(),[ready,setReady]=useState(!desktop);
  const input=useRef(initial);input.current=initial;
  const changed=useRef(onChange);changed.current=onChange;
  const activeProfile=useRef(profileKey);activeProfile.current=profileKey;
  const delivered=useRef<MainWindowLayout>();
  const timer=useRef<ReturnType<typeof setTimeout>>();
  const generation=useRef(0);
  const capture=useCallback(async()=>{
    if(timer.current){clearTimeout(timer.current);timer.current=undefined;}
    if(!isTauri() || !activeProfile.current)return undefined;
    const key=activeProfile.current,token=generation.current,layout=await nativeController().capture();
    if(layout && activeProfile.current===key && generation.current===token && !sameWindowLayout(layout,delivered.current)){
      delivered.current=layout;changed.current(layout);
    }
    return layout;
  },[]);
  useEffect(()=>{
    if(!desktop || !profileKey)return;
    const token=++generation.current,native=getCurrentWindow(),engine=nativeController();
    let prepared=false,disposed=false;
    const listeners:UnlistenFn[]=[];
    delivered.current=undefined;
    const schedule=()=>{
      if(disposed || !prepared || engine.restoring)return;
      if(timer.current)clearTimeout(timer.current);
      timer.current=setTimeout(()=>{timer.current=undefined;void capture().catch(()=>{});},250);
    };
    const register=async()=>{
      const results=await Promise.allSettled([native.onMoved(schedule),native.onResized(schedule),native.onScaleChanged(schedule)]);
      for(const result of results)if(result.status==="fulfilled"){
        if(disposed)result.value();else listeners.push(result.value);
      }
    };
    void register();
    // Shared startup promise also prevents duplicate mutations under React StrictMode.
    if(!startupRestore)startupRestore=engine.restore(input.current).catch(()=>undefined);
    void startupRestore.then(async()=>{
      if(disposed)return;
      prepared=true;
      await capture().catch(()=>undefined);
      if(!disposed && generation.current===token)setReady(true);
    });
    return ()=>{
      disposed=true;
      generation.current++;
      if(timer.current){clearTimeout(timer.current);timer.current=undefined;}
      for(const unlisten of listeners)unlisten();
    };
  },[desktop,profileKey,capture]);
  return {ready,capture};
}
