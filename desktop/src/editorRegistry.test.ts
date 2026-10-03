import {afterEach,describe,expect,it,vi} from "vitest";
import {captureEditorViewState,restoreEditorViewState,subscribeEditorViewStates,takeRestoredEditorViewState,consumePendingFocus,disposeModel,focusEditor,forceAutocomplete,insertInEditor,models,pendingInsertions,selectedCode,setCompletionContext,contexts,contextVersions,editorPreferences,revealEditorBlock} from "./editorRegistry";
import {registerDocument} from "./documentWindows";

afterEach(()=>{models.clear();pendingInsertions.clear();contexts.clear();contextVersions.clear();editorPreferences.clear();vi.unstubAllGlobals();});
describe("Editor focus across viewport virtualization",()=>{
  it("restores private cursor/scroll metadata and emits only changed view states without reading code",()=>{
    const state={cursorState:[],viewState:{scrollTop:30,scrollLeft:0},contributionsState:{}};
    expect(restoreEditorViewState("restored",state)).toBe(true);expect(takeRestoredEditorViewState("restored")).toBe(state);expect(takeRestoredEditorViewState("restored")).toBeNull();
    expect(restoreEditorViewState("invalid",{viewState:{}})).toBe(false);
    const listener=vi.fn(),unsubscribe=subscribeEditorViewStates(listener);
    models.set("current",{model:{getValue:()=>{throw new Error("must not read code");}},viewState:null,editor:{saveViewState:()=>({...state})}} as never);
    captureEditorViewState("current");captureEditorViewState("current");expect(listener).toHaveBeenCalledOnce();expect(listener.mock.calls[0]).toEqual(["current",state]);unsubscribe();
  });
  it("scrolls to an unmounted block and consumes focus only when that editor mounts",()=>{
    const scroll=vi.fn(),viewport={scrollTop:0,scrollHeight:1200,clientHeight:300,clientTop:0,getBoundingClientRect:()=>({top:100})};
    const block={scrollIntoView:scroll,closest:()=>viewport,getBoundingClientRect:()=>({top:800,bottom:1000})};
    vi.stubGlobal("document",{querySelector:vi.fn(()=>block)});vi.stubGlobal("CSS",{escape:(text:string)=>text});
    focusEditor("offscreen");expect(viewport.scrollTop).toBe(600);expect(scroll).not.toHaveBeenCalled();
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
    const main={querySelector:()=>null},view={focus:vi.fn()},scroll=vi.fn();
    const viewport={scrollTop:0,scrollHeight:1000,clientHeight:250,clientTop:0,getBoundingClientRect:()=>({top:30})};
    const owner={defaultView:view,querySelector:()=>({scrollIntoView:scroll,ownerDocument:owner,closest:()=>viewport,getBoundingClientRect:()=>({top:700,bottom:900})})} as unknown as Document;
    vi.stubGlobal("document",main);vi.stubGlobal("window",{});vi.stubGlobal("CSS",{escape:(text:string)=>text});
    const release=registerDocument(owner);
    focusEditor("detached");expect(viewport.scrollTop).toBe(620);expect(scroll).not.toHaveBeenCalled();expect(view.focus).toHaveBeenCalledOnce();expect(consumePendingFocus("detached")).toBe(true);
    release();
  });
  it("reveals an earlier block without changing the root or the horizontal panel position",()=>{
    const viewport={scrollTop:400,scrollLeft:20,scrollHeight:1200,clientHeight:300,clientTop:2,getBoundingClientRect:()=>({top:100})};
    const block={closest:()=>viewport,getBoundingClientRect:()=>({top:22,bottom:82}),scrollIntoView:vi.fn()} as unknown as HTMLElement;
    revealEditorBlock(block);expect(viewport.scrollTop).toBe(320);expect(viewport.scrollLeft).toBe(20);expect(block.scrollIntoView).not.toHaveBeenCalled();
  });
  it("keeps an already visible or oversized editor block in place",()=>{
    const viewport={scrollTop:400,scrollHeight:1200,clientHeight:300,clientTop:0,getBoundingClientRect:()=>({top:100})};
    for(const position of [{top:150,bottom:300},{top:50,bottom:700}]){
      revealEditorBlock({closest:()=>viewport,getBoundingClientRect:()=>position} as unknown as HTMLElement);expect(viewport.scrollTop).toBe(400);
    }
  });
  it("leaves detached or not-yet-measured blocks alone until their viewport is ready",()=>{
    const rectangle=vi.fn(()=>({top:700,bottom:900}));
    revealEditorBlock({closest:()=>null,getBoundingClientRect:rectangle} as unknown as HTMLElement);
    revealEditorBlock({closest:()=>({clientHeight:0}),getBoundingClientRect:rectangle} as unknown as HTMLElement);
    expect(rectangle).not.toHaveBeenCalled();
  });
});
