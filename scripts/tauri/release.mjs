import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export function signedConfiguration(env) {
  const publicKey = env.DATAPYN_TAURI_UPDATER_PUBLIC_KEY?.trim();
  const endpoint = env.DATAPYN_TAURI_UPDATER_ENDPOINT?.trim();
  if (!publicKey || !endpoint || !env.TAURI_SIGNING_PRIVATE_KEY?.trim()) throw new Error("Signed Tauri builds require the dedicated public key, HTTPS endpoint and signing private key.");
  const url = new URL(endpoint);
  if (url.protocol !== "https:" || url.username || url.password || url.hash) throw new Error("Choose a public HTTPS Tauri update endpoint without embedded credentials.");
  return { bundle: { createUpdaterArtifacts: true }, plugins: { updater: { pubkey: publicKey, endpoints: [endpoint], windows: { installMode: "passive" } } } };
}

function findArtifacts(directory) {
  const files = [];
  for (const item of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, item.name);
    if (item.isDirectory()) files.push(...findArtifacts(path));
    else if (item.name.endsWith(".sig")) files.push(path);
  }
  return files;
}

export function updateManifest({ bundleDirectory, version, platform, artifactBaseUrl, notes = "" }) {
  const origin = new URL(artifactBaseUrl);
  if (origin.protocol !== "https:" || origin.username || origin.password || origin.search || origin.hash) throw new Error("Artifact base URL must be public HTTPS without a query or credentials.");
  const signatures = findArtifacts(bundleDirectory).filter(path => platform.startsWith("windows-") ? path.endsWith(".exe.sig") : path.endsWith(".AppImage.sig"));
  if (signatures.length !== 1) throw new Error("Expected one signed NSIS or AppImage update artifact.");
  const signaturePath = signatures[0];
  const artifactName = signaturePath.split(/[\\/]/).at(-1).slice(0, -4);
  const signature = readFileSync(signaturePath, "utf8").trim();
  if (!signature) throw new Error("The updater artifact signature is empty.");
  return { version, notes, pub_date: new Date().toISOString(), platforms: { [platform]: { signature, url: `${origin.href.replace(/\/$/, "")}/${encodeURIComponent(artifactName)}` } } };
}

if (process.argv[1]?.endsWith("release.mjs") && process.argv[2] === "manifest") {
  const [directory, platform, artifactBaseUrl, output, version] = process.argv.slice(3);
  const manifest = updateManifest({ bundleDirectory: directory, platform, artifactBaseUrl, version });
  mkdirSync(join(output, ".."), { recursive: true });
  writeFileSync(output, JSON.stringify(manifest, null, 2) + "\n");
}
