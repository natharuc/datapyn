import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import test from "node:test";
import { repoRoot } from "./common.mjs";
import { prepareWindowsPrerequisites, verifyPrerequisiteHash } from "./windows-prerequisites.mjs";
import { pruneEmptyAppleEnvironment } from "./build-environment.mjs";

test("missing Apple secrets stay absent while valid signing identities survive", () => {
  const env = { APPLE_CERTIFICATE: "", APPLE_CERTIFICATE_PASSWORD: "", APPLE_API_KEY: "", APPLE_SIGNING_IDENTITY: "-", APPLE_TEAM_ID: "team", OTHER_EMPTY: "" };
  assert.deepEqual(pruneEmptyAppleEnvironment(env), { APPLE_SIGNING_IDENTITY: "-", APPLE_TEAM_ID: "team", OTHER_EMPTY: "" });
});

test("prerequisite SHA256 rejects modified and accepts exact bytes", async () => {
  const directory = await mkdtemp(join(tmpdir(), "datapyn-odbc-hash-"));
  try {
    const path = join(directory, "artifact.dat");
    await writeFile(path, "original");
    const expected = createHash("sha256").update("original").digest("hex");
    await verifyPrerequisiteHash(path, expected);
    await writeFile(path, "changed");
    await assert.rejects(verifyPrerequisiteHash(path, expected), /SHA256/);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("Linux/macOS and builds without installers do not fetch Windows prerequisites", async () => {
  assert.equal(await prepareWindowsPrerequisites([], { platform: "linux" }), undefined);
  assert.equal(await prepareWindowsPrerequisites([], { platform: "darwin" }), undefined);
  assert.equal(await prepareWindowsPrerequisites(["--no-bundle"], { platform: "win32" }), undefined);
});

test("unsupported Windows architecture cannot receive an x64 prerequisite", async () => {
  await assert.rejects(prepareWindowsPrerequisites([], { platform: "win32", target: "aarch64-pc-windows-msvc" }), /ODBC x64/);
});

test("Windows bootstrap prevents untrusted elevation and preserves installer outcomes", { skip: process.platform !== "win32" }, async () => {
  const directory = await mkdtemp(join(tmpdir(), "datapyn-odbc-bootstrap-"));
  try {
    const { stdout } = await promisify(execFile)("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
      join(repoRoot, "scripts", "tauri", "windows-prerequisites.test.ps1"),
      "-BootstrapPath", join(repoRoot, "desktop", "src-tauri", "windows", "install-odbc.ps1"), "-TestDirectory", directory], { windowsHide: true });
    const cases = Object.fromEntries(JSON.parse(stdout.trim()).map(item => [item.scenario, item]));
    for (const scenario of ["existing-driver", "check-only-missing", "tampered-installer", "unsigned-installer", "wrong-publisher"]) assert.equal(cases[scenario].starts, 0);
    assert.equal(cases["existing-driver"].code, 0);
    assert.equal(cases["check-only-missing"].code, 10);
    for (const scenario of ["tampered-installer", "unsigned-installer", "wrong-publisher", "driver-not-registered", "msi-failed"]) assert.equal(cases[scenario].code, 1603);
    assert.equal(cases["approved-install"].code, 0);
    assert.equal(cases["approved-install"].starts, 1);
    const process = cases["approved-install"].process;
    assert.match(process.file, /System32\\msiexec\.exe$/i);
    assert.equal(process.verb, "RunAs");
    assert.equal(process.style, "Hidden");
    assert.equal(process.wait, true);
    assert.equal(process.passThru, true);
    assert.ok(process.arguments.includes("/norestart"));
    assert.equal(cases["reboot-required"].code, 3010);
    assert.equal(cases["uac-cancelled"].code, 1223);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("installer acceptance refuses user/self-hosted machines and preserves NSIS path argument rules", { skip: process.platform !== "win32" }, async () => {
  const directory = await mkdtemp(join(tmpdir(), "datapyn-installer-guard-"));
  try {
    const { stdout } = await promisify(execFile)("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
      join(repoRoot, "scripts", "tauri", "windows-installation-guard.test.ps1"),
      "-ScriptPath", join(repoRoot, "scripts", "tauri", "smoke_windows_installation.ps1"), "-TestDirectory", directory], { windowsHide: true });
    const report = JSON.parse(stdout.trim());
    assert.equal(report.parsed, true);
    assert.deepEqual(new Set(report.rejected), new Set(["GITHUB_ACTIONS", "RUNNER_ENVIRONMENT", "RUNNER_OS", "RUNNER_ARCH", "RUNNER_TEMP", "filesystem-root"]));
    assert.equal(report.install.at(-1), `/D=${join(directory, "DataPyn Tauri with spaces")}`);
    assert.equal(report.install.at(-1).includes('"'), false);
    assert.equal(report.uninstall.at(-1), `_?=${join(directory, "DataPyn Tauri with spaces")}`);
    assert.ok(report.install.includes("/S"));
    assert.ok(report.uninstall.includes("/S"));
  } finally { await rm(directory, { recursive: true, force: true }); }
});
