import {afterEach,describe,expect,it,vi} from "vitest";
import {DEFAULT_PREFERENCES,loadPreferences,normalizePreferences,savePreferences} from "./preferences";
import {applyTransactionPreferences,readTransactionSettings,saveTransactionSettings} from "./transactionPreferences";
import {WorkspaceController,applyRuntimeEvent,decodeDocument,encodeDocument,newBlock,newSession} from "./workspace";
import {isRuntimeEvent,type ExecutionFinished,type RuntimeEvent,type RuntimeTransport} from "./runtime";

class Transport implements RuntimeTransport {
  executions:Record<string,unknown>[]=[];
  requests:Array<{method:string;params:Record<string,unknown>}>=[];
  listener?:(event:RuntimeEvent)=>void;
  async subscribe(listener:(event:RuntimeEvent)=>void){this.listener=listener;return()=>{};}
  async request<T>(method:string,params:Record<string,unknown>={}):Promise<T>{
    this.requests.push({method,params});
    if(method==="execution.review")return {confirmation_required:false,risks:[]} as T;
    if(method==="execution.run")this.executions.push(params);
    return (method==="system.info"?{protocol_version:1,capabilities:{}}:{}) as T;
  }
  finish(index:number,status:ExecutionFinished["status"]="succeeded"){
    const request=this.executions[index];this.listener?.({event:"execution.finished",payload:{session_id:String(request.session_id),execution_id:String(request.execution_id),block_id:String(request.block_id),status,duration_ms:1,results:[],variables:[]}});
  }
}
const controllers:WorkspaceController[]=[];
function setup(){const transport=new Transport(),controller=new WorkspaceController(transport,undefined,{nativePersistence:true});controllers.push(controller);return {controller,transport,session:controller.session()!};}
afterEach(()=>{controllers.splice(0).forEach(controller=>controller.dispose());vi.unstubAllGlobals();});

