import {describe,expect,it,vi} from "vitest";
import {normalizeMainWindowLayout,planWindowRestore,sameWindowLayout,WindowLayoutController,
  type MainWindowLayout,type WindowBounds,type WindowLayoutPort,type WindowMonitor,type WindowRestorePlan} from "./windowLayout";

const monitor:WindowMonitor={position:{x:0,y:0},size:{width:1920,height:1080},workArea:{position:{x:0,y:0},size:{width:1920,height:1040}},scaleFactor:1};
function layout(overrides:Partial<MainWindowLayout>={}):MainWindowLayout {
  return {version:1,position:{x:120,y:70},size:{width:1200,height:760},scaleFactor:1,maximized:false,...overrides};
}
function fakePort(){
  let bounds:WindowBounds={position:{x:20,y:30},size:{width:1440,height:900},outerSize:{width:1456,height:938},scaleFactor:1,maximized:false,minimized:false};
  const apply=vi.fn(async(plan:WindowRestorePlan)=>{
    bounds={...bounds,position:plan.layout.position,size:plan.layout.size,outerSize:{width:plan.layout.size.width+16,height:plan.layout.size.height+38},
      scaleFactor:plan.layout.scaleFactor,maximized:plan.layout.maximized};
  });
  const port:WindowLayoutPort={bounds:vi.fn(async()=>bounds),monitors:vi.fn(async()=>[monitor]),apply};
  return {port,apply,set:(value:Partial<WindowBounds>)=>{bounds={...bounds,...value};},get:()=>bounds};
}

