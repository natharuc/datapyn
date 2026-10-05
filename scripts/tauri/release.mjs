import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { appendFileSync, chmodSync, closeSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, openSync, readFileSync, readSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { buildDebianPackage, linuxLauncher } from "./linux-package.mjs";

export const RELEASE_REPOSITORY = "natharuc/datapyn";
export const RELEASE_CHANNEL = "tauri-stable";
export const UPDATE_ENDPOINT = `https://github.com/${RELEASE_REPOSITORY}/releases/download/${RELEASE_CHANNEL}/latest.json`;
export const RELEASE_PLATFORMS = ["windows-x86_64", "linux-x86_64", "darwin-aarch64"];
const root = fileURLToPath(new URL("../../", import.meta.url));
const versionPattern = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;

export function stableVersion(value) {
  if (typeof value !== "string" || !versionPattern.test(value) || value.split(".").some(part => !Number.isSafeInteger(Number(part)))) throw new Error("Use a stable Tauri version in X.Y.Z format.");
  return value;
}

export function releaseVersion(tag) {
  if (typeof tag !== "string" || !tag.startsWith("tauri-v")) throw new Error("Tauri releases require a dedicated tauri-vX.Y.Z tag.");
  return stableVersion(tag.slice("tauri-v".length));
}

export function releaseRequest({ eventName, refType, refName, inputTag, publish = false, currentVersion, tagExists }) {
  if (eventName === "push" && refType === "branch") {
    const tag = `tauri-v${stableVersion(currentVersion)}`;
    if (refName === "codex/tauri-migration") return { tag, publish: false, build: true };
    if (refName === "main") {
      if (typeof tagExists !== "boolean") throw new Error("Main releases require a verified version-tag lookup.");
      return { tag, publish: !tagExists, build: !tagExists };
    }
  }
  if (eventName === "push" && refType === "tag") { releaseVersion(refName); return { tag: refName, publish: true, build: true }; }
  if (eventName === "workflow_dispatch") { releaseVersion(inputTag); return { tag: inputTag, publish: publish === true, build: true }; }
  throw new Error("Unsupported release workflow event.");
}

export function workflowRequest(env = process.env, repositoryRoot = root) {
  const git = args => spawnSync("git", args, { cwd: repositoryRoot, encoding: "utf8", shell: false, windowsHide: true });
  const config = JSON.parse(readFileSync(join(repositoryRoot, "desktop/src-tauri/tauri.conf.json"), "utf8"));
  let tagExists;
  if (env.GITHUB_EVENT_NAME === "push" && env.GITHUB_REF_TYPE === "branch" && env.GITHUB_REF_NAME === "main") {
    const tag = `tauri-v${stableVersion(config.version)}`;
    const lookup = git(["show-ref", "--verify", "--quiet", `refs/tags/${tag}`]);
    if (lookup.error || ![0, 1].includes(lookup.status)) throw new Error("Could not verify whether the Tauri version tag already exists.");
    tagExists = lookup.status === 0;
  }
  const request = releaseRequest({ eventName: env.GITHUB_EVENT_NAME, refType: env.GITHUB_REF_TYPE, refName: env.GITHUB_REF_NAME, inputTag: env.DATAPYN_RELEASE_TAG, publish: env.DATAPYN_RELEASE_PUBLISH === "true", currentVersion: config.version, tagExists });
  const version = verifyReleaseVersion(request.tag, repositoryRoot);
  const commit = git(["rev-parse", "HEAD"]);
  if (commit.status !== 0 || !/^[a-f\d]{40}$/.test(commit.stdout.trim())) throw new Error("Could not resolve the Tauri release commit.");
  if (request.publish && !["origin/codex/tauri-migration", "origin/main"].some(branch => git(["merge-base", "--is-ancestor", "HEAD", branch]).status === 0)) throw new Error("Production Tauri tags must reference the isolated migration branch or main.");
  return { version, ...request, commit: commit.stdout.trim() };
}

export async function publishedReleaseExists(tag, token, request = fetch) {
  releaseVersion(tag);
  if (!token) throw new Error("Published Tauri release lookup requires the read-only GitHub workflow token.");
  const response = await request(`https://api.github.com/repos/${RELEASE_REPOSITORY}/releases/tags/${tag}`, {
    method: "GET",
    signal: AbortSignal.timeout(30_000),
    headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, "X-GitHub-Api-Version": "2026-03-10" },
  });
  if (response.status === 404) return false;
  if (!response.ok) throw new Error(`Could not verify the existing Tauri release: HTTP ${response.status}.`);
  const release = await response.json();
  if (release.tag_name !== tag || typeof release.draft !== "boolean") throw new Error("The existing Tauri release response is invalid.");
  return !release.draft;
}

