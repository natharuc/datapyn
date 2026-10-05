import { strict as assert } from "node:assert";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import { test } from "node:test";
import { completeRelease, temporaryRelease } from "./release-fixtures.mjs";
import { publishRelease, verifyPublishedFiles } from "./publish.mjs";
import { fileSha256 } from "./release.mjs";

const hash = bytes => createHash("sha256").update(bytes).digest("hex");
const candidateName = fixture => `latest-candidate-v${fixture.manifest.version}-${fileSha256(join(fixture.directory, "latest.json"))}.json`;
const published = fixture => ({ id: 9 + Number(fixture.manifest.version.split(".")[0]), tag_name: `tauri-v${fixture.manifest.version}`, draft: false, immutable: true, assets: readdirSync(fixture.directory).map(name => ({ name, size: statSync(join(fixture.directory, name)).size, digest: `sha256:${fileSha256(join(fixture.directory, name))}`, bytes: readFileSync(join(fixture.directory, name)) })) });
const activeFeed = (fixture, extras = []) => ({ id: 20, tag_name: "tauri-stable", draft: false, prerelease: true, assets: [{ name: "latest.json", bytes: readFileSync(join(fixture.directory, "latest.json")) }, ...extras] });

function githubMock(options = {}) {
  const calls = [], releases = new Map();
  let nextAssetId = 100;
  const json = (value, status = 200) => new Response(JSON.stringify(value, (key, item) => key === "bytes" ? undefined : item), { status });
  const addRelease = release => {
    release.assets ??= [];
    for (const asset of release.assets) {
      asset.id ??= nextAssetId++;
      asset.bytes ??= Buffer.from("asset");
      asset.size ??= asset.bytes.length;
      asset.digest ??= `sha256:${hash(asset.bytes)}`;
    }
    releases.set(release.tag_name, release);
    return release;
  };
  for (const version of options.versions ?? []) addRelease(version);
  if (options.existing) addRelease({ tag_name: "tauri-v1.0.0", ...options.existing });
  if (options.feed) addRelease({ tag_name: "tauri-stable", ...options.feed });
  const mock = {
    calls, releases, faults: {},
    feed: () => releases.get("tauri-stable"),
    upload: async (tag, files, { clobber = true } = {}) => {
      const call = { upload: tag, files, clobber };
      calls.push(call);
      const failure = mock.faults.upload?.(call);
      if (failure === "before") throw new Error("upload failed");
      const release = releases.get(tag);
      if (!release) throw new Error("Upload target is missing");
      for (const path of files) {
        const name = basename(path);
        const previous = release.assets.findIndex(item => item.name === name);
        if (previous >= 0) {
          if (!clobber) throw new Error("Refusing to replace an existing candidate");
          release.assets.splice(previous, 1);
        }
        const bytes = failure === "tamper" ? Buffer.from("unexpected bytes") : readFileSync(path);
        release.assets.push({ id: nextAssetId++, name, bytes, size: bytes.length, digest: `sha256:${hash(bytes)}` });
      }
      if (failure === "after") throw new Error("upload response lost");
    },
    request: async (url, init = {}) => {
      const call = { method: init.method ?? "GET", url, body: init.body ? JSON.parse(init.body) : undefined, accept: init.headers?.Accept };
      calls.push(call);
      if (mock.faults.request?.(call)) throw new Error("network unavailable");
      const path = url.replace("https://api.github.com/repos/natharuc/datapyn/", "");
      if (call.method === "GET" && path.startsWith("releases/tags/")) {
        const release = releases.get(path.slice("releases/tags/".length));
        return json(release ?? {}, release ? 200 : 404);
      }
      if (call.method === "GET" && path.startsWith("releases?")) {
        const page = Number(new URL(url).searchParams.get("page"));
        const versions = [...releases.values()].filter(release => !release.draft);
        return json(versions.slice((page - 1) * 100, page * 100));
      }
      const assetMatch = /^releases\/assets\/(\d+)$/.exec(path);
      if (assetMatch) {
        const release = [...releases.values()].find(item => item.assets.some(asset => asset.id === Number(assetMatch[1])));
        const asset = release?.assets.find(item => item.id === Number(assetMatch[1]));
        if (!asset) return json({}, 404);
        if (call.method === "GET") {
          assert.equal(call.accept, "application/octet-stream");
          return new Response(asset.bytes);
        }
        if (call.method === "PATCH") {
          const failure = mock.faults.rename?.(asset, call.body.name);
          if (failure === "before") return json({}, 500);
          if (release.assets.some(item => item.id !== asset.id && item.name === call.body.name)) return json({}, 422);
          asset.name = call.body.name;
          return failure === "after" ? json({}, 500) : json(asset);
        }
      }
      if (call.method === "POST" && path === "releases") return json(addRelease({ ...call.body, id: call.body.tag_name === "tauri-stable" ? 20 : 10, assets: [] }), 201);
      const releaseMatch = /^releases\/(\d+)$/.exec(path);
      if (releaseMatch) {
        const release = [...releases.values()].find(item => item.id === Number(releaseMatch[1]));
        if (!release) return json({}, 404);
        if (call.method === "GET") return json(release);
        if (call.method === "PATCH") { Object.assign(release, call.body); return json(release); }
      }
      throw new Error(`Unexpected GitHub mock request: ${url}`);
    },
  };
  return mock;
}

