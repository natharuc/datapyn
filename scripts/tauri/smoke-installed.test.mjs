import { strict as assert } from "node:assert";
import { mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { requireHostedRunner, smokeInstalled } from "./smoke-installed.mjs";
import { temporaryRelease } from "./release-fixtures.mjs";

test("installed-package acceptance refuses a local computer even if it has package tools", t => {
  const directory = temporaryRelease(t);
  for (const env of [{ RUNNER_TEMP: directory }, { GITHUB_ACTIONS: "true", RUNNER_OS: "Windows", RUNNER_TEMP: directory }, { GITHUB_ACTIONS: "false", RUNNER_OS: "Linux", RUNNER_TEMP: directory }]) assert.throws(() => requireHostedRunner(env, "linux"), /only on the matching GitHub/);
  assert.throws(() => requireHostedRunner({ GITHUB_ACTIONS: "true", RUNNER_OS: "Windows", RUNNER_TEMP: directory }, "win32"), /only on the matching GitHub/);
  assert.throws(() => requireHostedRunner({ GITHUB_ACTIONS: "true", RUNNER_ENVIRONMENT: "self-hosted", RUNNER_OS: "Linux", RUNNER_ARCH: "X64", RUNNER_TEMP: directory }, "linux"), /only on the matching GitHub/);
});

test("Linux acceptance extracts the actual Debian seed without launching the GUI and runs all four frozen smokes", t => {
  const root = temporaryRelease(t);
  const python = join(root, "python");
  writeFileSync(python, "mock Python");
  const env = { GITHUB_ACTIONS: "true", RUNNER_ENVIRONMENT: "github-hosted", RUNNER_OS: "Linux", RUNNER_ARCH: "X64", RUNNER_TEMP: root, DATAPYN_RUNTIME_PYTHON: python, APPIMAGE_EXTRACT_AND_RUN: "1" };
  const image = "same signed AppImage bytes";
  writeFileSync(join(root, "DataPyn-Tauri-1.0.0-linux-x86_64.AppImage"), image);
  const calls = [];
  smokeInstalled({ directory: root, version: "1.0.0", env, platform: "linux", execute: (command, args, options) => {
    calls.push({ command, args, options });
    if (command === "dpkg-deb") {
      const seed = join(args.at(-1), "usr/lib/datapyn-tauri");
      mkdirSync(seed, { recursive: true });
      writeFileSync(join(seed, "DataPyn-Tauri.AppImage"), image);
    } else if (args[0] === "--appimage-extract") {
      assert.equal(options.env.APPIMAGE_EXTRACT_AND_RUN, undefined);
      const runtime = join(options.cwd, "squashfs-root/usr/bin");
      mkdirSync(runtime, { recursive: true });
      writeFileSync(join(runtime, "datapyn-runtime"), "runtime");
    }
  } });
  assert.equal(calls.filter(call => call.command === python).length, 4);
  assert.ok(calls.filter(call => call.command === python).every(call => call.args[1] === "--executable"));
  assert.ok(readdirSync(root).every(name => !name.startsWith("datapyn-installed-")));
});

test("macOS acceptance detaches the DMG even when a runtime smoke fails", t => {
  const root = temporaryRelease(t);
  const python = join(root, "python");
  writeFileSync(python, "mock Python");
  const env = { GITHUB_ACTIONS: "true", RUNNER_ENVIRONMENT: "github-hosted", RUNNER_OS: "macOS", RUNNER_ARCH: "ARM64", RUNNER_TEMP: root, DATAPYN_RUNTIME_PYTHON: python };
  const calls = [];
  assert.throws(() => smokeInstalled({ directory: root, version: "1.0.0", env, platform: "darwin", execute: (command, args) => {
    calls.push({ command, args });
    if (command === "ditto") {
      const runtime = join(args[1], "Contents/MacOS");
      mkdirSync(runtime, { recursive: true });
      writeFileSync(join(runtime, "datapyn-runtime"), "runtime");
    }
    if (command === python) throw new Error("runtime failed");
  } }), /runtime failed/);
  assert.ok(calls.some(call => call.command === "hdiutil" && call.args[0] === "detach"));
  const attach = calls.find(call => call.command === "hdiutil" && call.args[0] === "attach");
  for (const flag of ["-readonly", "-nobrowse", "-noautoopen"]) assert.ok(attach.args.includes(flag));
  assert.ok(readdirSync(root).every(name => !name.startsWith("datapyn-installed-")));
});
