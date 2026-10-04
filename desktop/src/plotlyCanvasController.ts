import type { Config, Data, Layout, PlotlyDataLayoutConfig, PlotlyHTMLElement, ToImgopts } from "plotly.js";

export type ChartImageFormat = "png" | "svg" | "jpeg";
export interface ChartFigure {
  data: Data[];
  layout?: Partial<Layout>;
  config?: Partial<Config>;
  uirevision: string | number;
}
export interface PlotlyRenderer {
  react(node: HTMLElement, data: Data[], layout: Partial<Layout>, config: Partial<Config>): Promise<unknown>;
  purge(node: HTMLElement): void;
  relayout(node: HTMLElement, update: Partial<Layout>): Promise<unknown>;
  toImage(figure: HTMLElement | PlotlyDataLayoutConfig, options: ToImgopts): Promise<string>;
  Plots: { resize(node: PlotlyHTMLElement): unknown };
}
interface FigureVersion extends ChartFigure { version: number }
interface Graph {
  node: HTMLDivElement;
  document: Document;
  window: Window;
  ready: boolean;
  purged: boolean;
  figure?: FigureVersion;
  size?: { width: number; height: number };
  compact?: boolean;
}
interface Command {
  revision: string | number;
  run(renderer: PlotlyRenderer, graph: Graph): Promise<unknown>;
  resolve(value: unknown): void;
  reject(error: Error): void;
}
type AxisViewport = Record<string, { range?: unknown[]; autorange?: unknown }>;
type ObserverWindow = Window & typeof globalThis;
const unavailable = () => new Error("O gráfico não está mais disponível.");
const changed = () => new Error("O gráfico mudou antes da operação. Tente novamente.");
const errorObject = (value: unknown) => value instanceof Error ? value : new Error(String(value));
const compactHeight = 260;
const maximumImagePixels = 40_000_000;

function compactStyles(layout: Partial<Layout>): Record<string, unknown> {
  return {
    "margin.t": Math.min(layout.margin?.t ?? 30, 30),
    "margin.b": Math.min(layout.margin?.b ?? 32, 32),
    "margin.autoexpand": false,
    "legend.x": 1, "legend.xanchor": "right", "legend.y": 1, "legend.yanchor": "top",
  };
}

function sizedLayout(original: Partial<Layout>, size: { width: number; height: number }): Partial<Layout> {
  const layout = structuredClone(original);
  if (size.height < compactHeight) {
    const styles = compactStyles(layout);
    // Plotly supports autoexpand, though the bundled @types Margin omits it.
    const margin = { ...layout.margin, t: styles["margin.t"] as number, b: styles["margin.b"] as number, autoexpand: false };
    layout.margin = margin;
    layout.legend = { ...layout.legend, x: 1, xanchor: "right", y: 1, yanchor: "top" };
  }
  return { ...layout, ...size, autosize: false };
}

function axisViewport(layout: Partial<Layout> | undefined): AxisViewport {
  const axes: AxisViewport = {};
  for (const [name, axis] of Object.entries(layout ?? {})) {
    if (!/^[xy]axis\d*$/.test(name) || !axis || typeof axis !== "object") continue;
    const value = axis as { range?: unknown[]; autorange?: unknown };
    if (Array.isArray(value.range)) axes[name] = { range: structuredClone(value.range), autorange: value.autorange ?? false };
  }
  return axes;
}

function applyViewport(layout: Partial<Layout>, axes: AxisViewport): void {
  const fields = layout as Record<string, unknown>;
  for (const [axis, view] of Object.entries(axes)) fields[axis] = { ...(fields[axis] as object ?? {}), ...structuredClone(view) };
}

/** All Plotly work, including export and resize, runs through the same serial queue. */
export class PlotlyCanvasController {
  private latest?: FigureVersion;
  private version = 0;
  private dirty = false;
  private renderer?: PlotlyRenderer;
  private graph?: Graph;
  private running?: Promise<void>;
  private disposed = false;
  private busy = false;
  private failure?: Error;
  private commands: Command[] = [];
  private activeCommand?: Command;
  private resizePending = false;
  private frame?: { window: Window; document: Document; id: number };
  private observer?: ResizeObserver;
  private bound?: { window: Window; document: Document; resize: () => void; close: () => void };
  private closingDocuments = new WeakSet<Document>();
  private viewport?: { revision: string | number; axes: AxisViewport };

