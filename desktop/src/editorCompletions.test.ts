import { describe, expect, it } from "vitest";
import { completionInsertion, completionSite, contextualCompletions, filterCompletions, localCompletions, pythonSymbols } from "./editorCompletions";
import { dataframeMembers } from "./dataframeMembers";
import { mergeCompletions } from "./editorLanguage";
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
  it("prefers a temporary shadow for unqualified SQL names and preserves explicit schemas", () => {
    const scoped:CompletionContext={variables:[],tables:[],schema:"main",schemaSnapshot:{db_type:"sqlite",tables:{
      "main.sales":{name:"sales",schema:"main",columns:[{name:"permanent_only"}]},
      "temp.sales":{name:"sales",schema:"temp",temporary:true,columns:[{name:"temporary_only"}]},
    }}};
    expect(localCompletions("sql",site("sql","sales.|"),scoped,"sales.").map(item=>item.label)).toEqual(["temporary_only"]);
    expect(localCompletions("sql",site("sql","main.sales.|"),scoped,"main.sales.").map(item=>item.label)).toEqual(["permanent_only"]);
    expect(localCompletions("sql",site("sql","SELECT s.|"),scoped,"SELECT s.",[],"SELECT s. FROM sales s").map(item=>item.label)).toEqual(["temporary_only"]);
  });
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
  it.each([["sqlserver","[customers]"],["mysql","`customers`"],["mariadb","`customers`"],["databricks","`customers`"],["postgresql",'"customers"'],["sqlite",'"customers"']])("shows and inserts a short table name in the focused %s namespace",(dbType,expected)=>{
    const database="warehouse",schema=["mysql","mariadb"].includes(dbType)?database:"main",key=`${schema}.customers`;
    const scoped:CompletionContext={variables:[],tables:[key],dbType,database,schema:["mysql","mariadb"].includes(dbType)?undefined:schema,
      schemaSnapshot:{db_type:dbType,database,current_schema:schema,tables:{[key]:{name:"customers",schema,columns:[]}}}};
    expect(localCompletions("sql",site("sql","FROM cust|"),scoped,"FROM cust")).toEqual([expect.objectContaining({label:"customers",insert_text:expected,detail:key})]);
  });
  it("normalizes remote table enrichment to the same focused label and insertion",()=>{
    const remote=[{label:"main.sales",kind:"table",insert_text:'"main"."sales"',documentation:"Sales table"}];
    const local=localCompletions("sql",site("sql","FROM sa|"),context,"FROM sa");
    const normalized=contextualCompletions(remote,site("sql","FROM sa|"),context,"sql");
    expect(normalized[0]).toMatchObject({label:"sales",insert_text:'"sales"',documentation:"Sales table",detail:"main.sales"});
    expect(mergeCompletions(normalized,local,"sql")).toHaveLength(1);
  });
  it.each([["sqlserver","[c].[id]"],["mysql","`c`.`id`"],["mariadb","`c`.`id`"],["databricks","`c`.`id`"],["postgresql",'"c"."id"'],["sqlite",'"c"."id"']])("qualifies ambiguous %s JOIN fields without suggesting an invalid bare column",(dbType,insertion)=>{
    const scoped:CompletionContext={variables:[],tables:[],schema:"main",dbType,schemaSnapshot:{tables:{
      "main.customers":{name:"customers",schema:"main",columns:[{name:"id"},{name:"customer_name"}]},
      "main.orders":{name:"orders",schema:"main",columns:[{name:"id"},{name:"order_total"}]},
    }}};
    const query=site("sql","SELECT i|"),source="SELECT i FROM customers c JOIN orders o ON c.id=o.id";
    const local=localCompletions("sql",query,scoped,"SELECT i",[],source);
    expect(local.filter(item=>item.kind==="column").map(item=>item.label)).toEqual(["c.id","o.id"]);
    expect(local[0].insert_text).toBe(insertion);
    const enriched=contextualCompletions([{label:"id",kind:"column",insert_text:"id",documentation:"Identifier"}],query,scoped,"sql",local);
    expect(mergeCompletions(enriched,local,"sql").filter(item=>item.kind==="column").map(item=>item.label)).toEqual(["c.id","o.id"]);
    expect(localCompletions("sql",site("sql","SELECT customer_n|"),scoped,"SELECT customer_n",[],source.replace("SELECT i","SELECT customer_n"))[0].label).toBe("customer_name");
  });
  it("qualifies known columns when a derived table or CTE has an inferred output",()=>{
    const scoped:CompletionContext={variables:[],tables:[],dbType:"sqlite",schema:"main",schemaSnapshot:{tables:{"main.sales":{name:"sales",schema:"main",columns:[{name:"shared"}]}}}};
    for(const source of ["SELECT shared FROM sales s JOIN (SELECT 1 AS shared) d ON 1=1","WITH d AS (SELECT 1 AS shared) SELECT shared FROM sales s JOIN d ON 1=1"]){
      const before=source.slice(0,source.indexOf("shared FROM")+6),query=site("sql","SELECT shared|");
      const items=localCompletions("sql",query,scoped,before,[],source,before.length);
      expect(items.filter(item=>item.kind==="column")).toEqual([expect.objectContaining({label:"s.shared",filterText:"shared",insert_text:'"s"."shared"'})]);
      expect(contextualCompletions([{label:"shared",kind:"column"}],query,scoped,"sql",items)[0]).toMatchObject({label:"s.shared",insert_text:'"s"."shared"'});
    }
  });
  it("qualifies known columns until every JOIN table has loaded columns, then keeps unique names short",()=>{
    for(const columns of [undefined,[]]){
      const scoped:CompletionContext={variables:[],tables:[],dbType:"sqlite",schema:"main",schemaSnapshot:{tables:{
        "main.sales":{name:"sales",schema:"main",columns:[{name:"shared"}]},"main.pending":{name:"pending",schema:"main",columns},
      }}};
      const source="SELECT shared FROM sales s JOIN pending p ON 1=1",query=site("sql","SELECT shared|");
      expect(localCompletions("sql",query,scoped,"SELECT shared",[],source).filter(item=>item.kind==="column")).toEqual([expect.objectContaining({label:"s.shared",insert_text:'"s"."shared"'})]);
      const ready:CompletionContext={...scoped,schemaSnapshot:{tables:{...scoped.schemaSnapshot!.tables,"main.pending":{name:"pending",schema:"main",columns:[{name:"other"}]}}}};
      expect(localCompletions("sql",query,ready,"SELECT shared",[],source).filter(item=>item.kind==="column")).toEqual([expect.objectContaining({label:"shared",insert_text:'"shared"'})]);
    }
  });
  it("keeps explicit qualifier tails and out-of-scope schema/catalog names",()=>{
    const scoped:CompletionContext={variables:[],tables:[],dbType:"databricks",database:"warehouse",schema:"finance",schemaSnapshot:{tables:{
      "warehouse.finance.orders":{name:"orders",schema:"finance",catalog:"warehouse",columns:[]},
      "warehouse.reports.orders":{name:"orders",schema:"reports",catalog:"warehouse",columns:[]},
      "archive.finance.orders":{name:"orders",schema:"finance",catalog:"archive",columns:[]},
    }}};
    const items=localCompletions("sql",site("sql","FROM ord|"),scoped,"FROM ord");
    expect(items.map(item=>[item.label,item.insert_text])).toEqual([
      ["orders","`orders`"],["reports.orders","`reports`.`orders`"],["archive.finance.orders","`archive`.`finance`.`orders`"],
    ]);
    expect(localCompletions("sql",site("sql","FROM warehouse.finance.ord|"),scoped,"FROM warehouse.finance.ord")[0]).toMatchObject({label:"orders",insert_text:"`orders`"});
  });
  it("preserves PostgreSQL quoted schema identity for local and delayed remote table suggestions",()=>{
    const scoped:CompletionContext={variables:[],tables:[],dbType:"postgresql",database:"warehouse",schema:"analytics",schemaSnapshot:{tables:{
      "Analytics.UpperOrders":{name:"UpperOrders",schema:"Analytics",columns:[]},
      "analytics.lower_orders":{name:"lower_orders",schema:"analytics",columns:[]},
      "Analytics.shared":{name:"shared",schema:"Analytics",columns:[]},
      "analytics.shared":{name:"shared",schema:"analytics",columns:[]},
    }}};
    for(const [qualifier,expected] of [['"Analytics"',["UpperOrders","shared"]],["analytics",["lower_orders","shared"]],["ANALYTICS",["lower_orders","shared"]],['"analytics"',["lower_orders","shared"]]] as const){
      const before=`FROM ${qualifier}.`,query=site("sql",before+"|");
      const local=localCompletions("sql",query,scoped,before);
      expect(local.map(item=>item.label)).toEqual(expected);
      expect(local[0].insert_text).toBe(`"${expected[0]}"`);
      const remote=contextualCompletions([{label:"Analytics.UpperOrders",kind:"table"},{label:"analytics.lower_orders",kind:"table"},{label:"shared",kind:"table"}],query,scoped,"sql",local);
      expect(remote.map(item=>item.label)).toEqual(expected);
      expect(remote.find(item=>item.label==="shared")?.detail).toBe(`${qualifier==='"Analytics"'?"Analytics":"analytics"}.shared`);
    }
  });
  it("uses the selected MySQL database to disambiguate equal table names without a separate schema",()=>{
    const scoped:CompletionContext={variables:[],tables:[],dbType:"mysql",database:"green",schemaSnapshot:{tables:{
      "green.acesso":{name:"acesso",schema:"green",columns:[{name:"green_id"}]},
      "audit.acesso":{name:"acesso",schema:"audit",columns:[{name:"audit_id"}]},
    }}};
    expect(localCompletions("sql",site("sql","FROM ace|"),scoped,"FROM ace").map(item=>item.label)).toEqual(["acesso","audit.acesso"]);
    expect(localCompletions("sql",site("sql","acesso.|"),scoped,"acesso.").map(item=>item.label)).toEqual(["green_id"]);
  });
  it("retains qualification for an object shadowed by a temporary table",()=>{
    const scoped:CompletionContext={variables:[],tables:[],dbType:"sqlite",schema:"main",schemaSnapshot:{tables:{
      "main.sales":{name:"sales",schema:"main",columns:[]},"temp.sales":{name:"sales",schema:"temp",temporary:true,columns:[]},
    }}};
    expect(localCompletions("sql",site("sql","FROM sa|"),scoped,"FROM sa").map(item=>[item.label,item.insert_text])).toEqual([["main.sales",'"main"."sales"'],["sales",'"sales"']]);
  });
  it("matches embedded table words after prefix matches and keeps namespace restrictions",()=>{
    const scoped:CompletionContext={variables:[],tables:["main.gecon_ft_movimentos_premio","main.movimentocobranca","other.movimentos"],dbType:"sqlite",schema:"main"};
    expect(localCompletions("sql",site("sql","FROM movimento|"),scoped,"FROM movimento").map(item=>item.label)).toEqual(["main.movimentocobranca","other.movimentos","main.gecon_ft_movimentos_premio"]);
    expect(localCompletions("sql",site("sql","FROM main.movimento|"),scoped,"FROM main.movimento").map(item=>item.label)).toEqual(["movimentocobranca","gecon_ft_movimentos_premio"]);
    expect(filterCompletions([{label:"movimento"},{label:"gecon_ft_movimentos_premio"},{label:"orders"}],"movimento","sql").map(item=>item.label)).toEqual(["movimento","gecon_ft_movimentos_premio"]);
  });
  it("finds an embedded word in the final object of a 100k catalog and reuses bounded cached entries",()=>{
    const scoped:CompletionContext={variables:[],tables:[...Array.from({length:100_000},(_,index)=>`main.table_${index}`),"main.gecon_ft_movimentos_premio"]};
    const query=site("sql","FROM movimento|"),first=localCompletions("sql",query,scoped,"FROM movimento");
    expect(first.map(item=>item.label)).toEqual(["main.gecon_ft_movimentos_premio"]);
    expect(localCompletions("sql",query,{...scoped,variables:[{name:"df",type:"DataFrame"}]},"FROM movimento")[0]).toBe(first[0]);
    expect(localCompletions("sql",site("sql","FROM table_|"),scoped,"FROM table_")).toHaveLength(500);
  });
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
    expect(items.filter(item => item.kind === "field").map(item => item.label)).toEqual(["title", "total"]);
    expect(items.map(item => item.label)).toEqual(expect.arrayContaining(["query", "merge", "head", "columns", "shape"]));
    expect(localCompletions("python", site("python", "unknown.|"), context, "unknown.")).toEqual([]);
  });
  it("offers dataframe columns with spaces inside string indexing", () => {
    expect(localCompletions("python", site("python", 'frame["cust|"]'), context, 'frame["cust').map(item => item.label)).toEqual(["customer name"]);
  });
  it("excludes Python hard keywords from dot fields while retaining soft keywords and all bracket fields", () => {
    const scoped:CompletionContext={variables:[{name:"frame",type:"DataFrame",columns:["class","for","None","match","case","valid"]}],tables:[]};
    expect(localCompletions("python",site("python","frame.|"),scoped,"frame.").filter(item=>item.kind==="field").map(item=>item.label)).toEqual(["match","case","valid"]);
    expect(localCompletions("python",site("python",'frame["|"]'),scoped,'frame["').map(item=>item.label)).toEqual(["class","for","None","match","case","valid"]);
  });
  it("provides Pandas methods/properties instantly from one shared catalog even for a large document", () => {
    const large = "value = 1\n".repeat(55_000) + "frame.qu";
    const scoped: CompletionContext = { variables: [{ name: "frame", type: "DataFrame", module: "pandas.core.frame", columns: ["quantity"] }], tables: [] };
    const items = localCompletions("python", site("python", "frame.qu|"), scoped, "frame.qu", [], large);
    expect(large.length).toBeGreaterThan(500_000);
    expect(items).toEqual(expect.arrayContaining([expect.objectContaining({ label: "query", kind: "method", insert_text: "query" }), expect.objectContaining({ label: "quantile", kind: "method" }), expect.objectContaining({ label: "quantity", kind: "field" })]));
    expect(dataframeMembers("pandas")).toBe(dataframeMembers("pandas"));expect(dataframeMembers("pandas").length).toBeGreaterThan(200);
    expect(localCompletions("python", site("python", "frame.sh|"), scoped, "frame.sh")).toContainEqual(expect.objectContaining({ label: "shape", kind: "property" }));
  });
  it("uses Pandas for SQL stubs, keeps methods ahead of homonymous columns and preserves bracket labels", () => {
    const scoped: CompletionContext = { variables: [{ name: "sql_frame", type: "DataFrame", columns: ["head", "query", "columns", "customer name", "for", "value"] }], tables: [] };
    const items = localCompletions("python", site("python", "sql_frame.|"), scoped, "sql_frame.");
    for (const [label,kind] of [["head","method"],["query","method"],["columns","property"]]) expect(items.filter(item=>item.label===label)).toEqual([expect.objectContaining({label,kind})]);
    expect(items.map(item=>item.label)).not.toContain("customer name");expect(items.map(item=>item.label)).not.toContain("for");
    expect(localCompletions("python", site("python", 'sql_frame["|"]'), scoped, 'sql_frame["').map(item=>item.label)).toEqual(["head","query","columns","customer name","for","value"]);
  });
  it("merges enriched RPC members with the shared catalog once while keeping homonymous bracket columns", () => {
    const scoped: CompletionContext = { variables: [{ name: "sql_frame", type: "DataFrame", module:"pandas.core.frame", columns: ["head", "query", "columns"] }], tables: [] };
    const local=localCompletions("python",site("python","sql_frame.|"),scoped,"sql_frame.");
    const remote=[{label:"head",kind:"function",insert_text:"head",detail:"def head"},{label:"query",kind:"function",insert_text:"query",detail:"def query"},{label:"columns",kind:"instance",insert_text:"columns",detail:"Index"}];
    const merged=mergeCompletions(remote,local,"python");
    for(const item of remote){expect(merged.filter(candidate=>candidate.label===item.label)).toEqual([item]);expect(merged.find(candidate=>candidate.label===item.label)?.kind).not.toBe("field");}
    const bracket=localCompletions("python",site("python",'sql_frame[["|"]]'),scoped,'sql_frame[["');
    expect(mergeCompletions(scoped.variables[0].columns!.map(label=>({label,kind:"field",insert_text:label})),bracket,"python").map(item=>item.label)).toEqual(["head","query","columns"]);
  });
  it("keeps Polars methods/properties separate from Pandas and avoids nonexistent dot-column attributes", () => {
    const scoped: CompletionContext = { variables: [{ name: "polar", type: "DataFrame", module: "polars.dataframe.frame", columns: ["customer", "with_columns"] }], tables: [] };
    const items = localCompletions("python", site("python", "polar.|"), scoped, "polar.");
    expect(items).toEqual(expect.arrayContaining([expect.objectContaining({label:"with_columns",kind:"method"}),expect.objectContaining({label:"schema",kind:"property"}),expect.objectContaining({label:"height",kind:"property"})]));
    expect(items.map(item=>item.label)).not.toContain("customer");expect(items.map(item=>item.label)).not.toContain("query");expect(items.filter(item=>item.label==="with_columns")).toHaveLength(1);
    expect(localCompletions("python", site("python", 'polar["cust|"]'), scoped, 'polar["cust').map(item=>item.label)).toEqual(["customer"]);
    expect(localCompletions("python", site("python", 'polar.sort(by="cust|")'), scoped, 'polar.sort(by="cust').map(item=>item.label)).toEqual(["customer"]);
    expect(localCompletions("python", site("python", 'polar.loc[:, "cust|"]'), scoped, 'polar.loc[:, "cust')).toEqual([]);
  });
  it.each([
    'frame[["cust|"]]', 'frame[["title", "cust|"]]', "frame[['title', 'cust|']]",
    'frame.loc[:, "cust|"]', 'frame.loc["row label", "cust|"]', 'frame.loc[frame["title"] == "x", "cust|"]', 'frame.loc[:, ["title", "cust|"]]',
    'frame.sort_values(by="cust|")', 'frame.sort_values(ascending=False, by="cust|")', 'frame.sort_values("cust|")', 'frame.sort_values(by=["title", "cust|"])',
  ])("completes literal column positions in %s without inserting quotes twice", line => {
    const result = site("python", line);expect(result).toMatchObject({member:"frame",prefix:"cust",stringColumn:true});expect(result.blocked).not.toBe(true);
    const items = localCompletions("python", result, context, line.replace("|",""));
    expect(items.map(item=>item.label)).toEqual(["customer name"]);expect(completionInsertion(items[0],result,"python")).toBe("customer name");
  });
  it("escapes a column string once within a multi-column list and owns only its content", () => {
    const result=site("python",'frame[["title", "a|b"]]'),items=localCompletions("python",result,context,'frame[["title", "a');
    expect(items.map(item=>item.label)).toEqual(['a"b']);expect(completionInsertion(items[0],result,"python")).toBe('a\\"b');
    expect(result).toMatchObject({startColumn:18,endColumn:20});
  });
  it.each([
    'print("cust|")', 'label = "cust|"', '# frame.loc[:, "cust|"]', 'frame.loc["cust|", :]',
    'frame.sort_values(ascending="cust|")', 'frame.sort_values(by=frame.columns, kind="cust|")',
    'holder.frame["cust|"]', 'frame.iloc[:, "cust|"]', 'frame[["title", other_expression, "cust|"]]',
  ])("does not reinterpret unrelated strings as dataframe columns: %s", line => {
    expect(site("python",line).blocked).toBe(true);
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
  it.each([["sqlserver","[orders]"],["mysql","`orders`"],["mariadb","`orders`"],["databricks","`orders`"],["postgresql",'"orders"'],["sqlite",'"orders"']])("uses %s saved dialect before a metadata snapshot arrives",(dbType,expected)=>{
    const scoped:CompletionContext={variables:[],tables:["orders"],dbType};
    expect(localCompletions("sql",site("sql","FROM |"),scoped,"FROM ")[0].insert_text).toBe(expected);
  });
  it("keeps saved dialect authoritative when late metadata belongs to the previous connection",()=>{
    const scoped:CompletionContext={variables:[],tables:["public.orders"],dbType:"mysql",schemaSnapshot:{db_type:"sqlserver",tables:{"public.orders":{name:"orders",schema:"public",columns:[{name:"customer_id"}]}}}};
    expect(localCompletions("sql",site("sql","orders.|"),scoped,"orders.")[0].insert_text).toBe("`customer_id`");
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
