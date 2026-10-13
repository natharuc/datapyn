import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { chromium } from "playwright";

// Real React events and RPC dispatch with an isolated in-memory catalog; no desktop or database is contacted.
const root = resolve(dirname(fileURLToPath(import.meta.url)), ".."), route = "/__explorer_test";
const server = await createServer({ root, cacheDir: "node_modules/.vite-explorer-tests", plugins: [{ name: "explorer-fixture", configureServer(server) {
  server.middlewares.use(route, async (_request, response) => {
    response.setHeader("Content-Type", "text/html");
    response.end(await server.transformIndexHtml(route, '<!doctype html><html><body><div id="root"></div><script type="module" src="/tests/explorer.fixture.tsx"></script></body></html>'));
  });
} }], server: { host: "127.0.0.1", port: 0, watch: null } });
let browser;
await server.listen();
try {
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 960, height: 700 }, reducedMotion: "reduce" }), pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  const address = `http://127.0.0.1:${server.httpServer.address().port}${route}`;
  const row = id => page.locator(`[id="explorer-row-${id}"]`), menu = page.getByRole("menu");
  const open = async (id = "orders") => { await row(id).click({ button: "right", position: { x: 90, y: 14 } }); await menu.waitFor(); };
  const select = async (label, id = "orders") => { await open(id); await menu.getByRole("menuitem", { name: label, exact: true }).click(); await menu.waitFor({ state: "detached" }); };
  const latest = name => page.evaluate(name => JSON.parse(JSON.stringify(window.__EXPLORER_TEST__[name].at(-1))), name);
  for (const theme of ["light", "dark"]) {
    await page.goto(address); await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme); await row("orders").waitFor();
    await open();
    assert.equal(await page.locator(".modal-overlay").count(), 0);
    const source = await row("orders").boundingBox(), bounds = await menu.boundingBox();
    assert(Math.abs(bounds.x - source.x - 90) <= 1); assert(Math.abs(bounds.y - source.y - 14) <= 1);
    assert.equal(await menu.getByRole("menuitem").count(), 10);
    await page.keyboard.press("End"); assert.equal(await page.evaluate(() => document.activeElement.textContent), "Atualizar este grupo");
    await page.keyboard.press("Home"); assert.equal(await page.evaluate(() => document.activeElement.textContent), "Inserir nome no bloco em foco");
    await page.keyboard.press("Escape"); await menu.waitFor({ state: "detached" });
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute("role")), "tree");
    await page.keyboard.press("Shift+F10"); await menu.waitFor();
    await page.keyboard.press("Tab"); await menu.waitFor({ state: "detached" });
    await open(); await page.locator("#outside").click(); await menu.waitFor({ state: "detached" });
    await open(); await page.locator(".explorer-viewport").evaluate(element => element.dispatchEvent(new Event("scroll"))); await menu.waitFor({ state: "detached" });

    await select("Inserir nome no bloco em foco"); assert.deepEqual(await latest("inserts"), { code: "[public].[Orders]" });
    await select("Copiar nome"); assert.equal(await latest("copied"), "Orders");
    await select("Copiar nome qualificado"); assert.equal(await latest("copied"), "public.Orders");
    await select("Detalhes, colunas e índices"); const details = page.getByRole("dialog", { name: "Detalhes · public.Orders" }); await details.waitFor();
    assert.equal(await details.getByRole("heading", { name: "Colunas", exact: true }).count(), 1);
    assert((await details.textContent()).includes("PK_Orders"));
    await details.getByRole("button", { name: "Abrir definição em novo bloco" }).click(); await details.waitFor({ state: "detached" });
    assert.deepEqual(await latest("inserts"), { code: "CREATE TABLE Orders (id BIGINT);", language: "sql", newBlock: true });
    await select("Definição / CREATE"); assert.equal((await latest("inserts")).code, "CREATE TABLE Orders (id BIGINT);");
    await select("SELECT primeiras 1000 linhas"); await page.waitForFunction(() => window.__EXPLORER_TEST__.inserts.at(-1)?.code.startsWith("SELECT TOP (1000)"));
    const query = (await latest("calls"));
    assert.deepEqual(query, { method: "explorer.query", params: { session_id: "session", block_id: "block", scope_inherited: false, connection_id: "connection-sqlserver", database: "warehouse", schema: "public", name: "Orders", kind: "table", limit: 1000 } });
    await select("SELECT com todas as colunas"); assert.equal((await latest("inserts")).code, "SELECT TOP 1000 [Order ID],\n       [Total]\nFROM [public].[Orders];");
    await select("COUNT(*)"); assert.deepEqual(await latest("inserts"), { code: "SELECT COUNT(*) FROM [public].[Orders];", language: "sql", newBlock: true });
    await select("Script DROP e CREATE"); assert.equal((await latest("inserts")).code, "IF OBJECT_ID(N'[public].[Orders]', N'U') IS NOT NULL\n    DROP TABLE [public].[Orders];\n\nCREATE TABLE Orders (id BIGINT);");
    await select("Atualizar este grupo"); assert.equal((await latest("calls")).method, "explorer.list"); assert.equal((await latest("calls")).params.refresh, true);

    await open("view"); assert.equal(await menu.getByRole("menuitem", { name: "Script DROP e CREATE" }).count(), 0); await page.keyboard.press("Escape");
    await select("SELECT primeiras 1000 linhas", "view"); await page.waitForFunction(() => window.__EXPLORER_TEST__.inserts.at(-1)?.code.includes("ActiveOrders")); assert.equal((await latest("calls")).params.kind, "view");
    for (const id of ["proc", "func"]) { await open(id); assert.equal(await menu.getByRole("menuitem", { name: "SELECT primeiras 1000 linhas" }).count(), 0); await page.keyboard.press("Escape"); await select("Definição / CREATE", id); }
    await row("orders").dblclick({ position: { x: 90, y: 14 } }); await row("order-id").waitFor();
    await select("Copiar como Orders.Order ID", "order-id"); assert.equal(await latest("copied"), "Orders.Order ID");
    for (const clause of ["WHERE", "GROUP BY", "ORDER BY"]) { await select(clause, "order-id"); assert.equal((await latest("inserts")).code, `${clause} [Order ID]${clause === "WHERE" ? " = " : ""}`); }
    await select("Usar schema no bloco", "schema"); assert.deepEqual(await latest("contexts"), { database: "warehouse", schema: "analytics" });
    await select("Usar banco / catálogo no bloco", "database"); assert.deepEqual(await latest("contexts"), { database: "warehouse" });
    await page.evaluate(() => window.__EXPLORER_TEST__.setUseCallback(false));
    await select("Usar banco / catálogo no bloco", "catalog"); assert.equal((await latest("calls")).method, "explorer.use_database"); assert.equal((await latest("calls")).params.database, "catalog");
    await open("category"); assert.equal(await menu.getByRole("menuitem", { name: "Inserir nome no bloco em foco" }).count(), 0); await page.keyboard.press("Escape");
    console.log(`PASS ${theme}: cursor menu, keyboard/outside/scroll dismissal, table/view/routine/column/namespace actions and full block RPC scope`);
  }

  for (const dialect of ["postgresql", "mysql", "mariadb", "databricks", "sqlite"]) {
    await page.evaluate(dialect => window.__EXPLORER_TEST__.setDialect(dialect), dialect); await row("orders").waitFor();
    const quote = ["mysql", "mariadb", "databricks"].includes(dialect) ? "`" : '"';
    await select("SELECT com todas as colunas"); assert.equal((await latest("inserts")).code, `SELECT ${quote}Order ID${quote},\n       ${quote}Total${quote}\nFROM ${quote}public${quote}.${quote}Orders${quote}\nLIMIT 1000;`);
    await select("Script DROP e CREATE"); assert.equal((await latest("inserts")).code, `DROP TABLE IF EXISTS ${quote}public${quote}.${quote}Orders${quote};\n\nCREATE TABLE Orders (id BIGINT);`);
  }
  await page.evaluate(() => window.__EXPLORER_TEST__.setDisabled(true)); await open();
  for (const label of ["Inserir nome no bloco em foco", "Definição / CREATE", "SELECT primeiras 1000 linhas", "SELECT com todas as colunas", "COUNT(*)", "Script DROP e CREATE"]) assert.equal(await menu.getByRole("menuitem", { name: label, exact: true }).isDisabled(), true);
  assert.equal(await menu.getByRole("menuitem", { name: "Copiar nome", exact: true }).isDisabled(), false); await page.keyboard.press("Home"); assert.equal(await page.evaluate(() => document.activeElement.textContent), "Copiar nome"); await page.keyboard.press("Escape");
  await page.evaluate(() => { window.__EXPLORER_TEST__.setDisabled(false); window.__EXPLORER_TEST__.failNext("explorer.query"); });
  await select("SELECT primeiras 1000 linhas"); await page.getByRole("alert").filter({ hasText: "Permissão de metadados negada" }).waitFor(); assert.equal(await latest("errors"), "Permissão de metadados negada");
  await page.evaluate(() => window.__EXPLORER_TEST__.missingNext("columns")); await select("SELECT com todas as colunas"); await page.getByRole("alert").filter({ hasText: "Não há metadados" }).waitFor();
  await page.evaluate(() => window.__EXPLORER_TEST__.missingNext("definition")); await select("Definição / CREATE"); await page.getByRole("alert").filter({ hasText: "O driver não disponibilizou" }).waitFor();
  await page.evaluate(() => window.__EXPLORER_TEST__.failNext("explorer.details")); await select("Detalhes, colunas e índices"); await page.getByRole("dialog").getByText("Permissão de metadados negada").waitFor(); await page.getByRole("dialog").getByRole("button", { name: "Fechar" }).click();
  for (const [label, method, response] of [["SELECT primeiras 1000 linhas", "explorer.query", { code: "LATE QUERY" }], ["SELECT com todas as colunas", "explorer.details", { columns: [{ name: "late" }] }], ["Definição / CREATE", "explorer.details", { definition: "LATE DEFINITION" }]]) {
    const before = await page.evaluate(() => window.__EXPLORER_TEST__.inserts.length);
    await page.evaluate(method => window.__EXPLORER_TEST__.holdNext(method), method); await select(label); await page.waitForFunction(() => window.__EXPLORER_TEST__.pending);
    const previousBlock = (await latest("calls")).params.block_id;
    await page.evaluate(() => window.__EXPLORER_TEST__.changeBlock());
    await page.waitForFunction(previousBlock => window.__EXPLORER_TEST__.calls.filter(call => call.method === "explorer.list").at(-1)?.params.block_id !== previousBlock, previousBlock);
    await row("orders").waitFor(); await page.evaluate(response => window.__EXPLORER_TEST__.release(response), response);
    await page.waitForFunction(() => !window.__EXPLORER_TEST__.pending); assert.equal(await page.evaluate(() => window.__EXPLORER_TEST__.inserts.length), before);
  }
  await page.setViewportSize({ width: 280, height: 310 });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await row("orders").evaluate(element => element.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 270, clientY: 300 }))); await menu.waitFor(); const small = await menu.boundingBox();
  assert(small.x >= 7 && small.y >= 7 && small.x + small.width <= 273 && small.y + small.height <= 303);
  await page.keyboard.press("Escape"); assert.deepEqual(pageErrors, []);
  console.log("PASS all dialects: generated SQL, busy-state commands, metadata failures, missing data, stale responses and viewport bounds");
} finally { await browser?.close(); await server.close(); }
