import { describe, expect, it } from "vitest";
import { TAURI_UPDATE_CHANNEL, validateTauriUpdateManifest } from "./updateChannel";

const version = "1.58.0";
const url = `https://github.com/natharuc/datapyn/releases/download/tauri-v${version}/DataPyn.Tauri_1.58.0_x64-setup.exe`;
const manifest = (overrides: Record<string, unknown> = {}) => ({
  version, channel: TAURI_UPDATE_CHANNEL,
  platforms: { "windows-x86_64": { url, signature: "signed-by-tauri" } }, ...overrides,
});

describe("isolated Tauri update manifests", () => {
  it("accepts signed artifacts from the same immutable Tauri release across supported operating systems", () => {
    expect(() => validateTauriUpdateManifest(manifest({ platforms: {
      "windows-x86_64": { url, signature: "signature" },
      "linux-x86_64": { url: url.replace(/[^/]+$/, "DataPyn_Tauri_1.58.0.AppImage"), signature: "signature" },
      "darwin-aarch64": { url: url.replace(/[^/]+$/, "DataPyn_Tauri.app.tar.gz"), signature: "signature" },
    } }), version)).not.toThrow();
  });
  it.each([undefined, null, [], {}, manifest({ channel: "pyqt6" }), manifest({ version: "1.57.0" }), manifest({ platforms: {} }), manifest({ platforms: [] })])("rejects incomplete and unrelated release manifests %#", value => {
    expect(() => validateTauriUpdateManifest(value, version)).toThrow();
  });
  it.each([
    url.replace("tauri-v1.58.0", "v1.58.0"),
    url.replace("tauri-v1.58.0", "tauri-stable"),
    url.replace("tauri-v1.58.0", "tauri-v1.59.0"),
    url.replace("natharuc/datapyn", "other/repo"),
    url.replace("https:", "http:"),
    url.replace("github.com", "github.com.evil.example"),
    url.replace("github.com", "user@github.com"),
    `${url}?token=secret`, `${url}#fragment`,
    url.replace(/[^/]+$/, "evil%2Ffile.exe"),
    url.replace("/download/tauri-v1.58.0/", "/latest/download/"),
  ])("rejects legacy or mutable download routes and unsafe URLs %#", address => {
    expect(() => validateTauriUpdateManifest(manifest({ platforms: { "windows-x86_64": { url: address, signature: "signed" } } }), version)).toThrow();
  });
  it("rejects missing signatures on every platform even if the current platform is signed", () => {
    expect(() => validateTauriUpdateManifest(manifest({ platforms: {
      "windows-x86_64": { url, signature: "signed" },
      "darwin-aarch64": { url, signature: "" },
    } }), version)).toThrow("assinatura");
  });
});
