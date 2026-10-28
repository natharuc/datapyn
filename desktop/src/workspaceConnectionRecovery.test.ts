import {afterEach,describe,expect,it,vi} from "vitest";
import {applyRuntimeEvent,decodeDocument,encodeDocument,newBlock,newSession,WorkspaceController} from "./workspace";
import {activeConnectionRecovery,applyConnectionRecovery} from "./connectionRecovery";
import {isRuntimeEvent,RuntimeRequestError,type ConnectionRecoveryOutcome,type ConnectionRecoveryState,type RuntimeEvent,type RuntimeTransport} from "./runtime";

function deferred<T=unknown>(){let resolve!:(value:T)=>void,reject!:(error:unknown)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function recovering(sessionId:string,blockId?:string,overrides:Partial<ConnectionRecoveryState>={}):ConnectionRecoveryState{return {session_id:sessionId,block_id:blockId,scope_inherited:Boolean(blockId),automatic_transactions:true,requested_scope:{},phase:"recovering",recovery_id:"network-1",...overrides};}
class Transport implements RuntimeTransport {
  requests:Array<{method:string;params:Record<string,unknown>}>=[];
  listener?:(event:RuntimeEvent)=>void;
  recover?:(params:Record<string,unknown>)=>Promise<unknown>;
  connect?:(params:Record<string,unknown>)=>Promise<unknown>;
  run?:(params:Record<string,unknown>)=>void;
  async subscribe(listener:(event:RuntimeEvent)=>void){this.listener=listener;return()=>{};}
  async request<T>(method:string,params:Record<string,unknown>={}):Promise<T>{
    this.requests.push({method,params});
    if(method==="system.info")return {protocol_version:1,capabilities:{}} as T;
    if(method==="execution.review")return {confirmation_required:false,risks:[]} as T;
    if(method==="connection.recover")return (this.recover?await this.recover(params):{phase:"ready",recovery_id:"network-rpc",session_state_lost:true}) as T;
    if(method==="connection.connect")return (this.connect?await this.connect(params):{}) as T;
    if(method==="execution.run")this.run?.(params);
    return {} as T;
  }
  calls(method:string){return this.requests.filter(call=>call.method===method);}
}
const controllers:WorkspaceController[]=[];
function setup(){const transport=new Transport(),controller=new WorkspaceController(transport,undefined,{nativePersistence:true});controllers.push(controller);return {transport,controller,session:controller.session()!};}
afterEach(()=>{controllers.splice(0).forEach(controller=>controller.dispose());vi.useRealTimers();});

describe("connection recovery event contract",()=>{
  it("accepts scoped recovery and compact terminal outcomes while rejecting malformed flags",()=>{
    const state=recovering("session","block");expect(isRuntimeEvent({event:"connection.recovery",payload:state})).toBe(true);
    for(const invalid of [{automatic_transactions:"false"},{phase:"retry"},{recovery_id:""},{requested_scope:[]},{attempt:-1},{acknowledgement_required:1},{state_loss_acknowledged:1},{transaction_state:{automatic_transactions:true,pending:"false",state:"idle"}},{requested_scope:{database:{secret:true}}}])expect(isRuntimeEvent({event:"connection.recovery",payload:{...state,...invalid}})).toBe(false);
    expect(isRuntimeEvent({event:"execution.finished",payload:{session_id:"session",execution_id:"exec",status:"failed",connection_lost:true,connection_recovery:{phase:"blocked",recovery_id:"lost",acknowledgement_required:true}}})).toBe(true);
    expect(isRuntimeEvent({event:"execution.finished",payload:{session_id:"session",execution_id:"exec",status:"failed",connection_lost:"true"}})).toBe(false);
  });
  it("updates only the owning block, keeping sibling scope and live data intact",()=>{
    const session=newSession(),first=session.blocks[0],other=newBlock();session.blocks.push(other);session.variables=[{name:"df",type:"DataFrame",preview:"millions of rows"}];
    const next=applyConnectionRecovery(session,recovering(session.id,first.id));
    expect(next.blocks[0].connectionRecovery?.phase).toBe("recovering");expect(next.blocks[1]).toBe(other);expect(next.variables).toBe(session.variables);expect(next.connectionState).toBeUndefined();
  });
  it.each([
    {session_id:"closed-session"},{block_id:"removed-block"},{automatic_transactions:false},{requested_scope:{database:"different"}},{requested_scope:{schema:"different"}},{requested_scope:{connection_id:"different"}},{scope_inherited:false},
  ])("ignores recovery for a different lane: %j",overrides=>{
    const session=newSession(),state=recovering(session.id,session.focusedBlockId,overrides);expect(applyConnectionRecovery(session,state)).toBe(session);
  });
  it("keeps manual recovery separate and ignores a completed older recovery",()=>{
    const session=newSession(),block=session.blocks[0];block.disable_automatic_transactions=true;
    const first=recovering(session.id,block.id,{automatic_transactions:false});let next=applyConnectionRecovery(session,first);
    const newer={...first,recovery_id:"newer"};next=applyConnectionRecovery(next,newer);
    expect(applyConnectionRecovery(next,{...first,phase:"ready"})).toBe(next);
    next=applyConnectionRecovery(next,{...newer,phase:"blocked",acknowledgement_required:true});
    expect(applyConnectionRecovery(next,newer)).toBe(next);expect(activeConnectionRecovery(next,next.blocks[0])?.phase).toBe("blocked");
    expect(activeConnectionRecovery(next,{...next.blocks[0],disable_automatic_transactions:false})).toBeUndefined();
  });
  it("does not accept an old execution's recovery as a new current operation",()=>{
    const session=newSession();session.currentExecutionId="new-execution";
    expect(applyConnectionRecovery(session,recovering(session.id,session.focusedBlockId,{execution_id:"old-execution"}))).toBe(session);
  });
  it("does not confuse default-session recovery with the independently owned block lane",()=>{
    const session=newSession();session.connectionRecovery=recovering(session.id,undefined,{phase:"ready",scope_inherited:false});
    const block=recovering(session.id,session.focusedBlockId,{phase:"blocked",recovery_id:"separate",acknowledgement_required:true});
    expect(applyConnectionRecovery(session,block).blocks[0].connectionRecovery).toMatchObject({phase:"blocked",recovery_id:"separate"});
  });
  it("refreshes only backend-confirmed shared automatic lanes after another block recovers",()=>{
    const session=newSession(),first=session.blocks[0],shared=newBlock(),differentSocket=newBlock(),manual=newBlock();manual.disable_automatic_transactions=true;
    session.blocks.push(shared,differentSocket,manual);
    for(const block of session.blocks)block.connectionRecovery=recovering(session.id,block.id,{phase:"blocked",recovery_id:block.id,automatic_transactions:block!==manual,acknowledgement_required:true});
    let next=applyConnectionRecovery(session,recovering(session.id,first.id,{recovery_id:"new"}));
    next=applyConnectionRecovery(next,recovering(session.id,first.id,{recovery_id:"new",phase:"ready",affected_block_ids:[first.id,shared.id,manual.id],session_state_lost:true}));
    expect(next.blocks[1].connectionRecovery).toMatchObject({phase:"ready",recovery_id:"new"});expect(next.blocks[1].connectionRecovery?.acknowledgement_required).not.toBe(true);
    expect(next.blocks[2]).toBe(differentSocket);expect(next.blocks[3]).toBe(manual);
  });
  it("replaces stale transaction state only on the socket and peers confirmed ready by the backend",()=>{
    const session=newSession(),first=session.blocks[0],shared=newBlock(),independent=newBlock();session.blocks.push(shared,independent);
    const unknown={automatic_transactions:true,pending:null,state:"unknown" as const},idle={automatic_transactions:true,pending:false,state:"idle" as const};
    for(const block of session.blocks){block.transactionState=unknown;block.connectionRecovery=recovering(session.id,block.id,{phase:"blocked",recovery_id:block.id,acknowledgement_required:true});}
    let next=applyConnectionRecovery(session,recovering(session.id,first.id,{recovery_id:"replacement"}));
    expect(next.blocks[0].transactionState).toBe(unknown);
    next=applyConnectionRecovery(next,recovering(session.id,first.id,{recovery_id:"replacement",phase:"ready",transaction_state:idle,affected_block_ids:[first.id,shared.id]}));
    expect(next.blocks[0].transactionState).toEqual(idle);expect(next.blocks[1].transactionState).toEqual(idle);
    expect(next.blocks[2]).toBe(independent);expect(next.blocks[2].transactionState).toBe(unknown);
  });
  it("clears a lost socket's transaction state when an older backend confirms ready without a snapshot",()=>{
    const session=newSession(),block=session.blocks[0];block.transactionState={automatic_transactions:false,pending:null,state:"unknown"};
    block.disable_automatic_transactions=true;
    const next=applyConnectionRecovery(session,recovering(session.id,block.id,{automatic_transactions:false,phase:"ready"}));
    expect(next.blocks[0].transactionState).toBeUndefined();
  });
});

describe("recovering a connection without rerunning code",()=>{
  it("preserves large result references, variables and rich output on a failed connection",()=>{
    const session=newSession(),block=session.blocks[0];session.currentExecutionId="lost";session.currentBlockId=block.id;
    session.results=[{result_id:"old-grid",variable_name:"df",row_count:5_000_000,columns:[]}];block.results=session.results;
    session.variables=[{name:"df",type:"DataFrame",preview:"5 million rows"}];session.images=[{data:"image",mime:"image/png"}];session.richOutputs=[{type:"html",data:"previous chart"}];
    const result=applyRuntimeEvent(session,{event:"execution.finished",payload:{session_id:session.id,execution_id:"lost",block_id:block.id,status:"failed",duration_ms:1,error:"Network disconnected",results:[],variables:[],connection_lost:true,connection_recovery:{phase:"ready",recovery_id:"restored",session_state_lost:true}}});
    expect(result.results).toBe(session.results);expect(result.blocks[0].results).toBe(block.results);expect(result.variables).toBe(session.variables);expect(result.images).toBe(session.images);expect(result.richOutputs).toBe(session.richOutputs);
    expect(result.blocks[0].connectionRecovery).toMatchObject({phase:"ready",session_state_lost:true});expect(result.blocks[0].status).toBe("failed");
  });
  it("retains the existing behavior for failures unrelated to a connection",()=>{
    const session=newSession();session.currentExecutionId="syntax";session.currentBlockId=session.focusedBlockId;session.results=[{result_id:"old",variable_name:"df",row_count:1,columns:[]}];
    expect(applyRuntimeEvent(session,{event:"execution.finished",payload:{session_id:session.id,execution_id:"syntax",status:"failed",duration_ms:1,results:[],variables:[]}}).results).toEqual([]);
  });
  it("does not restore a dead socket's unknown transaction state after recovery completed",()=>{
    const session=newSession(),block=session.blocks[0];session.currentExecutionId="lost";session.currentBlockId=block.id;
    const replacement={automatic_transactions:true,pending:false,state:"idle" as const};
    const updated=applyRuntimeEvent(session,{event:"execution.finished",payload:{session_id:session.id,execution_id:"lost",block_id:block.id,status:"failed",duration_ms:1,results:[],variables:[],connection_lost:true,transaction_state:{automatic_transactions:true,pending:null,state:"unknown"},connection_recovery:{phase:"ready",recovery_id:"fresh",session_state_lost:true,transaction_state:replacement}}});
    expect(updated.blocks[0].transactionState).toEqual(replacement);
    expect(updated.blocks[0].status).toBe("failed");
    expect(updated.blocks[0].connectionRecovery?.acknowledgement_required).not.toBe(true);
  });
  it("deduplicates explicit recovery, pins its target and never sends SQL or resets a kernel",async()=>{
    const {transport,controller,session}=setup(),block=session.blocks[0],gate=deferred<ConnectionRecoveryOutcome>();
    controller.updateBlock(session.id,block.id,{connection_id:"warehouse",database_name:"catalog",schema:"finance",disable_automatic_transactions:true,code:"UPDATE secret SET value=1"});
    transport.recover=()=>gate.promise;const first=controller.recoverConnection(session.id,block.id),second=controller.recoverConnection(session.id,block.id);
    await vi.waitFor(()=>expect(transport.calls("connection.recover")).toHaveLength(1));expect(first).toBe(second);
    expect(transport.calls("connection.recover")[0].params).toEqual({session_id:session.id,block_id:block.id,scope_inherited:false,automatic_transactions:false,connection_id:"warehouse",database:"catalog",schema:"finance",acknowledge_state_loss:false});
    gate.resolve({phase:"ready",recovery_id:"restored",session_state_lost:true});await first;
    expect(controller.session(session.id)?.blocks[0].connectionRecovery?.phase).toBe("ready");expect(controller.session(session.id)?.blocks[0].code).toBe("UPDATE secret SET value=1");
    expect(transport.calls("execution.run")).toHaveLength(0);expect(transport.calls("connection.connect")).toHaveLength(0);expect(transport.calls("session.close")).toHaveLength(0);expect(transport.calls("session.create")).toHaveLength(1);
  });
  it("passes acknowledgement only when the caller explicitly confirms loss of physical state",async()=>{
    const {transport,controller,session}=setup();await controller.recoverConnection(session.id,session.focusedBlockId,true);
    expect(transport.calls("connection.recover")[0].params.acknowledge_state_loss).toBe(true);
  });
  it("rejects an acknowledgement captured for an older connection or recovery",async()=>{
    const {transport,controller,session}=setup();controller.onRuntimeEvent({event:"connection.recovery",payload:recovering(session.id,session.focusedBlockId,{phase:"blocked",acknowledgement_required:true,recovery_id:"current"})});
    await expect(controller.recoverConnection(session.id,session.focusedBlockId,true,"old")).rejects.toThrow("mudou");
    controller.updateBlock(session.id,session.focusedBlockId,{database_name:"changed"});await expect(controller.recoverConnection(session.id,session.focusedBlockId,true,"current")).rejects.toThrow("mudou");expect(transport.calls("connection.recover")).toHaveLength(0);
  });
  it("keeps a rejected acknowledgement blocked instead of claiming a new ready connection",async()=>{
    const {transport,controller,session}=setup();transport.recover=async()=>({phase:"blocked",recovery_id:"pending",acknowledgement_required:true,error:"Transaction outcome unknown"});
    await controller.recoverConnection(session.id,session.focusedBlockId);
    expect(controller.session(session.id)?.blocks[0].connectionRecovery).toMatchObject({phase:"blocked",acknowledgement_required:true});expect(transport.calls("execution.run")).toHaveLength(0);
  });
  it("requires recovery acknowledgement before allowing another SQL execution",async()=>{
    const {transport,controller,session}=setup();controller.updateBlock(session.id,session.focusedBlockId,{code:"DELETE FROM important_table"});
    controller.onRuntimeEvent({event:"connection.recovery",payload:recovering(session.id,session.focusedBlockId,{phase:"blocked",acknowledgement_required:true})});
    await expect(controller.runBlock(session.id,session.focusedBlockId)).rejects.toThrow("confirme");expect(transport.calls("execution.review")).toHaveLength(0);expect(transport.calls("execution.run")).toHaveLength(0);
  });
  it("allows a later retry after a network error without replacing other block state",async()=>{
    const {transport,controller,session}=setup(),other=controller.addBlock(session.id,"python","print(df)");
    transport.recover=async()=>{throw new Error("Network unavailable");};await expect(controller.recoverConnection(session.id,session.focusedBlockId)).rejects.toThrow("Network unavailable");
    expect(controller.session(session.id)?.blocks[0].connectionRecovery?.phase).toBe("error");expect(controller.session(session.id)?.blocks[1].code).toBe(other.code);expect(controller.session(session.id)?.busy).toBe(false);
    transport.recover=undefined;await controller.recoverConnection(session.id,session.focusedBlockId);expect(controller.session(session.id)?.blocks[0].connectionRecovery?.phase).toBe("ready");
  });
  it.each(["close","profile","context","mode"] as const)("ignores late recovery after %s changes its owner",async action=>{
    const {transport,controller,session}=setup(),gate=deferred<ConnectionRecoveryOutcome>();transport.recover=()=>gate.promise;
    const task=controller.recoverConnection(session.id,session.focusedBlockId);await vi.waitFor(()=>expect(transport.calls("connection.recover")).toHaveLength(1));
    if(action==="close")await controller.closeSession(session.id);else if(action==="profile"){controller.setWorkspaceIdentity("other");controller.setWorkspaceIdentity(undefined);}else if(action==="context")controller.updateBlock(session.id,session.focusedBlockId,{database_name:"new_database"});else controller.setAutomaticTransactions(false);
    const before=controller.getSnapshot();gate.resolve({phase:"ready",recovery_id:"late",session_state_lost:true});await task;expect(controller.getSnapshot()).toBe(before);
  });
  it("never overwrites a newer recovery with an older RPC acknowledgement",async()=>{
    const {transport,controller,session}=setup(),gate=deferred<ConnectionRecoveryOutcome>();transport.recover=()=>gate.promise;
    const task=controller.recoverConnection(session.id,session.focusedBlockId);await vi.waitFor(()=>expect(transport.calls("connection.recover")).toHaveLength(1));
    controller.onRuntimeEvent({event:"connection.recovery",payload:recovering(session.id,session.focusedBlockId,{recovery_id:"new-operation"})});
    gate.resolve({phase:"ready",recovery_id:"old-operation"});await task;
    expect(controller.session(session.id)?.blocks[0].connectionRecovery).toMatchObject({phase:"recovering",recovery_id:"new-operation"});
  });
  it("does not persist recovery or revive it when a document is imported",async()=>{
    const {controller,session}=setup();controller.onRuntimeEvent({event:"connection.recovery",payload:recovering(session.id,session.focusedBlockId)});
    expect(JSON.stringify(encodeDocument(controller.session(session.id)!))).not.toContain("connectionRecovery");
    expect(JSON.stringify(controller.nativeSnapshot())).not.toContain("connectionRecovery");
    const document=decodeDocument({blocks:[{language:"sql",code:"SELECT 1",connectionRecovery:recovering(session.id,session.focusedBlockId)}]});expect(document.blocks[0].connectionRecovery).toBeUndefined();
  });
  it("stops periodic execution after a connection failure with an unknown outcome",async()=>{
    vi.useFakeTimers();const {transport,controller,session}=setup();controller.updateBlock(session.id,session.focusedBlockId,{code:"UPDATE items SET state='done'"});
    transport.run=params=>queueMicrotask(()=>transport.listener?.({event:"execution.finished",payload:{session_id:session.id,execution_id:String(params.execution_id),block_id:session.focusedBlockId,status:"failed",duration_ms:1,results:[],variables:[],connection_lost:true,connection_recovery:{phase:"blocked",recovery_id:"uncertain",acknowledgement_required:true}}}));
    await controller.startPeriodic(session.id,1);expect(controller.session(session.id)?.periodicSeconds).toBeUndefined();await vi.advanceTimersByTimeAsync(10_000);expect(transport.calls("execution.run")).toHaveLength(1);
  });
  it("retries only structured transient initial failures with a bounded backoff",async()=>{
    vi.useFakeTimers();const {transport,controller,session}=setup();let attempts=0;
    transport.connect=async()=>{if(++attempts<3)throw new RuntimeRequestError("connection_unavailable","Offline",{retryable:true});return {config:{db_type:"sqlite",host:"",port:0,database:"file.db",username:""},database:"file.db"};};
    const task=controller.connectSaved(session.id,"saved","Main");await vi.advanceTimersByTimeAsync(1100);await task;
    expect(transport.calls("connection.connect")).toHaveLength(3);expect(controller.session(session.id)?.connectionState?.phase).toBe("ready");
  });
  it.each([new Error("Login failed"),new RuntimeRequestError("authentication_failed","MFA required"),new RuntimeRequestError("connection_unavailable","Offline",{retryable:false})])("does not retry authentication or an unclassified failure: %s",async failure=>{
    const {transport,controller,session}=setup();transport.connect=async()=>{throw failure;};
    await expect(controller.connectSaved(session.id,"saved")).rejects.toThrow(failure.message);expect(transport.calls("connection.connect")).toHaveLength(1);
  });
  it("ends initial retries after the limit and allows the existing retry controls to remain",async()=>{
    vi.useFakeTimers();const {transport,controller,session}=setup();transport.connect=async()=>{throw new RuntimeRequestError("connection_unavailable","Offline",{retryable:true});};
    const task=controller.connectSaved(session.id,"saved");const rejected=expect(task).rejects.toThrow("Offline");await vi.advanceTimersByTimeAsync(1100);await rejected;
    expect(transport.calls("connection.connect")).toHaveLength(3);expect(controller.session(session.id)?.connectionState).toMatchObject({phase:"error",connectionId:"saved",error:"Offline"});
  });
  it("does not reconnect a tab closed during initial backoff",async()=>{
    vi.useFakeTimers();const {transport,controller,session}=setup();transport.connect=async()=>{throw new RuntimeRequestError("connection_unavailable","Offline",{retryable:true});};
    const task=controller.connectSaved(session.id,"saved"),rejected=expect(task).rejects.toThrow("interrompida");await vi.advanceTimersByTimeAsync(0);await controller.closeSession(session.id);await vi.advanceTimersByTimeAsync(1100);await rejected;
    expect(transport.calls("connection.connect")).toHaveLength(1);
  });
  it("keeps a dismissed loss notice dismissed when an old terminal event arrives",async()=>{
    const {controller,session}=setup(),state=recovering(session.id,session.focusedBlockId,{phase:"ready",session_state_lost:true});
    controller.onRuntimeEvent({event:"connection.recovery",payload:state});controller.dismissConnectionRecovery(session.id,session.focusedBlockId);controller.onRuntimeEvent({event:"connection.recovery",payload:state});
    expect(controller.session(session.id)?.blocks[0].connectionRecovery).toBeUndefined();
  });
});