const options = (fixture, mock) => ({ directory: fixture.directory, tag: `tauri-v${fixture.manifest.version}`, commit: "a".repeat(40), token: "private-token", request: mock.request, upload: mock.upload });
const mutations = mock => mock.calls.filter(call => ["POST", "PATCH", "DELETE"].includes(call.method));
const active = mock => mock.feed()?.assets.find(asset => asset.name === "latest.json");
const previousRelease = t => completeRelease(join(temporaryRelease(t), "previous"), "0.9.0");

test("publication verifies versioned assets and a separate candidate before promoting the isolated feed", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const mock = githubMock();
  assert.deepEqual(await publishRelease(options(fixture, mock)), { version: "1.0.0", tag: "tauri-v1.0.0", channel: "tauri-stable" });
  const releaseChanges = mutations(mock).filter(call => !call.url.includes("/assets/"));
  assert.ok(releaseChanges.length >= 4);
  assert.ok(releaseChanges.every(call => call.body.make_latest === "false"));
  assert.equal(releaseChanges.at(-1).body.prerelease, true);
  const uploads = mock.calls.filter(call => call.upload);
  assert.equal(uploads[0].upload, "tauri-v1.0.0");
  assert.ok(uploads[0].files.some(file => file.endsWith(".dmg")));
  assert.ok(uploads[0].files.some(file => file.endsWith(".deb")));
  assert.equal(uploads[1].upload, "tauri-stable");
  assert.equal(uploads[1].clobber, false);
  assert.equal(basename(uploads[1].files[0]), candidateName(fixture));
  assert.ok(mock.calls.findIndex(call => call.url?.endsWith("/releases/10") && call.method === "PATCH") < mock.calls.findIndex(call => call.upload === "tauri-stable"));
  const candidateId = active(mock).id;
  assert.ok(mock.calls.findIndex(call => call.url?.endsWith(`/assets/${candidateId}`) && call.method === "GET") < mock.calls.findIndex(call => call.url?.endsWith(`/assets/${candidateId}`) && call.method === "PATCH"));
  assert.equal(active(mock).digest, `sha256:${fileSha256(join(fixture.directory, "latest.json"))}`);
  assert.ok(mock.calls.every(call => !call.url?.includes("/releases/latest")));
});

test("tampered release bytes stop publication before contacting GitHub", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const name = decodeURIComponent(fixture.manifest.platforms["windows-x86_64"].url.split("/").at(-1));
  writeFileSync(join(fixture.directory, name), "tampered executable");
  const mock = githubMock();
  await assert.rejects(publishRelease(options(fixture, mock)), /checksum mismatch/);
  assert.equal(mock.calls.length, 0);
});

