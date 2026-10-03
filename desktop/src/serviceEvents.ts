import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { isDesktop } from "./runtime";
export interface ServiceEvent { event: string; payload: Record<string, unknown> }
export function isServiceEvent(value: unknown): value is ServiceEvent {
  return !!value && typeof value === "object" && typeof (value as ServiceEvent).event === "string" && !!(value as ServiceEvent).payload && typeof (value as ServiceEvent).payload === "object" && !Array.isArray((value as ServiceEvent).payload);
}
export async function subscribeServiceEvents(callback: (event: ServiceEvent) => void): Promise<UnlistenFn> {
  if (!isDesktop()) return () => {};
  return listen<unknown>("runtime-event", ({ payload }) => { if (isServiceEvent(payload)) callback(payload); });
}
