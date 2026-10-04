import { describe, expect, it, vi } from "vitest";
import type { Data, Layout, PlotlyDataLayoutConfig } from "plotly.js";
import { PlotlyCanvasController, type ChartFigure, type PlotlyRenderer } from "./plotlyCanvasController";

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void, reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
class Realm {
  closed = false;
  nextFrame = 0;
  frames = new Map<number, FrameRequestCallback>();
  cancelled: number[] = [];
  listeners = new Map<string, Set<() => void>>();
  observers: { disconnected: boolean; fire(): void }[] = [];
  ResizeObserver = class {
    disconnected = false;
    constructor(private callback: () => void) {}
    observe = () => {};
    disconnect = () => { this.disconnected = true; };
    fire = () => this.callback();
  };
  constructor(readonly name: string) {
    const realm = this, Observer = this.ResizeObserver;
    this.ResizeObserver = class extends Observer {
      constructor(callback: () => void) { super(callback); realm.observers.push(this); }
    };
  }
  requestAnimationFrame = (callback: FrameRequestCallback) => { const id = ++this.nextFrame; this.frames.set(id, callback); return id; };
  cancelAnimationFrame = (id: number) => { this.cancelled.push(id); this.frames.delete(id); };
  addEventListener = (name: string, callback: () => void) => {
    const callbacks = this.listeners.get(name) ?? new Set(); callbacks.add(callback); this.listeners.set(name, callbacks);
  };
  removeEventListener = (name: string, callback: () => void) => this.listeners.get(name)?.delete(callback);
  fire(name: string) { for (const callback of this.listeners.get(name) ?? []) callback(); }
  flush() { const frames = [...this.frames.values()]; this.frames.clear(); for (const callback of frames) callback(0); }
}
class TestDocument {
  constructor(readonly defaultView: Realm) {}
  createElement() { return new TestNode(this); }
}
class TestNode {
  style: Record<string, string> = {};
  children: TestNode[] = [];
  parent?: TestNode;
  layout?: Partial<Layout>;
  bounds = { width: 800, height: 400 };
  constructor(public ownerDocument: TestDocument) {}
  appendChild(node: TestNode) { node.parent = this; this.children.push(node); return node; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); this.parent = undefined; }
  getBoundingClientRect() { return this.bounds; }
  adopt(document: TestDocument) { this.ownerDocument = document; this.children.forEach(child => child.adopt(document)); }
}
function setup() {
  const main = new Realm("main"), popout = new Realm("popout"), document = new TestDocument(main), otherDocument = new TestDocument(popout);
  const host = new TestNode(document);
  let active = 0, maximumActive = 0;
  const steps: string[] = [], renderGates: Promise<void>[] = [], imageGates: Promise<void>[] = [], resizeGates: Promise<void>[] = [];
  const renderer: PlotlyRenderer = {
    react: vi.fn(async (element, data, layout) => {
      const node = element as unknown as TestNode;
      active++; maximumActive = Math.max(maximumActive, active); steps.push(`react:${String(data[0]?.name)}:start`);
      try { await (renderGates.shift() ?? Promise.resolve()); node.layout = layout; }
      finally { active--; steps.push(`react:${String(data[0]?.name)}:end`); }
    }),
    purge: vi.fn(() => { expect(active).toBe(0); steps.push("purge"); }),
    toImage: vi.fn(async (_node, options) => {
      active++; maximumActive = Math.max(maximumActive, active); steps.push("image:start");
      try { await (imageGates.shift() ?? Promise.resolve()); return `data:image/${options.format};base64,chart`; }
      finally { active--; steps.push("image:end"); }
    }),
    relayout: vi.fn(async (element, update) => {
      const node = element as unknown as TestNode;
      if (typeof update.width === "number" && typeof update.height === "number") {
        active++; maximumActive = Math.max(maximumActive, active); steps.push("resize:start");
        try {
          await (resizeGates.shift() ?? Promise.resolve());
          const layout = { ...node.layout } as Record<string, unknown>;
          for (const [key, value] of Object.entries(update)) {
            const [section, field] = key.split(".");
            if (field) {
              const fields = { ...(layout[section] as object ?? {}) } as Record<string, unknown>;
              if (value === null) delete fields[field]; else fields[field] = value;
              layout[section] = fields;
            } else layout[key] = value;
          }
          node.layout = layout as Partial<Layout>;
        }
        finally { active--; steps.push("resize:end"); }
      } else { expect(active).toBe(0); steps.push("reset"); }
    }),
    Plots: { resize: vi.fn(async () => {
      active++; maximumActive = Math.max(maximumActive, active); steps.push("resize:start");
      try { await (resizeGates.shift() ?? Promise.resolve()); }
      finally { active--; steps.push("resize:end"); }
    }) },
  };
  const onBusyChange = vi.fn(), onError = vi.fn(), loader = vi.fn(async () => renderer);
  const controller = new PlotlyCanvasController(host as unknown as HTMLElement, loader, { onBusyChange, onError });
  return { main, popout, document, otherDocument, host, renderer, loader, controller, renderGates, imageGates, resizeGates, steps, onBusyChange, onError, maximumActive: () => maximumActive };
}
const figure = (name: string, uirevision = "session:result:x:y") : ChartFigure => ({
  data: [{ type: "scatter", name, x: [1, 2], y: [2, 3] }], layout: { xaxis: { autorange: true }, yaxis: { autorange: true } }, uirevision,
});
const styledFigure = (): ChartFigure => ({
  ...figure("styled"),
  layout: {
    margin: Object.assign({ l: 56, r: 24, t: 86, b: 96 }, { autoexpand: true }),
    title: { text: "Configurable title", y: 1, yref: "container", yanchor: "top", font: { size: 22, color: "#eeeeee" } },
    font: { family: "Ubuntu", size: 16, color: "#dddddd" },
    legend: { orientation: "h", y: 1, yanchor: "bottom", x: 0, xanchor: "left", font: { size: 16 }, bgcolor: "rgba(0,0,0,0)" },
    xaxis: { autorange: true, title: { text: "X" }, tickangle: -35 }, yaxis: { autorange: true, title: { text: "Y" } },
  },
  config: { scrollZoom: true },
});

