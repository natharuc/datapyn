import { describe, expect, it } from "vitest";
import type { DataView } from "./dataTypes";
import { reconcileGridView } from "./gridViewColumns";

const columns = [
  { name: "id", dtype: "Int64" },
  { name: "amount", dtype: "object" },
  { name: "when", dtype: "datetime64[ns, UTC]" },
];

describe("restored grid views after a result schema changes", () => {
  it("returns the same view, filters, rules and selection when all names remain valid", () => {
    const view: DataView = { filter: { text: "Alpha", filters: [{ column: "amount", operator: "between", value: "9007199254740993.000000000000000001", value_to: "9007199254740993.000000000000000002" }] }, sort: { column: "id", direction: "desc" }, scope: { rectangles: [{ x: 0, y: 1, width: 2, height: 3 }] } };
    const result = reconcileGridView(view, columns);
    expect(result).toBe(view);
    expect(result?.filter?.filters).toBe(view.filter?.filters);
    expect(result?.scope).toBe(view.scope);
  });

  it("prunes only vanished rules and the vanished sort before a page/export request", () => {
    const validRule = { column: "amount", operator: "gte", value: "9223372036854775807" };
    const view: DataView = { filter: { text: "Alpha", filters: [{ column: "old_city", operator: "equals", value: "Lisboa" }, validRule] }, sort: { column: "old_city", direction: "asc" }, scope: { column_indices: [0], row_ranges: [[0, 2]] } };
    const result = reconcileGridView(view, columns);
    expect(result).toEqual({ filter: { text: "Alpha", filters: [validRule] }, scope: view.scope });
    expect(result?.filter?.filters?.[0]).toBe(validRule);
    expect(result?.scope).toBe(view.scope);
    expect(view.filter?.filters).toHaveLength(2);
    expect(view.sort?.column).toBe("old_city");
    expect(reconcileGridView(result, columns)).toBe(result);
  });

  it("rejects both copies of an ambiguous wire label while keeping unique columns", () => {
    const view: DataView = { filter: { filters: [{ column: "id", operator: "equals", value: 2 }, { column: "amount", operator: "gte", value: "10" }] }, sort: { column: "id", direction: "asc" } };
    expect(reconcileGridView(view, [...columns, { name: "id", dtype: "object" }])).toEqual({ filter: { filters: [{ column: "amount", operator: "gte", value: "10" }] } });
  });

  it("reconciles the old single-column DTO independently of newer multi-column rules", () => {
    const rule = { column: "when", operator: "between", value: "2026-10-01", value_to: "2026-10-02" };
    const view: DataView = { filter: { text: "same global search", column: "removed", operator: "between", value: "1", value_to: "2", filters: [rule] }, sort: { column: "amount", direction: "asc" } };
    expect(reconcileGridView(view, columns)).toEqual({ filter: { text: "same global search", filters: [rule] }, sort: view.sort });
  });

  it("keeps false, zero, null and precise upper limits in existing single-column filters", () => {
    for (const value of [false, 0, null, "9007199254740993.000000000000000001"]) {
      const view: DataView = { filter: { column: "amount", operator: "equals", value, value_to: "9223372036854775807" } };
      expect(reconcileGridView(view, columns)).toBe(view);
    }
  });

  it("drops an empty invalid filter view without manufacturing filters for a new schema", () => {
    const view: DataView = { filter: { filters: [{ column: "removed", operator: "is_null" }] }, sort: { column: "removed", direction: "desc" } };
    expect(reconcileGridView(view, columns)).toBeUndefined();
    expect(reconcileGridView({ filter: { column: "removed", value: 1 } }, [])).toBeUndefined();
    expect(reconcileGridView(undefined, columns)).toBeUndefined();
  });

  it("retains global search and compact scope even when there are no columns", () => {
    const scope = { rectangles: [{ x: 0, y: 0, width: 100, height: 1_000_000 }] };
    const view: DataView = { filter: { text: "needle", filters: [{ column: "id", value: 1 }] }, scope };
    expect(reconcileGridView(view, [])).toEqual({ filter: { text: "needle" }, scope });
    expect(reconcileGridView(view, [])?.scope).toBe(scope);
  });

  it("retains unknown future view/filter fields when pruning invalid names", () => {
    const view = { filter: { column: "removed", value: "lost", future_rule: "preserved" }, future_view: { enabled: true } } as DataView;
    expect(reconcileGridView(view, columns)).toEqual({ filter: { future_rule: "preserved" }, future_view: { enabled: true } });
  });
});
