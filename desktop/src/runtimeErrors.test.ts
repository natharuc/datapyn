import {afterEach,describe,expect,it} from "vitest";
import {applyRuntimeEvent,decodeDocument,encodeDocument,newSession,WorkspaceController,type SessionDocument} from "./workspace";
import {errorDetailsText,errorInfoFor} from "./errorPresentation";
import {isRuntimeErrorInfo,isRuntimeEvent,runtimeRequestError,RuntimeRequestError,type RuntimeErrorInfo,type RuntimeTransport} from "./runtime";

const missing:RuntimeErrorInfo={category:"not_found",title:"Objeto não encontrado",message:"Invalid object name 'missing_view'.",technical_details:'ProgrammingError: Invalid object name\n  File "kernel.py", line 20, in execute'};
const denied:RuntimeErrorInfo={category:"permission",title:"Acesso negado",message:"The SELECT permission was denied.",technical_details:"ProgrammingError: SQLSTATE 42000 (229)"};
function finish(session:SessionDocument,id:string,info:RuntimeErrorInfo){
  session={...session,currentExecutionId:id,currentBlockId:session.focusedBlockId};
  return applyRuntimeEvent(session,{event:"execution.finished",payload:{session_id:session.id,block_id:session.focusedBlockId,execution_id:id,status:"failed",duration_ms:20,error:info.message,error_info:info,results:[],variables:[]}});
}
const controllers:WorkspaceController[]=[];
afterEach(()=>controllers.splice(0).forEach(controller=>controller.dispose()));

describe("structured error protocol",()=>{
  it.each(["permission","authentication","not_found","syntax","timeout","network","cancelled","python","constraint","data","file","internal"])("accepts the fixed category %s",category=>{
    expect(isRuntimeErrorInfo({...missing,category})).toBe(true);
  });
  it.each([null,[],{...missing,category:"custom"},{...missing,title:""},{...missing,title:"x".repeat(257)},{...missing,message:{}},{...missing,message:"x".repeat(8193)},{...missing,technical_details:[]},{...missing,technical_details:"x".repeat(32769)}])("rejects malformed or unbounded metadata",info=>{
    expect(isRuntimeErrorInfo(info)).toBe(false);
    const session=newSession();expect(isRuntimeEvent({event:"execution.finished",payload:{session_id:session.id,execution_id:"failed",status:"failed",error_info:info}})).toBe(false);
  });
  it("retains a validated RPC error envelope for the connection banner",()=>{
    const error=runtimeRequestError({code:"operation_failed",message:"Object not found",error_info:missing});
    expect(error).toBeInstanceOf(RuntimeRequestError);expect((error as RuntimeRequestError).errorInfo).toBe(missing);
    expect(errorInfoFor(error)).toBe(missing);expect(errorDetailsText(missing)).toContain(missing.technical_details);
  });
  it("keeps legacy tracebacks in collapsed diagnostics instead of the summary",()=>{
    const traceback='Traceback (most recent call last):\n  File "driver.py", line 1\nRuntimeError: failure';
    const info=errorInfoFor(traceback);
    expect(info.message).not.toContain("Traceback");expect(info.technical_details).toBe(traceback);
    expect(errorInfoFor(new Error("Please select a database")).message).toBe("Please select a database");
  });
});

describe("execution-owned error output",()=>{
  it("never merges consecutive failures from different executions or discards their ownership",()=>{
    let session=newSession();session.blocks[0].block_name="analysis";
    session=finish(session,"first",missing);const previous=session.logs[0];
    session=finish(session,"second",denied);
    expect(session.logs).toHaveLength(2);expect(session.logs[0]).toBe(previous);
    expect(session.logs.map(line=>line.executionId)).toEqual(["first","second"]);
    expect(session.logs[0].errorInfo).toBe(missing);expect(session.logs[1].errorInfo).toBe(denied);
    expect(session.logs[0].text).not.toContain(denied.message);expect(session.logs[1].text).not.toContain(missing.message);
    expect(session.blocks[0].errorInfo).toBe(denied);expect(session.blocks[0].error).toBe(denied.message);
  });
  it("keeps one error entry when a terminal message is delivered again for the same execution",()=>{
    const first=finish(newSession(),"same-execution",missing),again=finish(first,"same-execution",missing);
    expect(again.logs).toHaveLength(1);expect(again.logs[0].id).toBe(first.logs[0].id);
  });
  it("batches Python stream chunks within one execution and starts another entry for the next execution",()=>{
    let session=newSession();session.currentBlockId=session.focusedBlockId;session.blocks[0].status="running";
    const output=(id:string,text:string,stream="stdout")=>{
      session={...session,currentExecutionId:id};session=applyRuntimeEvent(session,{event:"execution.output",payload:{session_id:session.id,execution_id:id,stream,text}});
    };
    output("first","hello");output("first","\nworld\n");output("second","next\n");
    expect(session.logs.map(line=>line.text)).toEqual(["hello\nworld\n","next\n"]);
    output("second","user stderr","stderr");session=finish(session,"second",missing);
    expect(session.logs.at(-2)?.text).toBe("user stderr");expect(session.logs.at(-1)?.errorInfo).toBe(missing);
    expect(session.logs.at(-1)?.text).not.toContain("user stderr");
  });
  it("does not persist structured errors in DPW files, restored documents or duplicated blocks",()=>{
    const controller=new WorkspaceController({request:async<T,>()=>({} as T),subscribe:async()=>()=>{}}),session=controller.session()!;controllers.push(controller);
    controller.updateBlock(session.id,session.focusedBlockId,{error:missing.message,errorInfo:missing});
    expect(JSON.stringify(encodeDocument(controller.session()!))).not.toContain("errorInfo");
    expect(decodeDocument({blocks:[{language:"sql",code:"SELECT 1",errorInfo:missing}]}).blocks[0].errorInfo).toBeUndefined();
    const copy=controller.duplicateBlock(session.id,session.focusedBlockId)!;expect(controller.session()!.blocks.find(block=>block.id===copy.id)?.errorInfo).toBeUndefined();
  });
  it("preserves structured authentication errors through the normal tab connection path",async()=>{
    const info={...denied,category:"authentication" as const,title:"Falha de autenticação"};
    const transport:RuntimeTransport={subscribe:async()=>()=>{},request:async<T,>(method:string)=>{
      if(method==="system.info")return {protocol_version:1,capabilities:{}} as T;
      if(method==="connection.connect")throw new RuntimeRequestError("authentication_failed",info.message,undefined,info);
      return {} as T;
    }};
    const controller=new WorkspaceController(transport),session=controller.session()!;controllers.push(controller);
    await expect(controller.connectSaved(session.id,"saved","Shared")).rejects.toThrow(info.message);
    expect(controller.session()!.connectionState).toMatchObject({phase:"error",error:info.message,errorInfo:info});
  });
});
