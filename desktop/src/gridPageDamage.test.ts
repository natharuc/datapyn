import { describe, expect, it } from "vitest";
import { pageDamage } from "./gridPageDamage";
describe("page painting", () => {
  it("damages only loaded cells inside the current viewport, with no duplicate paints", () => {
    const viewport = { x: 35, y: 210, width: 3, height: 2 };
    const region = { x: 32, y: 200, width: 32, height: 200 };
    expect(pageDamage([region, region], viewport)).toEqual([
      { cell: [35, 210] }, { cell: [36, 210] }, { cell: [37, 210] },
      { cell: [35, 211] }, { cell: [36, 211] }, { cell: [37, 211] },
    ]);
  });
  it("does not repaint an old viewport after a scrollbar jump", () => {
    expect(pageDamage([{ x: 0, y: 0, width: 32, height: 200 }], { x: 64, y: 9_999_990, width: 10, height: 10 })).toEqual([]);
  });
  it("caps unexpected enormous visible regions", () => {
    expect(pageDamage([{ x: 0, y: 0, width: 5000, height: 10_000_000 }], { x: 0, y: 0, width: 5000, height: 10_000_000 }, 100).length).toBe(100);
  });
});
