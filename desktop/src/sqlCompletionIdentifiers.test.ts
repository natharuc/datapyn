import { describe, expect, it } from "vitest";
import { completionInsertion, completionSite, contextualCompletions, localCompletions } from "./editorCompletions";
import { mergeCompletions } from "./editorLanguage";
import type { CompletionContext } from "./editorLanguage";

const sqlserver:CompletionContext={variables:[],tables:[],database:"ESIM",schema:"dbo",dbType:"sqlserver",
  schemaSnapshot:{db_type:"sqlserver",database:"ESIM",current_schema:"dbo",default_schema:"dbo"}};
const site=(before="SELECT * FROM Item")=>completionSite("sql",before,before.length+1,"sqlserver");
const complete=(context:CompletionContext,before="SELECT * FROM Item")=>localCompletions("sql",site(before),context,before);

describe("SQL identifier completion and focused remote fallbacks",()=>{
  it.each(["loaded","fallback","unloaded"])("SQL Server ESIM/dbo displays and inserts Item from %s metadata",state=>{
    const context:CompletionContext={...sqlserver,tables:["ESIM.dbo.Item"],schemaSnapshot:{...sqlserver.schemaSnapshot,
      tables:state==="fallback"?undefined:{"ESIM.dbo.Item":state==="loaded"?{name:"Item",schema:"dbo",catalog:"ESIM",columns:[]}:{}}}};
    const local=complete(context);
    expect(local).toEqual([expect.objectContaining({label:"Item",insert_text:"Item",detail:"table",documentation:"ESIM.dbo.Item"})]);
    const remote=contextualCompletions([{label:"ESIM.dbo.Item",kind:"table",insert_text:"[ESIM].[dbo].[Item]"}],site(),context,"sql",local);
    expect(mergeCompletions(remote,local,"sql")).toEqual([expect.objectContaining({label:"Item",insert_text:"Item"})]);
  });
  it("normalizes a qualified remote table before a catalog snapshot arrives",()=>{
    const context:CompletionContext={...sqlserver,schemaSnapshot:undefined};
    expect(contextualCompletions([{label:"ESIM.dbo.Item",kind:"table",insert_text:"[ESIM].[dbo].[Item]"}],site(),context,"sql"))
      .toEqual([expect.objectContaining({label:"Item",insert_text:"Item",detail:"table",documentation:"ESIM.dbo.Item"})]);
  });
  it("fallback names disambiguate catalogs and keep foreign objects qualified",()=>{
    const context:CompletionContext={...sqlserver,tables:["ARCHIVE.dbo.Item","ESIM.dbo.Item","ESIM.audit.Item"]};
    expect(complete(context).map(item=>[item.label,item.insert_text])).toEqual([["ARCHIVE.dbo.Item","ARCHIVE.dbo.Item"],["Item","Item"],["audit.Item","audit.Item"]]);
    const remote=contextualCompletions([{label:"ARCHIVE.dbo.Item",kind:"table",insert_text:"[ARCHIVE].[dbo].[Item]"}],site(),sqlserver,"sql");
    expect(remote[0]).toMatchObject({label:"ARCHIVE.dbo.Item",insert_text:"ARCHIVE.dbo.Item"});
  });
  it("preserves a linked-server prefix even when its database/schema match the focused names",()=>{
    const item={label:"REMOTE.ESIM.dbo.Item",kind:"table",insert_text:"[REMOTE].[ESIM].[dbo].[Item]"};
    expect(contextualCompletions([item],site(),sqlserver,"sql")[0]).toMatchObject({label:"REMOTE.ESIM.dbo.Item",insert_text:"REMOTE.ESIM.dbo.Item"});
    expect(complete({...sqlserver,tables:[item.label]})[0]).toMatchObject({label:item.label,insert_text:"REMOTE.ESIM.dbo.Item"});
  });
  it("does not omit a selected SQL Server schema different from the login's physical default",()=>{
    const context:CompletionContext={...sqlserver,schema:"reports",tables:["ESIM.reports.Item"],schemaSnapshot:{...sqlserver.schemaSnapshot,current_schema:"reports",
      tables:{"ESIM.reports.Item":{name:"Item",schema:"reports",catalog:"ESIM",columns:[]}}}};
    expect(complete(context)[0]).toMatchObject({label:"Item",insert_text:"reports.Item"});
    expect(contextualCompletions([{label:"Item",kind:"table",insert_text:"[Item]"}],site(),context,"sql")[0]).toMatchObject({label:"Item",insert_text:"reports.Item"});
    const remoteOnly={...context,tables:[],schemaSnapshot:{...context.schemaSnapshot,tables:undefined}};
    for(const item of [{label:"Item",kind:"table",insert_text:"[Item]"},{label:"ESIM.reports.Item",kind:"table",insert_text:"[ESIM].[reports].[Item]"}])
      expect(contextualCompletions([item],site(),remoteOnly,"sql")[0]).toMatchObject({label:"Item",insert_text:"reports.Item"});
    const before="SELECT * FROM reports.Item";
    expect(complete(context,before)[0]).toMatchObject({label:"Item",insert_text:"Item"});
  });
  it("accepts a custom physical default without assuming every SQL Server login uses dbo",()=>{
    const context:CompletionContext={...sqlserver,schema:"reports",tables:["ESIM.reports.Item"],schemaSnapshot:{...sqlserver.schemaSnapshot,current_schema:"reports",default_schema:"reports"}};
    expect(complete(context)[0]).toMatchObject({label:"Item",insert_text:"Item"});
    const changed={...context,schemaSnapshot:{...context.schemaSnapshot,default_schema:"dbo"}};
    expect(complete(changed)[0]).toMatchObject({label:"Item",insert_text:"reports.Item"});
  });
  it("resolves an explicit schema against the current catalog instead of the focused schema",()=>{
    const context:CompletionContext={...sqlserver,schema:"reports",tables:[],schemaSnapshot:{...sqlserver.schemaSnapshot,current_schema:"reports",tables:{
      "ESIM.dbo.Item":{name:"Item",schema:"dbo",catalog:"ESIM",columns:[{name:"dbo_id"}]},
      "ESIM.reports.Item":{name:"Item",schema:"reports",catalog:"ESIM",columns:[{name:"reports_id"}]},
    }}};
    expect(complete(context,"SELECT * FROM dbo.Item")[0]).toMatchObject({label:"Item",insert_text:"Item"});
    expect(contextualCompletions([{label:"Item",kind:"table",insert_text:"[Item]"}],site("SELECT * FROM dbo.Item"),context,"sql")[0])
      .toMatchObject({label:"Item",insert_text:"Item",detail:"table",documentation:"ESIM.dbo.Item"});
    const before="SELECT i.",source="SELECT i. FROM dbo.Item i";
    expect(localCompletions("sql",site(before),context,before,[],source).map(item=>item.label)).toEqual(["dbo_id"]);
  });
  it("does not remove qualification from a permanent object shadowed by a known temporary table",()=>{
    const context:CompletionContext={variables:[],tables:[],dbType:"sqlite",schema:"main",schemaSnapshot:{tables:{
      "temp.Item":{name:"Item",schema:"temp",temporary:true},"main.Item":{name:"Item",schema:"main"},
    }}};
    expect(contextualCompletions([{label:"main.Item",kind:"table",insert_text:'"main"."Item"'}],site(),context,"sql")[0]).toMatchObject({label:"main.Item",insert_text:"main.Item"});
  });
  it("preserves quoted literal dots in a remote physical identifier",()=>{
    expect(contextualCompletions([{label:"Item.Part",kind:"table",insert_text:"[Item.Part]"}],site(),sqlserver,"sql")[0])
      .toMatchObject({label:"Item.Part",insert_text:"[Item.Part]"});
  });
  it.each([
    ["sqlserver","PIVOT","[PIVOT]","[customer name]"],
    ["mssql","SELECT","[SELECT]","[customer name]"],
    ["mysql","WINDOW","`WINDOW`","`customer name`"],
    ["mariadb","WINDOW","`WINDOW`","`customer name`"],
    ["databricks","CURRENT_SCHEMA","`CURRENT_SCHEMA`","`customer name`"],
    ["sqlite","FILTER",'"FILTER"','"customer name"'],
    ["postgresql","UserData",'"UserData"','"customer name"'],
  ])("%s uses plain ordinary names and valid reserved/special identifiers locally and remotely",(dbType,reserved,quoted,special)=>{
    const context:CompletionContext={variables:[],tables:["Item",reserved,"customer name"],dbType};
    const local=localCompletions("sql",completionSite("sql","FROM ",6,dbType),context,"FROM ");
    expect(local.map(item=>item.insert_text)).toEqual([dbType==="postgresql"?'"Item"':"Item",quoted,special]);
    const remote=contextualCompletions([{label:"Item",kind:"column",insert_text:dbType==="sqlserver"||dbType==="mssql"?"[Item]":dbType==="sqlite"||dbType==="postgresql"?'"Item"':"`Item`"}],site(),context,"sql");
    expect(remote[0].insert_text).toBe(dbType==="postgresql"?'"Item"':"Item");
  });
  it.each([["sqlserver","[","]"],["mysql","`","`"],["mariadb","`","`"],["databricks","`","`"],["sqlite",'"','"']])(
    "%s preserves the quoting explicitly typed by the user",(dbType,open,close)=>{
      const text=`FROM ${open}It${close}`,query=completionSite("sql",text,9,dbType),context:CompletionContext={variables:[],tables:["Item"],dbType};
      const item=localCompletions("sql",query,context,`FROM ${open}It`)[0];
      expect(item.insert_text).toBe("Item");
      expect(completionInsertion(item,query,"sql")).toBe(`${open}Item${close}`);
      expect(text.slice(0,query.startColumn-1)+completionInsertion(item,query,"sql")+text.slice(query.endColumn-1)).toBe(`FROM ${open}Item${close}`);
    });
  it("leaves runtime function expressions and snippets unchanged",()=>{
    const items=[{label:"get_date",kind:"function",insert_text:"GETDATE()"},{label:"select template",kind:"snippet",insert_text:"SELECT ${1:fields} FROM ${2:table}",is_snippet:true}];
    expect(contextualCompletions(items,site(),sqlserver,"sql")).toEqual(items);
  });
});
