import { describe, expect, it } from "vitest";
import { containsHeaderPoint, headerSortBounds } from "./gridHeaderControls";

describe("Independent grid header controls", () => {
  it("keeps sort separate from the menu on scrolled, resized headers", () => {
    const header = { x: -42, y: 0, width: 175, height: 36 };
    const sort = headerSortBounds(header, { x: 103, y: 3, width: 30, height: 30 });
    expect(sort).toEqual({ x: 79, y: 0, width: 24, height: 36 });
    expect(containsHeaderPoint(sort, 90, 18)).toBe(true);
    expect(containsHeaderPoint(sort, 103, 18)).toBe(false);
    expect(containsHeaderPoint(sort, 90, 36)).toBe(false);
  });
  it("reserves space on the opposite side of right-to-left menus", () => {
    expect(headerSortBounds({ x: 100, y: 20, width: 150, height: 34 }, { x: 100, y: 22, width: 30, height: 30 }))
      .toEqual({ x: 130, y: 20, width: 24, height: 34 });
  });
  it("leaves narrow headers available for selection and their menu", () => {
    expect(headerSortBounds({ x: 0, y: 0, width: 50, height: 34 }, { x: 20, y: 2, width: 30, height: 30 })).toBeUndefined();
    expect(containsHeaderPoint(undefined, 20, 10)).toBe(false);
  });
});
