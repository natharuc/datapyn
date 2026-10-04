import { describe,expect,it,vi } from "vitest";
import { formatClipboard,type ClipboardWorker } from "./clipboardFormatClient";
import type { ClipboardWorkerResponse } from "./clipboardFormat.worker";

function fakeWorker(){const worker:ClipboardWorker={postMessage:vi.fn(),terminate:vi.fn(),onmessage:null,onerror:null,onmessageerror:null};return worker;}
function message(worker:ClipboardWorker,data:ClipboardWorkerResponse){worker.onmessage?.({data} as MessageEvent<ClipboardWorkerResponse>);}
const table={columns:["x"],rows:[["9007199254740993"]]},options={format:"excel" as const,headers:true};
describe("Clipboard worker client",()=>{
  it("posts the payload without doing synchronous formatting and terminates after success",async()=>{
    const worker=fakeWorker(),formats={x:{type:"number" as const,decimals:0}};
    const pending=formatClipboard(table,options,formats,undefined,()=>worker);
    expect(worker.postMessage).toHaveBeenCalledWith({kind:"start",columns:table.columns,options,formats});
    message(worker,{ok:true,kind:"result",value:{plain:"value",html:"<table></table>",rowCount:1}});
    expect(await pending).toEqual({plain:"value",html:"<table></table>",rowCount:1});expect(worker.terminate).toHaveBeenCalledOnce();expect(worker.onmessage).toBeNull();
  });
  it("does not create a worker for a pre-aborted or oversized selection",async()=>{
    const controller=new AbortController();controller.abort();const factory=vi.fn(fakeWorker);
    await expect(formatClipboard(table,options,undefined,controller.signal,factory)).rejects.toMatchObject({name:"AbortError"});
    await expect(formatClipboard({columns:["x"],rows:new Array(200_001)},options,undefined,undefined,factory)).rejects.toThrow(/200 mil/);expect(factory).not.toHaveBeenCalled();
  });
  it("terminates CPU work immediately on abort and ignores a late worker response",async()=>{
    const worker=fakeWorker(),controller=new AbortController(),pending=formatClipboard(table,options,undefined,controller.signal,()=>worker),oldHandler=worker.onmessage!;
    controller.abort();oldHandler({data:{ok:true,kind:"result",value:{plain:"stale",rowCount:1}}} as MessageEvent<ClipboardWorkerResponse>);
    await expect(pending).rejects.toMatchObject({name:"AbortError"});expect(worker.terminate).toHaveBeenCalledOnce();
  });
  it("cleans up an abort occurring while the worker is being created",async()=>{
    const worker=fakeWorker(),controller=new AbortController();
    await expect(formatClipboard(table,options,undefined,controller.signal,()=>{controller.abort();return worker;})).rejects.toMatchObject({name:"AbortError"});
    expect(worker.terminate).toHaveBeenCalledOnce();expect(worker.postMessage).not.toHaveBeenCalled();
  });
  it.each(["format","load","clone"])("surfaces %s failures without synchronous fallback",async kind=>{
    const worker=fakeWorker(),pending=formatClipboard(table,options,undefined,undefined,()=>worker);
    if(kind==="format")message(worker,{ok:false,error:"16 MB"});else if(kind==="load")worker.onerror?.({message:"load failed"} as ErrorEvent);else worker.onmessageerror?.({} as MessageEvent);
    await expect(pending).rejects.toThrow();expect(worker.terminate).toHaveBeenCalledOnce();
  });
  it("reports worker construction and postMessage failures",async()=>{
    await expect(formatClipboard(table,options,undefined,undefined,()=>{throw new Error("no worker");})).rejects.toThrow("no worker");
    const worker=fakeWorker();worker.postMessage=()=>{throw new Error("clone failed");};
    await expect(formatClipboard(table,options,undefined,undefined,()=>worker)).rejects.toThrow("clone failed");expect(worker.terminate).toHaveBeenCalledOnce();
  });
  it("transfers small acknowledged batches and yields between them instead of cloning the entire table",async()=>{
    vi.useFakeTimers();
    try{
      const worker=fakeWorker(),source={columns:["x"],rows:Array.from({length:300},(_,index)=>[String(index)])},pending=formatClipboard(source,options,undefined,undefined,()=>worker);
      expect(worker.postMessage).toHaveBeenCalledTimes(1);
      message(worker,{ok:true,kind:"ready"});expect(worker.postMessage).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(0);expect(worker.postMessage).toHaveBeenLastCalledWith({kind:"rows",rows:source.rows.slice(0,128)});
      message(worker,{ok:true,kind:"ready"});await vi.advanceTimersByTimeAsync(0);expect(worker.postMessage).toHaveBeenLastCalledWith({kind:"rows",rows:source.rows.slice(128,256)});
      message(worker,{ok:true,kind:"ready"});await vi.advanceTimersByTimeAsync(0);expect(worker.postMessage).toHaveBeenLastCalledWith({kind:"rows",rows:source.rows.slice(256)});
      message(worker,{ok:true,kind:"ready"});await vi.advanceTimersByTimeAsync(0);expect(worker.postMessage).toHaveBeenLastCalledWith({kind:"finish"});
      message(worker,{ok:true,kind:"result",value:{plain:"done",rowCount:300}});expect((await pending).rowCount).toBe(300);
    }finally{vi.useRealTimers();}
  });
  it("does not transfer another batch after cancellation during the UI yield",async()=>{
    vi.useFakeTimers();
    try{
      const worker=fakeWorker(),controller=new AbortController(),pending=formatClipboard(table,options,undefined,controller.signal,()=>worker);
      message(worker,{ok:true,kind:"ready"});controller.abort();await expect(pending).rejects.toMatchObject({name:"AbortError"});
      await vi.runAllTimersAsync();expect(worker.postMessage).toHaveBeenCalledTimes(1);expect(worker.terminate).toHaveBeenCalledOnce();
    }finally{vi.useRealTimers();}
  });
});
