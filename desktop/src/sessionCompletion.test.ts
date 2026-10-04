import {describe,expect,it,vi} from "vitest";
import {isRuntimeEvent,type RuntimeEvent} from "./runtime";
import {SessionCompletionIndex,SessionLanguageContexts} from "./sessionCompletion";
import {newBlock,newSession} from "./workspace";

const update=(version:number,connection="a",database="db",schema="public",tables=["users"]):RuntimeEvent=>({event:"language.context_updated",payload:{session_id:"s",connection_id:connection,database,schema,version,
  variables:{df:{type:"DataFrame",module:"pandas.core.frame",columns:["sales total"]}},
  schema_snapshot:{db_type:"postgresql",tables:tables.map(name=>({key:`${schema}.${name}`,name,schema})),columns:{[`${schema}.${tables[0]}`]:[{name:"Id",data_type:"integer"}]}}}});

describe("language metadata delivery",()=>{
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
