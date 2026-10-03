import {describe, expect, it} from "vitest";
import {importedDataCode} from "./importCode";

describe("Reproducible data reader blocks", () => {
  it("retains the chosen CSV options and quotes Windows paths", () => {
    expect(importedDataCode('C:\\reports\\Nathan "data".csv', "sales", {delimiter: "|", decimal: ",", encoding: "cp1252"}))
      .toBe('sales = pd.read_csv("C:\\\\reports\\\\Nathan \\"data\\".csv", sep="|", encoding="cp1252", decimal=",")\nsales');
  });
  it("reuses sniffing and preserves the normalized runtime variable", () => {
    expect(importedDataCode("/tmp/source.csv", "df_source", {delimiter: null}))
      .toContain('df_source = pd.read_csv("/tmp/source.csv", sep=None, engine="python"');
    expect(importedDataCode("/tmp/source.tsv", "df_source")).toContain('sep="\\t"');
  });
  it("uses actual file readers for JSON, Excel and Parquet", () => {
    expect(importedDataCode("/tmp/a.parquet", "df")).toBe('df = pd.read_parquet("/tmp/a.parquet")\ndf');
    expect(importedDataCode("/tmp/a.xlsx", "df")).toContain('pd.read_excel("/tmp/a.xlsx")');
    expect(importedDataCode("/tmp/a.json", "df")).toContain('pd.read_json("/tmp/a.json")');
  });
});
