import { describe, expect, it } from "vitest";
import { downloadDirectory, queryDownloadDefaultPath, queryDownloadPath } from "./queryDownload";
describe("streaming query download destinations", () => {
  it("enforces the selected format, including an existing opposite extension", () => {
    expect(queryDownloadPath("C:\\reports\\result.PARQUET", "csv")).toBe("C:\\reports\\result.csv");
    expect(queryDownloadPath("result", "parquet")).toBe("result.parquet");
  });
  it("preserves Windows/UNC directories and cleans names from SQL block titles", () => {
    const directory = downloadDirectory("\\\\server\\reports\\result.csv");
    expect(queryDownloadDefaultPath("Vendas: Q3/2026", "csv", directory)).toBe("\\\\server\\reports\\Vendas_ Q3_2026.csv");
    expect(downloadDirectory("/tmp/result.csv")).toBe("/tmp/");
    expect(queryDownloadDefaultPath("...", "parquet")).toBe("consulta.parquet");
  });
});
