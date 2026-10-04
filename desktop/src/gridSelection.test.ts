import { describe, expect, it, vi } from "vitest";
import { CompactSelection } from "@glideapps/glide-data-grid";
import { compactRanges, selectionRectangles,selectedCellCount } from "./gridSelection";

describe("Seleção da grade", () => {
  it("copia somente as linhas escolhidas quando seleção não é contígua", () => {
    const rows = CompactSelection.empty().add(1).add(2).add(8);
    expect(selectionRectangles({ rows, columns: CompactSelection.empty() }, 3, 20)).toEqual([
      { x: 0, y: 1, width: 3, height: 2 }, { x: 0, y: 8, width: 3, height: 1 },
    ]);
  });
  it("mantém vários ranges e elimina range atual duplicado", () => {
    const range = { x: 0, y: 0, width: 2, height: 2 }, second = { x: 4, y: 5, width: 1, height: 3 };
    expect(selectionRectangles({ rows: CompactSelection.empty(), columns: CompactSelection.empty(), current: { cell: [0, 0], range, rangeStack: [range, second] } }, 10, 10)).toEqual([range, second]);
  });
  it("does not double-count intersections or retain row indices outside a refreshed result",()=>{
    expect(selectedCellCount([{x:0,y:0,width:3,height:3},{x:1,y:1,width:3,height:3}])).toBe(14);
    const rows=CompactSelection.empty().add(1).add(99);
    expect(selectionRectangles({rows,columns:CompactSelection.empty()},2,3)).toEqual([{x:0,y:1,width:2,height:1}]);
  });
  it.each([1_000_000,10_000_000])("keeps %i selected rows compact without iterating or expanding indices",count=>{
    const rows=CompactSelection.empty().add([0,count]);
    const array=vi.spyOn(CompactSelection.prototype,"toArray").mockImplementation(()=>{throw new Error("No index expansion");});
    const iterator=vi.spyOn(CompactSelection.prototype,Symbol.iterator).mockImplementation(function*(){throw new Error("No index iteration");});
    const hasAll=vi.spyOn(CompactSelection.prototype,"hasAll").mockImplementation(()=>{throw new Error("hasAll iterates indices");});
    try{expect(selectionRectangles({rows,columns:CompactSelection.empty()},24,count)).toEqual([{x:0,y:0,width:24,height:count}]);expect(array).not.toHaveBeenCalled();expect(iterator).not.toHaveBeenCalled();expect(hasAll).not.toHaveBeenCalled();}
    finally{array.mockRestore();iterator.mockRestore();hasAll.mockRestore();}
  });
  it("clips large disjoint compact ranges and keeps the gaps unselected",()=>{
    const rows=CompactSelection.empty().add([-50,1_000_000]).add([5_000_000,10_000_100]);
    expect(compactRanges(rows,10_000_000)).toEqual([[0,1_000_000],[5_000_000,10_000_000]]);
    expect(selectionRectangles({rows:CompactSelection.empty(),columns:rows},10_000_000,12)).toEqual([{x:0,y:0,width:1_000_000,height:12},{x:5_000_000,y:0,width:5_000_000,height:12}]);
  });
  it("matches compact range membership for sparse, overlapping and adjacent selections",()=>{
    for(let seed=1;seed<=25;seed++){
      let rows=CompactSelection.empty();for(let index=0;index<30;index++){const start=(seed*11+index*17)%97-5;rows=rows.add([start,start+index%7+1]);}
      const expected=rows.toArray().filter(index=>index>=0&&index<80), actual=compactRanges(rows,80).flatMap(([start,end])=>Array.from({length:end-start},(_,index)=>start+index));
      expect(actual).toEqual(expected);
    }
  });
});
