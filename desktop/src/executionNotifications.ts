import type { NotificationContext, NotificationResult } from "./NotificationsDialog";
import type { ExecutionFinished } from "./runtime";
import type { WorkspaceController } from "./workspace";

export interface NotificationTarget { workspace_id: string; session_id: string; block_id: string; execution_id: string }
export interface QueueCompletion {
  blockId: string; executionId: string; status: ExecutionFinished["status"];
  context: NotificationContext; notification?: NotificationResult; workspaceId?: string;
}
export interface NotificationEntry {
  id: string; title: string; message: string; color?: string; success: boolean; createdAt: number;
  read: boolean; target?: NotificationTarget; status?: ExecutionFinished["status"];
  deliveryError?: string;
}
interface NotificationState { entries: readonly NotificationEntry[]; toasts: readonly NotificationEntry[]; unread: number }
type IncomingNotification = Omit<NotificationEntry, "id" | "createdAt" | "read"> & { id?: string };
interface NotificationPresentation { toast?: boolean; read?: boolean }
export interface ExecutionNotificationFocus { workspaceId?: string; sessionId?: string; focused: boolean }

/** Only bounded text/identities reach the UI. Each completion owns its own lifetime. */
export class NotificationCenter {
  private state: NotificationState = { entries: [], toasts: [], unread: 0 };
  private listeners = new Set<() => void>();
  private timers = new Map<string, ReturnType<typeof setTimeout>>();
  private seen = new Set<string>();
  private pendingErrors = new Map<string, string>();
  private workspaceId?: string;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  getSnapshot = () => this.state;
  getWorkspaceIdentity = () => this.workspaceId;
  setWorkspace(id: string | undefined) {
    if (id === this.workspaceId) return;
    this.workspaceId = id; this.clear(); this.seen.clear();
  }
  publish(input: IncomingNotification, presentation: NotificationPresentation = {}): NotificationEntry | undefined {
    if (input.target && input.target.workspace_id !== this.workspaceId) return;
    const id = input.id ?? (input.target ? JSON.stringify(input.target) : crypto.randomUUID());
    if (this.seen.has(id) || (!input.title && !input.message)) return;
    this.seen.add(id);
    while (this.seen.size > 256) this.seen.delete(this.seen.values().next().value!);
    const entry: NotificationEntry = { ...input, id, title: input.title.slice(0, 256), message: input.message.slice(0, 4096), createdAt: Date.now(), read: presentation.read ?? false, deliveryError: input.deliveryError ?? this.pendingErrors.get(id) };
    this.pendingErrors.delete(id);
    const entries = [entry, ...this.state.entries].slice(0, 100), toasts = presentation.toast === false ? this.state.toasts : [entry, ...this.state.toasts].slice(0, 3);
    for (const old of this.state.toasts) if (!toasts.some(item => item.id === old.id)) this.clearTimer(old.id);
    this.update(entries, toasts);
    this.resume(id);
    return entry;
  }
  dismiss(id: string) { this.clearTimer(id); this.update(this.state.entries, this.state.toasts.filter(item => item.id !== id)); }
  pause(id: string) { this.clearTimer(id); }
  resume(id: string) {
    this.clearTimer(id);
    const entry = this.state.toasts.find(item => item.id === id); if (!entry) return;
    this.timers.set(id, setTimeout(() => this.dismiss(id), entry.success ? 6500 : 10000));
  }
  markRead(id?: string) {
    const entries = this.state.entries.map(entry => (!id || entry.id === id) && !entry.read ? { ...entry, read: true } : entry);
    const current = new Map(entries.map(entry => [entry.id, entry]));
    this.update(entries, this.state.toasts.map(entry => current.get(entry.id) ?? entry));
  }
  deliveryError(target: NotificationTarget, error: string) {
    if (target.workspace_id !== this.workspaceId) return;
    const id = JSON.stringify(target), text = error.slice(0, 512);
    if (!this.state.entries.some(entry => entry.id === id)) {
      if (this.seen.has(id)) return; // Cleared/expired history stays cleared.
      this.pendingErrors.set(id, text);
      while (this.pendingErrors.size > 64) this.pendingErrors.delete(this.pendingErrors.keys().next().value!);
      return;
    }
    const entries = this.state.entries.map(entry => entry.id === id ? { ...entry, deliveryError: text } : entry);
    const current = new Map(entries.map(entry => [entry.id, entry]));
    this.update(entries, this.state.toasts.map(entry => current.get(entry.id) ?? entry));
  }
  clear() {
    for (const timer of this.timers.values()) clearTimeout(timer); this.timers.clear(); this.pendingErrors.clear();
    this.update([], []);
  }
  dispose() { this.clear(); this.listeners.clear(); }
  private clearTimer(id: string) { clearTimeout(this.timers.get(id)); this.timers.delete(id); }
  private update(entries: readonly NotificationEntry[], toasts: readonly NotificationEntry[]) {
    this.state = { entries, toasts, unread: entries.filter(entry => !entry.read).length };
    this.listeners.forEach(listener => listener());
  }
}

export function shouldNotify(result: NotificationResult): boolean {
  return result.enabled && !result.suppressed && Boolean(result.title || result.message);
}

/** The originating tab is already showing its execution state, regardless of which block has focus. */
export function shouldDisplayExecutionNotification(target: NotificationTarget, focus: ExecutionNotificationFocus): boolean {
  return target.workspace_id === focus.workspaceId && (!focus.focused || target.session_id !== focus.sessionId);
}

/** Notifications navigate only on click, without replacing a document or executing code. */
export function activateNotificationTarget(workspace: WorkspaceController, activeWorkspaceId: string | undefined, target: NotificationTarget): boolean {
  if (workspace.isEditingLocked() || target.workspace_id !== activeWorkspaceId) return false;
  const session = workspace.session(target.session_id), block = session?.blocks.find(item => item.id === target.block_id);
  if (!session || !block) return false;
  workspace.patchSession(session.id, current => ({ ...current, focusedBlockId: block.id,
    maximizedBlockId: current.maximizedBlockId === block.id ? block.id : undefined,
    blocks: block.collapsed ? current.blocks.map(item => item.id === block.id ? { ...item, collapsed: false } : item) : current.blocks }));
  workspace.activate(session.id);
  return true;
}
