import assert from "node:assert/strict";
import {mkdir} from "node:fs/promises";
import {dirname,resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {createServer} from "vite";
import {chromium} from "playwright";

const root=resolve(dirname(fileURLToPath(import.meta.url)),".."),route="/__runtime_errors_test",artifacts=resolve(root,"../.tooling");
const server=await createServer({root,cacheDir:"node_modules/.vite-runtime-errors-tests",plugins:[{name:"runtime-errors-fixture",configureServer(server){server.middlewares.use(route,async(_request,response)=>{
  response.setHeader("Content-Type","text/html");response.end(await server.transformIndexHtml(route,'<!doctype html><html><body><div id="root"></div><script type="module" src="/tests/runtime-errors.fixture.tsx"></script></body></html>'));
});}}],server:{host:"127.0.0.1",port:0,watch:null,hmr:false}});
let browser;await server.listen();await mkdir(artifacts,{recursive:true});
try{
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1160,height:800}}),errors=[];page.on("pageerror",error=>errors.push(error.message));
  for(const locale of ["pt-BR","en-US"])for(const theme of ["dark","light"]){
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}${route}?locale=${locale}&theme=${theme}`);
    await page.waitForFunction(()=>window.__RUNTIME_ERRORS_TEST__);
    const t=text=>page.evaluate(text=>window.__RUNTIME_ERRORS_TEST__.translate(text),text),output=page.locator(".output-panel"),entries=output.locator(".output-error");
    await entries.nth(1).waitFor();assert.equal(await entries.count(),2);
    assert.equal(await output.locator("pre").first().textContent(),"Python output: 2 rows\n");
    assert.equal(await entries.nth(0).locator("strong").textContent(),await t("Execução interrompida"));
    assert.equal(await entries.nth(1).locator("strong").textContent(),await t("Objeto não encontrado"));
    assert.equal(await entries.nth(1).getByText("Invalid object name 'missing_view'.",{exact:true}).count(),1);
    assert.equal(await entries.nth(1).locator("pre").isVisible(),false);
    assert.notEqual(await entries.nth(0).getAttribute("data-execution-id"),await entries.nth(1).getAttribute("data-execution-id"));
    assert.equal(await page.locator("img").count(),0);
    const details=entries.nth(1).locator("summary");assert.equal(await details.textContent(),await t("Detalhes técnicos"));
    await details.focus();await page.keyboard.press("Enter");await entries.nth(1).locator("pre").waitFor();
    assert.ok((await entries.nth(1).locator("pre").textContent()).includes("42S02 / 208"));
    await entries.nth(1).getByRole("button",{name:await t("Copiar detalhes"),exact:true}).click();
    await page.waitForFunction(()=>window.__RUNTIME_ERRORS_TEST__.copied.length===1);
    assert.equal((await entries.nth(1).getByRole("button",{name:await t("Copiar detalhes"),exact:true}).textContent()).trim(),locale==="en-US"?"Copied":"Copiado");
    const copied=await page.evaluate(()=>window.__RUNTIME_ERRORS_TEST__.copied[0]);assert.ok(copied.includes("Objeto não encontrado"));assert.ok(copied.includes("<diagnostic-marker>"));
    await details.click();assert.equal(await entries.nth(1).locator("pre").isVisible(),false);
    const connection=page.locator(".session-connection-status");assert.equal(await connection.locator("strong").textContent(),`${await t("Falha de autenticação")} · Shared`);
    assert.equal(await connection.locator("pre").isVisible(),false);await connection.locator("summary").click();await connection.locator("pre").waitFor();
    assert.ok((await connection.locator("pre").textContent()).includes("28000 (18456)"));await connection.locator("summary").click();
    await page.evaluate(()=>window.__RUNTIME_ERRORS_TEST__.clipboardFailure(true));
    await connection.getByRole("button",{name:await t("Copiar detalhes"),exact:true}).click();
    await connection.getByRole("status").waitFor();assert.ok((await connection.getByRole("status").textContent()).includes(await t("Não foi possível copiar. Selecione o texto para copiar manualmente.")));
    await page.evaluate(()=>window.__RUNTIME_ERRORS_TEST__.clipboardFailure(false));
    await page.screenshot({path:resolve(artifacts,`errors-${theme}-${locale}.png`),fullPage:true});
    const dimensions=await page.locator(".error-details").evaluateAll(nodes=>nodes.map(node=>({right:node.getBoundingClientRect().right,width:node.scrollWidth,client:node.clientWidth})));
    for(const value of dimensions){assert.ok(value.right<=1160);assert.ok(value.width<=value.client+2);}
    await page.evaluate(()=>window.__RUNTIME_ERRORS_TEST__.fail());await page.waitForFunction(()=>window.__RUNTIME_ERRORS_TEST__.snapshot().logs.length===4);
    assert.equal(await entries.count(),3);assert.equal(await entries.nth(2).locator("details[open]").count(),0);
    await page.evaluate(()=>window.__RUNTIME_ERRORS_TEST__.openConnectionDialog());const dialog=page.getByRole("dialog");await dialog.waitFor();
    await dialog.getByRole("button",{name:await t("Testar conexão"),exact:true}).click();await dialog.getByRole("alert").waitFor();
    assert.equal(await dialog.getByRole("alert").locator("strong").textContent(),await t("Falha de autenticação"));assert.equal(await dialog.getByRole("alert").locator("pre").isVisible(),false);
    await dialog.getByRole("alert").locator("summary").click();await dialog.getByRole("alert").locator("pre").waitFor();
    assert.equal(await page.evaluate(()=>window.__RUNTIME_ERRORS_TEST__.calls.filter(method=>method==="connection.test").length),1);
    console.log(`PASS ${locale} ${theme}: separate execution errors, clear summaries, collapsed diagnostics, keyboard expand, copy/failure, connection banner/dialog and unchanged stdout`);
  }
  assert.deepEqual(errors,[]);
}finally{await browser?.close();await server.close();}
