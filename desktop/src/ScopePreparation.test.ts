import { describe, expect, it } from "vitest";
import { ScopePreparation, preparationCodeKey, type PreparationResult, type PreparationScope } from "./ScopePreparation";
import type { RuntimeEvent, RuntimeTransport } from "./runtime";

const ready: PreparationResult = { status: "ready", context_version: 1 };
const scope: PreparationScope = { sessionId: "analysis", connectionId: "production", database: "sales", schema: "public", dbType: "postgresql" };
function transport(handler: (method: string, params: Record<string, unknown>) => Promise<PreparationResult>): Pick<RuntimeTransport, "request"> {
  return { request: handler } as Pick<RuntimeTransport, "request">;
}
function contextEvent(payload: Record<string, unknown>): RuntimeEvent {
  return { event: "language.context_updated", payload: { session_id: "analysis", connection_id: "production", database: "sales", schema: "public", version: 1, variables: {}, ...payload } } as RuntimeEvent;
}

describe("focused SQL scope preparation", () => {
  it("keys metadata by relations rather than changes to expressions, whitespace, or comments", () => {
    expect(preparationCodeKey("SELECT 1 FROM sales s WHERE s.value > 0"))
      .toBe(preparationCodeKey("SELECT 2\nFROM sales s\nWHERE s.value > 200 /* JOIN irrelevant */"));
    expect(preparationCodeKey("SELECT s.va FROM sales s")).toBe(preparationCodeKey("SELECT s.value FROM sales s"));
    expect(preparationCodeKey("SELECT * FROM sales")).not.toBe(preparationCodeKey("SELECT * FROM customers"));
    expect(preparationCodeKey("SELECT * FROM sales JOIN customers c ON 1=1"))
      .toBe(preparationCodeKey("SELECT * FROM customers c JOIN sales ON 2=2"));
  });
  it("includes relations across statements and subqueries", () => {
    const key = preparationCodeKey("SELECT * FROM sales; SELECT (SELECT value FROM archived) FROM customers;");
    expect(key).toContain("sales"); expect(key).toContain("archived"); expect(key).toContain("customers");
  });
  it("includes comma sources while distinguishing expressions and nested argument lists", () => {
    const key = preparationCodeKey("SELECT foo, bar FROM sales s, customers c WHERE x IN (1, 2)");
    expect(key).toContain("sales"); expect(key).toContain("customers");
    expect(key).not.toContain("bar");
    expect(preparationCodeKey("SELECT * FROM sales s, customers c"))
      .not.toBe(preparationCodeKey("SELECT * FROM sales s, archived a"));
    expect(preparationCodeKey("SELECT * FROM sales s WHERE x=1, invalid"))
      .toBe(preparationCodeKey("SELECT * FROM sales s WHERE x=1"));
  });
  it("ignores keywords in quoted names, strings, and nested comments", () => {
    expect(preparationCodeKey("SELECT 'FROM fake', $$ JOIN nope $$ FROM real /* /* nested */ JOIN ignored */", "postgresql"))
      .toBe(preparationCodeKey("SELECT * FROM real", "postgresql"));
    expect(preparationCodeKey('SELECT "FROM fake" FROM real')).toBe(preparationCodeKey("SELECT * FROM real"));
  });
  it("preserves quoted identity and escaped qualified names", () => {
    expect(preparationCodeKey('SELECT * FROM "Sales"')).not.toBe(preparationCodeKey('SELECT * FROM "sales"'));
    expect(preparationCodeKey('SELECT * FROM "Odd.Schema"."Table"')).toBe(preparationCodeKey("SELECT * FROM [Odd.Schema].[Table]"));
    expect(preparationCodeKey('SELECT * FROM [odd]]name]')).toContain("odd]name");
    expect(preparationCodeKey("SELECT * FROM [db]..[table]")).toContain("dbo");
  });
  it("treats schema/catalog prefixes as relevant while ignoring partial field spelling", () => {
    expect(preparationCodeKey("SELECT * FROM catalog.schema.ta")).not.toBe(preparationCodeKey("SELECT * FROM other.schema.ta"));
    expect(preparationCodeKey("SELECT catalog.schema.ta")).toBe(preparationCodeKey("SELECT catalog.schema.table"));
    expect(preparationCodeKey("SELECT catalog.schema.")).toBe(preparationCodeKey("SELECT catalog.schema.table"));
  });
  it.each(["mysql", "mariadb"])("handles %s comments and string escaping", dbType => {
    expect(preparationCodeKey("SELECT 'x\\'JOIN nope' FROM real # JOIN false_table", dbType))
      .toBe(preparationCodeKey("SELECT * FROM real", dbType));
  });
  it("separates PostgreSQL ordinary strings and E strings", () => {
    expect(preparationCodeKey("SELECT 'C:\\' FROM real", "postgresql")).toBe(preparationCodeKey("SELECT * FROM real", "postgresql"));
    expect(preparationCodeKey("SELECT E'a\\'JOIN fake' FROM real", "postgresql")).toBe(preparationCodeKey("SELECT * FROM real", "postgresql"));
  });
  it("keys routine metadata separately from ordinary table metadata", () => {
    expect(preparationCodeKey("CALL process() ")).not.toBe(preparationCodeKey("SELECT 1"));
    expect(preparationCodeKey("SELECT 'CALL process()' ")).toBe(preparationCodeKey("SELECT 1"));
  });
  it("deduplicates requests and reuses prepared metadata despite expression changes", async () => {
    let calls = 0, method = "", params: Record<string, unknown> = {};
    const client = new ScopePreparation(transport(async (name, value) => { calls++; method = name; params = value; return ready; }));
    const first = client.request(scope, "SELECT value FROM sales"), duplicate = client.request(scope, "SELECT price FROM sales");
    expect(duplicate).toBe(first); expect(await first).toBe(ready);
    expect(client.request(scope, "SELECT COUNT(*) FROM sales")).toBe(first);
    expect(calls).toBe(1); expect(method).toBe("language.prepare");
    expect(params).toEqual({ session_id: "analysis", connection_id: "production", database: "sales", schema: "public", code: "SELECT value FROM sales" });
  });
  it("warms new sources and isolates sessions, databases, schemas, and connections", async () => {
    let calls = 0;
    const client = new ScopePreparation(transport(async () => { calls++; return ready; }));
    for (const input of [scope, { ...scope, sessionId: "other" }, { ...scope, database: "archive" },
      { ...scope, schema: "private" }, { ...scope, connectionId: "other" }]) await client.request(input, "SELECT * FROM sales");
    await client.request(scope, "SELECT * FROM customers"); expect(calls).toBe(6);
  });
  it("refresh invalidates the exact scope and lets later ordinary requests share its pending job", async () => {
    let calls = 0; const invalidated: PreparationScope[] = [];
    const client = new ScopePreparation(transport(async () => { calls++; return ready; }), value => invalidated.push(value));
    const old = client.request(scope, "SELECT * FROM sales"); await old;
    const other = client.request({ ...scope, database: "archive" }, "SELECT * FROM sales"); await other;
    await client.request(scope, "SELECT * FROM customers");
    const refresh = client.request(scope, "SELECT * FROM sales", true);
    expect(refresh).not.toBe(old); expect(client.request(scope, "SELECT 1 FROM sales")).toBe(refresh); await refresh;
    expect(invalidated).toEqual([scope]);
    expect(client.request({ ...scope, database: "archive" }, "SELECT * FROM sales")).toBe(other);
    await client.request(scope, "SELECT * FROM customers"); expect(calls).toBe(5);
  });
  it("sends explicit refresh to the backend and retries failed preparation", async () => {
    let calls = 0; const requests: Record<string, unknown>[] = [];
    const client = new ScopePreparation(transport(async (_, value) => {
      calls++; requests.push(value); if (calls === 1) throw new Error("unavailable"); return ready;
    }));
    await expect(client.request(scope, "", true)).rejects.toThrow("unavailable");
    await expect(client.request(scope)).resolves.toBe(ready);
    expect(calls).toBe(2); expect(requests[0].refresh).toBe(true); expect(requests[1]).not.toHaveProperty("refresh");
  });
  it("an obsolete failure cannot evict a newer request for the same scope", async () => {
    const failures: Array<(failure: Error) => void> = [], resolvers: Array<(value: PreparationResult) => void> = [];
    const client = new ScopePreparation(transport(() => new Promise((resolve, reject) => { resolvers.push(resolve); failures.push(reject); })));
    const old = client.request(scope); await Promise.resolve();
    const failure = old.catch(() => {});
    const current = client.request(scope, "", true); await Promise.resolve();
    failures[0](new Error("stale")); await failure;
    resolvers[1](ready); await current;
    expect(client.request(scope)).toBe(current);
  });
  it("bounds entries per session and retains most recently used scopes", async () => {
    let calls = 0;
    const client = new ScopePreparation(transport(async () => { calls++; return ready; }), undefined, 2);
    const first = client.request(scope); await first;
    await client.request({ ...scope, schema: "two" });
    expect(client.request(scope)).toBe(first);
    await client.request({ ...scope, schema: "three" });
    expect(client.request(scope)).toBe(first);
    await client.request({ ...scope, schema: "two" }); expect(calls).toBe(4);
    await client.request({ ...scope, sessionId: "other" });
    await client.request({ ...scope, sessionId: "other", schema: "two" });
    expect(calls).toBe(6);
  });
  it.each(["session.ready", "session.reset", "session.error"] as const)("clears one session on %s", async event => {
    const client = new ScopePreparation(transport(async () => ready));
    const original = client.request(scope), other = client.request({ ...scope, sessionId: "other" }); await Promise.all([original, other]);
    client.accept({ event, payload: { session_id: "analysis", error: "failure" } } as RuntimeEvent);
    expect(client.request(scope)).not.toBe(original);
    expect(client.request({ ...scope, sessionId: "other" })).toBe(other);
  });
  it("clears all scopes when the backend exits and removes closed sessions on retain", async () => {
    const client = new ScopePreparation(transport(async () => ready));
    const original = client.request(scope), other = client.request({ ...scope, sessionId: "other" }); await Promise.all([original, other]);
    client.retain(new Set(["analysis"]));
    expect(client.request(scope)).toBe(original);
    expect(client.request({ ...scope, sessionId: "other" })).not.toBe(other);
    client.accept({ event: "backend.exited", payload: { message: "closed" } });
    expect(client.request(scope)).not.toBe(original);
  });
  it("releases only the failed requested scope so focus can retry metadata", async () => {
    const client = new ScopePreparation(transport(async () => ready));
    const original = client.request(scope), other = client.request({ ...scope, database: "archive" }); await Promise.all([original, other]);
    client.accept(contextEvent({ metadata_state: "error", requested_scope: { connection_id: "production", database: "sales", schema: "public" } }));
    expect(client.request(scope)).not.toBe(original);
    expect(client.request({ ...scope, database: "archive" })).toBe(other);
  });
  it("invalidates a connection's prepared scopes without touching another connection", async () => {
    const client = new ScopePreparation(transport(async () => ready));
    const original = client.request(scope), other = client.request({ ...scope, connectionId: "other" }); await Promise.all([original, other]);
    client.accept(contextEvent({ metadata_invalidated: true }));
    expect(client.request(scope)).not.toBe(original);
    expect(client.request({ ...scope, connectionId: "other" })).toBe(other);
  });
  it("uses requested null identifiers rather than resolved transient labels when an implicit scope fails", async () => {
    const client = new ScopePreparation(transport(async () => ready));
    const implicit: PreparationScope = { sessionId: "analysis" };
    const original = client.request(implicit); await original;
    client.accept(contextEvent({ connection_id: "transient", metadata_state: "error",
      requested_scope: { connection_id: null, database: null, schema: null } }));
    expect(client.request(implicit)).not.toBe(original);
  });
  it("invalidates a transient scope even before its resolved alias was published", async () => {
    const client = new ScopePreparation(transport(async () => ready));
    const implicit = { ...scope, connectionId: undefined };
    const original = client.request(implicit), explicit = client.request(scope); await Promise.all([original, explicit]);
    client.accept(contextEvent({ connection_id: "transient", metadata_invalidated: true }));
    expect(client.request(implicit)).not.toBe(original);
    expect(client.request(scope)).toBe(explicit);
  });
  it("remembers the implicit connection behind resolved metadata and removes its preparation on invalidation", async () => {
    const client = new ScopePreparation(transport(async () => ready));
    const implicit = { ...scope, connectionId: undefined };
    const original = client.request(implicit), other = client.request({ ...scope, connectionId: "other" }); await Promise.all([original, other]);
    client.accept(contextEvent({ metadata_state: "ready", requested_scope: { connection_id: null, database: "sales", schema: "public" } }));
    client.accept(contextEvent({ metadata_invalidated: true }));
    expect(client.request(implicit)).not.toBe(original);
    expect(client.request({ ...scope, connectionId: "other" })).toBe(other);
  });
  it("clears connection resolution aliases when the session resets", async () => {
    const client = new ScopePreparation(transport(async () => ready));
    const implicit = { ...scope, connectionId: undefined };
    await client.request(implicit);
    client.accept(contextEvent({ metadata_state: "ready", requested_scope: { connection_id: null, database: "sales", schema: "public" } }));
    client.reset("analysis");
    const next = client.request(implicit); await next;
    client.accept(contextEvent({ metadata_invalidated: true }));
    expect(client.request(implicit)).toBe(next);
  });
});