describe("Plotly canvas queue", () => {
  it("coalesces changes during loading and draws only the latest figure", async () => {
    const fixture = setup(), loaded = deferred<PlotlyRenderer>();
    const controller = new PlotlyCanvasController(fixture.host as unknown as HTMLElement, () => loaded.promise);
    controller.update(figure("first")); await Promise.resolve();
    controller.update(figure("second")); controller.update(figure("latest"));
    loaded.resolve(fixture.renderer); await controller.whenIdle();
    expect(fixture.renderer.react).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fixture.renderer.react).mock.calls[0][1][0].name).toBe("latest");
    await controller.dispose();
  });

  it("finishes one render before drawing the latest update, resizing or exporting", async () => {
    const fixture = setup(), gate = deferred<void>(); fixture.renderGates.push(gate.promise);
    fixture.controller.update(figure("first"));
    await vi.waitFor(() => expect(fixture.renderer.react).toHaveBeenCalledTimes(1));
    fixture.controller.update(figure("skipped")); fixture.controller.update(figure("latest"));
    const imageGate = deferred<void>(); fixture.imageGates.push(imageGate.promise);
    const image = fixture.controller.exportImage("jpeg", 1200, 600, 2);
    expect(fixture.renderer.toImage).not.toHaveBeenCalled(); expect(fixture.renderer.Plots.resize).not.toHaveBeenCalled();
    gate.resolve(); await vi.waitFor(() => expect(fixture.renderer.toImage).toHaveBeenCalledTimes(1));
    fixture.host.bounds = { width: 1100, height: 700 };
    fixture.main.observers[0].fire(); fixture.main.flush(); imageGate.resolve();
    expect(await image).toBe("data:image/jpeg;base64,chart"); await fixture.controller.whenIdle();
    expect(vi.mocked(fixture.renderer.react).mock.calls.map(call => call[1][0].name)).toEqual(["first", "latest"]);
    expect(fixture.steps).toEqual(["react:first:start", "react:first:end", "react:latest:start", "react:latest:end", "image:start", "image:end", "resize:start", "resize:end"]);
    expect(fixture.maximumActive()).toBe(1);
    expect(fixture.renderer.relayout).toHaveBeenCalledWith(fixture.host.children[0], { width: 1100, height: 700, autosize: false });
    expect(fixture.renderer.Plots.resize).not.toHaveBeenCalled();
    expect(fixture.renderer.toImage).toHaveBeenCalledWith(expect.objectContaining({
      data: expect.arrayContaining([expect.objectContaining({ name: "latest" })]),
      layout: expect.objectContaining({ width: 1200, height: 600, autosize: false }),
    }), { format: "jpeg", width: 1200, height: 600, scale: 2 });
    await fixture.controller.dispose();
  });

  it("serializes reset and updates while export is in flight", async () => {
    const fixture = setup(), gate = deferred<void>();
    fixture.controller.update(figure("first")); await fixture.controller.whenIdle();
    fixture.imageGates.push(gate.promise); const image = fixture.controller.exportImage("svg");
    await vi.waitFor(() => expect(fixture.renderer.toImage).toHaveBeenCalledTimes(1));
    fixture.controller.update(figure("style")); const reset = fixture.controller.resetView();
    expect(fixture.renderer.react).toHaveBeenCalledTimes(1); expect(fixture.renderer.relayout).not.toHaveBeenCalled();
    gate.resolve(); await image; await reset; await fixture.controller.whenIdle();
    expect(fixture.renderer.relayout).toHaveBeenCalledWith(fixture.host.children[0], { "xaxis.autorange": true, "yaxis.autorange": true });
    expect(fixture.steps.indexOf("image:end")).toBeLessThan(fixture.steps.indexOf("react:style:start"));
    expect(fixture.steps.indexOf("react:style:end")).toBeLessThan(fixture.steps.indexOf("reset"));
    await fixture.controller.dispose();
  });

  it("does not mutate figure input and preserves stable uirevision on style and data changes", async () => {
    const fixture = setup(), first = figure("data"), layout = { ...first.layout, uirevision: "ignored-layout-key" };
    fixture.controller.update({ ...first, layout }); await fixture.controller.whenIdle();
    const node = fixture.host.children[0], calls = vi.mocked(fixture.renderer.react).mock.calls;
    (calls[0][1][0] as Data & { name: string }).name = "Plotly mutation";
    calls[0][2].xaxis!.range = [10, 20];
    expect(first.data[0].name).toBe("data"); expect(layout.xaxis?.range).toBeUndefined();
    fixture.controller.update({ ...figure("refreshed"), layout: { ...first.layout, paper_bgcolor: "#111111" } }); await fixture.controller.whenIdle();
    expect(calls[1][0]).toBe(node); expect(calls[1][2].uirevision).toBe(first.uirevision);
    expect(calls[0][2].uirevision).toBe(first.uirevision); expect(calls[1][3].responsive).toBe(false);
    expect(fixture.renderer.purge).not.toHaveBeenCalled();
    await fixture.controller.dispose();
  });

  it("defers purge until the in-flight drawing finishes and disposes exactly once", async () => {
    const fixture = setup(), gate = deferred<void>(); fixture.renderGates.push(gate.promise);
    fixture.controller.update(figure("drawing"));
    await vi.waitFor(() => expect(fixture.renderer.react).toHaveBeenCalledTimes(1));
    const image = fixture.controller.exportImage("png");
    const rejected = expect(image).rejects.toThrow("disponível");
    const cleanup = fixture.controller.dispose(), secondCleanup = fixture.controller.dispose();
    expect(fixture.renderer.purge).not.toHaveBeenCalled(); expect(fixture.main.observers[0].disconnected).toBe(true);
    gate.resolve(); await cleanup; await secondCleanup; await rejected;
    expect(fixture.renderer.purge).toHaveBeenCalledTimes(1); expect(fixture.renderer.toImage).not.toHaveBeenCalled();
    expect(fixture.host.children).toHaveLength(0); expect(fixture.onBusyChange).toHaveBeenLastCalledWith(false);
    expect(fixture.main.frames.size).toBe(0);
  });

  it("does not create a graph when lazy loading completes after unmount", async () => {
    const fixture = setup(), loaded = deferred<PlotlyRenderer>();
    const controller = new PlotlyCanvasController(fixture.host as unknown as HTMLElement, () => loaded.promise);
    controller.update(figure("never-mounted")); await Promise.resolve();
    const cleanup = controller.dispose(); loaded.resolve(fixture.renderer); await cleanup;
    expect(fixture.renderer.react).not.toHaveBeenCalled(); expect(fixture.renderer.purge).not.toHaveBeenCalled();
    expect(fixture.host.children).toHaveLength(0);
  });

  it("rejects an active export immediately on unmount but waits to purge until image generation finishes", async () => {
    const fixture = setup(), gate = deferred<void>();
    fixture.controller.update(figure("first")); await fixture.controller.whenIdle();
    fixture.imageGates.push(gate.promise); const image = fixture.controller.exportImage("png");
    await vi.waitFor(() => expect(fixture.renderer.toImage).toHaveBeenCalledTimes(1));
    const rejected = expect(image).rejects.toThrow("disponível"), cleanup = fixture.controller.dispose();
    await rejected; expect(fixture.renderer.purge).not.toHaveBeenCalled();
    gate.resolve(); await cleanup;
    expect(fixture.renderer.purge).toHaveBeenCalledTimes(1);
  });

  it("does not resolve an export with the prior source after that source changes in flight", async () => {
    const fixture = setup(), gate = deferred<void>();
    fixture.controller.update(figure("A", "source-A")); await fixture.controller.whenIdle();
    fixture.imageGates.push(gate.promise); const image = fixture.controller.exportImage("png");
    await vi.waitFor(() => expect(fixture.renderer.toImage).toHaveBeenCalledTimes(1));
    const rejected = expect(image).rejects.toThrow("mudou");
    fixture.controller.update(figure("B", "source-B")); await rejected;
    expect(fixture.renderer.react).toHaveBeenCalledTimes(1);
    gate.resolve(); await fixture.controller.whenIdle();
    expect(vi.mocked(fixture.renderer.react).mock.calls[1][2].uirevision).toBe("source-B"); await fixture.controller.dispose();
  });

  it("rejects queued operations when the source changes before they can run", async () => {
    const fixture = setup(), gate = deferred<void>(); fixture.renderGates.push(gate.promise);
    fixture.controller.update(figure("source-A", "A"));
    await vi.waitFor(() => expect(fixture.renderer.react).toHaveBeenCalledTimes(1));
    const image = fixture.controller.exportImage("png"), rejected = expect(image).rejects.toThrow("mudou");
    fixture.controller.update(figure("source-B", "B")); gate.resolve(); await rejected;
    expect(fixture.renderer.toImage).not.toHaveBeenCalled(); await fixture.controller.dispose();
  });

  it("reports the current failure, rejects export and accepts a later update without retrying the failed render", async () => {
    const fixture = setup(); vi.mocked(fixture.renderer.react).mockRejectedValueOnce(new Error("invalid figure"));
    fixture.controller.update(figure("bad")); await fixture.controller.whenIdle();
    expect(fixture.onError).toHaveBeenCalledWith("invalid figure"); expect(fixture.renderer.react).toHaveBeenCalledTimes(1);
    await expect(fixture.controller.exportImage("png")).rejects.toThrow("invalid figure");
    fixture.controller.update(figure("corrected")); await fixture.controller.whenIdle();
    expect(fixture.renderer.react).toHaveBeenCalledTimes(2); expect(fixture.onError).toHaveBeenLastCalledWith(undefined);
    await fixture.controller.dispose();
  });

  it("does not publish a failure from a superseded figure", async () => {
    const fixture = setup(), gate = deferred<void>(); fixture.renderGates.push(gate.promise);
    fixture.controller.update(figure("old"));
    await vi.waitFor(() => expect(fixture.renderer.react).toHaveBeenCalledTimes(1));
    fixture.controller.update(figure("new")); gate.reject(new Error("old render failure")); await fixture.controller.whenIdle();
    expect(fixture.onError).not.toHaveBeenCalledWith("old render failure"); expect(fixture.onError).toHaveBeenLastCalledWith(undefined);
    await fixture.controller.dispose();
  });

  it("validates export bounds before allocating an image", async () => {
    const fixture = setup(); fixture.controller.update(figure("first")); await fixture.controller.whenIdle();
    await expect(fixture.controller.exportImage("png", 0, 500)).rejects.toThrow("pixels");
    await expect(fixture.controller.exportImage("png", 10000, 10000, 1)).rejects.toThrow("limite");
    await expect(fixture.controller.exportImage("jpeg", 100, 100, Number.NaN)).rejects.toThrow("limite");
    expect(fixture.renderer.toImage).not.toHaveBeenCalled(); await fixture.controller.dispose();
  });

  it("uses the backend's 40 million pixel budget including image scale and omitted dimensions", async () => {
    const fixture = setup(); fixture.controller.update(figure("pixel budget")); await fixture.controller.whenIdle();
    await expect(fixture.controller.exportImage("png", 3200, 3200, 2)).rejects.toThrow("limite");
    await expect(fixture.controller.exportImage("png", 13000, undefined, 8)).rejects.toThrow("limite");
    expect(fixture.renderer.toImage).not.toHaveBeenCalled();
    await expect(fixture.controller.exportImage("png", 8000, 5000)).resolves.toBe("data:image/png;base64,chart");
    expect(fixture.renderer.toImage).toHaveBeenCalledTimes(1); await fixture.controller.dispose();
  });
});

