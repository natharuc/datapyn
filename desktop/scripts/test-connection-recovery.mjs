import assert from "node:assert/strict";
import {dirname,resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {createServer} from "vite";
import {chromium} from "playwright";

const root=resolve(dirname(fileURLToPath(import.meta.url)),".."),route="/__connection_recovery_test";
const server=await createServer({root,cacheDir:"node_modules/.vite-connection-recovery-tests",plugins:[{name:"connection-recovery-fixture",configureServer(server){server.middlewares.use(route,async(_request,response)=>{response.setHeader("Content-Type","text/html");response.end(await server.transformIndexHtml(route,'<!doctype html><html><body><div id="root"></div><script type="module" src="/tests/connection-recovery.fixture.tsx"></script></body></html>'));});}}],server:{host:"127.0.0.1",port:0,watch:null,hmr:false}});
let browser;await server.listen();
try{
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];page.on("pageerror",error=>errors.push(error.message));
  for(const locale of ["pt-BR","en-US"]){
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}${route}?locale=${locale}`);
    await page.locator(".new-session:not([disabled])").waitFor();await page.waitForFunction(()=>window.__CONNECTION_RECOVERY_TEST__?.editor()!==undefined);
    await page.evaluate(()=>window.__CONNECTION_RECOVERY_TEST__.seed());await page.waitForFunction(()=>window.__CONNECTION_RECOVERY_TEST__.editor()==="SELECT * FROM important_report;");
    const t=text=>page.evaluate(text=>window.__CONNECTION_RECOVERY_TEST__.translate(text),text),header=page.locator(".block-header").first();
    const reconnect=await t("Reconectar"),confirmTitle=await t("Reconectar este bloco?"),cancel=await t("Cancelar");
    const emit=(phase,id,ack)=>page.evaluate(([phase,id,ack])=>window.__CONNECTION_RECOVERY_TEST__.emit(phase,id,ack),[phase,id,ack]);
    await emit("recovering","first",false);await header.getByText(await t("Reconectando…"),{exact:true}).waitFor();assert.equal(await header.getByRole("button",{name:await t("Executar bloco ou seleção"),exact:true}).isDisabled(),true);
    await emit("blocked","first",true);await header.getByRole("button",{name:reconnect,exact:true}).click();
    const dialog=page.getByRole("dialog",{name:confirmTitle,exact:true});await dialog.waitFor();
    await page.keyboard.press("Escape");await dialog.waitFor({state:"hidden"});
    assert.equal(await page.evaluate(()=>window.__CONNECTION_RECOVERY_TEST__.calls.filter(call=>call.method==="connection.recover").length),0);
    await header.getByRole("button",{name:reconnect,exact:true}).click();await dialog.waitFor();await dialog.getByRole("button",{name:cancel,exact:true}).click();await dialog.waitFor({state:"hidden"});
    assert.equal(await page.evaluate(()=>window.__CONNECTION_RECOVERY_TEST__.calls.filter(call=>call.method==="connection.recover").length),0);
    await header.getByRole("button",{name:reconnect,exact:true}).click();await dialog.waitFor();await dialog.getByRole("button",{name:reconnect,exact:true}).click();
    await header.getByText(await t("Conexão recuperada"),{exact:true}).waitFor();
    let calls=await page.evaluate(()=>window.__CONNECTION_RECOVERY_TEST__.calls.filter(call=>call.method==="connection.recover"));assert.equal(calls.length,1);assert.equal(calls[0].params.acknowledge_state_loss,true);
    assert.equal(await page.evaluate(()=>window.__CONNECTION_RECOVERY_TEST__.snapshot().sessions[0].variables[0].name),"df");assert.equal(await page.evaluate(()=>window.__CONNECTION_RECOVERY_TEST__.editor()),"SELECT * FROM important_report;");
    await header.getByRole("button",{name:await t("Dispensar aviso"),exact:true}).click();await header.locator(".connection-recovery-status").waitFor({state:"hidden"});
    await emit("recovering","second",false);await emit("error","second",false);await page.evaluate(()=>window.__CONNECTION_RECOVERY_TEST__.mode("error"));await header.getByRole("button",{name:reconnect,exact:true}).click();await header.getByRole("button",{name:reconnect,exact:true}).waitFor();
    await page.evaluate(()=>window.__CONNECTION_RECOVERY_TEST__.mode("ready"));await header.getByRole("button",{name:reconnect,exact:true}).click();await header.getByText(await t("Conexão recuperada"),{exact:true}).waitFor();
    calls=await page.evaluate(()=>window.__CONNECTION_RECOVERY_TEST__.calls.filter(call=>call.method==="connection.recover"));assert.equal(calls.length,3);assert.equal(calls[1].params.acknowledge_state_loss,false);assert.equal(calls[2].params.acknowledge_state_loss,false);
    assert.equal(await page.evaluate(()=>window.__CONNECTION_RECOVERY_TEST__.calls.filter(call=>call.method==="execution.run").length),0);assert.deepEqual(await page.evaluate(()=>window.__CONNECTION_RECOVERY_TEST__.failures),[]);
    console.log(`PASS ${locale}: actual App/Monaco recovery indicator, explicit state-loss confirmation, Escape/cancel, retry in the same tab, preserved data/code and no SQL replay`);
  }
  assert.deepEqual(errors,[]);
}finally{await browser?.close();await server.close();}
