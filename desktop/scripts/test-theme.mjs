import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { chromium } from "playwright";

// An isolated headless CSS fixture; never opens or controls a desktop window.
const root=resolve(dirname(fileURLToPath(import.meta.url)),"..");
const route="/__theme_test",output=resolve(root,"../.tooling/theme-previews");
const server=await createServer({root,cacheDir:"node_modules/.vite-theme-tests",plugins:[{
  name:"theme-fixture",configureServer(server){server.middlewares.use(route,async(_request,response)=>{
    response.setHeader("Content-Type","text/html");
    response.end(await server.transformIndexHtml(route,`<!doctype html><html><head><style>
      /* Fixtures can validate 320px panels below the desktop's minimum width. */
      body {min-width:0!important;min-height:0!important;overflow:auto!important;}
      html,#root {height:auto!important;overflow:visible!important;}
      #theme-fixture {padding:12px;max-width:1280px;margin:auto;}
      .preview-grid {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:12px 0;}
      .preview-panel {min-width:0;border:1px solid var(--border);background:var(--panel);}
      .preview-panel.connections-sidebar,.preview-panel.object-explorer {height:190px;}
      .preview-panel .connection-tree-row,.preview-panel .explorer-row {height:29px;padding:0 10px;}
      .preview-panel.variable-inspector {height:auto;}
      .preview-panel.modal {width:auto;max-width:100%;}
      .preview-panel.block-scope-popover {position:static;width:auto;max-width:100%;align-self:start;}
      .preview-panel.pynia-panel {height:320px;}
      .preview-code {padding:12px;height:65px;font-family:'Ubuntu Mono',monospace;}
      .results-panel {min-height:100px;}
      .preview-dock {height:30px;margin-top:12px;}
      .preview-dock .dv-tab {padding:6px 12px;}
      @media(max-width:800px){.preview-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
      @media(max-width:440px){.preview-grid{grid-template-columns:minmax(0,1fr);}.app-header{padding:0 8px;}.app-menu{margin-left:8px;}.app-menu button{padding:6px 4px;}.workspace-toolbar{padding-inline:6px;}}
      </style></head><body><div id="root"></div><script type="module" src="/tests/theme.fixture.tsx"></script></body></html>`));
  });},
}],server:{host:"127.0.0.1",port:0,strictPort:false}});
let browser,passed=0;
await server.listen();
try {
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({reducedMotion:"reduce"});const errors=[];page.on("pageerror",error=>errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}${route}`);
  await page.waitForSelector(".explorer-search input");await page.evaluate(()=>document.fonts.ready);
  await mkdir(output,{recursive:true});
  for(const theme of ["dark","light"]) for(const width of [320,720,1280]) for(const [font,fontSize] of [["Ubuntu",12],["Consolas",16]]) {
    await page.setViewportSize({width,height:900});
    await page.evaluate(({theme,font,fontSize})=>{document.documentElement.dataset.theme=theme;document.documentElement.style.fontFamily=`${font},sans-serif`;document.documentElement.style.fontSize=`${fontSize}px`;document.querySelector(".datapyn-dock").className=`datapyn-dock dockview-theme-${theme} preview-dock`;},{theme,font,fontSize});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await page.waitForFunction(()=>[...document.querySelectorAll(".agent-icon img")].every(image=>image.complete&&image.naturalWidth>0));
    const name=`${theme}-${width}-${font}-${fontSize}`;
    const checks=await page.evaluate(()=>{
      const colors=color=>color.match(/[\d.]+/g).map(Number),luminance=color=>colors(color).slice(0,3).map(value=>{value/=255;return value<=.04045?value/12.92:((value+.055)/1.055)**2.4;}).reduce((sum,value,index)=>sum+value*[.2126,.7152,.0722][index],0);
      const ratio=(a,b)=>(Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05);
      function surface(element){for(let node=element;node;node=node.parentElement){const bg=getComputedStyle(node).backgroundColor;if(colors(bg)[3]!==0)return bg;}return getComputedStyle(document.documentElement).backgroundColor;}
      const search=[...document.querySelectorAll(".explorer-search,.connections-search,.variable-filter>label,.variable-archive-search,.grid-filter,.block-scope-search")].map(element=>{
        const input=element.querySelector("input"),box=element.getBoundingClientRect(),rect=input.getBoundingClientRect(),style=getComputedStyle(input);
        return {class:element.className,transparent:style.backgroundColor==="rgba(0, 0, 0, 0)",borderless:parseFloat(style.borderTopWidth)===0,padding:parseFloat(style.paddingTop)+parseFloat(style.paddingBottom),fits:rect.left>=box.left&&rect.right<=box.right&&rect.top>=box.top&&rect.bottom<=box.bottom,textContrast:ratio(style.color,surface(input)),placeholderContrast:ratio(getComputedStyle(input,"::placeholder").color,surface(input))};
      });
      const chrome=[...document.querySelectorAll(".session-tab.active,.result-tabs,.result-tabs button.active,.add-block-row button,.block-run,.driver-options button,.modal,.pynia-panel,.pynia-header,.pynia-composer,.dv-tab,.dv-tabs-and-actions-container")].map(element=>({class:element.className,background:surface(element),luminance:luminance(surface(element)),contrast:ratio(getComputedStyle(element).color,surface(element))}));
      const primary=[...document.querySelectorAll(".primary-button,.run-button kbd")].map(element=>({class:element.className,contrast:ratio(getComputedStyle(element).color,surface(element))}));
      const overflow=[...document.querySelectorAll(".preview-panel,.connections-search,.explorer-search,.variable-filter>label,.variable-archive-search,.block-scope-popover,.code-block")].filter(element=>element.scrollWidth>element.clientWidth+1).map(element=>({class:element.className,client:element.clientWidth,scroll:element.scrollWidth}));
      const icons=[...document.querySelectorAll(".agent-icon")].map(element=>{const images=[...element.querySelectorAll("img")],visible=images.filter(image=>getComputedStyle(image).display!=="none");return {label:element.getAttribute("aria-label"),visible:visible.length,variant:visible[0]?.className,width:visible[0]?.getBoundingClientRect().width};});
      return {search,chrome,primary,overflow,icons};
    });
    for(const check of checks.search){assert(check.transparent,`${name} ${check.class}: nested background`);assert(check.borderless,`${name} ${check.class}: nested border`);assert.equal(check.padding,0,`${name} ${check.class}: nested padding`);assert(check.fits,`${name} ${check.class}: input overflow`);assert(check.textContrast>=4.5,`${name} ${check.class}: text contrast ${check.textContrast}`);assert(check.placeholderContrast>=4.5,`${name} ${check.class}: placeholder contrast ${check.placeholderContrast}`);}
    for(const check of checks.chrome){if(theme==="light")assert(check.luminance>.6,`${name} ${check.class}: dark surface remains ${check.background}`);assert(check.contrast>=4.5,`${name} ${check.class}: text contrast ${check.contrast}`);}
    for(const check of checks.primary)assert(check.contrast>=4.5,`${name} ${check.class}: primary contrast ${check.contrast}`);
    assert.deepEqual(checks.overflow,[],`${name}: overflowing panels`);
    for(const icon of checks.icons){assert.equal(icon.visible,1,`${name} ${icon.label}: missing or duplicate logo`);assert(icon.width>0,`${name} ${icon.label}: collapsed logo`);if(icon.variant)assert.equal(icon.variant,`agent-icon-${theme}`,`${name} ${icon.label}: wrong theme asset`);}
    await page.locator(".explorer-search input").focus();
    assert.equal(await page.locator(".explorer-search").evaluate(element=>getComputedStyle(element).outlineStyle),"solid",`${name}: no visible wrapper focus`);
    if(font==="Ubuntu")await page.screenshot({path:resolve(output,`${name}.png`),fullPage:true});
    console.log(`PASS ${name}: search surfaces, focus, theme, contrast and panel bounds`);passed++;
  }
  assert.deepEqual(errors,[],"fixture browser errors");
  console.log(`${passed} theme scenarios passed; screenshots: ${output}`);
} finally {await browser?.close();await server.close();}
