import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { NotificationEntry, NotificationTarget } from "./executionNotifications";

interface NativeActivation { notification_id: string; target: NotificationTarget }
interface NativeFailure extends NativeActivation { error: { code: string; message: string; setting?: string } }
const validTarget = (target: unknown): target is NotificationTarget => Boolean(target && typeof target === "object" &&
  ["workspace_id", "session_id", "block_id", "execution_id"].every(key => typeof (target as Record<string, unknown>)[key] === "string" && /^[A-Za-z0-9_.-]{1,128}$/.test(String((target as Record<string, unknown>)[key]))));

export async function showNativeNotification(entry: NotificationEntry, sound: boolean) {
  if (!entry.target) return;
  await invoke("execution_notification_show", { notification: { title: entry.title.trim() ? entry.title : "DataPyn", body: entry.message, sound, target: entry.target } });
}
export async function focusNativeNotificationWindow(label = "main") {
  await invoke("execution_notification_focus_window", { label });
}

/** Subscribe before draining pending clicks; an event/pending race still activates once. */
export async function bindNativeNotifications(activate: (target: NotificationTarget) => void | Promise<void>, failed: (target: NotificationTarget, message: string) => void): Promise<() => void> {
  let disposed = false;
  const handled = new Set<string>();
  const receive = async (item: NativeActivation) => {
    if (disposed || !item || typeof item.notification_id !== "string" || !validTarget(item.target) || handled.has(item.notification_id)) return;
    handled.add(item.notification_id);
    while (handled.size > 256) handled.delete(handled.values().next().value!);
    try { await activate(item.target); }
    finally { await invoke("execution_notification_ack", { notificationId: item.notification_id }); }
  };
  const stop = await listen<NativeActivation>("datapyn-notification-activate", ({ payload }) => {
    void receive(payload).catch(error => { if (!disposed && validTarget(payload?.target)) failed(payload.target, nativeNotificationError(error)); });
  });
  let stopErrors: (() => void) | undefined;
  try {
    stopErrors = await listen<NativeFailure>("datapyn-notification-error", ({ payload }) => {
      if (!disposed && validTarget(payload?.target)) failed(payload.target, payload.error?.message ?? "Falha na notificação do sistema.");
    });
    const pending = await invoke<NativeActivation[]>("execution_notification_take_pending");
    for (const item of pending) await receive(item);
    return () => { disposed = true; stop(); stopErrors?.(); };
  } catch (error) { disposed = true; stop(); stopErrors?.(); throw error; }
}

export function nativeNotificationError(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) return String(error.message);
  return typeof error === "string" ? error : "Não foi possível mostrar a notificação do sistema.";
}
