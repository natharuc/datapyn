import { strict as assert } from "node:assert";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import { signedConfiguration, updateManifest } from "./release.mjs";

test("signed build is opt-in and rejects incomplete or insecure channels", () => {
  assert.throws(() => signedConfiguration({}), /require/);
  const env = { DATAPYN_TAURI_UPDATER_PUBLIC_KEY: "public", DATAPYN_TAURI_UPDATER_ENDPOINT: "http://example.com/latest.json", TAURI_SIGNING_PRIVATE_KEY: "private" };
  assert.throws(() => signedConfiguration(env), /HTTPS/);
  const config = signedConfiguration({ ...env, DATAPYN_TAURI_UPDATER_ENDPOINT: "https://example.com/tauri-preview/latest.json" });
  assert.equal(config.bundle.createUpdaterArtifacts, true);
  assert.equal(JSON.stringify(config).includes("private"), false);
});
test("manifest requires actual signature and isolates the platform artifact", () => {
  const root = mkdtempSync(join(tmpdir(), "datapyn-signed-release-"));
  try {
    mkdirSync(join(root, "nsis"));
    writeFileSync(join(root, "nsis", "DataPyn setup.exe.sig"), "actual-signature");
    const manifest = updateManifest({ bundleDirectory: root, version: "1.58.0", platform: "windows-x86_64", artifactBaseUrl: "https://example.com/tauri-preview/v1.58.0" });
    assert.equal(manifest.platforms["windows-x86_64"].signature, "actual-signature");
    assert.match(manifest.platforms["windows-x86_64"].url, /DataPyn%20setup.exe$/);
    assert.throws(() => updateManifest({ bundleDirectory: root, version: "1.58.0", platform: "linux-x86_64", artifactBaseUrl: "https://example.com/releases" }), /one signed/);
  } finally { assert.ok(resolve(root).startsWith(resolve(tmpdir()) + sep) && root.includes("datapyn-signed-release-")); rmSync(root, { recursive: true, force: true }); }
});
