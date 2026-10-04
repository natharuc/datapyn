import { afterEach, describe, expect, it, vi } from "vitest";
import { activateNotificationTarget, NotificationCenter, shouldNotify, type NotificationTarget } from "./executionNotifications";
import type { NotificationResult } from "./NotificationsDialog";
import type { RuntimeTransport } from "./runtime";
import { WorkspaceController } from "./workspace";

const centers: NotificationCenter[] = [];
const workspaces: WorkspaceController[] = [];
afterEach(() => {
  centers.splice(0).forEach(center => center.dispose());
  workspaces.splice(0).forEach(workspace => workspace.dispose());
  vi.useRealTimers();
});

const target = (execution = "execution-1", overrides: Partial<NotificationTarget> = {}): NotificationTarget => ({
  workspace_id: "profile-1", session_id: "session-1", block_id: "block-1", execution_id: execution, ...overrides,
});
function center() {
  vi.useFakeTimers();
  const value = new NotificationCenter();
  value.setWorkspace("profile-1");
  centers.push(value);
  return value;
}
const completed = (destination = target()) => ({ title: "Concluído", message: "Mesma mensagem", success: true, target: destination });
const result = (overrides: Partial<NotificationResult> = {}): NotificationResult => ({
  title: "Concluído", message: "1 linha", success: true, enabled: true, sound: true,
  suppressed: false, send_external: false, channels: { telegram: false, email: false }, ...overrides,
});

