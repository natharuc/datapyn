import { invoke } from "@tauri-apps/api/core";
import { isDesktop, errorText } from "./runtime";
import type { DownloadEvent, Update } from "@tauri-apps/plugin-updater";
import { TAURI_UPDATE_CHANNEL, TAURI_UPDATE_ENDPOINT, validateTauriUpdateManifest } from "./updateChannel";

export interface UpdateConfiguration { available: boolean; current_version: string; channel: string; automatic_download?: boolean; endpoint?: string; reason?: string }
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
    if (!isDesktop()) return { available: false, current_version: "", channel: TAURI_UPDATE_CHANNEL, reason: "Abra o aplicativo desktop para consultar atualizações." };
    return invoke<UpdateConfiguration>("updater_status");
  },
  async check() {
    const { check } = await import("@tauri-apps/plugin-updater");
    const update = await check({ timeout: 30_000, headers: { "Cache-Control": "no-cache" } }) as Update | null;
    if (update) {
      try { validateTauriUpdateManifest(update.rawJson, update.version); }
      catch (error) { await update.close().catch(() => {}); throw error; }
    }
    return update;
  },
  async relaunch() { const { relaunch } = await import("@tauri-apps/plugin-process"); await relaunch(); },
};

export class UpdateController {
  state: UpdateState = { phase: "loading", downloaded: 0 };
  private handle?: UpdateHandle;
  private disposed = false;
  private generation = 0;
  private active?: Promise<void>;
  private downloaded = false;
  private initialized?: Promise<void>;
  private listeners = new Set<() => void>();
  private automaticTimer?: ReturnType<typeof setTimeout>;
  private automaticGeneration = 0;
  constructor(private publish: (state: UpdateState) => void = () => {}, private transport = updateTransport) {}
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  getSnapshot = () => this.state;
  private change(values: Partial<UpdateState>) { if (!this.disposed) { this.state = { ...this.state, ...values }; this.publish(this.state); for (const listener of this.listeners) listener(); } }
  async initialize() {
    if (this.disposed) return;
    if (!this.initialized) this.initialized = (async () => {
      try {
        const reported = await this.transport.configuration();
        const configuration = reported.available && (reported.channel !== TAURI_UPDATE_CHANNEL || reported.endpoint !== TAURI_UPDATE_ENDPOINT)
          ? { ...reported, available: false, reason: "Este build não tem o canal exclusivo do DataPyn Tauri configurado." }
          : reported;
        this.change({ configuration, phase: configuration.available ? "idle" : "unavailable" });
      }
      catch (error) { this.change({ phase: "unavailable", error: errorText(error) }); }
    })();
    await this.initialized;
  }
  /** Check after startup, then every six hours. Network failures retry after fifteen minutes. */
  startAutomaticUpdates(initialDelay = 10_000) {
    this.stopAutomaticUpdates();
    if (this.disposed) return () => {};
    const generation = ++this.automaticGeneration;
    const current = () => !this.disposed && generation === this.automaticGeneration;
    const poll = async () => {
      if (!current()) return;
      await this.initialize();
      if (!current() || !this.state.configuration?.available || this.state.configuration.automatic_download === false) return;
      if (!this.active && !["downloaded", "installing", "installed"].includes(this.state.phase)) {
        await this.check();
        if (current() && this.state.phase === "available") await this.download();
      }
      if (current() && this.state.phase !== "installed") this.automaticTimer = setTimeout(() => { void poll(); }, this.state.phase === "failed" ? 900_000 : 21_600_000);
    };
    this.automaticTimer = setTimeout(() => { void poll(); }, initialDelay);
    return () => { if (generation === this.automaticGeneration) this.stopAutomaticUpdates(); };
  }
  stopAutomaticUpdates() {
    ++this.automaticGeneration;
    if (this.automaticTimer !== undefined) clearTimeout(this.automaticTimer);
    this.automaticTimer = undefined;
  }
  async check() {
    if (this.disposed || !this.state.configuration?.available || this.active || this.downloaded || this.state.phase === "installed") return;
    const generation = ++this.generation;
    this.change({ phase: "checking", error: undefined, downloaded: 0, total: undefined });
    const work = async () => {
      try {
        await this.handle?.close(); this.handle = undefined; this.downloaded = false;
        const handle = await this.transport.check();
        if (this.disposed || generation !== this.generation) { await handle?.close(); return; }
        this.handle = handle ?? undefined;
        this.change({ phase: handle ? "available" : "current", version: handle?.version, notes: handle?.body, date: handle?.date });
      } catch (error) { this.change({ phase: "failed", version: undefined, notes: undefined, date: undefined, error: errorText(error) }); }
    };
    this.active = work(); await this.active; this.active = undefined;
  }
  async download() {
    if (this.disposed || !this.handle || this.active || this.downloaded) return;
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
    if (this.disposed || !this.handle || !this.downloaded || this.active) return;
    this.change({ phase: "installing", error: undefined });
    const work = async () => {
      try {
        await beforeInstall();
      } catch (error) { this.change({ phase: "downloaded", error: errorText(error) }); return; }
      if (this.disposed) return;
      try {
        await this.handle!.install();
        this.downloaded = false; this.change({ phase: "installed" });
      } catch (error) { this.downloaded = false; this.change({ phase: "available", error: errorText(error) }); }
    };
    this.active = work(); await this.active; this.active = undefined;
  }
  async relaunch(beforeRelaunch: () => Promise<void>) {
    if (this.disposed || this.active || this.state.phase !== "installed") return;
    const work = async () => {
      try { await beforeRelaunch(); if (!this.disposed) await this.transport.relaunch(); }
      catch (error) { this.change({ error: errorText(error) }); }
    };
    this.active = work(); await this.active; this.active = undefined;
  }
  async dispose() {
    this.disposed = true; ++this.generation; this.stopAutomaticUpdates();
    await this.active;
    await this.handle?.close(); this.handle = undefined;
    this.listeners.clear();
  }
}
