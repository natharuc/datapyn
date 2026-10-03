import {afterEach,describe,expect,it,vi} from "vitest";
import type {SerializedDockview} from "dockview-react";
import {NativePopoutLayoutTracker,nativePopoutLabel,withNativePopoutPositions,type NativePopoutPort,type NativePopoutPosition} from "./nativePopoutLayout";

const trackers:NativePopoutLayoutTracker[]=[];
afterEach(async()=>{trackers.splice(0).forEach(tracker=>tracker.dispose());await Promise.resolve();vi.useRealTimers();});
const position:NativePopoutPosition={left:377,top:659,width:845,height:310};
const popup=(label="dock-popout-0")=>({__DATAPYN_NATIVE_LABEL__:label}) as unknown as Window;
function layout():SerializedDockview {
  return {grid:{width:1000,height:800,orientation:"HORIZONTAL",root:{type:"branch",data:[]}},panels:{},
    popoutGroups:[{data:{id:"tools",views:["output"],activeView:"output"},position:{left:385,top:690,width:845,height:310}}]} as unknown as SerializedDockview;
}
function setup(changed=vi.fn()){
  const load=vi.fn(async()=>({"dock-popout-0":position})),close=vi.fn(async()=>{}),subscribe=vi.fn(async(_label:string,_changed:()=>void)=>()=>{});
  const port:NativePopoutPort={load,close,subscribe},tracker=new NativePopoutLayoutTracker(changed,port);trackers.push(tracker);
  return {tracker,load,close,subscribe,changed};
}
describe("native popout geometry and host lifetime",()=>{
  it("accepts only the host-injected panel label and tolerates unscriptable window handles",()=>{
    expect(nativePopoutLabel(popup())).toBe("dock-popout-0");
    for(const value of ["main","splash","dock-popout-other",null])expect(nativePopoutLabel(popup(value as string))).toBeUndefined();
    const blocked=new Proxy({},{get:()=>{throw new Error("cross origin");}});expect(nativePopoutLabel(blocked as Window)).toBeUndefined();
  });
  it("replaces client-origin offsets with exact native outer coordinates without mutating Dockview DTO",()=>{
    const original=layout(),corrected=withNativePopoutPositions(original,[{id:"tools",window:popup()}],new Map([["dock-popout-0",position]]));
    expect(corrected.popoutGroups![0].position).toEqual(position);expect(original.popoutGroups![0].position!.left).toBe(385);
    expect(corrected.grid).toBe(original.grid);expect(corrected.panels).toBe(original.panels);
  });
  it("matches nested popout groups independently instead of assuming serialization order",()=>{
    const original=layout();original.popoutGroups=[{grid:{...original.grid,root:{type:"branch",data:[{type:"leaf",data:{id:"nested-tools",views:["output"]}}]}},position:null},original.popoutGroups![0]] as never;
    const second={left:-1500,top:50,width:900,height:700};
    const corrected=withNativePopoutPositions(original,[{id:"tools",window:popup()},{id:"nested-tools",window:popup("dock-popout-1")}],new Map([["dock-popout-0",position],["dock-popout-1",second]]));
    expect(corrected.popoutGroups![0].position).toEqual(second);expect(corrected.popoutGroups![1].position).toEqual(position);
  });
  it("keeps browser-only or unavailable native geometry intact",()=>{
    const original=layout();expect(withNativePopoutPositions(original,[{id:"tools",window:{} as Window}],new Map())).toBe(original);
  });
  it("flushes current native position and avoids autosave notifications when bounds are unchanged",async()=>{
    const test=setup(),view=popup(),release=test.tracker.bind(view);
    await test.tracker.flush();await test.tracker.flush();expect(test.changed).toHaveBeenCalledOnce();
    expect(test.tracker.capture(layout(),[{id:"tools",window:view}]).popoutGroups![0].position).toEqual(position);
    test.load.mockResolvedValueOnce({"dock-popout-0":{...position,left:400,top:700}});
    await test.tracker.flush();expect(test.changed).toHaveBeenCalledTimes(2);
    expect(test.tracker.capture(layout(),[{id:"tools",window:view}]).popoutGroups![0].position!.left).toBe(400);release();
  });
  it("debounces native move/resize notifications and cancels the timer on fresh capture",async()=>{
    vi.useFakeTimers();const test=setup(),release=test.tracker.bind(popup());await test.tracker.flush();
    const changed=test.subscribe.mock.calls[0][1];changed();changed();changed();
    await vi.advanceTimersByTimeAsync(149);expect(test.load).toHaveBeenCalledTimes(1);
    await test.tracker.flush();expect(test.load).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(500);expect(test.load).toHaveBeenCalledTimes(2);release();
  });
  it("native X / repeated cleanup closes the host idempotently only once after portal transfer",async()=>{
    const test=setup(),release=test.tracker.bind(popup());release();release();expect(test.close).not.toHaveBeenCalled();
    await Promise.resolve();expect(test.close).toHaveBeenCalledOnce();expect(test.close).toHaveBeenCalledWith("dock-popout-0");
  });
  it("does not close a window rebound during the same layout mutation",async()=>{
    const test=setup(),view=popup(),first=test.tracker.bind(view);first();const second=test.tracker.bind(view);
    await Promise.resolve();expect(test.close).not.toHaveBeenCalled();second();await Promise.resolve();expect(test.close).toHaveBeenCalledOnce();
  });
  it("does not close a host still owned by another mounted workbench",async()=>{
    const first=setup(),second=setup(),view=popup(),releaseFirst=first.tracker.bind(view),releaseSecond=second.tracker.bind(view);
    releaseFirst();await Promise.resolve();expect(first.close).not.toHaveBeenCalled();releaseSecond();await Promise.resolve();expect(second.close).toHaveBeenCalledOnce();
  });
  it("releases an asynchronous native event subscription even if the popout already closed",async()=>{
    const test=setup(),cleanup=vi.fn();let complete:(cleanup:()=>void)=>void=()=>{};
    test.subscribe.mockImplementationOnce(()=>new Promise(resolve=>{complete=resolve;}));const release=test.tracker.bind(popup());release();complete(cleanup);
    await Promise.resolve();expect(cleanup).toHaveBeenCalledOnce();
  });
  it("keeps previous geometry through a transient read error and retries the next flush",async()=>{
    const test=setup(),view=popup();test.tracker.bind(view);await test.tracker.flush();
    test.load.mockRejectedValueOnce(new Error("temporary unavailable"));await expect(test.tracker.flush()).rejects.toThrow("temporary unavailable");
    expect(test.tracker.capture(layout(),[{id:"tools",window:view}]).popoutGroups![0].position).toEqual(position);
    await expect(test.tracker.flush()).resolves.toBeUndefined();
  });
});
