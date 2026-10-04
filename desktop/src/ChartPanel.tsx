import { useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { save } from "@tauri-apps/plugin-dialog";
import { AreaChart, ArrowLeft, ArrowRight, ArrowUp, ArrowDown, BarChart3, Copy, Download, LineChart, LoaderCircle, Maximize2, PieChart, RefreshCw, ScatterChart, Settings2, X } from "lucide-react";
import type { Data, Layout } from "plotly.js";
import { featureTranslate as t } from "./featureTranslations";
import { useLocale } from "./i18n";
import { runtime, errorText, type ResultRef } from "./runtime";
import type { ChartConfig, ChartResponse, DataView } from "./dataTypes";
import { ChartCanvas, type ChartCanvasHandle } from "./ChartCanvas";
import {useOwnerDocumentRevision} from "./useOwnerDocument";
import { chartConfigError, chartInteractionRevision, chartPreparationKey, chartSourceView, chartThemeConfig, ChartPreviewQueue, normalizeChartConfig } from "./chartModel";
import "./dataActions.css";
import "./chartPanel.css";

export interface ChartPanelProps {
  sessionId: string; result: ResultRef; view?: DataView; initialConfig?: ChartConfig;
  title?: string; onConfigChange?: (config: ChartConfig) => void; onMessage?: (message: string) => void;
  onDuplicate?: () => void; availableResults?: ResultRef[]; onSourceChange?: (name: string) => void;
  onMove?: (direction:-1|1)=>void; canMoveLeft?:boolean; canMoveRight?:boolean;
  disabled?: boolean; active?: boolean; theme?: "dark" | "light" | "system"; refreshRevision?: number;
}
const chartTypes = [["bar", "Barras", BarChart3], ["line", "Linhas", LineChart], ["area", "Área", AreaChart], ["scatter", "Dispersão", ScatterChart], ["pie", "Pizza", PieChart]] as const;
const EMPTY_LAYOUT: Partial<Layout> = {};
const EMPTY_DATA: Data[] = [];

export function ChartPanel({ sessionId, result, view, initialConfig, title, onConfigChange, onMessage, onDuplicate,
  availableResults, onSourceChange, onMove,canMoveLeft,canMoveRight, disabled, active = true, theme = "dark", refreshRevision = 0 }: ChartPanelProps) {
  const locale = useLocale(), panel = useRef<HTMLDivElement>(null), canvas = useRef<ChartCanvasHandle>(null);
  const ownerRevision=useOwnerDocumentRevision(panel);
  const [config, setConfig] = useState(() => normalizeChartConfig(result, initialConfig));
  const baseline=useRef(config);
  const baselineSource=useRef(result.result_id);
  const [settingsOpen, setSettingsOpen] = useState(true), [seriesSearch, setSeriesSearch] = useState("");
  const [busy, setBusy] = useState(false), [painting, setPainting] = useState(false), [exporting, setExporting] = useState(false);
  const [error, setError] = useState(""), [canvasError, setCanvasError] = useState<string>();
  const [rendered, setRendered] = useState<{ response: ChartResponse; key: string; dataKey: string }>();
  const [systemLight, setSystemLight] = useState(false);
  const queue = useRef<ChartPreviewQueue<ChartResponse>>(), lastQueued = useRef("");
  const initialKey = JSON.stringify(initialConfig ?? {});
  useEffect(() => {
    const next = normalizeChartConfig(result, initialConfig);
    if(baselineSource.current!==result.result_id){baseline.current=next;baselineSource.current=result.result_id;}
    setConfig(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next);
  }, [initialKey, result.result_id]);
  useEffect(() => {
    const media = panel.current?.ownerDocument.defaultView?.matchMedia("(prefers-color-scheme: light)");
    if (!media) return; const update = () => setSystemLight(media.matches); update();
    media.addEventListener("change", update); return () => media.removeEventListener("change", update);
  }, [ownerRevision]);
  const light = theme === "light" || theme === "system" && systemLight;
  const effectiveConfig = useMemo(() => chartThemeConfig(config, light), [config, light]);
  const source = chartSourceView(config, view);
  // Inspection handles can expire independently of the namespace metadata.
  const params = { session_id: sessionId, variable_name: result.variable_name, ...source, config: effectiveConfig, language: locale };
  const requestKey = JSON.stringify({ ...params, refreshRevision });
  const dataKey = chartPreparationKey({sessionId, resultId:result.result_id, ...source, refreshRevision}, config);
  const validation = chartConfigError(result, config, view), chart = rendered?.response;
  const stale = Boolean(rendered && rendered.key !== requestKey);
  useEffect(() => {
    const worker = new ChartPreviewQueue<ChartResponse>(setBusy); queue.current = worker;
    return () => { worker.dispose(); if (queue.current === worker) queue.current = undefined; };
  }, []);
  useLayoutEffect(() => { queue.current?.invalidate(); lastQueued.current = ""; setError(""); }, [requestKey, active, disabled]);
  useEffect(() => { setRendered(undefined); setCanvasError(undefined); }, [sessionId, result.result_id]);
  function render(restyle = false) {
    if (disabled || !active || validation || exporting) return;
    lastQueued.current = requestKey; setError("");
    const chart_id = restyle && rendered?.dataKey === dataKey ? rendered.response.chart_id : undefined;
    queue.current?.request(() => runtime.request<ChartResponse>("result.chart", {...params, ...(chart_id ? {chart_id} : {})}),
      response => setRendered({ response, key: requestKey, dataKey }), failure => setError(errorText(failure)));
  }
  useEffect(() => {
    if (!config.live_preview || disabled || !active || exporting || validation || lastQueued.current === requestKey) return;
    const owner = panel.current?.ownerDocument.defaultView; if (!owner) return;
    const timer = owner.setTimeout(() => {if(lastQueued.current !== requestKey)render(true);}, 420); return () => owner.clearTimeout(timer);
  }, [requestKey, config.live_preview, active, disabled, exporting, validation,ownerRevision]);
  function update(key: string, value: unknown) {
    const next = { ...config, [key]: value }; setConfig(next); onConfigChange?.(next);
  }
  function sourceMode(value: string) {
    const next = { ...config, source_mode: value, ...(value === "selection" && view?.scope ? { selection_view: structuredClone(view) } : {}) };
    setConfig(next); onConfigChange?.(next);
  }
  async function exportChart(format: "png" | "jpg" | "html" | "json") {
    if (!chart || stale || busy || painting || exporting || !canvas.current) return;
    setExporting(true); setError("");
    // The figure ID captures its original source, filters and styles at preview time.
    const snapshot = chart, destination = String(snapshot.config.title || title || result.variable_name || "grafico").replace(/[\\/:*?"<>|]+/g, "_");
    try {
      // Capture the visible figure before a native dialog can outlive this source.
      const width = Number(config.export_width) || 1400, height = Number(config.export_height) || 850;
      const image_data = format === "png" || format === "jpg" ? await canvas.current.exportImage("png", width, height, Number(config.export_scale) || 1) : undefined;
      const path = await save({ defaultPath: `${destination}.${format}`, filters: [{ name: format === "html" ? t("Gráfico interativo offline") : format.toUpperCase(), extensions: format === "jpg" ? ["jpg", "jpeg"] : [format] }] });
      if (!path) return;
      const saved = await runtime.request<{ path: string }>("result.chart_export", {
        ...params, config: snapshot.config, chart_id: snapshot.chart_id, path, format, image_data,
      });
      onMessage?.(t("Gráfico salvo: {path}", { path: saved.path }));
    } catch (failure) { setError(errorText(failure)); } finally { setExporting(false); }
  }
  const search = useDeferredValue(seriesSearch.trim().toLocaleLowerCase(locale));
  const shownColumns = useMemo(() => result.columns.filter(c => !search || c.name.toLocaleLowerCase(locale).includes(search)).slice(0, 200), [result.columns, search, locale]);
  const names = useMemo(() => [...new Set(result.columns.map(c => c.name))], [result.columns]);
  const numericField = (key: string, label: string, low: number, high: number, fallback: number) => <label>{t(label)}<input type="number" min={low} max={high} value={Number(config[key] ?? fallback)} disabled={exporting} onChange={event => { const value = event.target.valueAsNumber; if (Number.isFinite(value)) update(key, Math.min(high, Math.max(low, value))); }}/></label>;
  const select = (key: string, label: string, options: readonly (readonly [string, string])[]) => <label>{t(label)}<select value={String(config[key] ?? "")} disabled={exporting} onChange={event => update(key, event.target.value)}>{options.map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label>;
  const columnPicker = (key: "x_column" | "group_by", label: string, empty: string) => <label>{t(label)}<input list={`${sessionId}-${result.result_id}-${key}`} value={String(config[key] || "")} placeholder={t(empty)} disabled={exporting} onChange={event => update(key, event.target.value)}/><datalist id={`${sessionId}-${result.result_id}-${key}`}>{names.filter(name => !config[key] || name.toLocaleLowerCase(locale).includes(String(config[key]).toLocaleLowerCase(locale))).slice(0, 200).map(name => <option key={name} value={name}/>)}</datalist></label>;
  const check = (key: string, label: string) => <label className="data-check" key={key}><input type="checkbox" checked={Boolean(config[key])} disabled={exporting} onChange={event => update(key, event.target.checked)}/>{t(label)}</label>;
  const data = chart?.figure.data as Data[] | undefined ?? EMPTY_DATA;
  const layout = chart?.figure.layout as Partial<Layout> | undefined ?? EMPTY_LAYOUT;
  const interaction = chartInteractionRevision(sessionId, result, chart?.config ?? config);

  return <div ref={panel} className="chart-panel" data-settings-open={settingsOpen}>
    <header className="chart-toolbar">
      <button className={settingsOpen ? "chart-active" : ""} aria-pressed={settingsOpen} onClick={() => {if(!settingsOpen)baseline.current=structuredClone(config);setSettingsOpen(!settingsOpen);}}><Settings2 size={14}/>{t("Configurar")}</button>
      <strong title={title || result.variable_name}>{title || t("Gráfico")}</strong><span className="chart-source-tag">{result.variable_name}</span>
      <div className="chart-toolbar-actions"><button disabled={disabled || !active || Boolean(validation) || exporting} onClick={() => render()} title={t("Atualizar gráfico")}>{busy ? <LoaderCircle size={14} className="spin"/> : <RefreshCw size={14}/>}<span>{t("Atualizar")}</span></button>
        <button disabled={!chart || painting || exporting} onClick={() => void canvas.current?.resetView().catch(e => setError(errorText(e)))} title={t("Restaurar zoom")} aria-label={t("Restaurar zoom")}><Maximize2 size={14}/></button>
        {onDuplicate && <button onClick={onDuplicate} disabled={exporting} title={t("Duplicar gráfico")} aria-label={t("Duplicar gráfico")}><Copy size={14}/></button>}
        {onMove && <><button disabled={!canMoveLeft || exporting} onClick={()=>onMove(-1)} title={t("Mover gráfico à esquerda")} aria-label={t("Mover gráfico à esquerda")}><ArrowLeft size={14}/></button><button disabled={!canMoveRight || exporting} onClick={()=>onMove(1)} title={t("Mover gráfico à direita")} aria-label={t("Mover gráfico à direita")}><ArrowRight size={14}/></button></>}
        <details className="chart-export-menu"><summary aria-label={t("Exportar gráfico")}><Download size={14}/>{t("Exportar")}</summary><div>{(["png", "jpg", "html", "json"] as const).map(format => <button key={format} disabled={!chart || stale || busy || painting || exporting || disabled} onClick={() => void exportChart(format)}>{format.toUpperCase()}</button>)}</div></details>
      </div>
    </header>
    <aside className="chart-settings" aria-label={t("Configuração do gráfico")} hidden={!settingsOpen}>
      <div className="chart-settings-heading"><span>{t("DADOS E VISUAL")}</span><button aria-label={t("Fechar configuração")} onClick={() => setSettingsOpen(false)}><X size={13}/></button></div>
      <div className="chart-type-picker" role="group" aria-label={t("Tipo de gráfico")}>{chartTypes.map(([type, label, Icon]) => <button key={type} disabled={exporting} aria-pressed={config.type === type} className={config.type === type ? "chart-active" : ""} onClick={() => update("type", type)}><Icon size={18}/><span>{t(label)}</span></button>)}</div>
      <fieldset className="chart-section"><legend>{t("Fonte e eixos")}</legend>
        {availableResults && onSourceChange && <label>{t("DataFrame")}<select value={result.variable_name} disabled={exporting} onChange={e => onSourceChange(e.target.value)}>{availableResults.map(item => <option key={item.variable_name} value={item.variable_name}>{item.variable_name}{item.result_id ? ` · ${item.row_count.toLocaleString(locale)}` : ""}</option>)}</select></label>}
        <label>{t("Dados do gráfico")}<select value={String(config.source_mode)} disabled={exporting} onChange={e => sourceMode(e.target.value)}><option value="filtered">{t("Dados filtrados")}</option><option value="all">{t("Todos os dados")}</option><option value="selection" disabled={!view?.scope && !(config.selection_view as DataView | undefined)?.scope}>{t("Somente seleção")}</option></select></label>
        {columnPicker("x_column", "Eixo X", "Índice")}
        <div className="chart-series-heading"><span>{t("Séries Y")}</span><small>{config.y_columns?.length || 0}/50</small></div>
        <input className="chart-series-search" aria-label={t("Buscar séries")} placeholder={t("Buscar colunas…")} value={seriesSearch} onChange={e => setSeriesSearch(e.target.value)}/>
        <div className="chart-series">{shownColumns.map((column, index) => <label className="data-check" key={`${column.name}:${index}`}><input type="checkbox" disabled={exporting || !config.y_columns?.includes(column.name) && (config.y_columns?.length ?? 0) >= 50} checked={config.y_columns?.includes(column.name) ?? false} onChange={e => update("y_columns", e.target.checked ? [...config.y_columns ?? [], column.name] : config.y_columns?.filter(name => name !== column.name))}/><span title={column.name}>{column.name}</span><small>{column.dtype}</small></label>)}</div>
        {result.columns.length > 200 && <small className="chart-hint">{t("Até 200 colunas exibidas. Use a busca para localizar outras.")}</small>}
        {config.y_columns?.filter(name => !names.includes(name)).map(name => <button className="chart-missing-column" key={name} onClick={() => update("y_columns", config.y_columns?.filter(c => c !== name))}>{name}<X size={12}/></button>)}
        {(config.y_columns?.length ?? 0)>1 && <div className="chart-series-order">{config.y_columns!.map((name,index)=><div key={name}><span title={name}>{index+1}. {name}</span>{([-1,1] as const).map(direction=><button key={direction} disabled={exporting || index+direction<0 || index+direction>=config.y_columns!.length} aria-label={`${t(direction===-1?"Mover série para cima":"Mover série para baixo")}: ${name}`} onClick={()=>{const ordered=[...config.y_columns!];[ordered[index],ordered[index+direction]]=[ordered[index+direction],ordered[index]];update("y_columns",ordered);}}>{direction===-1?<ArrowUp size={12}/>:<ArrowDown size={12}/>}</button>)}</div>)}</div>}
        {select("aggregation", "Agregação", [["sum", "sum"], ["mean", "mean"], ["min", "min"], ["max", "max"], ["count", "count"], ["median", "median"]])}
        {columnPicker("group_by", "Agrupar por", "Sem agrupamento")}
        {Boolean(config.group_by) && (config.y_columns?.length ?? 0) > 1 && <small className="chart-hint">{t("Agrupamento por coluna utiliza uma série Y.")}</small>}
      </fieldset>
      <details className="chart-section" open><summary>{t("Tratamento dos dados")}</summary>
        <div className="data-field-row">{select("nulls", "Nulos", [["zero", "Zero"], ["drop", "Ignorar"], ["keep", "Preservar"]])}{select("sort", "Ordem", [["original", "Original"], ["x_asc", "X crescente"], ["y_desc", "Y decrescente"]])}</div>
        {config.type !== "pie" && select("stacking", "Empilhamento", [["grouped", "Agrupado"], ["stacked", "Empilhado"], ["percent", "Percentual"]])}
        <div className="chart-toggles">{check("normalize", "Normalizar %")}{config.type === "bar" && check("horizontal", "Horizontal")}</div>
      </details>
      <details className="chart-section" open><summary>{t("Títulos e aparência")}</summary>
        <label>{t("Título")}<input value={String(config.title || "")} disabled={exporting} onChange={e => update("title", e.target.value)}/></label>
        <div className="data-field-row"><label>{t("Rótulo X")}<input value={String(config.x_label || "")} disabled={exporting} onChange={e => update("x_label", e.target.value)}/></label><label>{t("Rótulo Y")}<input value={String(config.y_label || "")} disabled={exporting} onChange={e => update("y_label", e.target.value)}/></label></div>
        {select("palette", "Paleta", [["default", "default"], ["categorical", "categorical"], ["teal", "teal"], ["warm", "warm"], ["ocean", "ocean"]])}
        <div className="chart-toggles">{[["show_grid", "Grade"], ["show_axis_line", "Eixos"], ["show_legend", "Legenda"], ["show_data_labels", "Rótulos"]].map(([key,label]) => check(key,label))}</div>
      </details>
      <details className="chart-section"><summary>{t("Traços e marcadores")}</summary>
        <div className="chart-toggles">{check("show_line", "Linhas")}{check("show_markers", "Marcadores")}</div>
        {select("line_style", "Traço", [["solid", "Contínuo"], ["dashed", "Tracejado"], ["dotted", "Pontilhado"], ["dashdot", "Traço e ponto"]])}
        <div className="data-field-row">{numericField("line_width", "Espessura", 1, 10, 2)}{numericField("marker_size", "Marcador", 1, 18, 5)}</div>
        <div className="data-field-row">{numericField("bar_opacity", "Barras %", 10, 100, 94)}{numericField("area_opacity", "Área %", 5, 90, 20)}</div>
        {numericField("label_decimals", "Decimais dos rótulos", 0, 6, 1)}
      </details>
      <details className="chart-section"><summary>{t("Cores e tipografia")}</summary>
        <label>{t("Cores das séries")}<input value={Array.isArray(config.custom_colors) ? config.custom_colors.join(", ") : ""} placeholder="#5b8def, #3ddc97" disabled={exporting} onChange={e => update("custom_colors", e.target.value.split(",").map(c => c.trim()).filter(Boolean))}/></label>
        <div className="chart-color-fields">{[["background_color", "Fundo"], ["text_color", "Texto"], ["label_color", "Rótulos"], ["grid_color", "Grade"], ["axis_color", "Eixos"]].map(([key,label]) => <label key={key}><span>{t(label)}</span><input type="color" disabled={exporting} aria-label={`${t(label)}: ${t("Cor")}`} value={/^#[0-9a-f]{6}$/i.test(String(effectiveConfig[key])) ? String(effectiveConfig[key]) : "#000000"} onChange={e => update(key,e.target.value)}/><input aria-label={`${t(label)}: ${t("Valor")}`} value={String(config[key] || "")} placeholder={String(effectiveConfig[key])} disabled={exporting} onChange={e => update(key,e.target.value)}/></label>)}</div>
        <button className="chart-reset-colors" disabled={exporting} onClick={() => { const next={...config}; ["background_color","text_color","label_color","grid_color","axis_color"].forEach(k => delete next[k]); setConfig(next); onConfigChange?.(next); }}>{t("Usar cores do tema")}</button>
        <label>{t("Fonte")}<input list={`${sessionId}-chart-fonts`} value={String(config.font_family || "")} placeholder={t("Padrão")} disabled={exporting} onChange={e=>update("font_family",e.target.value)}/><datalist id={`${sessionId}-chart-fonts`}><option value="Ubuntu, Segoe UI, sans-serif"/><option value="Segoe UI, sans-serif"/><option value="Consolas, monospace"/></datalist></label>
        <div className="data-field-row">{numericField("font_size", "Texto px", 8, 24, 12)}{numericField("title_size", "Título px", 10, 32, 16)}{numericField("tick_size", "Eixos px", 8, 20, 11)}</div>
        {select("hover_mode", "Inspeção", [["x unified", "X combinado"], ["closest", "Ponto mais próximo"], ["x", "Eixo X"], ["y", "Eixo Y"]])}
      </details>
      <details className="chart-section"><summary>{t("Tamanho da exportação")}</summary><div className="data-field-row">{numericField("export_width", "Largura px", 320, 4096, 1400)}{numericField("export_height", "Altura px", 240, 4096, 850)}</div>{numericField("export_scale", "Escala", 1, 3, 1)}</details>
      <label className="data-check chart-live-preview"><input type="checkbox" checked={Boolean(config.live_preview)} disabled={exporting} onChange={e => update("live_preview",e.target.checked)}/>{t("Prévia automática")}</label>
      <div className="chart-settings-footer"><button disabled={exporting} onClick={()=>{const next=normalizeChartConfig(result,baseline.current);setConfig(next);onConfigChange?.(next);}}>{t("Reverter alterações")}</button><button disabled={exporting || Boolean(validation)} onClick={()=>{baseline.current=structuredClone(config);setSettingsOpen(false);}}>{t("Aplicar")}</button></div>
    </aside>
    <main className="chart-main">
      {(validation || error || canvasError) && <p className="data-error chart-error" role="alert">{validation ? t(validation) : error || canvasError}</p>}
      {stale && <div className="chart-stale" role="status">{t("Configuração alterada. Atualize para exportar.")}</div>}
      <ChartCanvas ref={canvas} data={data} layout={layout} uirevision={interaction} onBusyChange={setPainting} onError={setCanvasError} ariaLabel={`${t("Gráfico")}: ${title || result.variable_name}`}/>
      {!chart && <div className="chart-empty"><BarChart3 size={28}/><strong>{t("Explore seus dados")}</strong><span>{t("Escolha os eixos e gere o gráfico.")}</span></div>}
      {(busy || painting || exporting) && <div className="chart-loading" role="status"><LoaderCircle size={13} className="spin"/>{t(exporting ? "Exportando…" : "Atualizando gráfico…")}</div>}
      <footer className="chart-metrics">{chart ? <><span>{chart.source_rows.toLocaleString(locale)} {t("linhas de origem")}</span><span>{chart.point_count.toLocaleString(locale)} {t("pontos")}{chart.series_count ? ` · ${chart.series_count} ${t("séries")}` : ""}</span>{chart.geometry_approximate && <span title={t("Valores exatos na inspeção; geometria aproximada.")}>{t("Geometria aproximada")}</span>}{chart.bounded && <strong>{t("Prévia limitada")}{chart.aggregated_point_count ? ` · ${chart.aggregated_point_count.toLocaleString(locale)} ${t("categorias no total")}` : ""}</strong>}</> : <span>{t("A agregação utiliza a fonte escolhida.")}</span>}</footer>
    </main>
  </div>;
}
