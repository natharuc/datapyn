import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { NotificationEntry, NotificationTarget } from "./executionNotifications";
import { bindNativeNotifications, focusNativeNotificationWindow, nativeNotificationError, showNativeNotification } from "./nativeExecutionNotifications";

const native = vi.hoisted(() => ({ invoke: vi.fn(), listen: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: native.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: native.listen }));

type Handler = (event: { payload: unknown }) => void;
const callbacks = new Map<string, Handler>(), stops = new Map<string, ReturnType<typeof vi.fn>>();
const cleanups: Array<() => void> = [];
const destination: NotificationTarget = { workspace_id: "profile-1", session_id: "session-1", block_id: "block-1", execution_id: "execution-1" };
const activation = (id = "notification-1", overrides: Partial<NotificationTarget> = {}) => ({ notification_id: id, target: { ...destination, ...overrides } });
const entry = (overrides: Partial<NotificationEntry> = {}): NotificationEntry => ({
  id: "local-id", title: "Concluído", message: "1 linha", success: true, createdAt: 100, read: false, target: { ...destination }, ...overrides,
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
async function settle() { for (let index = 0; index < 8; index++) await Promise.resolve(); }
const ackCalls = () => native.invoke.mock.calls.filter(([method]) => method === "execution_notification_ack");
const emit = (event: string, payload: unknown) => callbacks.get(event)?.({ payload });

beforeEach(() => {
  native.invoke.mockReset(); native.listen.mockReset(); callbacks.clear(); stops.clear();
  native.invoke.mockImplementation(async (method: string) => method === "execution_notification_take_pending" ? [] : undefined);
  native.listen.mockImplementation(async (event: string, callback: Handler) => {
    callbacks.set(event, callback);
    const stop = vi.fn(); stops.set(event, stop); return stop;
  });
});
afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); });

describe("native execution notification presentation", () => {
  it.each([true, false])("forwards sound=%s and all stable target IDs without sending other entry metadata", async sound => {
    await showNativeNotification(entry({ deliveryError: "SMTP timeout", status: "succeeded" }), sound);
    expect(native.invoke).toHaveBeenCalledExactlyOnceWith("execution_notification_show", { notification: {
      title: "Concluído", body: "1 linha", sound, target: destination,
    } });
  });

  it("does not create an unactionable native notification for a generic local message", async () => {
    await showNativeNotification(entry({ target: undefined }), true);
    expect(native.invoke).not.toHaveBeenCalled();
  });

  it("uses DataPyn for a message-only custom notification and restores the requested editor window", async () => {
    await showNativeNotification(entry({title:""}),false);
    expect(native.invoke).toHaveBeenCalledWith("execution_notification_show",{notification:{title:"DataPyn",body:"1 linha",sound:false,target:destination}});
    await focusNativeNotificationWindow("dock-popout-1");
    expect(native.invoke).toHaveBeenLastCalledWith("execution_notification_focus_window",{label:"dock-popout-1"});
  });

  it("propagates a native permission/platform failure so the local history can expose it", async () => {
    const failure = { code: "permission_denied", message: "Notificações bloqueadas" };
    native.invoke.mockRejectedValueOnce(failure);
    await expect(showNativeNotification(entry(), false)).rejects.toBe(failure);
    expect(nativeNotificationError(failure)).toBe("Notificações bloqueadas");
    expect(nativeNotificationError("Sistema indisponível")).toBe("Sistema indisponível");
    expect(nativeNotificationError(undefined)).toBe("Não foi possível mostrar a notificação do sistema.");
  });
});

