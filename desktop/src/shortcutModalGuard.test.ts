import { describe, expect, it } from "vitest";
import { hasVisibleShortcutDialog } from "./shortcutModalGuard";

function dialog({ hidden = false, monaco = false, modal = false, rects = 1, visibility = "visible", display = "block" } = {}) {
  return { closest: (selector: string) => selector.includes("monaco") ? monaco ? {} : null : hidden ? {} : null,
    getAttribute: (name: string) => name === "aria-modal" && modal ? "true" : null,
    getClientRects: () => ({ length: rects }), style: { visibility, display } };
}
function owner(...dialogs: ReturnType<typeof dialog>[]): Document {
  return { querySelectorAll: () => dialogs, defaultView: { getComputedStyle: (element: ReturnType<typeof dialog>) => element.style } } as unknown as Document;
}
describe("Shortcut modal guard", () => {
  it("blocks visible dialogs in the current window", () => {
    expect(hasVisibleShortcutDialog(owner(dialog({ modal: true })))).toBe(true);
    expect(hasVisibleShortcutDialog(owner(dialog({ hidden: true }), dialog({ modal: true })))).toBe(true);
  });
  it("does not block a visible nonmodal dialog outside Monaco", () => {
    expect(hasVisibleShortcutDialog(owner(dialog()))).toBe(false);
    expect(hasVisibleShortcutDialog(owner(dialog(), dialog({ modal: true })))).toBe(true);
  });
  it("ignores hidden ancestors and dialogs without rendered bounds", () => {
    expect(hasVisibleShortcutDialog(owner(dialog({ modal: true, hidden: true }), dialog({ modal: true, rects: 0 })))).toBe(false);
  });
  it("ignores CSS-hidden dialogs", () => {
    expect(hasVisibleShortcutDialog(owner(dialog({ modal: true, visibility: "hidden" }), dialog({ modal: true, visibility: "collapse" }), dialog({ modal: true, display: "none" })))).toBe(false);
  });
  it("lets app shortcuts through Monaco's nonmodal find widgets while preserving real editor modal dialogs", () => {
    expect(hasVisibleShortcutDialog(owner(dialog({ monaco: true }), dialog({ monaco: true, hidden: true })))).toBe(false);
    expect(hasVisibleShortcutDialog(owner(dialog({ monaco: true, modal: true })))).toBe(true);
  });
});
