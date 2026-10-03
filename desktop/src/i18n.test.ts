import {afterEach,describe,expect,it,vi} from "vitest";
import {getLocale,localizedSearch,setLocale,subscribeLocale,translate} from "./i18n";
afterEach(()=>{setLocale("pt-BR");vi.unstubAllGlobals();});
describe("Live interface locale",()=>{
  it("reuses legacy keys, new visible labels and keeps unknown text intact",()=>{
    expect(translate("menu.save",{},"en-US")).toBe("Save");
    expect(translate("Nova conexão",{},"en-US")).toBe("New connection");
    expect(translate("Preferências de cópia",{},"en-US")).toBe("Copy preferences");
    expect(translate("Enter the connection name.",{},"pt-BR")).toBe("Informe o nome da conexão.");
    expect(translate("server-side custom error",{},"en-US")).toBe("server-side custom error");
  });
  it("interpolates user-provided names once without interpreting braces inside them",()=>{
    expect(translate("Excluir “{name}” do catálogo?",{name:"{admin} ☃"},"en-US")).toBe("Delete “{admin} ☃” from the catalog?");
  });
  it("notifies React stores on locale changes and permits unsubscribing",()=>{
    vi.stubGlobal("document",{documentElement:{lang:""}});const listener=vi.fn(),unsubscribe=subscribeLocale(listener);
    setLocale("en-US");expect(listener).toHaveBeenCalledOnce();expect(document.documentElement.lang).toBe("en-US");expect(getLocale()).toBe("en-US");
    setLocale("en-US");expect(listener).toHaveBeenCalledOnce();unsubscribe();setLocale("pt-BR");expect(listener).toHaveBeenCalledOnce();
  });
  it("finds settings in either language and without accents",()=>{
    expect(localizedSearch("password","Senha")).toBe(true);expect(localizedSearch("autenticacao","Autenticação")).toBe(true);expect(localizedSearch("unknown","Autenticação")).toBe(false);
  });
});