test("published Tauri release bytes can never be overwritten", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const existing = published(fixture);
  existing.assets.find(asset => asset.name.endsWith(".exe")).digest = "sha256:" + "0".repeat(64);
  const mock = githubMock({ existing });
  await assert.rejects(publishRelease(options(fixture, mock)), /already been published/);
  assert.equal(mutations(mock).length, 0);
  assert.equal(mock.calls.filter(call => call.upload).length, 0);
});

test("an older build cannot downgrade the active feed", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const newer = completeRelease(join(temporaryRelease(t), "newer"), "2.0.0");
  const mock = githubMock({ feed: activeFeed(newer), versions: [published(newer)] });
  await assert.rejects(publishRelease(options(fixture, mock)), /newer version/);
  assert.equal(mutations(mock).length, 0);
});

test("failed version upload leaves its draft unpublished and the current feed unchanged", async t => {
  const fixture = completeRelease(temporaryRelease(t)), previous = previousRelease(t);
  const mock = githubMock({ feed: activeFeed(previous), versions: [published(previous)] });
  const oldId = active(mock).id;
  mock.faults.upload = () => "before";
  await assert.rejects(publishRelease(options(fixture, mock)), /upload failed/);
  assert.ok(mock.calls.every(call => call.method !== "PATCH"));
  assert.equal(active(mock).id, oldId);
  assert.equal(mock.calls.filter(call => call.method === "POST").length, 1);
});

test("unexpected repository, legacy tag or mismatched version is rejected before publication", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  for (const extra of [{ repository: "someone/another-project" }, { tag: "v1.57.0" }, { tag: "tauri-v1.0.1" }]) {
    const mock = githubMock();
    await assert.rejects(publishRelease({ ...options(fixture, mock), ...extra }));
    assert.equal(mock.calls.length, 0);
  }
  assert.equal(verifyPublishedFiles(fixture.directory).version, "1.0.0");
});

test("an immutable feed cannot be mutated accidentally", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const mock = githubMock({ feed: { id: 20, immutable: true } });
  await assert.rejects(publishRelease(options(fixture, mock)), /remain mutable/);
  assert.equal(mock.calls.length, 1);
});

test("a failed initial feed upload resumes without touching any published version asset", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const mock = githubMock();
  mock.faults.upload = call => call.upload === "tauri-stable" ? "before" : undefined;
  await assert.rejects(publishRelease(options(fixture, mock)), /upload failed/);
  assert.ok(mock.calls.some(call => call.method === "PATCH" && call.url.endsWith("/releases/10")));
  assert.equal(mock.feed().draft, true);
  mock.calls.length = 0;
  mock.faults.upload = undefined;
  assert.deepEqual(await publishRelease(options(fixture, mock)), { version: "1.0.0", tag: "tauri-v1.0.0", channel: "tauri-stable" });
  assert.deepEqual(mock.calls.filter(call => call.upload).map(call => call.upload), ["tauri-stable"]);
  assert.ok(mock.calls.every(call => call.method !== "POST" && !(call.method === "PATCH" && call.url.endsWith("/releases/10"))));
});

test("a completed promotion is idempotent only for the exact same published distribution", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const mock = githubMock({ existing: published(fixture), feed: activeFeed(fixture) });
  assert.deepEqual(await publishRelease(options(fixture, mock)), { version: "1.0.0", tag: "tauri-v1.0.0", channel: "tauri-stable", alreadyCurrent: true });
  assert.equal(mutations(mock).length, 0);
});

test("changed or missing server digest, size or name stops resuming a published distribution", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  for (const field of ["digest", "size", "name"]) {
    const existing = published(fixture);
    existing.assets.find(asset => asset.name.endsWith(".exe"))[field] = field === "size" ? 0 : "different";
    const mock = githubMock({ existing, feed: { id: 20, draft: true } });
    await assert.rejects(publishRelease(options(fixture, mock)), /different or unverifiable/);
    assert.equal(mutations(mock).length, 0);
  }
});

