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
import "monaco-editor/editor/contrib/format/browser/formatActions.js";
import "monaco-editor/editor/contrib/hover/browser/hoverContribution.js";
import "monaco-editor/editor/contrib/inlineCompletions/browser/inlineCompletions.contribution.js";
import "monaco-editor/editor/contrib/bracketMatching/browser/bracketMatching.js";
import "monaco-editor/editor/contrib/dropOrPasteInto/browser/copyPasteContribution.js";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import { runtime, type Language } from "./runtime";
import {translate as t,useLocale} from "./i18n";
import { models, contexts, completionGates, contextVersions, diagnosticRefreshers, editorPreferences, pendingInsertions, consumePendingFocus, markEditorFocused, wasEditorFocused, insertInEditor, takeRestoredEditorViewState,captureEditorViewState,type EditorPreferences } from "./editorRegistry";
export { selectedCode, focusEditor, editorAction, getRegisteredEditor, formatEditor, forceAutocomplete, transformEditorSelection, insertInEditor, replaceEditorCode, disposeModel, setCompletionContext } from "./editorRegistry";
export type { EditorPreferences } from "./editorRegistry";
import { LanguageRequestGate, languageParams, mergeCompletions, type LanguageCompletion, type LanguageMarker } from "./editorLanguage";
import { useOwnerDocumentRevision } from "./useOwnerDocument";

(globalThis as typeof globalThis & { MonacoEnvironment: monaco.Environment }).MonacoEnvironment = { getWorker: () => new EditorWorker() };
monaco.editor.defineTheme("datapyn", {
  base: "vs-dark", inherit: true,
  rules: [{ token: "keyword", foreground: "8eaeff" }, { token: "string", foreground: "80c9a0" },
    { token: "number", foreground: "e7b775" }, { token: "comment", foreground: "657791" }],
  colors: { "editor.background": "#0e1522", "editor.foreground": "#dce5f3", "editorLineNumber.foreground": "#4b5d77",
    "editorLineNumber.activeForeground": "#a3b4cb", "editor.lineHighlightBackground": "#141e30", "editor.selectionBackground": "#284785",
    "editorCursor.foreground": "#80a3ff", "editorIndentGuide.background1": "#1c2940", "editorWidget.background": "#161f30" },
});

monaco.editor.defineTheme("datapyn-light",{base:"vs",inherit:true,rules:[{token:"keyword",foreground:"2854c5"},{token:"string",foreground:"187442"},{token:"number",foreground:"a65508"},{token:"comment",foreground:"778497"}],colors:{"editor.background":"#ffffff","editor.foreground":"#243047","editorLineNumber.foreground":"#a6b0c0","editorLineNumber.activeForeground":"#53647e","editor.lineHighlightBackground":"#f6f8fc","editor.selectionBackground":"#d7e4ff","editorCursor.foreground":"#3369ff","editorIndentGuide.background1":"#e8edf5","editorWidget.background":"#f4f7fc"}});
let activeTheme="datapyn";
function applyTheme(preferences?:EditorPreferences,view:Window=window){const name=preferences?.theme==="light"||(preferences?.theme==="system"&&view.matchMedia("(prefers-color-scheme: light)").matches)?"datapyn-light":"datapyn";if(name!==activeTheme){monaco.editor.setTheme(name);activeTheme=name;}}

