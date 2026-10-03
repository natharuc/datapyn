import type { RuntimeTransport } from "./runtime";

export interface NativeDocumentRecord {title: string; filePath?: string; modified?: boolean; document: Record<string, unknown>; sessionId?: string; [key: string]: unknown}
export interface NativeWorkspaceState {documents: NativeDocumentRecord[]; activeIndex: number; preferences?: Record<string, unknown>; shortcuts?: Record<string, unknown>; layout?: Record<string, unknown>; [key: string]: unknown}
export interface WorkspaceProfile {id: string; name: string; path: string; archived?: boolean; created_at: number}
export interface ProfileState {active_id: string; profile: WorkspaceProfile; state?: NativeWorkspaceState | null}

/** Debounce saves, serialize writes and capture the profile at schedule time. */
export class NativeDrafts {
  private timer?: ReturnType<typeof setTimeout>;
  private pending?: {profileId: string; state: NativeWorkspaceState};
  private writing = Promise.resolve();
  constructor(private transport: RuntimeTransport, private onError: (error: unknown) => void, private delay = 500) {}
  schedule(profileId: string, state: NativeWorkspaceState) {
    this.pending = {profileId, state: structuredClone(state)};
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {this.timer = undefined; void this.flush().catch(this.onError);}, this.delay);
  }
  async flush() {
    if (this.timer) {clearTimeout(this.timer); this.timer = undefined;}
    const next = this.pending; this.pending = undefined;
    if (next) this.writing = this.writing.catch(() => {}).then(async () => {await this.transport.request("workspace.profiles.save", {profile_id: next.profileId, state: next.state});});
    await this.writing;
  }
  async load() {return this.transport.request<ProfileState>("workspace.profiles.state");}
  async select(profileId: string) {await this.flush(); return this.transport.request<ProfileState>("workspace.profiles.select", {profile_id: profileId});}
  dispose() {if (this.timer) clearTimeout(this.timer); this.timer = undefined; this.pending = undefined;}
}
