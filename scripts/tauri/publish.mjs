import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
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

export function runUploadProcess(command, args, env = process.env) {
  return new Promise((resolveProcess, reject) => {
    // Keep fetch sockets and timers responsive while gh sends large installers.
    const child = spawn(command, args, { shell: false, windowsHide: true, stdio: "inherit", env });
    child.once("error", reject);
    child.once("close", (code, signal) => code === 0 ? resolveProcess() : reject(new Error(`Upload process failed: ${signal ? `signal ${signal}` : `exit ${code}`}.`)));
  });
}

export async function githubRequest({ method, path, body, allowMissing = false, accept = "application/vnd.github+json", token, repository = RELEASE_REPOSITORY, request = fetch, wait = delay, decode = response => response.status === 204 ? undefined : response.json() }) {
  // GET is read-only. These PATCHes assign fixed release/asset fields and are
  // idempotent; POST creates resources and must never be retried blindly.
  const attempts = ["GET", "PATCH"].includes(method) ? 3 : 1;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    let failure;
    try {
      const response = await request(`https://api.github.com/repos/${repository}/${path}`, { method, signal: AbortSignal.timeout(30_000), headers: { Accept: accept, Authorization: `Bearer ${token}`, "X-GitHub-Api-Version": "2026-03-10", "Content-Type": "application/json" }, ...(body ? { body: JSON.stringify(body) } : {}) });
      if (response.status === 404 && allowMissing) {
        await response.body?.cancel().catch(() => undefined);
        return undefined;
      }
      if (!response.ok) {
        await response.body?.cancel().catch(() => undefined);
        failure = new Error(`HTTP ${response.status}.`);
        if (![408, 429, 500, 502, 503, 504].includes(response.status)) throw Object.assign(failure, { noRetry: true });
        throw failure;
      }
      return await decode(response);
    } catch (error) {
      failure = error;
      if (attempt === attempts || error.noRetry || error instanceof SyntaxError) {
        const code = error.cause?.code ?? error.code;
        const message = String(error.message).split(token).join("[redacted]");
        throw new Error(`GitHub ${method} ${path} failed after ${attempt} attempt${attempt === 1 ? "" : "s"}: ${message}${code ? ` (${code})` : ""}`, { cause: error });
      }
    }
    await wait(250 * 2 ** (attempt - 1));
  }
}

export function verifyExistingAssets(release, directory) {
  const names = readdirSync(directory).sort();
  const assets = release.assets ?? [];
  const matches = assets.length === names.length && new Set(assets.map(asset => asset.name)).size === assets.length && names.every(name => {
    const asset = assets.find(item => item.name === name);
    const path = join(directory, name);
    return asset && asset.size === statSync(path).size && asset.digest === `sha256:${fileSha256(path)}`;
  });
  if (!matches) throw new Error(release.draft ? "The Tauri draft has different or unverifiable assets and cannot be published." : "This Tauri version has already been published with different or unverifiable assets. Published artifacts cannot be replaced.");
}

export async function publishRelease({ directory, tag, commit, token, repository = RELEASE_REPOSITORY, request = fetch, upload, retryWait = delay }) {
  const version = releaseVersion(tag);
  const manifest = verifyPublishedFiles(directory);
  if (repository !== RELEASE_REPOSITORY || manifest.version !== version || !/^[a-f\d]{40}$/.test(commit ?? "") || !token) throw new Error("Only a matching tagged Tauri release can be published to the dedicated repository.");
  const api = (method, path, body, allowMissing = false, accept = "application/vnd.github+json", decode) => githubRequest({ method, path, body, allowMissing, accept, decode, token, repository, request, wait: retryWait });
  const versionReleases = new Map();
  const versionRelease = async (releaseTag, refresh = false) => {
    if (refresh || !versionReleases.has(releaseTag)) {
      let release = await api("GET", `releases/tags/${releaseTag}`, undefined, true);
      if (!release) {
        // GitHub may return 404 for a draft whose tag is created only when it
        // becomes public. Recover that draft by ID instead of creating another.
        for (let page = 1; ; page++) {
          const releases = await api("GET", `releases?per_page=100&page=${page}`);
          if (!Array.isArray(releases)) throw new Error("Could not list Tauri releases to recover an unpublished draft.");
          for (const candidate of releases) if (candidate.tag_name === releaseTag) {
            if (release) throw new Error("Multiple releases use this Tauri tag; publication was stopped.");
            release = candidate;
          }
          if (releases.length < 100) break;
        }
      }
      versionReleases.set(releaseTag, release);
    }
    return versionReleases.get(releaseTag);
  };
  const readManifest = async asset => {
    if (!Number.isSafeInteger(asset?.id) || !Number.isSafeInteger(asset.size) || asset.size <= 0 || asset.size > maximumManifestSize || !/^sha256:[a-f\d]{64}$/.test(asset.digest ?? "")) throw new Error("The feed manifest asset has missing or unverifiable metadata.");
    const bytes = await api("GET", `releases/assets/${asset.id}`, undefined, false, "application/octet-stream", async response => Buffer.from(await response.arrayBuffer()));
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
  const existingFeed = await versionRelease(RELEASE_CHANNEL);
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
  const uploadAssets = upload ?? (async (releaseTag, paths, { clobber = true } = {}) => {
    try { await runUploadProcess("gh", ["release", "upload", releaseTag, ...paths, "--repo", repository, ...(clobber ? ["--clobber"] : [])], { ...process.env, GH_TOKEN: token }); }
    catch (error) { throw new Error(`GitHub artifact upload failed for ${releaseTag}: ${error.message}`, { cause: error }); }
  });
  if (!existing || existing.draft) {
    if (existing && existing.target_commitish !== commit) throw new Error("The existing Tauri draft targets a different or unverified source commit; publication was stopped.");
    if (existing) {
      const expected = new Set(readdirSync(directory));
      const names = Array.isArray(existing.assets) ? existing.assets.map(asset => asset.name) : [];
      if (!Array.isArray(existing.assets) || new Set(names).size !== names.length || names.some(name => !expected.has(name))) throw new Error("The existing Tauri draft contains unexpected or duplicate assets; publication was stopped.");
    }
    const release = existing ?? await api("POST", "releases", { tag_name: tag, target_commitish: commit, name: `DataPyn Tauri ${version}`, body, draft: true, prerelease: false, make_latest: "false" });
    let complete = false;
    if (existing) {
      try { verifyExistingAssets(existing, directory); complete = true; }
      catch { /* A partial draft can resume its upload; public releases cannot. */ }
    }
    if (!complete) await uploadAssets(tag, readdirSync(directory).sort().map(name => join(directory, name)));
    // Validate fresh server metadata before making the version public. A
    // partial, altered or extra upload must stay a recoverable private draft.
    const verifiedDraft = await api("GET", `releases/${release.id}`);
    if (verifiedDraft?.id !== release.id || verifiedDraft.tag_name !== tag || verifiedDraft.draft !== true || verifiedDraft.target_commitish !== commit) throw new Error("The Tauri draft source or publication state changed; publication was stopped.");
    verifyExistingAssets(verifiedDraft, directory);
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
