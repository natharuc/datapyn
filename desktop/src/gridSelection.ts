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
    const ranges = [selection.current.range, ...selection.current.rangeStack].map(r=>({x:Math.max(0,r.x),y:Math.max(0,r.y),width:Math.max(0,Math.min(columns,r.x+r.width)-Math.max(0,r.x)),height:Math.max(0,Math.min(rows,r.y+r.height)-Math.max(0,r.y))}));
    return ranges.filter((range, index) => range.width > 0 && range.height > 0 && ranges.findIndex((other) => other.x === range.x && other.y === range.y && other.width === range.width && other.height === range.height) === index);
  }
  if (selection.rows.length) return groups(selection.rows.toArray().filter(index=>index>=0&&index<rows)).map((range) => ({ x: 0, y: range.start, width: columns, height: range.length }));
  if (selection.columns.length) return groups(selection.columns.toArray().filter(index=>index>=0&&index<columns)).map((range) => ({ x: range.start, y: 0, width: range.length, height: rows }));
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
