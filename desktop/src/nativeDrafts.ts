import type { RuntimeTransport } from "./runtime";

export interface NativeDocumentRecord {title:string;filePath?:string;modified?:boolean;document:Record<string,unknown>;sessionId?:string;blockIds?:string[];focusedBlockId?:string;editorViewState?:Record<string,unknown>;maximizedBlockId?:string;[key:string]:unknown}
export interface NativeWorkspaceState {documents:NativeDocumentRecord[];activeIndex:number;preferences?:Record<string,unknown>;shortcuts?:Record<string,unknown>;layout?:Record<string,unknown>;[key:string]:unknown}
export interface WorkspaceProfile {id:string;name:string;path:string;archived?:boolean;created_at:number}
export interface ProfileState {active_id:string;profile:WorkspaceProfile;state?:NativeWorkspaceState|null}
export interface NativeWorkspacePatch {profile_id:string;upserts?:Array<Partial<NativeDocumentRecord>&{sessionId:string;remove_header?:string[]}>;removes?:string[];order?:string[];metadata?:Record<string,unknown>;remove_metadata?:string[]}

function shallowEqual(left:unknown,right:unknown):boolean {
  if(left===right)return true;
  if(!left||!right||typeof left!=="object"||typeof right!=="object"||Array.isArray(left)||Array.isArray(right))return false;
  const a=left as Record<string,unknown>,b=right as Record<string,unknown>,keys=Object.keys(a);
  return keys.length===Object.keys(b).length&&keys.every(key=>a[key]===b[key]);
}
function header(record:NativeDocumentRecord):Record<string,unknown> {
  const {document:_document,...fields}=record;
  return Object.fromEntries(Object.entries(fields).filter(([,value])=>value!==undefined));
}
function recordId(record:NativeDocumentRecord):string {
  if(typeof record.sessionId!=="string"||!record.sessionId)throw new Error("Rascunho nativo sem identificador de sessão.");
  return record.sessionId;
}
function metadata(state:NativeWorkspaceState):Record<string,unknown> {
  return Object.fromEntries(Object.entries(state).filter(([key,value])=>key!=="documents"&&key!=="saved_at"&&value!==undefined));
}
/** Documents are immutable cached DTOs; only small headers/metadata are captured here. */
function capture(state:NativeWorkspaceState):NativeWorkspaceState {
  return {...state,documents:state.documents.map(record=>({...record})),
    ...(state.preferences?{preferences:{...state.preferences}}:{}),...(state.shortcuts?{shortcuts:{...state.shortcuts}}:{}),...(state.layout?{layout:{...state.layout}}:{})};
}
export function diffNativeWorkspace(profileId:string,next:NativeWorkspaceState,previous?:NativeWorkspaceState):NativeWorkspacePatch|undefined {
  const old=new Map((previous?.documents??[]).map(record=>[recordId(record),record]));
  const ids=next.documents.map(recordId);
  if(new Set(ids).size!==ids.length)throw new Error("Identificadores de sessão duplicados no rascunho.");
  const upserts:NonNullable<NativeWorkspacePatch["upserts"]>=[];
  for(const record of next.documents){
    const id=recordId(record),before=old.get(id);old.delete(id);
    if(!before||before.document!==record.document){upserts.push({...header(record),sessionId:id,document:record.document});continue;}
    const fields=header(record),oldFields=header(before);
    if(shallowEqual(fields,oldFields))continue;
    const removed=Object.keys(oldFields).filter(key=>!(key in fields));
    upserts.push({...fields,sessionId:id,...(removed.length?{remove_header:removed}:{})});
  }
  const previousOrder=previous?.documents.map(recordId)??[],orderChanged=ids.length!==previousOrder.length||ids.some((id,index)=>id!==previousOrder[index]);
  const fields=metadata(next),oldFields=previous?metadata(previous):{},changed:Record<string,unknown>={};
  Object.entries(fields).forEach(([key,value])=>{if(!shallowEqual(value,oldFields[key]))changed[key]=value;});
  const removedMeta=Object.keys(oldFields).filter(key=>!(key in fields));
  if(!upserts.length&&!old.size&&!orderChanged&&!Object.keys(changed).length&&!removedMeta.length)return;
  return {profile_id:profileId,...(upserts.length?{upserts}:{}),...(old.size?{removes:[...old.keys()]}:{}),...(orderChanged?{order:ids}:{}),...(Object.keys(changed).length?{metadata:changed}:{}),...(removedMeta.length?{remove_metadata:removedMeta}:{})};
}

