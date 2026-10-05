import {describe,expect,it,vi} from "vitest";
import {isRuntimeEvent,type RuntimeEvent} from "./runtime";
import {completionConnectionScope,SessionCompletionIndex,SessionLanguageContexts} from "./sessionCompletion";
import {applyRuntimeEvent,newBlock,newSession} from "./workspace";
import {completionSite,localCompletions} from "./editorCompletions";

const update=(version:number,connection="a",database="db",schema="public",tables=["users"]):RuntimeEvent=>({event:"language.context_updated",payload:{session_id:"s",connection_id:connection,database,schema,version,
  variables:{df:{type:"DataFrame",module:"pandas.core.frame",columns:["sales total"]}},
  schema_snapshot:{db_type:"postgresql",tables:tables.map(name=>({key:`${schema}.${name}`,name,schema})),columns:{[`${schema}.${tables[0]}`]:[{name:"Id",data_type:"integer"}]}}}});

describe("language metadata delivery",()=>{
  it("preserves the physical default schema independently from the focused SQL Server schema",()=>{
    const contexts=new SessionLanguageContexts();
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",connection_id:"esim",database:"ESIM",schema:"sales",version:1,variables:{},
      schema_snapshot:{db_type:"sqlserver",database:"ESIM",current_schema:"sales",default_schema:"dbo",tables:[{name:"Items",schema:"sales",catalog:"ESIM"}],columns:{}}}});
    expect(contexts.get("s","esim","ESIM","sales")?.schemaSnapshot).toMatchObject({current_schema:"sales",default_schema:"dbo"});
  });
  it("routes a block connection without inheriting another connection's database or schema",()=>{
    const session=newSession();session.id="s";session.savedConnectionId="a";session.database="database_a";session.schema="schema_a";
    const block={...newBlock("sql","SELECT o."),connection_id:"b"};session.blocks=[block];
    expect(completionConnectionScope(session,block)).toEqual({connectionId:"b",database:undefined,schema:undefined});
    expect(completionConnectionScope(session,{...block,connection_id:"a"})).toEqual({connectionId:"a",database:"database_a",schema:"schema_a"});
    expect(completionConnectionScope(session,{...block,database_name:"explicit",schema:"explicit_schema"})).toEqual({connectionId:"b",database:"explicit",schema:"explicit_schema"});
    const contexts=new SessionLanguageContexts();contexts.accept(update(1,"b","database_b","schema_b",["orders"]));
    const value=new SessionCompletionIndex().context(session,block.id,contexts)!;
    expect(value.tables).toEqual(["schema_b.orders"]);expect(value.database).toBeUndefined();
    expect(value.schemaSnapshot).toMatchObject({database:"database_b",current_schema:"schema_b"});
  });
  it("retains temporary table metadata from the kernel",()=>{
    const contexts=new SessionLanguageContexts();
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",version:1,variables:{},schema_snapshot:{db_type:"sqlite",tables:[{key:"temp.sales",name:"sales",schema:"temp",temporary:true}],columns:{"temp.sales":[{name:"value"}]}}}});
    expect(contexts.get("s")?.schemaSnapshot?.tables?.["temp.sales"]).toMatchObject({temporary:true,columns:[{name:"value"}]});
  });
  it("admits context updates before execution-id validation and rejects malformed versions",()=>{
    expect(isRuntimeEvent(update(1))).toBe(true);
    expect(isRuntimeEvent({...update(1),payload:{...update(1).payload,version:NaN}})).toBe(false);
    expect(isRuntimeEvent({event:"language.context_updated",payload:{session_id:"s",version:1,variables:[]}})).toBe(false);
  });
  it("isolates scopes and sessions, accepts resolved defaults and discards old responses",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(update(1));contexts.accept(update(2,"b","other","sales",["orders"]));
    expect(contexts.get("s","a")?.tables).toEqual(["public.users"]);
    expect(contexts.get("s","b","db","public")?.tables).toBeUndefined();
    expect(contexts.get("another","a")).toBeUndefined();expect(contexts.accept(update(1))).toBe(false);
    expect(contexts.get("s","b","other","sales")?.tables).toEqual(["sales.orders"]);
    contexts.accept({event:"session.reset",payload:{session_id:"s"}});expect(contexts.get("s","a")).toBeUndefined();
  });
  it("preserves loaded schema on namespace-only publishes and bounds scope storage",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(update(1));
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",connection_id:"a",database:"db",schema:"public",version:2,variables:{}}});
    expect(contexts.get("s","a")?.tables).toEqual(["public.users"]);expect(contexts.get("s","a")?.variables).toEqual({});
    for(let i=3;i<40;i++)contexts.accept(update(i,`connection-${i}`));expect(contexts.get("s","a")?.tables).toBeUndefined();
    contexts.retain(new Set());expect(contexts.get("s","connection-39")).toBeUndefined();
  });
  it("keeps resolved SQL metadata after a namespace publish omits database and schema",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(update(1));
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",connection_id:"a",version:2,variables:{live:{type:"int"}}}});
    expect(contexts.get("s","a")?.tables).toEqual(["public.users"]);
    expect(contexts.get("s","a","db","public")?.version).toBe(1);
    expect(contexts.get("s","a")?.variables).toEqual({live:{type:"int"}});
  });
  it("invalidates all database/schema scopes of the altered connection only",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(update(1));contexts.accept(update(2,"a","db","other"));contexts.accept(update(3,"b"));
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",connection_id:"a",database:"db",schema:"public",version:4,variables:{},metadata_invalidated:true,schema_snapshot:{}}});
    expect(contexts.get("s","a","db","public")?.tables).toEqual([]);expect(contexts.get("s","a","db","other")?.tables).toBeUndefined();
    expect(contexts.get("s","b")?.tables).toEqual(["public.users"]);
  });
  it("keeps Python inference valid when SQL metadata refreshes without namespace changes",()=>{
    const contexts=new SessionLanguageContexts(),index=new SessionCompletionIndex(),session=newSession();session.id="s";session.savedConnectionId="a";
    session.blocks[0].language="python";contexts.accept(update(1));
    const before=index.context(session,session.blocks[0].id,contexts)!;
    contexts.accept(update(2));const after=index.context(session,session.blocks[0].id,contexts)!;
    expect(after.namespaceVersion).toBe(before.namespaceVersion);expect(after.schemaVersion).toBeUndefined();expect(after.schemaSnapshot).toBeUndefined();
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",version:3,variables:{}}});
    expect(index.context(session,session.blocks[0].id,contexts)!.namespaceVersion).toBeGreaterThan(after.namespaceVersion!);
  });
  it("keeps scoped schema revisions stable on namespace-only publishes and isolates other sessions",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(update(1));contexts.accept(update(2,"b","other","sales",["orders"]));
    const namespaceVersion=contexts.get("s","a","db","public")!.namespaceVersion;
    expect(contexts.get("s","a","db","public")!.version).toBe(1);expect(contexts.get("s","b","other","sales")!.version).toBe(2);
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",connection_id:"a",database:"db",schema:"public",version:3,variables:{}}});
    expect(contexts.get("s","a","db","public")!.version).toBe(1);expect(contexts.get("s","a","db","public")!.namespaceVersion).toBeGreaterThan(namespaceVersion);
    expect(contexts.get("s","b","other","sales")!.version).toBe(2);
    contexts.accept(update(4,"a","db","public",["updated_users"]));
    expect(contexts.get("s","a","db","public")!.version).toBe(4);expect(contexts.get("s","b","other","sales")!.version).toBe(2);
    contexts.accept({event:"language.context_updated",payload:{session_id:"other",version:1,variables:{}}});
    expect(contexts.get("s","a","db","public")!.version).toBe(4);expect(contexts.get("s","a","db","public")!.namespaceVersion).toBeGreaterThan(namespaceVersion);
  });
});

