import { describe, expect, it } from "vitest";
import { CompactSelection } from "@glideapps/glide-data-grid";
import { selectionRectangles } from "./gridSelection";

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
});