describe("execution notification history and independent lifetimes", () => {
  it("bounds history to 100 and visible toasts/timers to three without losing unread history", () => {
    const value = center();
    for (let index = 0; index < 105; index++) value.publish(completed(target(`execution-${index}`)));
    const state = value.getSnapshot();
    expect(state.entries).toHaveLength(100);
    expect(state.toasts).toHaveLength(3);
    expect(state.unread).toBe(100);
    expect(state.entries[0].target?.execution_id).toBe("execution-104");
    expect(state.entries.at(-1)?.target?.execution_id).toBe("execution-5");
    expect(state.toasts.map(entry => entry.target?.execution_id)).toEqual(["execution-104", "execution-103", "execution-102"]);
    expect(vi.getTimerCount()).toBe(3);
    vi.advanceTimersByTime(6500);
    expect(value.getSnapshot().toasts).toEqual([]);
    expect(value.getSnapshot().entries).toHaveLength(100);
    expect(value.getSnapshot().unread).toBe(100);
  });

  it("identical messages from different executions keep independent identities and expiration", () => {
    const value = center(), first = value.publish(completed(target("first")))!;
    vi.advanceTimersByTime(1000);
    const second = value.publish(completed(target("second")))!;
    expect(first.id).not.toBe(second.id);
    expect(first.id).toBe(JSON.stringify(target("first")));
    vi.advanceTimersByTime(5500);
    expect(value.getSnapshot().toasts.map(entry => entry.id)).toEqual([second.id]);
    vi.advanceTimersByTime(1000);
    expect(value.getSnapshot().toasts).toEqual([]);
    expect(value.getSnapshot().entries.map(entry => entry.id)).toEqual([second.id, first.id]);
  });

  it("deduplicates a repeated completion without replacing its message or restarting its timer", () => {
    const value = center(), first = value.publish(completed())!;
    vi.advanceTimersByTime(6000);
    expect(value.publish({ ...completed(), message: "Resposta repetida atrasada" })).toBeUndefined();
    expect(value.getSnapshot().entries).toHaveLength(1);
    expect(value.getSnapshot().entries[0].message).toBe(first.message);
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(500);
    expect(value.getSnapshot().toasts).toEqual([]);
    expect(value.publish(completed())).toBeUndefined();
  });

  it("pauses one toast while another expires and resumes without accumulating timers", () => {
    const value = center(), paused = value.publish(completed(target("paused")))!;
    vi.advanceTimersByTime(3000);
    value.pause(paused.id);
    const other = value.publish(completed(target("other")))!;
    vi.advanceTimersByTime(7000);
    expect(value.getSnapshot().toasts.map(entry => entry.id)).toEqual([paused.id]);
    expect(value.getSnapshot().entries.some(entry => entry.id === other.id)).toBe(true);
    value.resume(paused.id);
    value.resume(paused.id);
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(6499);
    expect(value.getSnapshot().toasts).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(value.getSnapshot().toasts).toEqual([]);
    value.resume(paused.id);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps an error visible longer and allows dismissing it without deleting history", () => {
    const value = center(), failed = value.publish({ ...completed(), success: false, status: "failed" })!;
    vi.advanceTimersByTime(9999);
    expect(value.getSnapshot().toasts).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(value.getSnapshot().toasts).toEqual([]);
    const another = value.publish(completed(target("another")))!;
    value.dismiss(another.id);
    expect(vi.getTimerCount()).toBe(0);
    expect(value.getSnapshot().entries.map(entry => entry.id)).toEqual([another.id, failed.id]);
    expect(value.getSnapshot().unread).toBe(2);
  });

  it("marks only the selected execution read, synchronizes its toast and notifies subscribers", () => {
    const value = center(), changed = vi.fn(), unsubscribe = value.subscribe(changed);
    const first = value.publish(completed(target("first")))!, second = value.publish(completed(target("second")))!;
    value.markRead(first.id);
    expect(value.getSnapshot().unread).toBe(1);
    expect(value.getSnapshot().toasts.find(entry => entry.id === first.id)?.read).toBe(true);
    expect(value.getSnapshot().toasts.find(entry => entry.id === second.id)?.read).toBe(false);
    expect(changed).toHaveBeenCalledTimes(3);
    unsubscribe();
    value.markRead();
    expect(value.getSnapshot().unread).toBe(0);
    expect(changed).toHaveBeenCalledTimes(3);
  });

  it("clears lifetimes on workspace switch and rejects late events and delivery errors from the old profile", () => {
    const value = center();
    value.publish(completed());
    value.setWorkspace("profile-1");
    expect(value.getSnapshot().entries).toHaveLength(1);
    value.setWorkspace("profile-2");
    expect(value.getSnapshot()).toEqual({ entries: [], toasts: [], unread: 0 });
    expect(vi.getTimerCount()).toBe(0);
    expect(value.publish(completed())).toBeUndefined();
    const next = value.publish(completed(target("next", { workspace_id: "profile-2" })))!;
    value.deliveryError(target(), "Entrega antiga");
    expect(value.getSnapshot().entries).toEqual([next]);
    value.setWorkspace(undefined);
    expect(value.publish(completed(target("next", { workspace_id: "profile-2" })))).toBeUndefined();
    expect(value.getSnapshot().entries).toEqual([]);
  });

  it("allows the same stable execution identity again only after leaving and returning to a workspace", () => {
    const value = center();
    value.publish(completed());
    value.setWorkspace("profile-2");
    value.setWorkspace("profile-1");
    expect(value.publish(completed())).toBeDefined();
    expect(value.getSnapshot().entries).toHaveLength(1);
  });

  it("bounds text and associates a transport error with the exact execution, not an identical message", () => {
    const value = center();
    const first = value.publish({ ...completed(target("first")), title: "t".repeat(300), message: "m".repeat(5000) })!;
    const second = value.publish(completed(target("second")))!;
    value.deliveryError(target("first"), "e".repeat(1000));
    expect(value.getSnapshot().entries.find(entry => entry.id === first.id)).toMatchObject({ title: "t".repeat(256), message: "m".repeat(4096), deliveryError: "e".repeat(512) });
    expect(value.getSnapshot().toasts.find(entry => entry.id === first.id)?.deliveryError).toHaveLength(512);
    expect(value.getSnapshot().entries.find(entry => entry.id === second.id)?.deliveryError).toBeUndefined();
  });

  it("rejects empty messages and releases timers/subscriptions on disposal", () => {
    const value = center();
    expect(value.publish({ title: "", message: "", success: true })).toBeUndefined();
    const changed = vi.fn(); value.subscribe(changed);
    value.publish(completed()); value.dispose();
    expect(vi.getTimerCount()).toBe(0);
    const calls = changed.mock.calls.length;
    value.markRead();
    expect(changed).toHaveBeenCalledTimes(calls);
    expect(value.getSnapshot().entries).toEqual([]);
  });

  it("retains an early delivery error until its exact completion and clears pending errors on profile change", () => {
    const value = center();
    value.deliveryError(target("first"), "Windows indisponível");
    value.publish(completed(target("other")));
    expect(value.publish(completed(target("first")))?.deliveryError).toBe("Windows indisponível");
    expect(value.getSnapshot().entries.find(entry => entry.target?.execution_id === "other")?.deliveryError).toBeUndefined();
    value.deliveryError(target("later"), "Perfil anterior");
    value.setWorkspace("profile-2"); value.setWorkspace("profile-1");
    expect(value.publish(completed(target("later")))?.deliveryError).toBeUndefined();
  });

  it("does not repopulate cleared history with late delivery failures", () => {
    const value = center();
    value.publish(completed()); value.clear();
    value.deliveryError(target(), "Entrega atrasada");
    expect(value.getSnapshot().entries).toEqual([]);
    expect(value.publish(completed())).toBeUndefined();
  });
});

describe("execution notification eligibility", () => {
  it.each([
    ["enabled", {}, true],
    ["globally disabled", { enabled: false }, false],
    ["suppressed by a conditional rule", { suppressed: true }, false],
    ["empty", { title: "", message: "" }, false],
    ["message only", { title: "" }, true],
    ["title only", { message: "" }, true],
    ["local without external channels or sound", { send_external: false, sound: false }, true],
  ] as Array<[string, Partial<NotificationResult>, boolean]>)("%s", (_label, overrides, expected) => {
    expect(shouldNotify(result(overrides))).toBe(expected);
  });
});

