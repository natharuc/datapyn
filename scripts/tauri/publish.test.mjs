import { strict as assert } from "node:assert";
import { readdirSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { completeRelease, temporaryRelease } from "./release-fixtures.mjs";
import { publishRelease, verifyPublishedFiles } from "./publish.mjs";
import { fileSha256 } from "./release.mjs";

function githubMock(options = {}) {
  const calls = [];
  return { calls, upload: async (tag, files) => calls.push({ upload: tag, files }), request: async (url, init = {}) => {
    const call = { method: init.method ?? "GET", url, body: init.body ? JSON.parse(init.body) : undefined };
    calls.push(call);
    if (url.includes("/releases/tags/tauri-stable")) return new Response(options.feed ? JSON.stringify(options.feed) : "{}", { status: options.feed ? 200 : 404 });
    if (url === "https://example.test/feed.json") return new Response(JSON.stringify(options.feedManifest), { status: 200 });
    if (url.includes("/releases/tags/tauri-v")) return new Response(options.existing ? JSON.stringify(options.existing) : "{}", { status: options.existing ? 200 : 404 });
    if (call.method === "POST") return new Response(JSON.stringify({ id: call.body.tag_name === "tauri-stable" ? 20 : 10 }), { status: 201 });
    if (call.method === "PATCH") return new Response(JSON.stringify({ id: 10 }), { status: 200 });
    throw new Error(`Unexpected GitHub mock request: ${url}`);
  } };
}

const options = (fixture, mock) => ({ directory: fixture.directory, tag: "tauri-v1.0.0", commit: "a".repeat(40), token: "private-token", request: mock.request, upload: mock.upload });
const published = fixture => ({ id: 10, draft: false, immutable: true, assets: readdirSync(fixture.directory).map(name => ({ name, size: statSync(join(fixture.directory, name)).size, digest: `sha256:${fileSha256(join(fixture.directory, name))}` })) });

test("publication uploads all versioned assets before publishing and promoting the isolated feed", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const mock = githubMock();
  assert.deepEqual(await publishRelease(options(fixture, mock)), { version: "1.0.0", tag: "tauri-v1.0.0", channel: "tauri-stable" });
  const mutations = mock.calls.filter(call => ["POST", "PATCH"].includes(call.method));
  assert.ok(mutations.length >= 4);
  assert.ok(mutations.every(call => call.body.make_latest === "false"));
  assert.equal(mutations.at(-1).body.prerelease, true);
  const uploads = mock.calls.filter(call => call.upload);
  assert.equal(uploads[0].upload, "tauri-v1.0.0");
  assert.ok(uploads[0].files.some(file => file.endsWith(".dmg")));
  assert.ok(uploads[0].files.some(file => file.endsWith(".deb")));
  assert.equal(uploads[1].upload, "tauri-stable");
  assert.deepEqual(uploads[1].files, [join(fixture.directory, "latest.json")]);
  assert.ok(mock.calls.findIndex(call => call.url?.endsWith("/releases/10") && call.method === "PATCH") < mock.calls.findIndex(call => call.upload === "tauri-stable"));
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

test("published Tauri releases cannot be overwritten or promoted twice", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const mock = githubMock({ existing: { id: 10, draft: false } });
  await assert.rejects(publishRelease(options(fixture, mock)), /already been published/);
  assert.ok(mock.calls.every(call => call.method === "GET"));
});

test("an older build cannot downgrade the feed or publish a partial version", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const newer = completeRelease(join(temporaryRelease(t), "newer"), "2.0.0");
  const mock = githubMock({ feed: { id: 20, draft: false, assets: [{ name: "latest.json", browser_download_url: "https://example.test/feed.json" }] }, feedManifest: newer.manifest });
  await assert.rejects(publishRelease(options(fixture, mock)), /newer version/);
  assert.ok(mock.calls.every(call => call.method === "GET"));
});

test("failed artifact upload leaves the draft unpublished and the current feed unchanged", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const mock = githubMock();
  await assert.rejects(publishRelease({ ...options(fixture, mock), upload: async () => { throw new Error("upload failed"); } }), /upload failed/);
  assert.ok(mock.calls.every(call => call.method !== "PATCH"));
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

test("a feed upload failure can resume without touching any published version asset", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const first = githubMock();
  await assert.rejects(publishRelease({ ...options(fixture, first), upload: async (tag, files) => {
    if (tag === "tauri-stable") throw new Error("feed network failure");
    first.calls.push({ upload: tag, files });
  } }), /feed network failure/);
  assert.ok(first.calls.some(call => call.method === "PATCH" && call.url.endsWith("/releases/10")));
  assert.ok(first.calls.every(call => !(call.method === "PATCH" && call.url.endsWith("/releases/20"))));
  const retry = githubMock({ existing: published(fixture), feed: { id: 20, draft: true } });
  assert.deepEqual(await publishRelease(options(fixture, retry)), { version: "1.0.0", tag: "tauri-v1.0.0", channel: "tauri-stable" });
  assert.deepEqual(retry.calls.filter(call => call.upload).map(call => call.upload), ["tauri-stable"]);
  assert.ok(retry.calls.every(call => call.method !== "POST" && !(call.method === "PATCH" && call.url.endsWith("/releases/10"))));
});

test("a completed promotion is idempotent only for the exact same published distribution", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const mock = githubMock({ existing: published(fixture), feed: { id: 20, draft: false, assets: [{ name: "latest.json", browser_download_url: "https://example.test/feed.json" }] }, feedManifest: fixture.manifest });
  assert.deepEqual(await publishRelease(options(fixture, mock)), { version: "1.0.0", tag: "tauri-v1.0.0", channel: "tauri-stable", alreadyCurrent: true });
  assert.ok(mock.calls.every(call => call.method === "GET"));
});

test("same-version releases with any changed or missing server digest never resume feed promotion", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  for (const field of ["digest", "size", "name"]) {
    const existing = published(fixture);
    existing.assets[0][field] = field === "size" ? 0 : "different";
    const mock = githubMock({ existing, feed: { id: 20, draft: true } });
    await assert.rejects(publishRelease(options(fixture, mock)), /different or unverifiable/);
    assert.ok(mock.calls.every(call => call.method === "GET"));
  }
});

test("a same-version feed with different signatures is rejected instead of replaced", async t => {
  const fixture = completeRelease(temporaryRelease(t));
  const feedManifest = structuredClone(fixture.manifest);
  feedManifest.platforms["windows-x86_64"].signature = "another-signer";
  const mock = githubMock({ existing: published(fixture), feed: { id: 20, draft: false, assets: [{ name: "latest.json", browser_download_url: "https://example.test/feed.json" }] }, feedManifest });
  await assert.rejects(publishRelease(options(fixture, mock)), /different signed artifacts/);
  assert.ok(mock.calls.every(call => call.method === "GET"));
});
