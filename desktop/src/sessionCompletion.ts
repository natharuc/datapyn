import type {CompletionContext} from "./editorLanguage";
import type {LanguageContextUpdate, RuntimeEvent} from "./runtime";
import type {Block, ConnectionConfig, SessionDocument} from "./workspace";

type Schema = NonNullable<CompletionContext["schemaSnapshot"]>;
interface Snapshot {version:number; schemaSnapshot?:Schema; tables:string[]; metadataState?:"ready"|"error";error?:string|null}
const scopeKey=(connection?:string,database?:string,schema?:string,blockId?:string,scopeInherited=false)=>JSON.stringify([connection ?? "",database ?? "",schema ?? "",blockId ?? "",scopeInherited]);

/** Metadata arrives independently of typing; each connection scope keeps its own bounded index. */
export class SessionLanguageContexts {
  private sessions=new Map<string,{variables:LanguageContextUpdate["variables"];variableSignature:string;namespaceVersion:number;version:number;hasRequestedScopes:boolean;scopes:Map<string,Snapshot>}>();
  private scopedBlocks=new Map<string,Set<string>>();
  accept(event:RuntimeEvent):boolean {
    if(event.event === "backend.exited"){const changed=this.sessions.size>0;this.sessions.clear();this.scopedBlocks.clear();return changed;}
    if(["session.reset","session.error","session.ready"].includes(event.event)){this.scopedBlocks.delete(event.payload.session_id);return this.sessions.delete(event.payload.session_id);}
    if(event.event === "execution.finished" && event.payload.context_change){
      const change=event.payload.context_change,requested=change.requested_scope;
      if(event.payload.block_id)this.ownBlock(event.payload.session_id,event.payload.block_id);
      let removed=false;
      if(event.payload.scope_inherited){
        const scopes=this.sessions.get(event.payload.session_id)?.scopes,targets=new Set<Snapshot>();
        if(scopes){for(const [key,value] of scopes){const [connection,,,block,inherited]=JSON.parse(key) as [string,string,string,string,boolean];if(connection===(requested.connection_id ?? "") && (inherited || !block))targets.add(value);}
          for(const [key,value] of scopes)if(targets.has(value)){scopes.delete(key);removed=true;}
        }
      }
      removed=this.invalidate(event.payload.session_id,requested.connection_id ?? undefined,requested.database ?? undefined,requested.schema ?? undefined,event.payload.block_id) || removed;
      return this.invalidate(event.payload.session_id,requested.connection_id ?? undefined,change.current.database ?? undefined,change.current.schema ?? undefined,event.payload.block_id) || removed;
    }
    if(event.event !== "language.context_updated")return false;
    const p=event.payload,previous=this.sessions.get(p.session_id);
    if(previous && p.version<=previous.version)return false;
    if(p.block_id && (p.schema_snapshot || p.metadata_invalidated))this.ownBlock(p.session_id,p.block_id);
    const scopes=previous?.scopes ?? new Map<string,Snapshot>();let key=scopeKey(p.connection_id,p.database,p.schema,p.block_id,p.scope_inherited);
    if(p.metadata_invalidated){
      const invalidated=new Set<Snapshot>();
      for(const [oldKey,value] of scopes){const [connection,,,block,inherited]=JSON.parse(oldKey) as [string,string,string,string,boolean];
        if(connection===(p.connection_id ?? "") && (p.metadata_invalidation_scope!=="block" || !p.block_id || block===p.block_id || p.scope_inherited && (inherited || !block)))invalidated.add(value);
      }
      for(const [oldKey,value] of scopes)if(invalidated.has(value))scopes.delete(oldKey);
    }
    // A namespace-only event does not define a new unresolved SQL scope. Keep
    // the most recent metadata for this connection instead of shadowing it
    // with an empty [connection,"",""] entry after an execution.
    if(!p.schema_snapshot && !p.metadata_invalidated && !scopes.has(key) && (!p.database || !p.schema))for(const existing of scopes.keys()){
      const [connection,database,schema,block,inherited]=JSON.parse(existing) as [string,string,string,string,boolean];
      if(connection===(p.connection_id ?? "") && block===(p.block_id ?? "") && inherited===Boolean(p.scope_inherited) && (!p.database || database===p.database) && (!p.schema || schema===p.schema))key=existing;
    }
    const old=scopes.get(key);
    let schemaSnapshot=old?.schemaSnapshot,tables=old?.tables ?? [];
    if(p.schema_snapshot){
      const entries=p.schema_snapshot.tables ?? [];
      schemaSnapshot={db_type:p.schema_snapshot.db_type,database:p.schema_snapshot.database ?? p.database,current_schema:p.schema_snapshot.current_schema ?? p.schema,default_schema:p.schema_snapshot.default_schema,tables:Object.create(null)};
      tables=[];
      for(const table of entries){
        const name=table.key || [table.schema,table.name].filter(Boolean).join(".");
        if(!name)continue;
        tables.push(name);
        schemaSnapshot.tables![name]={name:table.name,schema:table.schema,catalog:table.catalog,temporary:table.temporary,columns:p.schema_snapshot.columns?.[name] ?? []};
      }
    }
    // Namespace-only publishes keep the loaded schema's revision stable.
    const schemaVersion=p.schema_snapshot ? p.version : old?.version ?? p.version;
    const snapshot=!p.schema_snapshot && old ? old : {version:schemaVersion,schemaSnapshot,tables,metadataState:p.metadata_state ?? old?.metadataState,error:p.schema_error ?? (p.metadata_state==="ready"?undefined:old?.error)};
    scopes.delete(key);scopes.set(key,snapshot);
    // Requested defaults and the resolved catalogue share the same immutable
    // snapshot. Never guess a default schema from whichever scope arrived last.
    if(p.requested_scope){
      const request=p.requested_scope,requested=scopeKey(request.connection_id ?? undefined,request.database ?? undefined,request.schema ?? undefined,p.block_id,p.scope_inherited);
      // A late preparation may resolve a connector after USE changed it. Such
      // metadata belongs to the actual scope, never the old explicit selection.
      if((!request.database || request.database===p.database) && (!request.schema || request.schema===p.schema)){
        scopes.delete(requested);scopes.set(requested,snapshot);
      }
    }
    while(scopes.size>32)scopes.delete(scopes.keys().next().value!);
    const variableSignature=JSON.stringify(p.variables),namespaceVersion=(previous?.namespaceVersion ?? 0)+(previous?.variableSignature===variableSignature ? 0 : 1);
    this.sessions.set(p.session_id,{variables:p.variables,variableSignature,namespaceVersion,version:p.version,hasRequestedScopes:Boolean(p.requested_scope)||Boolean(previous?.hasRequestedScopes),scopes});return true;
  }
  private ownBlock(sessionId:string,blockId:string){
    let blocks=this.scopedBlocks.get(sessionId);if(!blocks){blocks=new Set();this.scopedBlocks.set(sessionId,blocks);}blocks.add(blockId);
  }
  retain(ids:ReadonlySet<string>){for(const id of this.sessions.keys())if(!ids.has(id))this.sessions.delete(id);for(const id of this.scopedBlocks.keys())if(!ids.has(id))this.scopedBlocks.delete(id);}
  get(sessionId:string,connection?:string,database?:string,schema?:string,blockId?:string,scopeInherited=false){
    const session=this.sessions.get(sessionId);if(!session)return undefined;
    const owned=Boolean(blockId && this.scopedBlocks.get(sessionId)?.has(blockId));
    let snapshot=session.scopes.get(scopeKey(connection,database,schema,blockId,scopeInherited)) ?? (owned?undefined:session.scopes.get(scopeKey(connection,database,schema)));
    // Empty inherited database/schema accepts the resolved default for the SAME connection only.
    if(!snapshot && !session.hasRequestedScopes && (!database || !schema)){
      const candidates=new Set<Snapshot>();
      for(const [key,value] of session.scopes){const [c,d,s,b,inherited]=JSON.parse(key) as [string,string,string,string,boolean];
        if(c===(connection ?? "") && (b===blockId && inherited===scopeInherited || !owned && !b) && (!database || d===database) && (!schema || s===schema))candidates.add(value);
      }
      if(candidates.size===1)snapshot=candidates.values().next().value;
    }
    return {variables:session.variables,namespaceVersion:session.namespaceVersion,...snapshot};
  }
  invalidateConnection(sessionId:string,connection?:string){
    const session=this.sessions.get(sessionId);if(!session)return false;
    const targets=new Set<Snapshot>();
    for(const [key,value] of session.scopes)if((JSON.parse(key) as string[])[0]===(connection ?? ""))targets.add(value);
    for(const [key,value] of session.scopes)if(targets.has(value))session.scopes.delete(key);
    return targets.size>0;
  }
  invalidate(sessionId:string,connection?:string,database?:string,schema?:string,blockId?:string,scopeInherited?:boolean){
    const session=this.sessions.get(sessionId);if(!session)return false;
    const targets=new Set<Snapshot>();
    for(const [key,value] of session.scopes){const [c,d,s,b,inherited]=JSON.parse(key) as [string,string,string,string,boolean];
      if(c===(connection ?? "") && d===(database ?? "") && s===(schema ?? "") && b===(blockId ?? "") && (scopeInherited===undefined || scopeInherited===inherited))targets.add(value);
    }
    let changed=false;
    for(const [key,value] of session.scopes){
      if(targets.has(value)){session.scopes.delete(key);changed=true;}
    }
    return changed;
  }
}

