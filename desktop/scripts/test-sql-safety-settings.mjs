import assert from "node:assert/strict";
import {dirname,resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {createServer} from "vite";
import {chromium} from "playwright";

const root=resolve(dirname(fileURLToPath(import.meta.url)),".."),route="/__sql_safety_settings_test";
const server=await createServer({root,cacheDir:"node_modules/.vite-sql-safety-settings-tests",plugins:[{name:"sql-safety-settings-fixture",configureServer(server){server.middlewares.use(route,async(_request,response)=>{
  response.setHeader("Content-Type","text/html");response.end(await server.transformIndexHtml(route,'<!doctype html><html><body><div id="root"></div><script type="module" src="/tests/sql-safety-settings.fixture.tsx"></script></body></html>'));
});}}],server:{host:"127.0.0.1",port:0,watch:null}});
let browser;
await server.listen();
try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage(),errors=[];
  page.on("pageerror",error=>errors.push(error.message));
  const address=`http://127.0.0.1:${server.httpServer.address().port}${route}`;
  for(const locale of ["pt-BR","en-US"]){
    await page.goto(`${address}?locale=${locale}`);await page.waitForFunction(()=>window.__SQL_SAFETY_SETTINGS_TEST__);
    await page.evaluate(()=>localStorage.clear());await page.reload();await page.waitForFunction(()=>window.__SQL_SAFETY_SETTINGS_TEST__);
    const labels=await page.evaluate(()=>Object.fromEntries(["Confirmar comandos SQL destrutivos","Aplicar","Notificar ao terminar a execução"].map(text=>[text,window.__SQL_SAFETY_SETTINGS_TEST__.translate(text)])));
    const confirmation=page.getByRole("checkbox",{name:labels["Confirmar comandos SQL destrutivos"],exact:true}),apply=page.getByRole("button",{name:labels.Aplicar,exact:true});
    assert.equal(await confirmation.isChecked(),true);
    await confirmation.uncheck();await apply.click();await page.getByRole("dialog").waitFor({state:"detached"});
    assert.equal(await page.evaluate(()=>window.__SQL_SAFETY_SETTINGS_TEST__.preferences.confirmDestructiveSql),false);
    assert.deepEqual(await page.evaluate(()=>window.__SQL_SAFETY_SETTINGS_TEST__.calls),[{method:"sql.safety.settings.set",params:{confirm_destructive_sql:false}}]);
    await page.reload();await page.waitForFunction(()=>window.__SQL_SAFETY_SETTINGS_TEST__);assert.equal(await confirmation.isChecked(),false);
    await page.getByRole("checkbox",{name:labels["Notificar ao terminar a execução"],exact:true}).uncheck();await apply.click();await page.getByRole("dialog").waitFor({state:"detached"});
    assert.deepEqual(await page.evaluate(()=>window.__SQL_SAFETY_SETTINGS_TEST__.calls),[{method:"sql.safety.settings.get",params:{}}]);
    await page.locator("#open").click();await confirmation.check();await apply.click();await page.getByRole("dialog").waitFor({state:"detached"});
    assert.equal(await page.evaluate(()=>window.__SQL_SAFETY_SETTINGS_TEST__.preferences.confirmDestructiveSql),true);
    assert.deepEqual(await page.evaluate(()=>window.__SQL_SAFETY_SETTINGS_TEST__.calls.at(-1)),{method:"sql.safety.settings.set",params:{confirm_destructive_sql:true}});
    console.log(`PASS ${locale}: enabled default, explicit disable, persisted restart, unrelated edit and explicit re-enable`);
  }
  assert.deepEqual(errors,[]);
}finally{await browser?.close();await server.close();}
