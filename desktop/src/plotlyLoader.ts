import type * as Plotly from "plotly.js";

let pending: Promise<typeof Plotly> | undefined;

/** Loading a chart must not add Plotly to the editor's initial bundle. */
export function loadPlotly(): Promise<typeof Plotly> {
  if (!pending) {
    const request = import("plotly.js-basic-dist-min").then(module => module.default);
    pending = request;
    void request.catch(() => { if (pending === request) pending = undefined; });
  }
  return pending;
}
