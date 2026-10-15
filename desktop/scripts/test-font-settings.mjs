import assert from "node:assert/strict";
import {dirname,resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {createServer} from "vite";
import {chromium} from "playwright";

const root=resolve(dirname(fileURLToPath(import.meta.url)),".."),route="/__font_settings_test";
const server=await createServer({root,cacheDir:"node_modules/.vite-font-settings-tests",plugins:[{name:"font-settings-fixture",configureServer(server){server.middlewares.use(route,async(_request,response)=>{
  response.setHeader("Content-Type","text/html");response.end(await server.transformIndexHtml(route,'<!doctype html><html><body><div id="root"></div><script type="module" src="/tests/font-settings.fixture.tsx"></script></body></html>'));
});}}],server:{host:"127.0.0.1",port:0,watch:null}});
let browser;
await server.listen();
try{
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage(),errors=[];
  page.on("pageerror",error=>errors.push(error.message));
  const address=`http://127.0.0.1:${server.httpServer.address().port}${route}`;
  for(const locale of ["pt-BR","en-US"]){
    await page.goto(`${address}?locale=${locale}`);await page.waitForFunction(()=>window.__FONT_SETTINGS_TEST__);
    await page.evaluate(()=>localStorage.clear());await page.reload();await page.waitForFunction(()=>window.__FONT_SETTINGS_TEST__);
    const labels=await page.evaluate(()=>Object.fromEntries(["Tamanho do editor","Aplicar","Restaurar padrões","Fonte do editor"].map(text=>[text,window.__FONT_SETTINGS_TEST__.translate(text)])));
    const input=page.getByLabel(labels["Tamanho do editor"],{exact:true}),apply=page.getByRole("button",{name:labels.Aplicar,exact:true});
    assert.equal(await input.inputValue(),"13");
    await input.fill("");assert.equal(await input.inputValue(),"");
    await input.pressSequentially("13.");assert.equal(await input.inputValue(),"13.");
    await input.pressSequentially("5");assert.equal(await input.inputValue(),"13.5");
    await page.evaluate(()=>window.__FONT_SETTINGS_TEST__.updateUnrelated());assert.equal(await input.inputValue(),"13.5");
    await apply.click();await page.waitForFunction(()=>window.__FONT_SETTINGS_TEST__.saved===1);
    assert.equal(await page.evaluate(()=>window.__FONT_SETTINGS_TEST__.preferences.editorFontSize),13.5);
    for(const [draft,expected] of [["14,5",14.5],["",14.5],["NaN",14.5],["13.567",13.6],["999",32],["0",8]]){
      const count=await page.evaluate(()=>window.__FONT_SETTINGS_TEST__.saved);
      await input.fill(draft);assert.equal(await input.inputValue(),draft);
      await apply.click();await page.waitForFunction(count=>window.__FONT_SETTINGS_TEST__.saved===count+1,count);
      assert.equal(await page.evaluate(()=>window.__FONT_SETTINGS_TEST__.preferences.editorFontSize),expected);
      assert.equal(await input.inputValue(),String(expected));
    }
    await input.fill("15,5");await page.getByLabel(labels["Fonte do editor"],{exact:true}).focus();assert.equal(await input.inputValue(),"15.5");
    await apply.click();await page.reload();await page.waitForFunction(()=>window.__FONT_SETTINGS_TEST__);
    assert.equal(await input.inputValue(),"15.5");
    await input.fill("22,");await page.getByRole("button",{name:labels["Restaurar padrões"],exact:true}).click();assert.equal(await input.inputValue(),"13");
    await apply.click();assert.equal(await page.evaluate(()=>window.__FONT_SETTINGS_TEST__.preferences.editorFontSize),13);
    console.log(`PASS ${locale}: fractional typing, decimal comma, empty/invalid drafts, bounds, blur/apply, external updates and persisted restart`);
  }
  assert.deepEqual(errors,[]);
}finally{await browser?.close();await server.close();}
