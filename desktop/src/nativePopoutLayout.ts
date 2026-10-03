import {invoke,isTauri} from "@tauri-apps/api/core";
import {listen,type UnlistenFn} from "@tauri-apps/api/event";
import type {SerializedDockview} from "dockview-react";

export interface NativePopoutPosition {left:number;top:number;width:number;height:number}
export interface NativePopoutPort {
  load():Promise<Record<string,NativePopoutPosition>>;
  subscribe(label:string,changed:()=>void):Promise<()=>void>;
  close(label:string):Promise<void>;
}
export function nativePopoutLabel(view:Window):string|undefined {
  try {
    const label=(view as Window & {__DATAPYN_NATIVE_LABEL__?:unknown}).__DATAPYN_NATIVE_LABEL__;
    return typeof label==="string" && /^dock-popout-\d+$/.test(label) ? label : undefined;
  } catch {return undefined;}
}
function same(left:NativePopoutPosition|undefined,right:NativePopoutPosition|undefined){
  return left===right || !!left && !!right && left.left===right.left && left.top===right.top && left.width===right.width && left.height===right.height;
}
function groupIds(window:NonNullable<SerializedDockview["popoutGroups"]>[number]):Set<string> {
  const ids=new Set<string>();
  const visit=(node:unknown)=>{
    if(!node || typeof node!=="object")return;
    const value=node as {type?:string;data?:unknown};
    if(value.type==="branch" && Array.isArray(value.data))value.data.forEach(visit);
    else if(value.type==="leaf" && value.data && typeof value.data==="object"){
      const id=(value.data as {id?:unknown}).id;if(typeof id==="string")ids.add(id);
    }
  };
  if(window.data)ids.add(window.data.id);
  if(window.grid)visit(window.grid.root);
  return ids;
}
/** WebView2 screenX/Y report the client origin; serialized docks need native outer bounds. */
export function withNativePopoutPositions<T extends SerializedDockview>(layout:T,popouts:readonly {id:string;window:Window}[],positions:ReadonlyMap<string,NativePopoutPosition>):T {
  if(!layout.popoutGroups?.length)return layout;
  let changed=false;
  const windows=layout.popoutGroups.map(entry=>{
    const ids=groupIds(entry),live=popouts.find(item=>ids.has(item.id)),label=live && nativePopoutLabel(live.window),position=label ? positions.get(label) : undefined;
    if(!position)return entry;
    changed=true;return {...entry,position:{...position}};
  });
  return changed ? {...layout,popoutGroups:windows} : layout;
}

const activeTrackers=new Set<NativePopoutLayoutTracker>();
const ownership=new Map<string,Set<symbol>>();
/** Flush before close/profile switch/named-layout save, then take the synchronous dock snapshot. */
export async function flushNativePopoutLayouts(){await Promise.all([...activeTrackers].map(tracker=>tracker.flush()));}

const port:NativePopoutPort={
  load:()=>invoke("popout_layout"),
  subscribe:async(label,changed)=>{
    const results=await Promise.allSettled(["tauri://move","tauri://resize","tauri://scale-change"].map(event=>listen(event,changed,{target:{kind:"Window",label}})));
    const callbacks:UnlistenFn[]=results.flatMap(result=>result.status==="fulfilled" ? [result.value] : []);
    return ()=>callbacks.forEach(unlisten=>unlisten());
  },
  close:label=>invoke("close_popout",{label}),
};
interface Binding {label:string;token:symbol;cleanup?:()=>void}
export class NativePopoutLayoutTracker {
  private positions=new Map<string,NativePopoutPosition>();
  private bindings=new Map<Window,Binding>();
  private timer?:ReturnType<typeof setTimeout>;
  private pending:Promise<void>=Promise.resolve();
  constructor(private readonly changed:()=>void,private readonly native:NativePopoutPort=port){}
  bind(view:Window):()=>void {
    const label=nativePopoutLabel(view);
    if(!label)return ()=>{};
    const binding:Binding={label,token:Symbol(label)};
    this.bindings.set(view,binding);activeTrackers.add(this);
    const owners=ownership.get(label) ?? new Set<symbol>();owners.add(binding.token);ownership.set(label,owners);
    const update=()=>this.schedule();
    void this.native.subscribe(label,update).then(cleanup=>{
      if(this.bindings.get(view)===binding)binding.cleanup=cleanup;else cleanup();
    }).catch(()=>{});
    this.schedule(0);
    let released=false;
    return ()=>{
      if(released)return;released=true;
      binding.cleanup?.();
      if(this.bindings.get(view)===binding)this.bindings.delete(view);
      const owners=ownership.get(label);owners?.delete(binding.token);if(!owners?.size)ownership.delete(label);
      if(!this.bindings.size)activeTrackers.delete(this);
      // Dockview first rehomes the portal DOM. Closing its browser Window does
      // not close the Tauri host; destroy it only after that synchronous transfer.
      queueMicrotask(()=>{if(!ownership.has(label))void this.native.close(label).catch(()=>{});});
    };
  }
  private schedule(delay=150){
    if(this.timer)clearTimeout(this.timer);
    this.timer=setTimeout(()=>{this.timer=undefined;void this.flush().catch(()=>{});},delay);
  }
  flush():Promise<void> {
    if(this.timer){clearTimeout(this.timer);this.timer=undefined;}
    this.pending=this.pending.catch(()=>{}).then(async()=>{
      if(!this.bindings.size)return;
      const loaded=await this.native.load();
      const current=new Set([...this.bindings.values()].map(binding=>binding.label));
      let changed=false;
      for(const label of current){
        const position=loaded[label];if(!position)continue;
        if(!same(position,this.positions.get(label))){this.positions.set(label,position);changed=true;}
      }
      for(const label of this.positions.keys())if(!current.has(label))this.positions.delete(label);
      if(changed)this.changed();
    });
    return this.pending;
  }
  capture<T extends SerializedDockview>(layout:T,popouts:readonly {id:string;window:Window}[]):T {
    return withNativePopoutPositions(layout,popouts,this.positions);
  }
  dispose(){
    if(this.timer){clearTimeout(this.timer);this.timer=undefined;}
    for(const [view,binding] of this.bindings){
      binding.cleanup?.();
      const owners=ownership.get(binding.label);owners?.delete(binding.token);if(!owners?.size)ownership.delete(binding.label);
      this.bindings.delete(view);
      queueMicrotask(()=>{if(!ownership.has(binding.label))void this.native.close(binding.label).catch(()=>{});});
    }
    activeTrackers.delete(this);this.positions.clear();
  }
}
export function createNativePopoutLayoutTracker(changed:()=>void){
  return isTauri() ? new NativePopoutLayoutTracker(changed) : undefined;
}
