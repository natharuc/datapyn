import { strict as assert } from "node:assert";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { artifactBaseUrl, combineRelease, compareVersions, prepareWorkflowRequest, publishedReleaseExists, RELEASE_CHANNEL, RELEASE_PLATFORMS, releaseRequest, releaseVersion, signedConfiguration, stageRelease, UPDATE_ENDPOINT, updateManifest, validateManifest, verifyReleaseVersion, workflowRequest } from "./release.mjs";
import { completeRelease, fixturePlatforms, temporaryRelease } from "./release-fixtures.mjs";

test("signed builds cannot consume the PyQt latest release or leak a private key into configuration", () => {
  assert.throws(() => signedConfiguration({}), /require/);
  const env = { DATAPYN_TAURI_UPDATER_PUBLIC_KEY: "public", TAURI_SIGNING_PRIVATE_KEY: "private" };
  const embedded = { plugins: { updater: { pubkey: "public" } } };
  for (const endpoint of ["http://example.com/latest.json", "https://github.com/natharuc/datapyn/releases/latest/download/latest.json", "https://example.com/tauri/latest.json"]) assert.throws(() => signedConfiguration({ ...env, DATAPYN_TAURI_UPDATER_ENDPOINT: endpoint }, embedded), /isolated HTTPS/);
  const config = signedConfiguration(env, embedded);
  assert.equal(config.bundle.createUpdaterArtifacts, true);
  assert.deepEqual(config.plugins.updater.endpoints, [UPDATE_ENDPOINT]);
  assert.equal(JSON.stringify(config).includes("private"), false);
  assert.equal(signedConfiguration({ TAURI_SIGNING_PRIVATE_KEY: "private" }, embedded).plugins.updater.pubkey, "public");
  assert.throws(() => signedConfiguration({ ...env, DATAPYN_TAURI_UPDATER_PUBLIC_KEY: "another-key" }, embedded), /must match/);
});

test("Tauri tags use stable independent versions and reject legacy tags", () => {
  assert.equal(releaseVersion("tauri-v1.0.0"), "1.0.0");
  for (const tag of ["v1.57.0", "1.0.0", "tauri-stable", "tauri-v01.0.0", "tauri-v1.0.0-beta.1", "tauri-v1.0.0/other"]) assert.throws(() => releaseVersion(tag));
  assert.equal(compareVersions("1.10.0", "1.9.9"), 1);
  assert.equal(compareVersions("1.0.1", "2.0.0"), -1);
  assert.equal(compareVersions("1.0.0", "1.0.0"), 0);
});

test("migration branch pushes remain dry runs even if a publishing flag is present", () => {
  assert.deepEqual(releaseRequest({ eventName: "push", refType: "branch", refName: "codex/tauri-migration", currentVersion: "1.0.0", publish: true }), { tag: "tauri-v1.0.0", publish: false, build: true });
  assert.deepEqual(releaseRequest({ eventName: "push", refType: "tag", refName: "tauri-v1.0.1" }), { tag: "tauri-v1.0.1", publish: true, build: true });
  assert.deepEqual(releaseRequest({ eventName: "workflow_dispatch", inputTag: "tauri-v1.0.0" }), { tag: "tauri-v1.0.0", publish: false, build: true });
  assert.deepEqual(releaseRequest({ eventName: "workflow_dispatch", inputTag: "tauri-v1.0.0", publish: true }), { tag: "tauri-v1.0.0", publish: true, build: true });
  assert.throws(() => releaseRequest({ eventName: "push", refType: "tag", refName: "v1.57.0", publish: true }));
  assert.throws(() => releaseRequest({ eventName: "pull_request", publish: true }));
});

test("main publishes only a new synchronized Tauri version", () => {
  const event = { eventName: "push", refType: "branch", refName: "main", currentVersion: "1.0.1" };
  assert.deepEqual(releaseRequest({ ...event, tagExists: false }), { tag: "tauri-v1.0.1", publish: true, build: true });
  assert.deepEqual(releaseRequest({ ...event, tagExists: true, publish: true }), { tag: "tauri-v1.0.1", publish: false, build: false });
  assert.throws(() => releaseRequest(event), /verified version-tag lookup/);
  assert.throws(() => releaseRequest({ ...event, refName: "feature/other", tagExists: false }), /Unsupported/);
});

