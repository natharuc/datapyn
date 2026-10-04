import { describe, expect, it } from "vitest";
import { cellTile, GridPageCache, pageWeight, type GridPage, type GridTile } from "./gridPageCache";

const tile = (columnOffset = 0): GridTile => ({ rowOffset: 0, rowLimit: 200, columnOffset, columnLimit: 32 });
const page = (columnOffset = 0, value: string | number | null = 1): GridPage => ({ offset: 0, column_offset: columnOffset, total_rows: 10_000_000, columns: [], rows: Array.from({ length: 200 }, () => Array(32).fill(value)) });
describe("viewport page cache", () => {
  it("looks up projected columns without treating missing data as NULL", () => {
    const cache = new GridPageCache(); cache.set(tile(32), page(32, null));
    expect(cache.value(34, 5, 5000)).toEqual({ value: null });
    expect(cache.value(2, 5, 5000)).toBeUndefined();
    expect(cellTile(4999, 9_999_999, 5000)).toEqual({ rowOffset: 9_999_800, rowLimit: 200, columnOffset: 4992, columnLimit: 8 });
  });
  it("evicts by cell count and retains pages recently read outside painting", () => {
    const cache = new GridPageCache({ pages: 40, cells: 12_800, bytes: 16 * 1024 * 1024 });
    cache.set(tile(0), page(0)); cache.set(tile(32), page(32)); cache.get(tile(0)); cache.set(tile(64), page(64));
    expect(cache.peek(tile(32))).toBeUndefined(); expect(cache.peek(tile(0))).toBeDefined();
    expect(cache.stats.cells).toBe(12_800);
  });
  it("peek during painting does not change LRU order", () => {
    const cache = new GridPageCache({ pages: 2, cells: 100_000, bytes: 16 * 1024 * 1024 });
    cache.set(tile(0), page(0)); cache.set(tile(32), page(32));
    for (let i = 0; i < 1000; i++) cache.value(1, 1, 5000);
    cache.set(tile(64), page(64)); expect(cache.peek(tile(0))).toBeUndefined();
  });
  it("bounds UTF-16 string retention and rejects an oversized page without poisoning valid cache", () => {
    const numeric = page(0), bytes = pageWeight(numeric).bytes;
    const cache = new GridPageCache({ pages: 40, cells: 250_000, bytes: bytes * 2 });
    cache.set(tile(0), numeric);
    expect(cache.set(tile(32), page(32, "a".repeat(1000)))).toBe(false);
    expect(cache.peek(tile(0))).toBe(numeric); expect(cache.stats.bytes).toBe(bytes);
    cache.clear(); expect(cache.stats).toEqual({ pages: 0, cells: 0, bytes: 0 });
  });
  it("replaces pages without leaking their previous weights", () => {
    const cache = new GridPageCache();
    cache.set(tile(), page(0, "long")); cache.set(tile(), page());
    expect(cache.stats).toEqual({ pages: 1, ...pageWeight(page()) });
  });
});