  constructor(private readonly host: HTMLElement, private readonly load: () => Promise<PlotlyRenderer>,
    private readonly callbacks: { onBusyChange?(busy: boolean): void; onError?(message: string | undefined): void } = {}) {}

  update(figure: ChartFigure): void {
    if (this.disposed) return;
    if (this.latest && !Object.is(this.latest.uirevision, figure.uirevision)) {
      this.viewport = undefined;
      this.activeCommand?.reject(changed());
    }
    this.latest = { ...figure, version: ++this.version };
    this.dirty = true;
    this.failure = undefined;
    this.ownerChanged();
    this.start();
  }

  /** Dockview can adopt the host before React renders its document revision. */
  ownerChanged(): void {
    if (this.disposed) return;
    const owner = this.owner();
    if (owner?.document !== this.bound?.document || owner?.window !== this.bound?.window) {
      this.unbind();
      if (this.graph && (!owner || this.graph.document !== owner.document || this.graph.window !== owner.window)) {
        this.captureViewport(this.graph);
        this.dirty = Boolean(this.latest);
        this.activeCommand?.reject(unavailable());
      }
      if (owner) this.bind(owner.document, owner.window);
      this.start();
    }
    if (owner) this.requestResize();
  }

  exportImage(format: ChartImageFormat, width?: number, height?: number, scale = 1): Promise<string> {
    if (!["png", "svg", "jpeg"].includes(format)) return Promise.reject(new Error("Formato de imagem inválido."));
    for (const value of [width, height]) {
      if (value !== undefined && (!Number.isInteger(value) || value < 1 || value > 16384)) {
        return Promise.reject(new Error("A largura e a altura devem estar entre 1 e 16384 pixels."));
      }
    }
    if (!Number.isFinite(scale) || scale <= 0 || scale > 8 || (width && height && width * height * scale * scale > maximumImagePixels)) {
      return Promise.reject(new Error("A escala da imagem excede o limite de exportação."));
    }
    return this.command<string>((renderer, graph) => {
      const figure = graph.figure!;
      const size = { width: width ?? graph.size!.width, height: height ?? graph.size!.height };
      if (size.width * size.height * scale * scale > maximumImagePixels) throw new Error("A escala da imagem excede o limite de exportação.");
      // toImage's object API creates an independent exported plot. Keep the
      // original figure's full-size styles rather than the small dock's layout.
      const layout = sizedLayout(figure.layout ?? {}, size);
      applyViewport(layout, axisViewport((graph.node as unknown as PlotlyHTMLElement).layout));
      return renderer.toImage({ data: structuredClone(figure.data), layout, config: { ...structuredClone(figure.config ?? {}), responsive: false } }, {
        format, ...size, scale,
      });
    });
  }

  resetView(): Promise<void> {
    return this.command<void>(async (renderer, graph) => {
      const layout = (graph.node as unknown as PlotlyHTMLElement).layout ?? {};
      const axes = new Set(Object.keys(layout).filter(key => /^[xy]axis\d*$/.test(key)));
      if (graph.figure?.data.some(trace => trace.type === "bar" || !trace.type || trace.type === "scatter")) {
        axes.add("xaxis"); axes.add("yaxis");
      }
      const update = Object.fromEntries([...axes].map(axis => [`${axis}.autorange`, true]));
      if (axes.size) await renderer.relayout(graph.node, update as Partial<Layout>);
      this.viewport = undefined;
    });
  }

  async whenIdle(): Promise<void> {
    while (this.running) await this.running;
  }

  dispose(): Promise<void> {
    if (!this.disposed) {
      this.disposed = true;
      this.latest = undefined;
      this.dirty = false;
      this.resizePending = false;
      this.unbind();
      this.rejectCommands(unavailable());
      this.activeCommand?.reject(unavailable());
      this.setBusy(false);
      // Purging during react/toImage corrupts Plotly's in-flight drawing state.
      if (!this.running) this.retireGraph();
    }
    return this.running ?? Promise.resolve();
  }

  private owner(): { document: Document; window: Window } | undefined {
    const document = this.host.ownerDocument, window = document.defaultView;
    if (!window || window.closed || this.closingDocuments.has(document)) return;
    return { document, window };
  }

  private validGraph(graph: Graph): boolean {
    const owner = this.owner();
    return !this.disposed && this.graph === graph && !graph.purged && owner?.document === graph.document && owner.window === graph.window;
  }

