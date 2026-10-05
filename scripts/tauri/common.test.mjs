import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import test from "node:test";
import { repoRoot, runtimeBuildEnvironment } from "./common.mjs";

test("runtime build activates console tools for its selected Python and preserves the ambient PATH", async () => {
  const directory = await mkdtemp(join(tmpdir(), "datapyn selected python "));
  try {
    const python = join(directory, process.platform === "win32" ? "python.exe" : "python");
    await writeFile(python, "test interpreter placeholder");
    const ambient = ["ambient-one", "ambient-two"].join(delimiter);
    const base = { DATAPYN_RUNTIME_PYTHON: python, PATH: ambient, UNRELATED: "preserved" };
    const env = runtimeBuildEnvironment(base);
    assert.equal(env.DATAPYN_RUNTIME_PYTHON, python);
    assert.equal(env.PATH.split(delimiter)[0], directory);
    const projectTools = join(repoRoot, ".venv", process.platform === "win32" ? "Scripts" : "bin");
    assert.equal(env.PATH.split(delimiter).includes(projectTools), existsSync(projectTools));
    assert.ok(env.PATH.endsWith(ambient));
    assert.equal(env.UNRELATED, "preserved");
    assert.equal(base.PATH, ambient);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("Windows Path casing remains one key while a custom interpreter is selected", async () => {
  const directory = await mkdtemp(join(tmpdir(), "datapyn-tooling-python-"));
  try {
    const python = join(directory, "custom-python");
    await writeFile(python, "test interpreter placeholder");
    const env = runtimeBuildEnvironment({ DATAPYN_RUNTIME_PYTHON: python, Path: "existing-tools" });
    assert.equal(env.Path.split(delimiter)[0], directory);
    assert.ok(env.Path.endsWith("existing-tools"));
    assert.equal(Object.hasOwn(env, "PATH"), false);
  } finally { await rm(directory, { recursive: true, force: true }); }
});
