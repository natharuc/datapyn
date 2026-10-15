import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdir } from "node:fs/promises";
import { createServer } from "vite";
import { chromium } from "playwright";

// Production Monaco widgets in a private headless browser: no desktop window,
// application startup, database, user preferences or authentication cache.
const root = resolve(dirname(fileURLToPath(import.meta.url)), ".."), route = "/__editor_font_test";
const server = await createServer({root, cacheDir: "node_modules/.vite-font-tests", plugins: [{
  name: "editor-font-fixture",
  configureServer(server) { server.middlewares.use(route, async (_request, response) => {
    response.setHeader("Content-Type", "text/html");
    response.end(await server.transformIndexHtml(route, '<!doctype html><html><body><div id="root" style="width:760px"></div><script type="module" src="/tests/editor-font.fixture.tsx"></script></body></html>'));
  }); },
}], server: {host: "127.0.0.1", port: 0, strictPort: false}});
let browser;
let passed = 0;
await server.listen();
try {
  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1000, height: 800}});
  page.setDefaultTimeout(5000);
  const errors = []; page.on("pageerror", error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}${route}`);
  await page.waitForFunction(() => window.editorFontTest?.stats().editors.every(Boolean));
  async function size(expected) {
    await page.waitForFunction(expected => window.editorFontTest.stats().editors.every(editor => editor && editor.font === expected), expected);
    const state = await page.evaluate(() => window.editorFontTest.stats());
    assert.equal(state.zoom, 0, "Monaco's global multiplier must stay neutral");
    for (const editor of state.editors) {
      assert.equal(editor.raw, expected);
      assert.equal(editor.wheel, false);
      assert.equal(editor.lineHeight, Math.round(expected * 22 / 13));
      assert(editor.lineHeight >= editor.font, "Adjacent lines cannot overlap");
    }
    return state;
  }
  async function test(name, run) { await run(); passed++; console.log(`PASS ${name}`); }
  await test("settings update both editors once, including fractional sizes, without generating zoom callbacks", async () => {
    await size(13);
    await page.evaluate(() => window.editorFontTest.size(13.5)); await size(13.5);
    await page.evaluate(() => window.editorFontTest.rerender()); await size(13.5);
    assert.deepEqual(await page.evaluate(() => window.editorFontTest.changes), []);
  });
  await test("Ctrl+wheel changes the persisted size by one step and keeps both widgets synchronized", async () => {
    const editor = page.locator("#sql-font-section .view-lines"); await editor.hover({position: {x: 40, y: 10}});
    await page.keyboard.down("Control"); await page.mouse.wheel(0, -100); await page.keyboard.up("Control");
    assert.equal((await size(14.5)).saved, 14.5);
    assert.deepEqual(await page.evaluate(() => window.editorFontTest.changes), [14.5]);
    await page.mouse.wheel(0, 100); await size(14.5);
    assert.equal(await page.evaluate(() => window.visualViewport.scale), 1);
  });
  await test("several wheel events before React renders do not use a stale size or multiply the font", async () => {
    await page.evaluate(() => { window.editorFontTest.changes.length = 0; return window.editorFontTest.burst([-100, -100, -100, 100, 100]); });
    await size(15.5);
    assert.deepEqual(await page.evaluate(() => window.editorFontTest.changes), [15.5, 16.5, 17.5, 16.5, 15.5]);
    await page.evaluate(() => window.editorFontTest.burst(Array(100).fill(-100))); await size(32);
    await page.evaluate(() => window.editorFontTest.burst(Array(100).fill(100))); await size(8);
    const callbacks = await page.evaluate(() => window.editorFontTest.changes.length);
    await page.evaluate(() => window.editorFontTest.rerender()); await size(8);
    assert.equal(await page.evaluate(() => window.editorFontTest.changes.length), callbacks);
  });
  await test("small trackpad/pinch deltas accumulate instead of jumping through dozens of font sizes", async () => {
    await page.evaluate(() => window.editorFontTest.size(13)); await size(13);
    const cancelled = await page.evaluate(() => window.editorFontTest.burst(Array(20).fill(-2)));
    assert(cancelled.every(Boolean)); await size(13);
    await page.evaluate(() => window.editorFontTest.burst(Array(5).fill(-2))); await size(14);
    await page.evaluate(() => window.editorFontTest.burst([3], {deltaMode: 1, metaKey: true, ctrlKey: false})); await size(13);
  });
  await test("font actions share the same controlled setting even with Monaco's native font actions registered", async () => {
    await page.evaluate(() => window.editorFontTest.action("editor.action.fontZoomIn")); await size(14);
    await page.evaluate(() => window.editorFontTest.action("editor.action.fontZoomOut")); await size(13);
    await page.evaluate(() => window.editorFontTest.trigger("editor.action.fontZoomIn")); await size(14);
    await page.evaluate(() => window.editorFontTest.trigger("editor.action.fontZoomOut")); await size(13);
    await page.evaluate(() => window.editorFontTest.size(18.5)); await size(18.5);
    await page.evaluate(() => window.editorFontTest.action("editor.action.fontZoomReset")); await size(13);
  });
  await test("tab unmount/remount and reload preserve the single fractional preference", async () => {
    await page.evaluate(() => window.editorFontTest.size(17.3)); await size(17.3);
    await page.evaluate(() => window.editorFontTest.mounted(false));
    await page.waitForFunction(() => window.editorFontTest.stats().editors.every(editor => !editor));
    await page.evaluate(() => window.editorFontTest.mounted(true)); await size(17.3);
    await page.reload(); await size(17.3);
    assert.deepEqual(await page.evaluate(() => window.editorFontTest.changes), []);
  });
  await test("an editor moved into another document keeps font, line spacing and wheel controls", async () => {
    await page.evaluate(() => window.editorFontTest.adopt());
    await page.waitForFunction(() => window.editorFontTest.stats().editors[0]?.owner === "child");
    await size(17.3);
    const frame = page.frameLocator("#editor-font-child");
    await frame.locator(".monaco-block").hover({position: {x: 100, y: 50}});
    await page.keyboard.down("Control"); await page.mouse.wheel(0, -100); await page.keyboard.up("Control"); await size(18.3);
    await page.evaluate(() => window.editorFontTest.returnToMain());
    await page.waitForFunction(() => window.editorFontTest.stats().editors[0]?.owner === "main");
    await size(18.3);
    await page.evaluate(() => window.editorFontTest.burst([100])); await size(17.3);
  });
  assert.deepEqual(errors, []);
  const previews = resolve(root, "../.tooling/editor-font-previews"); await mkdir(previews, {recursive: true});
  for (const pixels of [8, 13.5, 32]) {
    await page.evaluate(value => window.editorFontTest.size(value), pixels); await size(pixels);
    await page.screenshot({path: resolve(previews, `${pixels}px.png`)});
  }
  console.log(`${passed} editor font browser checks passed.`);
} finally { await browser?.close(); await server.close(); }
