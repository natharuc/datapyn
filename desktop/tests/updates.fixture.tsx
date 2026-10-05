import React, { useEffect, useState, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { UpdateDialog } from "../src/UpdateDialog";
import { UpdateController, type UpdateHandle, type UpdateTransport } from "../src/updater";
import { TAURI_UPDATE_CHANNEL, TAURI_UPDATE_ENDPOINT } from "../src/updateChannel";
import "../src/styles.css";
import "../src/updater.css";

let finish: (() => void) | undefined, reject: ((reason: Error) => void) | undefined;
let busy = true;
const calls: string[] = [];
const handle: UpdateHandle = {
  version: "1.58.0", body: "Correções de estabilidade.\nDownload exclusivo do canal Tauri.", date: "2026-10-05T12:00:00Z",
  async download(callback) {
    calls.push("download"); callback({ event: "Started", data: { contentLength: 10 * 1048576 } });
    callback({ event: "Progress", data: { chunkLength: 5 * 1048576 } });
    await new Promise<void>((resolve, fail) => { finish = resolve; reject = fail; });
    callback({ event: "Progress", data: { chunkLength: 5 * 1048576 } }); callback({ event: "Finished" });
  },
  async install() { calls.push("install"); }, async close() { calls.push("close"); },
};
const transport: UpdateTransport = {
  async configuration() { return { available: true, automatic_download: true, current_version: "1.57.0", channel: TAURI_UPDATE_CHANNEL, endpoint: TAURI_UPDATE_ENDPOINT }; },
  async check() { calls.push("check"); return handle; }, async relaunch() { calls.push("relaunch"); },
};
const controller = new UpdateController(undefined, transport);
Object.assign(window, { __UPDATES_TEST__: {
  get state() { return controller.state; }, calls,
  finishDownload() { finish?.(); }, failDownload() { reject?.(new Error("Assinatura inválida.")); },
  allowInstall() { busy = false; },
} });

function Fixture() {
  const [open, setOpen] = useState(true);
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  useEffect(() => controller.startAutomaticUpdates(0), []);
  return <div className="app-shell"><header className="app-header"><button onClick={() => setOpen(true)}>Atualizações</button><span role="status">{state.phase}</span></header>
    <main style={{ padding: 20 }}>Consulta de dados disponível durante o download.</main>
    {open && <UpdateDialog controller={controller} onClose={() => setOpen(false)} beforeInstall={async () => {
      if (busy) throw new Error("Aguarde ou cancele as operações antes de instalar.");
      calls.push("save");
    }} />}
  </div>;
}

createRoot(document.getElementById("root")!).render(<Fixture />);
