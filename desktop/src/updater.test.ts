import { describe, expect, it, vi } from "vitest";
import { UpdateController, type UpdateHandle, type UpdateTransport } from "./updater";

function fixture(available = true) {
  const handle: UpdateHandle = {version:"1.58.0",body:"A new build",download:vi.fn(async callback=>{callback({event:"Started",data:{contentLength:10}});callback({event:"Progress",data:{chunkLength:10}});callback({event:"Finished"});}),install:vi.fn(async()=>{}),close:vi.fn(async()=>{})};
  const transport:UpdateTransport = {configuration:vi.fn(async()=>({available,current_version:"1.57.0",channel:"tauri-preview"})),check:vi.fn(async()=>handle),relaunch:vi.fn(async()=>{})};
  return {handle,transport,service:new UpdateController(()=>{},transport)};
}
describe("Tauri update lifecycle",()=>{
  it("never checks an unconfigured build or polls during initialization",async()=>{const {service,transport}=fixture(false);await service.initialize();await service.check();expect(service.state.phase).toBe("unavailable");expect(transport.check).not.toHaveBeenCalled();});
  it("flushes before installation and preserves download when saving fails",async()=>{const {service,handle}=fixture();await service.initialize();await service.check();await service.download();const flush=vi.fn(async()=>{throw new Error("disk full");});await service.install(flush);expect(handle.install).not.toHaveBeenCalled();expect(service.state.phase).toBe("downloaded");expect(service.state.error).toBe("disk full");const sequence:string[]=[];handle.install=vi.fn(async()=>{sequence.push("install");});await service.install(async()=>{sequence.push("save");});expect(sequence).toEqual(["save","install"]);});
  it("closes an update resource returned after dialog disposal",async()=>{const {service,handle,transport}=fixture();let resolve!:(value:UpdateHandle)=>void;transport.check=()=>new Promise(r=>{resolve=r;});await service.initialize();const pending=service.check();const closed=service.dispose();await Promise.resolve();resolve(handle);await pending;await closed;expect(handle.close).toHaveBeenCalledOnce();});
  it("requires downloading again after an installer consumes its resource and fails",async()=>{const {service,handle}=fixture();await service.initialize();await service.check();await service.download();handle.install=vi.fn(async()=>{throw new Error("installer failed");});await service.install(async()=>{});expect(service.state.phase).toBe("available");expect(service.state.error).toBe("installer failed");await service.download();expect(service.state.phase).toBe("downloaded");expect(handle.download).toHaveBeenCalledTimes(2);});
});
