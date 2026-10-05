import { strict as assert } from "node:assert";
import { spawn, spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { buildDebianPackage, debianLayout, linuxLauncher } from "./linux-package.mjs";
import { temporaryRelease } from "./release-fixtures.mjs";

const shell = process.platform === "win32" ? "C:/Program Files/Git/bin/bash.exe" : "/bin/sh";
const hasShell = existsSync(shell);
const posix = path => process.platform === "win32" ? path.replace(/^([A-Za-z]):/, (_, drive) => `/${drive.toLowerCase()}`).replaceAll("\\", "/") : path;
function launcherFixture(t, portable = false) {
  const directory = temporaryRelease(t);
  const seed = join(directory, "seed with spaces");
  mkdirSync(seed);
  const script = join(seed, "datapyn-tauri");
  writeFileSync(script, linuxLauncher({ portable }), { mode: 0o755 });
  const log = join(directory, "output.txt");
  const data = join(directory, "user data");
  const env = { ...process.env, HOME: posix(join(directory, "home")), XDG_DATA_HOME: posix(data), DATAPYN_TAURI_TEST_LOG: posix(log), ...(portable ? {} : { DATAPYN_TAURI_SEED_ROOT: posix(seed) }) };
  if (portable) delete env.DATAPYN_TAURI_SEED_ROOT;
  const app = label => `#!/bin/sh\nprintf '%s|%s|%s' '${label}' "$APPIMAGE_EXTRACT_AND_RUN" "$1" > "$DATAPYN_TAURI_TEST_LOG"\n`;
  return { directory, seed, script, log, data, env, app, managed: join(data, "datapyn-tauri/installation/DataPyn-Tauri.AppImage") };
}

for (const portable of [false, true]) test(`${portable ? "portable" : "Debian"} launcher uses a writable per-user AppImage, forwards arguments and preserves signed updates`, { skip: !hasShell }, t => {
  const fixture = launcherFixture(t, portable);
  writeFileSync(join(fixture.seed, "DataPyn-Tauri.AppImage"), fixture.app("initial"), { mode: 0o755 });
  const run = () => spawnSync(shell, [posix(fixture.script), "query with spaces.dpyn"], { env: fixture.env, encoding: "utf8", windowsHide: true });
  assert.equal(run().status, 0);
  assert.equal(readFileSync(fixture.log, "utf8"), "initial|1|query with spaces.dpyn");
  assert.ok(existsSync(fixture.managed));
  writeFileSync(fixture.managed, fixture.app("updated"));
  chmodSync(fixture.managed, 0o755);
  writeFileSync(join(fixture.seed, "DataPyn-Tauri.AppImage"), fixture.app("package-upgrade-seed"));
  assert.equal(run().status, 0);
  assert.equal(readFileSync(fixture.log, "utf8"), "updated|1|query with spaces.dpyn");
  assert.deepEqual(readdirSync(join(fixture.data, "datapyn-tauri/installation")), ["DataPyn-Tauri.AppImage"]);
});

test("launcher reports a missing seed in the same invocation and does not leave an incomplete installed application", { skip: !hasShell }, t => {
  const fixture = launcherFixture(t);
  const result = spawnSync(shell, [posix(fixture.script)], { env: fixture.env, encoding: "utf8", windowsHide: true });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /arquivo inicial ausente/);
  assert.equal(existsSync(fixture.managed), false);
});

test("concurrent initial launches leave one complete executable and no bootstrap files", { skip: !hasShell }, async t => {
  const fixture = launcherFixture(t);
  writeFileSync(join(fixture.seed, "DataPyn-Tauri.AppImage"), fixture.app("initial"), { mode: 0o755 });
  const runs = Array.from({ length: 8 }, () => new Promise((resolve, reject) => {
    const process = spawn(shell, [posix(fixture.script), "query"], { env: fixture.env, windowsHide: true, stdio: "ignore" });
    process.once("error", reject);
    process.once("close", resolve);
  }));
  assert.deepEqual(await Promise.all(runs), Array(8).fill(0));
  assert.equal(readFileSync(fixture.managed, "utf8"), fixture.app("initial"));
  assert.deepEqual(readdirSync(join(fixture.data, "datapyn-tauri/installation")), ["DataPyn-Tauri.AppImage"]);
});

test("Debian filesystem metadata, launcher, icon and application are isolated from the legacy datapyn package", t => {
  const directory = temporaryRelease(t);
  const image = join(directory, "initial.AppImage");
  writeFileSync(image, "appimage bytes");
  const layout = join(directory, "package");
  debianLayout({ directory: layout, appImage: image, version: "1.0.0" });
  assert.match(readFileSync(join(layout, "DEBIAN/control"), "utf8"), /Package: datapyn-tauri\nVersion: 1.0.0\nArchitecture: amd64/);
  assert.match(readFileSync(join(layout, "usr/bin/datapyn-tauri"), "utf8"), /\/usr\/lib\/datapyn-tauri/);
  assert.match(readFileSync(join(layout, "usr/share/applications/datapyn-tauri.desktop"), "utf8"), /Exec=datapyn-tauri %F/);
  assert.ok(existsSync(join(layout, "usr/share/icons/hicolor/256x256/apps/datapyn-tauri.png")));
  assert.equal(existsSync(join(layout, "usr/bin/datapyn")), false);
  assert.equal(existsSync(join(layout, "opt/datapyn")), false);
});

test("native Linux packaging produces an actual DEB with the expected package identity", { skip: process.platform !== "linux" }, t => {
  const directory = temporaryRelease(t);
  const image = join(directory, "initial.AppImage");
  writeFileSync(image, "dummy AppImage bytes");
  const output = join(directory, "DataPyn-Tauri.deb");
  buildDebianPackage({ appImage: image, version: "1.0.0", output });
  assert.ok(existsSync(output));
  const list = spawnSync("dpkg-deb", ["--contents", output], { encoding: "utf8" });
  assert.equal(list.status, 0);
  assert.match(list.stdout, /usr\/lib\/datapyn-tauri\/DataPyn-Tauri.AppImage/);
  assert.match(list.stdout, /usr\/bin\/datapyn-tauri/);
});