describe("native main window geometry",()=>{
  it("validates private metadata and rejects unsupported, malformed, zero and non-finite dimensions",()=>{
    expect(normalizeMainWindowLayout(layout())).toEqual(layout());
    for(const value of [null,[],{...layout(),version:2},{...layout(),position:{x:NaN,y:0}},
      {...layout(),size:{width:0,height:1}},{...layout(),size:{width:Infinity,height:1}},
      {...layout(),scaleFactor:0},{...layout(),scaleFactor:9},{...layout(),maximized:"yes"}]){
      expect(normalizeMainWindowLayout(value)).toBeUndefined();
    }
  });
  it("preserves valid normal bounds and taskbar-aware window position",()=>{
    expect(planWindowRestore(layout(),[monitor],{width:16,height:38})).toEqual({layout:layout(),minimum:{width:960,height:640}});
  });
  it("supports a monitor to the left with negative coordinates",()=>{
    const left:WindowMonitor={...monitor,position:{x:-1920,y:0},workArea:{position:{x:-1920,y:0},size:{width:1920,height:1040}}};
    const saved=layout({position:{x:-1800,y:80}});
    expect(planWindowRestore(saved,[monitor,left]).layout).toEqual(saved);
  });
  it("brings the complete frame back into work area after the saved monitor is unplugged",()=>{
    const restored=planWindowRestore(layout({position:{x:-2400,y:1800},size:{width:3000,height:1800}}),[monitor],{width:16,height:38}).layout;
    expect(restored.position).toEqual({x:0,y:0});
    expect(restored.size).toEqual({width:1904,height:1002});
    expect(restored.position.x+restored.size.width+16).toBeLessThanOrEqual(1920);
    expect(restored.position.y+restored.size.height+38).toBeLessThanOrEqual(1040);
  });
  it("preserves logical size when DPI drops and clamps position using physical coordinates",()=>{
    const restored=planWindowRestore(layout({position:{x:900,y:450},size:{width:1800,height:1200},scaleFactor:1.5}),[monitor],{width:16,height:38}).layout;
    expect(restored.size).toEqual({width:1200,height:800});
    expect(restored.position).toEqual({x:704,y:202});
    expect(restored.scaleFactor).toBe(1);
  });
  it("allows screens smaller than logical minimum and reserves the title bar and border",()=>{
    const small:WindowMonitor={position:{x:200,y:100},size:{width:800,height:600},workArea:{position:{x:200,y:100},size:{width:800,height:560}},scaleFactor:1};
    const restored=planWindowRestore(layout(),[small],{width:16,height:38});
    expect(restored.minimum).toEqual({width:784,height:522});
    expect(restored.layout.position).toEqual({x:200,y:100});
    expect(restored.layout.size).toEqual(restored.minimum);
  });
  it("rescales both client area and decoration when moving to a monitor with higher DPI",()=>{
    const highDpi:WindowMonitor={position:{x:1920,y:0},size:{width:3840,height:2160},workArea:{position:{x:1920,y:0},size:{width:3840,height:2080}},scaleFactor:2};
    const restored=planWindowRestore(layout({position:{x:2100,y:20},size:{width:4000,height:2000}}),[monitor,highDpi],{width:16,height:38,scaleFactor:1});
    expect(restored.layout.scaleFactor).toBe(2);
    expect(restored.layout.size).toEqual({width:3808,height:2004});
    expect(restored.layout.position).toEqual({x:1920,y:0});
    expect(restored.minimum).toEqual({width:1920,height:1280});
  });
  it("falls back to monitor resolution when work-area data is unavailable",()=>{
    const restored=planWindowRestore(layout({position:{x:1400,y:900}}),[{...monitor,workArea:undefined}]);
    expect(restored.layout.position).toEqual({x:720,y:320});
  });
  it("restores the saved normal geometry before maximization and keeps it through asynchronous resize",async()=>{
    const fake=fakePort(),controller=new WindowLayoutController(fake.port),saved=layout({maximized:true});
    const restored=await controller.restore(saved);
    expect(fake.apply).toHaveBeenCalledWith({layout:saved,minimum:{width:960,height:640}});
    expect(restored).toEqual(saved);
    fake.set({position:{x:-8,y:-8},size:{width:1920,height:1040},outerSize:{width:1936,height:1078}});
    expect(await controller.capture()).toEqual(saved);
  });
  it("tracks maximize/unmaximize without replacing the remembered normal bounds with full screen bounds",async()=>{
    const fake=fakePort(),controller=new WindowLayoutController(fake.port);await controller.restore(layout());
    fake.set({position:{x:-8,y:-8},size:{width:1920,height:1040},maximized:true});
    expect(await controller.capture()).toEqual(layout({maximized:true}));
    fake.set({position:{x:90,y:60},size:{width:1100,height:800},maximized:false});
    expect(await controller.capture()).toEqual(layout({position:{x:90,y:60},size:{width:1100,height:800}}));
  });
  it("closing a minimized window keeps valid bounds and previous maximized state",async()=>{
    const fake=fakePort(),controller=new WindowLayoutController(fake.port);await controller.restore(layout({maximized:true}));
    fake.set({position:{x:-32000,y:-32000},size:{width:0,height:0},minimized:true,maximized:false});
    expect(await controller.capture()).toEqual(layout({maximized:true}));
  });
  it("captures current normal geometry at flush even when no debounce event was delivered",async()=>{
    const fake=fakePort(),controller=new WindowLayoutController(fake.port);await controller.restore(layout());
    fake.set({position:{x:200,y:110},size:{width:1300,height:850}});
    expect(await controller.capture()).toEqual(layout({position:{x:200,y:110},size:{width:1300,height:850}}));
  });
  it("serializes capture behind restoration so intermediate moves cannot leak into autosave",async()=>{
    const fake=fakePort();let release:()=>void=()=>{};
    const blocked=new Promise<void>(resolve=>{release=resolve;});
    const apply=fake.port.apply;
    fake.port.apply=async(plan)=>{await blocked;await apply(plan);};
    const controller=new WindowLayoutController(fake.port),saved=layout();
    const restore=controller.restore(saved),capture=controller.capture();
    expect(controller.restoring).toBe(true);
    release();expect(await restore).toEqual(saved);expect(await capture).toEqual(saved);expect(controller.restoring).toBe(false);
  });
  it("retries a capture after an API failure without poisoning future native reads",async()=>{
    const fake=fakePort(),controller=new WindowLayoutController(fake.port);await controller.restore(layout());
    vi.mocked(fake.port.bounds).mockRejectedValueOnce(new Error("read failed"));
    await expect(controller.capture()).rejects.toThrow("read failed");
    expect(await controller.capture()).toEqual(layout());
  });
  it("compares geometry values instead of object identity so unchanged events do not autosave",()=>{
    expect(sameWindowLayout(layout(),layout())).toBe(true);
    expect(sameWindowLayout(layout(),layout({maximized:true}))).toBe(false);
    expect(sameWindowLayout(undefined,layout())).toBe(false);
  });
});
