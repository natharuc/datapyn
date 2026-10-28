import assert from "node:assert/strict";
import {dirname,resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {createServer} from "vite";
import {chromium} from "playwright";

const root=resolve(dirname(fileURLToPath(import.meta.url)),".."),route="/__telemetry_settings_test";
const server=await createServer({root,cacheDir:"node_modules/.vite-telemetry-settings-tests",plugins:[{name:"telemetry-settings-fixture",configureServer(server){server.middlewares.use(route,async(_request,response)=>{
  response.setHeader("Content-Type","text/html");response.end(await server.transformIndexHtml(route,'<!doctype html><html><body><div id="root"></div><script type="module" src="/tests/telemetry-settings.fixture.tsx"></script></body></html>'));
});}}],server:{host:"127.0.0.1",port:0,watch:null,hmr:false}});
let browser;
await server.listen();
try{
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1200,height:900}}),errors=[];
  page.on("pageerror",error=>errors.push(error.message));
  const address=`http://127.0.0.1:${server.httpServer.address().port}${route}`;
  for(const locale of ["pt-BR","en-US"]){
    await page.goto(`${address}?locale=${locale}`);
    await page.waitForFunction(()=>window.__TELEMETRY_TEST__?.calls.some(call=>call.method==="telemetry.settings.get"));
    const labels=await page.evaluate(()=>Object.fromEntries(["Enviar diagnósticos de falhas e desempenho","Salvar telemetria","Endpoint HTTPS","Telemetria salva."].map(text=>[text,window.__TELEMETRY_TEST__.t(text)])));
    const consent=page.getByRole("checkbox",{name:labels["Enviar diagnósticos de falhas e desempenho"],exact:true});
    await consent.waitFor();assert.equal(await consent.isChecked(),false);
    await consent.check();await page.getByRole("button",{name:labels["Salvar telemetria"],exact:true}).click();
    await page.getByRole("status").filter({hasText:labels["Telemetria salva."]}).waitFor();
    assert.equal((await page.evaluate(()=>window.__TELEMETRY_TEST__.status())).enabled,true);
    await consent.uncheck();await page.getByRole("button",{name:labels["Salvar telemetria"],exact:true}).click();
    await page.waitForFunction(()=>window.__TELEMETRY_TEST__.status().enabled===false);
    const writes=await page.evaluate(()=>window.__TELEMETRY_TEST__.calls.filter(call=>call.method==="telemetry.settings.set"));
    assert.deepEqual(writes.map(call=>call.params),[{enabled:true,endpoint:"https://telemetry.datapyn.com/v1/events"},{enabled:false,endpoint:"https://telemetry.datapyn.com/v1/events"}]);
    await page.getByLabel(labels["Endpoint HTTPS"],{exact:true}).fill("http://insecure.example.com/v1/events");
    await page.getByRole("button",{name:labels["Salvar telemetria"],exact:true}).click();await page.getByRole("alert").filter({hasText:"HTTPS required"}).waitFor();
    assert.equal((await page.evaluate(()=>window.__TELEMETRY_TEST__.status())).enabled,false);
    await page.goto(`${address}?locale=${locale}&fail=load`);await page.getByRole("alert").filter({hasText:"Diagnostics settings unavailable"}).waitFor();
    assert.equal(await page.getByRole("button",{name:labels["Salvar telemetria"],exact:true}).isDisabled(),true);
    console.log(`PASS ${locale}: opt-in disabled by default, explicit consent/revocation, HTTPS validation and settings failure without unrelated changes`);
  }
  assert.deepEqual(errors,[]);
}finally{await browser?.close();await server.close();}