  private bind(document: Document, window: Window): void {
    const resize = () => this.requestResize();
    const close = () => {
      this.closingDocuments.add(document);
      this.unbind();
      this.activeCommand?.reject(unavailable());
      this.dirty = Boolean(this.latest);
      this.start();
    };
    this.bound = { document, window, resize, close };
    window.addEventListener("resize", resize);
    window.addEventListener("pagehide", close);
    const Resize = (window as ObserverWindow).ResizeObserver;
    if (Resize) { this.observer = new Resize(resize); this.observer.observe(this.host); }
  }

  private unbind(): void {
    this.cancelFrame();
    this.resizePending = false;
    this.observer?.disconnect(); this.observer = undefined;
    const bound = this.bound; this.bound = undefined;
    if (bound && !bound.window.closed) {
      bound.window.removeEventListener("resize", bound.resize);
      bound.window.removeEventListener("pagehide", bound.close);
    }
  }

  private cancelFrame(): void {
    const frame = this.frame; this.frame = undefined;
    if (frame && !frame.window.closed) frame.window.cancelAnimationFrame(frame.id);
  }

  private requestResize(): void {
    if (this.disposed) return;
    const owner = this.owner(); if (!owner) return;
    if (this.frame && (this.frame.document !== owner.document || this.frame.window !== owner.window)) this.cancelFrame();
    if (this.frame) return;
    const frame = { ...owner, id: 0 }; this.frame = frame;
    frame.id = owner.window.requestAnimationFrame(() => {
      if (this.frame !== frame) return;
      this.frame = undefined;
      const current = this.owner();
      if (this.disposed || current?.document !== frame.document || current.window !== frame.window) return;
      if (this.latest && (!this.graph?.ready || this.graph.figure?.version !== this.latest.version)) this.dirty = true;
      this.resizePending = true;
      this.start();
    });
  }

  private command<T>(run: Command["run"]): Promise<T> {
    if (this.disposed || !this.latest || !this.owner() || !this.measureSize()) return Promise.reject(unavailable());
    const revision = this.latest.uirevision;
    const request = new Promise<T>((resolve, reject) => {
      this.commands.push({ revision, run, resolve: value => resolve(value as T), reject });
    });
    this.start();
    return request;
  }

  private start(): void {
    if (this.running || this.disposed) return;
    // Defer the first frame so synchronous state changes and lazy loading coalesce.
    this.running = Promise.resolve().then(() => this.drain()).finally(() => {
      if (this.disposed) this.retireGraph();
      this.running = undefined;
      const work = this.owner() && (this.dirty || this.commands.length || this.resizePending);
      if (!this.disposed && work) this.start(); else this.setBusy(false);
    });
    this.setBusy(true);
  }

