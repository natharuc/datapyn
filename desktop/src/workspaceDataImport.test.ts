import { describe, expect, it, vi } from "vitest";
import { WorkspaceController, encodeDocument, type ImportedData } from "./workspace";
import { isRuntimeEvent, type RuntimeEvent, type RuntimeTransport } from "./runtime";
import { dataImportPending } from "./dataImport";

class ImportTransport implements RuntimeTransport {
  requests: Array<{method:string;params:Record<string,unknown>}> = [];
  imports: Array<{params:Record<string,unknown>;resolve:(data:ImportedData)=>void;reject:(error:Error)=>void}> = [];
  async request<T>(method:string,params:Record<string,unknown>={}) {
    this.requests.push({method,params});
    if(method==="system.info")return {protocol_version:1,python_version:"3.12",capabilities:{}} as T;
    if(method==="data.import")return new Promise<ImportedData>((resolve,reject)=>this.imports.push({params,resolve,reject})) as Promise<T>;
    return {} as T;
  }
  async subscribe(){return ()=>{};}
  finish(index:number) {
    const name=String(this.imports[index].params.path).split(/[\\/]/).at(-1)!.split(".")[0];
    const result:ImportedData={result:{result_id:`result-${index}`,variable_name:name,columns:[{name:"value",dtype:"int64"}],row_count:200000},variables:[{name,type:"DataFrame",preview:"200000 rows"}],options:{delimiter:";",encoding:"utf-8-sig",decimal:"."}};
    this.imports[index].resolve(result);return result;
  }
  progress(controller:WorkspaceController,index:number,phase:"reading"|"registering"|"completed"|"cancelled",current=50,total=100) {
    const params=this.imports[index].params;
    controller.onRuntimeEvent({event:"data.import_progress",payload:{session_id:String(params.session_id),operation_id:String(params.operation_id),phase,current,total}});
  }
}

