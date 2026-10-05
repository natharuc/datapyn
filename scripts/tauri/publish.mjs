import { spawnSync } from "node:child_process";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compareVersions, fileSha256, RELEASE_CHANNEL, RELEASE_REPOSITORY, releaseVersion, validateManifest } from "./release.mjs";

export function verifyPublishedFiles(directory) {
  const manifest = validateManifest(JSON.parse(readFileSync(join(directory, "latest.json"), "utf8")), { complete: true });
  const checksums = readFileSync(join(directory, "SHA256SUMS.txt"), "utf8").trim().split("\n");
  const expected = new Set();
  for (const line of checksums) {
    const match = /^([a-f\d]{64})  ([^/\\]+)$/.exec(line);
    if (!match || match[2] === "SHA256SUMS.txt" || expected.has(match[2])) throw new Error("Invalid release checksum listing.");
    expected.add(match[2]);
    if (fileSha256(join(directory, match[2])) !== match[1]) throw new Error(`Release checksum mismatch: ${match[2]}`);
  }
  const files = readdirSync(directory).filter(name => name !== "SHA256SUMS.txt");
  if (files.length !== expected.size || files.some(name => !expected.has(name))) throw new Error("Release files and checksums do not match.");
  for (const artifact of Object.values(manifest.platforms)) {
    const name = decodeURIComponent(artifact.url.split("/").at(-1));
    if (!expected.has(name) || !expected.has(name + ".sig") || readFileSync(join(directory, name + ".sig"), "utf8").trim() !== artifact.signature) throw new Error("Manifest signature does not match the published update artifact.");
  }
  return manifest;
}

function samePlatforms(first, second) {
  return Object.keys(first).length === Object.keys(second).length && Object.entries(first).every(([platform, artifact]) => second[platform]?.url === artifact.url && second[platform]?.signature === artifact.signature);
}

export function verifyExistingAssets(release, directory) {
  const names = readdirSync(directory).sort();
  const assets = release.assets ?? [];
  const matches = assets.length === names.length && new Set(assets.map(asset => asset.name)).size === assets.length && names.every(name => {
    const asset = assets.find(item => item.name === name);
    const path = join(directory, name);
    return asset && asset.size === statSync(path).size && asset.digest === `sha256:${fileSha256(path)}`;
  });
  if (!matches) throw new Error("This Tauri version has already been published with different or unverifiable assets. Published artifacts cannot be replaced.");
}

export async function publishRelease({ directory, tag, commit, token, repository = RELEASE_REPOSITORY, request = fetch, upload }) {
  const version = releaseVersion(tag);
  const manifest = verifyPublishedFiles(directory);
  if (repository !== RELEASE_REPOSITORY || manifest.version !== version || !/^[a-f\d]{40}$/.test(commit ?? "") || !token) throw new Error("Only a matching tagged Tauri release can be published to the dedicated repository.");
  const api = async (method, path, body, allowMissing = false) => {
    const response = await request(`https://api.github.com/repos/${repository}/${path}`, { method, headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, "X-GitHub-Api-Version": "2026-03-10", "Content-Type": "application/json" }, ...(body ? { body: JSON.stringify(body) } : {}) });
    if (response.status === 404 && allowMissing) return undefined;
    if (!response.ok) throw new Error(`GitHub ${method} ${path} failed: HTTP ${response.status}.`);
    return response.status === 204 ? undefined : response.json();
  };
  const existingFeed = await api("GET", `releases/tags/${RELEASE_CHANNEL}`, undefined, true);
  if (existingFeed?.immutable) throw new Error("The tauri-stable feed must remain mutable; immutable releases cannot refresh latest.json.");
  let feedAlreadyCurrent = false;
  if (existingFeed && !existingFeed.draft) {
    const asset = existingFeed.assets?.find(item => item.name === "latest.json");
    if (!asset) throw new Error("The existing Tauri feed is missing its update manifest.");
    const response = await request(asset.browser_download_url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("Could not read the current Tauri feed; promotion was stopped.");
    const current = validateManifest(await response.json(), { complete: true });
    const comparison = compareVersions(version, current.version);
    if (comparison < 0) throw new Error("The Tauri stable feed only accepts a newer version; published versions are immutable.");
    if (comparison === 0) {
      if (!samePlatforms(manifest.platforms, current.platforms)) throw new Error("The current feed has the same Tauri version with different signed artifacts. It cannot be overwritten.");
      feedAlreadyCurrent = true;
    }
  }
  const existing = await api("GET", `releases/tags/${tag}`, undefined, true);
  if (existing && !existing.draft) {
    // Resume feed promotion only after GitHub's digests prove that *every*
    // already-published byte matches this distribution, including its manifest,
    // checksums and signatures. Never reupload or edit the version release.
    verifyExistingAssets(existing, directory);
    if (feedAlreadyCurrent) return { version, tag, channel: RELEASE_CHANNEL, alreadyCurrent: true };
  } else if (feedAlreadyCurrent) throw new Error("The current feed points to a missing or unpublished Tauri version release.");
  const body = `${manifest.notes}\n\nInstalação independente do DataPyn PyQt6. Os artefatos e o canal de atualização desta release pertencem somente ao DataPyn Tauri.\n\n- Windows x86_64: instalador NSIS e ZIP portátil.\n- Linux x86_64: DEB, AppImage e tar.gz portátil.\n- macOS Apple Silicon: DMG e aplicação para o atualizador.\n\nConfira SHA256SUMS.txt para verificar os downloads.\n`;
  const uploadAssets = upload ?? ((releaseTag, paths) => {
    const result = spawnSync("gh", ["release", "upload", releaseTag, ...paths, "--repo", repository, "--clobber"], { shell: false, windowsHide: true, stdio: "inherit", env: { ...process.env, GH_TOKEN: token } });
    if (result.error || result.status !== 0) throw new Error(`GitHub artifact upload failed for ${releaseTag}.`);
  });
  if (!existing || existing.draft) {
    const release = existing ?? await api("POST", "releases", { tag_name: tag, target_commitish: commit, name: `DataPyn Tauri ${version}`, body, draft: true, prerelease: false, make_latest: "false" });
    await uploadAssets(tag, readdirSync(directory).sort().map(name => join(directory, name)));
    await api("PATCH", `releases/${release.id}`, { draft: false, body, make_latest: "false" });
  }
  const feed = existingFeed ?? await api("POST", "releases", { tag_name: RELEASE_CHANNEL, target_commitish: commit, name: "DataPyn Tauri — canal de atualizações", body: "Manifesto exclusivo do DataPyn Tauri. Os instaladores estão nas releases tauri-vX.Y.Z. Este canal não atualiza a versão PyQt6.", draft: true, prerelease: true, make_latest: "false" });
  await uploadAssets(RELEASE_CHANNEL, [join(directory, "latest.json")]);
  await api("PATCH", `releases/${feed.id}`, { draft: false, prerelease: true, make_latest: "false" });
  return { version, tag, channel: RELEASE_CHANNEL };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const [directory, tag, commit] = process.argv.slice(2);
    const release = await publishRelease({ directory, tag, commit, token: process.env.GH_TOKEN, repository: process.env.GITHUB_REPOSITORY });
    console.log(`${release.alreadyCurrent ? "Already published" : "Published"} ${release.tag}; ${release.channel} now points to ${release.version}. PyQt latest release unchanged.`);
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