export async function prepareWorkflowRequest(env = process.env, repositoryRoot = root, lookupPublishedRelease = tag => publishedReleaseExists(tag, env.GH_TOKEN)) {
  const request = workflowRequest(env, repositoryRoot);
  if (env.GITHUB_EVENT_NAME === "push" && env.GITHUB_REF_TYPE === "tag") {
    // Publishing from main can create the tag through the release API. A later
    // tag event must not rebuild an already-published immutable distribution.
    const published = await lookupPublishedRelease(request.tag);
    if (typeof published !== "boolean") throw new Error("Could not verify whether the Tauri release is published.");
    if (published) return { ...request, publish: false, build: false };
  }
  return request;
}

export function compareVersions(left, right) {
  const first = stableVersion(left).split(".").map(Number);
  const second = stableVersion(right).split(".").map(Number);
  for (let index = 0; index < first.length; index += 1) if (first[index] !== second[index]) return first[index] > second[index] ? 1 : -1;
  return 0;
}

export function fileSha256(path) {
  const file = openSync(path, "r");
  const hash = createHash("sha256");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try {
    let length;
    while ((length = readSync(file, buffer, 0, buffer.length, null)) > 0) hash.update(buffer.subarray(0, length));
    return hash.digest("hex");
  } finally { closeSync(file); }
}

export function artifactBaseUrl(version) {
  return `https://github.com/${RELEASE_REPOSITORY}/releases/download/tauri-v${stableVersion(version)}`;
}

export function verifyReleaseVersion(tag, repositoryRoot = root) {
  const version = releaseVersion(tag);
  const config = JSON.parse(readFileSync(join(repositoryRoot, "desktop/src-tauri/tauri.conf.json"), "utf8"));
  const packageJson = JSON.parse(readFileSync(join(repositoryRoot, "desktop/package.json"), "utf8"));
  const cargo = readFileSync(join(repositoryRoot, "desktop/src-tauri/Cargo.toml"), "utf8").match(/^version\s*=\s*"([^"]+)"/m)?.[1];
  if ([config.version, packageJson.version, cargo].some(value => value !== version)) throw new Error("Tauri tag, tauri.conf.json, desktop/package.json and Cargo.toml versions must match. The PyQt version is independent.");
  if (config.identifier !== "app.datapyn.tauri") throw new Error("Production Tauri releases must use the isolated app.datapyn.tauri identity.");
  return version;
}

export function signedConfiguration(env, embeddedConfiguration = JSON.parse(readFileSync(join(root, "desktop/src-tauri/tauri.conf.json"), "utf8"))) {
  const embeddedKey = embeddedConfiguration.plugins?.updater?.pubkey?.trim();
  const providedKey = env.DATAPYN_TAURI_UPDATER_PUBLIC_KEY?.trim();
  const publicKey = providedKey || embeddedKey;
  const endpoint = env.DATAPYN_TAURI_UPDATER_ENDPOINT?.trim() || UPDATE_ENDPOINT;
  if (!publicKey || !env.TAURI_SIGNING_PRIVATE_KEY?.trim()) throw new Error("Signed Tauri builds require the dedicated public key and signing private key.");
  if (providedKey && providedKey !== embeddedKey) throw new Error("The signing public key must match the key embedded in the isolated Tauri application.");
  if (endpoint !== UPDATE_ENDPOINT) throw new Error("Use the isolated HTTPS GitHub tauri-stable update endpoint; the PyQt latest release channel is not allowed.");
  return { bundle: { createUpdaterArtifacts: true }, plugins: { updater: { pubkey: publicKey, endpoints: [endpoint], windows: { installMode: "passive" } } } };
}

