import { afterEach,describe, expect, it, vi } from "vitest";
import { diffNativeWorkspace,NativeDrafts, type NativeWorkspaceState,type ProfileState } from "./nativeDrafts";
import type { RuntimeTransport } from "./runtime";

const state = (title: string): NativeWorkspaceState => ({documents: [{sessionId:"session-a",title, document: {blocks: []}}], activeIndex: 0});
const loaded=(value:NativeWorkspaceState):ProfileState=>({active_id:"profile-a",profile:{id:"profile-a",name:"A",path:"A",created_at:0},state:value});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});
describe("native workspace drafts", () => {
  it("captures the profile and immutable document at schedule time", async () => {
    const request = vi.fn().mockResolvedValue({});
    const drafts = new NativeDrafts({request, subscribe: vi.fn()} as RuntimeTransport, vi.fn(), 60_000);
    const document = state("Original"); drafts.schedule("profile-a", document); document.documents[0].title = "Changed";
    await drafts.flush(); expect(request).toHaveBeenCalledWith("workspace.profiles.patch", {profile_id:"profile-a",upserts:state("Original").documents,order:["session-a"],metadata:{activeIndex:0}}); drafts.dispose();
  });
  it("coalesces rapid edits and serializes saves before selecting another profile", async () => {
    const calls: string[] = [];
    const request = vi.fn(async (method: string, _params?: Record<string, unknown>) => {calls.push(method); return {};});
    const drafts = new NativeDrafts({request, subscribe: vi.fn()} as RuntimeTransport, vi.fn(), 60_000);
    drafts.schedule("profile-a", state("First")); drafts.schedule("profile-a", state("Latest"));
    await drafts.select("profile-b");
    expect(calls).toEqual(["workspace.profiles.patch", "workspace.profiles.select"]);
    expect(request.mock.calls[0][1]).toEqual({profile_id:"profile-a",upserts:state("Latest").documents,order:["session-a"],metadata:{activeIndex:0}}); drafts.dispose();
  });
  it("debounces edits and writes only the latest document once",async()=>{
    vi.useFakeTimers();const request=vi.fn().mockResolvedValue({}),drafts=new NativeDrafts({request} as unknown as RuntimeTransport,vi.fn(),500);
    drafts.schedule("profile-a",state("first"));await vi.advanceTimersByTimeAsync(250);drafts.schedule("profile-a",state("latest"));
    await vi.advanceTimersByTimeAsync(499);expect(request).not.toHaveBeenCalled();await vi.advanceTimersByTimeAsync(1);
    expect(request).toHaveBeenCalledOnce();expect(request.mock.calls[0][1].upserts[0].title).toBe("latest");drafts.dispose();
  });
  it("does not inspect or clone a large unchanged document and skips identical restored state",async()=>{
    const payload=new Proxy({},{get(){throw new Error("unchanged code was inspected");},ownKeys(){throw new Error("unchanged code was enumerated");}});
    const previous=state("small");previous.documents.push({sessionId:"large",title:"large",document:payload});previous.preferences={font:13};
    const request=vi.fn().mockResolvedValue({}),drafts=new NativeDrafts({request} as unknown as RuntimeTransport,vi.fn(),60_000);
    drafts.acknowledge(loaded(previous));vi.stubGlobal("structuredClone",()=>{throw new Error("whole-workspace clone");});
    drafts.schedule("profile-a",{...previous,preferences:{font:13}});await drafts.flush();expect(request).not.toHaveBeenCalled();
    const edited=state("small edited");edited.documents.push(previous.documents[1]);edited.preferences={font:13};drafts.schedule("profile-a",edited);await drafts.flush();
    const patch=request.mock.calls[0][1];expect(patch.upserts).toHaveLength(1);expect(patch.upserts[0].sessionId).toBe("session-a");expect(patch.metadata).toBeUndefined();drafts.dispose();
  });
  it("focus/cursor/header changes preserve the code reference and clear removed header fields",()=>{
    const previous=state("Original");previous.documents[0].filePath="C:/saved.dpw";
    const next={...previous,documents:[{...previous.documents[0],filePath:undefined,focusedBlockId:"second",editorViewState:{second:{viewState:{scrollTop:30}}}}]};
    const patch=diffNativeWorkspace("profile-a",next,previous)!;
    expect(patch.upserts![0]).not.toHaveProperty("document");expect(patch.upserts![0].remove_header).toEqual(["filePath"]);expect(patch.order).toBeUndefined();
  });
  it("merges removal, order, active tab and metadata changes into one transaction",()=>{
    const previous=state("Original");previous.documents.push({sessionId:"second",title:"second",document:{blocks:[]}});previous.layout={panel:"results"};previous.unknown="preserved-until-explicit-removal";
    const next={documents:[previous.documents[1]],activeIndex:0,layout:{panel:"summary"}};
    expect(diffNativeWorkspace("profile-a",next,previous)).toEqual({profile_id:"profile-a",removes:["session-a"],order:["second"],metadata:{layout:{panel:"summary"}},remove_metadata:["unknown"]});
  });
  it("serializes a newer edit behind an in-flight write and keeps captured profile IDs",async()=>{
    let release!:()=>void;const writes:Array<Record<string,unknown>>=[];
    const request=vi.fn(async (_method:string,params:Record<string,unknown>)=>{writes.push(params);if(writes.length===1)await new Promise<void>(resolve=>{release=resolve;});return {};});
    const drafts=new NativeDrafts({request} as unknown as RuntimeTransport,vi.fn(),60_000);
    drafts.schedule("profile-a",state("First"));const flushing=drafts.flush();await Promise.resolve();
    drafts.schedule("profile-a",state("Latest"));drafts.schedule("profile-b",state("Different profile"));release();await flushing;
    expect(writes.map(write=>write.profile_id)).toEqual(["profile-a","profile-a","profile-b"]);
    expect((writes[1].upserts as Array<{title:string}>)[0].title).toBe("Latest");drafts.dispose();
  });
  it("retries transient failures and retains newer edits after a final failure",async()=>{
    const request=vi.fn().mockRejectedValueOnce(new Error("temporary")).mockResolvedValue({});
    const drafts=new NativeDrafts({request} as unknown as RuntimeTransport,vi.fn(),60_000,1);
    drafts.schedule("profile-a",state("recover"));await drafts.flush();expect(request).toHaveBeenCalledTimes(2);
    request.mockRejectedValue(new Error("offline"));drafts.schedule("profile-a",state("unsaved"));await expect(drafts.flush()).rejects.toThrow("offline");
    request.mockResolvedValue({});drafts.schedule("profile-a",state("latest retry"));await drafts.flush();
    expect(request.mock.calls.at(-1)![1].upserts[0].title).toBe("latest retry");drafts.dispose();
  });
  it("does not select another profile when pending writes remain failed",async()=>{
    const request=vi.fn().mockRejectedValue(new Error("cannot save")),drafts=new NativeDrafts({request} as unknown as RuntimeTransport,vi.fn(),60_000,1);
    drafts.schedule("profile-a",state("unsaved"));await expect(drafts.select("profile-b")).rejects.toThrow("cannot save");
    expect(request.mock.calls.every(call=>call[0]==="workspace.profiles.patch")).toBe(true);drafts.dispose();
  });
  it("retains a captured final write after disposal for an explicit close flush",async()=>{
    const request=vi.fn().mockResolvedValue({}),drafts=new NativeDrafts({request} as unknown as RuntimeTransport,vi.fn(),60_000);
    drafts.schedule("profile-a",state("closing"));drafts.dispose();await drafts.flush();expect(request).toHaveBeenCalledOnce();
    expect(request.mock.calls[0][1].profile_id).toBe("profile-a");
  });
});
