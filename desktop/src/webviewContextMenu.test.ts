import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { describe, expect, it, vi } from "vitest";

// Execute the same plain script embedded by Tauri and loaded by the HTML pages.
const source = readFileSync(new URL("../public/webview-context-menu.js", import.meta.url), "utf8");
const load = (window: EventTarget) => runInNewContext(source, { window });

describe("webview browser context-menu guard", () => {
  it("cancels the browser action in capture without consuming application handlers", () => {
    const window = new EventTarget(), register = vi.spyOn(window, "addEventListener");
    load(window);
    const [type, , options] = register.mock.calls[0];
    expect(type).toBe("contextmenu");
    expect(typeof options === "boolean" ? options : options?.capture).toBe(true);

    const handler = vi.fn((event: Event) => expect(event.defaultPrevented).toBe(true));
    window.addEventListener("contextmenu", handler);
    const event = new Event("contextmenu", { cancelable: true, bubbles: true });
    const stop = vi.spyOn(event, "stopPropagation"), stopImmediate = vi.spyOn(event, "stopImmediatePropagation");
    expect(window.dispatchEvent(event)).toBe(false);
    expect(handler).toHaveBeenCalledOnce();
    expect(stop).not.toHaveBeenCalled();
    expect(stopImmediate).not.toHaveBeenCalled();
  });

  it("installs once when native initialization and the HTML page both load it", () => {
    const window = new EventTarget(), register = vi.spyOn(window, "addEventListener");
    load(window); load(window); load(window);
    expect(register).toHaveBeenCalledOnce();
    const event = new Event("contextmenu", { cancelable: true });
    const prevent = vi.spyOn(event, "preventDefault");
    window.dispatchEvent(event);
    expect(prevent).toHaveBeenCalledOnce();
  });

  it("installs independently in each webview document", () => {
    for (const window of [new EventTarget(), new EventTarget()]) {
      const register = vi.spyOn(window, "addEventListener");
      load(window); load(window);
      expect(register).toHaveBeenCalledOnce();
      const event = new Event("contextmenu", { cancelable: true });
      window.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
    }
  });
});