function workspace() {
  const request = vi.fn(async () => ({}));
  const transport = { request, subscribe: vi.fn(async () => () => {}) } as RuntimeTransport;
  const controller = new WorkspaceController(transport, undefined, { nativePersistence: true });
  workspaces.push(controller);
  return { controller, request };
}

describe("clicking an execution notification", () => {
  it("activates the originating session and actual block, expanding it and clearing another maximized block without executing", () => {
    const { controller, request } = workspace(), original = controller.session()!;
    const notified = controller.addBlock(original.id, "python", "print('keep code')");
    controller.updateBlock(original.id, notified.id, { collapsed: true });
    controller.focusBlock(original.id, original.blocks[0].id);
    controller.maximizeBlock(original.id, original.blocks[0].id);
    const other = controller.createSession();
    const before = controller.session(original.id)!;
    const destination = target("done", { session_id: original.id, block_id: notified.id });
    expect(controller.session()!.id).toBe(other.id);
    expect(activateNotificationTarget(controller, "profile-1", destination)).toBe(true);
    const selected = controller.session()!;
    expect(selected.id).toBe(original.id);
    expect(selected.focusedBlockId).toBe(notified.id);
    expect(selected.maximizedBlockId).toBeUndefined();
    expect(selected.blocks.find(block => block.id === notified.id)).toMatchObject({ collapsed: false, code: "print('keep code')" });
    expect(selected.blocks[0]).toBe(before.blocks[0]);
    expect(selected.modified).toBe(before.modified);
    expect(request).not.toHaveBeenCalled();
  });

  it("preserves maximization when the notified block itself is maximized and preserves unrelated blocks", () => {
    const { controller, request } = workspace(), session = controller.session()!;
    const other = controller.addBlock(session.id, "sql", "SELECT 1");
    controller.maximizeBlock(session.id, other.id);
    controller.focusBlock(session.id, session.blocks[0].id);
    const blocks = controller.session(session.id)!.blocks;
    expect(activateNotificationTarget(controller, "profile-1", target("done", { session_id: session.id, block_id: other.id }))).toBe(true);
    expect(controller.session()!.maximizedBlockId).toBe(other.id);
    expect(controller.session()!.blocks).toBe(blocks);
    expect(request).not.toHaveBeenCalled();
  });

  it("uses stable IDs after reordering instead of a block index or current focus", () => {
    const { controller } = workspace(), session = controller.session()!;
    const notified = controller.addBlock(session.id, "python", "value = 1"), third = controller.addBlock(session.id, "python", "value = 2");
    controller.reorderBlock(session.id, notified.id, session.blocks[0].id);
    controller.focusBlock(session.id, third.id);
    expect(activateNotificationTarget(controller, "profile-1", target("done", { session_id: session.id, block_id: notified.id }))).toBe(true);
    expect(controller.session()!.focusedBlockId).toBe(notified.id);
    expect(controller.session()!.blocks[0].id).toBe(notified.id);
  });

  it("rejects clicks while profile editing is locked and rejects a stale or unloaded workspace without mutation", () => {
    const { controller, request } = workspace(), session = controller.session()!;
    const destination = target("done", { session_id: session.id, block_id: session.blocks[0].id });
    const before = controller.getSnapshot();
    controller.setEditingLocked(true);
    expect(activateNotificationTarget(controller, "profile-1", destination)).toBe(false);
    controller.setEditingLocked(false);
    expect(activateNotificationTarget(controller, "profile-2", destination)).toBe(false);
    expect(activateNotificationTarget(controller, undefined, destination)).toBe(false);
    expect(controller.getSnapshot()).toBe(before);
    expect(request).not.toHaveBeenCalled();
  });

  it("does not replace a closed session or recreate a deleted block", async () => {
    const { controller, request } = workspace(), session = controller.session()!;
    const removed = controller.addBlock(session.id, "python", "answer = 42");
    controller.removeBlock(session.id, removed.id);
    const before = controller.getSnapshot();
    expect(activateNotificationTarget(controller, "profile-1", target("deleted", { session_id: session.id, block_id: removed.id }))).toBe(false);
    expect(controller.getSnapshot()).toBe(before);
    const destination = target("closed", { session_id: session.id, block_id: session.blocks[0].id });
    await controller.closeSession(session.id);
    const afterClose = controller.getSnapshot();
    expect(activateNotificationTarget(controller, "profile-1", destination)).toBe(false);
    expect(controller.getSnapshot()).toBe(afterClose);
    expect(request).not.toHaveBeenCalled();
  });
});
