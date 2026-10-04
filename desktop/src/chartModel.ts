import type { ChartConfig, DataView } from "./dataTypes";
import type { ResultRef } from "./runtime";

export type ChartSourceMode = "all" | "filtered" | "selection";
export const CHART_TYPES = ["bar", "line", "area", "scatter", "pie"] as const;
export const CHART_AGGREGATIONS = ["sum", "mean", "min", "max", "count", "median"] as const;
export const CHART_DEFAULTS: ChartConfig = {
  type: "bar", aggregation: "sum", nulls: "zero", palette: "default", stacking: "grouped", sort: "original",
  show_grid: true, show_legend: true, show_line: true, show_markers: true, show_axis_line: false,
  show_data_labels: false, horizontal: false, normalize: false, line_width: 2, marker_size: 5,
  line_style: "solid", bar_opacity: 94, area_opacity: 20, label_decimals: 1, live_preview: true,
  source_mode: "filtered",
};

export function normalizeChartConfig(result: ResultRef, initial?: ChartConfig): ChartConfig {
  const numeric = result.columns.filter(c => /int|float|decimal|double|number|numeric|real/i.test(c.dtype));
  const numericColumns=new Set(numeric);
  const x = result.columns.find(c => !numericColumns.has(c))?.name ?? "";
  const y = numeric.find(c => c.name !== x) ?? result.columns.find(c => c.name !== x);
  return { ...CHART_DEFAULTS, x_column: x,
    ...initial, y_columns: initial?.y_columns === undefined ? y ? [y.name] : [] : Array.isArray(initial.y_columns) ? [...new Set(initial.y_columns.filter((name):name is string=>typeof name === "string"))] : [],
    custom_colors:Array.isArray(initial?.custom_colors) ? initial.custom_colors.filter((color):color is string=>typeof color === "string") : [],
    stacking: initial?.stacking === "none" ? "grouped" : initial?.stacking ?? "grouped",
    sort: initial?.sort === "none" ? "original" : initial?.sort || "original" };
}

export function chartConfigError(result: ResultRef, config: ChartConfig, view?: DataView): string | undefined {
  const counts = new Map<string, number>();
  result.columns.forEach(c => counts.set(c.name, (counts.get(c.name) ?? 0) + 1));
  if (!CHART_TYPES.includes(config.type as typeof CHART_TYPES[number])) return "Escolha um tipo de gráfico válido.";
  if (!CHART_AGGREGATIONS.includes(config.aggregation as typeof CHART_AGGREGATIONS[number])) return "Escolha uma agregação válida.";
  if (!config.y_columns?.length) return "Escolha pelo menos uma série Y.";
  if (config.y_columns.length > 50) return "Escolha até 50 séries Y.";
  const columns = [config.x_column, ...config.y_columns, config.group_by].filter((c): c is string => typeof c === "string" && c !== "");
  for (const name of columns) {
    if (!counts.has(name)) return "Uma coluna configurada não existe nesta versão dos dados. Revise os eixos e séries.";
    if (counts.get(name)! > 1) return "Renomeie as colunas duplicadas antes de usá-las no gráfico.";
  }
  if (config.source_mode === "selection" && !(config.selection_view as DataView | undefined)?.scope && !view?.scope) return "Selecione células na grade antes de usar somente a seleção.";
  return;
}

export function chartSourceView(config: ChartConfig, current?: DataView): DataView {
  if (config.source_mode === "all") return {};
  if (config.source_mode === "selection") return (config.selection_view as DataView | undefined) ?? current ?? {};
  return current ? { filter: current.filter, sort: current.sort } : {};
}

/** Canvas interactions reset for a different source/axes, not for color/title updates. */
export function chartInteractionRevision(sessionId: string, result: ResultRef, config: ChartConfig): string {
  return JSON.stringify([sessionId, result.result_id, config.type, config.x_column, config.y_columns, config.group_by]);
}

export function chartPreparationKey(source: Record<string, unknown>, config: ChartConfig): string {
  const keys = ["type", "x_column", "y_columns", "group_by", "aggregation", "nulls", "sort", "normalize", "stacking"];
  return JSON.stringify([source, keys.map(key => config[key])]);
}

export function chartThemeConfig(config: ChartConfig, light: boolean): ChartConfig {
  const defaults = light
    ? { background_color: "#ffffff", text_color: "#263448", grid_color: "#e0e6ef", axis_color: "#8392a8" }
    : { background_color: "#101725", text_color: "#d6dce8", grid_color: "#253044", axis_color: "#697b98" };
  return { ...config, ...Object.fromEntries(Object.entries(defaults).map(([key, value]) => [key, config[key] || value])), label_color: config.label_color || config.text_color || defaults.text_color };
}

export interface SavedChart { id: string; title: string; variable_name: string; config: ChartConfig }
export function activeSavedChart(extras: Record<string, unknown>): string | undefined {
  const id = extras.desktop_chart_id;
  return typeof id === "string" && Array.isArray(extras.charts) && (extras.charts as SavedChart[]).some(chart => chart?.id === id) ? id : undefined;
}
export function latestChartSource(name: string, results: readonly ResultRef[]): ResultRef | undefined {
  for (let index = results.length - 1; index >= 0; index--) if (results[index].variable_name === name) return results[index];
}

/** Reopening a chart must not register a fresh invisible result handle every time. */
export class ChartSourceCache {
  private sessions=new Map<string,{revision:number;values:Map<string,Promise<ResultRef>>}>();
  clear():void{this.sessions.clear();}
  resolve(sessionId:string,revision:number,name:string,inspect:()=>Promise<ResultRef>):Promise<ResultRef>{
    let session=this.sessions.get(sessionId);
    if(!session || session.revision!==revision){session={revision,values:new Map()};this.sessions.set(sessionId,session);}
    const previous=session.values.get(name);if(previous)return previous;
    const owner=session;
    const pending=inspect().catch(error=>{if(owner.values.get(name)===pending)owner.values.delete(name);throw error;});
    session.values.set(name,pending);
    if(this.sessions.size>32)this.sessions.delete(this.sessions.keys().next().value!);
    return pending;
  }
}

/** At most one RPC runs; typing replaces the queued request and invalidates old answers. */
export class ChartPreviewQueue<T> {
  private revision = 0;
  private pending?: { revision: number; run: () => Promise<T>; accept: (value: T) => void; fail: (error: unknown) => void };
  private running = false;
  private disposed = false;
  constructor(private readonly onBusy: (busy: boolean) => void) {}
  invalidate(): void { this.revision++; this.pending = undefined; }
  request(run: () => Promise<T>, accept: (value: T) => void, fail: (error: unknown) => void): void {
    if (this.disposed) return;
    this.pending = { revision: ++this.revision, run, accept, fail };
    void this.drain();
  }
  private async drain(): Promise<void> {
    if (this.running || this.disposed) return;
    this.running = true; this.onBusy(true);
    try {
      while (this.pending && !this.disposed) {
        const job = this.pending; this.pending = undefined;
        try { const value = await job.run(); if (!this.disposed && job.revision === this.revision) job.accept(value); }
        catch (error) { if (!this.disposed && job.revision === this.revision) job.fail(error); }
      }
    } finally { this.running = false; if (!this.disposed) this.onBusy(false); }
  }
  dispose(): void { this.disposed = true; this.invalidate(); }
}
