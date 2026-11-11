import { describe, expect, it, vi } from "vitest";
import { databaseCapabilities } from "./databaseCapabilities";
import { parseConnectionString, connectionStringFormats, formatConnectionString } from "./connectionStrings";
import { connectionMetadata, decodeDocument, encodeDocument, newSession, type ConnectionConfig } from "./workspace";
import { completionConnectionScope, SessionLanguageContexts } from "./sessionCompletion";
import { completionSite, completionInsertion, localCompletions, contextualCompletions } from "./editorCompletions";
import {documentFieldReference} from "./explorer";
import { ScopeOptionsClient } from "./blockScopeModel";
import { ScopePreparation } from "./ScopePreparation";
import { recoveryMatches } from "./connectionRecovery";
import type { CompletionContext } from "./editorLanguage";
import type { RuntimeEvent, RuntimeTransport } from "./runtime";

const profile=(db_type:ConnectionConfig["db_type"],extra:Partial<ConnectionConfig>={}):ConnectionConfig=>({db_type,host:"",port:443,database:"analysis",username:"reader",...extra});

describe("document database capabilities and public connection configuration",()=>{
  it.each(["elasticsearch","cosmosdb","mongodb"] as const)("does not expose SQLAlchemy, writes, temporary tables, SSH or manual transactions for %s",type=>{
    expect(databaseCapabilities(type)).toMatchObject({sqlalchemy:false,table_export:false,temporary_tables:false,manual_transactions:false,ssh:false,read_only:true});
  });
  it("keeps a dedicated container level only for Cosmos NoSQL",()=>{
    expect(databaseCapabilities(profile("cosmosdb")).context_levels).toEqual(["database","container"]);
    expect(databaseCapabilities(profile("cosmosdb",{cosmos_api:"mongodb"}))).toMatchObject({sql_dialect:"mongodb",context_levels:["database"]});
    expect(databaseCapabilities("elasticsearch").context_levels).toEqual([]);
    expect(databaseCapabilities("postgresql")).toMatchObject({table_export:true,temporary_tables:true,manual_transactions:true,ssh:true});
  });
  it("imports Mongo credentials separately from a public SRV URI",()=>{
    const config=parseConnectionString("mongodb+srv://user%40tenant:p%40ss%3Aword@cluster.example.net/sample?authSource=admin&retryWrites=false");
    expect(config).toMatchObject({db_type:"mongodb",username:"user@tenant",password:"p@ss:word",database:"sample"});
    expect(config.mongodb_uri).toBe("mongodb+srv://cluster.example.net/sample?authSource=admin&retryWrites=false");
    const publicConfig=connectionMetadata(config);
    expect(publicConfig.password).toBeUndefined();
    expect(JSON.stringify(publicConfig)).not.toContain("p@ss");
    const exported=formatConnectionString(config,"uri",true);
    expect(parseConnectionString(exported)).toMatchObject({username:config.username,password:config.password,database:config.database});
    expect(formatConnectionString(config,"python")).toContain("retryReads=False, retryWrites=False");
    expect(formatConnectionString(config,"csharp")).toContain("MongoDB.Driver");
    expect(formatConnectionString(config,"python")).not.toContain(config.password);
  });
  it("keeps the Cosmos Mongo compatibility profile during URI import",()=>{
    expect(parseConnectionString("mongodb://cluster.example.net/sample?ssl=true&replicaSet=globaldb","cosmosdb")).toMatchObject({db_type:"cosmosdb",cosmos_api:"mongodb"});
  });
  it("imports the Cosmos portal URI with maxIdleTimeMS and separates its account secret",()=>{
    const uri="mongodb://account:portal%2Fsecret%3D@account.mongo.cosmos.azure.com:10255/?ssl=true&replicaSet=globaldb&retrywrites=false&maxIdleTimeMS=120000&appName=@account@";
    const config=parseConnectionString(uri,"cosmosdb"),safe=connectionMetadata(config);
    expect(config).toMatchObject({db_type:"cosmosdb",cosmos_api:"mongodb",username:"account",password:"portal/secret="});
    const options=new URLSearchParams(config.mongodb_uri!.split("?")[1]);
    expect(options.get("maxIdleTimeMS")).toBe("120000");
    expect(options.get("appName")).toBe("@account@");
    expect(safe.mongodb_uri!.split("?")[0]).toBe("mongodb://account.mongo.cosmos.azure.com:10255/");
    expect(JSON.stringify(safe)).not.toContain("portal");
    expect(safe).not.toHaveProperty("password");
  });
  it.each(["mongodb://user:secret@host/db?authMechanismProperties=SECRET:abc","mongodb://host/db?password=secret","mongodb://host/db?tls=true&TLS=false","mongodb+srv://host:27017/db"])("rejects secret, ambiguous or invalid URI options: %s",uri=>{
    expect(()=>parseConnectionString(uri)).toThrow();
  });
  it("imports Cosmos account keys into secret fields and redacts every document credential",()=>{
    const config=parseConnectionString("AccountEndpoint=https://account.documents.azure.com/;AccountKey=private-key;Database=analysis;Container=sales;","cosmosdb");
    expect(config).toMatchObject({cosmos_api:"nosql",auth_mode:"key",account_key:"private-key",container:"sales"});
    const safe=connectionMetadata({...config,api_key:"private-api",client_secret:"private-client",password:"private-pass"});
    expect(JSON.stringify(safe)).not.toContain("private-");
    expect(formatConnectionString(config,"native")).toContain("<account-key>");
    expect(formatConnectionString(config,"native",true)).toContain("private-key");
  });
  it("uses real SDK examples and excludes fictional SQLAlchemy/native formats",()=>{
    const elastic=profile("elasticsearch",{endpoint:"https://elastic.example/",auth_mode:"api_key",api_key:"sensitive"});
    expect(connectionStringFormats(elastic).map(item=>item.id)).toEqual(["uri","python","csharp"]);
    expect(formatConnectionString(elastic,"python")).toContain("from elasticsearch import Elasticsearch");
    expect(formatConnectionString(elastic,"python")).not.toContain("sensitive");
    const cosmos=profile("cosmosdb",{endpoint:"https://account.documents.azure.com/",auth_mode:"entra",container:"sales"});
    expect(connectionStringFormats(cosmos).map(item=>item.id)).toEqual(["python","csharp"]);
    expect(formatConnectionString(cosmos,"python")).toContain('InteractiveBrowserCredential(tenant_id="organizations")');
    expect(()=>formatConnectionString(cosmos,"uri")).toThrow();
  });
  it("only accepts HTTP endpoints for a selected HTTP adapter",()=>{
    expect(()=>parseConnectionString("https://example.net/","sqlserver")).toThrow();
    expect(parseConnectionString("https://example.net/","elasticsearch")).toMatchObject({endpoint:"https://example.net/"});
    expect(()=>parseConnectionString("https://user:secret@example.net/","elasticsearch")).toThrow();
    expect(()=>parseConnectionString("https://example.net/?key=secret","cosmosdb")).toThrow();
  });
});