function workflowFixture(t) {
  const repositoryRoot = temporaryRelease(t);
  mkdirSync(join(repositoryRoot, "desktop/src-tauri"), { recursive: true });
  writeFileSync(join(repositoryRoot, "desktop/package.json"), JSON.stringify({ version: "1.0.1" }));
  writeFileSync(join(repositoryRoot, "desktop/src-tauri/Cargo.toml"), '[package]\nversion = "1.0.1"\n');
  writeFileSync(join(repositoryRoot, "desktop/src-tauri/tauri.conf.json"), JSON.stringify({ version: "1.0.1", identifier: "app.datapyn.tauri" }));
  const git = args => {
    const result = spawnSync("git", ["-c", "user.name=Release Test", "-c", "user.email=release-test@example.invalid", "-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false", ...args], { cwd: repositoryRoot, encoding: "utf8", shell: false, windowsHide: true });
    assert.equal(result.status, 0, result.stderr);
    return result.stdout.trim();
  };
  git(["init", "--initial-branch=main"]);
  git(["commit", "--allow-empty", "-m", "test: create workflow source"]);
  git(["update-ref", "refs/remotes/origin/main", "HEAD"]);
  const env = { GITHUB_EVENT_NAME: "push", GITHUB_REF_TYPE: "branch", GITHUB_REF_NAME: "main" };
  return { repositoryRoot, env, git };
}

test("workflow detects both lightweight and annotated existing tags and skips replacement builds", t => {
  const { repositoryRoot, env, git } = workflowFixture(t);
  const first = workflowRequest(env, repositoryRoot);
  assert.equal(first.version, "1.0.1");
  assert.equal(first.publish, true);
  assert.equal(first.build, true);
  assert.equal(first.commit, git(["rev-parse", "HEAD"]));
  git(["tag", "tauri-v1.0.1"]);
  assert.deepEqual(workflowRequest(env, repositoryRoot), { ...first, publish: false, build: false });
  git(["tag", "--delete", "tauri-v1.0.1"]);
  git(["tag", "--annotate", "tauri-v1.0.1", "--message", "Published version"]);
  assert.deepEqual(workflowRequest(env, repositoryRoot), { ...first, publish: false, build: false });
  assert.equal(workflowRequest({ ...env, GITHUB_REF_NAME: "codex/tauri-migration" }, repositoryRoot).build, true);
});

test("main publication fails for mismatched versions and sources outside the authorized branches", t => {
  const { repositoryRoot, env, git } = workflowFixture(t);
  writeFileSync(join(repositoryRoot, "desktop/package.json"), JSON.stringify({ version: "1.0.0" }));
  assert.throws(() => workflowRequest(env, repositoryRoot), /versions must match/);
  writeFileSync(join(repositoryRoot, "desktop/package.json"), JSON.stringify({ version: "1.0.1" }));
  git(["update-ref", "-d", "refs/remotes/origin/main"]);
  assert.throws(() => workflowRequest(env, repositoryRoot), /migration branch or main/);
});

test("tag pushes skip published versions, build new releases and fail closed when lookup fails", async t => {
  const { repositoryRoot, env } = workflowFixture(t);
  const tagEnv = { ...env, GITHUB_REF_TYPE: "tag", GITHUB_REF_NAME: "tauri-v1.0.1" };
  const first = workflowRequest(tagEnv, repositoryRoot);
  assert.deepEqual(await prepareWorkflowRequest(tagEnv, repositoryRoot, async tag => { assert.equal(tag, first.tag); return true; }), { ...first, publish: false, build: false });
  assert.deepEqual(await prepareWorkflowRequest(tagEnv, repositoryRoot, async () => false), first);
  await assert.rejects(prepareWorkflowRequest(tagEnv, repositoryRoot, async () => { throw new Error("API unavailable"); }), /API unavailable/);
  await assert.rejects(prepareWorkflowRequest(tagEnv, repositoryRoot, async () => undefined), /Could not verify/);
});

test("main and explicit dispatch retain their decisions without a published-release lookup", async t => {
  const { repositoryRoot, env } = workflowFixture(t);
  const unexpectedLookup = async () => { assert.fail("Only tag pushes query published releases"); };
  assert.deepEqual(await prepareWorkflowRequest(env, repositoryRoot, unexpectedLookup), workflowRequest(env, repositoryRoot));
  const dispatch = { ...env, GITHUB_EVENT_NAME: "workflow_dispatch", DATAPYN_RELEASE_TAG: "tauri-v1.0.1", DATAPYN_RELEASE_PUBLISH: "true" };
  const request = await prepareWorkflowRequest(dispatch, repositoryRoot, unexpectedLookup);
  assert.equal(request.build, true);
  assert.equal(request.publish, true);
});

