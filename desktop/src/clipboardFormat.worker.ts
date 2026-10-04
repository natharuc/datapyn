import { ClipboardFormatter, type ClipboardFormatOptions, type FormattedClipboard } from "./clipboardFormatter";
import type { CopyTable } from "./gridClipboard";
import type { ColumnFormats } from "./gridFormat";

export type ClipboardWorkerRequest = {kind:"start";columns:string[];options:ClipboardFormatOptions;formats?:ColumnFormats}|{kind:"rows";rows:CopyTable["rows"]}|{kind:"finish"};
export type ClipboardWorkerResponse = {ok:true;kind:"ready"}|{ok:true;kind:"result";value:FormattedClipboard}|{ok:false;error:string};
// A dedicated worker handles one copy. The client terminates it to cancel expensive formatting.
const scope=globalThis as unknown as {onmessage:((event:MessageEvent<ClipboardWorkerRequest>)=>void)|null;postMessage:(message:ClipboardWorkerResponse)=>void};
let formatter:ClipboardFormatter|undefined;
scope.onmessage=({data})=>{
  try{
    if(data.kind==="start")formatter=new ClipboardFormatter(data.columns,data.options,data.formats);
    else if(data.kind==="rows"){if(!formatter)throw new Error("Resposta de resultados inválida.");formatter.addRows(data.rows);}
    else{if(!formatter)throw new Error("Resposta de resultados inválida.");scope.postMessage({ok:true,kind:"result",value:formatter.finish()});formatter=undefined;return;}
    scope.postMessage({ok:true,kind:"ready"});
  }catch(error){formatter=undefined;scope.postMessage({ok:false,error:error instanceof Error?error.message:String(error)});}
};
