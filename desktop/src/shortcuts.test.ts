import { describe, expect, it } from "vitest";
import { DEFAULT_SHORTCUTS, commandForEvent, loadShortcuts, shortcutConflicts } from "./shortcuts";

const key = (value: string, modifiers: Partial<{ ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean; repeat: boolean }> = {}) => ({ key: value, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, repeat: false, ...modifiers });
describe("Atalhos", () => {
  it("separa executar, avançar e fila conforme modificadores", () => {
    expect(commandForEvent(key("F5"))).toBe("run"); expect(commandForEvent(key("Enter", { ctrlKey: true }))).toBe("run");
    expect(commandForEvent(key("Enter", { shiftKey: true }))).toBe("runAdvance"); expect(commandForEvent(key("F5", { ctrlKey: true }))).toBe("runAll");
    expect(commandForEvent(key("b", { ctrlKey: true, shiftKey: true }))).toBe("addBlock");
  });
  it("aceita Cmd no macOS e aliases de sessão", () => {
    expect(commandForEvent(key("s", { metaKey: true }))).toBe("save"); expect(commandForEvent(key("t", { ctrlKey: true }))).toBe("newTab");
  });
  it("reabre abas com o gesto dos navegadores sem colidir com a atualização de schema", () => {
    expect(commandForEvent(key("t", { ctrlKey: true, shiftKey: true }))).toBe("reopenClosedTab");
    expect(commandForEvent(key("t", { metaKey: true, shiftKey: true }))).toBe("reopenClosedTab");
    expect(commandForEvent(key("r", { ctrlKey: true, altKey: true }))).toBe("reloadSchema");
    expect(shortcutConflicts(DEFAULT_SHORTCUTS)).toEqual([]);
  });
  it("migra o antigo atalho padrão em configurações sem o comando de reabrir", () => {
    const migrated = loadShortcuts({reloadSchema:"Shift+Ctrl+T",run:"F9",newTab:""});
    expect(migrated).toMatchObject({reloadSchema:"Ctrl+Alt+R",reopenClosedTab:"Ctrl+Shift+T",run:"F9",newTab:""});
    expect(shortcutConflicts(migrated)).toEqual([]);
    expect(commandForEvent(key("t", { ctrlKey: true, shiftKey: true }),migrated)).toBe("reopenClosedTab");
  });
  it("preserva remapeamentos explícitos e atalhos desabilitados ao carregar ou importar", () => {
    expect(loadShortcuts({reloadSchema:"Alt+F8"})).toMatchObject({reloadSchema:"Alt+F8",reopenClosedTab:"Ctrl+Shift+T"});
    expect(loadShortcuts({reloadSchema:"Ctrl+Shift+T",reopenClosedTab:"Alt+F9"})).toMatchObject({reloadSchema:"Ctrl+Shift+T",reopenClosedTab:"Alt+F9"});
    expect(loadShortcuts({reloadSchema:"Ctrl+Shift+T",reopenClosedTab:""})).toMatchObject({reloadSchema:"Ctrl+Shift+T",reopenClosedTab:""});
    const current=loadShortcuts({save:"Alt+S",reopenClosedTab:"Alt+F9"});
    expect(loadShortcuts({reloadSchema:"Ctrl+Shift+T",run:"F9"},current)).toMatchObject({save:"Alt+S",run:"F9",reloadSchema:"Ctrl+Alt+R",reopenClosedTab:"Alt+F9"});
    expect(loadShortcuts({reloadSchema:"Ctrl+Shift+T",reopenClosedTab:"Alt+F9"},current)).toMatchObject({reloadSchema:"Ctrl+Shift+T",reopenClosedTab:"Alt+F9"});
  });
  it("ignora entradas de atalhos inválidas sem quebrar o roteamento", () => {
    for(const input of [null,[],"bad",{save:12,reopenClosedTab:null,unknown:"F2"}]){
      const shortcuts=loadShortcuts(input);
      expect(shortcuts).toEqual(DEFAULT_SHORTCUTS);
      expect(commandForEvent(key("t",{ctrlKey:true,shiftKey:true}),shortcuts)).toBe("reopenClosedTab");
    }
  });
  it("não repete execução e roteia busca para o editor focado", () => {
    expect(commandForEvent(key("F5", { repeat: true }))).toBeUndefined(); expect(commandForEvent(key("f", { ctrlKey: true }))).toBe("find");
  });
  it("remapeia comandos e identifica colisões", () => {
    const custom = { ...DEFAULT_SHORTCUTS, run: "Ctrl+R" };
    expect(commandForEvent(key("r", { ctrlKey: true }), custom)).toBe("run"); expect(commandForEvent(key("Enter", { ctrlKey: true }), custom)).toBeUndefined();
    expect(shortcutConflicts({ ...custom, save: "Ctrl+R" })).toHaveLength(1);
    expect(shortcutConflicts({ ...custom, save: "F5" })).toHaveLength(0);
  });
  it("desabilita atalhos vazios e normaliza as sequências antigas do Qt", () => {
    expect(commandForEvent(key("F5"), {...DEFAULT_SHORTCUTS,run:""})).toBeUndefined();
    expect(commandForEvent(key("Return", {shiftKey:true}), {...DEFAULT_SHORTCUTS,runAdvance:"Shift+Return"})).toBe("runAdvance");
    expect(shortcutConflicts({...DEFAULT_SHORTCUTS,save:"Shift+Ctrl+F"})).toHaveLength(1);
    expect(commandForEvent(key("l",{ctrlKey:true}))).toBe("editorCutLine");
    expect(commandForEvent(key("l",{ctrlKey:true,shiftKey:true}))).toBe("clearResults");
  });
});
