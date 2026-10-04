import type { CompactSelection, GridSelection, Rectangle } from "@glideapps/glide-data-grid";

/** Glide 6 exposes no range iterator. remove/length count ranges without visiting their indices. */
export function compactRanges(selection: CompactSelection, limit: number): Array<[number, number]> {
  if (!Number.isSafeInteger(limit) || limit <= 0 || !selection.length) return [];
  let remaining = selection;
  // Glide's remove can skip a following slice when deleting multiple slices; recheck each bound.
  while (remaining.length && remaining.first()! < 0) remaining = remaining.remove([remaining.first()!, 0]);
  while (remaining.length && remaining.last()! >= limit) remaining = remaining.remove([limit, remaining.last()! + 1]);
  const ranges: Array<[number, number]> = [];
  while (remaining.length) {
    const start = remaining.first()!, end = remaining.last()! + 1, count = remaining.length;
    if (end - start === count) { ranges.push([start, end]); break; }
    // A prefix contains every index iff removing it reduces the compact count by its length.
    let low = start + 1, high = end;
    while (low + 1 < high) {
      const middle = low + Math.floor((high - low) / 2);
      if (remaining.remove([start, middle]).length === count - (middle - start)) low = middle;
      else high = middle;
    }
    ranges.push([start, low]);
    remaining = remaining.remove([start, low]);
  }
  return ranges;
}
/** Never expand noncontiguous rows into a bounding rectangle containing unselected rows. */
export function selectionRectangles(selection: GridSelection, columns: number, rows: number): Rectangle[] {
  if (selection.current) {
    const ranges = [selection.current.range, ...selection.current.rangeStack].map(r=>({x:Math.max(0,r.x),y:Math.max(0,r.y),width:Math.max(0,Math.min(columns,r.x+r.width)-Math.max(0,r.x)),height:Math.max(0,Math.min(rows,r.y+r.height)-Math.max(0,r.y))}));
    return ranges.filter((range, index) => range.width > 0 && range.height > 0 && ranges.findIndex((other) => other.x === range.x && other.y === range.y && other.width === range.width && other.height === range.height) === index);
  }
  if (selection.rows.length) return compactRanges(selection.rows, rows).map(([start, end]) => ({ x: 0, y: start, width: columns, height: end - start }));
  if (selection.columns.length) return compactRanges(selection.columns, columns).map(([start, end]) => ({ x: start, y: 0, width: end - start, height: rows }));
  return [];
}
/** Count the rectangle union without iterating every selected cell. */
export function selectedCellCount(rectangles:Rectangle[]):number {
  const edges=[...new Set(rectangles.flatMap(r=>[r.y,r.y+r.height]))].sort((a,b)=>a-b);let count=0;
  for(let index=0;index<edges.length-1;index++){
    const y=edges[index],ranges=rectangles.filter(r=>r.y<=y&&r.y+r.height>y).map(r=>[r.x,r.x+r.width]).sort((a,b)=>a[0]-b[0]);
    let width=0,end=-1;for(const [first,last] of ranges){width+=Math.max(0,last-Math.max(first,end));end=Math.max(end,last);}
    count+=width*(edges[index+1]-y);
  }
  return count;
}