describe("focused block completion context",()=>{
  it("offers every SQL result in Python blocks across connection scopes, even after closing grid tabs",()=>{
    let session=newSession();session.id="sql-python";session.savedConnectionId="main";session.currentExecutionId="query";
    const sql={...newBlock("sql","SELECT 1; SELECT 2;"),block_name:"vendas",status:"running" as const},first={...newBlock("python","vend"),connection_id:"other"},second=newBlock("python","vendas1.");
    session.blocks=[sql,first,second];
    const contexts=new SessionLanguageContexts(),index=new SessionCompletionIndex();
    contexts.accept({event:"language.context_updated",payload:{session_id:session.id,connection_id:"main",version:1,variables:{}}});
    const frames={vendas:{type:"DataFrame",module:"pandas.core.frame",columns:["pedido_id","valor total"]},vendas1:{type:"DataFrame",module:"pandas.core.frame",columns:["status"]}};
    // Kernel publishes the immutable namespace before announcing query completion.
    contexts.accept({event:"language.context_updated",payload:{session_id:session.id,connection_id:"main",version:2,variables:frames}});
    session=applyRuntimeEvent(session,{event:"execution.finished",payload:{session_id:session.id,execution_id:"query",status:"succeeded",duration_ms:1,variables:Object.keys(frames).map(name=>({name,type:"DataFrame",preview:""})),results:Object.entries(frames).map(([name,metadata])=>({result_id:name,variable_name:name,row_count:10_000_000,columns:metadata.columns.map(column=>({name:column,dtype:"string"}))}))}});
    for(const block of [first,second]){
      const context=index.context(session,block.id,contexts)!;
      expect(localCompletions("python",completionSite("python","vend",5),context,"vend").filter(item=>item.kind==="variable").map(item=>item.label)).toEqual(["vendas","vendas1"]);
      expect(localCompletions("python",completionSite("python","vendas1.",9),context,"vendas1.")).toContainEqual(expect.objectContaining({label:"status",kind:"field"}));
      expect(context.variables.find(variable=>variable.name==="vendas")?.columns).toEqual(["pedido_id","valor total"]);
    }
    session.results=[];
    expect(index.context(session,first.id,contexts)!.variables.map(variable=>variable.name)).toEqual(["vendas","vendas1"]);
    expect(index.context({...session,id:"another-session",variables:[],results:[]},first.id,contexts)!.variables).not.toContainEqual(expect.objectContaining({name:"vendas1"}));
  });
  it("does not resurrect executed SQL frames after deletion or overwrite from stale block results",()=>{
    const session=newSession();session.id="executed";
    const sql={...newBlock("sql","SELECT 1"),block_name:"vendas",status:"succeeded" as const,results:[{result_id:"old",variable_name:"vendas",row_count:1,columns:[{name:"old_column",dtype:"int"}]}]},python=newBlock("python","vendas.");session.blocks=[sql,python];session.results=sql.results;
    const contexts=new SessionLanguageContexts(),index=new SessionCompletionIndex();
    contexts.accept({event:"language.context_updated",payload:{session_id:session.id,version:1,variables:{vendas:{type:"DataFrame",module:"pandas.core.frame",columns:["new_column"]}}}});
    expect(index.context(session,python.id,contexts)!.variables).toContainEqual(expect.objectContaining({name:"vendas",columns:["new_column"]}));
    contexts.accept({event:"language.context_updated",payload:{session_id:session.id,version:2,variables:{vendas:{type:"int"}}}});
    expect(index.context(session,python.id,contexts)!.variables).toContainEqual({name:"vendas",type:"int"});
    contexts.accept({event:"language.context_updated",payload:{session_id:session.id,version:3,variables:{}}});
    expect(index.context(session,python.id,contexts)!.variables).toEqual([]);
  });
  it("plans valid Unicode SQL frame names without offering Python keywords as executable identifiers",()=>{
    const session=newSession(),python=newBlock("python",""),unicode={...newBlock("sql","SELECT 1"),block_name:"Δados"},keyword={...newBlock("sql","SELECT 2"),block_name:"class"};session.blocks=[python,unicode,keyword];
    const context=new SessionCompletionIndex().context(session,python.id,new SessionLanguageContexts())!;
    expect(context.variables).toContainEqual({name:"Δados",type:"DataFrame"});expect(context.variables).not.toContainEqual(expect.objectContaining({name:"class"}));
  });
  it("provides imports from later blocks, multiline imports, peer snippets and SQL DataFrames without execution",()=>{
    const session=newSession();session.id="s";
    const current=newBlock("python","calcul"),other=newBlock("python","from collections import (\n    Counter,\n    defaultdict,\n)\nimport datetime as dt\ndef calculate_value():\n    return 3\n"),sql=newBlock("sql","SELECT 1");
    other.block_name="helpers";sql.block_name="orders";session.blocks=[current,other,sql,newBlock("python","import forbidden")];session.blocks[3].cell_type="raw";
    const index=new SessionCompletionIndex(),context=index.context(session,current.id,new SessionLanguageContexts())!;
    expect(context.globalImports).toContain("import datetime as dt");expect(context.globalImports).toContain("    Counter".trim());expect(context.globalImports).not.toContain("forbidden");
    expect(context.preamble).toContain("def calculate_value");expect(context.preamble).not.toContain("calcul\n");
    expect(context.siblings?.map(b=>b.name)).toEqual(["helpers","orders"]);expect(context.variables).toContainEqual({name:"orders",type:"DataFrame"});
    session.blocks=[current,{...other,code:"import decimal as dec"}];
    expect(index.context(session,current.id,new SessionLanguageContexts())!.globalImports).toContain("import decimal as dec");
    expect(index.context(session,current.id,new SessionLanguageContexts())!.globalImports).not.toContain("datetime");
  });
  it("uses per-block connection metadata and keeps DataFrame columns on unloaded snapshots",()=>{
    const session=newSession();session.id="s";const block=session.blocks[0];block.connection_id="a";session.savedConnectionId="b";
    session.variables=[{name:"df",type:"DataFrame",preview:""}];session.results=[{result_id:"r",variable_name:"df",row_count:1,columns:[{name:"sales total",dtype:"int"}]}];
    const contexts=new SessionLanguageContexts(),index=new SessionCompletionIndex();
    expect(index.context(session,block.id,contexts)?.variables[0].columns).toEqual(["sales total"]);
    contexts.accept(update(1));contexts.accept(update(2,"b","other","sales",["orders"]));
    expect(index.context(session,block.id,contexts)?.tables).toEqual(["public.users"]);
    expect(index.context(session,block.id,contexts)?.variables[0].module).toBe("pandas.core.frame");
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",connection_id:"a",version:3,variables:{}}});
    expect(index.context(session,block.id,contexts)?.variables).toEqual([]);
  });
  it("ignores imports inside strings/comments and incomplete statements",()=>{
    const session=newSession(),block=newBlock("python","'''\nimport phantom\n'''\n# import commented\nimport datetime as dt # (\nfrom collections import (\n    Counter, # )\n)\nfrom incomplete import (\n");session.blocks=[block];
    const context=new SessionCompletionIndex().context(session,block.id,new SessionLanguageContexts())!;
    expect(context.globalImports).toContain("import datetime as dt");expect(context.globalImports).toContain("Counter");
    expect(context.globalImports).not.toMatch(/phantom|commented|incomplete/);
  });
  it("never truncates a peer inside a docstring or argument list that absorbs the current block",()=>{
    const session=newSession(),current=newBlock("python","dt."),peer=newBlock("python",'import datetime as dt\ndoc = """\n'+"documentation\n".repeat(400)+'"""\ndef calculate_value():\n    return 42');
    session.blocks=[current,peer];const context=new SessionCompletionIndex().context(session,current.id,new SessionLanguageContexts())!;
    expect(context.globalImports).toContain("datetime as dt");expect(context.preamble).toBe("import datetime as dt\n");
    peer.code="before=1\nvalue=(\n"+"1,\n".repeat(2000)+")\n";
    expect(new SessionCompletionIndex().context(session,current.id,new SessionLanguageContexts())!.preamble).toBe("before=1\n");
  });
  it("bounds the focused preamble and never assembles context for every notebook block",()=>{
    const session=newSession(),current=newBlock("python","df.");session.blocks=[current,...Array.from({length:120},()=>newBlock("python","x=1\n".repeat(20_000)))];
    const context=new SessionCompletionIndex().context(session,current.id,new SessionLanguageContexts())!;
    expect(context.preamble!.length).toBeLessThanOrEqual(200_000);expect(context.siblings).toHaveLength(120);
    expect(context.siblings![0].code).toBe(session.blocks[1].code);
  });
});

