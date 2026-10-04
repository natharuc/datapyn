import { afterEach, describe, expect, it, vi } from "vitest";
import { InlineRequestGate, LanguageRequestGate, languageParams, mergeCompletions, type LanguageCompletion } from "./editorLanguage";
import type { RuntimeTransport } from "./runtime";
describe("editor language requests", () => {
  it("sends the focused block's database scope and cursor without changing indexes", () => {
    expect(languageParams({ variables: [], tables: [], sessionId: "s", connectionId: "c", database: "catalog", schema: "schema" }, { language: "sql", code: "SELECT a.", line: 1, column: 10 })).toMatchObject({ session_id: "s", connection_id: "c", database: "catalog", schema: "schema", line: 1, column: 10 });
  });
  it("rejects late completions after a newer keystroke or changed connection", async () => {
    const resolvers: Array<(value: { items: LanguageCompletion[] }) => void> = [];
    const transport = { request: () => new Promise((resolve) => resolvers.push(resolve as typeof resolvers[number])), subscribe: async () => () => {} } as RuntimeTransport;
    const gate = new LanguageRequestGate(), old = gate.complete(transport, {}, () => true), current = gate.complete(transport, {}, () => true);
    resolvers[1]({ items: [{ label: "current" }] }); expect(await current).toEqual([{ label: "current" }]); resolvers[0]({ items: [{ label: "old" }] }); expect(await old).toEqual([]);
    const changed = gate.complete(transport, {}, () => true); gate.invalidate(); resolvers[2]({ items: [{ label: "wrong_database" }] }); expect(await changed).toEqual([]);
  });
  it("lets contextual insert text win duplicates and bounds suggestion payloads", () => {
    expect(mergeCompletions([{ label: "orders", insert_text: '"orders"', detail: "server" }], [{ label: "orders", insert_text: '"orders"' }, { label: "SELECT" }])).toHaveLength(2);
    expect(mergeCompletions(Array.from({ length: 2000 }, (_, i) => ({ label: String(i) })), [])).toHaveLength(1000);
  });
});

