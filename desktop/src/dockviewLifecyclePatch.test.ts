import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
// @ts-expect-error Independently executable maintenance module.
import { DOCKVIEW_PATCH_TARGETS, patchDockview, sha256 } from "../scripts/apply-dockview-patch.mjs";
// @ts-expect-error Independently executable maintenance module.
import { callbacksAfter, resizeBefore, resizeAfter, reverseDockviewLifecycle } from "../scripts/apply-dockview-lifecycle-patch.mjs";

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packagePath = "node_modules/dockview-core";
const manifestName = "dockview-core-8.4.0-pointer-hashes.json";
const manifestText = readFileSync(join(desktop, "patches", manifestName), "utf8");
const manifest = JSON.parse(manifestText);

interface Disposable { dispose(): void }
class CompositeDisposable {
  private disposed = false;
  constructor(private readonly items: Disposable[]) {}
  dispose() { if (this.disposed) return; this.disposed = true; for (const item of this.items) item.dispose(); }
}
const disposable = { from: (dispose: () => void): Disposable => ({ dispose }) };
const listener = (target: EventTarget, name: string, callback: EventListener): Disposable => {
  target.addEventListener(name, callback);
  return { dispose: () => target.removeEventListener(name, callback) };
};
type ResizeHelper = (target: EventTarget, callback: () => void) => Disposable;
function helper(source: string, timers = { setTimeout, clearTimeout }): ResizeHelper {
  return new Function("CompositeDisposable", "Disposable", "addDisposableListener", "setTimeout", "clearTimeout", "DEBOUCE_DELAY", `${source}; return onDidWindowResizeEnd;`)(
    function (...items: Disposable[]) { return new CompositeDisposable(items); }, disposable, listener, timers.setTimeout, timers.clearTimeout, 100,
  ) as ResizeHelper;
}
function installedHelper(path: string): string {
  const source = readFileSync(join(desktop, packagePath, path), "utf8");
  const start = source.indexOf("function onDidWindowResizeEnd(element, cb) {");
  const end = source.indexOf("\nfunction shiftAbsoluteElementIntoView", start);
  expect(start).toBeGreaterThan(0); expect(end).toBeGreaterThan(start);
  return source.slice(start, end);
}
afterEach(() => vi.useRealTimers());