describe("shared session diagnostics context",()=>{
  it("compares 300 block sources once per replacement array and reuses context across layout/output updates",()=>{
    const session=newSession();session.blocks=Array.from({length:300},(_,index)=>newBlock("python",`value_${index} = ${index}\n`));
    const index=new SessionCompletionIndex(),revision=index.diagnosticsRevision(session),context=index.diagnosticsContext(session);
    session.blocks=session.blocks.map(block=>({...block,status:"succeeded",height:450,collapsed:true,is_active:false,duration_ms:4,error:"execution error",results:[]}));
    session.focusedBlockId=session.blocks[2].id;session.title="Renamed";session.resultRevision++;session.variables=[{name:"changed",type:"int",preview:"1"}];
    const compare=vi.spyOn(session.blocks,"every"),iterate=vi.spyOn(session.blocks,Symbol.iterator);
    try{
      for(let reader=0;reader<1000;reader++){expect(index.diagnosticsRevision(session)).toBe(revision);expect(index.diagnosticsContext(session)).toBe(context);}
      expect(compare).toHaveBeenCalledTimes(1);expect(iterate).not.toHaveBeenCalled();
    }finally{compare.mockRestore();iterate.mockRestore();}
  });
  it.each([
    {code:"changed_name = 2\n"}, {language:"sql" as const}, {cell_type:"markdown" as const}, {id:"replacement-block"},
  ])("invalidates the session revision on source changes: %j",patch=>{
    const session=newSession();session.blocks=[newBlock("python","original_name = 1\n")];
    const index=new SessionCompletionIndex(),revision=index.diagnosticsRevision(session),before=index.diagnosticsContext(session);
    session.blocks=[{...session.blocks[0],...patch}];
    expect(index.diagnosticsRevision(session)).toBeGreaterThan(revision);expect(index.diagnosticsContext(session)).not.toBe(before);
  });
  it("invalidates SQL names and order/add/remove but ignores Python display names",()=>{
    const session=newSession(),python=newBlock("python","peer_name = 1\n"),sql={...newBlock("sql","SELECT 1"),block_name:"first_result"};session.blocks=[python,sql];
    const index=new SessionCompletionIndex(),revision=index.diagnosticsRevision(session),context=index.diagnosticsContext(session);
    session.blocks=[{...python,block_name:"display label"},sql];expect(index.diagnosticsRevision(session)).toBe(revision);expect(index.diagnosticsContext(session)).toBe(context);
    session.blocks=[session.blocks[0],{...sql,block_name:"renamed_result"}];const renamed=index.diagnosticsRevision(session);expect(renamed).toBeGreaterThan(revision);expect(index.diagnosticsContext(session).preamble).toContain("renamed_result = None");
    session.blocks=[session.blocks[1],session.blocks[0]];const reordered=index.diagnosticsRevision(session);expect(reordered).toBeGreaterThan(renamed);
    session.blocks=[...session.blocks,newBlock("python","new_peer = 3\n")];const added=index.diagnosticsRevision(session);expect(added).toBeGreaterThan(reordered);
    session.blocks=session.blocks.slice(1);expect(index.diagnosticsRevision(session)).toBeGreaterThan(added);
  });
  it("preserves Python diagnostics while SQL/Markdown/raw text changes and invalidates peer declarations",()=>{
    const session=newSession(),python=newBlock("python","peer_name = 1\n"),sql={...newBlock("sql","SELECT 1"),block_name:"query_result"},markdown={...newBlock("python","# Description"),cell_type:"markdown" as const},raw={...newBlock("python","import ignored_raw"),cell_type:"raw" as const};
    session.blocks=[python,sql,markdown,raw];const index=new SessionCompletionIndex(),revision=index.diagnosticsRevision(session),context=index.diagnosticsContext(session);
    session.blocks=session.blocks.map(block=>block.id===sql.id?{...block,code:"SELECT changed_column FROM changed_table"}:block);
    expect(index.diagnosticsRevision(session)).toBe(revision);expect(index.diagnosticsContext(session)).toBe(context);
    session.blocks=session.blocks.map(block=>block.id===markdown.id||block.id===raw.id?{...block,code:"import text_only\nnot_a_python_declaration = 1\n"}:block);
    expect(index.diagnosticsRevision(session)).toBe(revision);expect(index.diagnosticsContext(session)).toBe(context);expect(context.globalImports).not.toContain("text_only");
    session.blocks=session.blocks.map(block=>block.id===python.id?{...block,code:"import datetime as dt\nupdated_peer = 2\n"}:block);
    const pythonRevision=index.diagnosticsRevision(session),pythonContext=index.diagnosticsContext(session);expect(pythonRevision).toBeGreaterThan(revision);expect(pythonContext).not.toBe(context);expect(pythonContext.preamble).toContain("updated_peer = 2");expect(pythonContext.preamble).not.toContain("peer_name = 1");
    session.blocks=session.blocks.map(block=>block.id===sql.id?{...block,block_name:"renamed_query_result"}:block);
    expect(index.diagnosticsRevision(session)).toBeGreaterThan(pythonRevision);const renamed=index.diagnosticsContext(session);expect(renamed).not.toBe(pythonContext);expect(renamed.preamble).toContain("renamed_query_result = None");expect(renamed.preamble).not.toMatch(/(?:^|\n)query_result = None/);
  });
  it("isolates session revisions and releases closed-session contexts without reviving old revisions",()=>{
    const first=newSession(),second=newSession();first.blocks=[newBlock("python","first_name = 1\n")];second.blocks=[newBlock("python","second_name = 2\n")];
    const index=new SessionCompletionIndex(),firstRevision=index.diagnosticsRevision(first),firstContext=index.diagnosticsContext(first),secondRevision=index.diagnosticsRevision(second),secondContext=index.diagnosticsContext(second);
    second.blocks=[{...second.blocks[0],code:"second_name = 3\n"}];expect(index.diagnosticsRevision(second)).toBeGreaterThan(secondRevision);
    expect(index.diagnosticsRevision(first)).toBe(firstRevision);expect(index.diagnosticsContext(first)).toBe(firstContext);
    const editedSecond=index.diagnosticsContext(second);expect(editedSecond).not.toBe(secondContext);
    index.retain(new Set([second.id]));expect(index.diagnosticsContext(second)).toBe(editedSecond);
    expect(index.diagnosticsRevision(first)).toBeGreaterThan(firstRevision);expect(index.diagnosticsContext(first)).not.toBe(firstContext);
    index.retain(new Set());expect(index.diagnosticsContext(second)).not.toBe(editedSecond);
  });
  it("includes code Python peers, multiline imports and SQL result declarations without execution",()=>{
    const session=newSession(),python=newBlock("python","from collections import (\n    Counter,\n    defaultdict,\n)\nimport datetime as dt\ndef helper(value):\n    return value\n"),sql=newBlock("sql","SELECT 1"),later=newBlock("python","later_name = 42\n"),inactive=newBlock("python","inactive_name = 1\n");
    sql.block_name="orders";python.cell_type="code";later.collapsed=true;inactive.is_active=false;
    session.blocks=[python,sql,later,inactive];
    const context=new SessionCompletionIndex().diagnosticsContext(session);
    expect(context.globalImports).toContain("import pandas as pd");expect(context.globalImports).toContain("import numpy as np");expect(context.globalImports).toContain("import polars as pl");
    expect(context.globalImports).toContain("Counter");expect(context.globalImports).toContain("import datetime as dt");
    expect(context.preamble).toContain("def helper(value):");expect(context.preamble).toContain("orders = None");expect(context.preamble).toContain("later_name = 42");expect(context.preamble).toContain("inactive_name = 1");expect(context.preamble).not.toContain("SELECT 1");
  });
  it("ignores markdown/raw chapters, strings/comments and invalid or reserved SQL names",()=>{
    const session=newSession(),markdown=newBlock("python","import from_markdown\nmarkdown_name = 1"),raw=newBlock("python","import from_raw\nraw_name = 2"),comment=newBlock("python","'''\nimport phantom\n'''\n# import commented\nimport decimal as dec\nfrom incomplete import (\n");
    markdown.cell_type="markdown";raw.cell_type="raw";
    const names=["valid_name","class","False","for","async","None","match","case","bad.name","with space","123name",""];
    const sql=names.map(name=>({...newBlock("sql","SELECT 1"),block_name:name}));sql.push({...newBlock("sql","SELECT 2"),block_name:"raw_sql",cell_type:"raw"});
    session.blocks=[markdown,raw,comment,...sql];const context=new SessionCompletionIndex().diagnosticsContext(session);
    expect(context.globalImports).toContain("import decimal as dec");expect(context.globalImports).not.toMatch(/from_markdown|from_raw|phantom|commented|incomplete/);
    expect(context.preamble).not.toMatch(/markdown_name|raw_name|raw_sql|bad\.name|with space|123name/);
    expect(context.preamble).toContain("valid_name = None");expect(context.preamble).toContain("match = None");expect(context.preamble).toContain("case = None");
    for(const name of ["class","False","for","async","None"])expect(context.preamble).not.toContain(`${name} = None`);
  });
  it("memoizes the same object by blocks identity and never touches session metadata or rescans cached blocks",()=>{
    const session=newSession();session.blocks=[newBlock("python","value = 1\n"),{...newBlock("sql","SELECT 1"),block_name:"sql_result"}];
    const index=new SessionCompletionIndex(),context=index.diagnosticsContext(session),iterator=vi.spyOn(session.blocks,Symbol.iterator).mockImplementation(()=>{throw new Error("A cache hit must not scan blocks");});
    const isolated={...session};for(const property of ["variables","results","savedConnectionId","database","schema","extras"])Object.defineProperty(isolated,property,{get(){throw new Error("Diagnostics must not read execution or connection state");}});
    try{for(let block=0;block<1000;block++)expect(index.diagnosticsContext(isolated)).toBe(context);expect(iterator).not.toHaveBeenCalled();}finally{iterator.mockRestore();}
    expect(new SessionCompletionIndex().diagnosticsContext(isolated)).toEqual(context);
    expect(index.diagnosticsContext({...session,title:"renamed",focusedBlockId:"another"})).toBe(context);
  });
  it("invalidates edits, SQL renames, removals, reordering and chapter type changes without leaking session contents",()=>{
    const session=newSession(),python=newBlock("python","import datetime as dt\nfirst = 1\n"),sql={...newBlock("sql","SELECT 1"),block_name:"old_sql"};session.blocks=[python,sql];
    const index=new SessionCompletionIndex(),initial=index.diagnosticsContext(session);
    session.blocks=[{...python,code:"import decimal as dec\nnew_value = 2\n"},{...sql,block_name:"new_sql"}];
    const edited=index.diagnosticsContext(session);expect(edited).not.toBe(initial);expect(edited.globalImports).toContain("decimal as dec");expect(edited.globalImports).not.toContain("datetime as dt");expect(edited.preamble).toContain("new_sql = None");expect(edited.preamble).not.toMatch(/old_sql|first = 1/);
    session.blocks=[session.blocks[1],session.blocks[0]];const reordered=index.diagnosticsContext(session);expect(reordered.preamble.indexOf("new_sql")).toBeLessThan(reordered.preamble.indexOf("new_value"));
    session.blocks=[{...session.blocks[1],cell_type:"markdown"}];const removed=index.diagnosticsContext(session);expect(removed.preamble).toBe("");expect(removed.globalImports).not.toContain("decimal as dec");
    const other=newSession();other.blocks=[newBlock("python","other_session_name = 3\n")];expect(index.diagnosticsContext(other).preamble).toBe("other_session_name = 3\n");expect(index.diagnosticsContext(session)).toBe(removed);expect(initial.preamble).toContain("old_sql = None");
  });
  it("truncates Python peers at safe statement boundaries and bounds shared source/import strings",()=>{
    const session=newSession(),docstring=newBlock("python",'before_doc = 1\ndoc = """\n'+"documentation\n".repeat(400)+'"""\nafter_doc = 2\n'),argument=newBlock("python","before_args = 1\nvalue=(\n"+"1,\n".repeat(2000)+")\n"),next=newBlock("python","next_peer = 42\n");
    session.blocks=[docstring,argument,next];const safe=new SessionCompletionIndex().diagnosticsContext(session);
    expect(safe.preamble).toBe("before_doc = 1\n\nbefore_args = 1\n\nnext_peer = 42\n");expect(safe.preamble).not.toContain('"""');
    const longImport=newBlock("python","import "+"oversized_".repeat(4000)+"\nimport small_after_oversized\n");
    session.blocks=[longImport,...Array.from({length:140},(_,index)=>newBlock("python",`import package_${index}\n`+"value=1\n".repeat(400))),next];
    const limited=new SessionCompletionIndex().diagnosticsContext(session);
    expect(limited.preamble.length).toBeLessThanOrEqual(200_000);expect(limited.globalImports.length).toBeLessThanOrEqual(32_000);expect(limited.globalImports).not.toContain("oversized_");expect(limited.globalImports).toContain("import small_after_oversized");
  });
  it("deduplicates global imports and releases full code chapters from the shared payload",()=>{
    const session=newSession();session.blocks=Array.from({length:8},()=>newBlock("python","import datetime as dt\nvalue=1\n"+"# padding\n".repeat(3000)));
    const index=new SessionCompletionIndex(),context=index.diagnosticsContext(session);
    expect(context.globalImports.match(/import datetime as dt/g)).toHaveLength(1);expect(context.preamble.length).toBeLessThan(8*2501);expect(Object.keys(context).sort()).toEqual(["globalImports","preamble"]);
  });
  it("invalidates the cached parse when a Python code block changes language",()=>{
    const session=newSession(),block={...newBlock("python","import datetime as dt\npython_value = 4\n"),block_name:"result_name"};session.blocks=[block];
    const index=new SessionCompletionIndex(),before=index.diagnosticsContext(session);expect(before.globalImports).toContain("datetime as dt");
    session.blocks=[{...block,language:"sql"}];const after=index.diagnosticsContext(session);expect(after).not.toBe(before);expect(after.globalImports).not.toContain("datetime as dt");expect(after.preamble).toBe("result_name = None");
    session.blocks=[{...block,cell_type:"code"}];expect(index.diagnosticsContext(session)).toEqual(before);
  });
  it("caps accumulated complete imports rather than slicing through an import statement",()=>{
    const session=newSession();session.blocks=Array.from({length:1000},(_,index)=>newBlock("python",`import package_${index}_with_a_long_complete_module_name as alias_${index}\n`));
    const context=new SessionCompletionIndex().diagnosticsContext(session),imports=context.globalImports.split("\n");
    expect(context.globalImports.length).toBeLessThanOrEqual(32_000);expect(context.globalImports.length).toBeGreaterThan(31_900);expect(imports.length).toBeLessThan(1003);
    for(const line of imports.slice(3))expect(line).toMatch(/^import package_\d+_with_a_long_complete_module_name as alias_\d+$/);
  });
});


