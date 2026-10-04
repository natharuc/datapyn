import { describe, expect, it, vi } from "vitest";
import { runInNewContext } from "node:vm";
import { GridRepaintScheduler, type RepaintWindow } from "./gridRepaintScheduler";

interface TestWindow extends RepaintWindow {
  closed: boolean;
  frames: Map<number, FrameRequestCallback>;
  cancelled: number[];
  flush(id?: number): void;
}

// Realms intentionally reuse frame IDs, just as independent browser windows do.
function realm(): TestWindow {
  return runInNewContext(`new class {
    frames = new Map(); cancelled = []; sequence = 0; closed = false;
    requestAnimationFrame(callback) { const id = ++this.sequence; this.frames.set(id, callback); return id; }
    cancelAnimationFrame(id) { this.cancelled.push(id); this.frames.delete(id); }
    flush(id = this.sequence) { const callback = this.frames.get(id); this.frames.delete(id); callback?.(0); }
  }`);
}
const visible = { x: 0, y: 20, width: 3, height: 30 };
const damage = { x: 1, y: 22, width: 1, height: 4 };

describe("grid repaint across document adoption", () => {
  it("cancels the former realm's frame and paints the current viewport in the new realm", () => {
    const main = realm(), popout = realm(), paint = vi.fn();
    let owner = popout;
    const scheduler = new GridRepaintScheduler(() => owner, paint);
    scheduler.enqueue(damage);
    const staleCallback = popout.frames.get(1)!;
    owner = main;
    scheduler.reset();
    scheduler.enqueue(visible);
    expect(popout.cancelled).toEqual([1]);
    expect(main.cancelled).toEqual([]);
    // Even a callback dispatched before cancellation cannot consume the new batch.
    staleCallback(0);
    expect(paint).not.toHaveBeenCalled();
    main.flush(1);
    expect(paint).toHaveBeenCalledExactlyOnceWith([visible]);
    scheduler.enqueue(damage);
    main.flush(2);
    expect(paint).toHaveBeenLastCalledWith([damage]);
  });

  it("does not paint adopted DOM before the React document revision arrives", () => {
    const main = realm(), popout = realm(), paint = vi.fn();
    let owner = popout;
    const scheduler = new GridRepaintScheduler(() => owner, paint);
    scheduler.enqueue(damage);
    owner = main;
    popout.flush();
    expect(paint).not.toHaveBeenCalled();
    scheduler.reset();
    scheduler.enqueue(visible);
    main.flush();
    expect(paint).toHaveBeenCalledExactlyOnceWith([visible]);
  });

  it("allows page arrivals in a new document before revision and discards the old damage", () => {
    const main = realm(), popout = realm(), paint = vi.fn();
    let owner = popout;
    const scheduler = new GridRepaintScheduler(() => owner, paint);
    scheduler.enqueue(damage);
    owner = main;
    scheduler.enqueue(visible);
    expect(popout.cancelled).toEqual([1]);
    main.flush();
    expect(paint).toHaveBeenCalledExactlyOnceWith([visible]);
  });

  it("invalidates a destroyed popout without calling its dead animation APIs", () => {
    const main = realm(), popout = realm(), paint = vi.fn();
    let owner = popout;
    const scheduler = new GridRepaintScheduler(() => owner, paint);
    scheduler.enqueue(damage);
    const staleCallback = popout.frames.get(1)!;
    popout.closed = true;
    popout.cancelAnimationFrame = () => { throw new Error("dead window API called"); };
    scheduler.reset();
    scheduler.enqueue(visible);
    staleCallback(0);
    expect(paint).not.toHaveBeenCalled();
    owner = main;
    scheduler.enqueue(visible);
    main.flush();
    expect(paint).toHaveBeenCalledExactlyOnceWith([visible]);
  });

  it("coalesces page damage and cancels it on unmount without scheduling into a missing document", () => {
    const window = realm(), paint = vi.fn();
    let owner: TestWindow | undefined = window;
    const scheduler = new GridRepaintScheduler(() => owner, paint);
    scheduler.enqueue(visible); scheduler.enqueue(damage);
    expect(window.frames.size).toBe(1);
    window.flush();
    expect(paint).toHaveBeenCalledExactlyOnceWith([visible, damage]);
    scheduler.enqueue(damage);
    const staleCallback = window.frames.get(2)!;
    scheduler.reset(); owner = undefined;
    staleCallback(0); scheduler.enqueue(visible);
    expect(paint).toHaveBeenCalledTimes(1);
    expect(window.frames.size).toBe(0);
    expect(window.cancelled).toEqual([2]);
  });
});
