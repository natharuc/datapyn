import { describe, expect, it } from "vitest";
import { DEFAULT_SHORTCUTS, commandForEvent, shortcutConflicts } from "./shortcuts";

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