describe("Plotly across dock and native document lifetimes", () => {
  it("uses only the owner's ResizeObserver/rAF and ignores an old realm's captured callback", async () => {
    const fixture = setup(); fixture.controller.update(figure("first")); await fixture.controller.whenIdle();
    expect(fixture.main.observers).toHaveLength(1); expect(fixture.popout.observers).toHaveLength(0);
    const oldNode = fixture.host.children[0], lateFrame = fixture.main.frames.get(1)!;
    oldNode.layout!.xaxis = { range: [1.2, 1.6], autorange: false };
    fixture.host.bounds = { width: 1700, height: 900 };
    fixture.host.adopt(fixture.otherDocument); fixture.controller.ownerChanged(); await fixture.controller.whenIdle();
    expect(fixture.main.cancelled).toEqual([1]); expect(fixture.main.observers[0].disconnected).toBe(true);
    expect(fixture.popout.observers).toHaveLength(1); expect(fixture.popout.frames.size).toBe(1);
    lateFrame(0); expect(fixture.renderer.Plots.resize).not.toHaveBeenCalled();
    const last = vi.mocked(fixture.renderer.react).mock.calls[1];
    expect(last[0]).not.toBe(oldNode); expect(fixture.host.children[0].ownerDocument).toBe(fixture.otherDocument);
    expect(last[2].xaxis).toMatchObject({ range: [1.2, 1.6], autorange: false });
    expect(last[2]).toMatchObject({ width: 1700, height: 900, autosize: false });
    fixture.host.bounds = { width: 2160, height: 1200 };
    fixture.popout.flush(); await fixture.controller.whenIdle();
    expect(fixture.renderer.relayout).toHaveBeenCalledWith(fixture.host.children[0], { width: 2160, height: 1200, autosize: false });
    expect(fixture.renderer.Plots.resize).not.toHaveBeenCalled();
    expect(fixture.renderer.purge).toHaveBeenCalledExactlyOnceWith(oldNode);
    // Adoption restores once; subsequent GUI zoom belongs to Plotly.uirevision.
    fixture.controller.update(figure("restyled")); await fixture.controller.whenIdle();
    expect(vi.mocked(fixture.renderer.react).mock.calls[2][2].xaxis?.range).toBeUndefined();
    await fixture.controller.dispose();
  });

  it("recreates an adopted graph after its prior render finishes, without concurrent purge", async () => {
    const fixture = setup(), gate = deferred<void>(); fixture.renderGates.push(gate.promise);
    fixture.controller.update(figure("moving"));
    await vi.waitFor(() => expect(fixture.renderer.react).toHaveBeenCalledTimes(1));
    const oldNode = fixture.host.children[0]; fixture.host.adopt(fixture.otherDocument); fixture.controller.ownerChanged();
    expect(fixture.renderer.purge).not.toHaveBeenCalled(); expect(fixture.renderer.react).toHaveBeenCalledTimes(1);
    gate.resolve(); await fixture.controller.whenIdle();
    expect(fixture.renderer.purge).toHaveBeenCalledExactlyOnceWith(oldNode); expect(fixture.renderer.react).toHaveBeenCalledTimes(2);
    expect(fixture.maximumActive()).toBe(1); expect(fixture.host.children).toHaveLength(1); await fixture.controller.dispose();
  });

  it("ignores resize from a closed popout and can return the same source to the main document", async () => {
    const fixture = setup(); fixture.host.adopt(fixture.otherDocument);
    fixture.controller.update(figure("first")); await fixture.controller.whenIdle();
    const lateFrame = fixture.popout.frames.get(1)!; fixture.popout.fire("pagehide"); fixture.popout.closed = true;
    fixture.popout.cancelAnimationFrame = () => { throw new Error("dead window API"); };
    await fixture.controller.whenIdle(); lateFrame(0);
    expect(fixture.renderer.Plots.resize).not.toHaveBeenCalled(); expect(fixture.host.children).toHaveLength(0);
    fixture.host.adopt(fixture.document); fixture.controller.ownerChanged(); await fixture.controller.whenIdle();
    expect(fixture.host.children).toHaveLength(1); expect(fixture.renderer.react).toHaveBeenCalledTimes(2);
    expect(fixture.onError).not.toHaveBeenCalledWith(expect.any(String)); await fixture.controller.dispose();
  });

  it("does not carry a prior source's zoom into a new source during adoption", async () => {
    const fixture = setup(); fixture.controller.update(figure("A", "source-A")); await fixture.controller.whenIdle();
    fixture.host.children[0].layout!.xaxis = { range: [1.2, 1.6], autorange: false };
    fixture.host.adopt(fixture.otherDocument); fixture.controller.update(figure("B", "source-B")); await fixture.controller.whenIdle();
    expect(vi.mocked(fixture.renderer.react).mock.calls[1][2].xaxis?.range).toBeUndefined();
    expect(vi.mocked(fixture.renderer.react).mock.calls[1][2].uirevision).toBe("source-B"); await fixture.controller.dispose();
  });

  it("handles adoption that precedes React's owner-document notification while drawing", async () => {
    const fixture = setup(), gate = deferred<void>(); fixture.renderGates.push(gate.promise);
    fixture.controller.update(figure("adopting"));
    await vi.waitFor(() => expect(fixture.renderer.react).toHaveBeenCalledTimes(1));
    fixture.host.adopt(fixture.otherDocument); gate.resolve(); await fixture.controller.whenIdle();
    expect(fixture.main.observers[0].disconnected).toBe(true); expect(fixture.popout.observers).toHaveLength(1);
    expect(vi.mocked(fixture.renderer.react).mock.calls[1][0]).toBe(fixture.host.children[0]);
    fixture.popout.fire("resize"); fixture.popout.flush(); await fixture.controller.whenIdle();
    expect(fixture.renderer.Plots.resize).not.toHaveBeenCalled(); await fixture.controller.dispose();
  });

  it("passes actual owner-element dimensions at first render rather than Plotly's 700x450 defaults", async () => {
    const fixture = setup(); fixture.host.bounds = { width: 2160.75, height: 1200.5 };
    fixture.controller.update({ ...figure("large"), layout: { width: 700, height: 450 } }); await fixture.controller.whenIdle();
    expect(vi.mocked(fixture.renderer.react).mock.calls[0][2]).toMatchObject({ width: 2160, height: 1200, autosize: false });
    fixture.main.flush(); await fixture.controller.whenIdle();
    expect(fixture.renderer.relayout).not.toHaveBeenCalled(); expect(fixture.renderer.Plots.resize).not.toHaveBeenCalled();
    await fixture.controller.dispose();
  });

  it("coalesces viewport changes while relayout is in flight and uses the latest actual bounds", async () => {
    const fixture = setup(), gate = deferred<void>();
    fixture.controller.update(figure("resizing")); await fixture.controller.whenIdle();
    fixture.resizeGates.push(gate.promise); fixture.host.bounds = { width: 1300, height: 700 };
    fixture.main.flush(); await vi.waitFor(() => expect(fixture.renderer.relayout).toHaveBeenCalledTimes(1));
    fixture.host.bounds = { width: 1500, height: 900 }; fixture.main.observers[0].fire(); fixture.main.flush();
    fixture.host.bounds = { width: 2160, height: 1200 }; fixture.main.observers[0].fire(); fixture.main.flush();
    expect(fixture.renderer.relayout).toHaveBeenCalledTimes(1); gate.resolve(); await fixture.controller.whenIdle();
    expect(vi.mocked(fixture.renderer.relayout).mock.calls.map(call => call[1])).toEqual([
      { width: 1300, height: 700, autosize: false }, { width: 2160, height: 1200, autosize: false },
    ]);
    expect(fixture.maximumActive()).toBe(1); expect(fixture.renderer.Plots.resize).not.toHaveBeenCalled();
    await fixture.controller.dispose();
  });

  it("waits for a visible viewport without drawing defaults or spinning, then renders the latest hidden update", async () => {
    const fixture = setup(); fixture.host.bounds = { width: 0, height: 0 };
    fixture.controller.update(figure("hidden-old")); await fixture.controller.whenIdle();
    fixture.controller.update(figure("hidden-latest")); await fixture.controller.whenIdle();
    expect(fixture.renderer.react).not.toHaveBeenCalled(); expect(fixture.onBusyChange).toHaveBeenLastCalledWith(false);
    await expect(fixture.controller.exportImage("png")).rejects.toThrow("disponível");
    fixture.host.bounds = { width: 1600, height: 900 }; fixture.main.observers[0].fire(); fixture.main.flush();
    await fixture.controller.whenIdle();
    expect(fixture.renderer.react).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fixture.renderer.react).mock.calls[0][1][0].name).toBe("hidden-latest");
    expect(vi.mocked(fixture.renderer.react).mock.calls[0][2]).toMatchObject({ width: 1600, height: 900, autosize: false });
    await fixture.controller.dispose();
  });
});