describe("resolved default scope delivery",()=>{
  const resolved=(version:number,schema="public",requestedSchema:string|null=null):RuntimeEvent=>({
    event:"language.context_updated",payload:{session_id:"s",connection_id:"transient",database:"analytics",schema,version,variables:{},metadata_state:"ready",
      requested_scope:{connection_id:null,database:"analytics",schema:requestedSchema},
      schema_snapshot:{db_type:"postgresql",database:"analytics",current_schema:schema,tables:[{key:`${schema}.orders`,name:"orders",schema}],columns:{[`${schema}.orders`]:[{name:"amount",data_type:"numeric"}]}}}
  });
  it("maps an implicit connection and default schema to the real catalogue without borrowing another schema",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(resolved(1));contexts.accept(resolved(2,"sales","sales"));
    expect(contexts.get("s",undefined,"analytics")?.tables).toEqual(["public.orders"]);
    expect(contexts.get("s",undefined,"analytics","sales")?.tables).toEqual(["sales.orders"]);
    const unaliased=new SessionLanguageContexts();unaliased.accept(update(1,"a","db","public"));unaliased.accept(update(2,"a","db","sales"));
    expect(unaliased.get("s","a","db")?.schemaSnapshot).toBeUndefined();
  });
  it("invalidates request aliases and resolved identities even after namespace-only events",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(resolved(1));contexts.accept(resolved(2,"sales","sales"));
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",connection_id:"transient",database:"analytics",schema:"public",version:3,variables:{live:{type:"int"}}}});
    expect(contexts.invalidate("s",undefined,"analytics")).toBe(true);
    expect(contexts.get("s",undefined,"analytics")?.schemaSnapshot).toBeUndefined();
    expect(contexts.get("s","transient","analytics","public")?.schemaSnapshot).toBeUndefined();
    expect(contexts.get("s",undefined,"analytics","sales")?.tables).toEqual(["sales.orders"]);
    expect(contexts.get("s",undefined,"analytics")?.variables).toEqual({live:{type:"int"}});
  });
  it("clears all aliases on SQL metadata invalidation and exposes catalogue errors",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(resolved(1));contexts.accept(resolved(2,"sales","sales"));
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",connection_id:"transient",database:"analytics",schema:"public",version:3,variables:{},metadata_invalidated:true,metadata_state:"error",schema_error:"Permission denied",requested_scope:{connection_id:null,database:"analytics",schema:null},schema_snapshot:{}}});
    expect(contexts.get("s",undefined,"analytics")?.tables).toEqual([]);
    expect(contexts.get("s",undefined,"analytics")?.error).toBe("Permission denied");
    expect(contexts.get("s",undefined,"analytics","sales")?.schemaSnapshot).toBeUndefined();
  });
  it("uses a block connection's configured database/dialect and resets schema when its database changes",()=>{
    const session=newSession();session.savedConnectionId="main";session.database="main_db";session.schema="private";
    const block={...newBlock("sql","SELECT x."),connection_id:"other"},defaults={db_type:"postgresql" as const,database:"other_db",schema:"public"};session.blocks=[block];
    expect(completionConnectionScope(session,block,defaults)).toEqual({connectionId:"other",database:"other_db",schema:"public"});
    expect(completionConnectionScope(session,{...block,database_name:"new_db"},defaults)).toEqual({connectionId:"other",database:"new_db",schema:undefined});
    expect(completionConnectionScope(session,{...block,connection_id:undefined,database_name:"new_db"},defaults).schema).toBeUndefined();
    expect(new SessionCompletionIndex().context(session,block.id,new SessionLanguageContexts(),defaults)?.dbType).toBe("postgresql");
  });
});