describe("Dockview native-popout timer lifetime", () => {
  it("reproduces the pinned upstream crash after resize, disposal and native window teardown", () => {
    vi.useFakeTimers();
    const target = new EventTarget(), current: { window: { innerWidth: number } | null } = { window: { innerWidth: 900 } };
    const callback = vi.fn(() => current.window!.innerWidth);
    const binding = helper(resizeBefore)(target, callback);
    target.dispatchEvent(new Event("resize")); binding.dispose(); current.window = null;
    expect(vi.getTimerCount()).toBe(1);
    expect(() => vi.advanceTimersByTime(100)).toThrow("innerWidth");
    expect(callback).toHaveBeenCalledOnce();
  });

  it.each(DOCKVIEW_PATCH_TARGETS as string[])("cancels pending resize on disposal in the actual %s entry point", path => {
    vi.useFakeTimers();
    const target = new EventTarget(), callback = vi.fn(), source = installedHelper(path);
    expect(source).toBe(resizeAfter);
    const binding = helper(source)(target, callback);
    target.dispatchEvent(new Event("resize")); binding.dispose(); binding.dispose();
    expect(vi.getTimerCount()).toBe(0);
    target.dispatchEvent(new Event("resize")); vi.advanceTimersByTime(500);
    expect(callback).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps ordinary resize debounce and delivers the latest geometry once", () => {
    vi.useFakeTimers();
    const target = new EventTarget(), view = { innerWidth: 900, innerHeight: 300 }, callback = vi.fn(() => ({ ...view }));
    const binding = helper(installedHelper(DOCKVIEW_PATCH_TARGETS[0]))(target, callback);
    target.dispatchEvent(new Event("resize")); vi.advanceTimersByTime(60);
    view.innerWidth = 1440; view.innerHeight = 940;
    target.dispatchEvent(new Event("resize")); vi.advanceTimersByTime(99);
    expect(callback).not.toHaveBeenCalled(); vi.advanceTimersByTime(1);
    expect(callback).toHaveReturnedWith({ innerWidth: 1440, innerHeight: 940 });
    expect(callback).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
    binding.dispose();
  });

  it("ignores a timer callback already captured by an event loop when disposal wins", () => {
    let queued: (() => void) | undefined;
    const timers = { setTimeout: ((callback: () => void) => { queued = callback; return 1; }) as unknown as typeof setTimeout, clearTimeout: vi.fn() as unknown as typeof clearTimeout };
    const callback = vi.fn(), target = new EventTarget(), binding = helper(resizeAfter, timers)(target, callback);
    target.dispatchEvent(new Event("resize")); binding.dispose(); queued?.();
    expect(callback).not.toHaveBeenCalled();
  });

  it("permits disposal from the callback itself without retaining listeners or rescheduling", () => {
    vi.useFakeTimers();
    const target = new EventTarget(); let binding: Disposable;
    const callback = vi.fn(() => { binding.dispose(); target.dispatchEvent(new Event("resize")); });
    binding = helper(resizeAfter)(target, callback);
    target.dispatchEvent(new Event("resize")); vi.advanceTimersByTime(500);
    expect(callback).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
});

interface NativeView { innerWidth: number; innerHeight: number; screenX: number; screenY: number; closed?: boolean }
function popoutCallbacks(view: NativeView | null, gridDisposed = false) {
  const callbacks: Record<string, () => void> = {}, current = { window: view };
  const size = vi.fn(), position = vi.fn(), layout = vi.fn(), group = { id: "results" };
  const block = callbacksAfter.slice(0, callbacksAfter.indexOf(", overlayRenderContainer")) + ");";
  new Function("_window", "popoutWindowDisposable", "onDidWindowResizeEnd", "_onDidWindowPositionChange", "addDisposableListener", "popoutGridview", "value", "popoutGridviewDisposed", block).call(
    { _onDidPopoutGroupSizeChange: { fire: size }, _onDidPopoutGroupPositionChange: { fire: position } },
    current, { addDisposables() {} }, (_target: unknown, callback: () => void) => { callbacks.end = callback; },
    { event: (callback: () => void) => { callbacks.move = callback; } }, (_target: unknown, _event: unknown, callback: () => void) => { callbacks.resize = callback; },
    { layout }, { popoutGroup: group }, gridDisposed,
  );
  return { callbacks, current, size, position, layout, group };
}
describe("late popout geometry events", () => {
  const live: NativeView = { innerWidth: 900, innerHeight: 300, screenX: -1500, screenY: 200 };
  it("delivers current size, position and layout without changing logical screen coordinates", () => {
    const test = popoutCallbacks(live); Object.values(test.callbacks).forEach(callback => callback());
    expect(test.size).toHaveBeenCalledWith({ width: 900, height: 300, group: test.group });
    expect(test.position).toHaveBeenCalledWith({ screenX: -1500, screenY: 200, group: test.group });
    expect(test.layout).toHaveBeenCalledWith(900, 300);
  });
  it.each(["absent", "closed", "disposed"])("drops queued geometry events for a %s native window", reason => {
    const test = popoutCallbacks({ ...live, closed: reason === "closed" }, reason === "disposed");
    if (reason === "absent") test.current.window = null;
    expect(() => Object.values(test.callbacks).forEach(callback => callback())).not.toThrow();
    expect(test.size).not.toHaveBeenCalled(); expect(test.position).not.toHaveBeenCalled(); expect(test.layout).not.toHaveBeenCalled();
  });
  it("handles a close triggered synchronously by a size listener before another queued event", () => {
    const test = popoutCallbacks(live); test.size.mockImplementationOnce(() => { test.current.window = null; });
    test.callbacks.end(); test.callbacks.move(); test.callbacks.resize();
    expect(test.size).toHaveBeenCalledOnce(); expect(test.position).not.toHaveBeenCalled(); expect(test.layout).not.toHaveBeenCalled();
  });
});

describe("reproducible Dockview lifecycle installation", () => {
  it("upgrades the previous pointer-only patch in both exports and remains idempotent", () => {
    const root = mkdtempSync(join(tmpdir(), "datapyn-dockview-lifecycle-"));
    try {
      mkdirSync(join(root, "patches")); mkdirSync(join(root, packagePath, "dist/package"), { recursive: true });
      writeFileSync(join(root, "patches", manifestName), manifestText);
      writeFileSync(join(root, packagePath, "package.json"), readFileSync(join(desktop, packagePath, "package.json")));
      for (const path of DOCKVIEW_PATCH_TARGETS as string[]) {
        const previous = reverseDockviewLifecycle(readFileSync(join(desktop, packagePath, path), "utf8"));
        expect(sha256(previous)).toBe(manifest.files[path].pointer_patched);
        writeFileSync(join(root, packagePath, path), previous);
      }
      expect(patchDockview(root)).toBe(2);
      for (const path of DOCKVIEW_PATCH_TARGETS as string[]) expect(sha256(readFileSync(join(root, packagePath, path)))).toBe(manifest.files[path].patched);
      expect(patchDockview(root)).toBe(0);
    } finally {
      if (dirname(root) !== resolve(tmpdir()) || !basename(root).startsWith("datapyn-dockview-lifecycle-")) throw new Error("Unexpected temporary fixture path");
      rmSync(root, { recursive: true, force: true });
    }
  });
});
