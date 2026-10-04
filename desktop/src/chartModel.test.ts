import { describe, expect, it, vi } from "vitest";
import { activeSavedChart, chartConfigError, chartInteractionRevision, chartPreparationKey, chartSourceView, chartThemeConfig, ChartPreviewQueue, ChartSourceCache, latestChartSource, normalizeChartConfig } from "./chartModel";
import type { ResultRef } from "./runtime";
const source: ResultRef = { result_id: "r", variable_name: "vendas", row_count: 10000000, columns: [{ name: "região", dtype: "string" }, { name: "valor", dtype: "Decimal(38, 18)" }] };
const deferred = <T>() => { let resolve!: (value:T) => void; let reject!: (error:unknown) => void; const promise = new Promise<T>((a,b)=>{resolve=a;reject=b;}); return {promise,resolve,reject}; };

describe("chart configuration and session identity", () => {
  it("uses the Qt defaults even with several numeric columns before the category",()=>{
    const result={...source,columns:[{name:"id",dtype:"int64"},{name:"cost",dtype:"float64"},...source.columns]};
    expect(normalizeChartConfig(result)).toMatchObject({x_column:"região",y_columns:["id"]});
    expect(normalizeChartConfig({...source,columns:result.columns.slice(0,2)})).toMatchObject({x_column:"",y_columns:["id"]});
  });
  it("keeps malformed imported series editable without crashing the controls",()=>{
    expect(normalizeChartConfig(source,{y_columns:"valor" as unknown as string[]}).y_columns).toEqual([]);
    expect(normalizeChartConfig(source,{y_columns:[null,"valor","valor"] as unknown as string[]}).y_columns).toEqual(["valor"]);
    expect(activeSavedChart({desktop_chart_id:"a",charts:{id:"a"}})).toBeUndefined();
  });
  it("restyles a captured figure only when its preparation and source version still match",()=>{
    const config=normalizeChartConfig(source),identity={resultId:"r",refreshRevision:0,filter:{text:"a"}},key=chartPreparationKey(identity,config);
    expect(chartPreparationKey(identity,{...config,title:"Style only",palette:"warm",font_size:18})).toBe(key);
    expect(chartPreparationKey({...identity,refreshRevision:1},config)).not.toBe(key);
    expect(chartPreparationKey(identity,{...config,aggregation:"mean"})).not.toBe(key);
    expect(chartPreparationKey(identity,{...config,y_columns:["other","valor"]})).not.toBe(key);
  });
  it("retains legacy fields and unknown extensions with usable defaults", () => {
    const config=normalizeChartConfig(source,{stacking:"none",custom_colors:["#ff0000"],future:{value:7},live_preview:false});
    expect(config).toMatchObject({x_column:"região",y_columns:["valor"],stacking:"grouped",future:{value:7},custom_colors:["#ff0000"],live_preview:false});
  });
  it("does not silently substitute missing saved columns", () => {
    const config=normalizeChartConfig(source,{y_columns:["removed"]});
    expect(config.y_columns).toEqual(["removed"]); expect(chartConfigError(source,config)).toContain("não existe");
  });
  it("rejects ambiguous columns and unavailable selections", () => {
    expect(chartConfigError({...source,columns:[...source.columns,source.columns[1]]},normalizeChartConfig(source))).toContain("duplicadas");
    expect(chartConfigError(source,{...normalizeChartConfig(source),source_mode:"selection"})).toContain("Selecione");
  });
  it("uses the view of the chart's source without adding a grid selection to filtered mode", () => {
    const view={filter:{filters:[{column:"valor",operator:"between",value:"9007199254740993",value_to:"9007199254740994"}]},sort:{column:"valor",direction:"desc" as const},scope:{row_ranges:[[1,5]]}};
    expect(chartSourceView({source_mode:"all"},view)).toEqual({});
    expect(chartSourceView({source_mode:"filtered"},view)).toEqual({filter:view.filter,sort:view.sort});
    expect(chartSourceView({source_mode:"selection",selection_view:view},{filter:{text:"changed"}})).toBe(view);
  });
  it("keeps zoom while changing styles but resets for another source or axis", () => {
    const config=normalizeChartConfig(source),key=chartInteractionRevision("s",source,config);
    expect(chartInteractionRevision("s",source,{...config,title:"Novo",palette:"ocean"})).toBe(key);
    expect(chartInteractionRevision("s",{...source,result_id:"new"},config)).not.toBe(key);
    expect(chartInteractionRevision("s",source,{...config,x_column:""})).not.toBe(key);
  });
  it("isolates active charts per document and ignores stale IDs", () => {
    expect(activeSavedChart({desktop_chart_id:"a",charts:[{id:"a"}]})).toBe("a");
    expect(activeSavedChart({desktop_chart_id:"a",charts:[{id:"b"}]})).toBeUndefined();
  });
  it("chooses the most recent result version without cloning the full list", () => {
    const latest={...source,result_id:"new"}; expect(latestChartSource("vendas",[source,{...source,variable_name:"other"},latest])).toBe(latest);
  });
  it("follows the app theme while conserving explicitly configured colors", () => {
    expect(chartThemeConfig({},true)).toMatchObject({background_color:"#ffffff",text_color:"#263448"});
    expect(chartThemeConfig({background_color:"#123456",text_color:"red"},true)).toMatchObject({background_color:"#123456",text_color:"red",label_color:"red"});
  });
});

