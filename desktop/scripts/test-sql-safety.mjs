import assert from "node:assert/strict";
import {mkdir} from "node:fs/promises";
import {dirname, resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {createServer} from "vite";
import {chromium} from "playwright";

const root = resolve(dirname(fileURLToPath(import.meta.url)), ".."), route = "/__sql_safety_test";
const output = resolve(root, "../.tooling/sql-safety-ui");
const server = await createServer({root, cacheDir: "node_modules/.vite-sql-safety-tests", plugins: [{name: "sql-safety-fixture", configureServer(server) {
  server.middlewares.use(route, async (_request, response) => {
    response.setHeader("Content-Type", "text/html");
    response.end(await server.transformIndexHtml(route, '<!doctype html><html><body><div id="root"></div><script type="module" src="/tests/sql-safety.fixture.tsx"></script></body></html>'));
  });
}}], server: {host: "127.0.0.1", port: 0, watch: null}});
const stripApproval = params => Object.fromEntries(Object.entries(params).filter(([key]) => !["method", "confirmation_token"].includes(key)));
let browser;
await server.listen();
try {
  await mkdir(output, {recursive: true});
  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1100, height: 820}}), errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const address = `http://127.0.0.1:${server.httpServer.address().port}${route}`;
  const calls = method => page.evaluate(method => window.__SQL_SAFETY_TEST__.calls.filter(call => call.method === method), method);
  const idle = () => page.waitForFunction(() => window.__SQL_SAFETY_TEST__.snapshot().sessions.every(session => !session.busy));
  const clean = async (locale, theme, long = false) => {
    await page.goto(`${address}?locale=${locale}&theme=${theme}${long ? "&long=1" : ""}`);
    await page.waitForFunction(() => window.__SQL_SAFETY_TEST__);
    return page.evaluate(() => Object.fromEntries(["Confirmar execução SQL", "Cancelar", "Executar", "Fechar", "Sem WHERE · todas as linhas", "Objeto inteiro", "Para tabela", "Exportar para tabela", "Exportar", "Tabela", "Se a tabela existir", "Confirmar comandos SQL destrutivos", "Aplicar"].map(text => [text, window.__SQL_SAFETY_TEST__.translate(text)])));
  };
  const ensureNoExecution = async () => {assert.equal((await calls("execution.run")).length, 0);assert.equal((await calls("result.export_table")).length, 0);};
  const assertHealthy = async () => {
    assert.deepEqual(await page.evaluate(() => window.__SQL_SAFETY_TEST__.violations), []);
    assert.deepEqual(await page.evaluate(() => window.__SQL_SAFETY_TEST__.failures), []);
  };

  for (const locale of ["pt-BR", "en-US"]) for (const theme of ["dark", "light"]) {
    let labels = await clean(locale, theme);
    let dialog = page.getByRole("dialog", {name: labels["Confirmar execução SQL"], exact: true});
    for (const action of ["cancel", "escape", "backdrop", "enter"]) {
      await page.locator("#run-a").click(); await dialog.waitFor();
      await ensureNoExecution();
      assert.match(await dialog.innerText(), /Fixture \/ Warehouse A/);
      assert.match(await dialog.innerText(), /FixtureDB/);
      assert.match(await dialog.innerText(), /dbo/);
      assert.match(await dialog.locator(".sql-safety-command-label code").innerText(), /orders/);
      assert.equal(await dialog.locator(".sql-safety-unfiltered").innerText(), labels["Sem WHERE · todas as linhas"]);
      assert.equal(await page.evaluate(() => window.__SQL_SAFETY_TEST__.snapshot().sessions[0].executionStartedAt), undefined);
      assert.equal(await dialog.getByRole("button", {name: labels.Fechar, exact: true}).evaluate(element => element === document.activeElement), true);
      if (action === "cancel") await dialog.getByRole("button", {name: labels.Cancelar, exact: true}).click();
      else if (action === "escape") await page.keyboard.press("Escape");
      else if (action === "backdrop") await page.mouse.click(4, 4);
      else await page.keyboard.press("Enter");
      await dialog.waitFor({state: "detached"}); await idle(); await ensureNoExecution();
    }
    const selectedSql = `USE [ReviewedDB];\n${"-- Keep this execution context unchanged.\n".repeat(24)}DELETE FROM dbo.orders WHERE id = 7;`;
    await page.evaluate(code => window.__SQL_SAFETY_TEST__.selection(code), selectedSql);
    await page.locator("#run-a").click(); await dialog.waitFor();
    const frozen = (await calls("execution.review")).at(-1).params;
    assert.equal(frozen.code, selectedSql);
    await dialog.locator(".sql-safety-source summary").click();
    assert.equal(await dialog.locator(".sql-safety-source pre").textContent(), selectedSql);
    assert.ok((await dialog.locator(".sql-safety-commands pre").textContent()).length < selectedSql.length);
    await page.evaluate(() => window.__SQL_SAFETY_TEST__.mutate("a"));
    await dialog.getByRole("button", {name: labels.Executar, exact: true}).click();
    await idle();
    const approved = await calls("execution.run");
    assert.equal(approved.length, 1); assert.ok(approved[0].params.confirmation_token);
    assert.deepEqual(stripApproval(approved[0].params), stripApproval(frozen));
    await assertHealthy();

    labels = await clean(locale, theme); dialog = page.getByRole("dialog", {name: labels["Confirmar execução SQL"], exact: true});
    await page.locator("#run-both").click(); await dialog.waitFor();
    await page.waitForFunction(() => window.__SQL_SAFETY_TEST__.calls.filter(call => call.method === "execution.review").length === 2);
    await ensureNoExecution(); assert.match(await dialog.innerText(), /Analysis A/);
    await dialog.getByRole("button", {name: labels.Cancelar, exact: true}).click();
    await page.waitForFunction(() => document.querySelector(".sql-safety-context")?.textContent?.includes("Analysis B"));
    await ensureNoExecution();
    await dialog.getByRole("button", {name: labels.Executar, exact: true}).click(); await idle();
    const separate = await calls("execution.run"), ids = await page.evaluate(() => window.__SQL_SAFETY_TEST__.sessions);
    assert.equal(separate.length, 1); assert.equal(separate[0].params.session_id, ids.b);
    await assertHealthy();

    labels = await clean(locale, theme); dialog = page.getByRole("dialog", {name: labels["Confirmar execução SQL"], exact: true});
    await page.locator("#result-actions").getByRole("button", {name: labels["Para tabela"], exact: true}).click();
    const tableDialog = page.getByRole("dialog", {name: labels["Exportar para tabela"], exact: true});
    await tableDialog.getByLabel(labels.Tabela, {exact: true}).fill("orders_snapshot");
    await tableDialog.getByLabel(labels["Se a tabela existir"]).selectOption("replace");
    await tableDialog.getByRole("button", {name: labels.Exportar, exact: true}).click(); await dialog.waitFor();
    await ensureNoExecution();
    assert.equal((await calls("execution.review"))[0].params.method, "result.export_table");
    assert.match(await dialog.locator(".sql-safety-context").innerText(), /Resolved export warehouse/);
    assert.equal(await dialog.locator(".sql-safety-unfiltered").innerText(), labels["Objeto inteiro"]);
    // Escape must cancel only the top confirmation, keeping the export form intact.
    await page.keyboard.press("Escape"); await dialog.waitFor({state: "detached"});
    await tableDialog.getByRole("button", {name: labels.Exportar, exact: true}).waitFor({state: "visible"});
    await ensureNoExecution();
    await tableDialog.getByRole("button", {name: labels.Exportar, exact: true}).click(); await dialog.waitFor();
    const exportReview = (await calls("execution.review")).at(-1).params;
    await dialog.getByRole("button", {name: labels.Executar, exact: true}).click();
    await tableDialog.waitFor({state: "detached"});
    const replaced = await calls("result.export_table"); assert.equal(replaced.length, 1);
    assert.deepEqual(stripApproval(replaced[0].params), stripApproval(exportReview)); assert.ok(replaced[0].params.confirmation_token);
    await page.locator("#result-actions").getByRole("button", {name: labels["Para tabela"], exact: true}).click();
    await tableDialog.getByLabel(labels["Se a tabela existir"]).selectOption("append");
    await tableDialog.getByRole("button", {name: labels.Exportar, exact: true}).click(); await tableDialog.waitFor({state: "detached"});
    assert.equal((await calls("execution.review")).length, 2);
    assert.equal((await calls("result.export_table")).length, 2);
    assert.equal((await calls("result.export_table"))[1].params.if_exists, "append");
    assert.equal((await calls("result.export_table"))[1].params.confirmation_token, undefined);
    await assertHealthy();

    await page.locator("#settings").click();
    const settingsDialog = page.getByRole("dialog");
    const toggle = settingsDialog.getByRole("checkbox", {name: labels["Confirmar comandos SQL destrutivos"], exact: true});
    assert.equal(await toggle.isChecked(), true); await toggle.uncheck();
    await settingsDialog.getByRole("button", {name: labels.Aplicar, exact: true}).click(); await settingsDialog.waitFor({state: "detached"});
    assert.equal(await page.evaluate(() => window.__SQL_SAFETY_TEST__.safety()), false);
    await page.locator("#run-a").click(); await idle(); assert.equal((await calls("execution.run")).length, 1);
    assert.equal((await calls("execution.run"))[0].params.confirmation_token, undefined);
    assert.equal(await dialog.count(), 0); await assertHealthy();

    await page.setViewportSize({width: 680, height: 760});
    labels = await clean(locale, theme, true); dialog = page.getByRole("dialog", {name: labels["Confirmar execução SQL"], exact: true});
    await page.locator("#run-a").click(); await dialog.waitFor();
    const geometry = await dialog.evaluate(element => {
      const rect = element.getBoundingClientRect(), body = element.querySelector(".sql-safety-body"), context = element.querySelector(".sql-safety-context dt");
      const footer = element.querySelector(".modal-footer").getBoundingClientRect();
      return {left: rect.left, right: rect.right, width: rect.width, viewport: innerWidth, bodyOverflow: body.scrollWidth > body.clientWidth + 1,
        commandOverflow: [...element.querySelectorAll(".sql-safety-commands li, pre, dd")].some(child => child.scrollWidth > child.clientWidth + 1),
        footerVisible: footer.top >= rect.top && footer.bottom <= innerHeight - 20,
        background: getComputedStyle(element).backgroundColor, text: getComputedStyle(element).color,
        muted: getComputedStyle(context).color, mutedVariable: getComputedStyle(document.documentElement).getPropertyValue("--muted").trim()};
    });
    assert.ok(geometry.left >= 15 && geometry.right <= geometry.viewport - 15); assert.ok(geometry.width <= 648);
    assert.equal(geometry.bodyOverflow, false); assert.equal(geometry.commandOverflow, false); assert.ok(geometry.mutedVariable);
    assert.equal(geometry.footerVisible, true);
    assert.notEqual(geometry.background, geometry.text); assert.notEqual(geometry.muted, geometry.text);
    await page.screenshot({path: resolve(output, `${locale}-${theme}-680.png`)});
    await dialog.locator(".sql-safety-source summary").click();
    assert.equal(await dialog.locator(".sql-safety-source pre").textContent(), (await calls("execution.review"))[0].params.code);
    await dialog.locator(".sql-safety-source pre").scrollIntoViewIfNeeded();
    assert.equal(await dialog.locator(".sql-safety-source pre").evaluate(element => element.scrollWidth <= element.clientWidth + 1 && element.clientHeight <= 240), true);
    assert.equal(await dialog.locator(".modal-footer").evaluate(element => {const rect=element.getBoundingClientRect();return rect.top>=0&&rect.bottom<=innerHeight-20;}), true);
    await page.screenshot({path: resolve(output, `${locale}-${theme}-680-source.png`)});
    await dialog.getByRole("button", {name: labels.Cancelar, exact: true}).click(); await idle(); await ensureNoExecution();
    await page.setViewportSize({width: 1100, height: 820});
    console.log(`PASS ${locale}/${theme}: cancel, Escape, backdrop, safe Enter, frozen selection/target, independent sessions, replace/append, setting and narrow layout`);
  }
  assert.deepEqual(errors, []);
  console.log(`Screenshots: ${output}`);
} finally {await browser?.close(); await server.close();}
