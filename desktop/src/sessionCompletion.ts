import type {CompletionContext} from "./editorLanguage";
import type {LanguageContextUpdate, RuntimeEvent} from "./runtime";
import type {Block, SessionDocument} from "./workspace";

type Schema = NonNullable<CompletionContext["schemaSnapshot"]>;
interface Snapshot {version:number; schemaSnapshot?:Schema; tables:string[]}
const scopeKey=(connection?:string,database?:string,schema?:string)=>JSON.stringify([connection ?? "",database ?? "",schema ?? ""]);

/** Metadata arrives independently of typing; each connection scope keeps its own bounded index. */
export class SessionLanguageContexts {
  private sessions=new Map<string,{variables:LanguageContextUpdate["variables"];variableSignature:string;namespaceVersion:number;version:number;scopes:Map<string,Snapshot>}>();
  accept(event:RuntimeEvent):boolean {
    if(event.event === "backend.exited"){const changed=this.sessions.size>0;this.sessions.clear();return changed;}
    if(["session.reset","session.error","session.ready"].includes(event.event))return this.sessions.delete(event.payload.session_id);
    if(event.event !== "language.context_updated")return false;
    const p=event.payload,previous=this.sessions.get(p.session_id);
    if(previous && p.version<=previous.version)return false;
    const scopes=previous?.scopes ?? new Map<string,Snapshot>(),key=scopeKey(p.connection_id,p.database,p.schema);
    if(p.metadata_invalidated)for(const oldKey of scopes.keys())if((JSON.parse(oldKey) as string[])[0]===(p.connection_id ?? ""))scopes.delete(oldKey);
    const old=scopes.get(key);
    let schemaSnapshot=old?.schemaSnapshot,tables=old?.tables ?? [];
    if(p.schema_snapshot){
      const entries=p.schema_snapshot.tables ?? [];
      schemaSnapshot={db_type:p.schema_snapshot.db_type,tables:{}};
      tables=[];
      for(const table of entries){
        const name=table.key || [table.schema,table.name].filter(Boolean).join(".");
        if(!name)continue;
        tables.push(name);
        schemaSnapshot.tables![name]={name:table.name,schema:table.schema,temporary:table.temporary,columns:p.schema_snapshot.columns?.[name] ?? []};
      }
    }
    scopes.delete(key);scopes.set(key,{version:p.version,schemaSnapshot,tables});
    while(scopes.size>32)scopes.delete(scopes.keys().next().value!);
    const variableSignature=JSON.stringify(p.variables),namespaceVersion=(previous?.namespaceVersion ?? 0)+(previous?.variableSignature===variableSignature ? 0 : 1);
    this.sessions.set(p.session_id,{variables:p.variables,variableSignature,namespaceVersion,version:p.version,scopes});return true;
  }
  retain(ids:ReadonlySet<string>){for(const id of this.sessions.keys())if(!ids.has(id))this.sessions.delete(id);}
  get(sessionId:string,connection?:string,database?:string,schema?:string){
    const session=this.sessions.get(sessionId);if(!session)return undefined;
    let snapshot=session.scopes.get(scopeKey(connection,database,schema));
    // Empty inherited database/schema accepts the resolved default for the SAME connection only.
    if(!snapshot && (!database || !schema))for(const [key,value] of session.scopes){
      const [c,d,s]=JSON.parse(key) as string[];
      if(c===(connection ?? "") && (!database || d===database) && (!schema || s===schema))snapshot=value;
    }
    return {variables:session.variables,namespaceVersion:session.namespaceVersion,...snapshot};
  }
}

