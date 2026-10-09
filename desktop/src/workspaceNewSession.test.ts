import {afterEach,describe,expect,it,vi} from "vitest";
import type {RuntimeTransport} from "./runtime";
import {applyExecutionContextChange,encodeDocument,WorkspaceController,type ConnectionConfig,type SessionDocument} from "./workspace";
import {commandForEvent,DEFAULT_SHORTCUTS} from "./shortcuts";

const configured:ConnectionConfig={db_type:"postgresql",host:"localhost",port:5432,database:"configured",schema:"public",username:"reader"};
function deferred<T>(){let resolve!:(value:T)=>void,reject!:(failure:unknown)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
class Transport implements RuntimeTransport {
  requests:Array<{method:string;params:Record<string,unknown>}>=[];
  authenticate?:(params:Record<string,unknown>)=>Promise<unknown>;
  async subscribe(){return ()=>{};}
  async request<T>(method:string,params:Record<string,unknown>={}):Promise<T>{
    this.requests.push({method,params});
    if(method==="system.info")return {protocol_version:1,capabilities:{}} as T;
    if(method==="connection.connect"){
      if(this.authenticate)return await this.authenticate(params) as T;
      const config=(params.config??configured) as ConnectionConfig;
      return {config,database:params.database??config.database,schema:params.schema??config.schema} as T;
    }
    return {} as T;
  }
  calls(method:string){return this.requests.filter(request=>request.method===method);}
}
const controllers:WorkspaceController[]=[];
function setup(maximizeFirstBlock=false){const transport=new Transport(),controller=new WorkspaceController(transport,undefined,{nativePersistence:true,maximizeFirstBlock});controllers.push(controller);return {transport,controller,session:controller.session()!};}
afterEach(()=>controllers.splice(0).forEach(controller=>controller.dispose()));
async function connectedSource(controller:WorkspaceController,session:SessionDocument){
  await controller.connectSaved(session.id,"main-db","Primary",{database:"ESIM",schema:"sales"});
  controller.patchSession(session.id,s=>({...s,extras:{...s.extras,connection_name:"Primary",connection_group:"Reports"}}));
}

describe("first block layout for every new tab",()=>{
  it("applies the preference to the initial tab, blank tabs, duplicates and document imports",()=>{
    const {controller,session}=setup(true);
    expect(session.maximizedBlockId).toBe(session.blocks[0].id);
    const second=controller.createSession(),last=controller.addBlock(second.id,"python","print(1)");
    controller.maximizeBlock(second.id,last.id);
    const copy=controller.duplicateSession(second.id)!;
    expect(copy.maximizedBlockId).toBe(copy.blocks[0].id);expect(copy.focusedBlockId).toBe(copy.blocks[0].id);
    const imported=controller.importDocuments({tabs:[{blocks:[{language:"sql",code:"SELECT 1",collapsed:true}]},{blocks:[{language:"python",code:"x=1"}]}]},"Opened");
    for(const next of [second,copy,...imported])expect(next.maximizedBlockId).toBe(next.blocks[0].id);
    expect(imported[0].blocks[0].collapsed).toBe(false);
  });
  it("changes the default for future tabs without changing an existing tab",()=>{
    const {controller,session}=setup();controller.setNewSessionPreferences({maximizeFirstBlock:true});
    expect(controller.session(session.id)!.maximizedBlockId).toBeUndefined();
    const next=controller.createSession();expect(next.maximizedBlockId).toBe(next.blocks[0].id);
    controller.setNewSessionPreferences({maximizeFirstBlock:false});expect(controller.createSession().maximizedBlockId).toBeUndefined();
    expect(controller.session(next.id)!.maximizedBlockId).toBe(next.blocks[0].id);
  });
  it("creates a maximized disconnected replacement after closing the last tab",async()=>{
    const {controller,session}=setup(true);await connectedSource(controller,session);await controller.closeSession(session.id);
    const replacement=controller.session()!;expect(replacement.maximizedBlockId).toBe(replacement.blocks[0].id);expect(replacement.savedConnectionId).toBeUndefined();expect(replacement.connection).toBeUndefined();
  });
  it("preserves restored focus and maximization even when the new-tab default is different",()=>{
    const {controller,session}=setup(),other=controller.addBlock(session.id,"python","x=1");controller.maximizeBlock(session.id,other.id);
    const snapshot=controller.nativeSnapshot();controller.setNewSessionPreferences({maximizeFirstBlock:true});controller.restoreSnapshot(snapshot);
    expect(controller.session()!.focusedBlockId).toBe(other.id);expect(controller.session()!.maximizedBlockId).toBe(other.id);
    snapshot.documents[0]={...snapshot.documents[0],maximizedBlockId:undefined};controller.restoreSnapshot(snapshot);expect(controller.session()!.maximizedBlockId).toBeUndefined();
  });
  it("applies the default only to the newly created tab of an empty restored workspace",()=>{
    const {controller}=setup(true);controller.restoreSnapshot({documents:[]});const next=controller.session()!;expect(next.maximizedBlockId).toBe(next.blocks[0].id);
  });
});

describe("new tabs inherit a connection without sharing execution state",()=>{
  it.each(["n","t"])("the Ctrl+%s command maps to a new tab with the same current database/schema",async key=>{
    const {controller,transport,session}=setup(true);await connectedSource(controller,session);
    expect(["newSession","newTab"]).toContain(commandForEvent({key,ctrlKey:true,metaKey:false,altKey:false,shiftKey:false,repeat:false},DEFAULT_SHORTCUTS));
    const gate=deferred<unknown>();transport.authenticate=()=>gate.promise;
    controller.patchSession(session.id,s=>({...s,variables:[{name:"private_frame",type:"DataFrame",preview:"10 rows"}],results:[{result_id:"old",variable_name:"private_frame",row_count:10,columns:[]}],logs:[{id:"old",time:"",stream:"stdout",text:"old",blockName:""}],busy:true}));
    const next=controller.createSession();
    expect(next).toMatchObject({savedConnectionId:"main-db",database:"ESIM",schema:"sales",connectionState:{phase:"preparing",name:"Primary"},variables:[],results:[],logs:[],busy:false});
    expect(next.connection).toBeUndefined();expect(next.id).not.toBe(session.id);expect(next.blocks[0].id).not.toBe(session.blocks[0].id);
    await vi.waitFor(()=>expect(transport.calls("connection.connect")).toHaveLength(2));
    expect(transport.calls("connection.connect")[1].params).toEqual({session_id:next.id,connection_id:"main-db",database:"ESIM",schema:"sales"});
    expect(transport.calls("session.create").map(call=>call.params.session_id)).toEqual([session.id,next.id]);
    gate.resolve({config:configured,database:"ESIM",schema:"sales"});await controller.prepareSession(next.id);
    expect(controller.session(next.id)!.connectionState?.phase).toBe("ready");expect(controller.session(session.id)!.busy).toBe(true);
  });
  it("inherits the current context after USE instead of configured connection defaults",async()=>{
    const {controller,transport,session}=setup();await connectedSource(controller,session);
    controller.patchSession(session.id,s=>applyExecutionContextChange(s,s.focusedBlockId,{previous:{database:"ESIM",schema:"sales"},current:{database:"reporting",schema:"analytics"},requested_scope:{connection_id:"main-db",database:"ESIM",schema:"sales"}}));
    const next=controller.createSession();await controller.prepareSession(next.id);
    expect(transport.calls("connection.connect")[1].params).toMatchObject({database:"reporting",schema:"analytics"});
    expect(controller.session(next.id)!).toMatchObject({database:"reporting",schema:"analytics"});
  });
  it("uses the connection and explicit context of the focused routed block",async()=>{
    const {controller,transport,session}=setup();await connectedSource(controller,session);
    const block=controller.addBlock(session.id,"sql");controller.updateBlock(session.id,block.id,{connection_id:"other-db",database_name:"warehouse",schema:"finance",connection_name:"Warehouse"});
    const next=controller.createSession();await controller.prepareSession(next.id);
    expect(transport.calls("connection.connect")[1].params).toEqual({session_id:next.id,connection_id:"other-db",database:"warehouse",schema:"finance"});
  });
  it.each(["preparing","connecting","error"] as const)("uses the intended %s target rather than an obsolete saved connection",async phase=>{
    const {controller,transport,session}=setup();await connectedSource(controller,session);
    controller.patchSession(session.id,s=>({...s,connection:undefined,connectionState:{phase,connectionId:"new-db",name:"New connection",...(phase==="error"?{error:"Login failed"}:{})}}));
    const next=controller.createSession();await controller.prepareSession(next.id);
    expect(transport.calls("connection.connect")[1].params).toEqual({session_id:next.id,connection_id:"new-db"});
    expect(controller.session(next.id)!.savedConnectionId).toBe("new-db");
  });
  it("retains an inherited authentication failure in its own tab and retries with the selected context",async()=>{
    const {controller,transport,session}=setup();await connectedSource(controller,session);
    transport.authenticate=async()=>{throw new Error("Warehouse unavailable");};const next=controller.createSession();
    await expect(controller.prepareSession(next.id)).rejects.toThrow("Warehouse unavailable");
    expect(controller.session(next.id)!.connectionState).toMatchObject({phase:"error",connectionId:"main-db",scope:{database:"ESIM",schema:"sales"},error:"Warehouse unavailable"});
    expect(controller.session(session.id)!.connectionState?.phase).toBe("ready");
    transport.authenticate=undefined;await controller.connectSaved(next.id,"main-db","Primary",controller.session(next.id)!.connectionState!.scope);
    expect(controller.session(next.id)!.connectionState?.phase).toBe("ready");
  });
  it("opens disconnected when there is no active tab, no connection or inheritance is disabled",async()=>{
    const {controller,transport,session}=setup();const disconnected=controller.createSession();expect(disconnected.savedConnectionId).toBeUndefined();
    controller.activate(session.id);await connectedSource(controller,session);
    const explicit=controller.createSession({inheritConnection:false});expect(explicit.savedConnectionId).toBeUndefined();expect(explicit.connectionState).toBeUndefined();
    (controller.getSnapshot() as {activeId:string}).activeId="missing";
    const noActive=controller.createSession();expect(noActive.savedConnectionId).toBeUndefined();expect(transport.calls("connection.connect")).toHaveLength(1);
  });
  it("duplicates the selected source connection rather than the currently active unrelated tab",async()=>{
    const {controller,transport,session}=setup(true);await connectedSource(controller,session);
    const other=controller.createSession({inheritConnection:false});await controller.connectSaved(other.id,"different-db","Different",{database:"different"});
    const copy=controller.duplicateSession(session.id)!;await controller.prepareSession(copy.id);
    expect(transport.calls("connection.connect").at(-1)!.params).toEqual({session_id:copy.id,connection_id:"main-db",database:"ESIM",schema:"sales"});expect(copy.maximizedBlockId).toBe(copy.blocks[0].id);
  });
  it("copies direct connection credentials only in memory and authenticates a separate kernel",async()=>{
    const {controller,transport,session}=setup();await controller.connect(session.id,{...configured,password:"private-password"});
    controller.setContext(session.id,{database:"current",schema:"work"});const next=controller.createSession();await controller.prepareSession(next.id);
    expect(transport.calls("connection.connect")[1].params).toMatchObject({session_id:next.id,config:{password:"private-password",database:"current",schema:"work"}});
    expect(controller.session(next.id)!.connection).not.toHaveProperty("password");
    expect(JSON.stringify(encodeDocument(controller.session(next.id)!))).not.toContain("private-password");expect(JSON.stringify(controller.nativeSnapshot())).not.toContain("private-password");
    const duplicate=controller.duplicateSession(session.id)!;await controller.prepareSession(duplicate.id);expect(transport.calls("connection.connect").at(-1)!.params).toMatchObject({config:{password:"private-password"}});
  });
  it.each(["saved","direct"] as const)("inherits the intended manual target while switching from %s connections",async origin=>{
    for(const phase of ["preparing","connecting","error"] as const){
      const {controller,transport,session}=setup();
      if(origin==="saved")await connectedSource(controller,session);else await controller.connect(session.id,{...configured,name:"Previous",database:"previous",schema:"previous_schema",password:"previous-password"});
      const target={...configured,name:"Manual target",database:"target_database",schema:"target_schema",password:"target-password"},gate=deferred<unknown>();
      transport.authenticate=async params=>params.session_id===session.id?gate.promise:{config:params.config,database:target.database,schema:target.schema};
      const attempt=controller.connect(session.id,target),completion=attempt.then(()=>undefined,failure=>failure);
      if(phase!=="preparing")await vi.waitFor(()=>expect(controller.session(session.id)!.connectionState?.phase).toBe("connecting"));
      if(phase==="error"){gate.reject(new Error("Manual authentication failed"));expect(await completion).toBeInstanceOf(Error);}
      const next=controller.createSession();await controller.prepareSession(next.id);
      expect(transport.calls("connection.connect").at(-1)!.params).toMatchObject({session_id:next.id,config:target});
      expect(transport.calls("connection.connect").at(-1)!.params).not.toHaveProperty("connection_id");
      expect(controller.session(next.id)!).toMatchObject({savedConnectionId:undefined,database:target.database,schema:target.schema});
      expect(JSON.stringify(controller.nativeSnapshot())).not.toContain("target-password");expect(JSON.stringify(encodeDocument(controller.session(next.id)!))).not.toContain("target-password");
      if(phase!=="error"){gate.resolve({config:target,database:target.database,schema:target.schema});await completion;}
    }
  });
  it("keeps a focused explicitly routed connection when the session switches to a manual target",async()=>{
    const {controller,transport,session}=setup();await connectedSource(controller,session);
    controller.updateBlock(session.id,session.focusedBlockId,{connection_id:"main-db",database_name:"ESIM",schema:"sales"});
    const gate=deferred<unknown>();transport.authenticate=async params=>params.session_id===session.id?gate.promise:{config:configured,database:"ESIM",schema:"sales"};
    const attempt=controller.connect(session.id,{...configured,database:"manual"});const next=controller.createSession();await controller.prepareSession(next.id);
    expect(transport.calls("connection.connect").at(-1)!.params).toEqual({session_id:next.id,connection_id:"main-db",database:"ESIM",schema:"sales"});
    gate.resolve({config:configured,database:"manual",schema:"public"});await attempt;
  });
  it("uses the direct connection's current USE context after a kernel error",async()=>{
    const {controller,transport,session}=setup();await controller.connect(session.id,{...configured,password:"private-password"});
    controller.patchSession(session.id,s=>applyExecutionContextChange(s,s.focusedBlockId,{previous:{database:"configured",schema:"public"},current:{database:"after_use",schema:"analysis"},requested_scope:{database:"configured",schema:"public"}}));
    controller.onRuntimeEvent({event:"session.error",payload:{session_id:session.id,error:"Kernel stopped"}});
    const next=controller.createSession();await controller.prepareSession(next.id);
    expect(transport.calls("connection.connect").at(-1)!.params).toMatchObject({config:{database:"after_use",schema:"analysis",password:"private-password"}});
    expect(controller.session(next.id)!.runtimeError).toBeUndefined();
  });
  it("discards closed-session direct credentials and refuses late direct authentication after disposal",async()=>{
    const {controller,transport,session}=setup();await controller.connect(session.id,{...configured,password:"closed-password"});await controller.closeSession(session.id);
    const next=controller.createSession();expect(next.connection).toBeUndefined();expect(next.connectionState).toBeUndefined();expect(transport.calls("connection.connect")).toHaveLength(1);
    const gate=deferred<unknown>();transport.authenticate=()=>gate.promise;
    const attempt=controller.connect(next.id,{...configured,name:"Disposed",password:"disposed-password"}),interrupted=expect(attempt).rejects.toThrow("interrompida");
    await vi.waitFor(()=>expect(transport.calls("connection.connect")).toHaveLength(2));controller.dispose();
    gate.resolve({config:{...configured,name:"Disposed",password:"disposed-password"},database:configured.database,schema:configured.schema});await interrupted;
    expect(controller.session(next.id)!.connection).toBeUndefined();expect(JSON.stringify(controller.nativeSnapshot())).not.toContain("disposed-password");
  });
  it("respects explicit document context and only inherits scripts without a saved connection",async()=>{
    const {controller,transport,session}=setup(true);await connectedSource(controller,session);
    const saved=controller.importDocument({blocks:[{language:"sql",code:"SELECT 1"}],desktop:{connection_id:"file-db",schema:"file-schema"},database_context:"file-catalog"},"File",undefined,{inheritConnection:true,sourceSessionId:session.id});await controller.prepareSession(saved.id);
    expect(transport.calls("connection.connect").at(-1)!.params).toEqual({session_id:saved.id,connection_id:"file-db",database:"file-catalog",schema:"file-schema"});
    const script=controller.importDocument({blocks:[{language:"sql",code:"SELECT 2"}]},"Script",undefined,{inheritConnection:true,sourceSessionId:session.id});await controller.prepareSession(script.id);
    expect(transport.calls("connection.connect").at(-1)!.params).toEqual({session_id:script.id,connection_id:"main-db",database:"ESIM",schema:"sales"});
  });
  it("retains a document's explicit database/schema when inheriting only its connection",async()=>{
    const {controller,transport,session}=setup();await connectedSource(controller,session);
    const file=controller.importDocument({blocks:[{language:"sql",code:"SELECT 1"}],database_context:"document_database",desktop:{schema:"document_schema"}},"File",undefined,{inheritConnection:true,sourceSessionId:session.id});await controller.prepareSession(file.id);
    expect(transport.calls("connection.connect").at(-1)!.params).toEqual({session_id:file.id,connection_id:"main-db",database:"document_database",schema:"document_schema"});
    const databaseOnly=controller.importDocument({blocks:[{language:"sql",code:"SELECT 2"}],database_context:"other_database"},"Other",undefined,{inheritConnection:true,sourceSessionId:session.id});await controller.prepareSession(databaseOnly.id);
    expect(transport.calls("connection.connect").at(-1)!.params).toEqual({session_id:databaseOnly.id,connection_id:"main-db",database:"other_database"});
  });
});
