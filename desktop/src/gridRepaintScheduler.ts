export interface RepaintRegion { x: number; y: number; width: number; height: number }
export type RepaintWindow = Pick<Window, "requestAnimationFrame" | "cancelAnimationFrame" | "closed">;

/** One damage batch belongs to the window that scheduled its animation frame. */
export class GridRepaintScheduler {
  private frame?: { window: RepaintWindow; id: number; revision: number };
  private regions: RepaintRegion[] = [];
  private revision = 0;

  constructor(private readonly ownerWindow: () => RepaintWindow | null | undefined,
    private readonly paint: (regions: RepaintRegion[]) => void) {}

  enqueue(region: RepaintRegion): void {
    const window = this.ownerWindow();
    if (!window || window.closed) return;
    if (this.frame && this.frame.window !== window) this.reset();
    this.regions.push(region);
    if (this.frame) return;
    const frame = { window, id: 0, revision: this.revision };
    this.frame = frame;
    frame.id = window.requestAnimationFrame(() => {
      // Cancellation can race a callback already dispatched by the old realm.
      // It must neither paint nor clear a newer window's queued frame.
      if (this.frame !== frame || this.revision !== frame.revision) return;
      this.frame = undefined;
      const regions = this.regions;
      this.regions = [];
      // Panel adoption precedes React's ownerDocument revision notification.
      if (window.closed || this.ownerWindow() !== window) return;
      this.paint(regions);
    });
  }

  /** Invalidate callbacks and damage on document move or view disposal. */
  reset(): void {
    const frame = this.frame;
    this.frame = undefined;
    this.regions = [];
    this.revision++;
    // A destroyed native WebView has no animation queue left to cancel.
    if (frame && !frame.window.closed) frame.window.cancelAnimationFrame(frame.id);
  }
}
