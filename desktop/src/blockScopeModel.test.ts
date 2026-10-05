import { describe, expect, it } from "vitest";
import { ScopeOptionsClient, filterScopeOptions, hasSchemaScope, scopeListWindow, scopeOptionIndex,
  scopeOptionList, type ScopeOptions } from "./blockScopeModel";
import type { ExplorerNode, ExplorerResult } from "./explorer";
import type { RuntimeTransport } from "./runtime";

const node = (name: string, kind = "database"): ExplorerNode => ({ name, kind, id: name, has_children: true });
const scope = { session_id: "analysis", connection_id: "production", database: "sales", schema: "public", db_type: "postgresql" };
function transport(handler: (method: string, params: Record<string, unknown>) => Promise<ExplorerResult>): RuntimeTransport {
  return { request: handler, subscribe: async () => () => {} } as RuntimeTransport;
}

describe("block database and schema picker", () => {
  it("separates list caches when a block switches between pinned and inherited physical affinity",async()=>{
    const requests:Record<string,unknown>[]=[];const client=new ScopeOptionsClient(transport(async(_,params)=>{requests.push(params);return{nodes:[node(params.scope_inherited?"inherited":"pinned","schema")]};}));
    expect((await client.list({...scope,block_id:"block"},"schema")).options[0].name).toBe("pinned");
    expect((await client.list({...scope,block_id:"block",scope_inherited:true},"schema")).options[0].name).toBe("inherited");
    expect((await client.list({...scope,block_id:"block",scope_inherited:false},"schema")).options[0].name).toBe("pinned");expect(requests.map(params=>params.scope_inherited)).toEqual([false,true]);
  });
  it("keeps selector metadata tied to each block connector",async()=>{
    const requests:Record<string,unknown>[]=[];
    const client=new ScopeOptionsClient(transport(async(_,params)=>{requests.push(params);return{nodes:[node(String(params.block_id),"schema")]};}));
    expect((await client.list({...scope,block_id:"first"},"schema")).options[0].name).toBe("first");
    expect((await client.list({...scope,block_id:"second"},"schema")).options[0].name).toBe("second");
    expect(requests.map(params=>params.block_id)).toEqual(["first","second"]);
  });
  it("normalizes only database/catalog metadata and keeps case-sensitive names distinct", () => {
    expect(scopeOptionList([node("catalog", "catalog"), node("db10"), node("db2"), node("db2"), node("DB2"), node("tbl", "table")], "database")
      .map(option => option.name)).toEqual(["catalog", "db2", "DB2", "db10"]);
    expect(scopeOptionList([node("public", "schema"), node("db"), node("private", "schema")], "schema")
      .map(option => option.name)).toEqual(["private", "public"]);
  });
  it("searches accents, substrings, and multiple terms locally", () => {
    const options = scopeOptionList([node("Produção Financeiro"), node("Produção Dados"), node("HML Financeiro")], "database");
    expect(filterScopeOptions(options, "PRODUCAO  finan").map(option => option.name)).toEqual(["Produção Financeiro"]);
    expect(filterScopeOptions(options, " ")).toBe(options);
    expect(filterScopeOptions(options, "inexistente")).toEqual([]);
  });
  it("shows schema for multi-schema engines, including PostgreSQL aliases", () => {
    expect(["databricks", "postgres", "postgresql", "sqlserver", "mssql"].every(hasSchemaScope)).toBe(true);
    expect(["mysql", "mariadb", "sqlite", undefined].some(hasSchemaScope)).toBe(false);
  });
  it("supports keyboard navigation without wrapping unexpectedly", () => {
    expect(scopeOptionIndex(5, -1, "ArrowDown")).toBe(0);
    expect(scopeOptionIndex(5, -1, "ArrowUp")).toBe(4);
    expect(scopeOptionIndex(5, 2, "ArrowUp")).toBe(1);
    expect(scopeOptionIndex(5, 0, "ArrowUp")).toBe(0);
    expect(scopeOptionIndex(5, 4, "ArrowDown")).toBe(4);
    expect(scopeOptionIndex(5, 3, "Home")).toBe(0);
    expect(scopeOptionIndex(5, 0, "End")).toBe(4);
    expect(scopeOptionIndex(0, 0, "End")).toBe(-1);
  });
  it("bounds render work even for hundreds of thousands of catalogs", () => {
    expect(scopeListWindow(100_000, 0, 224)).toEqual({ first: 0, end: 11 });
    const window = scopeListWindow(100_000, 50_000 * 28, 224);
    expect(window.end - window.first).toBe(14);
    expect(window.first).toBe(49_997);
    expect(scopeListWindow(0, 0, 224)).toEqual({ first: 0, end: 0 });
  });
  it("deduplicates metadata requests across blocks, then searches without new RPCs", async () => {
    let calls = 0, resolve!: (value: ExplorerResult) => void;
    const client = new ScopeOptionsClient(transport(async () => { calls++; return new Promise(done => { resolve = done; }); }));
    const first = client.list(scope, "database"), second = client.list(scope, "database");
    expect(calls).toBe(1);
    resolve({ nodes: [node("sales"), node("archive")], context: { database: "sales" } });
    const options = await first;
    expect(await second).toBe(options);
    expect(await client.list(scope, "database")).toBe(options);
    for (const query of ["s", "sa", "sal", "sales"]) filterScopeOptions(options.options, query);
    expect(calls).toBe(1);
  });
  it.each(["sqlserver", "postgresql", "mysql", "mariadb", "sqlite", "databricks"])("uses the same database list API for %s", async db_type => {
    let method = "", params: Record<string, unknown> = {};
    const client = new ScopeOptionsClient(transport(async (name, value) => { method = name; params = value; return { nodes: [node("one")] }; }));
    expect((await client.list({ ...scope, db_type }, "database")).options[0].name).toBe("one");
    expect(method).toBe("explorer.list");
    expect(params).toMatchObject({ session_id: "analysis", connection_id: "production", database: "sales", schema: "public", refresh: false });
    expect(params.node).toBeUndefined();
  });
  it.each(["sqlserver", "postgresql", "databricks"])("lists schemas in the selected database for %s without the previous schema", async db_type => {
    let params: Record<string, unknown> = {};
    const client = new ScopeOptionsClient(transport(async (_, value) => { params = value; return { nodes: [node("next_schema", "schema")] }; }));
    expect((await client.list({ ...scope, db_type, database: "new_database", schema: "old_schema" }, "schema")).options[0].name).toBe("next_schema");
    expect(params).toMatchObject({ database: "new_database", node: { name: "new_database", database: "new_database", kind: "database" } });
    expect(params).not.toHaveProperty("schema");
  });
  it("never shares schemas between databases or connections or metadata revisions", async () => {
    let calls = 0;
    const client = new ScopeOptionsClient(transport(async (_, params) => { calls++; return { nodes: [node(String(params.database), "schema")] }; }));
    await client.list(scope, "schema");
    await client.list({ ...scope, database: "archive" }, "schema");
    await client.list({ ...scope, connection_id: "other" }, "schema");
    await client.list({ ...scope, revision: 1 }, "schema");
    expect(calls).toBe(4);
    expect((await client.list(scope, "schema")).options[0].name).toBe("sales");
    expect(calls).toBe(4);
  });
  it("expires metadata and bounds the cache using least-recently-used entries", async () => {
    let clock = 0, calls = 0;
    const client = new ScopeOptionsClient(transport(async () => { calls++; return { nodes: [] }; }), () => clock, 100, 2);
    await client.list(scope, "database");
    await client.list({ ...scope, database: "two" }, "database");
    await client.list(scope, "database");
    await client.list({ ...scope, database: "three" }, "database");
    await client.list(scope, "database");
    expect(calls).toBe(3);
    await client.list({ ...scope, database: "two" }, "database"); expect(calls).toBe(4);
    clock = 101;
    await client.list(scope, "database"); expect(calls).toBe(5);
  });
  it("prevents an older request overwriting an explicit metadata refresh", async () => {
    const resolvers: Array<(value: ExplorerResult) => void> = [];
    const client = new ScopeOptionsClient(transport(() => new Promise(resolve => resolvers.push(resolve))));
    const old = client.list(scope, "database"), fresh = client.list(scope, "database", true);
    resolvers[1]({ nodes: [node("fresh")] }); await fresh;
    resolvers[0]({ nodes: [node("old")] }); await old;
    expect((await client.list(scope, "database")).options[0].name).toBe("fresh");
  });
  it("rejects cache writes from requests started before clearing", async () => {
    const resolvers: Array<(value: ExplorerResult) => void> = [];
    const client = new ScopeOptionsClient(transport(() => new Promise(resolve => resolvers.push(resolve))));
    const old = client.list(scope, "database"); client.clear();
    const fresh = client.list(scope, "database");
    resolvers[1]({ nodes: [node("fresh")] }); await fresh;
    resolvers[0]({ nodes: [node("old")] }); await old;
    expect((await client.list(scope, "database")).options[0].name).toBe("fresh");
  });
  it("retries failures without caching an error", async () => {
    let calls = 0;
    const client = new ScopeOptionsClient(transport(async () => { if (++calls === 1) throw new Error("permission denied"); return { nodes: [node("available")] }; }));
    await expect(client.list(scope, "database")).rejects.toThrow("permission denied");
    expect((await client.list(scope, "database")).options[0].name).toBe("available"); expect(calls).toBe(2);
  });
});