describe("metadata follows the physical connector of each SQL block",()=>{
  const scoped=(version:number,block_id:string,database="db",schema="public",name="orders"):RuntimeEvent=>({
    event:"language.context_updated",payload:{session_id:"s",block_id,connection_id:"main",database,schema,version,variables:{},metadata_state:"ready",
      requested_scope:{connection_id:"main",database,schema},schema_snapshot:{database,current_schema:schema,tables:[{key:name,name,temporary:true}],columns:{[name]:[{name:"value"}]}}},
  });
  const finished:RuntimeEvent={event:"execution.finished",payload:{session_id:"s",execution_id:"use",block_id:"first",status:"succeeded",duration_ms:1,results:[],variables:[],context_change:{connection_id:"main",previous:{database:"db",schema:"public"},current:{database:"next",schema:"private"},requested_scope:{connection_id:"main",database:"db",schema:"public"}}}};
  it("separates inherited affinity from pinned metadata in the same block and logical scope",()=>{
    const contexts=new SessionLanguageContexts(),inherited=scoped(1,"first","db","public","inherited_temp");if(inherited.event!=="language.context_updated")throw new Error("fixture");inherited.payload.scope_inherited=true;
    contexts.accept(inherited);contexts.accept(scoped(2,"first","db","public","late_pinned_temp"));
    expect(contexts.get("s","main","db","public","first",true)?.tables).toEqual(["inherited_temp"]);
    expect(contexts.get("s","main","db","public","first",false)?.tables).toEqual(["late_pinned_temp"]);
    expect(contexts.invalidate("s","main","db","public","first",true)).toBe(true);
    expect(contexts.get("s","main","db","public","first",true)?.schemaSnapshot).toBeUndefined();expect(contexts.get("s","main","db","public","first",false)?.tables).toEqual(["late_pinned_temp"]);
  });
  it("invalidates every inherited peer after a default connector changes while pinned peers keep their tables",()=>{
    const contexts=new SessionLanguageContexts();
    for(const [index,block] of ["first","inherited_peer"].entries()){const event=scoped(index+1,block,"next","private",block);if(event.event!=="language.context_updated")throw new Error("fixture");event.payload.scope_inherited=true;contexts.accept(event);}
    contexts.accept(scoped(3,"pinned_peer","next","private","pinned_temp"));contexts.accept({...finished,payload:{...finished.payload,scope_inherited:true}} as RuntimeEvent);
    expect(contexts.get("s","main","next","private","inherited_peer",true)?.schemaSnapshot).toBeUndefined();
    expect(contexts.get("s","main","next","private","pinned_peer",false)?.tables).toEqual(["pinned_temp"]);
  });
  it("invalidates inherited peers for a secondary search_path change without a primary scope change",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(update(1,"main","db","public",["legacy_default"]));
    const peer=scoped(2,"peer");if(peer.event!=="language.context_updated")throw new Error("fixture");peer.payload.scope_inherited=true;contexts.accept(peer);contexts.accept(scoped(3,"pinned"));
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",block_id:"first",scope_inherited:true,connection_id:"main",database:"db",schema:"public",version:4,variables:{},metadata_invalidated:true,metadata_invalidation_scope:"block"}});
    expect(contexts.get("s","main","db","public","peer",true)?.schemaSnapshot).toBeUndefined();expect(contexts.get("s","main","db","public","never_prepared",true)?.schemaSnapshot).toBeUndefined();
    expect(contexts.get("s","main","db","public","pinned",false)?.tables).toEqual(["orders"]);
  });
  it("isolates temporary tables for two blocks with identical connection/database/schema",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(scoped(1,"first","db","public","temp_first"));contexts.accept(scoped(2,"second","db","public","temp_second"));
    expect(contexts.get("s","main","db","public","first")?.tables).toEqual(["temp_first"]);
    expect(contexts.get("s","main","db","public","second")?.tables).toEqual(["temp_second"]);
    expect(contexts.get("s","main","db","public","unprepared")?.schemaSnapshot).toBeUndefined();
  });
  it("does not borrow global metadata or late old-scope snapshots after USE",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(update(1,"main","next","private",["wrong_connector"]));contexts.accept(scoped(2,"first"));contexts.accept(scoped(3,"second"));
    contexts.accept(finished);
    expect(contexts.get("s","main","next","private","first")?.schemaSnapshot).toBeUndefined();
    expect(contexts.get("s","main","db","public","second")?.tables).toEqual(["orders"]);
    contexts.accept(scoped(4,"first","db","public","late_previous"));
    expect(contexts.get("s","main","next","private","first")?.schemaSnapshot).toBeUndefined();
    contexts.accept(scoped(5,"first","next","private","fresh_current"));
    expect(contexts.get("s","main","next","private","first")?.tables).toEqual(["fresh_current"]);
  });
  it("never aliases a late response's resolved scope to a different explicit requested scope",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(scoped(1,"first","next","private","current"));
    const late=scoped(2,"first","db","public","stale");if(late.event!=="language.context_updated")throw new Error("fixture");
    late.payload.requested_scope={connection_id:"main",database:"next",schema:"private"};contexts.accept(late);
    expect(contexts.get("s","main","next","private","first")?.tables).toEqual(["current"]);
    expect(contexts.get("s","main","db","public","first")?.tables).toEqual(["stale"]);
  });
  it("invalidates only the changed block even when default aliases share the same scope",()=>{
    const contexts=new SessionLanguageContexts();contexts.accept(scoped(1,"first"));contexts.accept(scoped(2,"second"));
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",block_id:"first",connection_id:"main",database:"next",schema:"private",version:3,variables:{},metadata_invalidated:true,metadata_invalidation_scope:"block",requested_scope:{connection_id:"main",database:"db",schema:"public"}}});
    expect(contexts.get("s","main","db","public","first")?.schemaSnapshot).toBeUndefined();
    expect(contexts.get("s","main","db","public","second")?.tables).toEqual(["orders"]);
  });
  it.each(["connection",undefined] as const)("DDL invalidation clears peer blocks on the connection: %s",metadata_invalidation_scope=>{
    const contexts=new SessionLanguageContexts();contexts.accept(scoped(1,"first"));contexts.accept(scoped(2,"second"));contexts.accept(update(3,"other"));
    contexts.accept({event:"language.context_updated",payload:{session_id:"s",block_id:"first",connection_id:"main",database:"db",schema:"public",version:4,variables:{},metadata_invalidated:true,metadata_invalidation_scope}});
    expect(contexts.get("s","main","db","public","first")?.schemaSnapshot).toBeUndefined();expect(contexts.get("s","main","db","public","second")?.schemaSnapshot).toBeUndefined();
    expect(contexts.get("s","other","db","public")?.tables).toEqual(["public.users"]);
  });
  it("refreshes completion and diagnostics with the live block scope after a command",()=>{
    const session=newSession();session.id="s";session.savedConnectionId="main";session.database="db";session.schema="public";session.currentExecutionId="use";session.currentBlockId=session.blocks[0].id;
    const contexts=new SessionLanguageContexts(),index=new SessionCompletionIndex(),next=applyRuntimeEvent(session,{...finished,payload:{...finished.payload,block_id:session.blocks[0].id}} as RuntimeEvent);
    const metadata=scoped(1,next.blocks[0].id,"next","private","new_table");if(metadata.event!=="language.context_updated")throw new Error("fixture");metadata.payload.scope_inherited=true;contexts.accept(metadata);
    expect(index.context(next,next.blocks[0].id,contexts)).toMatchObject({sessionId:"s",blockId:next.blocks[0].id,database:"next",schema:"private",tables:["new_table"],schemaVersion:1});
  });
});


