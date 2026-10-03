import {afterEach, describe, expect, it} from "vitest";
import {setLocale} from "./i18n";
import {featureTranslate} from "./featureTranslations";

afterEach(() => setLocale("pt-BR"));
describe("Data, chart and workspace translations", () => {
  it("switches the migrated feature labels with the live locale", () => {
    expect(featureTranslate("Confirmar remoção do snapshot")).toBe("Confirmar remoção do snapshot");
    setLocale("en-US");
    expect(featureTranslate("Confirmar remoção do snapshot")).toBe("Confirm snapshot removal");
    expect(featureTranslate("Exportar para tabela")).toBe("Export to table");
    expect(featureTranslate("Envio externo suprimido")).toBe("External delivery suppressed");
    expect(featureTranslate("Totais da seleção")).toBe("Selection totals");
    expect(featureTranslate("Zoom do resumo")).toBe("Summary zoom");
    expect(featureTranslate("Preservar")).toBe("Keep");
  });
  it("interpolates names and paths only once in both languages", () => {
    const variables = {name: "{name} ☃", rows: "1152921504606846979"};
    expect(featureTranslate("Arquivo importado: {name} · {rows} linhas", variables))
      .toBe("Arquivo importado: {name} ☃ · 1152921504606846979 linhas");
    setLocale("en-US");
    expect(featureTranslate("Arquivo importado: {name} · {rows} linhas", variables))
      .toBe("Imported file: {name} ☃ · 1152921504606846979 rows");
  });
  it("translates chart enum labels while preserving saved user templates", () => {
    setLocale("en-US");
    expect(featureTranslate("sum")).toBe("Sum");
    expect(featureTranslate("categorical")).toBe("Categorical");
    expect(featureTranslate("{{result[0][0]}} custom SQL label")).toBe("{{result[0][0]}} custom SQL label");
  });
});
