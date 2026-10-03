import { afterEach, describe, expect, it, vi } from "vitest";
import { runInNewContext } from "node:vm";
// Test the installed ESM entry internals, including the versioned postinstall patch.
// @ts-expect-error The patched internal module is deliberately not a public package API.
import { isGridFocused, isMouseEvent, overlayPortal, ownerDocumentOf, ownerWindowOf } from "../node_modules/@glideapps/glide-data-grid/dist/esm/common/owner-document.js";
// @ts-expect-error Internal upstream JavaScript has no declaration for its implementation.
import ClickOutsideContainer from "../node_modules/@glideapps/glide-data-grid/dist/esm/internal/click-outside-container/click-outside-container.js";
// @ts-expect-error Internal upstream JavaScript has no declaration for its implementation.
import { copyToClipboard } from "../node_modules/@glideapps/glide-data-grid/dist/esm/data-editor/data-editor-fns.js";
// @ts-expect-error Internal upstream JavaScript has no declaration for its implementation.
import { AnimationManager } from "../node_modules/@glideapps/glide-data-grid/dist/esm/internal/data-grid/animation-manager.js";

afterEach(() => vi.unstubAllGlobals());

describe("Glide 6.0.3 adopted grid document", () => {
  it("recognizes mouse and pointer events from a different realm without treating them as touch events", () => {
    class MouseEvent {}
    vi.stubGlobal("MouseEvent", MouseEvent);
    const popoutEvent = runInNewContext("new (class MouseEvent { clientX = 120; clientY = 80; button = 0; buttons = 1; })()");
    expect(popoutEvent instanceof MouseEvent).toBe(false);
    expect(isMouseEvent(popoutEvent)).toBe(true);
    expect(isMouseEvent({ clientX: 20, clientY: 30, pointerType: "mouse" })).toBe(true);
    expect(isMouseEvent({ touches: [{ clientX: 20, clientY: 30 }], changedTouches: [] })).toBe(false);
    expect(isMouseEvent(undefined)).toBe(false);
  });

  it("reads focus and the clipboard realm from the canvas/scroll document instead of the main window", () => {
    const focused = {}, other = {}, view = {}, document = { activeElement: focused, defaultView: view };
    vi.stubGlobal("document", { activeElement: other }); vi.stubGlobal("window", {});
    const canvas = { ownerDocument: document, contains: (node: unknown) => node === focused };
    expect(ownerDocumentOf(canvas)).toBe(document); expect(ownerWindowOf(document)).toBe(view);
    expect(isGridFocused(null, canvas)).toBe(true);
    document.activeElement = other; expect(isGridFocused(null, canvas)).toBe(false);
    expect(isGridFocused(null, null)).toBe(false);
  });

  it("binds outside-click listeners to the popout document and removes exactly those listeners", () => {
    const main = { addEventListener: vi.fn(), removeEventListener: vi.fn() };
    const child = { addEventListener: vi.fn(), removeEventListener: vi.fn() }, closed = vi.fn();
    vi.stubGlobal("document", main);
    const container = new ClickOutsideContainer({ onClickOutside: closed });
    container.wrapperRef.current = { ownerDocument: child, contains: () => false };
    container.componentDidMount();
    expect(main.addEventListener).not.toHaveBeenCalled();
    expect(child.addEventListener.mock.calls.map(call => call[0])).toEqual(["touchend", "mousedown", "contextmenu"]);
    container.clickOutside({ target: { classList: { contains: () => false }, parentElement: null } });
    expect(closed).toHaveBeenCalledOnce();
    container.componentWillUnmount();
    expect(child.removeEventListener.mock.calls).toEqual(child.addEventListener.mock.calls);
    expect(main.removeEventListener).not.toHaveBeenCalled();
  });

  it("creates the overlay host in the child document once, without redirecting overlays to the main page", () => {
    let portal: { id: string; dataset: Record<string, string> } | undefined;
    const append = vi.fn((element: typeof portal) => { portal = element; });
    const document = { getElementById: () => portal ?? null, createElement: () => ({ id: "", dataset: {} }), body: { append } };
    vi.stubGlobal("document", { getElementById: () => ({ main: true }) });
    const first = overlayPortal(document);
    expect(first.id).toBe("portal"); expect(first.dataset.gdgPortal).toBe("true");
    expect(overlayPortal(document)).toBe(first); expect(append).toHaveBeenCalledOnce();
  });

  it("uses the child's ClipboardItem/Blob constructors and clipboard for programmatic copy", () => {
    const write = vi.fn(), mainWrite = vi.fn();
    class ChildBlob { constructor(readonly data: unknown[], readonly options: unknown) {} }
    class ChildClipboardItem { constructor(readonly data: Record<string, unknown>) {} }
    const view = { navigator: { clipboard: { write } }, Blob: ChildBlob, ClipboardItem: ChildClipboardItem };
    vi.stubGlobal("window", { navigator: { clipboard: { write: mainWrite } } });
    copyToClipboard([[{ kind: "text", data: "value", displayData: "value", allowOverlay: false }]], [0], undefined, { defaultView: view });
    expect(mainWrite).not.toHaveBeenCalled(); expect(write).toHaveBeenCalledOnce();
    const item = write.mock.calls[0][0][0] as ChildClipboardItem;
    expect(item).toBeInstanceOf(ChildClipboardItem); expect(item.data["text/plain"]).toBeInstanceOf(ChildBlob);
    expect((item.data["text/plain"] as ChildBlob).data).toEqual(["value"]);
  });

  it("cancels child-window hover animation on redock/unmount and ignores pending frames", () => {
    const requestAnimationFrame = vi.fn(() => 17), cancelAnimationFrame = vi.fn(), render = vi.fn();
    const manager = new AnimationManager(render, { requestAnimationFrame, cancelAnimationFrame });
    manager.setHovered([0, 0]); expect(requestAnimationFrame).toHaveBeenCalledOnce();
    manager.dispose(); expect(cancelAnimationFrame).toHaveBeenCalledWith(17);
    manager.step(100); manager.setHovered([1, 1]); expect(render).not.toHaveBeenCalled();
    expect(requestAnimationFrame).toHaveBeenCalledOnce();
  });
});