interface ParsedBlock {code:string;language:string;cellType?:string;imports:string[];hasCode:boolean;preamble:string}
export const inheritsSessionScope=(block:Block)=>block.connection_id===undefined && block.database_name===undefined && block.schema===undefined;
/** A block routed elsewhere inherits that connection's defaults, never another connection's database. */
export function completionConnectionScope(session:SessionDocument,block:Block,defaults?:Partial<ConnectionConfig>) {
  const inherits=block.connection_id===undefined || block.connection_id===session.savedConnectionId;
  const inheritedDatabase=(inherits?session.database ?? session.connection?.database:undefined) ?? defaults?.database;
  const database=block.database_name ?? inheritedDatabase;
  const sameDatabase=block.database_name===undefined || block.database_name===inheritedDatabase;
  const configuredSchema=defaults?.database && database!==defaults.database ? undefined : defaults?.schema;
  return {connectionId:block.connection_id ?? session.savedConnectionId,
    database,schema:block.schema ?? (sameDatabase ? (inherits?session.schema:undefined) ?? configuredSchema ?? (inherits && database===session.connection?.database?session.connection?.schema:undefined) : undefined)};
}
const MAX_PREAMBLE=200_000,MAX_IMPORTS=32_000;
export interface SessionDiagnosticsContext { globalImports:string; preamble:string }
interface DiagnosticBlockSource {id:string;code:string;language:string;cellType?:string;sqlName?:string}
interface DiagnosticSessionSource {blocks:SessionDocument["blocks"];sources:DiagnosticBlockSource[];revision:number;context?:SessionDiagnosticsContext}
const diagnosticCode=(block:Block)=>block.language==="python"&&(!block.cell_type||block.cell_type==="code")?block.code:"";
const PYTHON_KEYWORDS=new Set("False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield".split(" "));
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
  private diagnostics=new Map<string,DiagnosticSessionSource>();
  private diagnosticSequence=0;
  private diagnosticSource(session:SessionDocument):DiagnosticSessionSource {
    const previous=this.diagnostics.get(session.id);if(previous?.blocks===session.blocks)return previous;
    // Compare source references once per notebook edit; editor status/layout updates
    // replace blocks too, but must not invalidate every sibling's diagnostics.
    const unchanged=previous && previous.sources.length===session.blocks.length && session.blocks.every((block,index)=>{
      const source=previous.sources[index];return source.id===block.id && source.code===diagnosticCode(block) && source.language===block.language && source.cellType===block.cell_type && source.sqlName===(block.language==="sql"?block.block_name:undefined);
    });
    if(unchanged){previous.blocks=session.blocks;return previous;}
    const current={blocks:session.blocks,sources:session.blocks.map(block=>({id:block.id,code:diagnosticCode(block),language:block.language,cellType:block.cell_type,sqlName:block.language==="sql"?block.block_name:undefined})),revision:++this.diagnosticSequence};
    this.diagnostics.set(session.id,current);return current;
  }
  /** O(1) for all sibling readers after the first source comparison for this blocks array. */
  diagnosticsRevision(session:SessionDocument):number {return this.diagnosticSource(session).revision;}
  /** Release closed sessions and deleted blocks without evicting other open notebooks. */
  retain(ids:ReadonlySet<string>){
    for(const id of this.diagnostics.keys())if(!ids.has(id))this.diagnostics.delete(id);
    const blockIds=new Set<string>();for(const session of this.diagnostics.values())for(const source of session.sources)blockIds.add(source.id);
    for(const id of this.parsed.keys())if(!blockIds.has(id))this.parsed.delete(id);
  }
  private parse(block:Block){
    let entry=this.parsed.get(block.id);
    if(entry?.code===block.code && entry.language===block.language && entry.cellType===block.cell_type)return entry;
    const imports:string[]=[];
    if(block.language === "python" && (!block.cell_type || block.cell_type === "code") && (block.code.includes("import ") || block.code.includes("from "))){
      imports.push(...pythonImportLines(block.code));
    }
    entry={code:block.code,language:block.language,cellType:block.cell_type,imports,hasCode:/\S/.test(block.code),preamble:block.language === "python" ? safePythonPrefix(block.code) : ""};this.parsed.set(block.id,entry);return entry;
  }
  /** Diagnostics need peer declarations/imports only, never autocomplete metadata or DB access. */
  diagnosticsContext(session:SessionDocument):SessionDiagnosticsContext {
    const source=this.diagnosticSource(session);if(source.context)return source.context;
    const imports=new Set<string>(["import pandas as pd","import numpy as np","import polars as pl"]),parts:string[]=[];
    let size=0;
    for(const block of session.blocks){
      if(block.cell_type && block.cell_type!=="code")continue;
      const parsed=this.parse(block);
      for(const line of parsed.imports)imports.add(line);
      const prefix=block.language==="python"?parsed.preamble:/^[A-Za-z_]\w*$/.test(block.block_name)&&!PYTHON_KEYWORDS.has(block.block_name)?`${block.block_name} = None`:"";
      if(prefix && size+prefix.length+1<=MAX_PREAMBLE){parts.push(prefix);size+=prefix.length+1;}
    }
    const importParts:string[]=[];let importsLength=0;
    for(const line of imports)if(importsLength+line.length+1<=MAX_IMPORTS){importParts.push(line);importsLength+=line.length+1;}
    const context={globalImports:importParts.join("\n"),preamble:parts.join("\n")};
    source.context=context;return context;
  }
  context(session:SessionDocument,blockId:string,contexts:SessionLanguageContexts,defaults?:Partial<ConnectionConfig>):CompletionContext|undefined {
    const block=session.blocks.find(b=>b.id===blockId);if(!block)return undefined;
    this.diagnosticsRevision(session);
    const {connectionId,database,schema}=completionConnectionScope(session,block,defaults);
    const scopeInherited=inheritsSessionScope(block),snapshot=contexts.get(session.id,connectionId,database,schema,blockId,scopeInherited);
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
      // SQL names can be planned before the first run. After execution, only
      // the live namespace may assert that a DataFrame still exists (delete/overwrite).
      if(other.language === "sql" && ["idle","queued","running"].includes(other.status) && /^[\p{L}_][\p{L}\p{N}_]*$/u.test(other.block_name) && !PYTHON_KEYWORDS.has(other.block_name) && !variables.has(other.block_name))variables.set(other.block_name,{name:other.block_name,type:"DataFrame"});
      if(other.language === "python" && size+parsed.preamble.length+1<=MAX_PREAMBLE){
        parts.push(parsed.preamble);size+=parsed.preamble.length+1;
      }
    }
    const importParts:string[]=[];let importsLength=0;
    for(const line of imports)if(importsLength+line.length+1<=MAX_IMPORTS){importParts.push(line);importsLength+=line.length+1;}
    return {sessionId:session.id,blockId,scopeInherited,connectionId,database,schema,dbType:defaults?.db_type ?? (block.connection_id===undefined || block.connection_id===session.savedConnectionId?session.connection?.db_type:undefined),variables:[...variables.values()],tables:snapshot?.tables ?? [],
      schemaSnapshot:block.language === "sql" ? snapshot?.schemaSnapshot : undefined,schemaVersion:block.language === "sql" ? snapshot?.version : undefined,namespaceVersion:snapshot?.namespaceVersion,
      globalImports:importParts.join("\n"),preamble:parts.join("\n"),siblings};
  }
}
