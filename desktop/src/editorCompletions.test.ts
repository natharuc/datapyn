import { describe, expect, it } from "vitest";
import { completionInsertion, completionSite, filterCompletions, localCompletions, pythonSymbols } from "./editorCompletions";
import type { CompletionContext } from "./editorLanguage";

const context: CompletionContext = {
  variables: [{ name: "frame", type: "DataFrame", columns: ["title", "total", "customer name", 'a"b', "path\\file"] }],
  tables: ["main.sales", "main.customers"], schema: "main",
  schemaSnapshot: { db_type: "sqlite", tables: {
    "main.sales": { name: "sales", schema: "main", columns: [{ name: "title", data_type: "TEXT" }, { name: "amount", type: "REAL" }] },
    "main.customers": { name: "customers", schema: "main", columns: [{ name: "name" }] },
  } },
  globalImports: "import pandas as pd\nimport numpy as np\nfrom math import sqrt as square_root",
  preamble: "def calculate_total():\n    return 42\nother_frame = pd.DataFrame()",
};
const site = (language: "python" | "sql", line: string, marker = "|") => {
  const offset = line.indexOf(marker); return completionSite(language, line.replace(marker, ""), offset + 1);
};

describe("completion ranges and insertion", () => {
  it("replaces the entire identifier when the cursor is in its middle", () => {
    expect(site("python", "pri|nt")).toMatchObject({ prefix: "pri", startColumn: 1, endColumn: 6 });
    expect(site("sql", "SELECT ord|ers FROM orders")).toMatchObject({ prefix: "ord", startColumn: 8, endColumn: 14 });
  });
  it("keeps Monaco UTF-16 columns for non-BMP characters before the identifier", () => {
    expect(site("python", 'print("😀"); pri|nt')).toMatchObject({ prefix: "pri", startColumn: 14, endColumn: 19 });
  });
  it.each(['"', "[", "`"])("owns an existing %s identifier pair without touching its qualifier", quote => {
    const close = quote === "[" ? "]" : quote;
    const result = site("sql", `SELECT s.${quote}ti|tle${close} FROM sales s`);
    expect(result).toMatchObject({ prefix: "ti", member: "s", startColumn: 10, endColumn: 17, quote });
    expect(completionInsertion({ label: "title", insert_text: '"title"' }, result, "sql")).toBe(`${quote}title${close}`);
  });
  it("decodes already escaped SQL identifier text before quoting it once", () => {
    for (const [quote, label, text, expected] of [['"', 'a"b', '"a""b"', '"a""b"'], ["[", "a]b", "[a]]b]", "[a]]b]"], ["`", "a`b", "`a``b`", "`a``b`"]]) {
      expect(completionInsertion({ label, insert_text: text }, { prefix: "a", startColumn: 1, endColumn: 4, quote }, "sql")).toBe(expected);
    }
  });
  it("retains qualified parts while converting the current quote style", () => {
    expect(completionInsertion({ label: "public.User", insert_text: 'public."User"' }, { prefix: "", startColumn: 1, endColumn: 1, quote: "[" }, "sql")).toBe("[public].[User]");
    expect(completionInsertion({ label: "a.b", insert_text: '"a.b"' }, { prefix: "", startColumn: 1, endColumn: 1, quote: "[" }, "sql")).toBe("[a.b]");
  });
  it("replaces dataframe string contents while preserving the existing closing quote", () => {
    expect(site("python", 'frame["cust|omer name"]')).toMatchObject({ stringColumn: true, member: "frame", prefix: "cust", startColumn: 8, endColumn: 21 });
  });
  it("escapes Python column labels once, including quotes, backslashes and control characters", () => {
    const result = site("python", 'frame["a|b"]');
    expect(completionInsertion({ label: 'a"b', kind: "field", insert_text: 'a\\"b' }, result, "python")).toBe('a\\"b');
    expect(completionInsertion({ label: "path\\file\nnext", kind: "field" }, result, "python")).toBe("path\\\\file\\nnext");
  });
  it("decodes a typed Python escaped prefix for column filtering", () => {
    expect(site("python", 'frame["a\\"|b"]')).toMatchObject({ prefix: 'a"', member: "frame", stringColumn: true });
    expect(site("python", 'frame["path\\\\|file"]')).toMatchObject({ prefix: "path\\", member: "frame" });
  });
  it("replaces escaped quote suffixes entirely while retaining the actual closing delimiter", () => {
    const python = 'frame["a\\"b"]';
    expect(completionSite("python", python, 9)).toMatchObject({ stringColumn: true, startColumn: 8, endColumn: 12 });
    const sql = 'SELECT s."a""b" FROM sales s';
    expect(completionSite("sql", sql, 12)).toMatchObject({ quote: '"', startColumn: 10, endColumn: 16 });
    expect(site("sql", "SELECT s.[a|]]b] FROM sales s")).toMatchObject({ quote: "[", startColumn: 10, endColumn: 16 });
  });
  it("does not suggest names inside ordinary strings or line comments", () => {
    for (const line of ['print("cust|omer")', "# frame.t|", "text = 'cust|omer'"]) expect(site("python", line).blocked).toBe(true);
    for (const line of ["SELECT 'cust|omer'", "-- s.t|"]) expect(site("sql", line).blocked).toBe(true);
  });
});