describe("compact chart display and independent export layout", () => {
  it("keeps title, font and legend visible while reserving plotting space in a 150px dock", async () => {
    const fixture = setup(), source = styledFigure(), original = structuredClone(source);
    fixture.host.bounds = { width: 900, height: 150 };
    fixture.controller.update(source); await fixture.controller.whenIdle();
    const layout = vi.mocked(fixture.renderer.react).mock.calls[0][2];
    expect(layout).toMatchObject({ width: 900, height: 150, margin: { l: 56, r: 24, t: 30, b: 32, autoexpand: false } });
    expect(layout.legend).toMatchObject({ orientation: "h", x: 1, xanchor: "right", y: 1, yanchor: "top" });
    expect(layout.title).toEqual(source.layout!.title); expect(layout.font).toEqual(source.layout!.font);
    expect(layout.legend!.font).toEqual(source.layout!.legend!.font); expect(source).toEqual(original);
    expect(layout.height! - layout.margin!.t! - layout.margin!.b!).toBe(88);
    await fixture.controller.dispose();
  });

  it("restores full styles on expansion and compacts again without replacing the current axes", async () => {
    const fixture = setup(), source = styledFigure(); fixture.host.bounds.height = 180;
    fixture.controller.update(source); await fixture.controller.whenIdle();
    const node = fixture.host.children[0];
    node.layout!.xaxis = { ...node.layout!.xaxis, range: [1.25, 1.75], autorange: false };
    node.layout!.yaxis = { ...node.layout!.yaxis, range: [2.25, 2.75], autorange: false };
    fixture.host.bounds = { width: 1400, height: 850 }; fixture.main.flush(); await fixture.controller.whenIdle();
    expect(node.layout!.margin).toEqual(source.layout!.margin); expect(node.layout!.legend).toEqual(source.layout!.legend);
    expect(node.layout!.xaxis).toMatchObject({ range: [1.25, 1.75], autorange: false });
    expect(node.layout!.yaxis).toMatchObject({ range: [2.25, 2.75], autorange: false });
    await fixture.controller.exportImage("png", 1400, 850);
    const exported = vi.mocked(fixture.renderer.toImage).mock.calls[0][0] as PlotlyDataLayoutConfig;
    expect(exported.layout!.margin).toEqual(source.layout!.margin); expect(exported.layout!.legend).toEqual(source.layout!.legend);
    expect(exported.layout!.xaxis!.range).toEqual([1.25, 1.75]); expect(exported.layout!.yaxis!.range).toEqual([2.25, 2.75]);
    fixture.host.bounds.height = 130; fixture.main.observers[0].fire(); fixture.main.flush(); await fixture.controller.whenIdle();
    expect(node.layout!.margin).toMatchObject({ t: 30, b: 32, autoexpand: false });
    expect(node.layout!.legend).toMatchObject({ x: 1, xanchor: "right", y: 1, yanchor: "top" });
    expect(node.layout!.xaxis!.range).toEqual([1.25, 1.75]);
    expect(fixture.renderer.react).toHaveBeenCalledTimes(1);
    for (const call of vi.mocked(fixture.renderer.relayout).mock.calls) {
      expect(Object.keys(call[1]).some(key => /^[xy]axis/.test(key))).toBe(false);
    }
    await fixture.controller.dispose();
  });

  it("exports full original styles and current axis zoom from a compact dock without mutating either snapshot", async () => {
    const fixture = setup(), source = styledFigure(), original = structuredClone(source);
    fixture.host.bounds.height = 150; fixture.controller.update(source); await fixture.controller.whenIdle();
    const node = fixture.host.children[0];
    node.layout!.xaxis = { ...node.layout!.xaxis, range: [1.1, 1.4], autorange: false };
    node.layout!.yaxis2 = { title: { text: "Second axis" }, range: ["2026-10-01T12:34:56.123456789", "2026-10-02T12:34:56.123456789"], autorange: false };
    const displayed = structuredClone(node.layout);
    await expect(fixture.controller.exportImage("png", 1400, 850, 2)).resolves.toBe("data:image/png;base64,chart");
    const [exported, options] = vi.mocked(fixture.renderer.toImage).mock.calls[0] as [PlotlyDataLayoutConfig, unknown];
    expect(exported.layout).toMatchObject({ width: 1400, height: 850, autosize: false });
    expect(exported.layout!.margin).toEqual(source.layout!.margin); expect(exported.layout!.legend).toEqual(source.layout!.legend);
    expect(exported.layout!.title).toEqual(source.layout!.title); expect(exported.layout!.font).toEqual(source.layout!.font);
    expect(exported.layout!.xaxis).toMatchObject({ title: { text: "X" }, tickangle: -35, range: [1.1, 1.4], autorange: false });
    expect(exported.layout!.yaxis2).toMatchObject({ range: node.layout!.yaxis2.range, autorange: false });
    expect(exported.config).toMatchObject({ scrollZoom: true, responsive: false });
    expect(options).toEqual({ format: "png", width: 1400, height: 850, scale: 2 });
    // Even a renderer that changes its export input cannot change the display or
    // the persisted backend figure.
    exported.layout!.margin!.t = 999; exported.layout!.xaxis!.range![0] = 999;
    (exported.data[0] as Data & { name: string }).name = "mutated export";
    expect(node.layout).toEqual(displayed); expect(source).toEqual(original);
    await fixture.controller.dispose();
  });

  it("uses the actual dock dimensions and a compact layout when export dimensions are omitted", async () => {
    const fixture = setup(), source = styledFigure(); fixture.host.bounds = { width: 980, height: 180 };
    fixture.controller.update(source); await fixture.controller.whenIdle(); await fixture.controller.exportImage("svg");
    const [exported, options] = vi.mocked(fixture.renderer.toImage).mock.calls[0] as [PlotlyDataLayoutConfig, unknown];
    expect(exported.layout).toMatchObject({ width: 980, height: 180, margin: { t: 30, b: 32 }, legend: { x: 1, yanchor: "top" } });
    expect(options).toEqual({ format: "svg", width: 980, height: 180, scale: 1 });
    expect(source.layout!.margin!.t).toBe(86); await fixture.controller.dispose();
  });

  it("restores unspecified Plotly defaults at the breakpoint instead of retaining compact overrides", async () => {
    const fixture = setup(); fixture.host.bounds.height = 259;
    fixture.controller.update(figure("defaults")); await fixture.controller.whenIdle();
    fixture.host.bounds.height = 260; fixture.main.flush(); await fixture.controller.whenIdle();
    const update = vi.mocked(fixture.renderer.relayout).mock.calls[0][1] as Record<string, unknown>;
    expect(update).toMatchObject({ "margin.t": null, "margin.b": null, "margin.autoexpand": null, "legend.x": null, "legend.y": null, "legend.xanchor": null, "legend.yanchor": null });
    expect(fixture.host.children[0].layout!.margin!.t).toBeUndefined();
    expect(fixture.host.children[0].layout!.legend!.xanchor).toBeUndefined();
    await fixture.controller.dispose();
  });
});
