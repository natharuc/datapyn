import {afterEach,describe,expect,it,vi} from "vitest";
import {consumePendingFocus,disposeModel,focusEditor,forceAutocomplete,insertInEditor,models,pendingInsertions,selectedCode,setCompletionContext,contexts,contextVersions,editorPreferences} from "./editorRegistry";
import {registerDocument} from "./documentWindows";

afterEach(()=>{models.clear();pendingInsertions.clear();contexts.clear();contextVersions.clear();editorPreferences.clear();vi.unstubAllGlobals();});
describe("Editor focus across viewport virtualization",()=>{
  it("scrolls to an unmounted block and consumes focus only when that editor mounts",()=>{
    const scroll=vi.fn();vi.stubGlobal("document",{querySelector:vi.fn(()=>({scrollIntoView:scroll}))});vi.stubGlobal("CSS",{escape:(text:string)=>text});
    focusEditor("offscreen");expect(scroll).toHaveBeenCalledWith({block:"nearest"});
    expect(consumePendingFocus("other")).toBe(false);expect(consumePendingFocus("offscreen")).toBe(true);expect(consumePendingFocus("offscreen")).toBe(false);
  });
  it("queues insertions in order until content listeners and the editor are mounted",()=>{
    vi.stubGlobal("document",{querySelector:()=>null});vi.stubGlobal("CSS",{escape:(text:string)=>text});
    insertInEditor("later","SELECT ");insertInEditor("later","* FROM customers");
    expect(pendingInsertions.get("later")).toEqual(["SELECT ","* FROM customers"]);
    disposeModel("later");expect(pendingInsertions.has("later")).toBe(false);expect(consumePendingFocus("later")).toBe(false);
  });
  it("reads a reverse selection saved in an offscreen model without loading Monaco",()=>{
    const read=vi.fn(()=>"selection");models.set("b",{model:{isDisposed:()=>false,getValueInRange:read},viewState:{cursorState:[{selectionStart:{lineNumber:8,column:4},position:{lineNumber:2,column:3}}]}} as never);
    expect(selectedCode("b")).toBe("selection");expect(read).toHaveBeenCalledWith({startLineNumber:2,startColumn:3,endLineNumber:8,endColumn:4});
  });
  it("compares large editor context without serializing code and invalidates only real changes",()=>{
    const variable={name:"frame",type:"DataFrame"},context={variables:[variable],tables:["orders"],sessionId:"s",preamble:"x".repeat(200000)};
    setCompletionContext("b",context);const version=contextVersions.get("b");
    setCompletionContext("b",{...context,variables:[variable],tables:["orders"]});expect(contextVersions.get("b")).toBe(version);
    setCompletionContext("b",{...context,database:"other"});expect(contextVersions.get("b")).toBe(version!+1);
    setCompletionContext("b",{...context,preamble:context.preamble+"\nnew code"});expect(contextVersions.get("b")).toBe(version!+2);
  });
  it("forces ACP ghost completion when enabled, closing local suggestions so Tab accepts the inline result",()=>{
    const editor={focus:vi.fn(),trigger:vi.fn()};models.set("ai",{editor} as never);editorPreferences.set("ai",{aiAutocomplete:true,autocomplete:false});
    forceAutocomplete("ai");expect(editor.focus).toHaveBeenCalledOnce();
    expect(editor.trigger.mock.calls).toEqual([["datapyn","hideSuggestWidget",{}],["datapyn","editor.action.inlineSuggest.trigger",{explicit:true}]]);
  });
  it("keeps normal suggestions when AI is disabled and uses the latest per-block preference",()=>{
    const editor={focus:vi.fn(),trigger:vi.fn()};models.set("local",{editor} as never);editorPreferences.set("local",{aiAutocomplete:false});
    forceAutocomplete("local");expect(editor.trigger).toHaveBeenCalledWith("datapyn","editor.action.triggerSuggest",{});
    editorPreferences.set("local",{aiAutocomplete:true});forceAutocomplete("local");
    expect(editor.trigger).toHaveBeenLastCalledWith("datapyn","editor.action.inlineSuggest.trigger",{explicit:true});
    expect(()=>forceAutocomplete("absent")).not.toThrow();
  });
  it("finds offscreen blocks in their popout document and activates that native window before focus",()=>{
    const main={querySelector:()=>null},view={focus:vi.fn()},scroll=vi.fn(),owner={defaultView:view,querySelector:()=>({scrollIntoView:scroll,ownerDocument:owner})} as unknown as Document;
    vi.stubGlobal("document",main);vi.stubGlobal("window",{});vi.stubGlobal("CSS",{escape:(text:string)=>text});
    const release=registerDocument(owner);
    focusEditor("detached");expect(scroll).toHaveBeenCalledWith({block:"nearest"});expect(view.focus).toHaveBeenCalledOnce();expect(consumePendingFocus("detached")).toBe(true);
    release();
  });
});
