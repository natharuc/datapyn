import type {RuntimeTransport} from "./runtime";
export interface NotificationFlags {notifications:boolean;notificationSound:boolean}
export async function readNotificationFlags(transport:RuntimeTransport):Promise<NotificationFlags> {
  const loaded=await transport.request<{settings:Record<string,unknown>}>("notifications.settings.get");
  return {notifications:loaded.settings.enabled === true,notificationSound:loaded.settings.sound === true};
}
/** Edit only the global flags; templates, transports and credentials retain their own settings. */
export async function saveNotificationFlags(transport:RuntimeTransport,flags:NotificationFlags):Promise<void> {
  const loaded=await transport.request<{settings:Record<string,unknown>}>("notifications.settings.get");
  await transport.request("notifications.settings.set",{settings:{...loaded.settings,enabled:flags.notifications,sound:flags.notificationSound}});
}