export function findFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).sort((left, right) => left.name < right.name ? -1 : left.name > right.name ? 1 : 0).flatMap(item => {
    const path = join(directory, item.name);
    if (item.isDirectory()) return item.name.endsWith(".app") ? [] : findFiles(path);
    return item.isFile() ? [path] : [];
  });
}

function platformArtifact(platform, path) {
  if (platform === "windows-x86_64") return path.endsWith(".exe");
  if (platform === "linux-x86_64") return path.endsWith(".AppImage");
  if (platform === "darwin-aarch64") return path.endsWith(".app.tar.gz");
  throw new Error(`Unsupported Tauri release platform: ${platform}`);
}

export function updateManifest({ bundleDirectory, version, platform, artifactBaseUrl: baseUrl = artifactBaseUrl(version), notes = "" }) {
  stableVersion(version);
  const origin = new URL(baseUrl);
  if (origin.href.replace(/\/$/, "") !== artifactBaseUrl(version)) throw new Error("Artifacts must use the immutable GitHub tauri-vX.Y.Z release, separate from PyQt.");
  const signatures = findFiles(bundleDirectory).filter(path => path.endsWith(".sig") && platformArtifact(platform, path.slice(0, -4)));
  if (signatures.length !== 1) throw new Error("Expected one signed NSIS, AppImage or macOS application update artifact.");
  const signaturePath = signatures[0];
  const artifactPath = signaturePath.slice(0, -4);
  if (!existsSync(artifactPath) || statSync(artifactPath).size === 0) throw new Error("The signed update artifact is missing or empty.");
  const signature = readFileSync(signaturePath, "utf8").trim();
  if (!signature) throw new Error("The updater artifact signature is empty.");
  return { channel: RELEASE_CHANNEL, version, notes, pub_date: new Date().toISOString(), platforms: { [platform]: { signature, url: `${artifactBaseUrl(version)}/${encodeURIComponent(basename(artifactPath))}` } } };
}

export function validateManifest(manifest, { complete = false } = {}) {
  if (manifest?.channel !== RELEASE_CHANNEL) throw new Error("The update manifest belongs to a different channel.");
  stableVersion(manifest.version);
  if (manifest.pub_date !== undefined && (typeof manifest.pub_date !== "string" || !Number.isFinite(Date.parse(manifest.pub_date)))) throw new Error("The manifest publication date is invalid.");
  const platforms = Object.keys(manifest.platforms ?? {});
  if (platforms.length === 0 || platforms.some(platform => !RELEASE_PLATFORMS.includes(platform)) || (complete && (platforms.length !== RELEASE_PLATFORMS.length || RELEASE_PLATFORMS.some(platform => !platforms.includes(platform))))) throw new Error("The Tauri manifest must contain the expected platform set.");
  for (const [platform, artifact] of Object.entries(manifest.platforms)) {
    if (!artifact || typeof artifact.signature !== "string" || !artifact.signature.trim()) throw new Error("Each update artifact requires its actual signature.");
    const prefix = artifactBaseUrl(manifest.version) + "/";
    if (typeof artifact.url !== "string" || !artifact.url.startsWith(prefix)) throw new Error("An update artifact points outside its immutable Tauri release.");
    const name = artifact.url.slice(prefix.length);
    if (!name || name.includes("/") || !platformArtifact(platform, decodeURIComponent(name))) throw new Error("The update artifact does not match its platform.");
    const url = new URL(artifact.url);
    if (url.search || url.hash || /[\\/]/.test(decodeURIComponent(name))) throw new Error("The update artifact URL is invalid.");
  }
  return manifest;
}

function oneFile(files, suffix) {
  const matches = files.filter(file => file.endsWith(suffix));
  if (matches.length !== 1) throw new Error(`Expected exactly one ${suffix} artifact.`);
  return matches[0];
}

function archive(command, args, env = process.env) {
  const result = spawnSync(command, args, { env, stdio: "inherit", shell: false, windowsHide: true });
  if (result.error || result.status !== 0) throw new Error(`Portable archive failed: ${result.error?.message ?? command}`);
}

