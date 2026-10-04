import type * as monaco from "monaco-editor/editor/editor.api.js";
import type { CompletionContext, InlineRequestGate, LanguageRequestGate } from "./editorLanguage";
import { findInDocuments } from "./documentWindows";

export interface EditorPreferences { fontFamily?: string; fontSize?: number; wordWrap?: boolean; minimap?: boolean; lineNumbers?: boolean; tabSize?: number; readOnly?: boolean; autocomplete?: boolean; aiAutocomplete?: boolean;theme?:"dark"|"light"|"system" }
export interface ModelRecord { model: monaco.editor.ITextModel; viewState: monaco.editor.ICodeEditorViewState | null; editor?: monaco.editor.IStandaloneCodeEditor; container?: HTMLElement; clearMarkers?: () => void; completionIntent?: number; completionNavigation?: number; completionQuery?: { version: number; line: number; column: number; intent?: number; navigation?: number } }
export const models = new Map<string, ModelRecord>();
export const contexts = new Map<string, CompletionContext>();
let completionContextResolver: ((blockId:string)=>CompletionContext|undefined) | undefined;
export function setCompletionContextResolver(resolve:(blockId:string)=>CompletionContext|undefined) { completionContextResolver=resolve;return()=>{if(completionContextResolver===resolve)completionContextResolver=undefined;}; }
export function getCompletionContext(blockId:string):CompletionContext|undefined {
  // A request reading its context must not schedule itself again. External
  // namespace/schema events use the notifying setter below to refresh live UI.
  if(completionContextResolver){const context=completionContextResolver(blockId);if(context)setCompletionContext(blockId,context,false);else return undefined;}
  return contexts.get(blockId);
}
export const completionGates = new Map<string, LanguageRequestGate>();
export const inlineGates = new Map<string, InlineRequestGate>();
export const contextVersions = new Map<string, number>();
export const diagnosticRefreshers = new Map<string, () => void>();
export const editorPreferences = new Map<string, EditorPreferences | undefined>();
export const pendingInsertions = new Map<string, string[]>();
const manualSuggestions = new Set<string>();
interface EditorSuggestionController extends monaco.editor.IEditorContribution { triggerSuggest(onlyFrom?:Set<monaco.languages.CompletionItemProvider>,auto?:boolean,noFilter?:boolean):void }
export function consumeManualSuggestions(id:string) { const requested = manualSuggestions.has(id); manualSuggestions.delete(id); return requested; }
export function triggerLocalSuggestions(id:string) {
  const editor = models.get(id)?.editor; if (!editor) return;
  manualSuggestions.add(id);
  const controller=editor.getContribution?.<EditorSuggestionController>("editor.contrib.suggestController");
  // Monaco's action is disabled whenever its widget is visible (including
  // "No suggestions"). The controller can refresh that widget with new data.
  if(controller?.triggerSuggest)controller.triggerSuggest();
  else {editor.trigger("datapyn", "hideSuggestWidget", {});editor.trigger("datapyn", "editor.action.triggerSuggest", {});}
}
const restoredViews=new Map<string,monaco.editor.ICodeEditorViewState>();
const viewStateListeners=new Set<(blockId:string,state:monaco.editor.ICodeEditorViewState)=>void>();
export function subscribeEditorViewStates(listener:(blockId:string,state:monaco.editor.ICodeEditorViewState)=>void){viewStateListeners.add(listener);return()=>viewStateListeners.delete(listener);}
export function restoreEditorViewState(blockId:string,input:unknown):boolean {
  if(!input||typeof input!=="object")return false;
  const state=input as Partial<monaco.editor.ICodeEditorViewState>;
  if(!Array.isArray(state.cursorState)||!state.viewState||typeof state.viewState!=="object"||!state.contributionsState||typeof state.contributionsState!=="object")return false;
  restoredViews.set(blockId,state as monaco.editor.ICodeEditorViewState);return true;
}
export function takeRestoredEditorViewState(blockId:string):monaco.editor.ICodeEditorViewState|null {const state=restoredViews.get(blockId);restoredViews.delete(blockId);return state??null;}
export function captureEditorViewState(blockId:string):void {
  const record=models.get(blockId),state=record?.editor?.saveViewState?.()??record?.viewState;if(!record||!state)return;
  // Small editor metadata only: never serialize the model's code or undo stack.
  const value=JSON.stringify(state);if(value===JSON.stringify(record.viewState))return;
  record.viewState=state;viewStateListeners.forEach(listener=>listener(blockId,state));
}
export function flushEditorViewStates():void {models.forEach((_record,id)=>captureEditorViewState(id));}
let pendingFocus: string | undefined;
let focusedEditor: string | undefined;
export function markEditorFocused(id: string): void { focusedEditor = id; }
export function wasEditorFocused(id: string): boolean { return focusedEditor === id; }
export function consumePendingFocus(id: string): boolean { if (pendingFocus !== id) return false; pendingFocus = undefined; return true; }
function shallowArray<T>(a:readonly T[],b:readonly T[]){return a===b||(a.length===b.length&&a.every((value,index)=>value===b[index]));}
function sameVariables(a:CompletionContext["variables"],b:CompletionContext["variables"]) { return a===b||(a.length===b.length&&a.every((value,index)=>{const next=b[index];return value===next||(value.name===next.name&&value.type===next.type&&value.module===next.module&&shallowArray(value.columns??[],next.columns??[]));})); }
function sameSiblings(a:CompletionContext["siblings"],b:CompletionContext["siblings"]) { return a===b||((a?.length??0)===(b?.length??0)&&(a??[]).every((value,index)=>{const next=b![index];return value===next||(value.name===next.name&&value.code===next.code&&value.language===next.language&&value.cellType===next.cellType);})); }
export function setCompletionContext(blockId: string, context: CompletionContext, notify=true) {
  const previous=contexts.get(blockId);
  if(previous===context||(previous&&previous.sessionId===context.sessionId&&previous.connectionId===context.connectionId&&previous.database===context.database&&previous.schema===context.schema&&previous.globalImports===context.globalImports&&previous.preamble===context.preamble&&previous.schemaVersion===context.schemaVersion&&previous.namespaceVersion===context.namespaceVersion&&previous.schemaSnapshot===context.schemaSnapshot&&sameVariables(previous.variables,context.variables)&&shallowArray(previous.tables,context.tables)&&sameSiblings(previous.siblings,context.siblings)))return;
  contexts.set(blockId, context); contextVersions.set(blockId, (contextVersions.get(blockId) ?? 0) + 1);
  completionGates.get(blockId)?.invalidate(); inlineGates.get(blockId)?.cancel(); models.get(blockId)?.clearMarkers?.();
  if(!notify)return;
  diagnosticRefreshers.get(blockId)?.();
  const record = models.get(blockId), query = record?.completionQuery, editor = record?.editor, position = editor?.getPosition?.();
  if (query && editor?.hasTextFocus?.() && record?.model.getVersionId() === query.version && query.intent === record.completionIntent && query.navigation === record.completionNavigation && position?.lineNumber === query.line && position.column === query.column) queueMicrotask(()=>{
    const current=models.get(blockId),cursor=current?.editor?.getPosition?.();
    if(current===record&&current.editor===editor&&editor.hasTextFocus()&&current.completionQuery===query&&current.model.getVersionId()===query.version&&query.intent===current.completionIntent&&query.navigation===current.completionNavigation&&cursor?.lineNumber===query.line&&cursor.column===query.column)triggerLocalSuggestions(blockId);
  });
}
export function selectedCode(blockId: string): string | undefined {
  const record = models.get(blockId); if (!record || record.model.isDisposed()) return;
  const selection = record.editor?.getSelection();
  if (selection) return selection.isEmpty() ? undefined : record.model.getValueInRange(selection);
  const cursor = record.viewState?.cursorState[0]; if (!cursor) return;
  const a = cursor.selectionStart, b = cursor.position;
  if (a.lineNumber === b.lineNumber && a.column === b.column) return;
  const before = a.lineNumber < b.lineNumber || (a.lineNumber === b.lineNumber && a.column < b.column);
  return record.model.getValueInRange({ startLineNumber: before ? a.lineNumber : b.lineNumber, startColumn: before ? a.column : b.column, endLineNumber: before ? b.lineNumber : a.lineNumber, endColumn: before ? b.column : a.column });
}
/** Reveal a virtualized block inside its own panel, keeping desktop/dock chrome still. */
export function revealEditorBlock(element:HTMLElement):void {
  const viewport=element.closest<HTMLElement>(".editor-area");
  if(!viewport || viewport.clientHeight<=0)return;
  const block=element.getBoundingClientRect(),bounds=viewport.getBoundingClientRect();
  const top=bounds.top+viewport.clientTop,bottom=top+viewport.clientHeight;
  // A tall block already spanning the viewport is visible; preserve its position.
  const delta=block.top<top && block.bottom>bottom ? 0 : block.top<top ? block.top-top : block.bottom>bottom ? block.bottom-bottom : 0;
  if(delta)viewport.scrollTop=Math.max(0,Math.min(viewport.scrollHeight-viewport.clientHeight,viewport.scrollTop+delta));
}
export function focusEditor(blockId: string) {
  pendingFocus = blockId;
  focusedEditor = blockId;
  const record = models.get(blockId), selector = `[data-block-id="${CSS.escape(blockId)}"]`;
  const element = findInDocuments(selector, record?.container?.ownerDocument);
  if(element)revealEditorBlock(element);
  const editor = record?.editor;
  const view = element?.ownerDocument?.defaultView;
  if (view && view !== window) view.focus();
  if (editor) { editor.focus(); pendingFocus = undefined; }
}
export function editorAction(blockId: string, action: string) { return models.get(blockId)?.editor?.getAction(action)?.run(); }
export function getRegisteredEditor(blockId: string) { return models.get(blockId)?.editor; }
export async function formatEditor(blockId: string) { await editorAction(blockId, "editor.action.formatDocument"); focusEditor(blockId); }
export function forceAutocomplete(blockId: string) {
  const editor = models.get(blockId)?.editor; if (!editor) return;
  editor.focus();
  if (editorPreferences.get(blockId)?.aiAutocomplete) {
    const record = models.get(blockId); if(record){record.completionQuery=undefined;record.completionIntent=(record.completionIntent??0)+1;}
    completionGates.get(blockId)?.cancel();
    // A visible suggestion list takes precedence over accepting ghost text with Tab.
    editor.trigger("datapyn", "hideSuggestWidget", {});
    editor.trigger("datapyn", "editor.action.inlineSuggest.trigger", { explicit: true });
  } else triggerLocalSuggestions(blockId);
}
export function transformEditorSelection(blockId: string, transform: "upper" | "lower" | "duplicate" | "deleteLine") {
  const editor = models.get(blockId)?.editor; if (!editor) return;
  if (transform === "duplicate" || transform === "deleteLine") { editor.trigger("datapyn", transform === "duplicate" ? "editor.action.copyLinesDownAction" : "editor.action.deleteLines", {}); editor.focus(); return; }
  const selection = editor.getSelection(), model = editor.getModel(); if (!selection || !model) return;
  const range = selection.isEmpty() ? { startLineNumber: selection.positionLineNumber, startColumn: 1, endLineNumber: selection.positionLineNumber, endColumn: model.getLineMaxColumn(selection.positionLineNumber) } : selection;
  const text = model.getValueInRange(range); editor.pushUndoStop(); editor.executeEdits("datapyn-case", [{ range, text: transform === "upper" ? text.toLocaleUpperCase() : text.toLocaleLowerCase() }]); editor.pushUndoStop(); editor.focus();
}
export function insertInEditor(blockId: string, text: string) {
  const record = models.get(blockId);
  if (record?.editor) { const selection = record.editor.getSelection(); if (!selection) return; record.editor.executeEdits("datapyn-insert", [{ range: selection, text, forceMoveMarkers: true }]); record.editor.focus(); }
  else { pendingInsertions.set(blockId, [...(pendingInsertions.get(blockId) ?? []), text]); focusEditor(blockId); }
}
export function replaceEditorCode(blockId: string, code: string) {
  const record = models.get(blockId); if (!record || record.model.isDisposed() || record.model.getValue() === code) return;
  record.model.pushStackElement(); record.model.pushEditOperations(record.editor?.getSelections() ?? [], [{ range: record.model.getFullModelRange(), text: code }], () => record.editor?.getSelections() ?? null); record.model.pushStackElement();
}
export function disposeModel(blockId: string) {
  manualSuggestions.delete(blockId);
  restoredViews.delete(blockId);
  models.get(blockId)?.model.dispose(); models.delete(blockId); contexts.delete(blockId); completionGates.get(blockId)?.invalidate(); completionGates.delete(blockId); inlineGates.get(blockId)?.cancel();inlineGates.delete(blockId);contextVersions.delete(blockId); diagnosticRefreshers.delete(blockId); editorPreferences.delete(blockId); pendingInsertions.delete(blockId); if (pendingFocus === blockId) pendingFocus = undefined;
  if (focusedEditor === blockId) focusedEditor = undefined;
}
