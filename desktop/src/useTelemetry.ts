import {useEffect} from "react";
import {runtime, isDesktop} from "./runtime";
import {version} from "../package.json";

/** Only fixed error categories cross IPC; never forward browser error objects. */
export function useTelemetry() {
  useEffect(() => {
    if (!isDesktop()) return;
    void runtime.request("telemetry.client", {version}).catch(() => {});
    let lastError = 0;
    const observe = () => {
      const now = Date.now();
      if (now - lastError < 10_000) return;
      lastError = now;
      void runtime.request("telemetry.event", {event: "ui_error", status: "error", error_code: "unknown"}).catch(() => {});
    };
    window.addEventListener("error", observe);
    window.addEventListener("unhandledrejection", observe);
    return () => {window.removeEventListener("error", observe); window.removeEventListener("unhandledrejection", observe);};
  }, []);
}
