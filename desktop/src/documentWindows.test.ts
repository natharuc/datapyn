import { afterEach, describe, expect, it, vi } from "vitest";
import { copyLazyStylesheets, copyRootPresentation, findInDocuments, getFocusedDocument, hasFocusedDocument, observeElementDocument, PopoutBindings, refreshOwnerDocuments, registerDocument } from "./documentWindows";

const documentReleases: Array<() => void> = [];
afterEach(() => { documentReleases.splice(0).forEach(release => release()); vi.unstubAllGlobals(); });
describe("Native popout document bridge", () => {
  it("considers the application focused when either the main window or a detached dock is focused", () => {
    let mainFocused = true, childFocused = false;
    const main = { hasFocus: () => mainFocused } as unknown as Document;
    const child = { hasFocus: () => childFocused, defaultView: { closed: false } } as unknown as Document;
    documentReleases.push(registerDocument(child));
    expect(hasFocusedDocument(main)).toBe(true);
    mainFocused = false;
    expect(hasFocusedDocument(main)).toBe(false);
    childFocused = true;
    expect(hasFocusedDocument(main)).toBe(true);
    childFocused = false;
    expect(hasFocusedDocument(main)).toBe(false);
  });
  it("ignores closed, hidden or released popouts even if they retain a focus flag", () => {
    let closed = false, visibilityState = "visible";
    const main = { hasFocus: () => false } as unknown as Document;
    const child = { hasFocus: () => true, get visibilityState() { return visibilityState; }, defaultView: { get closed() { return closed; } } } as unknown as Document;
    const release = registerDocument(child); documentReleases.push(release);
    expect(hasFocusedDocument(main)).toBe(true);
    closed = true; expect(hasFocusedDocument(main)).toBe(false);
    closed = false; visibilityState = "hidden"; expect(hasFocusedDocument(main)).toBe(false);
    visibilityState = "visible"; expect(hasFocusedDocument(main)).toBe(true);
    release(); expect(hasFocusedDocument(main)).toBe(false);
  });
  it("targets a shortcut modal to the focused child document and ignores closed/released windows", () => {
    let mainFocused=false,childFocused=true,closed=false;
    const main={hasFocus:()=>mainFocused} as unknown as Document;
    const child={hasFocus:()=>childFocused,defaultView:{get closed(){return closed;}}} as unknown as Document;
    const unregister=registerDocument(child);
    expect(getFocusedDocument(main)).toBe(child);
    mainFocused=true;childFocused=false;expect(getFocusedDocument(main)).toBe(main);
    mainFocused=false;childFocused=true;closed=true;expect(getFocusedDocument(main)).toBe(main);
    closed=false;unregister();expect(getFocusedDocument(main)).toBe(main);
  });
  it("keeps a document registered until the final owner releases it and removes closed windows", () => {
    vi.stubGlobal("document", { querySelector: () => null });
    const node = {}, owner = { querySelector: () => node } as unknown as Document;
    const first = registerDocument(owner), second = registerDocument(owner);
    expect(findInDocuments("block")).toBe(node); first(); first();
    expect(findInDocuments("block")).toBe(node); second(); expect(findInDocuments("block")).toBeNull();
  });
  it("notifies document-bound widgets exactly once per adoption without remounting other panels", () => {
    const initial = {}, popout = {}, element = { ownerDocument: initial } as HTMLElement, changed = vi.fn();
    const stop = observeElementDocument(element, changed);
    const panel = { contains: (candidate: HTMLElement) => candidate === element } as HTMLElement;
    refreshOwnerDocuments(panel); expect(changed).not.toHaveBeenCalled();
    Object.assign(element, { ownerDocument: popout }); refreshOwnerDocuments(panel); refreshOwnerDocuments(panel);
    expect(changed).toHaveBeenCalledOnce();
    Object.assign(element, { ownerDocument: initial }); refreshOwnerDocuments(panel); expect(changed).toHaveBeenCalledTimes(2);
    stop(); Object.assign(element, { ownerDocument: popout }); refreshOwnerDocuments(panel); expect(changed).toHaveBeenCalledTimes(2);
  });
  it("copies light theme, font preferences and custom CSS variables, removing obsolete attributes", () => {
    const attributes = new Map([["data-theme", "dark"], ["dir", "rtl"]]);
    const source = { documentElement: { getAttribute: (key: string) => ({ "data-theme": "light", lang: "en-US" } as Record<string, string>)[key] ?? null, style: { cssText: "font-family: Ubuntu; font-size: 15px; --editor-font: Consolas;" } } } as unknown as Document;
    const target = { documentElement: { setAttribute: (key: string, value: string) => attributes.set(key, value), removeAttribute: (key: string) => attributes.delete(key), style: { cssText: "" } }, body: { style: {} } } as unknown as Document;
    copyRootPresentation(source, target);
    expect(attributes.get("data-theme")).toBe("light"); expect(attributes.get("lang")).toBe("en-US"); expect(attributes.has("dir")).toBe(false);
    expect(target.documentElement.style.cssText).toBe(source.documentElement.style.cssText); expect(target.body.style.minWidth).toBe("0");
  });
  it("attaches keyboard listeners once and cleans them on redock, close and owner disposal", () => {
    const cleanup = vi.fn(), attach = vi.fn(() => cleanup), bindings = new PopoutBindings(attach);
    const first = {} as Window, second = {} as Window;
    bindings.add(first); bindings.add(first); expect(attach).toHaveBeenCalledTimes(1);
    bindings.update([second]); expect(cleanup).toHaveBeenCalledTimes(1); expect(attach).toHaveBeenCalledTimes(2);
    bindings.remove(second); bindings.remove(second); expect(cleanup).toHaveBeenCalledTimes(2);
    bindings.add(first); bindings.dispose(); bindings.dispose(); expect(cleanup).toHaveBeenCalledTimes(3);
  });
  it("loads styles for a lazy panel into already-open windows without duplicating asset links",()=>{
    const links=[{href:"http://app/index.css"}],source={head:{querySelectorAll:()=>[{href:"http://app/index.css"},{href:"http://app/PyniaPanel.css"}]}} as unknown as Document;
    const target={head:{querySelectorAll:()=>links,appendChild:(link:{href:string})=>links.push(link)},createElement:()=>({})} as unknown as Document;
    copyLazyStylesheets(source,target);copyLazyStylesheets(source,target);
    expect(links.map(link=>link.href)).toEqual(["http://app/index.css","http://app/PyniaPanel.css"]);
  });
});
