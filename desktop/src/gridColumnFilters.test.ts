import { describe, expect, it } from "vitest";
import type { ColumnFilter } from "./dataTypes";
import {
  columnFilterDraft, compareDateFilters, compareNumericFilters, draftToColumnFilters,
  filterSummary, headerPopupPosition, inferColumnFilterKind, normalizeNumericFilter, replaceColumnFilters,
  validDateFilter, type ColumnFilterDraft,
} from "./gridColumnFilters";

const edited = (kind: ColumnFilterDraft["kind"], patch: Partial<ColumnFilterDraft> = {}): ColumnFilterDraft => ({
  kind, presence: "value", operator: kind === "number" || kind === "date" ? "between" : "contains",
  value: "", valueTo: "", booleanValue: "any", ...patch,
});

describe("Column header filters", () => {
  it("infers nullable, Arrow, Polars and database types without guessing object values in JS", () => {
    for (const dtype of ["Int64", "uint8", "Float64", "decimal128(38, 9)[pyarrow]", "Decimal(precision=38, scale=8)", "numeric"]) expect(inferColumnFilterKind(dtype)).toBe("number");
    expect(inferColumnFilterKind("boolean")).toBe("bool");
    expect(inferColumnFilterKind("datetime64[ns, UTC]")).toBe("date");
    expect(inferColumnFilterKind("Date32[day]")).toBe("date");
    expect(inferColumnFilterKind("object")).toBe("text");
    expect(inferColumnFilterKind("object", "number")).toBe("number");
  });

  it("normalizes decimal comma and exponent strings but rejects grouping, malformed values and huge powers", () => {
    expect(normalizeNumericFilter(" -9007199254740993,125e+2 ")).toBe("-9007199254740993.125e+2");
    expect(normalizeNumericFilter(".25")).toBe(".25");
    expect(normalizeNumericFilter("1e1000")).toBe("1e1000");
    for (const value of ["", ".", "NaN", "Infinity", "1.000,50", "1,2,3", "1e1001", "1e-1001", "1_000", "0x10", "1e999999999999999999999"]) expect(normalizeNumericFilter(value)).toBeUndefined();
  });

  it("orders exact large integers, fractions, signs and scientific notation without JS floating point", () => {
    expect(compareNumericFilters("9007199254740993", "9007199254740992")).toBe(1);
    expect(compareNumericFilters("-9007199254740993", "-9007199254740992")).toBe(-1);
    expect(compareNumericFilters("1.0000000000000000000001", "1")).toBe(1);
    expect(compareNumericFilters("1e-1000", "0")).toBe(1);
    expect(compareNumericFilters("-0.000", "+0")).toBe(0);
    expect(compareNumericFilters("001.20e3", "1200.000")).toBe(0);
    expect(compareNumericFilters(".001", "1e-3")).toBe(0);
    expect(compareNumericFilters("1e1000", "9e999")).toBe(1);
  });

  it("sends inclusive numeric bounds as exact strings, permits one-sided bounds and rejects reversed bounds", () => {
    expect(draftToColumnFilters("amount", edited("number", { value: "9007199254740993,1", valueTo: "9007199254740993,2" }))).toEqual({ ok: true, filters: [{ column: "amount", operator: "between", value: "9007199254740993.1", value_to: "9007199254740993.2" }] });
    expect(draftToColumnFilters("amount", edited("number", { valueTo: "1.5" }))).toEqual({ ok: true, filters: [{ column: "amount", operator: "between", value_to: "1.5" }] });
    expect(draftToColumnFilters("amount", edited("number", { value: "2.00000000000000001", valueTo: "2" }))).toMatchObject({ ok: false, field: "valueTo" });
    expect(draftToColumnFilters("amount", edited("number", { value: "." }))).toMatchObject({ ok: false, field: "value" });
  });

  it("preserves stored scalar and multiple conditions until editing, including bigint values", () => {
    const rules: ColumnFilter[] = [{ column: "id", operator: "gt", value: "9007199254740993" }, { column: "id", operator: "lt", value: "99999999999999999" }];
    const draft = columnFilterDraft({ name: "id", dtype: "int64" }, rules);
    expect(draft.operator).toBe("gt");
    expect(draftToColumnFilters("id", draft)).toEqual({ ok: true, filters: rules });
    expect(draftToColumnFilters("id", { ...draft, original: undefined, value: "9007199254740994" })).toEqual({ ok: true, filters: [{ column: "id", operator: "gt", value: "9007199254740994" }] });
  });

  it("validates calendar dates, complete ISO timestamps and nanosecond ordering", () => {
    expect(validDateFilter("2024-02-29")).toBe(true);
    expect(validDateFilter("2026-02-29")).toBe(false);
    expect(validDateFilter("1900-02-29")).toBe(false);
    expect(validDateFilter("2000-02-29")).toBe(true);
    expect(validDateFilter("2026-04-31")).toBe(false);
    expect(validDateFilter("2026-10-01T12:34:56.123456789-03:00")).toBe(true);
    expect(validDateFilter("2026-10-01T25:34:56Z")).toBe(false);
    expect(compareDateFilters("2026-10-01T12:00:00.000000001Z", "2026-10-01T12:00:00.000000000Z")).toBe(1);
    expect(compareDateFilters("2026-10-01T15:00:00.123456789+03:00", "2026-10-01T12:00:00.123456789Z")).toBe(0);
  });

  it("includes the complete end day and leaves mixed-zone ordering to the column-aware backend", () => {
    expect(draftToColumnFilters("date", edited("date", { value: "2026-10-01T23:59:59.999999999", valueTo: "2026-10-01" }))).toMatchObject({ ok: true });
    expect(draftToColumnFilters("date", edited("date", { value: "2026-10-02", valueTo: "2026-10-01" }))).toMatchObject({ ok: false, field: "valueTo" });
    expect(draftToColumnFilters("date", edited("date", { value: "2026-02-30" }))).toMatchObject({ ok: false, field: "value" });
    expect(compareDateFilters("2026-10-01T12:00:00-03:00", "2026-10-01")).toBeUndefined();
  });

  it("edits restored timestamps without rounding or silently converting scalar operators", () => {
    const value = "2026-10-01T12:34:56.123456789-03:00";
    const draft = columnFilterDraft({ name: "stamp", dtype: "datetime64[ns, UTC]" }, [{ column: "stamp", operator: "gte", value }]);
    expect(draftToColumnFilters("stamp", { ...draft, original: undefined })).toEqual({ ok: true, filters: [{ column: "stamp", operator: "gte", value }] });
  });

  it("preserves literal text operators on numeric/date columns and both bounds on textual ranges", () => {
    expect(draftToColumnFilters("amount", edited("number", { operator: "starts_with", value: "-" }))).toEqual({ ok: true, filters: [{ column: "amount", operator: "starts_with", value: "-" }] });
    expect(draftToColumnFilters("stamp", edited("date", { operator: "contains", value: "2026" }))).toEqual({ ok: true, filters: [{ column: "stamp", operator: "contains", value: "2026" }] });
    expect(draftToColumnFilters("name", edited("text", { operator: "between", valueTo: "Zulu" }))).toEqual({ ok: true, filters: [{ column: "name", operator: "between", value_to: "Zulu" }] });
    expect(draftToColumnFilters("name", edited("text", { operator: "equals" }))).toEqual({ ok: true, filters: [{ column: "name", operator: "equals", value: "" }] });
    expect(draftToColumnFilters("name", edited("text", { value: "  " }))).toEqual({ ok: true, filters: [{ column: "name", operator: "contains", value: "  " }] });
  });

  it("supports boolean aliases, Any, false and null/not-null without stringifying booleans", () => {
    for (const value of [true, 1, "1", "sim", "t"]) expect(columnFilterDraft({ name: "active", dtype: "bool" }, [{ column: "active", operator: "equals", value }]).booleanValue).toBe("true");
    for (const value of [false, 0, "0", "nao", "f"]) expect(columnFilterDraft({ name: "active", dtype: "bool" }, [{ column: "active", operator: "equals", value }]).booleanValue).toBe("false");
    expect(draftToColumnFilters("active", edited("bool", { booleanValue: "false" }))).toEqual({ ok: true, filters: [{ column: "active", operator: "equals", value: false }] });
    expect(draftToColumnFilters("active", edited("bool"))).toEqual({ ok: true, filters: [] });
    expect(draftToColumnFilters("active", edited("bool", { presence: "is_null" }))).toEqual({ ok: true, filters: [{ column: "active", operator: "is_null" }] });
  });

  it("replaces only the selected column while preserving order, other rules and original arrays", () => {
    const before: ColumnFilter[] = [{ column: "name", value: "literal" }, { column: "id", operator: "gte", value: "3" }, { column: "other", operator: "is_null" }, { column: "id", operator: "lte", value: "5" }];
    const replacement: ColumnFilter = { column: "id", operator: "between", value: "4", value_to: "8" };
    expect(replaceColumnFilters(before, "id", [replacement])).toEqual([before[0], replacement, before[2]]);
    expect(before).toHaveLength(4);
    expect(replaceColumnFilters(before, "id", [])).toEqual([before[0], before[2]]);
    expect(replaceColumnFilters(before, "id", [{ column: "unrelated", value: "oops" }])).toEqual([before[0], before[2]]);
  });

  it("summarizes both bounds, scalar/null rules and localized booleans without losing raw precision", () => {
    expect(filterSummary([{ column: "n", operator: "between", value: "9007199254740993", value_to: "9007199254740994" }], "pt-BR")).toBe("n: 9007199254740993 … 9007199254740994");
    expect(filterSummary([{ column: "n", operator: "between", value_to: "5" }, { column: "b", operator: "equals", value: false }], "en-US")).toBe("n ≤ 5; b = False");
    expect(filterSummary([{ column: "date", operator: "not_null" }], "pt-BR")).toBe("date: não nulo");
  });

  it("anchors to the header, flips above near the bottom and clamps in the owning viewport", () => {
    expect(headerPopupPosition({ x: 100, y: 20, width: 200, height: 30 }, { width: 300, height: 400 }, { width: 1000, height: 900 })).toEqual({ left: 8, top: 54 });
    expect(headerPopupPosition({ x: 990, y: 850, width: 100, height: 30 }, { width: 300, height: 400 }, { width: 1000, height: 900 })).toEqual({ left: 692, top: 446 });
    expect(headerPopupPosition({ x: -100, y: -10, width: 100, height: 20 }, { width: 300, height: 400 }, { width: 400, height: 300 })).toEqual({ left: 8, top: 8 });
  });
});
