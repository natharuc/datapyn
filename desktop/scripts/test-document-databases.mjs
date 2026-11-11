import assert from "node:assert/strict";
import {mkdir} from "node:fs/promises";
import {dirname,resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {createServer} from "vite";
import {chromium} from "playwright";

const root=resolve(dirname(fileURLToPath(import.meta.url)),".."),route="/__document_databases_test",artifacts=resolve(root,"../.tooling");
const server=await createServer({root,cacheDir:"node_modules/.vite-document-databases-tests",plugins:[{name:"document-databases-fixture",configureServer(server){server.middlewares.use(route,async(_request,response)=>{
  response.setHeader("Content-Type","text/html");response.end(await server.transformIndexHtml(route,'<!doctype html><html><body><div id="root"></div><script type="module" src="/tests/document-databases.fixture.tsx"></script></body></html>'));
});}}],server:{host:"127.0.0.1",port:0,watch:null,hmr:false}});
let browser;await server.listen();await mkdir(artifacts,{recursive:true});
try{
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1160,height:840}}),errors=[];page.on("pageerror",error=>errors.push(error.message));
  const base=()=>`http://127.0.0.1:${server.httpServer.address().port}${route}`;
  const ft=text=>page.evaluate(text=>window.__DOCUMENT_DATABASES_TEST__.featureTranslate(text),text);
  const t=text=>page.evaluate(text=>window.__DOCUMENT_DATABASES_TEST__.translate(text),text);
  for(const locale of ["pt-BR","en-US"])for(const theme of ["dark","light"]){
    await page.goto(`${base()}?locale=${locale}&theme=${theme}`);await page.waitForFunction(()=>window.__DOCUMENT_DATABASES_TEST__);
    const modal=page.getByRole("dialog"),driver=modal.getByLabel(await t("Tipo do banco"),{exact:true});
    await driver.selectOption("elasticsearch");await modal.getByLabel(await t("Nome"),{exact:true}).fill("Elastic");
    await modal.getByLabel("Endpoint",{exact:true}).fill("https://elastic.example.net/");
    await modal.getByLabel(await t("Autenticação"),{exact:true}).selectOption("api_key");await modal.getByLabel("API key",{exact:true}).fill("synthetic-api-secret");
    await modal.getByRole("button",{name:await t("Testar conexão"),exact:true}).click();
    await page.waitForFunction(()=>window.__DOCUMENT_DATABASES_TEST__.calls.some(item=>item.method==="connection.test"));
    assert.equal(await modal.getByLabel(await t("Servidor"),{exact:true}).count(),0);assert.equal(await modal.getByLabel(await t("Túnel SSH"),{exact:true}).count(),0);
    const elastic=await page.evaluate(()=>window.__DOCUMENT_DATABASES_TEST__.calls.find(item=>item.method==="connection.test").params.config);
    assert.equal(elastic.api_key,"synthetic-api-secret");assert.equal(elastic.ssh_tunnel_id,null);
    await driver.selectOption("mongodb");await modal.getByLabel("URI MongoDB",{exact:true}).fill("mongodb+srv://reader:p%40ss@cluster.example.net/analysis?authSource=admin");
    await modal.getByRole("button",{name:await t("Testar conexão"),exact:true}).click();
    await page.waitForFunction(()=>window.__DOCUMENT_DATABASES_TEST__.calls.filter(item=>item.method==="connection.test").length===2);
    const mongo=await page.evaluate(()=>window.__DOCUMENT_DATABASES_TEST__.calls.filter(item=>item.method==="connection.test").at(-1).params.config);
    assert.equal(mongo.password,"p@ss");assert.equal(mongo.mongodb_uri.includes("@"),false);assert.equal(mongo.database,"analysis");
    await driver.selectOption("cosmosdb");await modal.getByLabel("Endpoint",{exact:true}).fill("https://account.documents.azure.com/");
    await modal.getByLabel(await t("Autenticação"),{exact:true}).selectOption("entra");
    await modal.getByLabel("Container",{exact:true}).fill("orders");await modal.getByLabel(await t("Banco"),{exact:true}).fill("analysis");
    await modal.getByRole("button",{name:await t("Testar conexão"),exact:true}).click();
    await page.waitForFunction(()=>window.__DOCUMENT_DATABASES_TEST__.calls.filter(item=>item.method==="connection.test").length===3);
    assert.equal(await modal.getByLabel(await t("Chave da conta"),{exact:true}).count(),0);
    assert.equal(await modal.evaluate(node=>node.scrollWidth<=node.clientWidth+1),true);
    await page.screenshot({path:resolve(artifacts,`document-connections-${theme}-${locale}.png`)});
    await page.goto(`${base()}?locale=${locale}&theme=${theme}&screen=workspace`);await page.waitForFunction(()=>window.__DOCUMENT_DATABASES_TEST__);
    await page.getByRole("button",{name:await t("Selecionar container"),exact:true}).click();await page.getByRole("option",{name:"orders",exact:true}).click();
    assert.equal(await page.evaluate(()=>window.__DOCUMENT_DATABASES_TEST__.contexts.at(-1).container),"orders");
    await page.getByRole("treeitem").filter({hasText:"orders"}).click({button:"right"});const menu=page.getByRole("menu");
    assert.equal(await menu.getByText("COUNT(*)",{exact:true}).count(),0);assert.equal(await menu.getByText(await t("Script DROP e CREATE"),{exact:true}).count(),0);
    await page.keyboard.press("Escape");await page.getByRole("button",{name:await ft("Para tabela"),exact:true}).click();
    const target=page.getByLabel(await ft("Conexão de destino"),{exact:true});assert.deepEqual(await target.locator("option").allTextContents(),["PostgreSQL · postgresql · target"]);
    assert.equal(await target.inputValue(),"sql");await page.getByRole("dialog").getByRole("button",{name:await ft("Fechar"),exact:true}).last().click();
  }
  assert.deepEqual(errors,[]);console.log("Document database forms, credential separation, container picker, explorer capability gating, export destinations and themes passed (PT/EN).");
}finally{await browser?.close();await server.close();}