/** Incremental immutable snapshots, one serialized queue, captured profile IDs and retained retries. */
export class NativeDrafts {
  private timer?:ReturnType<typeof setTimeout>;
  private pending=new Map<string,NativeWorkspaceState>();
  private acknowledged=new Map<string,NativeWorkspaceState>();
  private writing?:Promise<void>;
  private stopped=false;
  private failures=0;
  constructor(private transport:RuntimeTransport,private onError:(error:unknown)=>void,private delay=500,private retryDelay=100){}
  schedule(profileId:string,state:NativeWorkspaceState){
    if(this.stopped)return;
    this.pending.set(profileId,capture(state));
    this.arm(this.delay);
  }
  private arm(delay:number){
    if(this.timer)clearTimeout(this.timer);
    this.timer=setTimeout(()=>{this.timer=undefined;void this.flush().catch(this.onError);},delay);
  }
  private async drain(){
    while(this.pending.size){
      const [profileId,next]=this.pending.entries().next().value!;
      this.pending.delete(profileId);
      try{
        const patch=diffNativeWorkspace(profileId,next,this.acknowledged.get(profileId));
        if(!patch){this.acknowledged.set(profileId,next);continue;}
        let lastError:unknown;
        for(let attempt=0;attempt<3;attempt++){
          try{await this.transport.request("workspace.profiles.patch",patch as unknown as Record<string,unknown>);lastError=undefined;break;}
          catch(error){lastError=error;if(attempt<2)await new Promise(resolve=>setTimeout(resolve,this.retryDelay*2**attempt));}
        }
        if(lastError!==undefined)throw lastError;
        this.acknowledged.set(profileId,next);this.failures=0;
      }catch(error){
        // A newer snapshot already contains every edit since this failed write.
        if(!this.pending.has(profileId))this.pending.set(profileId,next);
        this.failures++;
        if(!this.stopped)this.arm(Math.min(30_000,Math.max(this.delay,this.retryDelay)*2**Math.min(this.failures,6)));
        throw error;
      }
    }
  }
  async flush(){
    if(this.timer){clearTimeout(this.timer);this.timer=undefined;}
    if(!this.writing)this.writing=this.drain().finally(()=>{this.writing=undefined;});
    await this.writing;
    if(this.pending.size)await this.flush();
  }
  acknowledge(loaded:ProfileState){
    const id=loaded.profile?.id??loaded.active_id;
    if(id&&!this.pending.has(id)){
      this.acknowledged.set(id,loaded.state?capture(loaded.state):{documents:[],activeIndex:0});
      // Profiles are reloaded before use. Avoid retaining every historical code payload in memory.
      for(const other of this.acknowledged.keys())if(other!==id&&!this.pending.has(other))this.acknowledged.delete(other);
    }
  }
  async load(){const loaded=await this.transport.request<ProfileState>("workspace.profiles.state");this.acknowledge(loaded);return loaded;}
  async select(profileId:string){await this.flush();const loaded=await this.transport.request<ProfileState>("workspace.profiles.select",{profile_id:profileId});this.acknowledge(loaded);return loaded;}
  /** Call flush before disposal. Pending work is retained for an explicit final flush. */
  dispose(){this.stopped=true;if(this.timer)clearTimeout(this.timer);this.timer=undefined;}
}
