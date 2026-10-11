import {afterEach,describe,expect,it,vi} from "vitest";
import type {ExecutionFinished,RuntimeEvent,RuntimeTransport} from "./runtime";
import {WorkspaceController,applyRuntimeEvent,decodeDocument,encodeDocument,newSession} from "./workspace";

class Transport implements RuntimeTransport {
  requests:Array<{method:string;params:Record<string,unknown>}>=[];
  listener?:(event:RuntimeEvent)=>void;
  async subscribe(listener:(event:RuntimeEvent)=>void){this.listener=listener;return()=>{};}
  async request<T>(method:string,params:Record<string,unknown>={}):Promise<T>{
    this.requests.push({method,params});
    return (method==="system.info"?{protocol_version:1,python_version:"3.12",capabilities:{}}:{status:"queued"}) as T;
  }
  executions(){return this.requests.filter(request=>request.method==="execution.run");}
  started(index:number){const {params}=this.executions()[index];this.listener?.({event:"execution.started",payload:{session_id:String(params.session_id),execution_id:String(params.execution_id)}});}
  finished(index:number,status:ExecutionFinished["status"]="succeeded",duration_ms=125.25){
    const {params}=this.executions()[index];this.listener?.({event:"execution.finished",payload:{session_id:String(params.session_id),execution_id:String(params.execution_id),status,duration_ms,results:[],variables:[]}});
  }
}
const controllers:WorkspaceController[]=[];
function setup(){const transport=new Transport(),controller=new WorkspaceController(transport,undefined,{nativePersistence:true});controllers.push(controller);return {controller,transport,session:controller.session()!};}
afterEach(()=>{controllers.splice(0).forEach(controller=>controller.dispose());vi.restoreAllMocks();});

describe("actual per-block execution timing",()=>{
  it("starts each block's clock on its own runtime event and retains the server's final duration",async()=>{
    const {controller,transport,session}=setup(),first=session.blocks[0],second=controller.addBlock(session.id,"python","print(2)");
    controller.updateBlock(session.id,first.id,{language:"python",code:"print(1)",executionStartedAt:1,duration_ms:99});
    const run=controller.runAll(session.id);
    await vi.waitFor(()=>expect(transport.executions()).toHaveLength(1));
    expect(controller.session(session.id)!.blocks[0]).toMatchObject({executionStartedAt:undefined,duration_ms:undefined});
    expect(controller.session(session.id)!.blocks[1].executionStartedAt).toBeUndefined();
    const now=vi.spyOn(Date,"now").mockReturnValue(1_000);
    transport.started(0);expect(controller.session(session.id)!.blocks[0].executionStartedAt).toBe(1_000);
    now.mockReturnValue(1_500);transport.started(0);expect(controller.session(session.id)!.blocks[0].executionStartedAt).toBe(1_000);
    transport.finished(0);await vi.waitFor(()=>expect(transport.executions()).toHaveLength(2));
    expect(controller.session(session.id)!.blocks[0]).toMatchObject({status:"succeeded",duration_ms:125.25,executionStartedAt:undefined});
    expect(controller.session(session.id)!.blocks[1].executionStartedAt).toBeUndefined();
    now.mockReturnValue(2_000);transport.started(1);expect(controller.session(session.id)!.blocks[1].executionStartedAt).toBe(2_000);
    expect(controller.session(session.id)!.blocks[1].id).toBe(second.id);
    transport.finished(1,"succeeded",350.75);await run;
    expect(controller.session(session.id)!.blocks[1]).toMatchObject({status:"succeeded",duration_ms:350.75,executionStartedAt:undefined});
  });
  it("continues the active clock while cancelling and clears it at the terminal event",async()=>{
    const {controller,transport,session}=setup();controller.updateBlock(session.id,session.blocks[0].id,{language:"python",code:"print(1)"});
    const run=controller.runBlock(session.id,session.blocks[0].id);await vi.waitFor(()=>expect(transport.executions()).toHaveLength(1));
    vi.spyOn(Date,"now").mockReturnValue(42);transport.started(0);await controller.cancel(session.id);
    expect(controller.session(session.id)!.blocks[0]).toMatchObject({status:"cancelling",executionStartedAt:42});
    transport.started(0);expect(controller.session(session.id)!.blocks[0].status).toBe("cancelling");
    transport.finished(0,"cancelled");await run;expect(controller.session(session.id)!.blocks[0].executionStartedAt).toBeUndefined();
  });
  it.each(["session.reset","session.error","backend.exited"] as const)("clears clocks on %s and rejects unrelated execution starts",event=>{
    const {controller,session}=setup();controller.patchSession(session.id,s=>({...s,currentExecutionId:"active",currentBlockId:s.blocks[0].id,blocks:s.blocks.map(block=>({...block,status:"running",executionStartedAt:42}))}));
    const stale=applyRuntimeEvent(controller.session(session.id)!,{event:"execution.started",payload:{session_id:session.id,execution_id:"old"}});
    expect(stale.blocks[0].executionStartedAt).toBe(42);
    if(event==="backend.exited")controller.onRuntimeEvent({event,payload:{message:"Closed"}});
    else if(event==="session.error")controller.onRuntimeEvent({event,payload:{session_id:session.id,error:"Closed"}});
    else controller.onRuntimeEvent({event,payload:{session_id:session.id}});
    expect(controller.session(session.id)!.blocks[0].executionStartedAt).toBeUndefined();
  });
  it("never saves, restores or duplicates a live clock",()=>{
    const {controller,session}=setup();controller.updateBlock(session.id,session.blocks[0].id,{executionStartedAt:42,status:"running"});
    const encoded=encodeDocument(controller.session(session.id)!);
    expect((encoded.blocks as object[])[0]).not.toHaveProperty("executionStartedAt");
    expect(JSON.stringify(controller.nativeSnapshot())).not.toContain("executionStartedAt");
    expect(controller.duplicateBlock(session.id,session.blocks[0].id)!.executionStartedAt).toBeUndefined();
    const imported=decodeDocument({blocks:[{language:"sql",code:"SELECT 1",executionStartedAt:42}]});
    expect(imported.blocks[0].executionStartedAt).toBeUndefined();
    expect(controller.duplicateSession(session.id)!.blocks.every(block=>block.executionStartedAt===undefined)).toBe(true);
    expect(newSession().blocks[0].executionStartedAt).toBeUndefined();
  });
});
