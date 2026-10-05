import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join, resolve, sep } from "node:path";
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

const sha256 = bytes => createHash("sha256").update(bytes).digest("hex");
const transactionName = /^(?:latest-candidate|latest-backup)-v(\d+\.\d+\.\d+)-([a-f\d]{64})(?:-\d+)?\.json$/;
const maximumManifestSize = 256 * 1024;

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
  const apiResponse = async (method, path, body, allowMissing = false, accept = "application/vnd.github+json") => {
    const response = await request(`https://api.github.com/repos/${repository}/${path}`, { method, signal: AbortSignal.timeout(30_000), headers: { Accept: accept, Authorization: `Bearer ${token}`, "X-GitHub-Api-Version": "2026-03-10", "Content-Type": "application/json" }, ...(body ? { body: JSON.stringify(body) } : {}) });
    if (response.status === 404 && allowMissing) return undefined;
    if (!response.ok) throw new Error(`GitHub ${method} ${path} failed: HTTP ${response.status}.`);
    return response;
  };
  const api = async (...args) => { const response = await apiResponse(...args); return !response || response.status === 204 ? undefined : response.json(); };
  const versionReleases = new Map();
  const versionRelease = async (releaseTag, refresh = false) => {
    if (refresh || !versionReleases.has(releaseTag)) versionReleases.set(releaseTag, await api("GET", `releases/tags/${releaseTag}`, undefined, true));
    return versionReleases.get(releaseTag);
  };
  const readManifest = async asset => {
    if (!Number.isSafeInteger(asset?.id) || !Number.isSafeInteger(asset.size) || asset.size <= 0 || asset.size > maximumManifestSize || !/^sha256:[a-f\d]{64}$/.test(asset.digest ?? "")) throw new Error("The feed manifest asset has missing or unverifiable metadata.");
    const response = await apiResponse("GET", `releases/assets/${asset.id}`, undefined, false, "application/octet-stream");
    const bytes = Buffer.from(await response.arrayBuffer());
    const hash = sha256(bytes);
    if (bytes.length !== asset.size || `sha256:${hash}` !== asset.digest) throw new Error("The remote feed manifest does not match its SHA-256 digest.");
    const document = validateManifest(JSON.parse(bytes.toString("utf8")), { complete: true });
    const transaction = transactionName.exec(asset.name);
    if (transaction && (transaction[1] !== document.version || transaction[2] !== hash)) throw new Error("The retained feed manifest does not match its transaction name.");
    return { asset, manifest: document, bytes, hash };
  };
  const readPublishedManifest = async asset => {
    const retained = await readManifest(asset);
    const release = await versionRelease(`tauri-v${retained.manifest.version}`);
    const publishedManifest = release?.assets?.find(item => item.name === "latest.json");
    if (!release || release.draft || publishedManifest?.size !== retained.bytes.length || publishedManifest?.digest !== `sha256:${retained.hash}`) throw new Error("The retained feed manifest does not match its published immutable Tauri version.");
    return retained;
  };
  const existingFeed = await api("GET", `releases/tags/${RELEASE_CHANNEL}`, undefined, true);
  if (existingFeed?.immutable) throw new Error("The tauri-stable feed must remain mutable; immutable releases cannot refresh latest.json.");
  // A previous interrupted rename can leave only a verified candidate or backup.
  // Older --clobber publishers left neither; recover from the highest published
  // Tauri version, never from the PyQt /releases/latest channel.
  let current;
  const active = existingFeed?.assets?.find(item => item.name === "latest.json");
  if (active) current = await readPublishedManifest(active);
  else {
    for (const asset of existingFeed?.assets ?? []) {
      if (!transactionName.test(asset.name)) continue;
      const retained = await readPublishedManifest(asset);
      if (!current || compareVersions(retained.manifest.version, current.manifest.version) > 0) current = retained;
    }
    if (!current) {
      let newest;
      for (let page = 1; ; page++) {
        const releases = await api("GET", `releases?per_page=100&page=${page}`);
        if (!Array.isArray(releases)) throw new Error("Could not list published Tauri releases to recover the feed.");
        for (const release of releases) {
          if (release.draft || !/^tauri-v\d+\.\d+\.\d+$/.test(release.tag_name ?? "")) continue;
          const releaseVersionValue = releaseVersion(release.tag_name);
          versionReleases.set(release.tag_name, release);
          if (!newest || compareVersions(releaseVersionValue, releaseVersion(newest.tag_name)) > 0) newest = release;
        }
        if (releases.length < 100) break;
      }
      if (newest) {
        const asset = newest.assets?.find(item => item.name === "latest.json");
        if (!asset) throw new Error("The newest published Tauri version has no manifest to recover the feed.");
        current = { ...await readPublishedManifest(asset), fromVersion: true };
      } else if (existingFeed && !existingFeed.draft) throw new Error("The existing Tauri feed has no verified published version from which to recover.");
    }
  }
  let feedAlreadyCurrent = false;
  if (current) {
    const comparison = compareVersions(version, current.manifest.version);
    if (comparison < 0) throw new Error("The Tauri stable feed only accepts a newer version; published versions are immutable.");
    if (comparison === 0) {
      if (!samePlatforms(manifest.platforms, current.manifest.platforms)) throw new Error("The current feed has the same Tauri version with different signed artifacts. It cannot be overwritten.");
      feedAlreadyCurrent = true;
    }
  }
  const existing = await versionRelease(tag);
  if (existing && !existing.draft) {
    // Resume feed promotion only after GitHub's digests prove that *every*
    // already-published byte matches this distribution, including its manifest,
    // checksums and signatures. Never reupload or edit the version release.
    verifyExistingAssets(existing, directory);
    if (feedAlreadyCurrent && active && !existingFeed.draft) return { version, tag, channel: RELEASE_CHANNEL, alreadyCurrent: true };
  } else if (feedAlreadyCurrent) throw new Error("The current feed points to a missing or unpublished Tauri version release.");
  const body = `${manifest.notes}\n\nInstalação independente do DataPyn PyQt6. Os artefatos e o canal de atualização desta release pertencem somente ao DataPyn Tauri.\n\n- Windows x86_64: instalador NSIS e ZIP portátil.\n- Linux x86_64: DEB, AppImage e tar.gz portátil.\n- macOS Apple Silicon: DMG e aplicação para o atualizador.\n\nConfira SHA256SUMS.txt para verificar os downloads.\n`;
  const uploadAssets = upload ?? ((releaseTag, paths, { clobber = true } = {}) => {
    const result = spawnSync("gh", ["release", "upload", releaseTag, ...paths, "--repo", repository, ...(clobber ? ["--clobber"] : [])], { shell: false, windowsHide: true, stdio: "inherit", env: { ...process.env, GH_TOKEN: token } });
    if (result.error || result.status !== 0) throw new Error(`GitHub artifact upload failed for ${releaseTag}.`);
  });
  if (!existing || existing.draft) {
    const release = existing ?? await api("POST", "releases", { tag_name: tag, target_commitish: commit, name: `DataPyn Tauri ${version}`, body, draft: true, prerelease: false, make_latest: "false" });
    await uploadAssets(tag, readdirSync(directory).sort().map(name => join(directory, name)));
    await api("PATCH", `releases/${release.id}`, { draft: false, body, make_latest: "false" });
    const published = await versionRelease(tag, true);
    if (!published || published.draft) throw new Error("The version release was not published; feed promotion was stopped.");
    verifyExistingAssets(published, directory);
  }
  const feed = existingFeed ?? await api("POST", "releases", { tag_name: RELEASE_CHANNEL, target_commitish: commit, name: "DataPyn Tauri — canal de atualizações", body: "Manifesto exclusivo do DataPyn Tauri. Os instaladores estão nas releases tauri-vX.Y.Z. Este canal não atualiza a versão PyQt6.", draft: true, prerelease: true, make_latest: "false" });
  const refreshFeed = () => api("GET", `releases/${feed.id}`);
  const renameAsset = async (asset, name) => {
    try { return await api("PATCH", `releases/assets/${asset.id}`, { name }); }
    catch (error) {
      // The request may have succeeded before its response was lost.
      const refreshed = await refreshFeed().catch(() => undefined);
      const renamed = refreshed?.assets?.find(item => item.id === asset.id && item.name === name && item.digest === asset.digest);
      if (renamed) return renamed;
      throw error;
    }
  };
  const prepareCandidate = async retained => {
    const name = `latest-candidate-v${retained.manifest.version}-${retained.hash}.json`;
    let candidate = (await refreshFeed()).assets?.find(item => item.name === name);
    if (!candidate) {
      const temporary = mkdtempSync(join(tmpdir(), "datapyn-tauri-feed-"));
      try {
        const path = join(temporary, name);
        writeFileSync(path, retained.bytes);
        try { await uploadAssets(RELEASE_CHANNEL, [path], { clobber: false }); }
        catch (error) {
          candidate = (await refreshFeed().catch(() => undefined))?.assets?.find(item => item.name === name);
          if (!candidate) throw error;
        }
      } finally {
        const resolved = resolve(temporary);
        if (!resolved.startsWith(resolve(tmpdir()) + sep) || !basename(resolved).startsWith("datapyn-tauri-feed-")) throw new Error("Refusing to clean a directory outside the temporary feed workspace.");
        rmSync(resolved, { recursive: true, force: true });
      }
      candidate ??= (await refreshFeed()).assets?.find(item => item.name === name);
    }
    const verified = await readPublishedManifest(candidate);
    if (verified.hash !== retained.hash) throw new Error("The prepared feed candidate differs from this verified distribution.");
    return verified;
  };
  const switchManifest = async candidate => {
    const fresh = await refreshFeed();
    const latest = fresh.assets?.find(item => item.name === "latest.json");
    if (latest?.id === candidate.asset.id) return;
    let backup;
    if (latest) {
      const previous = await readPublishedManifest(latest);
      if (compareVersions(previous.manifest.version, candidate.manifest.version) > 0 || (previous.manifest.version === candidate.manifest.version && !samePlatforms(previous.manifest.platforms, candidate.manifest.platforms))) throw new Error("The feed changed during publication; promotion was stopped to avoid replacement or downgrade.");
      const name = `latest-backup-v${previous.manifest.version}-${previous.hash}-${latest.id}.json`;
      backup = { ...latest, name };
    }
    try {
      if (backup) await renameAsset(latest, backup.name);
      await renameAsset(candidate.asset, "latest.json");
    } catch (error) {
      const retainedFeed = await refreshFeed().catch(() => undefined);
      const installed = retainedFeed?.assets?.find(item => item.name === "latest.json");
      if (installed?.id === candidate.asset.id && installed.digest === candidate.asset.digest) return;
      if (!installed && backup) {
        try { await renameAsset(backup, "latest.json"); }
        catch { throw new Error(`${error.message} The verified previous manifest is retained as ${backup.name}; re-run this workflow to recover the interrupted promotion.`); }
      }
      throw error;
    }
  };
  if (!active && current) {
    // Repair an interrupted transaction before attempting a newer promotion.
    const recovered = current.fromVersion ? await prepareCandidate(current) : current;
    await switchManifest(recovered);
  }
  if (!feedAlreadyCurrent) {
    const bytes = readFileSync(join(directory, "latest.json"));
    await switchManifest(await prepareCandidate({ bytes, manifest, hash: sha256(bytes) }));
  }
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
