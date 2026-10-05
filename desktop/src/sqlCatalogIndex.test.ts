import { describe, expect, it } from "vitest";
import { completionSite, localCompletions } from "./editorCompletions";
import type { CompletionContext } from "./editorLanguage";

function complete(marked: string, context: CompletionContext) {
  const cursor = marked.indexOf("|"), source = marked.replace("|", ""), before = source.slice(0, cursor), line = before.split("\n").at(-1)!;
  return localCompletions("sql", completionSite("sql", line, line.length + 1, context.dbType ?? context.schemaSnapshot?.db_type), context, before, [], source, cursor);
}
const largeTables: NonNullable<NonNullable<CompletionContext["schemaSnapshot"]>["tables"]> = {};
for (let index = 0; index < 100_000; index++) {
  const name = `table_${String(index).padStart(6, "0")}`, key = `main.analytics.${name}`;
  largeTables[key] = { name, catalog: "main", schema: "analytics", columns: index === 99_999 ? [{ name: "value" }] : [] };
}
const large: CompletionContext = { variables: [], tables: Object.keys(largeTables), database: "main", schema: "analytics", dbType: "databricks",
  schemaSnapshot: { db_type: "databricks", database: "main", current_schema: "analytics", tables: largeTables } };

describe("large SQL catalogs", () => {
  it("reaches the final table by bare and qualified prefixes without losing names beyond the visible bound", () => {
    expect(complete("SELECT * FROM table_099999|", large)).toEqual([expect.objectContaining({ label: "table_099999",detail:"table",documentation:"main.analytics.table_099999", insert_text: "table_099999" })]);
    expect(complete("SELECT * FROM main.analytics.table_099999|", large)).toEqual([expect.objectContaining({ label: "table_099999", insert_text: "table_099999" })]);
    expect(complete("SELECT t.va| FROM table_099999 t", large)).toEqual([expect.objectContaining({ label: "value", insert_text: "value" })]);
    expect(complete("SELECT t.va| FROM main.analytics.table_099999 t", large)).toEqual([expect.objectContaining({ label: "value" })]);
  });
  it("preserves metadata order for bounded broad searches and never duplicates a full/bare match", () => {
    const broad = complete("SELECT * FROM table_|", large);
    expect(broad).toHaveLength(500);
    expect(broad[0]).toMatchObject({label:"table_000000",detail:"table",documentation:"main.analytics.table_000000"}); expect(broad.at(-1)).toMatchObject({label:"table_000499",detail:"table",documentation:"main.analytics.table_000499"});
    const namespaced = complete("SELECT * FROM main.analytics.table_|", large);
    expect(namespaced).toHaveLength(500); expect(namespaced[0].label).toBe("table_000000"); expect(namespaced.at(-1)?.label).toBe("table_000499");
    const mixed: CompletionContext = { variables: [], tables: ["foo_schema.foo", "foo_schema.bar", "other.foo_table"], dbType: "sqlite" };
    expect(complete("FROM foo|", mixed).map(item => item.label)).toEqual(["foo_schema.foo", "foo_schema.bar", "other.foo_table"]);
  });
  it.each([
    ["sqlserver", "analytics.table_099999", "value"],
    ["postgresql", '"table_099999"', '"value"'],
    ["mysql", "analytics.table_099999", "value"],
    ["mariadb", "analytics.table_099999", "value"],
    ["sqlite", "table_099999", "value"],
    ["databricks", "table_099999", "value"],
  ])("shares names without borrowing cached insertion quoting from another dialect: %s", (dbType, table, column) => {
    const scoped = { ...large, dbType };
    expect(complete("FROM table_099999|", scoped)[0].insert_text).toBe(table);
    expect(complete("SELECT t.va| FROM table_099999 t", scoped)[0].insert_text).toBe(column);
    expect(complete("FROM main.analytics.table_099999|", scoped)[0].insert_text).toBe(dbType==="postgresql" ? '"table_099999"' : "table_099999");
  });
  it("continues to resolve SQL columns after the live Python namespace changes", () => {
    expect(complete("SELECT t.va| FROM table_099999 t", large).map(item => item.label)).toEqual(["value"]);
    const updated: CompletionContext = { ...large, namespaceVersion: 2, variables: [{ name: "python_result", type: "DataFrame", columns: ["unrelated"] }] };
    expect(complete("SELECT t.va| FROM table_099999 t", updated).map(item => item.label)).toEqual(["value"]);
    expect(complete("FROM main.analytics.table_099999|", updated)[0].label).toBe("table_099999");
  });
  it("retains schema and catalog ambiguity rules when the same metadata is reused for another block scope", () => {
    const shared = {
      "production.public.sales": { name: "sales", catalog: "production", schema: "public", columns: [{ name: "production_value" }] },
      "sandbox.public.sales": { name: "sales", catalog: "sandbox", schema: "public", columns: [{ name: "sandbox_value" }] },
      "production.audit.sales": { name: "sales", catalog: "production", schema: "audit", columns: [{ name: "audit_value" }] },
    };
    const base: CompletionContext = { variables: [], tables: Object.keys(shared), dbType: "databricks", schemaSnapshot: { tables: shared } };
    expect(complete("SELECT s.| FROM sales s", { ...base, database: "production", schema: "public" }).map(item => item.label)).toEqual(["production_value"]);
    expect(complete("SELECT s.| FROM sales s", { ...base, database: "sandbox", schema: "public" }).map(item => item.label)).toEqual(["sandbox_value"]);
    expect(complete("SELECT s.| FROM sales s", { ...base, database: "production", schema: "audit" }).map(item => item.label)).toEqual(["audit_value"]);
    expect(complete("SELECT s.| FROM sales s", base)).toEqual([]);
  });
  it("does not resolve a case-folded ambiguous name or change PostgreSQL quoted identity", () => {
    const shared = {
      "public.IdTable": { name: "IdTable", schema: "public", columns: [{ name: "upper_only" }] },
      "public.idtable": { name: "idtable", schema: "public", columns: [{ name: "lower_only" }] },
    };
    const base: CompletionContext = { variables: [], tables: Object.keys(shared), schema: "public", schemaSnapshot: { tables: shared } };
    expect(complete("SELECT s.| FROM IDTABLE s", { ...base, dbType: "sqlserver" })).toEqual([]);
    expect(complete("SELECT s.| FROM IDTABLE s", { ...base, dbType: "postgresql" }).map(item => item.label)).toEqual(["lower_only"]);
    expect(complete('SELECT s.| FROM "IdTable" s', { ...base, dbType: "postgresql" }).map(item => item.label)).toEqual(["upper_only"]);
  });
  it("updates indexes when an immutable catalog snapshot is replaced after DDL", () => {
    const before: CompletionContext = { variables: [], tables: ["public.original"], schema: "public", dbType: "postgresql",
      schemaSnapshot: { tables: { "public.original": { name: "original", schema: "public", columns: [{ name: "original_value" }] } } } };
    expect(complete("SELECT s.| FROM original s", before).map(item => item.label)).toEqual(["original_value"]);
    const after: CompletionContext = { ...before, tables: ["public.renamed"], schemaSnapshot: { tables: { "public.renamed": { name: "renamed", schema: "public", columns: [{ name: "new_value" }] } } } };
    expect(complete("FROM orig|", after)).toEqual([]); expect(complete("SELECT s.| FROM renamed s", after).map(item => item.label)).toEqual(["new_value"]);
  });
  it("treats prototype-like fallback names as SQL identifiers rather than inherited objects", () => {
    const bare: CompletionContext = { variables: [], tables: ["constructor", "toString", "__proto__"], dbType: "sqlite", schemaSnapshot: { tables: {} } };
    expect(complete("FROM con|", bare)[0].insert_text).toBe('constructor');
    expect(complete("FROM toS|", bare)[0].insert_text).toBe('toString');
    expect(complete("FROM __pro|", bare)[0].insert_text).toBe('__proto__');
    expect(complete("constructor.|", bare)).toEqual([]);
    const defined = Object.fromEntries(["constructor", "toString", "__proto__"].map(name => [name, { name, columns: [{ name: "actual_column" }] }]));
    const explicit: CompletionContext = { ...bare, schemaSnapshot: { tables: defined } };
    for (const name of bare.tables) expect(complete(`${name}.|`, explicit).map(item => item.label)).toEqual(["actual_column"]);
  });
});