afterEach(() => vi.useRealTimers());
describe("non-blocking completion requests", () => {
  function backend() {
    const requests: Array<{ method:string; params?:Record<string,unknown>; resolve:(value:unknown)=>void; reject:(error:Error)=>void }> = [];
    const request=vi.fn((method:string,params?:Record<string,unknown>)=>method==="language.cancel"?Promise.resolve({cancelled:true}):new Promise((resolve,reject)=>requests.push({method,params,resolve,reject})));
    return {requests,request,transport:{request,subscribe:async()=>()=>{}} as RuntimeTransport};
  }
  it("returns cached/local-ready results synchronously and builds no source payload before a typing pause", async () => {
    vi.useFakeTimers();const b=backend(),gate=new LanguageRequestGate(),params=vi.fn(()=>({code:"typed",block_id:"b",session_id:"s"})),ready=vi.fn();
    expect(gate.suggest(b.transport,"cursor",params,()=>true,ready)).toEqual([]);
    expect(params).not.toHaveBeenCalled();expect(b.request).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(119);expect(b.request).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);expect(params).toHaveBeenCalledOnce();expect(b.requests[0].params).toMatchObject({code:"typed",block_id:"b",completion_id:expect.stringMatching(/^[A-Za-z0-9_-]+$/)});
    b.requests[0].resolve({items:[{label:"result"}]});await vi.advanceTimersByTimeAsync(0);
    expect(ready).toHaveBeenCalledOnce();expect(gate.suggest(b.transport,"cursor",params,()=>true,ready)).toEqual([{label:"result"}]);expect(params).toHaveBeenCalledOnce();expect(b.request).toHaveBeenCalledOnce();
  });
  it("coalesces rapid typing and makes only the latest paused cursor enter IPC", async () => {
    vi.useFakeTimers();const b=backend(),gate=new LanguageRequestGate();
    for(let i=0;i<100;i++){gate.suggest(b.transport,`cursor${i}`,()=>({code:String(i)}),()=>true,()=>{});await vi.advanceTimersByTimeAsync(10);}
    expect(b.request).not.toHaveBeenCalled();await vi.advanceTimersByTimeAsync(120);
    expect(b.request).toHaveBeenCalledOnce();expect(b.requests[0].params?.code).toBe("99");
  });
  it("deduplicates the same cursor and lets a manual request bypass the pending debounce", async () => {
    vi.useFakeTimers();const b=backend(),gate=new LanguageRequestGate(),ready=vi.fn();
    gate.suggest(b.transport,"same",()=>({code:"a"}),()=>true,()=>{});
    gate.suggest(b.transport,"same",()=>({code:"a"}),()=>true,ready,0);
    await vi.advanceTimersByTimeAsync(0);expect(b.request).toHaveBeenCalledOnce();
    gate.suggest(b.transport,"same",()=>({code:"a"}),()=>true,ready,0);expect(b.request).toHaveBeenCalledOnce();
    b.requests[0].resolve({items:[{label:"a"}]});await vi.advanceTimersByTimeAsync(0);expect(ready).toHaveBeenCalledOnce();
  });
  it("cancels the exact old native job and bounds the queue to one running and one latest request", async () => {
    vi.useFakeTimers();const b=backend(),gate=new LanguageRequestGate(),oldReady=vi.fn(),newReady=vi.fn();
    gate.suggest(b.transport,"old",()=>({block_id:"b",session_id:"s",code:"old"}),()=>true,oldReady,0);await vi.advanceTimersByTimeAsync(0);
    const oldId=b.requests[0].params?.completion_id;
    for(const key of ["middle","new"])gate.suggest(b.transport,key,()=>({block_id:"b",session_id:"s",code:key}),()=>true,newReady,0);
    await vi.advanceTimersByTimeAsync(0);expect(b.requests).toHaveLength(1);
    expect(b.request).toHaveBeenCalledWith("language.cancel",{block_id:"b",session_id:"s",completion_id:oldId});
    b.requests[0].resolve({items:[{label:"obsolete"}]});await vi.advanceTimersByTimeAsync(0);
    expect(oldReady).not.toHaveBeenCalled();expect(b.requests).toHaveLength(2);expect(b.requests[1].params?.code).toBe("new");
    b.requests[1].resolve({items:[{label:"fresh"}]});await vi.advanceTimersByTimeAsync(0);expect(newReady).toHaveBeenCalledOnce();
  });
  it("drops late results after cursor, connection, model lifetime or Escape invalidates intent", async () => {
    vi.useFakeTimers();const b=backend(),gate=new LanguageRequestGate(),ready=vi.fn();let valid=true;
    gate.suggest(b.transport,"one",()=>({block_id:"b"}),()=>valid,ready,0);await vi.advanceTimersByTimeAsync(0);valid=false;
    b.requests[0].resolve({items:[{label:"obsolete"}]});await vi.advanceTimersByTimeAsync(0);expect(ready).not.toHaveBeenCalled();
    valid=true;gate.suggest(b.transport,"two",()=>({block_id:"b"}),()=>valid,ready,0);await vi.advanceTimersByTimeAsync(0);gate.invalidate();
    b.requests[1].resolve({items:[{label:"wrong_database"}]});await vi.advanceTimersByTimeAsync(0);expect(ready).not.toHaveBeenCalled();
  });
  it("backs off a service failure without disabling local completion", async () => {
    vi.useFakeTimers();const b=backend(),gate=new LanguageRequestGate(),ready=vi.fn();
    gate.suggest(b.transport,"offline",()=>({}),()=>true,ready,0);await vi.advanceTimersByTimeAsync(0);b.requests[0].reject(new Error("offline"));await vi.advanceTimersByTimeAsync(0);
    for(let i=0;i<10;i++)expect(gate.suggest(b.transport,"offline",()=>({}),()=>true,ready,0)).toEqual([]);
    await vi.advanceTimersByTimeAsync(0);expect(b.requests).toHaveLength(1);expect(ready).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1_001);gate.suggest(b.transport,"offline",()=>({}),()=>true,ready,0);await vi.advanceTimersByTimeAsync(0);expect(b.requests).toHaveLength(2);
  });
  it("keeps only eight recent cursor snapshots and does not cache a superseded server response", async () => {
    vi.useFakeTimers();const b=backend(),gate=new LanguageRequestGate();
    for(let i=0;i<10;i++){gate.suggest(b.transport,String(i),()=>({}),()=>true,()=>{},0);await vi.advanceTimersByTimeAsync(0);b.requests[i].resolve({items:[{label:String(i)}]});await vi.advanceTimersByTimeAsync(0);}
    expect(gate.suggest(b.transport,"9",()=>({}),()=>true,()=>{},0)).toEqual([{label:"9"}]);
    expect(gate.suggest(b.transport,"0",()=>({}),()=>true,()=>{},0)).toEqual([]);await vi.advanceTimersByTimeAsync(0);expect(b.requests).toHaveLength(11);
    b.requests[10].resolve({items:[{label:"wrong"}],superseded:true});await vi.advanceTimersByTimeAsync(0);
    expect(gate.suggest(b.transport,"0",()=>({}),()=>true,()=>{},0)).toEqual([]);await vi.advanceTimersByTimeAsync(0);expect(b.requests).toHaveLength(12);
  });
  it("preserves distinct PostgreSQL quoted identifiers while folding only keyword duplicates", () => {
    expect(mergeCompletions([{label:"Id",kind:"column",insert_text:'"Id"'},{label:"SELECT",kind:"keyword"}],[{label:"id",kind:"column",insert_text:'"id"'},{label:"select",kind:"keyword"}],"sql")).toEqual([{label:"Id",kind:"column",insert_text:'"Id"'},{label:"SELECT",kind:"keyword"},{label:"id",kind:"column",insert_text:'"id"'}]);
  });
  it("deduplicates the same Python column before local/remote escaping while preserving case-sensitive distinct fields", () => {
    expect(mergeCompletions([{label:"O'Brien",kind:"field",insert_text:"O\\'Brien"},{label:"Id",kind:"field"}],[{label:"O'Brien",kind:"field",insert_text:"O'Brien"},{label:"id",kind:"field"}],"python")).toEqual([{label:"O'Brien",kind:"field",insert_text:"O\\'Brien"},{label:"Id",kind:"field"},{label:"id",kind:"field"}]);
  });
});

