import {afterEach,describe,expect,it,vi} from "vitest";
import {captureEditorViewState,restoreEditorViewState,subscribeEditorViewStates,takeRestoredEditorViewState,consumePendingFocus,disposeModel,focusEditor,forceAutocomplete,insertInEditor,models,pendingInsertions,selectedCode,setCompletionContext,contexts,contextVersions,editorPreferences,revealEditorBlock,consumeManualSuggestions,triggerLocalSuggestions,getCompletionContext,setCompletionContextResolver,completionGates,inlineGates,diagnosticRefreshers,revealEditorRange,takePendingReveal} from "./editorRegistry";
import {registerDocument} from "./documentWindows";

afterEach(()=>{models.clear();pendingInsertions.clear();contexts.clear();contextVersions.clear();completionGates.clear();inlineGates.clear();diagnosticRefreshers.clear();editorPreferences.clear();vi.unstubAllGlobals();});
describe("Editor focus across viewport virtualization",()=>{
  it("reveals a diagnostic range in a live editor without changing its code",()=>{
    vi.stubGlobal("document",{querySelector:()=>null});vi.stubGlobal("CSS",{escape:(text:string)=>text});
    const editor={focus:vi.fn(),setSelection:vi.fn(),revealRangeInCenter:vi.fn()},range={startLineNumber:8,startColumn:3,endLineNumber:8,endColumn:5};
    models.set("diagnostic-live",{editor} as never);revealEditorRange("diagnostic-live",range);
    expect(editor.focus).toHaveBeenCalledOnce();expect(editor.setSelection).toHaveBeenCalledWith(range);expect(editor.revealRangeInCenter).toHaveBeenCalledWith(range);expect(takePendingReveal("diagnostic-live")).toBeUndefined();
  });
  it("queues an offscreen diagnostic range until the editor mounts",()=>{
    vi.stubGlobal("document",{querySelector:()=>null});vi.stubGlobal("CSS",{escape:(text:string)=>text});
    const range={startLineNumber:12,startColumn:2,endLineNumber:12,endColumn:9};revealEditorRange("diagnostic-later",range);
    expect(consumePendingFocus("diagnostic-later")).toBe(true);expect(takePendingReveal("diagnostic-later")).toEqual(range);expect(takePendingReveal("diagnostic-later")).toBeUndefined();disposeModel("diagnostic-later");
  });
  it("clears Monaco's persistent marker owner before disposing a datapyn URI and drops deferred ranges",()=>{
    vi.stubGlobal("document",{querySelector:()=>null});vi.stubGlobal("CSS",{escape:(text:string)=>text});
    const calls:string[]=[];models.set("diagnostic-close",{model:{dispose:()=>calls.push("dispose")},clearMarkers:()=>calls.push("clear")} as never);
    revealEditorRange("diagnostic-close",{startLineNumber:1,startColumn:1,endLineNumber:1,endColumn:2});disposeModel("diagnostic-close");
    expect(calls).toEqual(["clear","dispose"]);expect(takePendingReveal("diagnostic-close")).toBeUndefined();expect(models.has("diagnostic-close")).toBe(false);
  });
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
  it("reads the live selection after toolbar blur instead of an older saved range",()=>{
    const selection={isEmpty:()=>false,startLineNumber:2,startColumn:1,endLineNumber:3,endColumn:8};
    const read=vi.fn(()=>"  selected = 1\r\nselected");
    models.set("blurred",{model:{isDisposed:()=>false,getValueInRange:read},editor:{getSelection:()=>selection,hasTextFocus:()=>false},viewState:{cursorState:[{selectionStart:{lineNumber:1,column:1},position:{lineNumber:1,column:5}}]}} as never);
    expect(selectedCode("blurred","never execute this")).toBe("  selected = 1\r\nselected");expect(read).toHaveBeenCalledWith(selection);
  });
  it("does not revive an old saved selection when the live cursor has collapsed",()=>{
    const read=vi.fn();models.set("collapsed",{model:{isDisposed:()=>false,getValueInRange:read},editor:{getSelection:()=>({isEmpty:()=>true})},viewState:{cursorState:[{selectionStart:{lineNumber:1,column:1},position:{lineNumber:1,column:5}}]}} as never);
    expect(selectedCode("collapsed","full code")).toBeUndefined();expect(read).not.toHaveBeenCalled();
  });
  it("preserves a live whitespace-only selection rather than treating it as no selection",()=>{
    const selection={isEmpty:()=>false};models.set("spaces",{model:{isDisposed:()=>false,getValueInRange:()=>" \r\n\t "},editor:{getSelection:()=>selection},viewState:null} as never);
    expect(selectedCode("spaces","never execute this")).toBe(" \r\n\t ");
  });
  it("reads reversed restored selection before the editor mounts without consuming its view state",()=>{
    const state={cursorState:[{selectionStart:{lineNumber:3,column:9},position:{lineNumber:2,column:1}}],viewState:{scrollTop:0,scrollLeft:0},contributionsState:{}};
    restoreEditorViewState("unmounted-selection",state);
    expect(selectedCode("unmounted-selection","before = 1\r\n  selected = '😀'\r\nselected\r\nnever = True")).toBe("  selected = '😀'\r\nselected");
    expect(models.has("unmounted-selection")).toBe(false);expect(takeRestoredEditorViewState("unmounted-selection")).toBe(state);
  });
  it.each(["\n","\r\n","\r"])("preserves %j line endings and whitespace in an unmounted restored range",ending=>{
    const id=`restored-${JSON.stringify(ending)}`;
    restoreEditorViewState(id,{cursorState:[{selectionStart:{lineNumber:2,column:1},position:{lineNumber:3,column:2}}],viewState:{},contributionsState:{}});
    expect(selectedCode(id,`before${ending}   ${ending}\t ${ending}after`)).toBe(`   ${ending}\t`);disposeModel(id);
  });
  it("clamps and rounds restored coordinates to document boundaries as Monaco does",()=>{
    restoreEditorViewState("clamped-selection",{cursorState:[{selectionStart:{lineNumber:-10,column:999},position:{lineNumber:2.9,column:999}}],viewState:{},contributionsState:{}});
    expect(selectedCode("clamped-selection","first\r\nsecond\r\nthird")).toBe("first\r\nsecond");disposeModel("clamped-selection");
    restoreEditorViewState("past-end-selection",{cursorState:[{selectionStart:{lineNumber:1,column:3},position:{lineNumber:999,column:1}}],viewState:{},contributionsState:{}});
    expect(selectedCode("past-end-selection","first\nlast")).toBe("rst\nlast");disposeModel("past-end-selection");
  });
  it("keeps complete Unicode characters when restored endpoints are inside a surrogate pair",()=>{
    restoreEditorViewState("unicode-selection",{cursorState:[{selectionStart:{lineNumber:1,column:3},position:{lineNumber:1,column:5}}],viewState:{},contributionsState:{}});
    expect(selectedCode("unicode-selection","a😀😀z")).toBe("😀😀");disposeModel("unicode-selection");
  });
  it("returns no selection for collapsed, missing or invalid restored cursor metadata",()=>{
    for(const [id,cursorState] of [
      ["empty-restored",[]],
      ["collapsed-restored",[{selectionStart:{lineNumber:2,column:3},position:{lineNumber:2,column:3}}]],
      ["invalid-restored",[{selectionStart:null,position:{lineNumber:1,column:4}}]],
      ["clamped-collapsed-restored",[{selectionStart:{lineNumber:50,column:1},position:{lineNumber:60,column:1}}]],
    ] as const){restoreEditorViewState(id,{cursorState,viewState:{},contributionsState:{}});expect(selectedCode(id,"first\nlast")).toBeUndefined();disposeModel(id);}
    expect(selectedCode("missing-restored","full code")).toBeUndefined();
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
  it("keeps Ctrl+Space/manual suggestions available when automatic completion is disabled",()=>{
    const editor={trigger:vi.fn()};models.set("manual",{editor} as never);editorPreferences.set("manual",{autocomplete:false});
    triggerLocalSuggestions("manual");expect(editor.trigger).toHaveBeenCalledWith("datapyn","editor.action.triggerSuggest",{});
    expect(consumeManualSuggestions("manual")).toBe(true);expect(consumeManualSuggestions("manual")).toBe(false);
  });
  it("refreshes an already visible empty/suggestion widget through the controller instead of its disabled action",()=>{
    const controller={triggerSuggest:vi.fn()},editor={getContribution:vi.fn(()=>controller),trigger:vi.fn()};models.set("visible-widget",{editor} as never);
    triggerLocalSuggestions("visible-widget");expect(editor.getContribution).toHaveBeenCalledWith("editor.contrib.suggestController");expect(controller.triggerSuggest).toHaveBeenCalledOnce();expect(editor.trigger).not.toHaveBeenCalled();expect(consumeManualSuggestions("visible-widget")).toBe(true);
  });
  it("closes the existing widget before triggering suggestions if an editor exposes no controller",()=>{
    const editor={getContribution:vi.fn(()=>undefined),trigger:vi.fn()};models.set("fallback-widget",{editor} as never);triggerLocalSuggestions("fallback-widget");
    expect(editor.trigger.mock.calls).toEqual([["datapyn","hideSuggestWidget",{}],["datapyn","editor.action.triggerSuggest",{}]]);
  });
  it("cancels pending local enrichment before forcing AI so the dropdown cannot steal Tab",()=>{
    const editor={focus:vi.fn(),trigger:vi.fn()},cancel=vi.fn();const record={editor,completionQuery:{version:1,line:1,column:1}};
    models.set("ai-race",record as never);completionGates.set("ai-race",{cancel} as never);editorPreferences.set("ai-race",{aiAutocomplete:true});
    forceAutocomplete("ai-race");expect(cancel).toHaveBeenCalledOnce();expect(record.completionQuery).toBeUndefined();expect(models.get("ai-race")?.completionIntent).toBe(1);
  });
  it("compares enriched metadata and sibling source semantically without cancelling every React update",()=>{
    const context={variables:[{name:"df",type:"DataFrame",columns:["name"]}],tables:["main.sales"],siblings:[{name:"example",code:"x = 1",language:"python" as const}],schemaVersion:1,namespaceVersion:2};
    setCompletionContext("metadata",context);const version=contextVersions.get("metadata");
    setCompletionContext("metadata",{...context,variables:[{...context.variables[0],columns:["name"]}],siblings:[{...context.siblings[0]}]});expect(contextVersions.get("metadata")).toBe(version);
    setCompletionContext("metadata",{...context,variables:[{...context.variables[0],columns:["other"]}]});expect(contextVersions.get("metadata")).toBe(version!+1);
    setCompletionContext("metadata",{...context,siblings:[{...context.siblings[0],code:"x = 2"}]});expect(contextVersions.get("metadata")).toBe(version!+2);
  });
  it("resolves the requesting block's context lazily and releases the callback on profile disposal",()=>{
    const context={variables:[],tables:["owned_table"],sessionId:"owned-session"};const resolve=vi.fn((id:string)=>id==="owned"?context:undefined),release=setCompletionContextResolver(resolve);
    expect(getCompletionContext("owned")).toBe(context);expect(resolve).toHaveBeenCalledWith("owned");expect(getCompletionContext("other")).toBeUndefined();
    release();expect(getCompletionContext("owned")).toBe(context);expect(getCompletionContext("other")).toBeUndefined();
  });
  it("does not reschedule a diagnostic or suggestion request when that request lazily reads newer context",()=>{
    let revision=1;const refresh=vi.fn(),invalidate=vi.fn(),clearMarkers=vi.fn();diagnosticRefreshers.set("lazy",refresh);completionGates.set("lazy",{invalidate} as never);models.set("lazy",{clearMarkers} as never);
    const release=setCompletionContextResolver(()=>({variables:[],tables:[],sessionId:"s",namespaceVersion:revision}));
    expect(getCompletionContext("lazy")?.namespaceVersion).toBe(1);revision=2;expect(getCompletionContext("lazy")?.namespaceVersion).toBe(2);
    expect(refresh).not.toHaveBeenCalled();expect(invalidate).toHaveBeenCalledTimes(2);
    setCompletionContext("lazy",{variables:[],tables:[],sessionId:"s",namespaceVersion:3});expect(refresh).toHaveBeenCalledOnce();expect(clearMarkers).not.toHaveBeenCalled();release();
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
