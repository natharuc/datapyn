import { forwardRef, useImperativeHandle, useLayoutEffect, useRef, type CSSProperties } from "react";
import type { Config, Data, Layout } from "plotly.js";
import { PlotlyCanvasController, type ChartImageFormat } from "./plotlyCanvasController";
import { loadPlotly } from "./plotlyLoader";
import { useOwnerDocumentRevision } from "./useOwnerDocument";

export interface ChartCanvasHandle {
  exportImage(format: ChartImageFormat, width?: number, height?: number, scale?: number): Promise<string>;
  resetView(): Promise<void>;
}
export interface ChartCanvasProps {
  data: Data[];
  layout?: Partial<Layout>;
  config?: Partial<Config>;
  uirevision: string | number;
  className?: string;
  style?: CSSProperties;
  ariaLabel?: string;
  ownerDocumentRevision?: number;
  onBusyChange?(busy: boolean): void;
  onError?(message: string | undefined): void;
}

export const ChartCanvas = forwardRef<ChartCanvasHandle, ChartCanvasProps>(function ChartCanvas({
  data, layout, config, uirevision, className = "chart-canvas", style, ariaLabel,
  ownerDocumentRevision, onBusyChange, onError,
}, ref) {
  const host = useRef<HTMLDivElement>(null), controller = useRef<PlotlyCanvasController>();
  const callbacks = useRef({ onBusyChange, onError }); callbacks.current = { onBusyChange, onError };
  const documentRevision = useOwnerDocumentRevision(host);
  useLayoutEffect(() => {
    const instance = new PlotlyCanvasController(host.current!, loadPlotly, {
      onBusyChange: busy => callbacks.current.onBusyChange?.(busy),
      onError: message => callbacks.current.onError?.(message),
    });
    controller.current = instance;
    return () => { controller.current = undefined; void instance.dispose(); };
  }, []);
  useLayoutEffect(() => { controller.current?.update({ data, layout, config, uirevision }); }, [data, layout, config, uirevision]);
  useLayoutEffect(() => { controller.current?.ownerChanged(); }, [documentRevision, ownerDocumentRevision]);
  useImperativeHandle(ref, () => ({
    exportImage: (format, width, height, scale) => controller.current?.exportImage(format, width, height, scale) ?? Promise.reject(new Error("O gráfico não está disponível.")),
    resetView: () => controller.current?.resetView() ?? Promise.reject(new Error("O gráfico não está disponível.")),
  }), []);
  return <div ref={host} className={className} role="img" aria-label={ariaLabel} style={{ width: "100%", height: "100%", minWidth: 0, ...style }}/>
});
