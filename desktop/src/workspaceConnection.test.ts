import {afterEach,describe,expect,it,vi} from "vitest";
import type {RuntimeEvent,RuntimeTransport} from "./runtime";
import {WorkspaceController,encodeDocument,type ConnectionConfig} from "./workspace";

function deferred<T=unknown>() {
  let resolve!:(value:T)=>void,reject!:(error:unknown)=>void;
  const promise=new Promise<T>((accept,fail)=>{resolve=accept;reject=fail;});
  return {promise,resolve,reject};
}
class ConnectionTransport implements RuntimeTransport {
  requests:Array<{method:string;params:Record<string,unknown>}>=[];
  connections:Array<ReturnType<typeof deferred>>=[];
  createGate?:ReturnType<typeof deferred>;
  infoError?:string;
  listener?:(event:RuntimeEvent)=>void;
  async subscribe(listener:(event:RuntimeEvent)=>void){this.listener=listener;return ()=>{};}
  async request<T>(method:string,params:Record<string,unknown>={}):Promise<T>{
    this.requests.push({method,params});
    if(method==="system.info"){
      if(this.infoError)throw new Error(this.infoError);
      return {protocol_version:1,python_version:"3.12",capabilities:{}} as T;
    }
    if(method==="session.create"&&this.createGate)return await this.createGate.promise as T;
    if(method==="connection.connect"){
      const gate=deferred();this.connections.push(gate);return await gate.promise as T;
    }
    if(method==="execution.run")queueMicrotask(()=>this.listener?.({event:"execution.finished",payload:{
      session_id:String(params.session_id),execution_id:String(params.execution_id),status:"succeeded",duration_ms:1,results:[],variables:[],
    }}));
    return {} as T;
  }
  calls(method:string){return this.requests.filter(request=>request.method===method);}
}
const config:ConnectionConfig={db_type:"sqlserver",host:"local",port:1433,database:"configured",username:"user",schema:"configured_schema",password:"secret"};
const connected={config,database:"ESIM",schema:"dbo"};
const controllers:WorkspaceController[]=[];
function setup(){const transport=new ConnectionTransport(),controller=new WorkspaceController(transport,undefined,{nativePersistence:true});controllers.push(controller);return {transport,controller,session:controller.session()!};}
afterEach(()=>{controllers.splice(0).forEach(controller=>controller.dispose());});

