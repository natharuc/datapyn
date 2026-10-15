import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import * as monaco from "monaco-editor/editor/editor.api.js";
import "monaco-editor/editor/contrib/fontZoom/browser/fontZoom.js";
import { EditorZoom } from "monaco-editor/editor/common/config/editorZoom.js";
import { MonacoBlock } from "../src/MonacoBlock";
import { models } from "../src/editorRegistry";
import { loadPreferences, normalizeEditorFontSize, savePreferences } from "../src/preferences";
import { refreshOwnerDocuments } from "../src/documentWindows";
import { runtime } from "../src/runtime";
import "../src/styles.css";

runtime.request = async <T,>() => ({} as T);
let setSize: (value: number) => void, setVisible: (visible: boolean) => void, rerender: () => void;
const changes: number[] = [];
function Fixture() {
  const [size, updateSize] = useState(loadPreferences().editorFontSize), [visible, updateVisible] = useState(true), [revision, updateRevision] = useState(0);
  setSize = value => {
    const normalized = normalizeEditorFontSize(value);
    updateSize(normalized);
    savePreferences({ ...loadPreferences(), editorFontSize: normalized });
  };
  setVisible = updateVisible;
  rerender = () => updateRevision(value => value + 1);
  const changed = (value: number) => { changes.push(value); setSize(value); };
  return <>{visible && ["sql-font", "python-font"].map((id, index) =>
    <section id={`${id}-section`} key={id}>
      <MonacoBlock id={id} code={index ? "value = 1\nprint(value)" : "SELECT 1;\nSELECT 2;"} language={index ? "python" : "sql"}
        preferences={{fontSize: size, wordWrap: revision % 2 === 1, theme: "dark"}} height={200} onChange={() => {}} onFocus={() => {}} onFontSizeChange={changed}/>
    </section>)}</>;
}
const test = {
  changes,
  size(value: number) { setSize(value); },
  mounted(visible: boolean) { setVisible(visible); },
  rerender() { rerender(); },
  stats() {
    return { zoom: EditorZoom.getZoomLevel(), saved: loadPreferences().editorFontSize,
      editors: ["sql-font", "python-font"].map(id => {
        const editor = models.get(id)?.editor;
        return editor ? {id, font: editor.getOption(monaco.editor.EditorOption.fontSize), raw: editor.getRawOptions().fontSize,
          lineHeight: editor.getOption(monaco.editor.EditorOption.lineHeight), wheel: editor.getOption(monaco.editor.EditorOption.mouseWheelZoom),
          owner: editor.getDomNode()?.ownerDocument === document ? "main" : "child"} : null;
      }) };
  },
  async action(name: string) { await models.get("sql-font")!.editor!.getAction(name)!.run(); },
  trigger(name: string) { models.get("sql-font")!.editor!.trigger("font-fixture", name, {}); },
  burst(deltas: number[], options: WheelEventInit = {}) {
    const host = models.get("sql-font")!.container!, view = host.ownerDocument.defaultView!;
    return deltas.map(deltaY => {
      const event = new view.WheelEvent("wheel", {deltaY, ctrlKey: true, bubbles: true, cancelable: true, ...options});
      host.querySelector(".view-lines")!.dispatchEvent(event);
      return event.defaultPrevented;
    });
  },
  async adopt() {
    const frame = document.createElement("iframe"); frame.id = "editor-font-child";
    frame.style.cssText = "position:fixed;left:0;top:450px;width:760px;height:240px";
    frame.srcdoc = "<!doctype html><html><head></head><body></body></html>";
    const loaded = new Promise(resolve => frame.addEventListener("load", resolve, {once: true}));
    document.body.append(frame); await loaded;
    const target = frame.contentDocument!;
    for (const style of document.head.querySelectorAll("style,link[rel=stylesheet]")) target.head.append(style.cloneNode(true));
    const panel = document.getElementById("sql-font-section")!;
    target.body.append(panel); refreshOwnerDocuments(panel);
  },
  returnToMain() {
    const frame = document.getElementById("editor-font-child") as HTMLIFrameElement;
    const panel = frame.contentDocument!.getElementById("sql-font-section")!;
    document.getElementById("root")!.prepend(panel); refreshOwnerDocuments(panel); frame.remove();
  },
};
declare global { interface Window { editorFontTest: typeof test } }
window.editorFontTest = test;
createRoot(document.getElementById("root")!).render(<Fixture/>);