export function stageRelease({ bundleDirectory, nativeDirectory, outputDirectory, version, platform, createPortable = true }) {
  stableVersion(version);
  if (!RELEASE_PLATFORMS.includes(platform)) throw new Error("Unsupported Tauri release platform.");
  mkdirSync(outputDirectory, { recursive: true });
  if (readdirSync(outputDirectory).length !== 0) throw new Error("Use an empty directory to stage immutable Tauri artifacts.");
  const files = findFiles(bundleDirectory);
  const prefix = `DataPyn-Tauri-${version}-${platform}`;
  const signedSource = oneFile(files.filter(file => file.endsWith(".sig") && platformArtifact(platform, file.slice(0, -4))), ".sig").slice(0, -4);
  const signedName = platform === "windows-x86_64" ? `${prefix}-setup.exe` : platform === "linux-x86_64" ? `${prefix}.AppImage` : `${prefix}.app.tar.gz`;
  copyFileSync(signedSource, join(outputDirectory, signedName));
  copyFileSync(signedSource + ".sig", join(outputDirectory, signedName + ".sig"));
  if (platform !== "windows-x86_64") chmodSync(join(outputDirectory, signedName), 0o755);
  if (platform === "linux-x86_64") buildDebianPackage({ appImage: join(outputDirectory, signedName), version, output: join(outputDirectory, `${prefix}.deb`) });
  if (platform === "darwin-aarch64") copyFileSync(oneFile(files, ".dmg"), join(outputDirectory, `${prefix}.dmg`));
  if (createPortable && platform !== "darwin-aarch64") {
    const temporary = mkdtempSync(join(tmpdir(), "datapyn-tauri-release-"));
    try {
      const appDirectory = join(temporary, "DataPyn-Tauri");
      mkdirSync(appDirectory);
      if (platform === "windows-x86_64") {
        for (const name of ["datapyn-desktop.exe", "datapyn-runtime.exe"]) copyFileSync(join(nativeDirectory, name), join(appDirectory, name));
        writeFileSync(join(appDirectory, "LEIA-ME.txt"), "DataPyn Tauri\r\nExtraia em uma pasta gravável pelo seu usuário e abra datapyn-desktop.exe. Mantenha datapyn-runtime.exe nesta pasta.\r\nPara instalar WebView2, Microsoft ODBC e os atalhos automaticamente, use o instalador -setup.exe desta release.\r\nA primeira atualização do ZIP executa o instalador NSIS assinado nesta mesma pasta e registra sua desinstalação; o caminho do aplicativo é preservado.\r\nDados e atualizações são separados da versão PyQt6.\r\n");
        archive("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", "Compress-Archive -LiteralPath $env:DATAPYN_TAURI_ARCHIVE_SOURCE -DestinationPath $env:DATAPYN_TAURI_ARCHIVE_OUTPUT -CompressionLevel Optimal"], { ...process.env, DATAPYN_TAURI_ARCHIVE_SOURCE: appDirectory, DATAPYN_TAURI_ARCHIVE_OUTPUT: resolve(outputDirectory, `${prefix}.zip`) });
      } else {
        copyFileSync(join(outputDirectory, signedName), join(appDirectory, "DataPyn-Tauri.AppImage"));
        chmodSync(join(appDirectory, "DataPyn-Tauri.AppImage"), 0o755);
        writeFileSync(join(appDirectory, "datapyn-tauri"), linuxLauncher({ portable: true }), { mode: 0o755 });
        writeFileSync(join(appDirectory, "LEIA-ME.txt"), "DataPyn Tauri\nExecute ./datapyn-tauri. O launcher prepara uma cópia por usuário em $XDG_DATA_HOME/datapyn-tauri/installation e preserva as atualizações.\nNão precisa de FUSE. O runtime Python e os drivers acompanham o AppImage. Dados e atualizações são separados do PyQt6.\n");
        archive("tar", ["-czf", resolve(outputDirectory, `${prefix}.tar.gz`), "-C", temporary, "DataPyn-Tauri"]);
      }
    } finally {
      const resolved = resolve(temporary);
      if (!resolved.startsWith(resolve(tmpdir()) + sep) || !basename(resolved).startsWith("datapyn-tauri-release-")) throw new Error("Refusing to clean a directory outside the temporary release workspace.");
      rmSync(resolved, { recursive: true, force: true });
    }
  }
  const manifest = updateManifest({ bundleDirectory: outputDirectory, platform, version });
  writeFileSync(join(outputDirectory, `manifest-${platform}.json`), JSON.stringify(manifest, null, 2) + "\n");
  return manifest;
}