test("a same-version feed with different signed artifacts is never replaced", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const feedManifest = structuredClone(fixture.manifest);
  feedManifest.platforms["windows-x86_64"].signature = "another-signer";
  const changed = Buffer.from(JSON.stringify(feedManifest));
  const existing = published(fixture);
  Object.assign(existing.assets.find(asset => asset.name === "latest.json"), { bytes: changed, size: changed.length, digest: `sha256:${hash(changed)}` });
  const mock = githubMock({ existing, feed: { id: 20, draft: false, assets: [{ name: "latest.json", bytes: changed }] } });
  await assert.rejects(publishRelease(options(fixture, mock)), /different signed artifacts/);
  assert.equal(mutations(mock).length, 0);
});

test("a failed candidate upload preserves the active manifest instead of clobbering it", async t => {
  const fixture = completeRelease(temporaryRelease(t)), previous = previousRelease(t);
  const mock = githubMock({ existing: published(fixture), feed: activeFeed(previous), versions: [published(previous)] });
  const oldId = active(mock).id;
  mock.faults.upload = () => "before";
  await assert.rejects(publishRelease(options(fixture, mock)), /upload failed/);
  assert.equal(active(mock).id, oldId);
  assert.equal(mutations(mock).length, 0);
  assert.equal(mock.calls.find(call => call.upload).clobber, false);
});

test("a remotely tampered candidate stops promotion before renaming the old manifest", async t => {
  const fixture = completeRelease(temporaryRelease(t)), previous = previousRelease(t);
  const mock = githubMock({ existing: published(fixture), feed: activeFeed(previous), versions: [published(previous)] });
  const oldId = active(mock).id;
  mock.faults.upload = () => "tamper";
  await assert.rejects(publishRelease(options(fixture, mock)));
  assert.equal(active(mock).id, oldId);
  assert.equal(mutations(mock).length, 0);
});

test("successful promotion retains the previous verified manifest as a recoverable backup", async t => {
  const fixture = completeRelease(temporaryRelease(t)), previous = previousRelease(t);
  const mock = githubMock({ existing: published(fixture), feed: activeFeed(previous), versions: [published(previous)] });
  const oldId = active(mock).id;
  await publishRelease(options(fixture, mock));
  const backup = mock.feed().assets.find(asset => asset.id === oldId);
  assert.match(backup.name, /^latest-backup-v0\.9\.0-[a-f\d]{64}-\d+\.json$/);
  assert.equal(backup.digest, `sha256:${fileSha256(join(previous.directory, "latest.json"))}`);
  assert.equal(JSON.parse(active(mock).bytes).version, "1.0.0");
  assert.ok(mock.calls.every(call => call.method !== "DELETE"));
});

test("failed candidate rename rolls back immediately, then retries reuse the verified candidate", async t => {
  const fixture = completeRelease(temporaryRelease(t)), previous = previousRelease(t);
  const mock = githubMock({ existing: published(fixture), feed: activeFeed(previous), versions: [published(previous)] });
  const oldId = active(mock).id;
  mock.faults.rename = (asset, name) => asset.name.startsWith("latest-candidate") && name === "latest.json" ? "before" : undefined;
  await assert.rejects(publishRelease(options(fixture, mock)), /HTTP 500/);
  assert.equal(active(mock).id, oldId);
  assert.ok(mock.feed().assets.some(asset => asset.name === candidateName(fixture)));
  mock.calls.length = 0;
  mock.faults.rename = undefined;
  await publishRelease(options(fixture, mock));
  assert.equal(JSON.parse(active(mock).bytes).version, "1.0.0");
  assert.equal(mock.calls.filter(call => call.upload).length, 0);
  assert.ok(mock.calls.every(call => !(call.method === "PATCH" && call.url.endsWith("/releases/10"))));
});

