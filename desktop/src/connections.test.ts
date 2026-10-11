import { describe, expect, it } from "vitest";
import { ConnectionsController, connectionRows, connectionSearchText, effectiveConnectionColor, effectiveGroupColor, groupDescendants, groupHierarchy, catalogDropAllowed, moveCatalogRow, type ConnectionCatalog, type SavedConnection } from "./connections";
import type { RuntimeTransport } from "./runtime";
const connection = (id: string, group_id: string | null, name = id): SavedConnection => ({ id, group_id, name, order: 1, color: "", favorite: false, has_password: false, config: { db_type: "sqlite", host: "", port: 0, database: "sample.db", username: "" } });
const catalog: ConnectionCatalog = { version: 1, groups: [
  { id: "g1", name: "Produção", parent_id: null, color: "", order: 0 }, { id: "g2", name: "Operações", parent_id: "g1", color: "", order: 0 },
], connections: [connection("c1", "g2", "Financeiro"), connection("c2", null, "Local")] };

describe("saved connection tree", () => {
  it("uses the explicit connection color before its nearest colored group ancestor",()=>{
    const data={...catalog,groups:catalog.groups.map(group=>({...group,color:group.id==="g1"?"#eeaa00":"#0066ff"}))};
    expect(effectiveConnectionColor("c1",data)).toBe("#0066ff");
    expect(effectiveConnectionColor({...catalog.connections[0],color:"#cc44bb"},data)).toBe("#cc44bb");
    const inherited={...data,groups:data.groups.map(group=>({...group,color:group.id==="g2"?"  ":group.color}))};
    expect(effectiveConnectionColor("c1",inherited)).toBe("#eeaa00");expect(effectiveGroupColor("g2",inherited)).toBe("#eeaa00");
  });
  it("handles missing connections, missing parents and cyclic imported group colors safely",()=>{
    expect(effectiveConnectionColor("unknown",catalog)).toBeUndefined();expect(effectiveConnectionColor("c2",catalog)).toBeUndefined();
    const missing={...catalog,groups:[]};expect(effectiveConnectionColor("c1",missing)).toBeUndefined();
    const cyclic={...catalog,groups:catalog.groups.map(group=>({...group,parent_id:group.id==="g1"?"g2":"g1",color:""}))};
    expect(effectiveConnectionColor("c1",cyclic)).toBeUndefined();
    cyclic.groups[0].color="#55aa33";expect(effectiveConnectionColor("c1",cyclic)).toBe("#55aa33");
  });
  it("expands nested groups and search preserves matching ancestors", () => {
    expect(connectionRows(catalog, new Set()).map((row) => row.key)).toEqual(["g:g1", "c:c2"]);
    expect(connectionRows(catalog, new Set(), "financeiro").map((row) => [row.key, row.depth])).toEqual([["g:g1", 0], ["g:g2", 1], ["c:c1", 2]]);
  });
  it("searches host, database, user and auth without including secrets", () => {
    const entry = { ...connection("one", null), config: { ...connection("one", null).config, host: "analytics", username: "reader", password: "hidden-secret", use_windows_auth: true } };
    const text = connectionSearchText(entry, []);
    expect(text).toContain("analytics"); expect(text).toContain("reader"); expect(text).toContain("windows auth"); expect(text).not.toContain("hidden-secret");
  });
  it("shows favorited descendants with their group path", () => {
    const data = { ...catalog, connections: catalog.connections.map((item) => ({ ...item, favorite: item.id === "c1" })) };
    expect(connectionRows(data, new Set(), "", true).map((row) => row.key)).toEqual(["g:g1", "g:g2", "c:c1"]);
  });
  it("rejects cycles when selecting a group's new parent", () => {
    expect([...groupDescendants(catalog.groups, "g1")]).toEqual(["g1", "g2"]);
    const cyclic = [{ ...catalog.groups[0], parent_id: "g2" }, catalog.groups[1]];
    expect(groupDescendants(cyclic, "g1").size).toBe(2);
  });
  it("keeps orphaned imported connections discoverable", () => {
    expect(connectionRows({ version: 1, groups: [], connections: [connection("orphan", "missing")] }, new Set()).map((row) => row.key)).toEqual(["c:orphan"]);
  });
});

