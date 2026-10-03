import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import type {StartupSnapshot} from "./splashProtocol";

const mocks=vi.hoisted(()=>({invoke:vi.fn(),listen:vi.fn(),isTauri:vi.fn()}));
vi.mock("@tauri-apps/api/core",()=>({invoke:mocks.invoke,isTauri:mocks.isTauri}));
vi.mock("@tauri-apps/api/event",()=>({listen:mocks.listen}));

const snapshot=(phase:StartupSnapshot["phase"],attempt=0):StartupSnapshot=>({phase,attempt,message:phase,version:"1.57.0"});
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(done=>{resolve=done;});return{promise,resolve};}
let retryHandler:(event:{payload:StartupSnapshot})=>void;
const reload=vi.fn();
beforeEach(()=>{
  vi.resetModules();mocks.invoke.mockReset();mocks.listen.mockReset();mocks.isTauri.mockReset();reload.mockReset();
  mocks.isTauri.mockReturnValue(true);
  mocks.listen.mockImplementation(async(_event:string,callback:typeof retryHandler)=>{retryHandler=callback;return()=>{};});
  vi.stubGlobal("window",{location:{reload}});
});
afterEach(()=>vi.unstubAllGlobals());

describe("native startup bridge",()=>{
  it("installs the retry listener before reading state and keeps a newer retry event over a late initial reply",async()=>{
    const listening=deferred<()=>void>(),initial=deferred<StartupSnapshot>();
    mocks.listen.mockImplementation((_event:string,callback:typeof retryHandler)=>{retryHandler=callback;return listening.promise;});
    mocks.invoke.mockReturnValue(initial.promise);
    const bridge=await import("./startupBridge"),boot=bridge.initializeStartup();
    expect(mocks.listen).toHaveBeenCalledWith("splash-retry",expect.any(Function));
    expect(mocks.invoke).not.toHaveBeenCalled();
    listening.resolve(()=>{});await Promise.resolve();
    expect(mocks.invoke).toHaveBeenCalledWith("splash_state");
    retryHandler({payload:snapshot("runtime",1)});
    initial.resolve(snapshot("frontend",0));await boot;
    expect(bridge.getStartupSnapshot()).toEqual(snapshot("runtime",1));
    expect(reload).not.toHaveBeenCalled();
  });

  it("coalesces identical pending publications and rejects a previous attempt's late completion",async()=>{
    const previous=deferred<StartupSnapshot>(),next=deferred<StartupSnapshot>();
    mocks.invoke.mockResolvedValueOnce(snapshot("runtime",0)).mockReturnValueOnce(previous.promise).mockReturnValueOnce(next.promise);
    const bridge=await import("./startupBridge");await bridge.initializeStartup();
    const publishing=bridge.publishStartup("workspace","Restoring analyses");
    expect(bridge.publishStartup("workspace","Restoring analyses")).toBe(publishing);
    expect(mocks.invoke).toHaveBeenCalledTimes(2);
    retryHandler({payload:snapshot("runtime",1)});
    const current=bridge.publishStartup("editor","Preparing editor");
    expect(mocks.invoke).toHaveBeenLastCalledWith("splash_publish",{phase:"editor",message:"Preparing editor",attempt:1});
    next.resolve(snapshot("editor",1));await current;
    previous.resolve(snapshot("workspace",0));await publishing;
    expect(bridge.getStartupSnapshot()).toEqual(snapshot("editor",1));
  });

  it("reports a bundle or render failure and reloads on the native retry even without React mounted",async()=>{
    mocks.invoke.mockResolvedValueOnce(snapshot("frontend")).mockResolvedValueOnce(snapshot("error"));
    const bridge=await import("./startupBridge");await bridge.initializeStartup();
    bridge.startupFailed();await Promise.resolve();
    expect(mocks.invoke).toHaveBeenLastCalledWith("splash_publish",{phase:"error",message:expect.any(String),attempt:0});
    expect(bridge.getStartupSnapshot().phase).toBe("error");
    retryHandler({payload:snapshot("runtime",1)});
    expect(reload).toHaveBeenCalledOnce();
    await bridge.publishStartup("ready");
    expect(mocks.invoke).toHaveBeenCalledTimes(2);
  });

  it("stops publishing after native readiness so later application errors cannot reopen startup",async()=>{
    mocks.invoke.mockResolvedValueOnce(snapshot("editor")).mockResolvedValueOnce(snapshot("ready"));
    const bridge=await import("./startupBridge");await bridge.initializeStartup();
    await bridge.publishStartup("ready");
    const calls=mocks.invoke.mock.calls.length;
    bridge.startupFailed();await bridge.publishStartup("runtime");
    expect(bridge.getStartupSnapshot().phase).toBe("ready");
    expect(mocks.invoke).toHaveBeenCalledTimes(calls);
  });
});