test("read-only release lookup distinguishes public, draft and missing releases without accepting API errors", async () => {
  const tag = "tauri-v1.0.1";
  const token = "workflow-test-token";
  for (const [draft, expected] of [[false, true], [true, false]]) {
    const published = await publishedReleaseExists(tag, token, async (url, options) => {
      assert.equal(url, `https://api.github.com/repos/natharuc/datapyn/releases/tags/${tag}`);
      assert.equal(options.method, "GET");
      assert.equal(options.headers.Authorization, `Bearer ${token}`);
      return new Response(JSON.stringify({ tag_name: tag, draft }), { status: 200 });
    });
    assert.equal(published, expected);
  }
  assert.equal(await publishedReleaseExists(tag, token, async () => new Response(null, { status: 404 })), false);
  for (const status of [401, 403, 429, 500]) await assert.rejects(publishedReleaseExists(tag, token, async () => new Response(null, { status })), new RegExp(`HTTP ${status}`));
  for (const release of [{ tag_name: "tauri-v1.0.0", draft: false }, { tag_name: tag }, { tag_name: tag, draft: "false" }]) {
    await assert.rejects(publishedReleaseExists(tag, token, async () => new Response(JSON.stringify(release))), /response is invalid/);
  }
  await assert.rejects(publishedReleaseExists(tag, "", async () => { assert.fail("No unauthenticated lookup"); }), /read-only GitHub workflow token/);
});

test("release workflow fetches version tags and gates package builds on the version decision", () => {
  const workflow = readFileSync(new URL("../../.github/workflows/tauri-release.yml", import.meta.url), "utf8");
  assert.match(workflow, /branches:\s+ - "main"/);
  assert.match(workflow, /fetch-depth: 0\s+fetch-tags: true/);
  assert.match(workflow, /build: \$\{\{ steps\.release\.outputs\.build \}\}/);
  assert.match(workflow, /build:\s+needs: prepare\s+if: needs\.prepare\.outputs\.build == 'true'/);
  assert.match(workflow, /GH_TOKEN: \$\{\{ github\.token \}\}/);
});

test("tag verification checks only Tauri versions and its isolated application identity", t => {
  const root = temporaryRelease(t);
  mkdirSync(join(root, "desktop/src-tauri"), { recursive: true });
  writeFileSync(join(root, "pyproject.toml"), '[project]\nversion = "99.0.0"\n');
  writeFileSync(join(root, "desktop/package.json"), JSON.stringify({ version: "1.0.0" }));
  writeFileSync(join(root, "desktop/src-tauri/Cargo.toml"), '[package]\nversion = "1.0.0"\n');
  writeFileSync(join(root, "desktop/src-tauri/tauri.conf.json"), JSON.stringify({ version: "1.0.0", identifier: "app.datapyn.tauri" }));
  assert.equal(verifyReleaseVersion("tauri-v1.0.0", root), "1.0.0");
  assert.equal(readFileSync(join(root, "pyproject.toml"), "utf8"), '[project]\nversion = "99.0.0"\n');
  assert.throws(() => verifyReleaseVersion("tauri-v1.0.1", root), /must match/);
  writeFileSync(join(root, "desktop/src-tauri/tauri.conf.json"), JSON.stringify({ version: "1.0.0", identifier: "app.datapyn.desktop.preview" }));
  assert.throws(() => verifyReleaseVersion("tauri-v1.0.0", root), /isolated/);
});

for (const [platform, name] of [["windows-x86_64", "DataPyn setup.exe"], ["linux-x86_64", "DataPyn.AppImage"], ["darwin-aarch64", "DataPyn Tauri.app.tar.gz"]]) {
  test(`manifest binds the actual ${platform} artifact and signature to an immutable Tauri tag`, t => {
    const root = temporaryRelease(t);
    writeFileSync(join(root, name), "actual-artifact");
    writeFileSync(join(root, name + ".sig"), "actual-signature");
    const manifest = updateManifest({ bundleDirectory: root, version: "1.0.0", platform });
    assert.equal(manifest.channel, RELEASE_CHANNEL);
    assert.equal(manifest.platforms[platform].signature, "actual-signature");
    assert.equal(manifest.platforms[platform].url, `${artifactBaseUrl("1.0.0")}/${encodeURIComponent(name)}`);
    assert.equal(validateManifest(manifest), manifest);
    assert.throws(() => updateManifest({ bundleDirectory: root, version: "1.0.0", platform, artifactBaseUrl: "https://github.com/natharuc/datapyn/releases/download/v1.57.0" }), /immutable/);
    writeFileSync(join(root, name), "");
    assert.throws(() => updateManifest({ bundleDirectory: root, version: "1.0.0", platform }), /empty/);
  });
}

test("missing, empty and ambiguous update signatures fail instead of producing a partial release", t => {
  const root = temporaryRelease(t);
  const input = { bundleDirectory: root, version: "1.0.0", platform: "windows-x86_64" };
  assert.throws(() => updateManifest(input), /one signed/);
  writeFileSync(join(root, "one.exe.sig"), "sig");
  assert.throws(() => updateManifest(input), /missing/);
  writeFileSync(join(root, "one.exe"), "artifact");
  writeFileSync(join(root, "one.exe.sig"), "");
  assert.throws(() => updateManifest(input), /signature is empty/);
  writeFileSync(join(root, "two.exe.sig"), "sig2");
  assert.throws(() => updateManifest(input), /one signed/);
});

