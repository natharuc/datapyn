export type QueryDownloadFormat = "csv" | "parquet";
export function queryDownloadPath(path: string, format: QueryDownloadFormat) {
  return `${path.replace(/\.(csv|parquet)$/i, "")}.${format}`;
}
export function downloadDirectory(path: string) {
  const index = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return index >= 0 ? path.slice(0, index + 1) : "";
}
export function queryDownloadDefaultPath(title: string, format: QueryDownloadFormat, directory = "") {
  const name = title.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").trim().replace(/[. ]+$/, "") || "consulta";
  return `${directory}${directory && !/[\\/]$/.test(directory) ? "\\" : ""}${name}.${format}`;
}
