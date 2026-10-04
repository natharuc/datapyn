export type RichExportType = "image" | "json" | "html" | "plotly";

/** Derive the format from the actual destination chosen in the native dialog. */
export function artifactExportTarget(type: RichExportType, path: string): {path: string; format: string} {
  const extension = path.match(/\.([^.\\/]+)$/)?.[1].toLowerCase();
  const allowed = type === "image" ? ["png", "jpg", "jpeg"] : type === "plotly" ? ["html", "json"] : [type];
  const fallback = type === "image" ? "png" : type === "json" ? "json" : "html";
  const format = extension && allowed.includes(extension) ? extension : fallback;
  return {path: extension === format ? path : `${path}.${format}`, format};
}