describe("catalog broker state", () => {
  it("discards old reads after switching to a newer catalog", async () => {
    const resolvers: Array<(value: ConnectionCatalog) => void> = [];
    const transport = { request: () => new Promise((resolve) => resolvers.push(resolve as (value: ConnectionCatalog) => void)), subscribe: async () => () => {} } as RuntimeTransport;
    const controller = new ConnectionsController(transport), first = controller.refresh(), second = controller.refresh();
    resolvers[1](catalog); await second; resolvers[0]({ version: 1, groups: [], connections: [] }); await first;
    expect(controller.getSnapshot().catalog).toBe(catalog);
  });
  it("removes password from config and sends it only to the save request", async () => {
    const requests: Array<{ method: string; params?: Record<string, unknown> }> = [];
    const transport = { request: async (method: string, params?: Record<string, unknown>) => { requests.push({ method, params }); return method === "connections.list" ? catalog : connection("saved", null); }, subscribe: async () => () => {} } as RuntimeTransport;
    const controller = new ConnectionsController(transport);
    await controller.save({ name: "saved", config: { ...connection("x", null).config, password: "transient" } }, "secret", true);
    const request = requests[0].params!; expect((request.connection as { config: unknown }).config).not.toHaveProperty("password"); expect(request.password).toBe("secret");
    expect(JSON.stringify(controller.getSnapshot())).not.toContain("secret");
  });
});

describe("connection organization", () => {
  it("shows full paths and terminates malformed group cycles", () => {
    expect(groupHierarchy(catalog.groups).map(item => item.label)).toEqual(["Produção", "Produção / Operações"]);
    expect(groupHierarchy([{ ...catalog.groups[0], parent_id: "g2" }, catalog.groups[1]])).toHaveLength(2);
  });
  it("rejects group cycles and allows connections between ancestors, children and root", () => {
    const parent = { key: "g:g1", depth: 0, group: catalog.groups[0] }, child = { key: "g:g2", depth: 1, group: catalog.groups[1] }, leaf = { key: "c:c1", depth: 2, connection: catalog.connections[0] };
    expect(catalogDropAllowed(catalog, parent, child)).toBe(false); expect(catalogDropAllowed(catalog, child, child)).toBe(false);
    expect(catalogDropAllowed(catalog, child, null)).toBe(true); expect(catalogDropAllowed(catalog, leaf, parent)).toBe(true); expect(catalogDropAllowed(catalog, leaf, null)).toBe(true);
    expect(catalogDropAllowed(catalog, leaf, leaf)).toBe(false);
  });
  it("moves to the destination group before reordering relative to a connection", async () => {
    const requests: Array<{ method: string; params?: Record<string, unknown> }> = [];
    const transport = { request: async (method: string, params?: Record<string, unknown>) => { requests.push({ method, params }); return method === "connections.list" ? catalog : {}; }, subscribe: async () => () => {} } as RuntimeTransport;
    const controller = new ConnectionsController(transport); await controller.refresh(); requests.length = 0;
    await moveCatalogRow(controller, { key: "c:c2", depth: 0, connection: catalog.connections[1] }, { key: "c:c1", depth: 2, connection: catalog.connections[0] });
    expect(requests.filter(request => request.method !== "connections.list")).toEqual([{ method: "connections.move", params: { connection_id: "c2", group_id: "g2" } }, { method: "connections.reorder", params: { connection_ids: ["c2", "c1"] } }]);
  });
  it("requests credentials only with the caller's explicit choice and does not mutate state", async () => {
    const requests: Array<{ method: string; params?: Record<string, unknown> }> = [];
    const transport = { request: async (method: string, params?: Record<string, unknown>) => { requests.push({ method, params }); return { config: { ...connection("c", null).config, ...(params?.include_password ? { password: "secret" } : {}) } }; }, subscribe: async () => () => {} } as RuntimeTransport;
    const controller = new ConnectionsController(transport), before = controller.getSnapshot();
    expect((await controller.exportConfig("c")).config.password).toBeUndefined(); expect((await controller.exportConfig("c", true)).config.password).toBe("secret");
    expect(requests.map(request => request.params?.include_password)).toEqual([false, true]); expect(controller.getSnapshot()).toBe(before);
  });
});
