import { describe, expect, it, vi } from "vitest";
import { applyExecutionContextChange, applyRuntimeEvent, newBlock, newSession, WorkspaceController, type ConnectionConfig } from "./workspace";
import { completionConnectionScope } from "./sessionCompletion";
import { ScopePreparation } from "./ScopePreparation";
import { prepareExecutionContextAfterEvent } from "./executionContextRefresh";
import type { ExecutionContextChange, ExecutionFinished, RuntimeEvent, RuntimeTransport } from "./runtime";

const config: ConnectionConfig = {db_type:"databricks",host:"local",port:443,username:"user",database:"old_catalog",schema:"old_schema"};
const change = (requested: ExecutionContextChange["requested_scope"] = {connection_id:"main",database:"old_catalog",schema:"old_schema"}): ExecutionContextChange => ({
  connection_id:requested.connection_id, requested_scope:requested,
  previous:{db_type:"databricks",database:"old_catalog",schema:"old_schema"},current:{db_type:"databricks",database:"new_catalog",schema:"new_schema"},
});
function session() {
  const value=newSession();value.savedConnectionId="main";value.database="old_catalog";value.schema="old_schema";value.connection=config;
  value.connectionState={phase:"ready",connectionId:"main",scope:{database:"old_catalog",schema:"old_schema"}};
  return value;
}
class Transport implements RuntimeTransport {
  executions:Record<string,unknown>[]=[];
  listener?:(event:RuntimeEvent)=>void;
  async subscribe(listener:(event:RuntimeEvent)=>void){this.listener=listener;return()=>{};}
  async request<T>(method:string,params:Record<string,unknown>={}):Promise<T>{
    if(method==="execution.run")this.executions.push(params);
    return (method==="system.info"?{protocol_version:1,capabilities:{}}:method==="connection.connect"?{config,database:config.database,schema:config.schema}:{}) as T;
  }
  finish(index:number,context_change?:ExecutionContextChange,status:ExecutionFinished["status"]="succeeded"){
    const request=this.executions[index];this.listener?.({event:"execution.finished",payload:{session_id:String(request.session_id),execution_id:String(request.execution_id),block_id:String(request.block_id),status,duration_ms:1,results:[],variables:[],context_change}});
  }
}

