import { describe, expect, it } from "vitest";
import { contextMenuIndex, contextMenuPosition } from "./contextMenuModel";

describe("connection context menu", () => {
  it("opens at the cursor in the source window", () => {
    expect(contextMenuPosition({ x: 100, y: 120 }, { width: 220, height: 240 }, { width: 1280, height: 720 }))
      .toEqual({ left: 100, top: 120 });
  });
  it("keeps all commands inside a small detached window at its lower edge", () => {
    expect(contextMenuPosition({ x: 470, y: 320 }, { width: 220, height: 240 }, { width: 480, height: 360 }))
      .toEqual({ left: 252, top: 112 });
  });
  it("keeps the minimum edge when the window is smaller than the menu", () => {
    expect(contextMenuPosition({ x: -20, y: -5 }, { width: 220, height: 240 }, { width: 140, height: 120 }))
      .toEqual({ left: 8, top: 8 });
  });
  it("wraps around disabled connect commands without changing their actions", () => {
    const disabled = [true, true, false, false, true, false];
    expect(contextMenuIndex(disabled, -1, "ArrowDown")).toBe(2);
    expect(contextMenuIndex(disabled, 5, "ArrowDown")).toBe(2);
    expect(contextMenuIndex(disabled, 2, "ArrowUp")).toBe(5);
    expect(contextMenuIndex(disabled, 3, "ArrowDown")).toBe(5);
    expect(contextMenuIndex(disabled, 3, "Home")).toBe(2);
    expect(contextMenuIndex(disabled, 3, "End")).toBe(5);
  });
  it("handles a catalog with no enabled commands", () => {
    expect(contextMenuIndex([], -1, "Home")).toBe(-1);
    expect(contextMenuIndex([true, true], 1, "ArrowDown")).toBe(-1);
  });
});