it("discards the edited connection's catalogue and every default alias while keeping other connections",()=>{
  const contexts=new SessionLanguageContexts();
  contexts.accept({...update(1,"main"),payload:{...update(1,"main").payload,requested_scope:{connection_id:"main",database:null,schema:null}}} as RuntimeEvent);
  contexts.accept(update(2,"other"));
  expect(contexts.invalidateConnection("s","main")).toBe(true);
  expect(contexts.get("s","main")?.schemaSnapshot).toBeUndefined();
  expect(contexts.get("s","main","db","public")?.schemaSnapshot).toBeUndefined();
  expect(contexts.get("s","other","db","public")?.tables).toEqual(["public.users"]);
});


it("preserves SQL metadata for table names that match JavaScript prototype properties",()=>{
  const contexts=new SessionLanguageContexts();contexts.accept({event:"language.context_updated",payload:{session_id:"s",version:1,variables:{},schema_snapshot:{db_type:"sqlite",tables:[{key:"__proto__",name:"__proto__"}],columns:{["__proto__"]:[{name:"real_field",type:"INTEGER"}]}}}});
  const snapshot=contexts.get("s")!.schemaSnapshot!;
  expect(Object.hasOwn(snapshot.tables!,"__proto__")).toBe(true);expect(Object.getPrototypeOf(snapshot.tables)).toBeNull();
  const code='SELECT p. FROM "__proto__" p',offset=code.indexOf('p.')+2;
  expect(localCompletions("sql",completionSite("sql",code.slice(0,offset),offset+1),{sessionId:"s",variables:[],schemaSnapshot:snapshot,tables:["__proto__"]},code.slice(0,offset),[],code,offset)).toContainEqual(expect.objectContaining({label:"real_field",kind:"column"}));
});