export function combineRelease({ inputDirectory, outputDirectory, version, notes = `DataPyn Tauri ${version}` }) {
  stableVersion(version);
  const files = findFiles(inputDirectory);
  const manifests = files.filter(file => /^manifest-.+\.json$/.test(basename(file))).map(file => validateManifest(JSON.parse(readFileSync(file, "utf8"))));
  if (manifests.length !== RELEASE_PLATFORMS.length || manifests.some(manifest => manifest.version !== version || Object.keys(manifest.platforms).length !== 1)) throw new Error("All three matching platform builds are required before publication.");
  const platforms = {};
  for (const manifest of manifests) for (const [platform, artifact] of Object.entries(manifest.platforms)) {
    if (platforms[platform]) throw new Error("A platform occurs more than once in the release.");
    platforms[platform] = artifact;
  }
  // Keep the final manifest identical when retrying only publication with the
  // same already-built platform artifacts. No clock-based rebuild of metadata.
  const pubDate = manifests.map(manifest => manifest.pub_date).filter(Boolean).sort().at(-1);
  if (!pubDate) throw new Error("Platform manifests require a publication date.");
  const manifest = validateManifest({ channel: RELEASE_CHANNEL, version, notes, pub_date: pubDate, platforms }, { complete: true });
  mkdirSync(outputDirectory, { recursive: true });
  if (readdirSync(outputDirectory).length !== 0) throw new Error("Use an empty final release directory.");
  const assets = files.filter(file => !basename(file).startsWith("manifest-"));
  const names = new Set();
  for (const asset of assets) {
    const name = basename(asset);
    if (!name.startsWith(`DataPyn-Tauri-${version}-`) || names.has(name) || statSync(asset).size === 0) throw new Error("Release assets must be unique, nonempty and isolated from PyQt filenames.");
    names.add(name);
    copyFileSync(asset, join(outputDirectory, name));
  }
  for (const artifact of Object.values(platforms)) {
    const name = decodeURIComponent(artifact.url.split("/").at(-1));
    if (!names.has(name) || !names.has(name + ".sig") || readFileSync(join(outputDirectory, name + ".sig"), "utf8").trim() !== artifact.signature) throw new Error("A manifest update artifact or its matching signature is missing.");
  }
  writeFileSync(join(outputDirectory, "latest.json"), JSON.stringify(manifest, null, 2) + "\n");
  const checksums = readdirSync(outputDirectory).sort().map(name => `${fileSha256(join(outputDirectory, name))}  ${name}`).join("\n") + "\n";
  writeFileSync(join(outputDirectory, "SHA256SUMS.txt"), checksums);
  return manifest;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const [command, ...args] = process.argv.slice(2);
    if (command === "workflow-request") {
      const request = await prepareWorkflowRequest();
      if (!process.env.GITHUB_OUTPUT) throw new Error("This command requires a GitHub Actions output file.");
      appendFileSync(process.env.GITHUB_OUTPUT, `version=${request.version}\ntag=${request.tag}\ncommit=${request.commit}\npublish=${request.publish}\nbuild=${request.build}\n`);
      console.log(request.build ? `${request.publish ? "Publish" : "Validate"} ${request.tag} from ${request.commit}.` : `${request.tag} already exists; this event will not rebuild or replace the version.`);
    } else if (command === "verify-version") console.log(verifyReleaseVersion(args[0]));
    else if (command === "manifest") {
      const [directory, platform, baseUrl, output, version] = args;
      const manifest = updateManifest({ bundleDirectory: directory, platform, artifactBaseUrl: baseUrl, version });
      mkdirSync(dirname(output), { recursive: true });
      writeFileSync(output, JSON.stringify(manifest, null, 2) + "\n");
    } else if (command === "stage") {
      const [bundleDirectory, platform, version, outputDirectory, nativeDirectory] = args;
      stageRelease({ bundleDirectory, platform, version, outputDirectory, nativeDirectory });
    } else if (command === "combine") {
      const [inputDirectory, outputDirectory, version, notesPath] = args;
      combineRelease({ inputDirectory, outputDirectory, version, ...(notesPath ? { notes: readFileSync(notesPath, "utf8") } : {}) });
    } else throw new Error("Use verify-version, manifest, stage or combine.");
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