const completionKinds: Record<string, monaco.languages.CompletionItemKind> = {
  variable: monaco.languages.CompletionItemKind.Variable, table: monaco.languages.CompletionItemKind.Class, class: monaco.languages.CompletionItemKind.Class,
  field: monaco.languages.CompletionItemKind.Field, column: monaco.languages.CompletionItemKind.Field,
  keyword: monaco.languages.CompletionItemKind.Keyword, function: monaco.languages.CompletionItemKind.Function,
  method: monaco.languages.CompletionItemKind.Method, module: monaco.languages.CompletionItemKind.Module,
  property: monaco.languages.CompletionItemKind.Property, snippet: monaco.languages.CompletionItemKind.Snippet,
};
const sqlKeywords = ["SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "BETWEEN", "LIKE", "IS", "NULL", "JOIN", "INNER JOIN", "LEFT JOIN", "ON", "AS", "ORDER BY", "GROUP BY", "HAVING", "LIMIT", "DISTINCT", "INSERT INTO", "VALUES", "UPDATE", "SET", "DELETE", "CREATE TABLE", "DROP TABLE", "ALTER TABLE", "COUNT", "SUM", "AVG", "MIN", "MAX", "CASE", "WHEN", "THEN", "ELSE", "END"];
const pythonKeywords = ["def", "class", "if", "elif", "else", "for", "while", "return", "import", "from", "as", "try", "except", "finally", "with", "lambda", "yield", "True", "False", "None"];
for (const language of ["sql", "python"]) monaco.languages.registerCompletionItemProvider(language, {
  triggerCharacters: [".", ...(language === "sql" ? [" "] : [])],
  async provideCompletionItems(model, position, _trigger, token) {
    const id = model.uri.path.split("/").at(-1) ?? "", context = contexts.get(id);
    if (editorPreferences.get(id)?.autocomplete === false) return { suggestions: [] };
    const word = model.getWordUntilPosition(position), range = { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn };
    const entries: LanguageCompletion[] = language === "python" ? context?.variables.map((variable) => ({ label: variable.name, kind: "variable", detail: variable.type })) ?? [] : context?.tables.map((table) => ({ label: table, kind: "class", detail: t("Tabela da conexão") })) ?? [];
    entries.push(...(language === "sql" ? sqlKeywords : pythonKeywords).map((label) => ({ label, kind: "keyword" })));
    const version = model.getVersionId(), contextVersion = contextVersions.get(id), gate = completionGates.get(id) ?? new LanguageRequestGate(); completionGates.set(id, gate);
    let remote: LanguageCompletion[] = [];
    try {
      remote = await gate.complete(runtime, { ...languageParams(context, { language: language as Language, code: model.getValue(), line: position.lineNumber, column: position.column }), block_id: id }, () => !token.isCancellationRequested && !model.isDisposed() && model.getVersionId() === version && contextVersions.get(id) === contextVersion);
    } catch { /* Offline editing still has keywords and the last known schema. */ }
    if (token.isCancellationRequested || model.isDisposed() || model.getVersionId() !== version || contextVersions.get(id) !== contextVersion) return { suggestions: [] };
    return { suggestions: mergeCompletions(remote, entries).map((entry) => ({ label: entry.label, kind: completionKinds[(entry.kind ?? "variable").toLowerCase()] ?? monaco.languages.CompletionItemKind.Text, detail: entry.detail, documentation: entry.documentation, insertText: entry.insert_text ?? entry.insertText ?? entry.label, insertTextRules: entry.kind === "snippet" ? monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet : undefined, range })) };
  },
});
for (const language of ["sql", "python"]) monaco.languages.registerInlineCompletionsProvider(language, {
  async provideInlineCompletions(model, position, completion, token) {
    const id = model.uri.path.split("/").at(-1) ?? "", context = contexts.get(id);
    if (!editorPreferences.get(id)?.aiAutocomplete || !context?.sessionId) return { items: [] };
    const version = model.getVersionId(), contextVersion = contextVersions.get(id);
    if (completion.triggerKind !== monaco.languages.InlineCompletionTriggerKind.Explicit) await new Promise((resolve) => setTimeout(resolve, 350));
    const valid = () => !token.isCancellationRequested && !model.isDisposed() && model.getVersionId() === version && contextVersions.get(id) === contextVersion;
    if (!valid()) return { items: [] };
    const text = model.getValue(), offset = model.getOffsetAt(position), prefix = text.slice(Math.max(0, offset - 2000), offset), suffix = text.slice(offset, offset + 500);
    const body = `Continue ${language} code at <CURSOR>. Output only raw text to insert, without Markdown fences, explanation or repeating the existing code. Preserve indentation.\nContext: ${JSON.stringify({ variables: context.variables.slice(0, 80), tables: context.tables.slice(0, 80), database: context.database, schema: context.schema }).slice(0, 2000)}\n${prefix}<CURSOR>${suffix}`;
    try {
      const { text: insertText } = await runtime.request<{ text: string }>("pynia.inline", { session_id: context.sessionId, body, timeout: 8, block_id: id });
      if (!valid() || !insertText) return { items: [] };
      return { items: [{ insertText, range: new monaco.Range(position.lineNumber, position.column, position.lineNumber, position.column) }] };
    } catch { return { items: [] }; }
  },
  disposeInlineCompletions() {},
});
for (const language of ["sql", "python"]) monaco.languages.registerDocumentFormattingEditProvider(language, {
  async provideDocumentFormattingEdits(model, options, token) {
    const version = model.getVersionId(), id = model.uri.path.split("/").at(-1) ?? "";
    const { code, error } = await runtime.request<{ code: string; error?: string | null }>("language.format", { ...languageParams(contexts.get(id), { language: language as Language, code: model.getValue() }), options });
    if (error) throw new Error(error);
    return token.isCancellationRequested || model.isDisposed() || version !== model.getVersionId() ? [] : [{ range: model.getFullModelRange(), text: code }];
  },
});

interface Props { id: string; code: string; language: Language; height: number; onChange: (code: string) => void; onFocus: () => void; preferences?: EditorPreferences; onCursor?: (line: number, column: number) => void;onFontSizeChange?:(size:number)=>void;onReady?:(id:string)=>void }

/** Editor lifetime and model lifetime differ: switching tabs preserves undo and cursor. */
export const MonacoBlock = memo(function MonacoBlock({ id, code, language, height, onChange, onFocus, preferences, onCursor,onFontSizeChange,onReady }: Props) {
  useLocale();
  const container = useRef<HTMLDivElement>(null);
  const documentRevision = useOwnerDocumentRevision(container);
  const callbacks = useRef({ onChange, onFocus, onCursor,onFontSizeChange,onReady }); callbacks.current = { onChange, onFocus, onCursor,onFontSizeChange,onReady };
  useEffect(() => {
    if (!container.current) return;
    const host = container.current, view = host.ownerDocument.defaultView ?? window;
    applyTheme(preferences,view);
    let record = models.get(id);
    if (!record) {
      record = { model: monaco.editor.createModel(code, language, monaco.Uri.parse(`datapyn://blocks/${id}`)), viewState: takeRestoredEditorViewState(id) };
      models.set(id, record);
    }
    const editor = monaco.editor.create(host, {
      model: record.model, theme: activeTheme, fontFamily: "'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace", fontSize: 13,
      lineHeight: 22, minimap: { enabled: false }, automaticLayout: true,
      scrollBeyondLastLine: false, overviewRulerLanes: 0, hideCursorInOverviewRuler: true,
      lineNumbersMinChars: 3, folding: true, renderLineHighlight: "line", wordWrap: "off",
      padding: { top: 12, bottom: 12 }, smoothScrolling: false,
      scrollbar: { verticalScrollbarSize: 9, horizontalScrollbarSize: 9 },
      bracketPairColorization: { enabled: true }, tabSize: 4,
      mouseWheelZoom:true,
    });
    record.editor = editor;
    record.container = host;
    record.clearMarkers = () => { if (!record.model.isDisposed()) monaco.editor.setModelMarkers(record.model, "datapyn", []); };
    if (record.viewState) editor.restoreViewState(record.viewState);
    if (consumePendingFocus(id) || (documentRevision > 0 && wasEditorFocused(id))) queueMicrotask(() => { if (record.editor === editor) editor.focus(); });
    const changed = editor.onDidChangeModelContent(() => callbacks.current.onChange(record.model.getValue()));
    const focused = editor.onDidFocusEditorText(() => { markEditorFocused(id); callbacks.current.onFocus(); });
    const cursor = editor.onDidChangeCursorPosition(({ position }) => callbacks.current.onCursor?.(position.lineNumber, position.column));
    let viewTimer:ReturnType<typeof setTimeout>|undefined;
    const scheduleView=()=>{clearTimeout(viewTimer);viewTimer=setTimeout(()=>captureEditorViewState(id),300);};
    const selectionView=editor.onDidChangeCursorSelection(scheduleView),scrollView=editor.onDidScrollChange(scheduleView);
    const configuration=editor.onDidChangeConfiguration(event=>{if(!event.hasChanged(monaco.editor.EditorOption.fontSize))return;const current=editor.getOption(monaco.editor.EditorOption.fontSize),size=Math.max(8,Math.min(32,current));if(current!==size){editor.updateOptions({fontSize:size});return;}if(size!==(editorPreferences.get(id)?.fontSize??13))callbacks.current.onFontSizeChange?.(size);});
    if (pendingInsertions.has(id)) queueMicrotask(() => {
      if (record.editor !== editor) return;
      const texts = pendingInsertions.get(id) ?? []; pendingInsertions.delete(id);
      for (const text of texts) insertInEditor(id, text);
    });
    // Hidden desktop webviews may suspend animation frames. The microtask
    // follows creation, restored cursor state and the preference effects.
    queueMicrotask(()=>{if(record.editor === editor)callbacks.current.onReady?.(id);});
    return () => { clearTimeout(viewTimer);selectionView.dispose();scrollView.dispose();captureEditorViewState(id);changed.dispose(); focused.dispose(); cursor.dispose();configuration.dispose(); completionGates.get(id)?.invalidate(); record.viewState = editor.saveViewState(); record.editor = undefined; record.container = undefined; editor.dispose(); };
    // Creating a new widget for a changed code prop discards undo history.
    // The separate effect below synchronizes external edits into the stable model.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id,documentRevision]);
  useEffect(() => {
    const record = models.get(id); if (!record) return;
    if (record.model.getLanguageId() !== language) monaco.editor.setModelLanguage(record.model, language);
    if (record.model.getValue() !== code) {
      record.model.pushStackElement();
      record.model.pushEditOperations([], [{ range: record.model.getFullModelRange(), text: code }], () => null);
      record.model.pushStackElement();
    }
  }, [id, code, language]);
  useEffect(() => { editorPreferences.set(id, preferences); applyTheme(preferences,container.current?.ownerDocument.defaultView??window); models.get(id)?.editor?.updateOptions({ fontFamily: preferences?.fontFamily ?? "'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace", fontSize: Math.max(8, Math.min(32, preferences?.fontSize ?? 13)), wordWrap: preferences?.wordWrap ? "on" : "off", minimap: { enabled: !!preferences?.minimap }, lineNumbers: preferences?.lineNumbers === false ? "off" : "on", tabSize: preferences?.tabSize ?? 4, readOnly: preferences?.readOnly ?? false, quickSuggestions: preferences?.autocomplete !== false, suggestOnTriggerCharacters: preferences?.autocomplete !== false, inlineSuggest: { enabled: !!preferences?.aiAutocomplete } }); }, [id, preferences,documentRevision]);
  useEffect(() => {
    const record = models.get(id); if (!record) return;
    let timeout: ReturnType<typeof setTimeout> | undefined, disposed = false;
    const validate = () => {
      clearTimeout(timeout);
      timeout = setTimeout(async () => {
        const model = record.model, version = model.getVersionId(), contextVersion = contextVersions.get(id);
        try {
          const { markers } = await runtime.request<{ markers: LanguageMarker[] }>("language.diagnostics", { ...languageParams(contexts.get(id), { language: model.getLanguageId() as Language, code: model.getValue() }), block_id: id });
          if (disposed || model.isDisposed() || model.getVersionId() !== version || contextVersions.get(id) !== contextVersion) return;
          monaco.editor.setModelMarkers(model, "datapyn", (markers ?? []).map((marker) => ({ startLineNumber: marker.start_line, startColumn: marker.start_column, endLineNumber: marker.end_line, endColumn: marker.end_column, message: marker.message, severity: marker.severity === "warning" ? monaco.MarkerSeverity.Warning : marker.severity === "info" ? monaco.MarkerSeverity.Info : monaco.MarkerSeverity.Error })));
        } catch { /* Diagnostics never prevent editing or execution. */ }
      }, 750);
    };
    diagnosticRefreshers.set(id, validate);
    const changed = record.model.onDidChangeContent(validate); validate();
    return () => { disposed = true; clearTimeout(timeout); changed.dispose(); diagnosticRefreshers.delete(id); };
  }, [id, language]);
  return <div className="monaco-block" ref={container} style={{ height }} aria-label={`Editor ${language}`} />;
});