describe("SQL commands update the executed block context",()=>{
  it("updates inherited tab scope atomically and preserves every pinned peer and profile",()=>{
    const before=session(),running=before.blocks[0],inherited=newBlock(),schemaOnly={...newBlock(),schema:"private"},sameConnection={...newBlock(),connection_id:"main"},other={...newBlock(),connection_id:"other"},pinned={...newBlock(),database_name:"pinned_catalog",schema:"pinned_schema"};
    before.blocks.push(inherited,schemaOnly,sameConnection,other,pinned);before.currentExecutionId="execution";before.currentBlockId=running.id;
    const next=applyRuntimeEvent(before,{event:"execution.finished",payload:{session_id:before.id,execution_id:"execution",status:"succeeded",duration_ms:12,results:[],variables:[],context_change:change()}});
    expect(next).toMatchObject({database:"new_catalog",schema:"new_schema",modified:true,connectionState:{scope:{database:"new_catalog",schema:"new_schema"}}});
    expect(next.blocks[0]).toMatchObject({status:"succeeded",duration_ms:12});expect(next.connection).toBe(config);expect(config).toMatchObject({database:"old_catalog",schema:"old_schema"});
    expect(completionConnectionScope(next,next.blocks[1])).toMatchObject({database:"new_catalog",schema:"new_schema"});
    expect(completionConnectionScope(next,next.blocks[2])).toMatchObject({database:"old_catalog",schema:"private"});
    expect(completionConnectionScope(next,next.blocks[3])).toMatchObject({database:"old_catalog",schema:"old_schema"});
    expect(next.blocks[4]).toBe(other);expect(next.blocks[5]).toBe(pinned);
  });
  it.each([{connection_id:"other"},{database_name:"old_catalog",schema:"old_schema"},{connection_id:"main"}])("keeps a custom block isolated: %j",override=>{
    const before=session(),block={...before.blocks[0],...override},peer=newBlock();before.blocks=[block,peer];
    const scope=completionConnectionScope(before,block),next=applyExecutionContextChange(before,block.id,change({connection_id:scope.connectionId,database:scope.database,schema:scope.schema}));
    expect(next).toMatchObject({database:"old_catalog",schema:"old_schema"});expect(next.blocks[0]).toMatchObject({database_name:"new_catalog",schema:"new_schema"});expect(next.blocks[1]).toBe(peer);expect(next.connection).toBe(config);
  });
  it("reflects a successful USE even when a later statement fails",()=>{
    const before=session();before.currentBlockId=before.blocks[0].id;before.currentExecutionId="partial";
    expect(applyRuntimeEvent(before,{event:"execution.finished",payload:{session_id:before.id,execution_id:"partial",status:"failed",duration_ms:1,error:"Later statement failed",results:[],variables:[],context_change:change()}})).toMatchObject({database:"new_catalog",schema:"new_schema",blocks:[{status:"failed"}]});
  });
  it("ignores unchanged context and stale scope or execution identity",()=>{
    const before=session(),block=before.blocks[0];before.currentBlockId=block.id;before.currentExecutionId="current";
    expect(applyExecutionContextChange(before,block.id,{...change(),current:change().previous})).toBe(before);
    expect(applyExecutionContextChange(before,block.id,change({connection_id:"wrong",database:"old_catalog",schema:"old_schema"}))).toBe(before);
    expect(applyExecutionContextChange(before,block.id,change({connection_id:"main",database:null,schema:null}))).toBe(before);
    expect(applyRuntimeEvent(before,{event:"execution.finished",payload:{session_id:before.id,execution_id:"stale",status:"succeeded",duration_ms:1,results:[],variables:[],context_change:change()}})).toBe(before);
  });
  it("dispatches queued inherited blocks with new scope while a pinned block keeps its captured choice",async()=>{
    const transport=new Transport(),controller=new WorkspaceController(transport,undefined,{nativePersistence:true}),before=controller.session()!,first=before.blocks[0];
    try {
      await controller.connectSaved(before.id,"main");controller.updateBlock(before.id,first.id,{code:"USE CATALOG new_catalog; USE SCHEMA new_schema"});
      const inherited=controller.addBlock(before.id,"sql","SELECT 1"),pinned=controller.addBlock(before.id,"sql","SELECT 2");controller.updateBlock(before.id,pinned.id,{schema:"private"});
      const queue=controller.runAll(before.id);await vi.waitFor(()=>expect(transport.executions).toHaveLength(1));
      expect(transport.executions[0].scope_inherited).toBe(true);
      controller.focusBlock(before.id,pinned.id);controller.createSession();transport.finish(0,change());
      await vi.waitFor(()=>expect(transport.executions).toHaveLength(2));expect(transport.executions[1]).toMatchObject({block_id:inherited.id,database:"new_catalog",schema:"new_schema",scope_inherited:true});transport.finish(1);
      await vi.waitFor(()=>expect(transport.executions).toHaveLength(3));expect(transport.executions[2]).toMatchObject({block_id:pinned.id,database:"old_catalog",schema:"private",scope_inherited:false});transport.finish(2);await queue;
      expect(controller.session(before.id)).toMatchObject({database:"new_catalog",schema:"new_schema",focusedBlockId:pinned.id});
    } finally {controller.dispose();}
  });
  it("publishes the terminal status and changed scope together to observers",async()=>{
    const transport=new Transport(),controller=new WorkspaceController(transport,undefined,{nativePersistence:true}),before=controller.session()!,block=before.blocks[0];
    try {
      await controller.connectSaved(before.id,"main");controller.updateBlock(before.id,block.id,{code:"USE CATALOG new_catalog"});const queue=controller.runBlock(before.id,block.id);await vi.waitFor(()=>expect(transport.executions).toHaveLength(1));
      const observations:Array<{status:string;database?:string}>=[];const unsubscribe=controller.subscribe(()=>{const value=controller.session(before.id)!;observations.push({status:value.blocks[0].status,database:value.database});});
      transport.finish(0,change());unsubscribe();await queue;
      expect(observations).toEqual([{status:"succeeded",database:"new_catalog"}]);
    }finally{controller.dispose();}
  });
  it.each(["frontend_first","workspace_first"])("preloads the updated scope independently of subscriber order: %s",async order=>{
    const transport=new Transport(),controller=new WorkspaceController(transport,undefined,{nativePersistence:true}),before=controller.session()!,block=before.blocks[0];
    const requests:Record<string,unknown>[]=[];
    const preparation=new ScopePreparation({request:async<T>(_method:string,params:Record<string,unknown>={})=>{requests.push(params);return {status:"queued",context_version:1} as T;}});
    try{
      await controller.connectSaved(before.id,"main");controller.updateBlock(before.id,block.id,{code:"USE CATALOG new_catalog"});const queue=controller.runBlock(before.id,block.id);await vi.waitFor(()=>expect(transport.executions).toHaveLength(1));
      const workspaceListener=transport.listener!;let refresh:Promise<void>|undefined;
      transport.listener=event=>{
        if(event.event!=="execution.finished")throw new Error("fixture");
        const prepare=()=>{refresh=prepareExecutionContextAfterEvent(event.payload,id=>controller.session(id),preparation);};
        if(order==="frontend_first")prepare();workspaceListener(event);if(order==="workspace_first")prepare();
      };
      transport.finish(0,change());await refresh;await queue;
      expect(requests).toHaveLength(1);expect(requests[0]).toMatchObject({block_id:block.id,database:"new_catalog",schema:"new_schema",scope_inherited:true,refresh:true});
      expect(controller.session(before.id)?.currentExecutionId).toBeUndefined();
    }finally{controller.dispose();}
  });
  it("does not preload an obsolete event after the selected block context changes",async()=>{
    let current=session();const block=current.blocks[0],request=vi.fn(async()=>({status:"ready",context_version:1})),preparation=new ScopePreparation({request:request as RuntimeTransport["request"]});
    const refresh=prepareExecutionContextAfterEvent({session_id:current.id,execution_id:"old",block_id:block.id,status:"succeeded",duration_ms:1,results:[],variables:[],context_change:change()},()=>current,preparation);
    current={...current,database:"manually_selected",schema:"other"};await refresh;expect(request).not.toHaveBeenCalled();
  });
});
