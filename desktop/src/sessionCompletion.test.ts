import {describe,expect,it} from "vitest";
import {isRuntimeEvent,type RuntimeEvent} from "./runtime";
import {SessionCompletionIndex,SessionLanguageContexts} from "./sessionCompletion";
import {newBlock,newSession} from "./workspace";

const update=(version:number,connection="a",database="db",schema="public",tables=["users"]):RuntimeEvent=>({event:"language.context_updated",payload:{session_id:"s",connection_id:connection,database,schema,version,
  variables:{df:{type:"DataFrame",module:"pandas.core.frame",columns:["sales total"]}},
  schema_snapshot:{db_type:"postgresql",tables:tables.map(name=>({key:`${schema}.${name}`,name,schema})),columns:{[`${schema}.${tables[0]}`]:[{name:"Id",data_type:"integer"}]}}}});

describe("language metadata delivery",()=>{
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
