import type * as monaco from "monaco-editor/editor/editor.api.js";
import type { CompletionContext, LanguageRequestGate } from "./editorLanguage";
import { findInDocuments } from "./documentWindows";

export interface EditorPreferences { fontFamily?: string; fontSize?: number; wordWrap?: boolean; minimap?: boolean; lineNumbers?: boolean; tabSize?: number; readOnly?: boolean; autocomplete?: boolean; aiAutocomplete?: boolean;theme?:"dark"|"light"|"system" }
export interface ModelRecord { model: monaco.editor.ITextModel; viewState: monaco.editor.ICodeEditorViewState | null; editor?: monaco.editor.IStandaloneCodeEditor; container?: HTMLElement; clearMarkers?: () => void }
export const models = new Map<string, ModelRecord>();
export const contexts = new Map<string, CompletionContext>();
export const completionGates = new Map<string, LanguageRequestGate>();
export const contextVersions = new Map<string, number>();
export const diagnosticRefreshers = new Map<string, () => void>();
export const editorPreferences = new Map<string, EditorPreferences | undefined>();
export const pendingInsertions = new Map<string, string[]>();
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
export function setCompletionContext(blockId: string, context: CompletionContext) {
  const previous=contexts.get(blockId);
  if(previous===context||(previous&&previous.sessionId===context.sessionId&&previous.connectionId===context.connectionId&&previous.database===context.database&&previous.schema===context.schema&&previous.globalImports===context.globalImports&&previous.preamble===context.preamble&&shallowArray(previous.variables,context.variables)&&shallowArray(previous.tables,context.tables)))return;
  contexts.set(blockId, context); contextVersions.set(blockId, (contextVersions.get(blockId) ?? 0) + 1);
  completionGates.get(blockId)?.invalidate(); models.get(blockId)?.clearMarkers?.(); diagnosticRefreshers.get(blockId)?.();
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
    // A visible suggestion list takes precedence over accepting ghost text with Tab.
    editor.trigger("datapyn", "hideSuggestWidget", {});
    editor.trigger("datapyn", "editor.action.inlineSuggest.trigger", { explicit: true });
  } else editor.trigger("datapyn", "editor.action.triggerSuggest", {});
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
  restoredViews.delete(blockId);
  models.get(blockId)?.model.dispose(); models.delete(blockId); contexts.delete(blockId); completionGates.get(blockId)?.invalidate(); completionGates.delete(blockId); contextVersions.delete(blockId); diagnosticRefreshers.delete(blockId); editorPreferences.delete(blockId); pendingInsertions.delete(blockId); if (pendingFocus === blockId) pendingFocus = undefined;
  if (focusedEditor === blockId) focusedEditor = undefined;
}
