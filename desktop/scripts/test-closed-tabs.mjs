import assert from "node:assert/strict";
import {dirname,resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {createServer} from "vite";
import {chromium} from "playwright";

const root=resolve(dirname(fileURLToPath(import.meta.url)),".."),route="/__closed_tabs_test";
const server=await createServer({root,cacheDir:"node_modules/.vite-closed-tabs-tests",plugins:[{name:"closed-tabs-fixture",configureServer(server){server.middlewares.use(route,async(_request,response)=>{
  response.setHeader("Content-Type","text/html");response.end(await server.transformIndexHtml(route,'<!doctype html><html><body><div id="root"></div><script type="module" src="/tests/closed-tabs.fixture.tsx"></script></body></html>'));
});}}],server:{host:"127.0.0.1",port:0,watch:null,hmr:false}});
let browser;
await server.listen();
try{
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on("pageerror",error=>errors.push(error.message));
  const address=`http://127.0.0.1:${server.httpServer.address().port}${route}`;
  const state=()=>page.evaluate(()=>window.__CLOSED_TABS_TEST__.snapshot());
  const count=expected=>page.waitForFunction(expected=>window.__CLOSED_TABS_TEST__.snapshot().closedSessionCount===expected,expected);
  const editorReady=()=>page.waitForFunction(()=>window.__CLOSED_TABS_TEST__.editor()?.code===window.__CLOSED_TABS_TEST__.current()?.blocks.find(block=>block.id===window.__CLOSED_TABS_TEST__.current()?.focusedBlockId)?.code);
  const focusEditor=()=>page.locator('.dock-editor .monaco-editor textarea').first().focus();
  const titles=async()=> (await state()).sessions.map(session=>session.title);
  for(const locale of ["pt-BR","en-US"]){
    await page.goto(`${address}?locale=${locale}`);await page.waitForFunction(()=>window.__CLOSED_TABS_TEST__?.snapshot().runtimeStatus==="ready");
    await page.locator(".new-session:not([disabled])").waitFor();await editorReady();
    const labels=await page.evaluate(()=>Object.fromEntries(["Mais","Reabrir aba fechada","Salvar alterações?","Voltar","Descartar","Fechar todas","Fechar análises","Descartar e fechar","Atalhos","Configurações","Atualizar schema","Atalho","Fechar","Reabrir aba fechada"].map(text=>[text,window.__CLOSED_TABS_TEST__.translate(text)])));
    await page.getByRole("button",{name:labels.Mais,exact:true}).click();
    assert.equal(await page.getByRole("menuitem",{name:labels["Reabrir aba fechada"],exact:true}).isDisabled(),true);
    await page.keyboard.press("Escape");
    await focusEditor();await page.keyboard.press("Control+Shift+t");await count(0);assert.equal((await state()).sessions.length,1);
    const code=Array.from({length:220},(_,index)=>`SELECT ${index+1};`).join("\n");
    const originalId=await page.evaluate(code=>window.__CLOSED_TABS_TEST__.seed("Recovered analysis",code,true),code);await editorReady();
    const originalCode=await page.evaluate(()=>window.__CLOSED_TABS_TEST__.editor().code);
    await page.evaluate(()=>window.__CLOSED_TABS_TEST__.select(120,3,120,8));
    // Ctrl+W opens the actual modified-document dialog; cancellation records nothing.
    await page.keyboard.press("Control+w");
    const saveDialog=page.getByRole("dialog",{name:labels["Salvar alterações?"],exact:true});await saveDialog.waitFor();
    await page.keyboard.press("Control+Shift+t");await count(0);
    await saveDialog.getByRole("button",{name:labels.Voltar,exact:true}).click();
    assert.equal((await state()).activeId,originalId);assert.deepEqual(await titles(),["Recovered analysis"]);
    await page.getByRole("button",{name:"Fechar Recovered analysis",exact:true}).click();await saveDialog.waitFor();
    await saveDialog.getByRole("button",{name:labels.Descartar,exact:true}).click();await count(1);await editorReady();
    await focusEditor();await page.keyboard.press("Control+Shift+t");await count(0);await editorReady();
    const recovered=await state();assert.notEqual(recovered.activeId,originalId);assert.deepEqual(await titles(),["Recovered analysis"]);
    const restored=await page.evaluate(()=>window.__CLOSED_TABS_TEST__.editor());assert.equal(restored.code,originalCode);assert.equal(restored.focused,true);
    assert.deepEqual({line:restored.selection.startLineNumber,column:restored.selection.startColumn,end:restored.selection.endColumn},{line:120,column:3,end:8});assert.ok(restored.scrollTop>0);
    assert.equal((await page.evaluate(()=>window.__CLOSED_TABS_TEST__.calls.filter(call=>call.method==="execution.run"))).length,0);

    // A regular tab closes with X; the app menu reopens it, retaining its position.
    await page.evaluate(()=>window.__CLOSED_TABS_TEST__.seed("Recovered analysis", "SELECT 1;",false));
    await page.locator(".new-session").click();await editorReady();await page.evaluate(()=>window.__CLOSED_TABS_TEST__.seed("Second analysis","SELECT 2;",false));await editorReady();await page.evaluate(()=>window.__CLOSED_TABS_TEST__.saved());
    await page.getByRole("button",{name:"Fechar Second analysis",exact:true}).click();await count(1);
    await page.getByRole("button",{name:labels.Mais,exact:true}).click();await page.getByRole("menuitem",{name:labels["Reabrir aba fechada"],exact:true}).click();await count(0);await editorReady();
    assert.deepEqual(await titles(),["Recovered analysis","Second analysis"]);
    await page.getByRole("button",{name:"Fechar Second analysis",exact:true}).click();await count(1);
    await page.locator(".session-tab").first().click({button:"right"});await page.locator(".tab-context").getByRole("button",{name:labels["Reabrir aba fechada"],exact:true}).click();await count(0);await editorReady();
    assert.deepEqual(await titles(),["Recovered analysis","Second analysis"]);

    // The actual tab context menu closes a group; repeated shortcuts unwind LIFO.
    await page.locator(".session-tab").last().click({button:"right"});await page.locator(".tab-context").getByRole("button",{name:labels["Fechar todas"],exact:true}).click();
    const bulk=page.getByRole("dialog",{name:labels["Fechar análises"],exact:true});await bulk.waitFor();
    await bulk.getByRole("button",{name:labels["Descartar e fechar"],exact:true}).click();await count(2);await editorReady();
    await focusEditor();await page.keyboard.press("Control+Shift+t");await count(1);await editorReady();assert.deepEqual(await titles(),["Second analysis"]);
    await focusEditor();await page.keyboard.press("Control+Shift+t");await count(0);await editorReady();assert.deepEqual(await titles(),["Recovered analysis","Second analysis"]);

    // Legacy Ctrl+Shift+T schema settings migrate; both editable bindings are visible.
    await page.getByRole("button",{name:labels.Configurações,exact:true}).click();
    const settings=page.getByRole("dialog",{name:labels.Configurações,exact:true});await settings.waitFor();
    await settings.getByRole("button",{name:labels.Atalhos,exact:true}).click();
    assert.equal(await settings.getByLabel(`${labels.Atalho} ${labels["Reabrir aba fechada"]}`,{exact:true}).inputValue(),"Ctrl+Shift+T");
    assert.equal(await settings.getByLabel(`${labels.Atalho} ${labels["Atualizar schema"]}`,{exact:true}).inputValue(),"Ctrl+Alt+R");
    await settings.getByRole("button",{name:labels.Fechar,exact:true}).click();
    await page.getByRole("button",{name:"Fechar Second analysis",exact:true}).click();await count(1);
    assert.deepEqual(await page.evaluate(()=>window.__CLOSED_TABS_TEST__.failures),[]);
    await page.reload();await page.waitForFunction(()=>window.__CLOSED_TABS_TEST__?.snapshot().runtimeStatus==="ready");await page.locator(".new-session:not([disabled])").waitFor();await count(0);
    console.log(`PASS ${locale}: real App/Monaco shortcut, cancel/discard, selection/scroll/focus, X/menu, bulk LIFO, legacy shortcut migration and app-lifetime history`);
  }
  assert.deepEqual(errors,[]);
}finally{await browser?.close();await server.close();}