describe("opening a tab connection",()=>{
  it("shows preparation immediately, waits for authentication and retains driver-resolved focus without secrets",async()=>{
    const {controller,transport,session}=setup();transport.createGate=deferred();
    const task=controller.connectSaved(session.id,"esim","ESIM");
    expect(controller.session()!.connectionState).toEqual({phase:"preparing",connectionId:"esim",name:"ESIM"});
    await vi.waitFor(()=>expect(transport.calls("session.create")).toHaveLength(1));
    expect(transport.connections).toHaveLength(0);
    transport.createGate.resolve({});await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));
    expect(controller.session()!.connectionState).toMatchObject({phase:"connecting",name:"ESIM"});
    expect(controller.session()!.connection).toBeUndefined();
    transport.connections[0].resolve(connected);await task;
    expect(controller.session()!).toMatchObject({database:"ESIM",schema:"dbo",savedConnectionId:"esim",connection:{database:"ESIM",schema:"dbo"},connectionState:{phase:"ready"}});
    expect(controller.session()!.connection).not.toHaveProperty("password");
  });
  it("keeps an authentication error in its tab when the user switches tabs and permits retry",async()=>{
    const {controller,transport,session}=setup();const other=controller.createSession();
    const task=controller.connectSaved(session.id,"esim","ESIM"),failed=expect(task).rejects.toThrow("Login failed");
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));transport.connections[0].reject(new Error("Login failed: account disabled"));await failed;
    expect(controller.session()!.id).toBe(other.id);expect(controller.session()!.connectionState).toBeUndefined();
    expect(controller.session(session.id)!.connectionState).toEqual({phase:"error",connectionId:"esim",name:"ESIM",error:"Login failed: account disabled"});
    const retry=controller.connectSaved(session.id,"esim","ESIM");
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(2));transport.connections[1].resolve(connected);await retry;
    expect(controller.session(session.id)!.connectionState).toMatchObject({phase:"ready"});
    expect(transport.calls("session.create")).toHaveLength(1);
  });
  it("deduplicates the same connection and rejects a conflicting attempt within one tab",async()=>{
    const {controller,transport,session}=setup();const first=controller.connectSaved(session.id,"a");
    expect(controller.connectSaved(session.id,"a")).toBe(first);
    await expect(controller.connectSaved(session.id,"b")).rejects.toThrow("em andamento");
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));transport.connections[0].resolve(connected);await first;
  });
  it("authenticates connections in separate tabs independently",async()=>{
    const {controller,transport,session}=setup();const other=controller.createSession();
    const first=controller.connectSaved(session.id,"a","A"),second=controller.connectSaved(other.id,"b","B");
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(2));
    transport.connections[1].resolve({...connected,database:"SECOND"});await second;
    expect(controller.session(session.id)!.connectionState?.phase).toBe("connecting");
    expect(controller.session(other.id)!.database).toBe("SECOND");
    transport.connections[0].resolve(connected);await first;
  });
  it("shows bootstrap failures in the requested tab without dispatching database authentication",async()=>{
    const {controller,transport,session}=setup();transport.infoError="Python unavailable";
    await expect(controller.connectSaved(session.id,"a","A")).rejects.toThrow("Python unavailable");
    expect(controller.session()!.connectionState).toMatchObject({phase:"error",name:"A",connectionId:"a",error:"Python unavailable"});
    expect(transport.calls("session.create")).toHaveLength(0);expect(transport.connections).toHaveLength(0);
    transport.infoError=undefined;await controller.retryRuntime();
    const retry=controller.connectSaved(session.id,"a","A");await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));
    transport.connections[0].resolve(connected);await retry;expect(controller.session()!.connectionState?.phase).toBe("ready");
  });
  it("shows kernel creation errors in the same status without a database request",async()=>{
    const {controller,transport,session}=setup();transport.createGate=deferred();
    const task=controller.prepareSession(session.id),failed=expect(task).rejects.toThrow("Kernel failed");
    await vi.waitFor(()=>expect(transport.calls("session.create")).toHaveLength(1));transport.createGate.reject(new Error("Kernel failed"));await failed;
    expect(controller.session()!.connectionState).toMatchObject({phase:"error",error:"Kernel failed"});expect(transport.connections).toHaveLength(0);
  });
  it("restores the active connection before reporting readiness and preserves restored database/schema focus",async()=>{
    const {controller,transport,session}=setup();controller.patchSession(session.id,s=>({...s,savedConnectionId:"a",database:"RESTORED",schema:"sales",extras:{connection_name:"Saved"}}));
    const other=controller.createSession();controller.patchSession(other.id,s=>({...s,savedConnectionId:"b"}));controller.activate(session.id);
    let ready=false;const task=controller.prepareSession(session.id).then(()=>{ready=true;});
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));expect(ready).toBe(false);
    expect(transport.calls("connection.connect")[0].params).toEqual({session_id:session.id,connection_id:"a",database:"RESTORED",schema:"sales"});
    expect(controller.session(other.id)!.connectionState).toBeUndefined();
    transport.connections[0].resolve({...connected,database:"RESTORED",schema:"sales"});await task;
    expect(controller.session()!).toMatchObject({database:"RESTORED",schema:"sales",connectionState:{phase:"ready"}});
  });
  it("preparation joins an existing authentication request",async()=>{
    const {controller,transport,session}=setup();const connection=controller.connectSaved(session.id,"a");
    let ready=false;const preparation=controller.prepareSession(session.id).then(()=>{ready=true;});
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));expect(ready).toBe(false);
    transport.connections[0].resolve(connected);await Promise.all([connection,preparation]);expect(transport.connections).toHaveLength(1);
  });
  it("retains the restored authentication scope for retry rather than reverting to configured defaults",async()=>{
    const {controller,transport,session}=setup();controller.patchSession(session.id,s=>({...s,savedConnectionId:"a",database:"RESTORED",schema:"sales",extras:{connection_name:"Saved"}}));
    const task=controller.prepareSession(session.id),failed=expect(task).rejects.toThrow("Transient");
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));transport.connections[0].reject(new Error("Transient"));await failed;
    const state=controller.session()!.connectionState!;
    expect(state.scope).toEqual({database:"RESTORED",schema:"sales"});
    const retry=controller.connectSaved(session.id,state.connectionId!,state.name,state.scope);
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(2));
    expect(transport.calls("connection.connect")[1].params).toEqual({session_id:session.id,connection_id:"a",database:"RESTORED",schema:"sales"});
    transport.connections[1].resolve({...connected,database:"RESTORED",schema:"sales"});await retry;
    expect(controller.session()!).toMatchObject({database:"RESTORED",schema:"sales",connectionState:{phase:"ready"}});
  });
  it("does not revive a closed tab when authentication finishes",async()=>{
    const {controller,transport,session}=setup();const task=controller.connectSaved(session.id,"a"),interrupted=expect(task).rejects.toThrow("interrompida");
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));await controller.closeSession(session.id);
    transport.connections[0].resolve(connected);await interrupted;
    expect(controller.session(session.id)).toBeUndefined();expect(controller.session()!.connectionState).toBeUndefined();
  });
  it("closes a kernel created after its tab was closed",async()=>{
    const {controller,transport,session}=setup();transport.createGate=deferred();
    const task=controller.prepareSession(session.id),interrupted=expect(task).rejects.toThrow("encerrada");
    await vi.waitFor(()=>expect(transport.calls("session.create")).toHaveLength(1));await controller.closeSession(session.id);
    transport.createGate.resolve({});await interrupted;
    expect(transport.calls("session.close")).toEqual([{method:"session.close",params:{session_id:session.id}}]);expect(controller.session(session.id)).toBeUndefined();
  });
  it("ignores old connection replies after restoring a workspace with the same session id",async()=>{
    const {controller,transport,session}=setup();const snapshot=controller.nativeSnapshot();
    const old=controller.connectSaved(session.id,"old"),interrupted=expect(old).rejects.toThrow("interrompida");
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));controller.restoreSnapshot(snapshot);
    const next=controller.connectSaved(session.id,"next");await vi.waitFor(()=>expect(transport.connections).toHaveLength(2));
    transport.connections[0].resolve({...connected,database:"OLD"});await interrupted;
    expect(controller.session()!.connectionState).toMatchObject({phase:"connecting",connectionId:"next"});
    transport.connections[1].resolve(connected);await next;expect(controller.session()!.database).toBe("ESIM");
  });
  it("keeps loading/error state transient without changing the exported PyQt document",async()=>{
    const {controller,transport,session}=setup();const before=encodeDocument(session),record=controller.nativeSnapshot().documents[0],revision=controller.getSnapshot().documentRevision??0;
    const task=controller.connectSaved(session.id,"a"),failed=expect(task).rejects.toThrow("Denied");
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));
    expect(encodeDocument(controller.session()!)).toEqual(before);expect(controller.nativeSnapshot().documents[0]).toBe(record);expect(controller.getSnapshot().documentRevision).toBe(revision);
    transport.connections[0].reject(new Error("Denied"));await failed;
    expect(encodeDocument(controller.session()!)).toEqual(before);expect(controller.nativeSnapshot().documents[0]).toBe(record);
  });
  it("blocks execution shortcuts during authentication and keeps Python usable after a SQL connection error",async()=>{
    const {controller,transport,session}=setup();controller.updateBlock(session.id,session.blocks[0].id,{code:"SELECT 1"});
    const task=controller.connectSaved(session.id,"a"),failed=expect(task).rejects.toThrow("Denied");
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));
    await expect(controller.runBlock(session.id,session.blocks[0].id)).rejects.toThrow("Aguarde a conexão");expect(transport.calls("execution.run")).toHaveLength(0);
    transport.connections[0].reject(new Error("Denied"));await failed;
    await expect(controller.runBlock(session.id,session.blocks[0].id)).rejects.toThrow("Denied");
    const python=controller.addBlock(session.id,"python","print(1)");await controller.runBlock(session.id,python.id);
    expect(transport.calls("execution.run")).toHaveLength(1);expect(controller.session()!.blocks.at(-1)!.status).toBe("succeeded");
  });
  it("keeps the target and runtime error visible when the backend exits mid-authentication",async()=>{
    const {controller,transport,session}=setup();const task=controller.connectSaved(session.id,"a","Target"),interrupted=expect(task).rejects.toThrow("interrompida");
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));controller.onRuntimeEvent({event:"backend.exited",payload:{message:"Runtime stopped"}});
    expect(controller.session()!.connectionState).toEqual({phase:"error",name:"Target",connectionId:"a",error:"Runtime stopped"});
    transport.connections[0].resolve(connected);await interrupted;expect(controller.session()!.connection).toBeUndefined();
  });
  it("starts a fresh kernel after a backend exit without awaiting or adopting the old kernel response",async()=>{
    const {controller,transport,session}=setup();const oldGate=deferred();transport.createGate=oldGate;
    const old=controller.connectSaved(session.id,"old"),interrupted=expect(old).rejects.toThrow("preparação");
    await vi.waitFor(()=>expect(transport.calls("session.create")).toHaveLength(1));
    controller.onRuntimeEvent({event:"backend.exited",payload:{message:"Runtime stopped"}});
    transport.createGate=undefined;const retry=controller.connectSaved(session.id,"new");
    await vi.waitFor(()=>expect(transport.connections).toHaveLength(1));
    oldGate.resolve({});await interrupted;
    expect(controller.session()!.connectionState).toMatchObject({phase:"connecting",connectionId:"new"});
    transport.connections[0].resolve(connected);await retry;
    expect(transport.calls("session.create")).toHaveLength(2);expect(controller.session()!.savedConnectionId).toBe("new");
  });
});
