import {afterEach,describe,expect,it,vi} from "vitest";
import type {RuntimeTransport} from "./runtime";
import {disposeModel,models,selectedCode,takeRestoredEditorViewState} from "./editorRegistry";
import {WorkspaceController,type ConnectionConfig,type SessionDocument,type WorkspaceStorage} from "./workspace";

const configured:ConnectionConfig={db_type:"postgresql",host:"localhost",port:5432,database:"configured",schema:"public",username:"reader"};
function deferred<T>(){let resolve!:(value:T)=>void,reject!:(failure:unknown)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
class Transport implements RuntimeTransport {
  requests:Array<{method:string;params:Record<string,unknown>}>=[];
  create?:(params:Record<string,unknown>)=>Promise<unknown>;
  close?:()=>Promise<unknown>;
  importData?:()=>Promise<unknown>;
  authenticate?:(params:Record<string,unknown>)=>Promise<unknown>;
  async subscribe(){return ()=>{};}
  async request<T>(method:string,params:Record<string,unknown>={}):Promise<T>{
    this.requests.push({method,params});
    if(method==="system.info")return {protocol_version:1,capabilities:{}} as T;
    if(method==="session.create" && this.create)return await this.create(params) as T;
    if(method==="session.close" && this.close)return await this.close() as T;
    if(method==="data.import" && this.importData)return await this.importData() as T;
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
function setup(options:{storage?:WorkspaceStorage;maximizeFirstBlock?:boolean}={}){
  const transport=new Transport(),controller=new WorkspaceController(transport,options.storage,{nativePersistence:!options.storage,maximizeFirstBlock:options.maximizeFirstBlock});
  controllers.push(controller);return {transport,controller,session:controller.session()!};
}
afterEach(()=>{controllers.splice(0).forEach(controller=>controller.dispose());[...models.keys()].forEach(disposeModel);});
function title(controller:WorkspaceController,session:SessionDocument,value:string){controller.renameSession(session.id,value);return controller.session(session.id)!;}

describe("recently closed workspace tabs",()=>{
  it("reopens successfully closed tabs one at a time in reverse closing order",async()=>{
    const {controller,session}=setup();title(controller,session,"First");
    const second=title(controller,controller.createSession(),"Second"),third=title(controller,controller.createSession(),"Third");
    await controller.closeSession(session.id);await controller.closeSession(third.id);await controller.closeSession(second.id);
    expect(controller.getSnapshot().closedSessionCount).toBe(3);
    expect(controller.reopenClosedSession()?.title).toBe("Second");
    expect(controller.reopenClosedSession()?.title).toBe("Third");
    expect(controller.reopenClosedSession()?.title).toBe("First");
    expect(controller.getSnapshot().closedSessionCount).toBe(0);expect(controller.reopenClosedSession()).toBeUndefined();
  });

  it("restores the original tab position and activates the recovered tab",async()=>{
    const {controller,session}=setup();title(controller,session,"First");
    const second=title(controller,controller.createSession(),"Second");title(controller,controller.createSession(),"Third");
    await controller.closeSession(second.id);const restored=controller.reopenClosedSession()!;
    expect(controller.getSnapshot().sessions.map(tab=>tab.title)).toEqual(["First","Second","Third"]);
    expect(controller.getSnapshot().activeId).toBe(restored.id);expect(restored.id).not.toBe(second.id);
  });

  it("releases the automatic empty replacement tab's existing kernel and editor when reopening the last closed tab",async()=>{
    const {controller,transport,session}=setup();controller.updateBlock(session.id,session.focusedBlockId,{code:"SELECT 7"});await controller.closeSession(session.id);
    const placeholder=controller.session()!;await controller.prepareSession(placeholder.id);const dispose=vi.fn();
    models.set(placeholder.focusedBlockId,{model:{dispose,isDisposed:()=>false} as never,viewState:null});
    const restored=controller.reopenClosedSession()!;
    expect(controller.getSnapshot().sessions.map(tab=>tab.id)).toEqual([restored.id]);expect(controller.session(placeholder.id)).toBeUndefined();
    expect(dispose).toHaveBeenCalledOnce();expect(models.has(placeholder.focusedBlockId)).toBe(false);
    expect(transport.calls("session.close").map(call=>call.params.session_id)).toEqual([placeholder.id]);
    expect(controller.getSnapshot().closedSessionCount).toBe(0);expect(controller.reopenClosedSession()).toBeUndefined();
  });

  it.each(["modified","saved","results"] as const)("preserves the automatic replacement tab after it gains %s content",async kind=>{
    const {controller,transport,session}=setup();await controller.closeSession(session.id);const placeholder=controller.session()!;await controller.prepareSession(placeholder.id);
    controller.patchSession(placeholder.id,s=>({...s,...(kind==="modified"?{modified:true}:kind==="saved"?{filePath:"C:/saved-empty.sql",modified:false}:{results:[{result_id:"new-result",variable_name:"df",row_count:1,columns:[]}]})}));
    const restored=controller.reopenClosedSession()!;
    expect(controller.getSnapshot().sessions.map(tab=>tab.id)).toContain(placeholder.id);expect(controller.getSnapshot().sessions.map(tab=>tab.id)).toContain(restored.id);
    expect(transport.calls("session.close")).toHaveLength(0);
  });

  it("closes a replacement kernel whose pending creation completes after the empty tab was replaced",async()=>{
    const {controller,transport,session}=setup();await controller.closeSession(session.id);const placeholder=controller.session()!,gate=deferred<unknown>();transport.create=()=>gate.promise;
    const preparing=controller.prepareSession(placeholder.id),interrupted=expect(preparing).rejects.toThrow("encerrada");
    await vi.waitFor(()=>expect(transport.calls("session.create")).toHaveLength(1));const restored=controller.reopenClosedSession()!;
    gate.resolve({});await interrupted;
    expect(controller.getSnapshot().sessions.map(tab=>tab.id)).toEqual([restored.id]);expect(transport.calls("session.close").map(call=>call.params.session_id)).toEqual([placeholder.id]);
    expect(controller.getSnapshot().closedSessionCount).toBe(0);
  });

  it.each(["saved","direct"] as const)("preserves the replacement tab's intended %s connection while reopening another tab",async kind=>{
    for(const phase of ["preparing","connecting","error"] as const){
      const {controller,transport,session}=setup();await controller.closeSession(session.id);const placeholder=controller.session()!,gate=deferred<unknown>();transport.authenticate=()=>gate.promise;
      const attempt=kind==="saved"?controller.connectSaved(placeholder.id,"chosen-db","Chosen",{database:"chosen",schema:"work"}):controller.connect(placeholder.id,{...configured,name:"Manual",database:"chosen",schema:"work",password:"manual-secret"});
      const completion=attempt.then(()=>undefined,failure=>failure);
      if(phase!=="preparing")await vi.waitFor(()=>expect(transport.calls("connection.connect")).toHaveLength(1));
      if(phase==="error"){gate.reject(new Error("Login required"));expect(await completion).toBeInstanceOf(Error);}
      const restored=controller.reopenClosedSession()!;
      expect(controller.getSnapshot().sessions.map(tab=>tab.id)).toEqual([restored.id,placeholder.id]);expect(transport.calls("session.close")).toHaveLength(0);
      if(phase!=="error"){gate.resolve({config:configured,database:"chosen",schema:"work"});await completion;expect(controller.session(placeholder.id)?.connectionState?.phase).toBe("ready");}
      else expect(controller.session(placeholder.id)?.connectionState?.phase).toBe("error");
    }
  });

  it("preserves unsaved code, path, layout, focus and document settings without applying new-tab defaults",async()=>{
    const {controller,session}=setup({maximizeFirstBlock:true});
    controller.updateBlock(session.id,session.blocks[0].id,{code:"SELECT * FROM products",block_name:"products",height:312,collapsed:true,connection_id:"routed",database_name:"warehouse",schema:"sales",sql_parameters_enabled:true,sql_parameters:[{name:"id",value:3}],disable_automatic_transactions:true});
    const python=controller.addBlock(session.id,"python","answer = 42");
    controller.patchSession(session.id,s=>({...s,title:"Unsaved analysis",filePath:"C:/reports/analysis.dpw",maximizedBlockId:undefined,extras:{table_views:{products:{filter:"open"}},shared_parameters:[{name:"year",value:2026}],charts:[{id:"chart",title:"Revenue",variable_name:"products",config:{type:"bar"}}]}}));
    const before=controller.session(session.id)!;
    await controller.closeSession(session.id);const restored=controller.reopenClosedSession()!;
    expect(restored).toMatchObject({title:before.title,filePath:before.filePath,modified:true,extras:before.extras,maximizedBlockId:undefined});
    expect(restored.blocks.map(block=>block.code)).toEqual(before.blocks.map(block=>block.code));
    expect(restored.blocks[0]).toMatchObject({block_name:"products",height:312,collapsed:true,connection_id:"routed",database_name:"warehouse",schema:"sales",sql_parameters_enabled:true,sql_parameters:[{name:"id",value:3}],disable_automatic_transactions:true});
    expect(restored.focusedBlockId).toBe(restored.blocks[1].id);expect(restored.focusedBlockId).not.toBe(python.id);
    expect(restored.blocks.every(block=>!before.blocks.some(old=>old.id===block.id))).toBe(true);
  });

  it("maps a maximized block and editor selection/scroll to their new block IDs",async()=>{
    const {controller,session}=setup(),block=controller.addBlock(session.id,"sql","select 1;\nselect 2;");
    controller.maximizeBlock(session.id,block.id);
    const view={cursorState:[{inSelectionMode:true,selectionStart:{lineNumber:2,column:1},position:{lineNumber:2,column:9}}],viewState:{scrollTop:144,scrollLeft:12,firstPosition:{lineNumber:2,column:1},firstPositionDeltaTop:0},contributionsState:{}};
    models.set(block.id,{model:{dispose:vi.fn(),isDisposed:()=>false} as never,viewState:null,editor:{saveViewState:()=>view} as never});
    await controller.closeSession(session.id);disposeModel(block.id);const restored=controller.reopenClosedSession()!,newBlock=restored.blocks[1];
    expect(restored.maximizedBlockId).toBe(newBlock.id);expect(restored.focusedBlockId).toBe(newBlock.id);
    expect(selectedCode(newBlock.id,newBlock.code)).toBe("select 2");
    expect(takeRestoredEditorViewState(newBlock.id)).toEqual(view);
  });

  it("keeps clean saved documents clean instead of falsely marking them modified",async()=>{
    const {controller,session}=setup();controller.patchSession(session.id,s=>({...s,filePath:"C:/saved.sql",modified:false}));
    await controller.closeSession(session.id);expect(controller.reopenClosedSession()).toMatchObject({filePath:"C:/saved.sql",modified:false});
  });

  it("starts a fresh runtime with no results, logs, errors, transactions or automatic periodic execution",async()=>{
    const {controller,transport,session}=setup();await controller.ensureSession(session.id);
    controller.patchSession(session.id,s=>({...s,variables:[{name:"private_frame",type:"DataFrame",preview:"millions of rows"}],results:[{result_id:"old",variable_name:"private_frame",row_count:1_000_000,columns:[]}],images:[{data:"image-bytes",mime:"image/png"}],richOutputs:[{kind:"html",data:"old"} as never],logs:[{id:"old",time:"",stream:"stdout",text:"old",blockName:""}],periodicSeconds:60,runtimeError:"stale error",notice:"stale notice",currentExecutionId:"old",executionStartedAt:1,lastDurationMs:100,dataImport:{operationId:"old",path:"old.csv",phase:"error",current:0,total:0,error:"old"},blocks:s.blocks.map(block=>({...block,status:"succeeded",duration_ms:100,error:"old",transactionState:{pending:true} as never,results:s.results}))}));
    await controller.closeSession(session.id);const restored=controller.reopenClosedSession()!;await controller.prepareSession(restored.id);
    expect(restored).toMatchObject({busy:false,results:[],variables:[],images:[],logs:[]});
    for(const field of ["runtimeError","notice","currentExecutionId","executionStartedAt","lastDurationMs","periodicSeconds","dataImport"])expect(restored[field as keyof SessionDocument]).toBeUndefined();
    expect(restored.richOutputs?.length??0).toBe(0);expect(restored.commandExecutions?.length??0).toBe(0);
    expect(restored.blocks[0].status).toBe("idle");
    for(const field of ["transactionState","results","error","duration_ms"])expect(restored.blocks[0][field]).toBeUndefined();
    expect(transport.calls("session.create").map(call=>call.params.session_id)).toEqual([session.id,restored.id]);
    expect(transport.calls("execution.run")).toHaveLength(0);
  });

  it("reconnects the saved connection using the tab's current database and schema",async()=>{
    const {controller,transport,session}=setup();await controller.connectSaved(session.id,"saved-db","Primary",{database:"after_use",schema:"analytics"});
    await controller.closeSession(session.id);const restored=controller.reopenClosedSession()!;await controller.prepareSession(restored.id);
    expect(restored).toMatchObject({savedConnectionId:"saved-db",database:"after_use",schema:"analytics"});
    expect(transport.calls("connection.connect").at(-1)?.params).toEqual({session_id:restored.id,connection_id:"saved-db",database:"after_use",schema:"analytics"});
    expect(transport.calls("execution.run")).toHaveLength(0);
  });

  it("keeps a reopened authentication failure in its own tab without losing recovered code",async()=>{
    const {controller,transport,session}=setup();await controller.connectSaved(session.id,"saved-db","Primary");controller.updateBlock(session.id,session.focusedBlockId,{code:"SELECT 42"});
    await controller.closeSession(session.id);transport.authenticate=async()=>{throw new Error("Authentication required");};
    const restored=controller.reopenClosedSession()!;await vi.waitFor(()=>expect(controller.session(restored.id)?.connectionState?.phase).toBe("error"));
    expect(controller.session(restored.id)?.blocks[0].code).toBe("SELECT 42");expect(controller.getSnapshot().closedSessionCount).toBe(0);
  });

  it("restores the intended saved target when the tab closes during a connection switch",async()=>{
    const {controller,transport,session}=setup();await controller.connectSaved(session.id,"old-db","Previous",{database:"old",schema:"previous"});
    const gate=deferred<unknown>();transport.authenticate=async params=>params.session_id===session.id?gate.promise:{config:configured,database:params.database,schema:params.schema};
    const attempt=controller.connectSaved(session.id,"new-db","Intended",{database:"new",schema:"analytics"}),completion=attempt.then(()=>undefined,failure=>failure);
    await vi.waitFor(()=>expect(transport.calls("connection.connect")).toHaveLength(2));await controller.closeSession(session.id);
    const restored=controller.reopenClosedSession()!;await controller.prepareSession(restored.id);
    expect(controller.session(restored.id)).toMatchObject({savedConnectionId:"new-db",database:"new",schema:"analytics",extras:{connection_name:"Intended"},connectionState:{phase:"ready",name:"Intended"}});
    expect(transport.calls("connection.connect").at(-1)?.params).toEqual({session_id:restored.id,connection_id:"new-db",database:"new",schema:"analytics"});
    gate.resolve({config:configured,database:"obsolete-late-response",schema:"obsolete"});expect(await completion).toBeInstanceOf(Error);
    expect(controller.session(restored.id)).toMatchObject({savedConnectionId:"new-db",database:"new",schema:"analytics"});
  });

  it.each(["preparing","connecting","error"] as const)("does not restore an obsolete saved connection when a direct switch was %s",async phase=>{
    const {controller,transport,session}=setup();await controller.connectSaved(session.id,"obsolete-saved","Previous",{database:"old",schema:"old_schema"});
    controller.patchSession(session.id,s=>({...s,extras:{...s.extras,connection_name:"Previous",connection_group:"Old group"}}));
    const gate=deferred<unknown>(),target={...configured,name:"Manual target",database:"manual_database",schema:"manual_schema",password:"manual-password",ssh:{enabled:true,host:"jump",port:22,username:"ssh",auth_method:"password" as const,password:"ssh-secret",passphrase:"key-secret"}};
    transport.authenticate=()=>gate.promise;const attempt=controller.connect(session.id,target),completion=attempt.then(()=>undefined,failure=>failure);
    if(phase!=="preparing")await vi.waitFor(()=>expect(transport.calls("connection.connect")).toHaveLength(2));
    if(phase==="error"){gate.reject(new Error("Manual login failed"));expect(await completion).toBeInstanceOf(Error);}
    await controller.closeSession(session.id);const callsBefore=transport.calls("connection.connect").length,restored=controller.reopenClosedSession()!;await controller.prepareSession(restored.id);
    expect(restored.savedConnectionId).toBeUndefined();expect(restored.connection).toBeUndefined();expect(restored).toMatchObject({database:"manual_database",schema:"manual_schema",extras:{connection_name:"Manual target"}});
    expect(restored.extras.connection_group).toBeUndefined();expect(restored.notice).toContain("Reconecte");expect(transport.calls("connection.connect")).toHaveLength(callsBefore);
    for(const secret of ["manual-password","ssh-secret","key-secret"])expect(JSON.stringify(restored)).not.toContain(secret);
    if(phase!=="error"){gate.resolve({config:target,database:target.database,schema:target.schema});expect(await completion).toBeInstanceOf(Error);}
    expect(controller.session(restored.id)?.savedConnectionId).toBeUndefined();expect(controller.getSnapshot().closedSessionCount).toBe(0);
  });

  it("allows a pending authentication to finish when closing its tab fails",async()=>{
    const {controller,transport,session}=setup(),gate=deferred<unknown>();transport.authenticate=()=>gate.promise;
    const connecting=controller.connectSaved(session.id,"saved-db","Primary",{database:"current",schema:"analytics"});
    await vi.waitFor(()=>expect(transport.calls("connection.connect")).toHaveLength(1));transport.close=async()=>{throw new Error("Close failed");};
    await expect(controller.closeSession(session.id)).rejects.toThrow("Close failed");gate.resolve({config:configured,database:"current",schema:"analytics"});await connecting;
    expect(controller.session(session.id)?.connectionState?.phase).toBe("ready");expect(controller.getSnapshot().closedSessionCount).toBe(0);
  });

  it("never reuses direct connection passwords or SSH secrets from the closed tab",async()=>{
    const {controller,transport,session}=setup();await controller.connect(session.id,{...configured,password:"database-secret",ssh:{enabled:true,host:"jump",port:22,username:"network",auth_method:"password",password:"ssh-secret",passphrase:"key-secret"}});
    await controller.closeSession(session.id);const restored=controller.reopenClosedSession()!;await controller.prepareSession(restored.id);
    expect(JSON.stringify(restored)).not.toContain("database-secret");expect(JSON.stringify(restored)).not.toContain("ssh-secret");expect(JSON.stringify(restored)).not.toContain("key-secret");
    expect(transport.calls("connection.connect")).toHaveLength(1);expect(transport.calls("execution.run")).toHaveLength(0);
  });

  it("does not add missing tabs, refused closes or internal temporary tabs to history",async()=>{
    const {controller,session}=setup();await controller.closeSession("missing");
    controller.patchSession(session.id,s=>({...s,busy:true}));await expect(controller.closeSession(session.id)).rejects.toThrow();
    expect(controller.getSnapshot().closedSessionCount).toBe(0);expect(controller.session(session.id)).toBeDefined();
    controller.patchSession(session.id,s=>({...s,busy:false}));await controller.closeSession(session.id,{remember:false});
    expect(controller.getSnapshot().closedSessionCount).toBe(0);expect(controller.reopenClosedSession()).toBeUndefined();
  });

  it("keeps a tab open and does not record it when closing the runtime fails",async()=>{
    const {controller,transport,session}=setup();await controller.ensureSession(session.id);transport.close=async()=>{throw new Error("Close failed");};
    await expect(controller.closeSession(session.id)).rejects.toThrow("Close failed");expect(controller.session(session.id)).toBeDefined();expect(controller.getSnapshot().closedSessionCount).toBe(0);
    transport.close=undefined;await controller.closeSession(session.id);expect(controller.getSnapshot().closedSessionCount).toBe(1);
  });

  it("refuses to close an importing tab without adding a history entry",async()=>{
    const {controller,transport,session}=setup(),gate=deferred<unknown>();transport.importData=()=>gate.promise;
    const importing=controller.importData(session.id,"fixture.csv",{addBlock:false});await vi.waitFor(()=>expect(transport.calls("data.import")).toHaveLength(1));
    await expect(controller.closeSession(session.id)).rejects.toThrow("importação");expect(controller.getSnapshot().closedSessionCount).toBe(0);
    gate.resolve({result:{result_id:"imported",variable_name:"df",row_count:0,columns:[]},variables:[]});await importing;
    await controller.closeSession(session.id);expect(controller.getSnapshot().closedSessionCount).toBe(1);
  });

  it("deduplicates concurrent close requests for the same tab",async()=>{
    const {controller,transport,session}=setup();await controller.ensureSession(session.id);const gate=deferred<unknown>();transport.close=()=>gate.promise;
    const first=controller.closeSession(session.id),second=controller.closeSession(session.id);
    await vi.waitFor(()=>expect(transport.calls("session.close")).toHaveLength(1));gate.resolve({});await Promise.all([first,second]);
    expect(controller.getSnapshot().closedSessionCount).toBe(1);expect(controller.reopenClosedSession()?.id).not.toBe(session.id);expect(controller.reopenClosedSession()).toBeUndefined();
  });

  it("captures edits made while an asynchronous runtime close is still pending",async()=>{
    const {controller,transport,session}=setup();await controller.ensureSession(session.id);const gate=deferred<unknown>();transport.close=()=>gate.promise;
    const closing=controller.closeSession(session.id);controller.updateBlock(session.id,session.focusedBlockId,{code:"SELECT 'latest'"});controller.renameSession(session.id,"Latest title");
    gate.resolve({});await closing;const restored=controller.reopenClosedSession()!;
    expect(restored.title).toBe("Latest title");expect(restored.blocks[0].code).toBe("SELECT 'latest'");
  });

  it("keeps a closed document snapshot independent of later changes to its old objects",async()=>{
    const {controller,session}=setup(),parameters=[{name:"id",value:"original"}],extras={shared_parameters:[{name:"year",value:2026}]};
    controller.updateBlock(session.id,session.focusedBlockId,{code:"SELECT :id",sql_parameters:parameters});controller.patchSession(session.id,s=>({...s,extras}));
    await controller.closeSession(session.id);parameters[0].value="changed";extras.shared_parameters[0].value=2027;
    const restored=controller.reopenClosedSession()!;expect(restored.blocks[0].sql_parameters).toEqual([{name:"id",value:"original"}]);expect(restored.extras.shared_parameters).toEqual([{name:"year",value:2026}]);
  });

  it("does not consume history while the workspace is locked during a profile transition",async()=>{
    const {controller,session}=setup();await controller.closeSession(session.id);controller.setEditingLocked(true);
    expect(controller.reopenClosedSession()).toBeUndefined();expect(controller.getSnapshot().closedSessionCount).toBe(1);
    controller.setEditingLocked(false);expect(controller.reopenClosedSession()).toBeDefined();
  });

  it("never writes closed-tab content into browser drafts or a new controller",async()=>{
    const values=new Map<string,string>(),storage:WorkspaceStorage={getItem:key=>values.get(key)??null,setItem:(key,value)=>{values.set(key,value);},removeItem:key=>{values.delete(key);}};
    const {controller,session}=setup({storage});controller.updateBlock(session.id,session.focusedBlockId,{code:"closed-only-content"});controller.persist();
    await controller.closeSession(session.id);controller.persist();
    expect(JSON.stringify(controller.nativeSnapshot())).not.toContain("closed-only-content");expect([...values.values()].join("")).not.toContain("closed-only-content");
    const restarted=setup({storage}).controller;expect(restarted.getSnapshot().closedSessionCount).toBe(0);expect(restarted.reopenClosedSession()).toBeUndefined();
    expect(controller.reopenClosedSession()?.blocks[0].code).toBe("closed-only-content");
  });

  it.each(["restore","profile","dispose"] as const)("clears ephemeral history on %s",async action=>{
    const {controller,session}=setup();controller.setWorkspaceIdentity("profile-one");await controller.closeSession(session.id);expect(controller.getSnapshot().closedSessionCount).toBe(1);
    if(action==="restore")controller.restoreSnapshot(controller.nativeSnapshot());else if(action==="profile")controller.setWorkspaceIdentity("profile-two");else controller.dispose();
    expect(controller.getSnapshot().closedSessionCount).toBe(0);expect(controller.reopenClosedSession()).toBeUndefined();
  });

  it("keeps history when setting the same workspace identity",async()=>{
    const {controller,session}=setup();controller.setWorkspaceIdentity("same-profile");await controller.closeSession(session.id);controller.setWorkspaceIdentity("same-profile");
    expect(controller.reopenClosedSession()).toBeDefined();
  });

  it.each(["restore","profile","dispose"] as const)("ignores a late close after %s invalidates its originating workspace",async action=>{
    const {controller,transport,session}=setup();controller.setWorkspaceIdentity("profile-one");await controller.ensureSession(session.id);
    const gate=deferred<unknown>();transport.close=()=>gate.promise;const closing=controller.closeSession(session.id);
    if(action==="restore")controller.restoreSnapshot({documents:[]});else if(action==="profile")controller.setWorkspaceIdentity("profile-two");else controller.dispose();
    const before=controller.getSnapshot().sessions.map(tab=>tab.id);gate.resolve({});await closing;
    expect(controller.getSnapshot().sessions.map(tab=>tab.id)).toEqual(before);expect(controller.getSnapshot().closedSessionCount).toBe(0);
  });

  it.each(["restore","profile","dispose"] as const)("ignores a completed runtime close after %s invalidates the pending operation",async action=>{
    const {controller,transport,session}=setup();controller.setWorkspaceIdentity("profile-one");await controller.ensureSession(session.id);
    const gate=deferred<unknown>();transport.close=()=>gate.promise;const closing=controller.closeSession(session.id);await vi.waitFor(()=>expect(transport.calls("session.close")).toHaveLength(1));
    if(action==="restore")controller.restoreSnapshot({documents:[]});else if(action==="profile")controller.setWorkspaceIdentity("profile-two");else controller.dispose();
    const before=controller.getSnapshot().sessions.map(tab=>tab.id);gate.resolve({});await closing;
    expect(controller.getSnapshot().sessions.map(tab=>tab.id)).toEqual(before);expect(controller.getSnapshot().closedSessionCount).toBe(0);
  });

  it.each(["before-start","after-rpc"] as const)("invalidates an old close across profile A to B to A even %s",async phase=>{
    const {controller,transport,session}=setup();controller.setWorkspaceIdentity("profile-a");await controller.ensureSession(session.id);
    const gate=deferred<unknown>();transport.close=()=>gate.promise;const closing=controller.closeSession(session.id);
    if(phase==="after-rpc")await vi.waitFor(()=>expect(transport.calls("session.close")).toHaveLength(1));
    controller.setWorkspaceIdentity("profile-b");controller.setWorkspaceIdentity("profile-a");gate.resolve({});await closing;
    expect(controller.session(session.id)).toBeDefined();expect(controller.getSnapshot().closedSessionCount).toBe(0);expect(controller.reopenClosedSession()).toBeUndefined();
  });

  it("keeps only the 50 most recent closed tabs",async()=>{
    const {controller}=setup();for(let index=0;index<53;index++){const session=controller.session()!;title(controller,session,`Tab ${index}`);await controller.closeSession(session.id);}
    expect(controller.getSnapshot().closedSessionCount).toBe(50);const titles:string[]=[];let restored:SessionDocument|undefined;
    while((restored=controller.reopenClosedSession()))titles.push(restored.title);
    expect(titles).toHaveLength(50);expect(titles[0]).toBe("Tab 52");expect(titles.at(-1)).toBe("Tab 3");
  });

  it("evicts older large documents to bound memory while keeping the newest oversized document recoverable",async()=>{
    const {controller}=setup(),large="x".repeat(17*1024*1024);
    for(const name of ["Older large","Newest large"]){const session=controller.session()!;title(controller,session,name);controller.updateBlock(session.id,session.focusedBlockId,{code:large});await controller.closeSession(session.id);}
    expect(controller.getSnapshot().closedSessionCount).toBe(1);expect(controller.reopenClosedSession()?.title).toBe("Newest large");
    const session=controller.session()!;title(controller,session,"Oversized");controller.updateBlock(session.id,session.focusedBlockId,{code:"z".repeat(33*1024*1024)});await controller.closeSession(session.id);
    expect(controller.getSnapshot().closedSessionCount).toBe(1);expect(controller.reopenClosedSession()?.title).toBe("Oversized");
  });
});