describe("automatic transaction preferences",()=>{
  it("preserves old defaults and persists an explicit global disable",()=>{
    expect(DEFAULT_PREFERENCES.automaticTransactions).toBe(true);
    expect(normalizePreferences({}).automaticTransactions).toBe(true);
    expect(normalizePreferences({automaticTransactions:"false" as unknown as boolean}).automaticTransactions).toBe(true);
    let value="{}";
    vi.stubGlobal("localStorage",{getItem:()=>value,setItem:(_key:string,next:string)=>{value=next;}});
    expect(loadPreferences().automaticTransactions).toBe(true);
    savePreferences({...DEFAULT_PREFERENCES,automaticTransactions:false});
    expect(loadPreferences().automaticTransactions).toBe(false);
  });
  it("reads and saves the authoritative runtime setting without touching a connection",async()=>{
    const request=vi.fn().mockResolvedValue({automatic_transactions:false});
    const transport={request,subscribe:vi.fn()} as RuntimeTransport;
    expect(await readTransactionSettings(transport)).toEqual({automatic_transactions:false});
    expect(await saveTransactionSettings(transport,false)).toEqual({automatic_transactions:false});
    expect(request.mock.calls).toEqual([["transactions.settings.get"],["transactions.settings.set",{automatic_transactions:false}]]);
    request.mockResolvedValue({automatic_transactions:"false"});
    await expect(readTransactionSettings(transport)).rejects.toThrow("Configuração de transações inválida");
  });
  it("does not overwrite the global policy when applying an unrelated edit before the initial read finishes",async()=>{
    const request=vi.fn().mockResolvedValue({automatic_transactions:false});
    const transport={request,subscribe:vi.fn()} as RuntimeTransport;
    expect(await applyTransactionPreferences(transport,{...DEFAULT_PREFERENCES,editorFontSize:18},false)).toMatchObject({editorFontSize:18,automaticTransactions:false});
    expect(request).toHaveBeenCalledExactlyOnceWith("transactions.settings.get");
    request.mockClear();request.mockResolvedValue({automatic_transactions:true});
    expect((await applyTransactionPreferences(transport,DEFAULT_PREFERENCES,true)).automaticTransactions).toBe(true);
    expect(request).toHaveBeenCalledExactlyOnceWith("transactions.settings.set",{automatic_transactions:true});
  });
  it.each(["sql","python"] as const)("applies the global setting and block override to %s",async language=>{
    const {controller,transport,session}=setup(),first=session.blocks[0];
    controller.updateBlock(session.id,first.id,{language,code:language==="sql"?"SELECT 1":"print(1)",disable_automatic_transactions:true});
    controller.addBlock(session.id,language,language==="sql"?"SELECT 2":"print(2)");
    const run=controller.runAll(session.id);
    await vi.waitFor(()=>expect(transport.executions).toHaveLength(1));
    expect(transport.executions[0]).toMatchObject({block_id:first.id,automatic_transactions:false,disable_automatic_transactions:true});
    transport.finish(0);await vi.waitFor(()=>expect(transport.executions).toHaveLength(2));
    expect(transport.executions[1]).toMatchObject({automatic_transactions:true,disable_automatic_transactions:false});
    transport.finish(1);await run;
    controller.setAutomaticTransactions(false);
    const next=controller.runBlock(session.id,controller.session(session.id)!.blocks[1].id);
    await vi.waitFor(()=>expect(transport.executions).toHaveLength(3));
    expect(transport.executions[2]).toMatchObject({automatic_transactions:false,disable_automatic_transactions:false});
    controller.setAutomaticTransactions(true); // No connection RPC is made by changing preferences.
    expect(transport.executions[2].automatic_transactions).toBe(false);
    transport.finish(2);await next;
    expect(transport.requests.every(item=>!/(?:commit|rollback|disconnect|transaction\.mode)/.test(item.method))).toBe(true);
  });
  it("saves block changes in DPW and native drafts, copying only the setting to duplicates",()=>{
    const {controller,session}=setup(),block=session.blocks[0],before=controller.nativeSnapshot();
    controller.updateBlock(session.id,block.id,{disable_automatic_transactions:true});
    const snapshot=controller.nativeSnapshot();
    expect(snapshot.documents[0].document).not.toBe(before.documents[0].document);
    expect(decodeDocument(encodeDocument(controller.session(session.id)!)).blocks[0].disable_automatic_transactions).toBe(true);
    expect((snapshot.documents[0].document.blocks as Record<string,unknown>[])[0].disable_automatic_transactions).toBe(true);
    const duplicate=controller.duplicateBlock(session.id,block.id)!;
    expect(controller.session(session.id)!.blocks.find(item=>item.id===duplicate.id)!.disable_automatic_transactions).toBe(true);expect(duplicate.id).not.toBe(block.id);
    const tab=controller.duplicateSession(session.id)!;
    expect(tab.blocks.every(item=>item.disable_automatic_transactions)).toBe(true);
    expect(tab.blocks.every(item=>!controller.session(session.id)!.blocks.some(old=>old.id===item.id))).toBe(true);
    expect(newBlock().disable_automatic_transactions).toBe(false);
    expect(decodeDocument({blocks:[{language:"sql",code:"SELECT 1"}]}).blocks[0].disable_automatic_transactions).toBe(false);
  });
  it("uses the same block policy for direct query-to-file execution and preserves the selection",async()=>{
    const {controller,transport,session}=setup(),block=session.blocks[0];
    controller.updateBlock(session.id,block.id,{code:"SELECT 1; SELECT 2",disable_automatic_transactions:true});
    const run=controller.runToFile(session.id,block.id,{path:"isolated.csv",format:"csv"},"SELECT 2");
    await vi.waitFor(()=>expect(transport.executions).toHaveLength(1));
    expect(transport.executions[0]).toMatchObject({block_id:block.id,code:"SELECT 2",automatic_transactions:false,disable_automatic_transactions:true,export:{path:"isolated.csv",format:"csv"}});
    transport.finish(0);await run;
  });
  it("keeps transaction state live only, scoped to the executed block",()=>{
    const session=newSession(),first=session.blocks[0],second=newBlock();session.blocks.push(second);
    session.currentExecutionId="execution";session.currentBlockId=first.id;
    const transaction_state={automatic_transactions:false,pending:true,state:"active" as const,transaction_count:1,xact_state:1};
    const event:RuntimeEvent={event:"execution.finished",payload:{session_id:session.id,execution_id:"execution",status:"succeeded",duration_ms:1,results:[],variables:[],automatic_transactions:false,transaction_state}};
    expect(isRuntimeEvent(event)).toBe(true);
    const updated=applyRuntimeEvent(session,event);
    expect(updated.blocks[0].transactionState).toEqual(transaction_state);
    expect(updated.blocks[1].transactionState).toBeUndefined();
    expect((encodeDocument(updated).blocks as Record<string,unknown>[])[0]).not.toHaveProperty("transactionState");
    expect(decodeDocument({blocks:[{language:"sql",code:"SELECT 1",transactionState:transaction_state}]}).blocks[0].transactionState).toBeUndefined();
    expect(applyRuntimeEvent(updated,{event:"session.reset",payload:{session_id:session.id}}).blocks[0].transactionState).toBeUndefined();
    expect(isRuntimeEvent({...event,payload:{...event.payload,transaction_state:{...transaction_state,pending:"false"}}})).toBe(false);
  });
  it("accepts legacy metadata and rejects a malformed transaction mode",()=>{
    const event={event:"language.context_updated",payload:{session_id:"analysis",version:1,variables:{}}};
    expect(isRuntimeEvent(event)).toBe(true);
    for(const mode of [true,false])expect(isRuntimeEvent({...event,payload:{...event.payload,automatic_transactions:mode}})).toBe(true);
    expect(isRuntimeEvent({...event,payload:{...event.payload,automatic_transactions:"false"}})).toBe(false);
  });
});
