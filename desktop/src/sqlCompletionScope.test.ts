import { describe, expect, it } from "vitest";
import { completionSite, localCompletions } from "./editorCompletions";
import type { CompletionContext } from "./editorLanguage";
import { sqlCompletionScope } from "./sqlCompletionScope";

const context: CompletionContext = { variables: [], tables: ["main.sales", "main.customers"], schemaSnapshot: {
  db_type: "sqlite", current_schema: "main", tables: {
    "main.sales": { name: "sales", schema: "main", columns: [{ name: "value" }, { name: "shared" }] },
    "main.customers": { name: "customers", schema: "main", columns: [{ name: "customer_name" }, { name: "shared" }] },
  },
} };
function complete(marked: string, supplied = context) {
  const cursor = marked.indexOf("|"), code = marked.replace("|", ""), before = code.slice(0, cursor), line = before.split("\n").at(-1)!;
  return localCompletions("sql", completionSite("sql", line, line.length + 1, supplied.schemaSnapshot?.db_type), supplied, before, [], code, cursor);
}

describe("SQL completion query scopes", () => {
  it("offers loaded columns immediately at SELECT, WHERE, ON and ORDER BY", () => {
    for (const marked of ["SELECT va| FROM sales s", "SELECT * FROM sales s WHERE va|", "SELECT * FROM sales s ORDER BY va|", "SELECT * FROM sales s JOIN customers c ON va|"]) {
      expect(complete(marked)).toContainEqual(expect.objectContaining({ label: "value", kind: "column", insert_text: '"value"' }));
    }
    expect(complete("SELECT * FROM sales s JOIN customers c ON customer_n|")).toContainEqual(expect.objectContaining({ label: "c.customer_name", insert_text: '"c"."customer_name"' }));
  });
  it("keeps alias suggestions within the statement at the actual cursor", () => {
    expect(complete("SELECT s.| FROM sales s; SELECT s.value FROM customers s").map(item => item.label)).toEqual(["value", "shared"]);
    expect(complete("SELECT s.value FROM sales s; SELECT s.| FROM customers s").map(item => item.label)).toEqual(["customer_name", "shared"]);
  });
  it("lets the innermost query shadow an outer alias without losing correlated aliases", () => {
    expect(complete("SELECT (SELECT s.| FROM sales s) FROM customers s").map(item => item.label)).toEqual(["value", "shared"]);
    expect(complete("SELECT (SELECT c.| FROM sales s) FROM customers c").map(item => item.label)).toEqual(["customer_name", "shared"]);
  });
  it("does not infer a physical table for a CTE shadowing its name", () => {
    expect(complete("WITH sales AS (SELECT 1 AS planned) SELECT s.| FROM sales s")).toEqual([]);
  });
  it.each([
    "SELECT sales.| FROM (SELECT customer_name FROM main.customers) sales",
    "SELECT sales.| FROM main.customers c JOIN (SELECT customer_name FROM main.customers) AS sales ON TRUE",
    "SELECT sales.| FROM main.customers c, (SELECT customer_name FROM main.customers) sales",
  ])("reserves the derived alias before runtime inference for %s", marked => {
    expect(complete(marked)).toEqual([]);
  });
  it("resolves comma-separated physical sources without mixing SELECT expressions into bindings", () => {
    expect(complete("SELECT 1, c.| FROM main.sales s, main.customers c").map(item => item.label)).toEqual(["customer_name", "shared"]);
  });
  it("treats an alias as more specific than an identically named physical table", () => {
    expect(complete("SELECT sales.| FROM customers sales").map(item => item.label)).toEqual(["customer_name", "shared"]);
  });
  it.each([['"', '"'], ["[", "]"], ["`", "`"]])("recovers a partial identifier with %s quotes without swallowing FROM", (quote, close) => {
    expect(complete(`SELECT s.${quote}va| FROM sales s JOIN customers c ON 1=1`).map(item => item.label)).toEqual(["value"]);
    expect(complete(`SELECT s.${quote}va|lue${close} FROM sales s JOIN customers c ON 1=1`).map(item => item.label)).toEqual(["value"]);
  });
  it("ignores comments, string literals and their semicolons", () => {
    expect(complete("SELECT s.| /* ; FROM customers s */ FROM sales s WHERE value='; JOIN customers s'").map(item => item.label)).toEqual(["value", "shared"]);
    expect(complete("SELECT /* s.| */ FROM sales s")).toEqual([]);
    const code = "SELECT $text$; FROM customers s$text$, s. FROM sales s";
    expect(sqlCompletionScope(code, code.indexOf("s. FROM") + 2, "postgresql").relations[0].parts[0].name).toBe("sales");
  });
  it("distinguishes ordinary PostgreSQL strings from E strings throughout the editor pipeline", () => {
    const supplied: CompletionContext = { ...context, schemaSnapshot: { ...context.schemaSnapshot, db_type: "postgresql" } };
    for (const marked of ["SELECT 'C:\\' AS folder, s.| FROM main.sales s", "SELECT E'a\\'b' AS marker, s.| FROM main.sales s"]) {
      expect(complete(marked, supplied).map(item => item.label)).toEqual(["value", "shared"]);
    }
    expect(complete("SELECT E'a\\'s.va| FROM main.sales s", supplied)).toEqual([]);
  });
  it("preserves MySQL and MariaDB backslash escapes in completed strings", () => {
    for (const db_type of ["mysql", "mariadb"]) {
      const supplied: CompletionContext = { ...context, schemaSnapshot: { ...context.schemaSnapshot, db_type } };
      expect(complete("SELECT 'a\\'b' AS marker, s.| FROM main.sales s", supplied).map(item => item.label)).toEqual(["value", "shared"]);
    }
  });
  it("resolves unqualified tables using the actual metadata default and current catalog", () => {
    const supplied: CompletionContext = { variables: [], tables: [], schemaSnapshot: { db_type: "databricks", database: "current", current_schema: "chosen", tables: {
      "foreign.chosen.sales": { name: "sales", schema: "chosen", catalog: "foreign", columns: [{ name: "wrong_catalog" }] },
      "current.other.sales": { name: "sales", schema: "other", catalog: "current", columns: [{ name: "wrong_schema" }] },
      "current.chosen.sales": { name: "sales", schema: "chosen", catalog: "current", columns: [{ name: "value" }] },
    } } };
    expect(complete("SELECT s.| FROM sales s", supplied).map(item => item.label)).toEqual(["value"]);
  });
  it("treats SQL Server omitted schema paths and batches as context boundaries", () => {
    const supplied: CompletionContext = { ...context, schemaSnapshot: { db_type: "sqlserver", tables: {
      "db.dbo.sales": { name: "sales", schema: "dbo", catalog: "db", columns: [{ name: "value" }] },
      "db.dbo.customers": { name: "customers", schema: "dbo", catalog: "db", columns: [{ name: "customer_name" }] },
    } } };
    expect(complete("SELECT s.| FROM db..sales s\nGO\nSELECT s.value FROM db..customers s", supplied).map(item => item.label)).toEqual(["value"]);
  });
});
