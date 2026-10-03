import type { GridSelection, Rectangle } from "@glideapps/glide-data-grid";

function groups(values: number[]): Array<{ start: number; length: number }> {
  const ranges: Array<{ start: number; length: number }> = [];
  for (const index of values) {
    const last = ranges.at(-1);
    if (last && last.start + last.length === index) last.length++;
    else ranges.push({ start: index, length: 1 });
  }
  return ranges;
}
/** Never expand noncontiguous rows into a bounding rectangle containing unselected rows. */
export function selectionRectangles(selection: GridSelection, columns: number, rows: number): Rectangle[] {
  if (selection.current) {
    const ranges = [selection.current.range, ...selection.current.rangeStack];
    return ranges.filter((range, index) => range.width > 0 && range.height > 0 && ranges.findIndex((other) => other.x === range.x && other.y === range.y && other.width === range.width && other.height === range.height) === index);
  }
  if (selection.rows.length) return groups(selection.rows.toArray()).map((range) => ({ x: 0, y: range.start, width: columns, height: range.length }));
  if (selection.columns.length) return groups(selection.columns.toArray()).map((range) => ({ x: range.start, y: 0, width: range.length, height: rows }));
  return [];
}
