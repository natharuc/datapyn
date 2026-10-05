import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { chromium } from "playwright";

// First run on a clean checkout: npm exec playwright install chromium.
// This runner launches an isolated headless browser; it never opens or drives
// a desktop window, and its fixture uses no user settings or database secrets.

const root=resolve(dirname(fileURLToPath(import.meta.url)),"..");
const route="/__completion_test";
const server=await createServer({root,cacheDir:"node_modules/.vite-completion-tests",plugins:[{
  name:"completion-fixture",
  configureServer(server){server.middlewares.use(route,async(_request,response)=>{
    response.setHeader("Content-Type","text/html");
    response.end(await server.transformIndexHtml(route,'<!doctype html><html><body><div id="root" style="width:720px;height:250px;contain:paint;transform:translateZ(0)"></div><script type="module" src="/tests/completion.fixture.tsx"></script></body></html>'));
  });},
}],server:{host:"127.0.0.1",port:0,strictPort:false}});
let browser;
let passed=0;
const failures=[];
await server.listen();
try {
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1000,height:700}});
  page.setDefaultTimeout(5000);
  const browserErrors=[];page.on("pageerror",error=>browserErrors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}${route}`);
  await page.waitForFunction(()=>window.completionTest?.ready);
  async function test(name,run){
    try{await run();passed++;console.log(`PASS ${name}`);}
    catch(error){failures.push({name,error});console.error(`FAIL ${name}: ${error.message}`);console.log(await page.evaluate(()=>({position:window.completionTest.editor().getPosition(),code:window.completionTest.editor().getValue(),focus:window.completionTest.editor().hasTextFocus(),calls:window.completionTest.calls.slice(-3).map(({method,params})=>({method,params})),widgets:[...document.querySelectorAll(".suggest-widget")].map(w=>({class:w.className,display:getComputedStyle(w).display,rect:w.getBoundingClientRect().toJSON(),labels:[...w.querySelectorAll(".label-name")].map(e=>e.textContent)}))})));}
    finally{
      await page.keyboard.press("Escape");
      // Resolve cancelled mock requests so only one latest intent remains queued.
      await page.evaluate(()=>{const p=window.completionTest;p.calls.forEach((call,index)=>{if(call.resolve&&!call.resolved)p.reply(index,[]);});});
      await page.waitForTimeout(10);
    }
  }
  const context=(dbType="sqlite",database="main",schema="main",columns=["customer_id","customer_name"])=>({
    sessionId:"test-session",connectionId:"test-connection",database,schema,dbType,variables:[],tables:[`${schema}.customers`],
    schemaSnapshot:{db_type:dbType,database,current_schema:schema,tables:{[`${schema}.customers`]:{name:"customers",schema,columns:columns.map(name=>({name,type:"TEXT"}))}}},
  });
  const configure=value=>page.evaluate(value=>window.completionTest.configure(value),value);
  async function labels(expected){await page.waitForFunction(expected=>expected.every(label=>window.completionTest.labels().includes(label)),expected,{timeout:3000});return page.evaluate(()=>window.completionTest.labels());}
  const value=()=>page.evaluate(()=>window.completionTest.editor().getValue());

  for(const [dbType,quote] of [["sqlserver",name=>`[${name}]`],["mysql",name=>`\`${name}\``],["mariadb",name=>`\`${name}\``],["databricks",name=>`\`${name}\``],["postgresql",name=>`"${name}"`],["sqlite",name=>`"${name}"`]]){
    await test(`${dbType}: ordinary typing opens focused table suggestions without a shortcut`,async()=>{
      await configure({code:"SELECT * FROM |",context:context(dbType)});
      await page.keyboard.type("cust",{delay:20});
      const current=await labels(["customers"]);assert(!current.includes("main.customers"));
      await page.keyboard.press("Tab");assert.equal(await value(),`SELECT * FROM ${quote("customers")}`);
    });
    await test(`${dbType}: WHERE letters automatically suggest unqualified bound fields`,async()=>{
      await configure({code:"SELECT * FROM customers WHERE |",context:context(dbType)});
      await page.keyboard.type("customer_n",{delay:15});await labels(["customer_name"]);
      await page.keyboard.press("Tab");assert.equal(await value(),`SELECT * FROM customers WHERE ${quote("customer_name")}`);
    });
    await test(`${dbType}: JOIN typing and delayed inference retain aliases for ambiguous fields`,async()=>{
      const scoped=context(dbType,"main","main",["id","customer_name"]);
      scoped.tables.push("main.orders");scoped.schemaSnapshot.tables["main.orders"]={name:"orders",schema:"main",columns:[{name:"id",type:"INTEGER"}]};
      await configure({code:"SELECT | FROM customers c JOIN orders o ON c.id=o.id",context:scoped});
      const before=await page.evaluate(()=>window.completionTest.calls.length);
      await page.keyboard.type("i",{delay:20});const current=await labels(["c.id","o.id"]);assert(!current.includes("id"));
      await page.waitForFunction(before=>window.completionTest.calls.slice(before).some(call=>call.method==="language.complete"),before);
      await page.evaluate(before=>{const p=window.completionTest,index=p.calls.findIndex((call,index)=>index>=before&&call.method==="language.complete");p.reply(index,[{label:"id",kind:"column",insert_text:"id"}]);},before);
      await page.waitForTimeout(70);assert(!(await labels(["c.id","o.id"])).includes("id"));
      await page.keyboard.press("Tab");assert.equal(await value(),`SELECT ${quote("c")}.${quote("id")} FROM customers c JOIN orders o ON c.id=o.id`);
    });
    await test(`${dbType}: automatic alias fields appear and Tab inserts a valid identifier while IPC is held`,async()=>{
      await configure({code:"SELECT c| FROM customers c",context:context(dbType)});
      await page.keyboard.type(".");await labels(["customer_id","customer_name"]);
      await page.keyboard.press("Tab");assert.equal(await value(),`SELECT c.${quote("customer_id")} FROM customers c`);
    });
  }
  await test("Databricks table search matches a word inside the name, with prefix matches first",async()=>{
    const scoped=context("databricks","warehouse","finance");
    scoped.tables=["finance.movimentocobranca","finance.gecon_ft_movimentos_premio"];
    scoped.schemaSnapshot.tables={
      "finance.movimentocobranca":{name:"movimentocobranca",schema:"finance",catalog:"warehouse",columns:[]},
      "finance.gecon_ft_movimentos_premio":{name:"gecon_ft_movimentos_premio",schema:"finance",catalog:"warehouse",columns:[]},
    };
    await configure({code:"SELECT * FROM |",context:scoped});
    await page.keyboard.type("movimento",{delay:15});const current=await labels(["movimentocobranca","gecon_ft_movimentos_premio"]);
    assert(current.indexOf("movimentocobranca")<current.indexOf("gecon_ft_movimentos_premio"));
    await page.keyboard.press("Tab");assert.equal(await value(),"SELECT * FROM `movimentocobranca`");
  });
  for(const [qualifier,expected,wrong,schema] of [['"Analytics"',"UpperOrders","lower_orders","Analytics"],["ANALYTICS","lower_orders","UpperOrders","analytics"]]){
    await test(`PostgreSQL: ${qualifier} schema suggestions and remote enrichment preserve exact namespace identity`,async()=>{
      const scoped=context("postgresql","warehouse","analytics");
      scoped.tables=["Analytics.UpperOrders","analytics.lower_orders","Analytics.shared","analytics.shared"];
      scoped.schemaSnapshot.tables={"Analytics.UpperOrders":{name:"UpperOrders",schema:"Analytics",columns:[]},"analytics.lower_orders":{name:"lower_orders",schema:"analytics",columns:[]},"Analytics.shared":{name:"shared",schema:"Analytics",columns:[]},"analytics.shared":{name:"shared",schema:"analytics",columns:[]}};
      await configure({code:`SELECT * FROM ${qualifier}|`,context:scoped});
      const before=await page.evaluate(()=>window.completionTest.calls.length);await page.keyboard.type(".");
      const current=await labels([expected,"shared"]);assert(!current.includes(wrong));
      await page.waitForFunction(before=>window.completionTest.calls.slice(before).some(call=>call.method==="language.complete"),before);
      await page.evaluate(({before,schema,wrong})=>{const p=window.completionTest,index=p.calls.findIndex((call,index)=>index>=before&&call.method==="language.complete");p.reply(index,[{label:`${schema==="Analytics"?"analytics":"Analytics"}.${wrong}`,kind:"table"},{label:"shared",kind:"table"}]);},{before,schema,wrong});
      await page.waitForTimeout(60);const enriched=await labels([expected,"shared"]);assert(!enriched.includes(wrong));
      await page.keyboard.type(expected.slice(0,2),{delay:20});await labels([expected]);
      await page.keyboard.press("Tab");assert.equal(await value(),`SELECT * FROM ${qualifier}."${expected}"`);
    });
  }
  await test("SQL keyword spaces open tables automatically and further letters reach objects beyond the first 500",async()=>{
    const scoped=context();
    scoped.tables=[...Array.from({length:1200},(_,index)=>`main.early_${index}`),"main.zebra"];
    scoped.schemaSnapshot.tables={"main.zebra":{name:"zebra",schema:"main",columns:[]}};
    await configure({code:"SELECT *|",context:scoped});
    await page.keyboard.type(" FROM ",{delay:15});await labels(["main.early_0"]);
    await page.keyboard.type("zeb",{delay:20});await labels(["zebra"]);
    await page.keyboard.press("Tab");assert.equal(await value(),'SELECT * FROM "zebra"');
  });
  await test("manual shortcut completion and remote enrichment keep focused names short without duplicate rows",async()=>{
    await configure({code:"SELECT * FROM cust|",context:context("mysql","main","main")});
    const before=await page.evaluate(()=>window.completionTest.calls.length);
    await page.evaluate(()=>window.completionTest.force());await labels(["customers"]);
    await page.waitForFunction(before=>window.completionTest.calls.slice(before).some(call=>call.method==="language.complete"),before);
    await page.evaluate(before=>{const p=window.completionTest,index=p.calls.findIndex((call,index)=>index>=before&&call.method==="language.complete");p.reply(index,[{label:"main.customers",kind:"table",insert_text:"`main`.`customers`"}]);},before);
    await page.waitForTimeout(80);const current=await labels(["customers"]);
    assert.equal(current.filter(label=>label==="customers").length,1);assert(!current.includes("main.customers"));
    await page.keyboard.press("Tab");assert.equal(await value(),"SELECT * FROM `customers`");
  });
  await test("a late metadata delivery refreshes automatic letter completion without another key or shortcut",async()=>{
    await configure({code:"SELECT * FROM |",context:{...context(),tables:[],schemaSnapshot:undefined}});
    await page.keyboard.type("cust",{delay:15});await page.waitForTimeout(60);
    assert(!await page.evaluate(()=>window.completionTest.labels().includes("customers")));
    await page.evaluate(next=>window.completionTest.context(next),context());await labels(["customers"]);
  });
  await test("Python ordinary letter typing suggests dataframe variables before remote inference",async()=>{
    await configure({code:"|",language:"python",context:{...context(),variables:[{name:"df_customers",type:"DataFrame",columns:["id"]}]}});
    await page.keyboard.type("df_c",{delay:20});await labels(["df_customers"]);
    await page.keyboard.press("Tab");assert.equal(await value(),"df_customers");
  });
  await test("Ctrl+Space suggests unqualified SELECT fields from FROM to the right of the cursor",async()=>{
    await configure({code:"SELECT | FROM customers c",context:context()});
    await page.keyboard.press("Control+Space");await labels(["customer_id","customer_name"]);
  });
  await test("quoted partial fields replace the whole identifier without duplicate quotes",async()=>{
    await configure({code:'SELECT c."customer_i|x" FROM customers c',context:context("postgresql")});
    await page.keyboard.press("Control+Space");await labels(["customer_id"]);
    await page.keyboard.press("Tab");assert.equal(await value(),'SELECT c."customer_id" FROM customers c');
  });
  await test("changing database and schema refreshes a visible widget and drops old fields",async()=>{
    await configure({code:"SELECT c.| FROM customers c",context:context()});
    await page.keyboard.press("Control+Space");await labels(["customer_id"]);
    await page.evaluate(next=>window.completionTest.context(next),context("postgresql","analytics","sales",["new_scope_id"]));
    const current=await labels(["new_scope_id"]);assert(!current.includes("customer_id"));
  });
  await test("a late response from the previous database cannot pollute the new scope widget",async()=>{
    await configure({code:"SELECT c.| FROM customers c",context:{...context(),tables:[],schemaSnapshot:undefined}});
    const before=await page.evaluate(()=>window.completionTest.calls.length);await page.keyboard.press("Control+Space");
    await page.waitForFunction(before=>window.completionTest.calls.slice(before).some(call=>call.method==="language.complete"),before);
    await page.evaluate(next=>window.completionTest.context(next),context("postgresql","new_db","sales",["new_scope_id"]));
    await labels(["new_scope_id"]);
    await page.evaluate(before=>{const p=window.completionTest,index=p.calls.findIndex((call,index)=>index>=before&&call.method==="language.complete");p.reply(index,[{label:"previous_database_id",kind:"column"}]);},before);
    await page.waitForTimeout(100);const current=await labels(["new_scope_id"]);assert(!current.includes("previous_database_id"));
  });
  await test("JOIN alias fields come only from the bound relation",async()=>{
    const joined=context();joined.tables.push("main.orders");joined.schemaSnapshot.tables["main.orders"]={name:"orders",schema:"main",columns:[{name:"order_id",type:"INTEGER"}]};
    await configure({code:"SELECT o| FROM customers c JOIN orders o ON c.customer_id = o.order_id",context:joined});
    await page.keyboard.type(".");const current=await labels(["order_id"]);assert(!current.includes("customer_name"));
  });
  for(const source of ["customers c JOIN (SELECT 1 AS id) d ON 1=1","customers c JOIN pending p ON 1=1"]){
    await test(`SQL joins qualify known fields while the other source is not yet inferred: ${source}`,async()=>{
      const scoped=context("sqlite","main","main",["id"]);
      scoped.schemaSnapshot.tables["main.pending"]={name:"pending",schema:"main",columns:[]};
      await configure({code:`SELECT | FROM ${source}`,context:scoped});
      await page.keyboard.type("id",{delay:20});const current=await labels(["c.id"]);assert(!current.includes("id"));
      await page.keyboard.press("Tab");assert.equal(await value(),`SELECT "c"."id" FROM ${source}`);
    });
  }
  await test("late metadata replaces No suggestions without another keypress",async()=>{
    const cold={...context(),tables:[],schemaSnapshot:undefined};
    await configure({code:"SELECT c.| FROM customers c",context:cold});
    await page.keyboard.press("Control+Space");await page.waitForTimeout(50);
    assert(!await page.evaluate(()=>window.completionTest.labels().includes("customer_id")));
    await page.evaluate(next=>window.completionTest.context(next),context());
    await labels(["customer_id","customer_name"]);
  });
  for(const [dbType,schema,transient] of [["postgresql","public",false],["sqlserver","dbo",false],["postgresql","public",true]]){
    await test(`${dbType}: unresolved ${transient?"transient":"saved"} defaults resolve to ${schema} and refresh the actual editor`,async()=>{
      await page.evaluate(async({dbType,schema,transient})=>{window.defaultDelivery=await window.completionTest.defaultScope({dbType,database:"configured_db",schema,transient});},{dbType,schema,transient});
      await page.keyboard.press("Control+Space");await page.waitForTimeout(30);
      assert(!await page.evaluate(()=>window.completionTest.labels().includes("resolved_default_id")));
      const scope=await page.evaluate(()=>window.defaultDelivery.deliver());
      assert.deepEqual(scope,{database:"configured_db",schema,tables:[`${schema}.customers`]});
      await labels(["resolved_default_id"]);
    });
  }
  await test("remote-only inference enriches an empty member widget without changing the model",async()=>{
    await configure({code:"SELECT derived.| FROM (SELECT 1 AS computed_id) derived",context:context()});
    const before=await page.evaluate(()=>window.completionTest.calls.length);
    await page.keyboard.press("Control+Space");
    await page.waitForFunction(before=>window.completionTest.calls.slice(before).some(call=>call.method==="language.complete"),before);
    await page.evaluate(before=>{const p=window.completionTest,index=p.calls.findIndex((call,index)=>index>=before&&call.method==="language.complete");p.reply(index,[{label:"computed_id",kind:"column",insert_text:'"computed_id"'}]);},before);
    await labels(["computed_id"]);assert.equal(await value(),"SELECT derived. FROM (SELECT 1 AS computed_id) derived");
  });
  await test("Escape keeps cancelled remote replies and later metadata from reopening suggestions",async()=>{
    await configure({code:"SELECT c.| FROM customers c",context:{...context(),tables:[],schemaSnapshot:undefined}});
    const before=await page.evaluate(()=>window.completionTest.calls.length);await page.keyboard.press("Control+Space");
    await page.waitForFunction(before=>window.completionTest.calls.slice(before).some(call=>call.method==="language.complete"),before);
    await page.keyboard.press("Escape");
    await page.evaluate(({before,next})=>{const p=window.completionTest,index=p.calls.findIndex((call,index)=>index>=before&&call.method==="language.complete");p.reply(index,[{label:"stale_id",kind:"column"}]);p.context(next);},{before,next:context()});
    await page.waitForTimeout(200);assert.deepEqual(await page.evaluate(()=>window.completionTest.labels()),[]);
  });
  await test("manual SQL completion remains available when automatic completion is disabled",async()=>{
    await configure({code:"SELECT c| FROM customers c",context:context(),preferences:{autocomplete:false}});
    await page.keyboard.type(".");await page.waitForTimeout(150);assert.deepEqual(await page.evaluate(()=>window.completionTest.labels()),[]);
    await page.keyboard.press("Control+Space");await labels(["customer_id"]);
  });
  await test("Python SQL dataframe fields appear in member and string-column positions",async()=>{
    const python={...context(),variables:[{name:"df_customers",type:"DataFrame",module:"pandas.core.frame",columns:["customer_id","customer name"]}]};
    await configure({code:"df_customers|",language:"python",context:python});
    await page.keyboard.type(".");await labels(["customer_id"]);
    await configure({code:'df_customers["customer n|"]',language:"python",context:python});
    await page.keyboard.press("Control+Space");await labels(["customer name"]);
    await page.keyboard.press("Tab");assert.equal(await value(),'df_customers["customer name"]');
  });
  await test("suggestion widgets escape transformed dock paint containment",async()=>{
    await configure({code:"\n\n\n\n\n\nSELECT c.| FROM customers c",context:context()});
    await page.keyboard.press("Control+Space");await labels(["customer_id"]);
    assert(await page.evaluate(()=>{const widget=[...document.querySelectorAll(".suggest-widget")].find(node=>node.checkVisibility());return Boolean(widget?.closest(".datapyn-monaco-overflow")?.parentElement===document.body&&widget.getBoundingClientRect().width>100);}));
  });
  await test("database picker searches locally, changes raw scope and reloads editor suggestions",async()=>{
    await configure({code:"SELECT c.| FROM customers c",context:context("postgresql","main","public"),picker:true});
    await page.getByRole("button",{name:"Selecionar Banco",exact:true}).click();
    await page.getByRole("option",{name:"analytics",exact:true}).waitFor();
    const before=await page.evaluate(()=>window.completionTest.calls.filter(call=>call.method==="explorer.list").length);
    await page.getByRole("combobox",{name:"Pesquisar Banco",exact:true}).fill("ana");
    assert.equal(await page.getByRole("option").count(),1);
    assert.equal(await page.evaluate(()=>window.completionTest.calls.filter(call=>call.method==="explorer.list").length),before);
    await page.getByRole("option",{name:"analytics",exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.block-scope-trigger[aria-label="Selecionar Banco"] .block-scope-value')?.textContent==="analytics");
    assert.deepEqual(await page.evaluate(()=>window.completionTest.scopeChanges.at(-1)),{database:"analytics"});
    await page.waitForTimeout(50);await page.evaluate(()=>window.completionTest.editor().focus());
    await page.keyboard.press("Control+Space");const current=await labels(["analytics_id"]);assert(!current.includes("customer_id"));
  });
  await test("schema picker filters and Enter applies only the selected schema in the current database",async()=>{
    await configure({code:"SELECT c.| FROM customers c",context:context("postgresql","analytics","public"),picker:true});
    await page.getByRole("button",{name:"Selecionar schema",exact:true}).click();
    await page.getByRole("option",{name:"finance",exact:true}).waitFor();
    await page.getByRole("combobox").fill("fin");
    await page.waitForFunction(()=>document.querySelector('[role="option"].active')?.textContent==="finance");
    await page.keyboard.press("Enter");
    await page.waitForFunction(()=>document.querySelector('.block-scope-trigger[aria-label="Selecionar schema"] .block-scope-value')?.textContent==="finance");
    assert.deepEqual(await page.evaluate(()=>window.completionTest.scopeChanges.at(-1)),{database:"analytics",schema:"finance"});
    await page.waitForTimeout(50);await page.evaluate(()=>window.completionTest.editor().focus());
    await page.keyboard.press("Control+Space");await labels(["finance_id"]);
  });
  for(const width of [320,720]){
    await test(`database/schema controls and portal fit a ${width}px viewport`,async()=>{
      await page.setViewportSize({width,height:700});
      await page.evaluate(width=>{document.body.style.minWidth="0";document.getElementById("root").style.width=`${width}px`;},width);
      await configure({code:"SELECT c.| FROM customers c",context:context("postgresql","database_with_a_very_long_name","schema_with_a_very_long_name"),picker:true});
      const controls=await page.locator(".block-scope-trigger").evaluateAll(nodes=>nodes.map(node=>{const r=node.getBoundingClientRect();return {visible:node.checkVisibility(),left:r.left,right:r.right,width:r.width};}));
      assert.equal(controls.length,2);assert(controls.every(control=>control.visible&&control.width>0&&control.left>=0&&control.right<=width));
      await page.getByRole("button",{name:"Selecionar Banco",exact:true}).click();
      await page.getByRole("option",{name:"analytics",exact:true}).waitFor();
      const popover=await page.locator(".block-scope-popover").boundingBox();assert(popover.x>=0&&popover.x+popover.width<=width);
      assert(await page.locator(".block-scope-popover").evaluate(node=>node.parentElement===document.body));
    });
  }
  assert.deepEqual(browserErrors,[],"Browser console errors");
} finally {await browser?.close();await server.close();}
console.log(`${passed} real Monaco headless scenarios passed; ${failures.length} failed.`);
if(failures.length)process.exitCode=1;