describe("Cosmos containers are isolated execution and completion scopes",()=>{
  it("persists explicit block and session containers through DPW without credentials",()=>{
    const session=newSession();session.database="db";session.container="orders";session.blocks[0].container="customers";
    const restored=decodeDocument(encodeDocument(session));
    expect(restored.container).toBe("orders");expect(restored.blocks[0].container).toBe("customers");
    expect(completionConnectionScope(restored,restored.blocks[0])).toMatchObject({database:"db",container:"customers"});
  });
  it("does not inherit another database's container",()=>{
    const session=newSession();session.database="one";session.container="orders";
    expect(completionConnectionScope(session,{...session.blocks[0],database_name:"two"}).container).toBeUndefined();
  });
  it("clears a restored container rather than reviving its old desktop extras",()=>{
    const session=newSession();session.container="orders";
    const restored=decodeDocument(encodeDocument(session));restored.container=undefined;
    expect(decodeDocument(encodeDocument(restored)).container).toBeUndefined();
  });
  it("caches distinct container snapshots and does not borrow a late old snapshot",()=>{
    const contexts=new SessionLanguageContexts();
    const event=(container:string,version:number):RuntimeEvent=>({event:"language.context_updated",payload:{session_id:"s",block_id:"b",connection_id:"c",database:"db",container,version,variables:{},requested_scope:{connection_id:"c",database:"db",container},schema_snapshot:{db_type:"cosmosdb",database:"db",container,tables:[{name:container}],columns:{[container]:[{name:`${container}_id`}]}}}});
    contexts.accept(event("orders",1));contexts.accept(event("customers",2));
    expect(contexts.get("s","c","db",undefined,"b",false,true,"customers")?.tables).toEqual(["customers"]);
    expect(contexts.get("s","c","db",undefined,"b",false,true,"orders")?.tables).toEqual(["orders"]);
    expect(contexts.get("s","c","db",undefined,"b",false,true,"unknown")?.tables).toBeUndefined();
    contexts.invalidate("s","c","db",undefined,"b",false,true,"orders");
    expect(contexts.get("s","c","db",undefined,"b",false,true,"customers")?.tables).toEqual(["customers"]);
  });
  it("loads containers from the selected database without a fictitious schema",async()=>{
    const request=vi.fn(async()=>({nodes:[{id:"orders",name:"orders",kind:"table",has_children:true}],context:{database:"db"}}));
    const client=new ScopeOptionsClient({request} as unknown as RuntimeTransport);
    expect((await client.list({session_id:"s",database:"db",container:"old"},"container")).options.map(item=>item.name)).toEqual(["orders"]);
    expect(request).toHaveBeenCalledWith("explorer.list",expect.objectContaining({database:"db",node:expect.objectContaining({kind:"database",name:"db"})}));
  });
  it("prepares distinct container requests and preserves the container in RPC",async()=>{
    const request=vi.fn(async()=>({status:"ready",context_version:1}));
    const preparation=new ScopePreparation({request} as unknown as RuntimeTransport);
    await preparation.request({sessionId:"s",blockId:"b",connectionId:"c",database:"db",container:"orders"},"SELECT * FROM c");
    await preparation.request({sessionId:"s",blockId:"b",connectionId:"c",database:"db",container:"customers"},"SELECT * FROM c");
    expect(request.mock.calls).toHaveLength(2);
    expect(request).toHaveBeenLastCalledWith("language.prepare",expect.objectContaining({container:"customers"}));
  });
  it("rejects recovery events from another container",()=>{
    const session=newSession();session.savedConnectionId="c";session.database="db";session.container="customers";
    expect(recoveryMatches(session,undefined,{session_id:session.id,automatic_transactions:true,phase:"ready",recovery_id:"r",requested_scope:{connection_id:"c",database:"db",container:"orders"}})).toBe(false);
  });
});