describe("native activation delivery and listener lifetime", () => {
  it("subscribes to activation and failure before draining pending clicks, then acknowledges each activation", async () => {
    const activate = vi.fn(), failed = vi.fn();
    native.invoke.mockImplementation(async (method: string) => {
      if (method !== "execution_notification_take_pending") return;
      expect(callbacks.has("datapyn-notification-activate")).toBe(true);
      expect(callbacks.has("datapyn-notification-error")).toBe(true);
      return [activation("first"), activation("second", { session_id: "session-2", block_id: "block-2" })];
    });
    const stop = await bindNativeNotifications(activate, failed); cleanups.push(stop);
    expect(activate.mock.calls.map(([target]) => target)).toEqual([destination, { ...destination, session_id: "session-2", block_id: "block-2" }]);
    expect(ackCalls()).toEqual([
      ["execution_notification_ack", { notificationId: "first" }],
      ["execution_notification_ack", { notificationId: "second" }],
    ]);
    expect(failed).not.toHaveBeenCalled();
  });

  it("activates and acknowledges only once when pending drain races a native event while activation is still awaiting", async () => {
    const pending = deferred<Array<ReturnType<typeof activation>>>(), focusing = deferred<void>();
    native.invoke.mockImplementation(async (method: string) => method === "execution_notification_take_pending" ? pending.promise : undefined);
    const activate = vi.fn(() => focusing.promise), binding = bindNativeNotifications(activate, vi.fn());
    await settle();
    emit("datapyn-notification-activate", activation());
    emit("datapyn-notification-activate", activation());
    pending.resolve([activation(), activation()]);
    const stop = await binding; cleanups.push(stop);
    expect(activate).toHaveBeenCalledExactlyOnceWith(destination);
    expect(ackCalls()).toHaveLength(0);
    focusing.resolve(); await settle();
    expect(ackCalls()).toEqual([["execution_notification_ack", { notificationId: "notification-1" }]]);
    emit("datapyn-notification-activate", activation()); await settle();
    expect(activate).toHaveBeenCalledTimes(1);
    expect(ackCalls()).toHaveLength(1);
  });

  it("routes different native IDs independently even if their target and message are equal", async () => {
    const activate = vi.fn(), stop = await bindNativeNotifications(activate, vi.fn()); cleanups.push(stop);
    emit("datapyn-notification-activate", activation("first"));
    emit("datapyn-notification-activate", activation("second"));
    await settle();
    expect(activate).toHaveBeenCalledTimes(2);
    expect(ackCalls().map(([, params]) => params.notificationId)).toEqual(["first", "second"]);
  });

  it("ignores malformed targets/activation payloads without navigating or reporting a different session", async () => {
    const activate = vi.fn(), failed = vi.fn(), stop = await bindNativeNotifications(activate, failed); cleanups.push(stop);
    for (const payload of [null, {}, { ...activation(), notification_id: 123 },
      activation("empty", { block_id: "" }), activation("spaces", { session_id: "session other" }),
      activation("path", { workspace_id: "../other" }), activation("long", { execution_id: "x".repeat(129) }),
      { notification_id: "missing", target: { session_id: "session-1" } }]) emit("datapyn-notification-activate", payload);
    emit("datapyn-notification-error", { ...activation(), target: { ...destination, block_id: "" }, error: { message: "Bad target" } });
    await settle();
    expect(activate).not.toHaveBeenCalled(); expect(failed).not.toHaveBeenCalled(); expect(ackCalls()).toEqual([]);
  });

  it("acknowledges even if the target cannot be opened, without retrying the same event", async () => {
    const activate = vi.fn(async () => { throw new Error("Closed session"); });
    const stop = await bindNativeNotifications(activate, vi.fn()); cleanups.push(stop);
    emit("datapyn-notification-activate", activation()); await settle();
    expect(ackCalls()).toEqual([["execution_notification_ack", { notificationId: "notification-1" }]]);
    emit("datapyn-notification-activate", activation()); await settle();
    expect(activate).toHaveBeenCalledTimes(1);
  });

  it("reports native errors against their own target and supplies a fallback for missing error metadata", async () => {
    const activate = vi.fn(), failed = vi.fn(), stop = await bindNativeNotifications(activate, failed); cleanups.push(stop);
    emit("datapyn-notification-error", { ...activation(), error: { code: "permission_denied", message: "Sistema bloqueado" } });
    emit("datapyn-notification-error", activation("other", { block_id: "block-2" }));
    expect(failed.mock.calls).toEqual([[destination, "Sistema bloqueado"], [{ ...destination, block_id: "block-2" }, "Falha na notificação do sistema."]]);
    expect(activate).not.toHaveBeenCalled(); expect(ackCalls()).toEqual([]);
  });

  it("releases both subscriptions and rejects delayed callbacks after unmount/profile switch", async () => {
    const activate = vi.fn(), failed = vi.fn(), stop = await bindNativeNotifications(activate, failed);
    stop();
    expect(stops.get("datapyn-notification-activate")).toHaveBeenCalledOnce();
    expect(stops.get("datapyn-notification-error")).toHaveBeenCalledOnce();
    emit("datapyn-notification-activate", activation());
    emit("datapyn-notification-error", { ...activation(), error: { message: "Late old profile" } });
    await settle();
    expect(activate).not.toHaveBeenCalled(); expect(failed).not.toHaveBeenCalled(); expect(ackCalls()).toEqual([]);
  });

  it("cleans the first listener when failure-listener setup fails", async () => {
    const failure = new Error("Second listener failed"), firstStop = vi.fn();
    native.listen.mockResolvedValueOnce(firstStop).mockRejectedValueOnce(failure);
    await expect(bindNativeNotifications(vi.fn(), vi.fn())).rejects.toBe(failure);
    expect(firstStop).toHaveBeenCalledOnce();
    expect(native.invoke).not.toHaveBeenCalled();
  });

  it("cleans both listeners when pending-drain IPC fails and leaves old callbacks inert", async () => {
    const failure = new Error("Runtime closing"), activate = vi.fn(), failed = vi.fn();
    native.invoke.mockRejectedValueOnce(failure);
    await expect(bindNativeNotifications(activate, failed)).rejects.toBe(failure);
    expect(stops.get("datapyn-notification-activate")).toHaveBeenCalledOnce();
    expect(stops.get("datapyn-notification-error")).toHaveBeenCalledOnce();
    emit("datapyn-notification-activate", activation());
    emit("datapyn-notification-error", { ...activation(), error: { message: "After rejection" } });
    await settle();
    expect(activate).not.toHaveBeenCalled(); expect(failed).not.toHaveBeenCalled();
  });

  it("acknowledges a failing pending activation and releases both listeners before rejecting setup", async () => {
    const failure = new Error("Session removed"), activate = vi.fn(async () => { throw failure; });
    native.invoke.mockImplementation(async (method: string) => method === "execution_notification_take_pending" ? [activation()] : undefined);
    await expect(bindNativeNotifications(activate, vi.fn())).rejects.toBe(failure);
    expect(ackCalls()).toEqual([["execution_notification_ack", { notificationId: "notification-1" }]]);
    expect(stops.get("datapyn-notification-activate")).toHaveBeenCalledOnce();
    expect(stops.get("datapyn-notification-error")).toHaveBeenCalledOnce();
  });
});