describe("restored chart source handles",()=>{
  it("coalesces lookups and reuses handles when charts remount",async()=>{
    const cache=new ChartSourceCache(),load=vi.fn(async()=>source);
    const first=cache.resolve("s",1,"vendas",load),second=cache.resolve("s",1,"vendas",load);
    expect(first).toBe(second);await first;await cache.resolve("s",1,"vendas",load);expect(load).toHaveBeenCalledOnce();
  });
  it("refreshes after namespace changes and isolates sessions and profiles",async()=>{
    const cache=new ChartSourceCache(),load=vi.fn(async()=>source);
    await cache.resolve("s",1,"vendas",load);await cache.resolve("other",1,"vendas",load);await cache.resolve("s",2,"vendas",load);
    cache.clear();await cache.resolve("s",2,"vendas",load);expect(load).toHaveBeenCalledTimes(4);
  });
  it("resolves a reassigned namespace frame after scalar output rather than its older result handle",async()=>{
    const cache=new ChartSourceCache(),newFrame={...source,result_id:"reassigned",row_count:2,columns:[{name:"new_column",dtype:"Int64"}]};
    await cache.resolve("s",1,"vendas",async()=>source);
    const canonical=vi.fn(async()=>newFrame);
    expect(await cache.resolve("s",2,"vendas",canonical)).toBe(newFrame);
    expect(await cache.resolve("s",2,"vendas",canonical)).toBe(newFrame);
    expect(canonical).toHaveBeenCalledOnce();
  });
  it("allows a failed restored source to be retried without poisoning another generation",async()=>{
    const cache=new ChartSourceCache(),failed=deferred<ResultRef>();
    const old=cache.resolve("s",1,"vendas",()=>failed.promise);const fresh=cache.resolve("s",2,"vendas",async()=>source);
    failed.reject(new Error("closed"));await expect(old).rejects.toThrow("closed");
    expect(cache.resolve("s",2,"vendas",vi.fn())).toBe(fresh);
  });
});

describe("chart RPC coalescing", () => {
  it("runs one request at a time and keeps only the latest queued edit", async () => {
    const first=deferred<number>(),second=deferred<number>(),accept=vi.fn(),obsolete=vi.fn(),last=vi.fn(()=>second.promise),busy=vi.fn();
    const queue=new ChartPreviewQueue<number>(busy);
    queue.request(()=>first.promise,accept,vi.fn()); queue.request(obsolete,accept,vi.fn()); queue.request(last,accept,vi.fn());
    expect(last).not.toHaveBeenCalled(); first.resolve(1); await Promise.resolve(); await Promise.resolve();
    expect(obsolete).not.toHaveBeenCalled(); expect(last).toHaveBeenCalledOnce(); expect(accept).not.toHaveBeenCalled();
    second.resolve(3); await Promise.resolve(); await Promise.resolve(); expect(accept).toHaveBeenCalledExactlyOnceWith(3); expect(busy.mock.calls).toEqual([[true],[false]]);
  });
  it("ignores stale success/error immediately when settings change before debounce", async () => {
    const pending=deferred<number>(),accept=vi.fn(),fail=vi.fn(),queue=new ChartPreviewQueue<number>(vi.fn());
    queue.request(()=>pending.promise,accept,fail); queue.invalidate(); pending.reject(new Error("old")); await Promise.resolve(); await Promise.resolve();
    expect(accept).not.toHaveBeenCalled(); expect(fail).not.toHaveBeenCalled();
  });
  it("drops pending work and callbacks when a chart/source unmounts", async () => {
    const pending=deferred<number>(),accept=vi.fn(),next=vi.fn(),queue=new ChartPreviewQueue<number>(vi.fn());
    queue.request(()=>pending.promise,accept,vi.fn()); queue.request(next,accept,vi.fn()); queue.dispose(); pending.resolve(1); await Promise.resolve(); await Promise.resolve();
    expect(next).not.toHaveBeenCalled(); expect(accept).not.toHaveBeenCalled();
  });
});
