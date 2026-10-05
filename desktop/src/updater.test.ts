import { afterEach, describe, expect, it, vi } from "vitest";
import { UpdateController, type UpdateHandle, type UpdateTransport } from "./updater";
import { TAURI_UPDATE_CHANNEL, TAURI_UPDATE_ENDPOINT } from "./updateChannel";

afterEach(() => vi.useRealTimers());

function fixture(available = true) {
  const handle: UpdateHandle = {version:"1.58.0",body:"A new build",download:vi.fn(async callback=>{callback({event:"Started",data:{contentLength:10}});callback({event:"Progress",data:{chunkLength:10}});callback({event:"Finished"});}),install:vi.fn(async()=>{}),close:vi.fn(async()=>{})};
  const transport:UpdateTransport = {configuration:vi.fn(async()=>({available,current_version:"1.57.0",channel:TAURI_UPDATE_CHANNEL,endpoint:TAURI_UPDATE_ENDPOINT})),check:vi.fn(async()=>handle),relaunch:vi.fn(async()=>{})};
  return {handle,transport,service:new UpdateController(()=>{},transport)};
}
describe("Tauri update lifecycle",()=>{
  it("never checks an unconfigured build or polls during initialization",async()=>{const {service,transport}=fixture(false);await service.initialize();await service.check();expect(service.state.phase).toBe("unavailable");expect(transport.check).not.toHaveBeenCalled();});
  it("flushes before installation and preserves download when saving fails",async()=>{const {service,handle}=fixture();await service.initialize();await service.check();await service.download();const flush=vi.fn(async()=>{throw new Error("disk full");});await service.install(flush);expect(handle.install).not.toHaveBeenCalled();expect(service.state.phase).toBe("downloaded");expect(service.state.error).toBe("disk full");const sequence:string[]=[];handle.install=vi.fn(async()=>{sequence.push("install");});await service.install(async()=>{sequence.push("save");});expect(sequence).toEqual(["save","install"]);});
  it("closes an update resource returned after dialog disposal",async()=>{const {service,handle,transport}=fixture();let resolve!:(value:UpdateHandle)=>void;transport.check=()=>new Promise(r=>{resolve=r;});await service.initialize();const pending=service.check();const closed=service.dispose();await Promise.resolve();resolve(handle);await pending;await closed;expect(handle.close).toHaveBeenCalledOnce();});
  it("requires downloading again after an installer consumes its resource and fails",async()=>{const {service,handle}=fixture();await service.initialize();await service.check();await service.download();handle.install=vi.fn(async()=>{throw new Error("installer failed");});await service.install(async()=>{});expect(service.state.phase).toBe("available");expect(service.state.error).toBe("installer failed");await service.download();expect(service.state.phase).toBe("downloaded");expect(handle.download).toHaveBeenCalledTimes(2);});
  it("rejects legacy and unrelated channels before issuing a network request", async () => {
    for (const configuration of [
      { channel: "pyqt6", endpoint: TAURI_UPDATE_ENDPOINT },
      { channel: TAURI_UPDATE_CHANNEL, endpoint: "https://github.com/natharuc/datapyn/releases/latest/download/latest.json" },
    ]) {
      const { service, transport } = fixture();
      transport.configuration = async () => ({ available: true, current_version: "1.57.0", ...configuration });
      await service.initialize(); await service.check();
      expect(service.state.phase).toBe("unavailable");
      expect(transport.check).not.toHaveBeenCalled();
    }
  });
  it("checks and downloads after startup without automatically installing or restarting", async () => {
    vi.useFakeTimers();
    const { service, handle, transport } = fixture();
    const stop = service.startAutomaticUpdates();
    await vi.advanceTimersByTimeAsync(9_999);
    expect(transport.check).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(service.state.phase).toBe("downloaded");
    expect(handle.download).toHaveBeenCalledOnce();
    expect(handle.install).not.toHaveBeenCalled();
    expect(transport.relaunch).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(21_600_000);
    expect(transport.check).toHaveBeenCalledOnce();
    stop(); await service.dispose();
  });
  it("keeps the verified native download when dialog listeners unsubscribe", async () => {
    const { service, handle } = fixture();
    const listener = vi.fn(), stopListening = service.subscribe(listener);
    await service.initialize(); await service.check(); await service.download();
    stopListening();
    await service.check(); await service.download();
    expect(handle.close).not.toHaveBeenCalled();
    expect(handle.download).toHaveBeenCalledOnce();
    const reopened = vi.fn(), stopReopened = service.subscribe(reopened);
    expect(service.getSnapshot().phase).toBe("downloaded");
    await service.install(async () => {});
    expect(reopened).toHaveBeenCalled(); stopReopened();
    await service.dispose();
  });
  it("retries network errors after fifteen minutes and then returns to the normal interval", async () => {
    vi.useFakeTimers();
    const { service, transport } = fixture();
    transport.check = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(null);
    const stop = service.startAutomaticUpdates(0);
    await vi.advanceTimersByTimeAsync(0);
    expect(service.state.phase).toBe("failed"); expect(service.state.error).toBe("offline");
    await vi.advanceTimersByTimeAsync(899_999); expect(transport.check).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1); expect(service.state.phase).toBe("current");
    await vi.advanceTimersByTimeAsync(21_599_999); expect(transport.check).toHaveBeenCalledTimes(2);
    stop(); await service.dispose();
  });
  it("does not run automatic checks in unsigned, development or unsupported packaging modes", async () => {
    vi.useFakeTimers();
    for (const available of [false, true]) {
      const { service, transport } = fixture(available);
      transport.configuration = async () => ({ available, automatic_download: false, current_version: "1.57.0", channel: TAURI_UPDATE_CHANNEL, endpoint: TAURI_UPDATE_ENDPOINT });
      service.startAutomaticUpdates(0);
      await vi.advanceTimersByTimeAsync(21_600_000);
      expect(transport.check).not.toHaveBeenCalled(); await service.dispose();
    }
  });
  it("shares initialization and has only one timer through a startup effect remount", async () => {
    vi.useFakeTimers();
    const { service, transport } = fixture();
    await Promise.all([service.initialize(), service.initialize()]);
    expect(transport.configuration).toHaveBeenCalledOnce();
    const staleStop = service.startAutomaticUpdates(0);
    const stop = service.startAutomaticUpdates(0);
    staleStop(); await vi.advanceTimersByTimeAsync(0);
    expect(transport.check).toHaveBeenCalledOnce(); stop(); await service.dispose();
  });
  it("does not call a download verified when signature validation rejects after transfer", async () => {
    const { service, handle } = fixture();
    handle.download = vi.fn(async callback => { callback({ event: "Finished" }); throw new Error("invalid signature"); });
    await service.initialize(); await service.check(); await service.download();
    expect(service.state.phase).toBe("failed"); expect(service.state.error).toBe("invalid signature");
    await service.install(async () => {}); expect(handle.install).not.toHaveBeenCalled();
    await service.dispose();
  });
  it("stops automatic timers and prevents installation after disposal during saving", async () => {
    vi.useFakeTimers();
    const { service, handle, transport } = fixture();
    await service.initialize(); await service.check(); await service.download();
    service.startAutomaticUpdates(0);
    let saved!: () => void;
    const installing = service.install(() => new Promise<void>(resolve => { saved = resolve; }));
    const closed = service.dispose(); saved(); await installing; await closed;
    await vi.advanceTimersByTimeAsync(43_200_000);
    expect(handle.install).not.toHaveBeenCalled(); expect(handle.close).toHaveBeenCalledOnce(); expect(transport.check).toHaveBeenCalledOnce();
  });
});
