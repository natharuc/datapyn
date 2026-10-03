import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const version = "8.4.0";
export const DOCKVIEW_PATCH_TARGETS = ["dist/package/main.esm.mjs", "dist/package/main.cjs.js"];
const fail = message => { throw new Error(`Dockview floating-pointer patch: ${message}`); };
export const sha256 = content => createHash("sha256").update(content).digest("hex");

// Upstream's HTML5 source already distinguishes moving a float from Shift+drag redocking.
// The pointer source must make the same distinction for mouse, retaining touch/pen long-press.
export const before = "\t\t\tisCancelled: () => {\n\t\t\t\tif (!resolveDndCapabilities(this.accessor.options).pointer) return true;\n\t\t\t\tif (this.group.api.location.type === \"edge\" && this.group.size === 0) return true;\n\t\t\t\treturn false;\n\t\t\t},";
export const after = "\t\t\tisCancelled: (event) => {\n\t\t\t\tif (event.pointerType === \"mouse\" && this.group.api.location.type === \"floating\" && this.isFloatingMoveHandle() && !event.shiftKey) return true;\n\t\t\t\tif (!resolveDndCapabilities(this.accessor.options).pointer) return true;\n\t\t\t\tif (this.group.api.location.type === \"edge\" && this.group.size === 0) return true;\n\t\t\t\treturn false;\n\t\t\t},";
export const patchDefinitionHash = () => sha256(JSON.stringify({ before, after }));

export function transformDockview(source) {
  if (source.split(before).length !== 2) fail("the exact upstream cancellation hook must occur once");
  return source.replace(before, after);
}

export function patchDockview(desktopRoot) {
  const packageRoot = resolve(desktopRoot, "node_modules/dockview-core");
  const installed = JSON.parse(readFileSync(resolve(packageRoot, "package.json"), "utf8"));
  const manifest = JSON.parse(readFileSync(resolve(desktopRoot, "patches/dockview-core-8.4.0-pointer-hashes.json"), "utf8"));
  if (installed.version !== version || manifest.version !== version) fail(`expected ${version}, found ${installed.version}`);
  if (installed.exports?.["."]?.import !== "./dist/package/main.esm.mjs" || installed.exports?.["."]?.require !== "./dist/package/main.cjs.js") fail("the active ESM/CommonJS entry points changed");
  if (manifest.patch_sha256 !== patchDefinitionHash()) fail("tracked patch digest mismatch");
  if (Object.keys(manifest.files).length !== DOCKVIEW_PATCH_TARGETS.length || DOCKVIEW_PATCH_TARGETS.some(path => !manifest.files[path])) fail("patch/manifest targets differ");
  const writes = [];
  // Validate BOTH published entry points before touching either, including on repeated installs.
  for (const path of DOCKVIEW_PATCH_TARGETS) {
    const target = resolve(packageRoot, path), local = relative(packageRoot, target);
    if (isAbsolute(local) || local.startsWith("..")) fail(`target escapes package: ${path}`);
    const expected = manifest.files[path], current = readFileSync(target), currentHash = sha256(current);
    if (currentHash === expected.patched) continue;
    if (currentHash !== expected.original) fail(`unexpected installed content: ${path}`);
    const patched = transformDockview(current.toString("utf8"));
    if (sha256(patched) !== expected.patched) fail(`patched digest mismatch: ${path}`);
    writes.push([target, patched]);
  }
  for (const [target, content] of writes) writeFileSync(target, content, "utf8");
  return writes.length;
}

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const count = patchDockview(desktopRoot);
  console.log(`Dockview ${version} floating-pointer patch: ${count ? `${count} verified files patched` : "already applied"}.`);
}