describe("instant local completion scope", () => {
  it("includes real Python variables, imports, declarations, builtins and keywords", () => {
    const items = localCompletions("python", site("python", "|"), context, "", pythonSymbols("local_value = 1\nclass Thing:\n    pass"));
    expect(items.map(item => item.label)).toEqual(expect.arrayContaining(["frame", "pd", "np", "square_root", "calculate_total", "other_frame", "local_value", "Thing", "print", "False", "return"]));
  });
  it("keeps Python case sensitive and SQL prefix matching case insensitive", () => {
    expect(filterCompletions([{ label: "False" }, { label: "frame" }], "f", "python")).toEqual([{ label: "frame" }]);
    expect(localCompletions("sql", site("sql", "sel|"), context, "sel").map(item => item.label)).toContain("SELECT");
  });
  it("limits a dataframe dot to valid column identifiers without unrelated keywords or variables", () => {
    const items = localCompletions("python", site("python", "frame.|"), context, "frame.");
    expect(items.map(item => item.label)).toEqual(["title", "total"]);
    expect(localCompletions("python", site("python", "unknown.|"), context, "unknown.")).toEqual([]);
  });
  it("offers dataframe columns with spaces inside string indexing", () => {
    expect(localCompletions("python", site("python", 'frame["cust|"]'), context, 'frame["cust').map(item => item.label)).toEqual(["customer name"]);
  });
  it("excludes Python hard keywords from dot fields while retaining soft keywords and all bracket fields", () => {
    const scoped:CompletionContext={variables:[{name:"frame",type:"DataFrame",columns:["class","for","None","match","case","valid"]}],tables:[]};
    expect(localCompletions("python",site("python","frame.|"),scoped,"frame.").map(item=>item.label)).toEqual(["match","case","valid"]);
    expect(localCompletions("python",site("python",'frame["|"]'),scoped,'frame["').map(item=>item.label)).toEqual(["class","for","None","match","case","valid"]);
  });
  it("resolves a simple alias using the actual qualified schema snapshot even with FROM below the cursor", () => {
    const source = "SELECT s.t\nFROM sales AS s";
    expect(localCompletions("sql", site("sql", "SELECT s.t|"), context, "SELECT s.t", [], source).map(item => item.label)).toEqual(["title"]);
  });
  it("resolves an unqualified table in the selected schema and never chooses an ambiguous other schema", () => {
    const scoped: CompletionContext = { ...context, tables: ["main.sales", "other.sales"], schemaSnapshot: { tables: { ...context.schemaSnapshot?.tables, "other.sales": { name: "sales", schema: "other", columns: [{ name: "wrong" }] } } } };
    expect(localCompletions("sql", site("sql", "sales.|"), scoped, "sales.").map(item => item.label)).toEqual(["title", "amount"]);
    expect(localCompletions("sql", site("sql", "sales.|"), { ...scoped, schema: undefined }, "sales.")).toEqual([]);
  });
  it("preserves quoted PostgreSQL table case and folds only unquoted identifiers", () => {
    const scoped:CompletionContext={variables:[],tables:["public.IdTable","public.idtable"],schema:"public",schemaSnapshot:{db_type:"postgresql",tables:{"public.IdTable":{name:"IdTable",schema:"public",columns:[{name:"upper_only"}]},"public.idtable":{name:"idtable",schema:"public",columns:[{name:"lower_only"}]}}}};
    for(const [name,expected] of [['public."IdTable"',"upper_only"],['"IdTable"',"upper_only"],["public.idtable","lower_only"],["idtable","lower_only"],["public.IdTable","lower_only"],["IDTABLE","lower_only"]])expect(localCompletions("sql",site("sql",`${name}.|`),scoped,`${name}.`).map(item=>item.label)).toEqual([expected]);
    for(const name of ['public."IDTABLE"','"IDTABLE"'])expect(localCompletions("sql",site("sql",`${name}.|`),scoped,`${name}.`)).toEqual([]);
    const source='SELECT t. FROM public."IdTable" t';
    expect(localCompletions("sql",site("sql","SELECT t.|"),scoped,"SELECT t.",[],source).map(item=>item.label)).toEqual(["upper_only"]);
    expect(localCompletions("sql",site("sql","SELECT t.|"),scoped,"SELECT t.",[],source.replace('"IdTable"','IdTable')).map(item=>item.label)).toEqual(["lower_only"]);
    const onlyUpper:CompletionContext={...scoped,tables:["public.IdTable"],schemaSnapshot:{...scoped.schemaSnapshot,tables:{"public.IdTable":scoped.schemaSnapshot!.tables!["public.IdTable"]}}};
    expect(localCompletions("sql",site("sql","SELECT t.|"),onlyUpper,"SELECT t.",[],source.replace('"IdTable"','"idtable"'))).toEqual([]);
  });
  it("decodes escaped SQL table identifiers in aliases without inventing another relation", () => {
    for(const [db_type,quoted,name] of [["postgresql",'"a""b"','a"b'],["sqlserver","[a]]b]","a]b"],["mysql","`a``b`","a`b"],["postgresql",'"a\'b"',"a'b"],["postgresql",'"a--b"',"a--b"]]) {
      const scoped:CompletionContext={variables:[],tables:[`public.${name}`,"public.ab"],schema:"public",schemaSnapshot:{db_type,tables:{[`public.${name}`]:{name,schema:"public",columns:[{name:"literal_only"}]},"public.ab":{name:"ab",schema:"public",columns:[{name:"wrong"}]}}}};
      expect(localCompletions("sql",site("sql","SELECT t.|"),scoped,"SELECT t.",[],`SELECT t. FROM public.${quoted} t`).map(item=>item.label)).toEqual(["literal_only"]);
      expect(localCompletions("sql",site("sql",`public.${quoted}.|`),scoped,`public.${quoted}.`).map(item=>item.label)).toEqual(["literal_only"]);
    }
  });
  it("refuses ambiguous folded table names on case-insensitive connections", () => {
    const scoped:CompletionContext={variables:[],tables:["main.IdTable","main.idtable"],schemaSnapshot:{db_type:"sqlite",tables:{"main.IdTable":{name:"IdTable",columns:[{name:"upper_only"}]},"main.idtable":{name:"idtable",columns:[{name:"lower_only"}]}}}};
    expect(localCompletions("sql",site("sql","main.IDTABLE.|"),scoped,"main.IDTABLE.")).toEqual([]);
  });
  it("provides schema-qualified table tails after a dot without keyword pollution", () => {
    expect(localCompletions("sql", site("sql", "FROM main.c|"), context, "FROM main.c").map(item => item.label)).toEqual(["customers"]);
  });
  it("restricts a FROM relation to table names", () => {
    const items = localCompletions("sql", site("sql", "SELECT * FROM |"), context, "SELECT * FROM ");
    expect(items.every(item => item.kind === "table")).toBe(true);
  });
  it("filters before applying a bound so late alphabet names remain reachable in large schemas", () => {
    const large: CompletionContext = { variables: [], tables: [...Array.from({ length: 10_000 }, (_, i) => `table_${i}`), "zebra"] };
    expect(localCompletions("sql", site("sql", "FROM zeb|"), large, "FROM zeb").map(item => item.label)).toEqual(["zebra"]);
    expect(localCompletions("sql", site("sql", "|"), large, "")).toHaveLength(500);
  });
  it("quotes reserved names, PostgreSQL case and punctuation for the connection dialect", () => {
    for (const [db_type, name, expected] of [["sqlserver", "select", "[select]"], ["sqlite", "select", '"select"'], ["mysql", "select", "`select`"], ["postgresql", "UserData", '"UserData"'], ["sqlserver", "customer name", "[customer name]"]]) {
      const scoped: CompletionContext = { variables: [], tables: [name], schemaSnapshot: { db_type } };
      expect(localCompletions("sql", site("sql", "|"), scoped, "").find(item => item.kind === "table")?.insert_text).toBe(expected);
    }
  });
  it("quotes every local SQL identifier before remote enrichment, including dialect-specific reserved words", () => {
    for(const [db_type,expectedTable,expectedColumn] of [["postgresql",'"public"."normal"','"authorization"'],["sqlite",'"public"."normal"','"authorization"'],["sqlserver","[public].[normal]","[authorization]"],["mssql","[public].[normal]","[authorization]"],["mysql","`public`.`normal`","`authorization`"],["mariadb","`public`.`normal`","`authorization`"],["databricks","`public`.`normal`","`authorization`"]]) {
      const scoped:CompletionContext={variables:[],tables:["public.normal"],schemaSnapshot:{db_type,tables:{"public.normal":{name:"normal",schema:"public",columns:[{name:"authorization"}]}}}};
      expect(localCompletions("sql",site("sql","FROM |"),scoped,"FROM ")[0].insert_text).toBe(expectedTable);
      expect(localCompletions("sql",site("sql","normal.|"),scoped,"normal.")[0].insert_text).toBe(expectedColumn);
    }
  });
  it("treats metadata object names containing a dot as a single identifier before remote enrichment", () => {
    const scoped:CompletionContext={variables:[],tables:["main.a.b"],schemaSnapshot:{db_type:"sqlite",tables:{"main.a.b":{name:"a.b",schema:"main",columns:[]}}}};
    expect(localCompletions("sql",site("sql","FROM |"),scoped,"FROM ")[0].insert_text).toBe('"main"."a.b"');
    expect(localCompletions("sql",site("sql","FROM main.|"),scoped,"FROM main.")[0].insert_text).toBe('"a.b"');
    const dottedSchema:CompletionContext={...scoped,tables:["my.schema.a.b"],schemaSnapshot:{db_type:"sqlite",tables:{"my.schema.a.b":{name:"a.b",schema:"my.schema",columns:[]}}}};
    expect(localCompletions("sql",site("sql","FROM |"),dottedSchema,"FROM ")[0].insert_text).toBe('"my.schema"."a.b"');
  });
  it("offers literal same-language sibling code while preserving dollar signs and excluding markdown", () => {
    const code = 'price = "$100"\nprint(price)';
    const scoped: CompletionContext = { variables: [], tables: [], siblings: [{ name: "price_example", code, language: "python" }, { name: "sql_example", code: "SELECT 1", language: "sql" }, { name: "notes", code: "# notes", language: "python", cellType: "markdown" }] };
    const items = localCompletions("python", site("python", "price_|"), scoped, "price_");
    expect(items).toHaveLength(1);expect(items[0]).toMatchObject({ label: "block: price_example", filterText: "price_example", kind: "snippet", is_snippet: false, insert_text: `${code}\n` });
  });
  it("does not leak names from another session into local completion", () => {
    const other: CompletionContext = { variables: [{ name: "secret_other_session", type: "str" }], tables: [] };
    expect(localCompletions("python", site("python", "secret_|"), context, "secret_")).toEqual([]);
    expect(localCompletions("python", site("python", "secret_|"), other, "secret_").map(item => item.label)).toEqual(["secret_other_session"]);
  });
});
