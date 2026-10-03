import { invoke } from "@tauri-apps/api/core";
import { isDesktop, errorText } from "./runtime";
import type { DownloadEvent, Update } from "@tauri-apps/plugin-updater";

export interface UpdateConfiguration { available: boolean; current_version: string; channel: string; reason?: string }
export interface UpdateState {
  phase: "loading" | "idle" | "unavailable" | "checking" | "current" | "available" | "downloading" | "downloaded" | "installing" | "installed" | "failed";
  configuration?: UpdateConfiguration; version?: string; notes?: string; date?: string; downloaded: number; total?: number; error?: string;
}
export interface UpdateHandle {
  version: string; body?: string; date?: string;
  download(callback: (event: DownloadEvent) => void, options?: { timeout: number }): Promise<void>;
  install(): Promise<void>;
  close(): Promise<void>;
}
export interface UpdateTransport {
  configuration(): Promise<UpdateConfiguration>;
  check(): Promise<UpdateHandle | null>;
  relaunch(): Promise<void>;
}
export const updateTransport: UpdateTransport = {
  async configuration() {
    if (!isDesktop()) return { available: false, current_version: "", channel: "tauri-preview", reason: "Abra o aplicativo desktop para consultar atualizações." };
    return invoke<UpdateConfiguration>("updater_status");
  },
  async check() { const { check } = await import("@tauri-apps/plugin-updater"); return check({ timeout: 30_000 }) as Promise<Update | null>; },
  async relaunch() { const { relaunch } = await import("@tauri-apps/plugin-process"); await relaunch(); },
};

export class UpdateController {
  state: UpdateState = { phase: "loading", downloaded: 0 };
  private handle?: UpdateHandle;
  private disposed = false;
  private generation = 0;
  private active?: Promise<void>;
  private downloaded = false;
  constructor(private publish: (state: UpdateState) => void, private transport = updateTransport) {}
  private change(values: Partial<UpdateState>) { if (!this.disposed) { this.state = { ...this.state, ...values }; this.publish(this.state); } }
  async initialize() {
    try { const configuration = await this.transport.configuration(); this.change({ configuration, phase: configuration.available ? "idle" : "unavailable" }); }
    catch (error) { this.change({ phase: "unavailable", error: errorText(error) }); }
  }
  async check() {
    if (!this.state.configuration?.available || this.active) return;
    const generation = ++this.generation;
    this.change({ phase: "checking", error: undefined, downloaded: 0, total: undefined });
    const work = async () => {
      try {
        await this.handle?.close(); this.handle = undefined; this.downloaded = false;
        const handle = await this.transport.check();
        if (this.disposed || generation !== this.generation) { await handle?.close(); return; }
        this.handle = handle ?? undefined;
        this.change({ phase: handle ? "available" : "current", version: handle?.version, notes: handle?.body, date: handle?.date });
      } catch (error) { this.change({ phase: "failed", error: errorText(error) }); }
    };
    this.active = work(); await this.active; this.active = undefined;
  }
  async download() {
    if (!this.handle || this.active) return;
    this.change({ phase: "downloading", error: undefined, downloaded: 0, total: undefined });
    let downloaded = 0, lastUpdate = 0;
    const work = async () => {
      try {
        await this.handle!.download((event) => {
          if (event.event === "Started") this.change({ total: event.data.contentLength });
          if (event.event === "Progress") { downloaded += event.data.chunkLength; const now = Date.now(); if (now - lastUpdate >= 100) { lastUpdate = now; this.change({ downloaded }); } }
          if (event.event === "Finished") this.change({ downloaded });
        }, { timeout: 600_000 });
        this.downloaded = true; this.change({ phase: "downloaded", downloaded });
      } catch (error) { this.downloaded = false; this.change({ phase: "failed", error: errorText(error) }); }
    };
    this.active = work(); await this.active; this.active = undefined;
  }
  async install(beforeInstall: () => Promise<void>) {
    if (!this.handle || !this.downloaded || this.active) return;
    this.change({ phase: "installing", error: undefined });
    const work = async () => {
      try {
        await beforeInstall();
      } catch (error) { this.change({ phase: "downloaded", error: errorText(error) }); return; }
      try {
        await this.handle!.install();
        this.downloaded = false; this.change({ phase: "installed" });
      } catch (error) { this.downloaded = false; this.change({ phase: "available", error: errorText(error) }); }
    };
    this.active = work(); await this.active; this.active = undefined;
  }
  async relaunch(beforeRelaunch: () => Promise<void>) {
    try { await beforeRelaunch(); await this.transport.relaunch(); }
    catch (error) { this.change({ error: errorText(error) }); }
  }
  async dispose() {
    this.disposed = true; ++this.generation;
    await this.active;
    await this.handle?.close(); this.handle = undefined;
  }
}