test("interruption including failed rollback recovers the retained candidate without any reupload", async t => {
  const fixture = completeRelease(temporaryRelease(t)), previous = previousRelease(t);
  const mock = githubMock({ existing: published(fixture), feed: activeFeed(previous), versions: [published(previous)] });
  mock.faults.rename = (_asset, name) => name === "latest.json" ? "before" : undefined;
  await assert.rejects(publishRelease(options(fixture, mock)), /verified previous manifest is retained/);
  assert.equal(active(mock), undefined);
  assert.ok(mock.feed().assets.some(asset => asset.name.startsWith("latest-backup")));
  mock.calls.length = 0;
  mock.faults.rename = undefined;
  await publishRelease(options(fixture, mock));
  assert.equal(JSON.parse(active(mock).bytes).version, "1.0.0");
  assert.equal(mock.calls.filter(call => call.upload).length, 0);
});

test("lost API rename responses are reconciled instead of undoing an already successful promotion", async t => {
  const fixture = completeRelease(temporaryRelease(t)), previous = previousRelease(t);
  const mock = githubMock({ existing: published(fixture), feed: activeFeed(previous), versions: [published(previous)] });
  mock.faults.rename = () => "after";
  await publishRelease(options(fixture, mock));
  assert.equal(JSON.parse(active(mock).bytes).version, "1.0.0");
  assert.equal(mock.calls.filter(call => call.method === "PATCH" && call.url.includes("/assets/")).length, 2);
});

test("lost candidate upload response resumes from server digest proof without deleting or replacing bytes", async t => {
  const fixture = completeRelease(temporaryRelease(t)), previous = previousRelease(t);
  const mock = githubMock({ existing: published(fixture), feed: activeFeed(previous), versions: [published(previous)] });
  mock.faults.upload = () => "after";
  await publishRelease(options(fixture, mock));
  assert.equal(JSON.parse(active(mock).bytes).version, "1.0.0");
  assert.equal(mock.calls.filter(call => call.upload).length, 1);
});

test("missing latest.json from an older clobber publisher recovers from the newest immutable Tauri manifest", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const mock = githubMock({ existing: published(fixture), feed: { id: 20, draft: false }, versions: [{ id: 99, tag_name: "v99.0.0", draft: false, assets: [] }] });
  await publishRelease(options(fixture, mock));
  assert.equal(JSON.parse(active(mock).bytes).version, "1.0.0");
  assert.ok(mock.calls.every(call => !call.url?.includes("/releases/latest")));
  assert.ok(mock.calls.every(call => !(call.method === "PATCH" && call.url.endsWith("/releases/10"))));
});

test("missing or deleted feed cannot be recovered by an older version when a newer Tauri version exists", async t => {
  const fixture = completeRelease(temporaryRelease(t)), newer = completeRelease(join(temporaryRelease(t), "newer"), "2.0.0");
  for (const feed of [undefined, { id: 20, draft: false }]) {
    const mock = githubMock({ existing: published(fixture), feed, versions: [published(newer)] });
    await assert.rejects(publishRelease(options(fixture, mock)), /newer version/);
    assert.equal(mutations(mock).length, 0);
  }
});

test("newer retained candidate prevents recovery with an older local distribution", async t => {
  const fixture = completeRelease(temporaryRelease(t)), newer = completeRelease(join(temporaryRelease(t), "newer"), "2.0.0");
  const mock = githubMock({ existing: published(fixture), versions: [published(newer)], feed: { id: 20, draft: false, assets: [{ name: candidateName(newer), bytes: readFileSync(join(newer.directory, "latest.json")) }] } });
  await assert.rejects(publishRelease(options(fixture, mock)), /newer version/);
  assert.equal(mutations(mock).length, 0);
});

test("a retained backup alone restores the old feed before attempting a newer candidate upload", async t => {
  const fixture = completeRelease(temporaryRelease(t)), previous = previousRelease(t);
  const backup = { name: `latest-backup-v0.9.0-${fileSha256(join(previous.directory, "latest.json"))}-42.json`, bytes: readFileSync(join(previous.directory, "latest.json")) };
  const mock = githubMock({ existing: published(fixture), versions: [published(previous)], feed: { id: 20, draft: false, assets: [backup] } });
  mock.faults.upload = () => "before";
  await assert.rejects(publishRelease(options(fixture, mock)), /upload failed/);
  assert.equal(JSON.parse(active(mock).bytes).version, "0.9.0");
});

