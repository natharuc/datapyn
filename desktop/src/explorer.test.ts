import { describe, expect, it } from "vitest";
import { ExplorerController, explorerRows, quoteIdentifier, quoteIdentifierPart, identifierParts,reloadExpanded, type ExplorerNode } from "./explorer";
import type { RuntimeTransport } from "./runtime";
describe("Object Explorer", () => {
  it("quotes identifiers using their real dialect and preserves embedded quoted dots", () => {
    expect(identifierParts('[my.db].[odd]]name]')).toEqual(["my.db", "odd]name"]);
    expect(quoteIdentifier('[my.db].[odd]]name]', "sqlserver")).toBe('[my.db].[odd]]name]');
    expect(quoteIdentifier('"my.schema"."Table"', "postgresql")).toBe('"my.schema"."Table"');
    expect(quoteIdentifier("db.table", "mysql")).toBe("`db`.`table`");
    expect(quoteIdentifierPart("a.b", "postgresql")).toBe('"a.b"');
  });
  it("filters loaded children while retaining their parent folders", () => {
    const root: ExplorerNode = { id: "db", name: "main", kind: "database", has_children: true }, table: ExplorerNode = { id: "table", name: "Orders", kind: "table", has_children: true };
    expect(explorerRows([root], { db: [table] }, new Set(), "orders").map((row) => row.node.id)).toEqual(["db", "table"]);
    expect(explorerRows([root], { db: [table] }, new Set(), "").map((row) => row.node.id)).toEqual(["db"]);
  });
  it("deduplicates repeated expansion requests and invalidates old database responses", async () => {
    const resolvers: Array<(value: { nodes: ExplorerNode[] }) => void> = [], calls: unknown[] = [];
    const transport = { request: (_method: string, params: unknown) => { calls.push(params); return new Promise((resolve) => resolvers.push(resolve as typeof resolvers[number])); }, subscribe: async () => () => {} } as RuntimeTransport;
    const controller = new ExplorerController(transport); controller.setScope({ session_id: "s", connection_id: "one" });
    const old = controller.list(), duplicate = controller.list(); expect(calls).toHaveLength(1);
    controller.setScope({ session_id: "s", connection_id: "two" }); const current = controller.list();
    resolvers[0]({ nodes: [{ id: "old", name: "old", kind: "database", has_children: true }] }); expect(await old).toEqual([]); expect(await duplicate).toEqual([]);
    const nodes = [{ id: "new", name: "new", kind: "database", has_children: true }]; resolvers[1]({ nodes }); expect(await current).toEqual(nodes); expect(await controller.list()).toEqual(nodes); expect(calls).toHaveLength(2);
  });
  it("retains open stable branches and never loads unopened metadata during refresh",async()=>{
    const db:ExplorerNode={id:"db",name:"main",kind:"database",has_children:true},closed:ExplorerNode={id:"closed",name:"archive",kind:"database",has_children:true},table:ExplorerNode={id:"table",name:"orders",kind:"table",has_children:true};
    const calls:string[]=[];
    const transport={request:async(_method:string,params:{node?:ExplorerNode})=>{const id=params.node?.id??"root";calls.push(id);return {nodes:id==="root"?[db,closed]:id==="db"?[table]:[{id:"column",name:"id",kind:"column",has_children:false,dtype:"BIGINT"}]};}} as unknown as RuntimeTransport;
    const controller=new ExplorerController(transport);controller.setScope({session_id:"s"});
    const fresh=await reloadExpanded(controller,new Set(["db","table","removed"]),()=>true);
    expect(calls).toEqual(["root","db","table"]);expect(fresh?.expanded).toEqual(new Set(["db","table"]));expect(fresh?.children.table[0].data_type).toBe("BIGINT");
  });
  it("abandons a refresh when a connection change invalidates its generation",async()=>{
    let current=true;const node:ExplorerNode={id:"db",name:"main",kind:"database",has_children:true};
    const transport={request:async()=>{current=false;return {nodes:[node]};}} as unknown as RuntimeTransport;
    const controller=new ExplorerController(transport);controller.setScope({session_id:"s"});
    expect(await reloadExpanded(controller,new Set(["db"]),()=>current)).toBeUndefined();
  });
});
