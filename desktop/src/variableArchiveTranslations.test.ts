import {afterEach, describe, expect, it} from "vitest";
import {featureTranslate} from "./featureTranslations";
import {setLocale} from "./i18n";

afterEach(() => setLocale("pt-BR"));
describe("portable variable package translations", () => {
  it("switches package controls to English without altering variable names or paths", () => {
    setLocale("en-US");
    expect(featureTranslate("Exportar variáveis")).toBe("Export variables");
    expect(featureTranslate("Pasta com várias variáveis")).toBe("Folder with multiple variables");
    expect(featureTranslate("Substituir variáveis existentes")).toBe("Replace existing variables");
    expect(featureTranslate("{count} variáveis exportadas para {path}", {count: 2, path: "C:/João/{dados}"})).toBe("2 variables exported to C:/João/{dados}");
    setLocale("pt-BR");
    expect(featureTranslate("Exportar variáveis")).toBe("Exportar variáveis");
  });
});
