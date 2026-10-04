import type { CopyTable } from "./gridClipboard";
import type { ColumnFormats } from "./gridFormat";
import type { ClipboardFormatOptions, FormattedClipboard } from "./clipboardFormatter";
import type { ClipboardWorkerRequest, ClipboardWorkerResponse } from "./clipboardFormat.worker";
import { MAX_COPY_CELLS } from "./clipboardLimits";

export type { ClipboardFormatOptions, FormattedClipboard } from "./clipboardFormatter";
export interface ClipboardWorker {
  postMessage(message:ClipboardWorkerRequest):void;
  terminate():void;
  onmessage:((event:MessageEvent<ClipboardWorkerResponse>)=>void)|null;
  onerror:((event:ErrorEvent)=>void)|null;
  onmessageerror:((event:MessageEvent)=>void)|null;
}
export type ClipboardWorkerFactory=()=>ClipboardWorker;
const createWorker:ClipboardWorkerFactory=()=>new Worker(new URL("./clipboardFormat.worker.ts",import.meta.url),{type:"module",name:"datapyn-clipboard"});
function cancelled(){return new DOMException("Cópia cancelada.","AbortError");}

/** No synchronous formatting fallback: worker failure is surfaced, and abort terminates its CPU work. */
export function formatClipboard(table:CopyTable,options:ClipboardFormatOptions,formats?:ColumnFormats,signal?:AbortSignal,workerFactory:ClipboardWorkerFactory=createWorker):Promise<FormattedClipboard>{
  if(signal?.aborted)return Promise.reject(cancelled());
  if(table.columns.length*table.rows.length>MAX_COPY_CELLS)return Promise.reject(new Error("Use a exportação para seleções com mais de 200 mil células."));
  return new Promise((resolve,reject)=>{
    let worker:ClipboardWorker|undefined,settled=false,nextRow=0,timer:ReturnType<typeof setTimeout>|undefined;
    const finish=(error?:unknown,value?:FormattedClipboard)=>{
      if(settled)return;settled=true;signal?.removeEventListener("abort",abort);if(timer!==undefined)clearTimeout(timer);
      if(worker){worker.onmessage=null;worker.onerror=null;worker.onmessageerror=null;worker.terminate();}
      if(error)reject(error);else resolve(value!);
    };
    const abort=()=>finish(cancelled());
    const sendNext=()=>{
      timer=undefined;if(settled)return;if(signal?.aborted){abort();return;}
      try{
        if(nextRow>=table.rows.length){worker!.postMessage({kind:"finish"});return;}
        const first=nextRow;let cells=0,characters=0;
        // Each acknowledged batch yields back to the UI and limits structured-clone input.
        while(nextRow<table.rows.length&&nextRow-first<128&&cells<4096&&characters<262_144){
          const row=table.rows[nextRow];cells+=row.length;
          for(const value of row)if(typeof value==="string")characters+=value.length;
          nextRow++;
        }
        worker!.postMessage({kind:"rows",rows:table.rows.slice(first,nextRow)});
      }catch(error){finish(error);}
    };
    signal?.addEventListener("abort",abort,{once:true});
    try{
      worker=workerFactory();
      if(settled||signal?.aborted){worker.terminate();abort();return;}
      worker.onmessage=({data})=>{if(settled)return;if(signal?.aborted){abort();return;}if(!data.ok)finish(new Error(data.error));else if(data.kind==="result")finish(undefined,data.value);else timer=setTimeout(sendNext,0);};
      worker.onerror=event=>finish(new Error(event.message||"Não foi possível preparar a cópia."));
      worker.onmessageerror=()=>finish(new Error("Resposta de resultados inválida."));
      worker.postMessage({kind:"start",columns:table.columns,options,formats});
    }catch(error){finish(error);}
  });
}