describe("data import lifecycle",()=>{
  it.each([false,true])("shows loading before reading and preserves focus/layout (maximized=%s)",async(maximized)=>{
    const transport=new ImportTransport(),controller=new WorkspaceController(transport),session=controller.session()!;
    if(maximized)controller.maximizeBlock(session.id,session.blocks[0].id);
    const job=controller.importData(session.id,"C:\\data\\sales.csv");
    expect(controller.session()!.dataImport).toMatchObject({path:"C:\\data\\sales.csv",phase:"preparing"});
    await vi.waitFor(()=>expect(transport.imports).toHaveLength(1));
    expect(dataImportPending(controller.session()!.dataImport)).toBe(true);
    transport.progress(controller,0,"reading",20,100);
    expect(controller.session()!.dataImport).toMatchObject({phase:"reading",current:20,total:100});
    transport.progress(controller,0,"registering",100,100);
    expect(controller.session()!.dataImport?.phase).toBe("registering");
    transport.finish(0);await job;
    const imported=controller.session()!;
    expect(imported.dataImport).toBeUndefined();expect(imported.blocks).toHaveLength(2);
    expect(imported.focusedBlockId).toBe(session.focusedBlockId);expect(imported.maximizedBlockId).toBe(maximized?session.blocks[0].id:undefined);
    expect(imported.blocks[1].code).toContain('sep=";"');expect(imported.blocks[1].code).not.toContain('engine="python"');
    expect(imported.results[0].row_count).toBe(200000);expect(encodeDocument(imported)).not.toHaveProperty("dataImport");
    controller.dispose();
  });
  it("serializes repeated drops in one tab and imports independently in another tab",async()=>{
    const transport=new ImportTransport(),controller=new WorkspaceController(transport),first=controller.session()!;
    const firstJob=controller.importData(first.id,"one.csv"),secondJob=controller.importData(first.id,"two.xlsx");
    const second=controller.createSession(),otherJob=controller.importData(second.id,"other.csv");
    await vi.waitFor(()=>expect(transport.imports).toHaveLength(2));
    expect(transport.imports.map(item=>item.params.path)).toEqual(["one.csv","other.csv"]);
    transport.finish(0);await firstJob;
    await vi.waitFor(()=>expect(transport.imports).toHaveLength(3));expect(transport.imports[2].params.session_id).toBe(first.id);
    transport.finish(1);transport.finish(2);await Promise.all([otherJob,secondJob]);
    expect(controller.getSnapshot().activeId).toBe(second.id);
    expect(controller.session(first.id)?.results).toHaveLength(2);expect(controller.session(first.id)?.blocks).toHaveLength(3);
    expect(controller.session(second.id)?.results).toHaveLength(1);controller.dispose();
  });
  it("blocks conflicting actions only in the importing tab",async()=>{
    const transport=new ImportTransport(),controller=new WorkspaceController(transport),session=controller.session()!;
    controller.updateBlock(session.id,session.blocks[0].id,{code:"SELECT 1"});
    const job=controller.importData(session.id,"one.csv");await vi.waitFor(()=>expect(transport.imports).toHaveLength(1));
    await expect(controller.runBlock(session.id,session.blocks[0].id)).rejects.toThrow("importação");
    await expect(controller.closeSession(session.id)).rejects.toThrow("importação");
    expect(()=>controller.restoreSnapshot({documents:[]})).toThrow("importações");
    expect(controller.createSession().id).not.toBe(session.id);transport.finish(0);await job;controller.dispose();
  });
  it("retains data/layout on failure and allows retry",async()=>{
    const transport=new ImportTransport(),controller=new WorkspaceController(transport),session=controller.session()!;
    const previous={result_id:"old",variable_name:"old",row_count:1,columns:[]};
    controller.patchSession(session.id,s=>({...s,results:[previous],variables:[{name:"old",type:"DataFrame",preview:"1 row"}]}));
    const job=controller.importData(session.id,"bad.xlsx");const handled=job.catch(error=>error);
    await vi.waitFor(()=>expect(transport.imports).toHaveLength(1));transport.imports[0].reject(new Error("Invalid workbook"));await handled;
    expect(controller.session()!.dataImport).toMatchObject({phase:"error",error:"Invalid workbook"});
    expect(controller.session()!.results).toEqual([previous]);expect(controller.session()!.blocks).toEqual(session.blocks);
    const retry=controller.importData(session.id,"good.xlsx");await vi.waitFor(()=>expect(transport.imports).toHaveLength(2));transport.finish(1);await retry;
    expect(controller.session()!.dataImport).toBeUndefined();expect(controller.session()!.results).toHaveLength(2);controller.dispose();
  });
  it("cancels by operation ID without restarting the session",async()=>{
    const transport=new ImportTransport(),controller=new WorkspaceController(transport),session=controller.session()!;
    const job=controller.importData(session.id,"large.csv"),handled=job.catch(error=>error);
    await vi.waitFor(()=>expect(transport.imports).toHaveLength(1));await controller.cancelImport(session.id);
    expect(transport.requests.find(item=>item.method==="data.import_cancel")?.params).toEqual({session_id:session.id,operation_id:transport.imports[0].params.operation_id});
    transport.progress(controller,0,"reading",75);expect(controller.session()!.dataImport?.phase).toBe("cancelling");
    transport.imports[0].reject(new Error("ExportCancelled: Import cancelled"));await handled;
    expect(controller.session()!.dataImport?.phase).toBe("cancelled");expect(controller.session()!.blocks).toHaveLength(1);
    expect(transport.requests.some(item=>["execution.cancel","session.reset","session.close"].includes(item.method))).toBe(false);
    controller.clearImportStatus(session.id);expect(controller.session()!.dataImport).toBeUndefined();controller.dispose();
  });
  it("can cancel session preparation before a file read is submitted",async()=>{
    const transport=new ImportTransport(),controller=new WorkspaceController(transport),session=controller.session()!;
    const job=controller.importData(session.id,"large.xlsx"),handled=job.catch(error=>error);
    await controller.cancelImport(session.id);
    expect((await handled).message).toContain("Import cancelled");
    expect(transport.imports).toHaveLength(0);expect(controller.session()!.dataImport?.phase).toBe("cancelled");controller.dispose();
  });
  it("accepts a completed import if cancellation arrived after the backend commit",async()=>{
    const transport=new ImportTransport(),controller=new WorkspaceController(transport),session=controller.session()!;
    const job=controller.importData(session.id,"done.csv");await vi.waitFor(()=>expect(transport.imports).toHaveLength(1));
    await controller.cancelImport(session.id);transport.finish(0);await job;
    expect(controller.session()!.dataImport).toBeUndefined();expect(controller.session()!.results).toHaveLength(1);controller.dispose();
  });
  it("ignores stale progress and keeps operation state out of document persistence",async()=>{
    const transport=new ImportTransport(),controller=new WorkspaceController(transport,undefined,{nativePersistence:true}),session=controller.session()!;
    const original=controller.nativeSnapshot().documents[0],job=controller.importData(session.id,"one.csv");
    await vi.waitFor(()=>expect(transport.imports).toHaveLength(1));
    controller.onRuntimeEvent({event:"data.import_progress",payload:{session_id:session.id,operation_id:"stale",phase:"reading",current:90,total:100}});
    expect(controller.session()!.dataImport?.current).toBe(0);expect(controller.nativeSnapshot().documents[0]).toBe(original);
    transport.progress(controller,0,"completed",100);expect(dataImportPending(controller.session()!.dataImport)).toBe(true);
    transport.finish(0);await job;controller.dispose();
  });
  it("shows a terminal error when the runtime exits while importing",async()=>{
    const transport=new ImportTransport(),controller=new WorkspaceController(transport),session=controller.session()!;
    const job=controller.importData(session.id,"large.csv"),handled=job.catch(error=>error);
    await vi.waitFor(()=>expect(transport.imports).toHaveLength(1));controller.onRuntimeEvent({event:"backend.exited",payload:{message:"Runtime stopped"}});
    expect(controller.session()!.dataImport).toMatchObject({phase:"error",error:"Runtime stopped"});
    transport.imports[0].reject(new Error("Runtime stopped"));await handled;controller.dispose();
  });
});

describe("import progress wire validation",()=>{
  const valid={event:"data.import_progress",payload:{session_id:"session",operation_id:"import",phase:"reading",current:0,total:10}};
  it("accepts finite file progress",()=>expect(isRuntimeEvent(valid)).toBe(true));
  it.each([{operation_id:""},{phase:"unknown"},{current:-1},{total:Infinity},{total:"10"}])("rejects malformed progress %j",change=>expect(isRuntimeEvent({...valid,payload:{...valid.payload,...change}})).toBe(false));
});
