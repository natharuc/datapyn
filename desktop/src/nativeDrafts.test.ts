import { describe, expect, it, vi } from "vitest";
import { NativeDrafts, type NativeWorkspaceState } from "./nativeDrafts";
import type { RuntimeTransport } from "./runtime";

const state = (title: string): NativeWorkspaceState => ({documents: [{title, document: {blocks: []}}], activeIndex: 0});
describe("native workspace drafts", () => {
  it("captures the profile and immutable document at schedule time", async () => {
    const request = vi.fn().mockResolvedValue({});
    const drafts = new NativeDrafts({request, subscribe: vi.fn()} as RuntimeTransport, vi.fn(), 60_000);
    const document = state("Original"); drafts.schedule("profile-a", document); document.documents[0].title = "Changed";
    await drafts.flush(); expect(request).toHaveBeenCalledWith("workspace.profiles.save", {profile_id: "profile-a", state: state("Original")}); drafts.dispose();
  });
  it("coalesces rapid edits and serializes saves before selecting another profile", async () => {
    const calls: string[] = [];
    const request = vi.fn(async (method: string, _params?: Record<string, unknown>) => {calls.push(method); return {};});
    const drafts = new NativeDrafts({request, subscribe: vi.fn()} as RuntimeTransport, vi.fn(), 60_000);
    drafts.schedule("profile-a", state("First")); drafts.schedule("profile-a", state("Latest"));
    await drafts.select("profile-b");
    expect(calls).toEqual(["workspace.profiles.save", "workspace.profiles.select"]);
    expect(request.mock.calls[0][1]).toEqual({profile_id: "profile-a", state: state("Latest")}); drafts.dispose();
  });
});
