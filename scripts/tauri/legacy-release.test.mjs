import { strict as assert } from "node:assert";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { runInNewContext } from "node:vm";

const bash = process.platform === "win32"
  ? join(process.env.ProgramFiles || "C:/Program Files", "Git/bin/bash.exe")
  : "bash";

for (const name of ["release.yml", "release-linux.yml"]) {
  const workflow = readFileSync(new URL(`../../.github/workflows/${name}`, import.meta.url), "utf8").replaceAll("\r\n", "\n");
  const expression = workflow.match(/^    if: \|\n((?:      .*\n)+)/m)?.[1].trim();
  const guard = workflow.match(/      - name: Guard \| Keep PyQt releases separate from Tauri\n        env:\n          RELEASE_REF: \$\{\{ github\.ref_name \}\}\n        run: \|\n((?:          .*\n)+)/)?.[1].replace(/^          /gm, "");

  test(`${name}: only explicit manual runs can build legacy installers`, () => {
    const triggers = workflow.match(/^on:\n([\s\S]*?)^permissions:/m)?.[1];
    assert.ok(triggers);
    assert.deepEqual([...triggers.matchAll(/^  ([a-z_]+):/gm)].map(match => match[1]), ["workflow_dispatch"]);
    assert.ok(expression);
    for (const event_name of ["push", "workflow_run", "release"]) {
      assert.equal(runInNewContext(expression, {
        github: { event_name, ref_name: "legacy/pyqt6" },
        startsWith: (value, prefix) => value.startsWith(prefix),
      }), false);
    }
  });

  test(`${name}: the job excludes modern main and Tauri refs but permits legacy maintenance`, () => {
    assert.ok(expression);
    for (const [ref_name, expected] of [
      ["main", false],
      ["codex/tauri-migration", false],
      ["tauri-v1.0.1", false],
      ["tauri-stable", false],
      ["v1.60.2", true],
      ["legacy/pyqt6", true],
    ]) {
      assert.equal(runInNewContext(expression, {
        github: { event_name: "workflow_dispatch", ref_name },
        startsWith: (value, prefix) => value.startsWith(prefix),
      }), expected, ref_name);
    }
  });

  test(`${name}: the actual shell guard rejects renamed modern sources before packaging`, { skip: process.platform === "win32" && !existsSync(bash) }, t => {
    assert.ok(guard);
    assert.ok(workflow.indexOf("uses: actions/checkout@v4") < workflow.indexOf("name: Guard |"));
    assert.ok(workflow.indexOf("name: Guard |") < workflow.indexOf("name: Setup | Python"));
    const directory = mkdtempSync(join(tmpdir(), "datapyn-legacy-guard-"));
    t.after(() => rmSync(directory, { recursive: true, force: true }));
    for (const ref of ["main", "codex/tauri-migration", "tauri-v1.0.1", "tauri-stable"]) {
      const result = spawnSync(bash, ["-s"], { cwd: directory, input: guard, encoding: "utf8", env: { ...process.env, RELEASE_REF: ref } });
      assert.equal(result.status, 1, `${ref}: ${result.stderr}`);
      assert.match(result.stdout, /::error::/);
    }
    for (const ref of ["v1.60.2", "legacy/pyqt6"]) {
      const result = spawnSync(bash, ["-s"], { cwd: directory, input: guard, encoding: "utf8", env: { ...process.env, RELEASE_REF: ref } });
      assert.equal(result.status, 0, `${ref}: ${result.stderr}`);
    }
    mkdirSync(join(directory, "desktop/src-tauri"), { recursive: true });
    writeFileSync(join(directory, "desktop/src-tauri/tauri.conf.json"), "{}");
    const modern = spawnSync(bash, ["-s"], { cwd: directory, input: guard, encoding: "utf8", env: { ...process.env, RELEASE_REF: "renamed-modern-branch" } });
    assert.equal(modern.status, 1, modern.stderr);
    assert.match(modern.stdout, /::error::/);
  });
}