test("unverifiable retained candidates and backups never become an active feed", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  for (const alteration of ["digest", "transaction", "published-proof"]) {
    const retained = { name: candidateName(fixture), bytes: readFileSync(join(fixture.directory, "latest.json")) };
    if (alteration === "digest") retained.digest = "sha256:" + "0".repeat(64);
    if (alteration === "transaction") retained.name = retained.name.replace(/-[a-f\d]{64}\.json$/, "-" + "0".repeat(64) + ".json");
    const existing = published(fixture);
    if (alteration === "published-proof") existing.assets.find(asset => asset.name === "latest.json").digest = "sha256:" + "f".repeat(64);
    const mock = githubMock({ existing, feed: { id: 20, draft: false, assets: [retained] } });
    await assert.rejects(publishRelease(options(fixture, mock)));
    assert.equal(mutations(mock).length, 0);
    assert.equal(active(mock), undefined);
  }
});

test("recovery paginates past legacy releases to find the newest independent Tauri distribution", async t => {
  const fixture = completeRelease(temporaryRelease(t)), newer = completeRelease(join(temporaryRelease(t), "newer"), "2.0.0");
  const legacy = Array.from({ length: 100 }, (_, index) => ({ id: 1000 + index, tag_name: `v8.0.${index}`, draft: false, assets: [] }));
  const mock = githubMock({ versions: [...legacy, published(newer)], existing: published(fixture), feed: { id: 20, draft: false } });
  await assert.rejects(publishRelease(options(fixture, mock)), /newer version/);
  assert.ok(mock.calls.some(call => call.url?.includes("page=2")));
  assert.equal(mutations(mock).length, 0);
});

test("new version upload must match every published server digest before any feed mutation", async t => {
  const fixture = completeRelease(temporaryRelease(t)), previous = previousRelease(t);
  const mock = githubMock({ feed: activeFeed(previous), versions: [published(previous)] });
  const oldId = active(mock).id;
  mock.faults.upload = call => call.upload.startsWith("tauri-v") ? "tamper" : undefined;
  await assert.rejects(publishRelease(options(fixture, mock)), /different or unverifiable/);
  assert.equal(active(mock).id, oldId);
  assert.ok(mock.calls.every(call => call.upload !== "tauri-stable" && !(call.method === "PATCH" && call.url.includes("/assets/"))));
});

test("a feed advanced concurrently cannot be replaced by the prepared older candidate", async t => {
  const fixture = completeRelease(temporaryRelease(t)), previous = previousRelease(t), newer = completeRelease(join(temporaryRelease(t), "newer"), "2.0.0");
  const mock = githubMock({ existing: published(fixture), feed: activeFeed(previous), versions: [published(previous), published(newer)] });
  mock.faults.upload = () => {
    const bytes = readFileSync(join(newer.directory, "latest.json"));
    Object.assign(active(mock), { bytes, size: bytes.length, digest: `sha256:${hash(bytes)}` });
  };
  await assert.rejects(publishRelease(options(fixture, mock)), /feed changed/);
  assert.equal(JSON.parse(active(mock).bytes).version, "2.0.0");
  assert.equal(mutations(mock).length, 0);
});

test("publication interrupted after the first manifest rename retries without reuploading version or feed bytes", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const mock = githubMock();
  mock.faults.request = call => call.method === "PATCH" && call.url.endsWith("/releases/20");
  await assert.rejects(publishRelease(options(fixture, mock)), /network unavailable/);
  assert.equal(mock.feed().draft, true);
  assert.equal(JSON.parse(active(mock).bytes).version, "1.0.0");
  mock.calls.length = 0;
  mock.faults.request = undefined;
  await publishRelease(options(fixture, mock));
  assert.equal(mock.feed().draft, false);
  assert.equal(mock.feed().prerelease, true);
  assert.equal(mock.calls.filter(call => call.upload).length, 0);
  assert.deepEqual(mutations(mock).map(call => call.url.split("/").at(-1)), ["20"]);
});
