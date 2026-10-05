/** Tauri releases have their own feed; the legacy app owns releases/latest. */
export const TAURI_UPDATE_CHANNEL = "tauri-stable";
export const TAURI_UPDATE_ENDPOINT = "https://github.com/natharuc/datapyn/releases/download/tauri-stable/latest.json";

export function validateTauriUpdateManifest(manifest: unknown, updateVersion: string): void {
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) throw new Error("O canal Tauri retornou um manifesto de atualização inválido.");
  const data = manifest as Record<string, unknown>;
  const version = updateVersion.replace(/^v/, "");
  if (!/^\d+\.\d+\.\d+$/.test(version) || data.version !== version || data.channel !== TAURI_UPDATE_CHANNEL) {
    throw new Error("A atualização não pertence ao canal estável do DataPyn Tauri.");
  }
  if (!data.platforms || typeof data.platforms !== "object" || Array.isArray(data.platforms)) throw new Error("O manifesto Tauri não informa os instaladores assinados.");
  const platforms = Object.entries(data.platforms);
  if (!platforms.length) throw new Error("O manifesto Tauri não informa os instaladores assinados.");
  for (const [target, entry] of platforms) {
    if (!/^(windows|linux|darwin)-(x86_64|aarch64|i686|armv7)$/.test(target) || !entry || typeof entry !== "object" || Array.isArray(entry)) throw new Error("O manifesto Tauri contém uma plataforma inválida.");
    const artifact = entry as Record<string, unknown>;
    if (typeof artifact.signature !== "string" || !artifact.signature.trim()) throw new Error("O instalador Tauri não possui assinatura.");
    let url: URL;
    try { url = new URL(String(artifact.url)); } catch { throw new Error("O manifesto Tauri contém um endereço de download inválido."); }
    const prefix = `/natharuc/datapyn/releases/download/tauri-v${version}/`;
    const filename = url.pathname.slice(prefix.length);
    if (url.protocol !== "https:" || url.hostname !== "github.com" || url.port || url.username || url.password || url.search || url.hash || !url.pathname.startsWith(prefix) || !filename || /[/\\]/.test(decodeURIComponent(filename))) {
      throw new Error("O download deve pertencer à release assinada do DataPyn Tauri no GitHub.");
    }
  }
}
