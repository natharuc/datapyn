import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { chromium } from "playwright";

// Isolated updater controller/modal fixture; no desktop, IPC, real release download or installer.
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const route = "/__updates_test";
const server = await createServer({ root, cacheDir: "node_modules/.vite-updater-tests", plugins: [{
  name: "updater-fixture", configureServer(server) { server.middlewares.use(route, async (_request, response) => {
    response.setHeader("Content-Type", "text/html");
    response.end(await server.transformIndexHtml(route, '<!doctype html><html><head></head><body><div id="root"></div><script type="module" src="/tests/updates.fixture.tsx"></script></body></html>'));
  }); },
}], server: { host: "127.0.0.1", port: 0 } });
let browser, passed = 0;
await server.listen();
try {
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ reducedMotion: "reduce" }), errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const address = `http://127.0.0.1:${server.httpServer.address().port}${route}`;
  for (const theme of ["light", "dark"]) for (const width of [960, 1440]) {
    await page.setViewportSize({ width, height: 800 }); await page.goto(address);
    await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
    await page.waitForFunction(() => window.__UPDATES_TEST__?.state.phase === "downloading");
    await page.getByRole("button", { name: "Fechar", exact: true }).last().click();
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]'));
    assert.equal(await page.evaluate(() => window.__UPDATES_TEST__.state.phase), "downloading");
    await page.getByRole("button", { name: "Atualizações", exact: true }).click();
    const modal = page.getByRole("dialog", { name: "Atualizações do DataPyn" });
    await modal.waitFor(); assert.equal(await modal.locator("progress").count(), 1);
    await page.evaluate(() => window.__UPDATES_TEST__.finishDownload());
    await page.getByRole("button", { name: "Salvar e instalar", exact: true }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.__UPDATES_TEST__.calls), ["check", "download"]);
    await page.getByRole("button", { name: "Salvar e instalar", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "Aguarde ou cancele" }).waitFor();
    assert.equal(await page.evaluate(() => window.__UPDATES_TEST__.state.phase), "downloaded");
    const bounds = await modal.evaluate(element => {
      const box = element.getBoundingClientRect();
      return { fits: box.left >= 0 && box.top >= 0 && box.right <= innerWidth && box.bottom <= innerHeight, overflow: element.scrollWidth > element.clientWidth + 1 };
    });
    assert.equal(bounds.fits, true); assert.equal(bounds.overflow, false);
    await page.evaluate(() => window.__UPDATES_TEST__.allowInstall());
    await page.getByRole("button", { name: "Salvar e instalar", exact: true }).click();
    await page.getByRole("button", { name: "Reiniciar agora", exact: true }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.__UPDATES_TEST__.calls), ["check", "download", "save", "install"]);
    passed++;
  }
  await page.goto(address); await page.waitForFunction(() => window.__UPDATES_TEST__?.state.phase === "downloading");
  await page.evaluate(() => window.__UPDATES_TEST__.failDownload());
  await page.getByRole("alert").filter({ hasText: "Assinatura inválida" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Salvar e instalar", exact: true }).count(), 0);
  assert.equal(await page.evaluate(() => window.__UPDATES_TEST__.calls.includes("install")), false);
  passed++;
  assert.deepEqual(errors, []); console.log(`${passed} real updater dialog scenarios passed`);
} finally { await browser?.close(); await server.close(); }