  private async drain(): Promise<void> {
    try {
      if (this.disposed) return;
      if (!this.owner()) { this.retireGraph(); this.rejectCommands(unavailable()); return; }
      this.renderer ??= await this.load();
      if (this.disposed) return;
      while (!this.disposed) {
        const owner = this.owner();
        if (!owner) { this.retireGraph(); this.rejectCommands(unavailable()); return; }
        if (this.bound?.document !== owner.document || this.bound.window !== owner.window) {
          this.unbind(); this.bind(owner.document, owner.window);
        }
        if (this.graph && !this.validGraph(this.graph)) {
          this.captureViewport(this.graph); this.retireGraph(); this.dirty = Boolean(this.latest);
        }
        if (!this.graph && this.latest) {
          const node = owner.document.createElement("div");
          node.style.width = "100%"; node.style.height = "100%";
          this.host.appendChild(node);
          this.graph = { node, ...owner, ready: false, purged: false };
          this.dirty = true;
        }
        const graph = this.graph;
        if (!graph) { this.rejectCommands(unavailable()); return; }
        if (this.dirty && this.latest) {
          const figure = this.latest; this.dirty = false;
          const size = this.measureSize();
          if (!size) {
            // An invisible dock has no drawable viewport. Its owner's observer
            // resumes the latest figure when the panel becomes visible again.
            this.resizePending = false; this.rejectCommands(unavailable()); return;
          }
          try {
            const layout = sizedLayout(figure.layout ?? {}, size);
            const restoredViewport = !graph.ready && !graph.figure && this.viewport && Object.is(this.viewport.revision, figure.uirevision) ? this.viewport : undefined;
            if (restoredViewport) {
              applyViewport(layout, restoredViewport.axes);
            }
            // Plotly's autosize reads the singleton's global window rather than
            // this adopted element's document. Give it the actual dock bounds.
            await this.renderer.react(graph.node, structuredClone(figure.data), { ...layout, uirevision: figure.uirevision }, {
              displaylogo: false, scrollZoom: true, modeBarButtonsToRemove: ["lasso2d", "select2d", "toImage"], ...figure.config, responsive: false,
            });
            graph.ready = true; graph.figure = figure; graph.size = size; graph.compact = size.height < compactHeight;
            if (this.viewport === restoredViewport) this.viewport = undefined;
            if (this.validGraph(graph) && this.latest.version === figure.version) {
              this.failure = undefined; this.callbacks.onError?.(undefined);
            }
          } catch (error) {
            graph.ready = false;
            if (this.validGraph(graph) && this.latest.version === figure.version) {
              this.failure = errorObject(error); this.callbacks.onError?.(this.failure.message);
            }
          }
          continue;
        }
        const command = this.commands.shift();
        if (command) {
          if (!graph.ready) { command.reject(this.failure ?? unavailable()); continue; }
          if (!Object.is(command.revision, this.latest?.uirevision)) {
            command.reject(changed()); continue;
          }
          this.activeCommand = command;
          try {
            const value = await command.run(this.renderer, graph);
            if (!this.validGraph(graph)) command.reject(unavailable());
            else if (!Object.is(command.revision, this.latest?.uirevision)) command.reject(changed());
            else command.resolve(value);
          } catch (error) { command.reject(errorObject(error)); }
          finally { this.activeCommand = undefined; }
          continue;
        }
        if (this.resizePending) {
          this.resizePending = false;
          const size = this.measureSize();
          if (graph.ready && size && (graph.size?.width !== size.width || graph.size.height !== size.height)) {
            try {
              const compact = size.height < compactHeight;
              const update: Record<string, unknown> = { ...size, autosize: false };
              if (compact !== graph.compact) {
                const original = graph.figure?.layout ?? {};
                if (compact) Object.assign(update, compactStyles(original));
                else {
                  // Null restores Plotly defaults when the original snapshot did
                  // not specify a field. Dotted updates leave all axes untouched.
                  for (const key of Object.keys(compactStyles(original))) {
                    const [section, field] = key.split(".");
                    update[key] = (original[section as keyof Layout] as Record<string, unknown> | undefined)?.[field] ?? null;
                  }
                }
              }
              await this.renderer.relayout(graph.node, update as Partial<Layout>);
              graph.size = size; graph.compact = compact;
            }
            catch (error) { if (this.validGraph(graph)) this.callbacks.onError?.(errorObject(error).message); }
          }
          continue;
        }
        return;
      }
    } catch (error) {
      this.dirty = false; this.resizePending = false;
      this.failure = errorObject(error);
      this.rejectCommands(this.failure);
      if (!this.disposed) this.callbacks.onError?.(this.failure.message);
    }
  }

  private captureViewport(graph: Graph): void {
    if (!graph.ready || !graph.figure || graph.purged) return;
    this.viewport = { revision: graph.figure.uirevision, axes: axisViewport((graph.node as unknown as PlotlyHTMLElement).layout) };
  }

  private measureSize(): { width: number; height: number } | undefined {
    const bounds = this.host.getBoundingClientRect();
    if (!Number.isFinite(bounds.width) || !Number.isFinite(bounds.height) || bounds.width < 10 || bounds.height < 10) return;
    return { width: Math.floor(bounds.width), height: Math.floor(bounds.height) };
  }

  private retireGraph(): void {
    const graph = this.graph;
    if (graph) this.captureViewport(graph);
    this.graph = undefined;
    if (!graph || graph.purged) return;
    graph.purged = true;
    try { this.renderer?.purge(graph.node); }
    catch (error) { if (!this.disposed && this.owner()) this.callbacks.onError?.(errorObject(error).message); }
    graph.node.remove();
  }

  private rejectCommands(error: Error): void {
    for (const command of this.commands.splice(0)) command.reject(error);
  }

  private setBusy(busy: boolean): void {
    if (this.busy === busy) return;
    this.busy = busy; this.callbacks.onBusyChange?.(busy);
  }
}