describe("bounded ACP inline completion", () => {
  function token() {const listeners=new Set<()=>void>();return {isCancellationRequested:false,onCancellationRequested(listener:()=>void){listeners.add(listener);return {dispose:()=>listeners.delete(listener)};},cancel(){this.isCancellationRequested=true;for(const listener of [...listeners])listener();}};}
  it("cancels a typing pause before source extraction or ACP IPC", async () => {
    vi.useFakeTimers();const gate=new InlineRequestGate(),params=vi.fn(()=>({body:"source"})),request=vi.fn(),signal=token();
    const completion=gate.complete({request,subscribe:async()=>()=>{}} as RuntimeTransport,"one",params,()=>true,signal);
    signal.cancel();expect(await completion).toBe("");await vi.advanceTimersByTimeAsync(500);expect(params).not.toHaveBeenCalled();expect(request).not.toHaveBeenCalled();
  });
  it("keeps one running ACP request and starts only the latest valid queued cursor", async () => {
    vi.useFakeTimers();const gate=new InlineRequestGate(),jobs:Array<{params:Record<string,unknown>;resolve:(value:{text:string})=>void}>=[];
    const request=vi.fn((_method:string,params:Record<string,unknown>)=>new Promise(resolve=>jobs.push({params,resolve} as never))),transport={request,subscribe:async()=>()=>{}} as RuntimeTransport;
    const old=gate.complete(transport,"old",()=>({body:"old"}),()=>true,token(),0);await vi.advanceTimersByTimeAsync(0);
    const middle=gate.complete(transport,"middle",()=>({body:"middle"}),()=>true,token(),0);
    const latest=gate.complete(transport,"latest",()=>({body:"latest"}),()=>true,token(),0);await vi.advanceTimersByTimeAsync(0);
    expect(await old).toBe("");expect(await middle).toBe("");expect(jobs).toHaveLength(1);
    jobs[0].resolve({text:"stale"});await vi.advanceTimersByTimeAsync(0);expect(jobs).toHaveLength(2);expect(jobs[1].params.body).toBe("latest");
    jobs[1].resolve({text:"fresh"});expect(await latest).toBe("fresh");
  });
  it("reuses a same-cursor response without launching duplicate ACP requests", async () => {
    vi.useFakeTimers();const gate=new InlineRequestGate();let resolve:(result:{text:string})=>void=()=>{};
    const request=vi.fn(()=>new Promise(done=>{resolve=done;})),transport={request,subscribe:async()=>()=>{}} as RuntimeTransport;
    const old=gate.complete(transport,"same",()=>({}),()=>true,token(),0);await vi.advanceTimersByTimeAsync(0);
    const current=gate.complete(transport,"same",()=>({}),()=>true,token(),0);await vi.advanceTimersByTimeAsync(0);
    resolve({text:"one result"});expect(await old).toBe("");expect(await current).toBe("one result");expect(request).toHaveBeenCalledOnce();
  });
  it("never returns ghost text after Escape, blur, changed scope or a disposed model", async () => {
    vi.useFakeTimers();const gate=new InlineRequestGate();let valid=true,resolve:(result:{text:string})=>void=()=>{};
    const request=vi.fn(()=>new Promise(done=>{resolve=done;})),transport={request,subscribe:async()=>()=>{}} as RuntimeTransport;
    const result=gate.complete(transport,"one",()=>({}),()=>valid,token(),0);await vi.advanceTimersByTimeAsync(0);valid=false;resolve({text:"must disappear"});expect(await result).toBe("");
  });
});
