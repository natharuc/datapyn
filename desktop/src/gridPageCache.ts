import type { Primitive, ResultPage } from "./runtime";

export const GRID_PAGE_ROWS = 200;
export const GRID_PAGE_COLUMNS = 32;
export interface GridTile { rowOffset: number; columnOffset: number; rowLimit: number; columnLimit: number }
export type GridPage = ResultPage & { column_offset?: number; total_columns?: number };
export function gridTileKey(tile: GridTile) { return `${tile.rowOffset}:${tile.columnOffset}:${tile.rowLimit}:${tile.columnLimit}`; }
export function cellTile(column: number, row: number, columnCount: number): GridTile {
  const columnOffset = Math.floor(column / GRID_PAGE_COLUMNS) * GRID_PAGE_COLUMNS;
  return { rowOffset: Math.floor(row / GRID_PAGE_ROWS) * GRID_PAGE_ROWS, columnOffset,
    rowLimit: GRID_PAGE_ROWS, columnLimit: Math.min(GRID_PAGE_COLUMNS, Math.max(0, columnCount - columnOffset)) };
}

/** Approximate retained JS memory, including array slots/headers and UTF-16 strings. */
export function pageWeight(page: GridPage) {
  let cells = 0, bytes = 128 + page.rows.length * 32;
  for (const row of page.rows) {
    cells += row.length;
    for (const value of row) bytes += 16 + (typeof value === "string" ? value.length * 2 + 24 : 0);
  }
  for (const column of page.columns) bytes += 64 + 2 * (column.name.length + column.dtype.length);
  return { cells, bytes };
}

/** Painting only peeks. Touching LRU order happens once per viewport/request, never per cell. */
export class GridPageCache {
  private entries = new Map<string, { page: GridPage; cells: number; bytes: number }>();
  private cells = 0;
  private bytes = 0;
  constructor(readonly limits = { pages: 40, cells: 250_000, bytes: 16 * 1024 * 1024 }) {}
  get stats() { return { pages: this.entries.size, cells: this.cells, bytes: this.bytes }; }
  clear() { this.entries.clear(); this.cells = 0; this.bytes = 0; }
  peek(tile: GridTile) { return this.entries.get(gridTileKey(tile))?.page; }
  get(tile: GridTile) {
    const key = gridTileKey(tile), entry = this.entries.get(key);
    if (entry) { this.entries.delete(key); this.entries.set(key, entry); }
    return entry?.page;
  }
  set(tile: GridTile, page: GridPage): boolean {
    const weight = pageWeight(page);
    if (weight.cells > this.limits.cells || weight.bytes > this.limits.bytes || this.limits.pages < 1) return false;
    const key = gridTileKey(tile), old = this.entries.get(key);
    if (old) { this.cells -= old.cells; this.bytes -= old.bytes; this.entries.delete(key); }
    while (this.entries.size && (this.entries.size >= this.limits.pages || this.cells + weight.cells > this.limits.cells || this.bytes + weight.bytes > this.limits.bytes)) {
      const oldestKey = this.entries.keys().next().value!, oldest = this.entries.get(oldestKey)!;
      this.entries.delete(oldestKey); this.cells -= oldest.cells; this.bytes -= oldest.bytes;
    }
    this.entries.set(key, { page, ...weight }); this.cells += weight.cells; this.bytes += weight.bytes;
    return true;
  }
  value(column: number, row: number, columnCount: number): { value: Primitive } | undefined {
    const page = this.peek(cellTile(column, row, columnCount));
    if (!page || row < page.offset || row >= page.offset + page.rows.length) return;
    const values = page.rows[row - page.offset], index = column - (page.column_offset ?? 0);
    return index >= 0 && index < values.length ? { value: values[index] } : undefined;
  }
}