test("manifest validation rejects legacy channels, wrong platform assets, credentials and traversal", t => {
  const { manifest } = completeRelease(temporaryRelease(t));
  for (const url of ["https://github.com/natharuc/datapyn/releases/download/v1.57.0/DataPyn-Setup.exe", `${artifactBaseUrl("1.0.0")}/another.AppImage`, `${artifactBaseUrl("1.0.0")}/folder%2FDataPyn.exe`, `${artifactBaseUrl("1.0.0")}/DataPyn.exe?token=secret`]) assert.throws(() => validateManifest({ ...manifest, platforms: { ...manifest.platforms, "windows-x86_64": { signature: "sig", url } } }, { complete: true }));
  assert.throws(() => validateManifest({ ...manifest, channel: "pyqt-stable" }), /different channel/);
  assert.throws(() => validateManifest({ ...manifest, platforms: { "windows-x86_64": manifest.platforms["windows-x86_64"] } }, { complete: true }), /platform set/);
});

test("Windows staging renames bytes and signature together without producing PyQt-compatible asset names", t => {
  const root = temporaryRelease(t);
  const bundle = join(root, "bundle");
  mkdirSync(bundle);
  writeFileSync(join(bundle, "DataPyn Tauri_1.0.0_x64-setup.exe"), "original installer bytes");
  writeFileSync(join(bundle, "DataPyn Tauri_1.0.0_x64-setup.exe.sig"), "original-signature");
  const output = join(root, "staged");
  const manifest = stageRelease({ bundleDirectory: bundle, outputDirectory: output, version: "1.0.0", platform: "windows-x86_64", createPortable: false });
  assert.deepEqual(readdirSync(output).sort(), ["DataPyn-Tauri-1.0.0-windows-x86_64-setup.exe", "DataPyn-Tauri-1.0.0-windows-x86_64-setup.exe.sig", "manifest-windows-x86_64.json"].sort());
  assert.equal(readFileSync(join(output, "DataPyn-Tauri-1.0.0-windows-x86_64-setup.exe"), "utf8"), "original installer bytes");
  assert.equal(manifest.platforms["windows-x86_64"].signature, "original-signature");
});

test("publication requires all three platforms and preserves Linux/macOS installer formats", t => {
  const root = temporaryRelease(t);
  const { directory, manifest } = completeRelease(root);
  assert.deepEqual(Object.keys(manifest.platforms).sort(), [...RELEASE_PLATFORMS].sort());
  const files = readdirSync(directory);
  for (const suffix of ["-setup.exe", ".zip", ".deb", ".AppImage", ".tar.gz", ".dmg", ".app.tar.gz", "latest.json", "SHA256SUMS.txt"]) assert.ok(files.some(name => name.endsWith(suffix)), suffix);
  assert.equal(readFileSync(join(directory, "SHA256SUMS.txt"), "utf8").trim().split("\n").length, files.length - 1);
});

test("partial and mixed-version platform builds never promote a release", t => {
  const root = temporaryRelease(t);
  const input = fixturePlatforms(root);
  const path = join(input, "linux-x86_64", "manifest-linux-x86_64.json");
  const manifest = JSON.parse(readFileSync(path, "utf8"));
  writeFileSync(path, JSON.stringify({ ...manifest, version: "2.0.0" }));
  assert.throws(() => combineRelease({ inputDirectory: input, outputDirectory: join(root, "complete"), version: "1.0.0" }), /immutable|matching/);
  writeFileSync(path, JSON.stringify({ ...manifest, platforms: {} }));
  assert.throws(() => combineRelease({ inputDirectory: input, outputDirectory: join(root, "complete"), version: "1.0.0" }), /platform/);
});

test("publication retries generate byte-identical manifests and checksums from the original platform artifacts", t => {
  const root = temporaryRelease(t);
  const inputDirectory = fixturePlatforms(root);
  const first = join(root, "first");
  const retry = join(root, "retry");
  combineRelease({ inputDirectory, outputDirectory: first, version: "1.0.0" });
  combineRelease({ inputDirectory, outputDirectory: retry, version: "1.0.0" });
  assert.equal(readFileSync(join(first, "latest.json"), "utf8"), readFileSync(join(retry, "latest.json"), "utf8"));
  assert.equal(readFileSync(join(first, "SHA256SUMS.txt"), "utf8"), readFileSync(join(retry, "SHA256SUMS.txt"), "utf8"));
});
