import { memo, useEffect, useRef } from "react";
import * as monaco from "monaco-editor/editor/editor.api.js";
import "monaco-editor/languages/definitions/sql/register.js";
import "monaco-editor/languages/definitions/python/register.js";
import "monaco-editor/editor/browser/coreCommands.js";
import "monaco-editor/editor/contrib/find/browser/findController.js";
import "monaco-editor/editor/contrib/comment/browser/comment.js";
import "monaco-editor/editor/contrib/clipboard/browser/clipboard.js";
import "monaco-editor/editor/contrib/suggest/browser/suggestController.js";
import "monaco-editor/editor/contrib/snippet/browser/snippetController2.js";
import "monaco-editor/editor/contrib/linesOperations/browser/linesOperations.js";
import "monaco-editor/editor/contrib/wordOperations/browser/wordOperations.js";
import "monaco-editor/editor/contrib/multicursor/browser/multicursor.js";
import "monaco-editor/editor/contrib/folding/browser/folding.js";
import "monaco-editor/editor/contrib/contextmenu/browser/contextmenu.js";
import "monaco-editor/editor/contrib/bracketMatching/browser/bracketMatching.js";
import "monaco-editor/editor/contrib/dropOrPasteInto/browser/copyPasteContribution.js";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import type { Language } from "./runtime";

(globalThis as typeof globalThis & { MonacoEnvironment: monaco.Environment }).MonacoEnvironment = { getWorker: () => new EditorWorker() };
monaco.editor.defineTheme("datapyn", {
  base: "vs-dark", inherit: true,
  rules: [{ token: "keyword", foreground: "8eaeff" }, { token: "string", foreground: "80c9a0" },
    { token: "number", foreground: "e7b775" }, { token: "comment", foreground: "657791" }],
  colors: { "editor.background": "#0e1522", "editor.foreground": "#dce5f3", "editorLineNumber.foreground": "#4b5d77",
    "editorLineNumber.activeForeground": "#a3b4cb", "editor.lineHighlightBackground": "#141e30", "editor.selectionBackground": "#284785",
    "editorCursor.foreground": "#80a3ff", "editorIndentGuide.background1": "#1c2940", "editorWidget.background": "#161f30" },
});

interface ModelRecord { model: monaco.editor.ITextModel; viewState: monaco.editor.ICodeEditorViewState | null; editor?: monaco.editor.IStandaloneCodeEditor }
const models = new Map<string, ModelRecord>();
const contexts = new Map<string, { variables: Array<{ name: string; type: string }>; tables: string[] }>();
export function setCompletionContext(blockId: string, context: { variables: Array<{ name: string; type: string }>; tables: string[] }) { contexts.set(blockId, context); }
for (const language of ["sql", "python"]) monaco.languages.registerCompletionItemProvider(language, {
  provideCompletionItems(model, position) {
    const context = contexts.get(model.uri.path.split("/").at(-1) ?? "");
    const word = model.getWordUntilPosition(position), range = { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn };
    const entries = language === "python" ? context?.variables.map((variable) => ({ label: variable.name, kind: monaco.languages.CompletionItemKind.Variable, detail: variable.type })) : context?.tables.map((table) => ({ label: table, kind: monaco.languages.CompletionItemKind.Class, detail: "Tabela da conexão" }));
    return { suggestions: (entries ?? []).map((entry) => ({ ...entry, insertText: entry.label, range })) };
  },
});

export function selectedCode(blockId: string): string | undefined {
  const record = models.get(blockId), selection = record?.editor?.getSelection();
  if (!record || !selection || selection.isEmpty()) return undefined;
  return record.model.getValueInRange(selection);
}
export function focusEditor(blockId: string) { models.get(blockId)?.editor?.focus(); }
export function insertInEditor(blockId: string, text: string) {
  const editor = models.get(blockId)?.editor; if (!editor) return;
  const selection = editor.getSelection(); if (!selection) return;
  editor.executeEdits("datapyn-insert", [{ range: selection, text, forceMoveMarkers: true }]); editor.focus();
}
export function disposeModel(blockId: string) { const record = models.get(blockId); record?.model.dispose(); models.delete(blockId); contexts.delete(blockId); }

interface Props { id: string; code: string; language: Language; height: number; onChange: (code: string) => void; onFocus: () => void }

/** Editor lifetime and model lifetime differ: switching tabs preserves undo and cursor. */
export const MonacoBlock = memo(function MonacoBlock({ id, code, language, height, onChange, onFocus }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onChange, onFocus }); callbacks.current = { onChange, onFocus };
  useEffect(() => {
    if (!container.current) return;
    let record = models.get(id);
    if (!record) {
      record = { model: monaco.editor.createModel(code, language, monaco.Uri.parse(`datapyn://blocks/${id}`)), viewState: null };
      models.set(id, record);
    }
    const editor = monaco.editor.create(container.current, {
      model: record.model, theme: "datapyn", fontFamily: "Ubuntu Mono, Consolas, monospace", fontSize: 14,
      lineHeight: 22, minimap: { enabled: false }, automaticLayout: true,
      scrollBeyondLastLine: false, overviewRulerLanes: 0, hideCursorInOverviewRuler: true,
      lineNumbersMinChars: 3, folding: true, renderLineHighlight: "line", wordWrap: "off",
      padding: { top: 12, bottom: 12 }, smoothScrolling: false,
      scrollbar: { verticalScrollbarSize: 9, horizontalScrollbarSize: 9 },
      bracketPairColorization: { enabled: true }, tabSize: 4,
    });
    record.editor = editor;
    if (record.viewState) editor.restoreViewState(record.viewState);
    const changed = editor.onDidChangeModelContent(() => callbacks.current.onChange(record.model.getValue()));
    const focused = editor.onDidFocusEditorText(() => callbacks.current.onFocus());
    return () => { changed.dispose(); focused.dispose(); record.viewState = editor.saveViewState(); record.editor = undefined; editor.dispose(); };
    // Creating a new widget for a changed code prop discards undo history.
    // The separate effect below synchronizes external edits into the stable model.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  useEffect(() => {
    const record = models.get(id); if (!record) return;
    if (record.model.getLanguageId() !== language) monaco.editor.setModelLanguage(record.model, language);
    if (record.model.getValue() !== code) {
      record.model.pushStackElement();
      record.model.pushEditOperations([], [{ range: record.model.getFullModelRange(), text: code }], () => null);
      record.model.pushStackElement();
    }
  }, [id, code, language]);
  return <div className="monaco-block" ref={container} style={{ height }} aria-label={`Editor ${language}`} />;
});