describe("document SQL completion",()=>{
  const suggest=(code:string,context:CompletionContext)=>localCompletions("sql",completionSite("sql",code,code.length+1,context.dbType),context,code);
  const context=(dbType:string):CompletionContext=>({dbType,container:dbType==="cosmosdb"?"orders":undefined,variables:[],tables:["orders"],schemaSnapshot:{db_type:dbType,container:dbType==="cosmosdb"?"orders":undefined,partial:true,tables:{orders:{name:"orders",columns:[{name:"id"},{name:"customer.name"},{name:"customer.address.city"}]}}}});
  it("uses the Cosmos alias and selected container instead of relation qualification",()=>{
    const source=context("cosmosdb");
    expect(suggest("SELECT * FROM ",source).filter(item=>item.kind==="table").map(item=>item.insert_text)).toEqual(["c"]);
    expect(suggest("SELECT * FROM c WHERE c.cust",source).find(item=>item.label==="customer.name")?.insert_text).toBe("customer.name");
    expect(suggest("SELECT * FROM c WHERE ",source).find(item=>item.label==="id")?.insert_text).toBe("c.id");
  });
  it("completes nested JSON paths for Mongo aliases without quoting the full path",()=>{
    expect(suggest("SELECT * FROM orders o WHERE o.customer.na",context("mongodb")).find(item=>item.label==="name")?.insert_text).toBe("name");
    expect(suggest("SELECT * FROM orders o WHERE o.customer.address.",context("mongodb")).find(item=>item.label==="city")?.insert_text).toBe("city");
  });
  it("replaces the dot before a Cosmos bracket property, preserving its SQL syntax",()=>{
    const source=context("cosmosdb");source.schemaSnapshot!.tables!.orders.columns!.push({name:"customer.full-name"});
    const code="SELECT * FROM c WHERE c.customer.fu",site=completionSite("sql",code,code.length+1,"cosmosdb");
    const item=localCompletions("sql",site,source,code).find(item=>item.label==="full-name")!;
    expect(item.start_column).toBe(site.startColumn-1);
    expect(code.slice(0,item.start_column!-1)+completionInsertion(item,site,"sql")).toBe('SELECT * FROM c WHERE c.customer["full-name"]');
    expect(documentFieldReference("customer.full-name","cosmosdb")).toBe('c.customer["full-name"]');
    expect(documentFieldReference("customer.name","mongodb")).toBe('"customer"."name"');
  });
  it("keeps broad table suggestions bounded and narrows large immutable catalogs",()=>{
    const tables=Object.fromEntries(Array.from({length:100_000},(_,i)=>[`orders_${i}`,{name:`orders_${i}`}])) as NonNullable<CompletionContext["schemaSnapshot"]>["tables"];
    const source:CompletionContext={dbType:"mongodb",variables:[],tables:Object.keys(tables!),schemaSnapshot:{db_type:"mongodb",tables}};
    expect(suggest("SELECT * FROM ",source)).toHaveLength(500);
    expect(suggest("SELECT * FROM orders_99999",source).map(item=>item.label)).toEqual(["orders_99999"]);
  });
  it.each(["cosmosdb","mongodb","elasticsearch"])("does not suggest writes or relational remote completions for %s",type=>{
    const source=context(type),site=completionSite("sql","",1,type);
    expect(suggest("SELECT * FROM orders WHERE ",source).map(item=>item.label)).not.toEqual(expect.arrayContaining(["DELETE","UPDATE","COMMIT","ROLLBACK"]));
    expect(contextualCompletions([{label:"DELETE",kind:"keyword"}],site,source,"sql")).toEqual([]);
  });
});