interface ParsedBlock {code:string;language:string;cellType?:string;imports:string[];hasCode:boolean;preamble:string}
const MAX_PREAMBLE=200_000,MAX_IMPORTS=32_000;
/** A truncated docstring/argument list must never absorb the next block or editable document. */
function safePythonPrefix(code:string,limit=2500):string {
  const end=Math.min(code.length,limit);let quote="",triple=false,comment=false,depth=0,safe=0,visible="";
  for(let i=0;i<end;i++){
    const c=code[i];
    if(comment && c!=="\n")continue;
    if(quote){
      if(c === "\\"){i++;continue;}
      if(triple && code.slice(i,i+3)===quote.repeat(3)){i+=2;quote="";triple=false;}
      else if(!triple && c===quote)quote="";
    }else if(c === "#")comment=true;
    else if(c === "'" || c === '"'){quote=c;triple=code.slice(i,i+3)===c.repeat(3);if(triple)i+=2;visible+="x";}
    else {if("([{".includes(c))depth++;if(")]}".includes(c))depth--;visible+=c;}
    if(c === "\n"){
      if(!quote && depth===0 && !/[:\\]\s*$/.test(visible) && !visible.trimStart().startsWith("@"))safe=i+1;
      visible="";comment=false;
    }
  }
  if(end===code.length && !quote && depth===0 && !/[:\\]\s*$/.test(visible) && !visible.trimStart().startsWith("@"))safe=end;
  return code.slice(0,safe);
}
function pythonImportLines(code:string):string[]{
  let triple="";
  const lines=code.split("\n").map(line=>{
    let visible="";
    for(let i=0;i<line.length;){
      if(triple){const end=line.indexOf(triple,i);if(end<0)break;i=end+3;triple="";continue;}
      const c=line[i];if(c === "#")break;
      if(c === "'" || c === '"'){
        if(line.slice(i,i+3)===c.repeat(3)){triple=c.repeat(3);i+=3;continue;}
        i++;while(i<line.length){if(line[i] === "\\"){i+=2;continue;}if(line[i++]===c)break;}
        visible+=" ";continue;
      }
      visible+=c;i++;
    }
    return visible.trim();
  });
  const imports:string[]=[];
  for(let i=0;i<lines.length;i++){
    let line=lines[i];if(!/^(?:import\s|from\s)/.test(line))continue;
    let balance=(line.match(/\(/g)?.length ?? 0)-(line.match(/\)/g)?.length ?? 0);
    while((balance>0 || /\\\s*$/.test(line)) && i+1<lines.length){
      const next=lines[++i];line+="\n"+next;balance+=(next.match(/\(/g)?.length ?? 0)-(next.match(/\)/g)?.length ?? 0);
    }
    // An unfinished import stays in its editable block until it can form a valid prelude.
    if(balance===0 && !/\\\s*$/.test(line))imports.push(line);
  }
  return imports;
}
/** Parse changed blocks once and build context only for the focused editor, never N preambles per key. */
export class SessionCompletionIndex {
  private parsed=new Map<string,ParsedBlock>();
  private parse(block:Block){
    let entry=this.parsed.get(block.id);
    if(entry?.code===block.code && entry.language===block.language && entry.cellType===block.cell_type)return entry;
    const imports:string[]=[];
    if(block.language === "python" && (!block.cell_type || block.cell_type === "code") && (block.code.includes("import ") || block.code.includes("from "))){
      imports.push(...pythonImportLines(block.code));
    }
    entry={code:block.code,language:block.language,cellType:block.cell_type,imports,hasCode:/\S/.test(block.code),preamble:block.language === "python" ? safePythonPrefix(block.code) : ""};this.parsed.set(block.id,entry);return entry;
  }
  context(session:SessionDocument,blockId:string,contexts:SessionLanguageContexts):CompletionContext|undefined {
    const block=session.blocks.find(b=>b.id===blockId);if(!block)return undefined;
    const connectionId=block.connection_id ?? session.savedConnectionId,database=block.database_name ?? session.database,schema=block.schema ?? session.schema;
    const snapshot=contexts.get(session.id,connectionId,database,schema);
    const variables=new Map((snapshot ? [] : session.variables).map(v=>[v.name,{name:v.name,type:v.type} as CompletionContext["variables"][number]]));
    for(const [name,v] of Object.entries(snapshot?.variables ?? {}))variables.set(name,{name,...v});
    for(const result of session.results)if(!snapshot) {
      const existing=variables.get(result.variable_name);
      if(!snapshot || existing)variables.set(result.variable_name,{...existing,name:result.variable_name,type:existing?.type ?? "DataFrame",columns:result.columns.map(c=>c.name)});
    }
    const imports=new Set<string>(["import pandas as pd","import numpy as np","import polars as pl"]),parts:string[]=[],siblings:NonNullable<CompletionContext["siblings"]>=[];
    let size=0;
    for(const other of session.blocks){
      const parsed=this.parse(other);
      for(const line of parsed.imports)imports.add(line);
      if(other.id===blockId || (other.cell_type && other.cell_type!=="code"))continue;
      const hasCode=parsed.hasCode;
      if(hasCode)siblings.push({name:other.block_name || "block",code:other.code,language:other.language,cellType:other.cell_type});
      if(block.language !== "python" || !hasCode)continue;
      if(other.language === "sql" && /^[A-Za-z_]\w*$/.test(other.block_name) && !variables.has(other.block_name))variables.set(other.block_name,{name:other.block_name,type:"DataFrame"});
      if(other.language === "python" && size+parsed.preamble.length+1<=MAX_PREAMBLE){
        parts.push(parsed.preamble);size+=parsed.preamble.length+1;
      }
    }
    // Removing blocks/profile switches must release potentially large source strings.
    const ids=new Set(session.blocks.map(b=>b.id));for(const id of this.parsed.keys())if(!ids.has(id))this.parsed.delete(id);
    const importParts:string[]=[];let importsLength=0;
    for(const line of imports)if(importsLength+line.length+1<=MAX_IMPORTS){importParts.push(line);importsLength+=line.length+1;}
    return {sessionId:session.id,connectionId,database,schema,variables:[...variables.values()],tables:snapshot?.tables ?? [],
      schemaSnapshot:block.language === "sql" ? snapshot?.schemaSnapshot : undefined,schemaVersion:block.language === "sql" ? snapshot?.version : undefined,namespaceVersion:snapshot?.namespaceVersion,
      globalImports:importParts.join("\n"),preamble:parts.join("\n"),siblings};
  }
}
