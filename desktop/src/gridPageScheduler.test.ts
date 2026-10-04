import { afterEach, describe, expect, it, vi } from "vitest";
import { GridPageScheduler, viewportTiles } from "./gridPageScheduler";
import type { GridTile } from "./gridPageCache";
const tile = (rowOffset: number, columnOffset = 0): GridTile => ({ rowOffset, columnOffset, rowLimit: 200, columnLimit: 32 });
function fixture(concurrency = 2) {
  const requests: { tile: GridTile; resolve: (value: number) => void; reject: (error: Error) => void }[] = [];
  const receive = vi.fn(), failed = vi.fn(), busy = vi.fn();
  const scheduler = new GridPageScheduler<number>({
    load: item => new Promise((resolve, reject) => requests.push({ tile: item, resolve, reject })),
    cached: () => undefined, receive, failed, busy, concurrency, debounceMs: 35,
  });
  return { scheduler, requests, receive, failed, busy };
}
const settle = async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); };
afterEach(() => vi.useRealTimers());
describe("page scheduler", () => {
  it("coalesces 1000 scrollbar jumps into the latest visible tiles", () => {
    vi.useFakeTimers(); const { scheduler, requests } = fixture();
    for (let index = 0; index < 1000; index++) scheduler.setViewport([tile(index * 200)]);
    expect(requests).toHaveLength(0); expect(scheduler.stats.queued).toBe(0);
    vi.advanceTimersByTime(35); expect(requests.map(item => item.tile.rowOffset)).toEqual([199_800]);
  });
  it("does not postpone a pending fetch on each pixel of scrolling inside one tile", () => {
    vi.useFakeTimers(); const { scheduler, requests } = fixture();
    scheduler.setViewport([tile(0)]); vi.advanceTimersByTime(20);
    scheduler.setViewport([tile(0)]); vi.advanceTimersByTime(15); expect(requests).toHaveLength(1);
  });
  it("bounds in-flight work while dropping obsolete queued pages", async () => {
    vi.useFakeTimers(); const { scheduler, requests, receive } = fixture();
    scheduler.setViewport([tile(0), tile(200), tile(400)], true);
    expect(requests).toHaveLength(2); expect(scheduler.stats.queued).toBe(1);
    for (let i = 0; i < 100; i++) scheduler.setViewport([tile(1_000_000 + i * 200)]);
    vi.advanceTimersByTime(35); expect(requests).toHaveLength(2); expect(scheduler.stats.queued).toBe(1);
    requests[0].resolve(1); await settle();
    expect(receive).not.toHaveBeenCalled(); expect(requests).toHaveLength(3);
    expect(requests[2].tile.rowOffset).toBe(1_019_800);
    requests[2].resolve(2); await settle(); expect(receive).toHaveBeenCalledWith(2, tile(1_019_800));
    scheduler.dispose();
  });
  it("deduplicates explicit reads with a viewport request and supports independent abort", async () => {
    const { scheduler, requests } = fixture(); scheduler.setViewport([tile(0)], true);
    const controller = new AbortController(), cancelled = scheduler.read(tile(0), controller.signal), retained = scheduler.read(tile(0));
    const rejected = expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
    controller.abort(); await rejected;
    expect(requests).toHaveLength(1); requests[0].resolve(8); await expect(retained).resolves.toBe(8); scheduler.dispose();
  });
  it("rejects old view reads and discards their responses, without exceeding the concurrency cap after reset", async () => {
    const { scheduler, requests, receive } = fixture(1);
    const old = scheduler.read(tile(0)), rejected = expect(old).rejects.toMatchObject({ name: "AbortError" });
    scheduler.reset(); await rejected; scheduler.setViewport([tile(200)], true);
    expect(requests).toHaveLength(1); requests[0].resolve(4); await settle();
    expect(receive).not.toHaveBeenCalled(); expect(requests).toHaveLength(2);
    requests[1].resolve(5); await settle(); expect(receive).toHaveBeenCalledWith(5, tile(200)); scheduler.dispose();
  });
  it("does not let an old request of the same tile prevent unrelated latest viewport work", async () => {
    const { scheduler, requests } = fixture();
    scheduler.setViewport([tile(0)], true); scheduler.reset(); scheduler.setViewport([tile(0), tile(200)], true);
    expect(requests.map(item => item.tile.rowOffset)).toEqual([0, 200]);
    requests[0].resolve(1); await settle(); expect(requests.map(item => item.tile.rowOffset)).toEqual([0, 200, 0]); scheduler.dispose();
  });
  it("suppresses errors from obsolete viewports and permits explicit retry of current failures", async () => {
    vi.useFakeTimers(); const { scheduler, requests, failed } = fixture();
    scheduler.setViewport([tile(0)], true); scheduler.setViewport([tile(200)]); requests[0].reject(new Error("old")); await settle();
    expect(failed).not.toHaveBeenCalled(); vi.advanceTimersByTime(35);
    requests[1].reject(new Error("current")); await settle(); expect(failed).toHaveBeenCalledOnce();
    scheduler.setViewport([tile(200)], true); expect(requests).toHaveLength(3); scheduler.dispose();
  });
  it("bounds tile expansion for 10M rows and 5000 columns and returns a narrow far-right tile", () => {
    expect(viewportTiles({ x: 4990, y: 9_999_980, width: 10, height: 20 }, 10_000_000, 5000)).toEqual([
      { rowOffset: 9_999_800, columnOffset: 4960, rowLimit: 200, columnLimit: 32 },
      { rowOffset: 9_999_800, columnOffset: 4992, rowLimit: 200, columnLimit: 8 },
    ]);
    expect(viewportTiles({ x: 0, y: 0, width: 5000, height: 10_000_000 }, 10_000_000, 5000)).toHaveLength(32);
  });
});
