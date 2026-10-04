import { GRID_PAGE_COLUMNS, GRID_PAGE_ROWS, gridTileKey, type GridTile } from "./gridPageCache";

export interface GridRegion { x: number; y: number; width: number; height: number }
export function viewportTiles(region: GridRegion, rowCount: number, columnCount: number, maxTiles = 32): GridTile[] {
  const x = Math.max(0, Math.floor(region.x)), y = Math.max(0, Math.floor(region.y));
  const right = Math.min(columnCount, Math.ceil(region.x + region.width)), bottom = Math.min(rowCount, Math.ceil(region.y + region.height));
  if (right <= x || bottom <= y) return [];
  const firstRow = Math.floor(y / GRID_PAGE_ROWS), lastRow = Math.floor((bottom - 1) / GRID_PAGE_ROWS);
  const firstColumn = Math.floor(x / GRID_PAGE_COLUMNS), lastColumn = Math.floor((right - 1) / GRID_PAGE_COLUMNS);
  const result: GridTile[] = [];
  // Top/left visible tiles take priority. Never expand the full result into a queue.
  for (let r = firstRow; r <= lastRow && result.length < maxTiles; r++) {
    for (let c = firstColumn; c <= lastColumn && result.length < maxTiles; c++) {
      result.push({ rowOffset: r * GRID_PAGE_ROWS, columnOffset: c * GRID_PAGE_COLUMNS,
        rowLimit: GRID_PAGE_ROWS, columnLimit: Math.min(GRID_PAGE_COLUMNS, columnCount - c * GRID_PAGE_COLUMNS) });
    }
  }
  return result;
}

export class StaleGridRequest extends Error { constructor() { super("Grid request is no longer needed"); this.name = "AbortError"; } }
interface Waiter<T> { resolve: (value: T) => void; reject: (error: unknown) => void; signal?: AbortSignal; abort?: () => void }
interface Job<T> { tile: GridTile; generation: number; waiters: Set<Waiter<T>> }
export interface GridSchedulerOptions<T> {
  load: (tile: GridTile) => Promise<T>;
  cached: (tile: GridTile) => T | undefined;
  receive: (page: T, tile: GridTile) => void;
  failed: (error: unknown) => void;
  busy?: (busy: boolean) => void;
  concurrency?: number;
  debounceMs?: number;
  maxQueued?: number;
}

/** A single bounded queue for viewport tiles and explicit selection reads. Old viewport work is dropped. */
export class GridPageScheduler<T> {
  private generation = 0;
  private desired = new Map<string, GridTile>();
  private queued = new Map<string, Job<T>>();
  private active = new Map<string, Job<T>>();
  private timer?: ReturnType<typeof setTimeout>;
  private disposed = false;
  private isBusy = false;
  constructor(private readonly options: GridSchedulerOptions<T>) {}
  get stats() { return { queued: this.queued.size, active: this.active.size, desired: this.desired.size }; }
  reset() {
    this.generation++;
    this.desired.clear();
    if (this.timer !== undefined) clearTimeout(this.timer);
    this.timer = undefined;
    for (const job of [...this.queued.values(), ...this.active.values()]) this.rejectWaiters(job, new StaleGridRequest());
    this.queued.clear(); this.updateBusy();
  }
  dispose() { this.disposed = true; this.reset(); }
  setViewport(tiles: readonly GridTile[], immediate = false) {
    if (this.disposed) return;
    const desired = new Map(tiles.slice(0, this.options.maxQueued ?? 32).map(tile => [gridTileKey(tile), tile]));
    // Pixel scrolling inside the same tiles must not keep postponing their fetch indefinitely.
    if (!immediate && desired.size === this.desired.size && [...desired.keys()].every(key => this.desired.has(key))) return;
    this.desired = desired;
    for (const [key, job] of this.queued) if (!this.desired.has(key) && !job.waiters.size) this.queued.delete(key);
    if (this.timer !== undefined) clearTimeout(this.timer);
    if (immediate) { this.timer = undefined; this.enqueueViewport(); }
    else this.timer = setTimeout(() => { this.timer = undefined; this.enqueueViewport(); }, this.options.debounceMs ?? 35);
    this.updateBusy();
  }
  read(tile: GridTile, signal?: AbortSignal): Promise<T> {
    if (this.disposed || signal?.aborted) return Promise.reject(new StaleGridRequest());
    const cached = this.options.cached(tile);
    if (cached !== undefined) return Promise.resolve(cached);
    const key = gridTileKey(tile), active = this.active.get(key);
    let job = active?.generation === this.generation ? active : this.queued.get(key);
    if (!job) {
      if (this.queued.size >= (this.options.maxQueued ?? 32)) return Promise.reject(new Error("Too many pending grid reads"));
      job = { tile, generation: this.generation, waiters: new Set() }; this.queued.set(key, job);
    }
    const target = job;
    const promise = new Promise<T>((resolve, reject) => {
      const waiter: Waiter<T> = { resolve, reject, signal };
      waiter.abort = () => {
        target.waiters.delete(waiter); reject(new StaleGridRequest());
        if (!target.waiters.size && !this.desired.has(key) && this.queued.get(key) === target) this.queued.delete(key);
        this.updateBusy();
      };
      target.waiters.add(waiter); signal?.addEventListener("abort", waiter.abort, { once: true });
    });
    this.pump(); this.updateBusy(); return promise;
  }
  private enqueueViewport() {
    for (const [key, tile] of this.desired) {
      if (this.options.cached(tile) !== undefined || this.queued.has(key) || this.active.get(key)?.generation === this.generation) continue;
      if (this.queued.size >= (this.options.maxQueued ?? 32)) break;
      this.queued.set(key, { tile, generation: this.generation, waiters: new Set() });
    }
    this.pump(); this.updateBusy();
  }
  private pump() {
    if (this.disposed) return;
    while (this.active.size < (this.options.concurrency ?? 2)) {
      const available = [...this.queued].filter(([key]) => !this.active.has(key));
      const entry = available.find(([key]) => this.desired.has(key)) ?? available[0];
      if (!entry) break;
      const [key, job] = entry;
      // An old in-flight request occupies its slot until it settles; no IPC flood on view resets.
      this.queued.delete(key); this.active.set(key, job);
      let request: Promise<T>;
      try { request = this.options.load(job.tile); } catch (error) { request = Promise.reject(error); }
      request.then(page => {
        if (this.disposed || job.generation !== this.generation) return;
        if (this.desired.has(key)) this.options.receive(page, job.tile);
        for (const waiter of job.waiters) { waiter.signal?.removeEventListener("abort", waiter.abort!); waiter.resolve(page); }
        job.waiters.clear();
      }).catch(error => {
        if (!this.disposed && job.generation === this.generation) {
          if (this.desired.has(key)) this.options.failed(error);
          this.rejectWaiters(job, error);
        }
      }).finally(() => {
        if (this.active.get(key) === job) this.active.delete(key);
        this.pump(); this.updateBusy();
      });
    }
  }
  private rejectWaiters(job: Job<T>, error: unknown) {
    for (const waiter of job.waiters) { waiter.signal?.removeEventListener("abort", waiter.abort!); waiter.reject(error); }
    job.waiters.clear();
  }
  private updateBusy() {
    const next = this.queued.size > 0 || [...this.active.values()].some(job => job.generation === this.generation);
    if (next !== this.isBusy) { this.isBusy = next; this.options.busy?.(next); }
  }
}
