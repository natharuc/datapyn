export interface ExportSettings {
  delimiter: string; decimal: string; encoding: string; include_header: boolean; open_folder: boolean;
}
export const DEFAULT_EXPORT_SETTINGS: ExportSettings = {
  delimiter: ";", decimal: ".", encoding: "utf-8-sig", include_header: true, open_folder: true,
};
export function normalizeExportSettings(raw: Partial<ExportSettings> | undefined): ExportSettings {
  const value = raw ?? {};
  return {
    delimiter: [";", ",", "\t", "|"].includes(value.delimiter ?? "") ? value.delimiter! : DEFAULT_EXPORT_SETTINGS.delimiter,
    decimal: value.decimal === "," ? "," : ".",
    encoding: ["utf-8-sig", "utf-8", "cp1252", "latin-1"].includes(value.encoding ?? "") ? value.encoding! : DEFAULT_EXPORT_SETTINGS.encoding,
    include_header: value.include_header !== false,
    open_folder: value.open_folder !== false,
  };
}
