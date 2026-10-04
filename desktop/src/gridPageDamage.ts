import type { GridRegion } from "./gridPageScheduler";

export function intersectRegions(first: GridRegion, second: GridRegion): GridRegion | undefined {
  const x = Math.max(first.x, second.x), y = Math.max(first.y, second.y);
  const right = Math.min(first.x + first.width, second.x + second.width), bottom = Math.min(first.y + first.height, second.y + second.height);
  return right > x && bottom > y ? { x, y, width: right - x, height: bottom - y } : undefined;
}
/** Damage is clipped again at paint time: a page arriving during a jump never repaints the old viewport. */
export function pageDamage(regions: readonly GridRegion[], viewport: GridRegion, maxCells = 20_000): { cell: readonly [number, number] }[] {
  const cells = new Map<string, { cell: readonly [number, number] }>();
  for (const region of regions) {
    const intersection = intersectRegions(region, viewport);
    if (!intersection) continue;
    for (let row = intersection.y; row < intersection.y + intersection.height && cells.size < maxCells; row++) {
      for (let column = intersection.x; column < intersection.x + intersection.width && cells.size < maxCells; column++) {
        const key = `${column}:${row}`;
        if (!cells.has(key)) cells.set(key, { cell: [column, row] });
      }
    }
  }
  return [...cells.values()];
}
