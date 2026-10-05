import { useEffect, useState, useSyncExternalStore } from "react";
import { isDesktop } from "./runtime";
import { UpdateController } from "./updater";

/** The downloaded native resource lives with the app, independently of the update dialog. */
export function useTauriUpdates(ready: boolean) {
  const [controller] = useState(() => new UpdateController());
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  useEffect(() => {
    if (ready && isDesktop()) return controller.startAutomaticUpdates();
  }, [controller, ready]);
  return { controller, state };
}
