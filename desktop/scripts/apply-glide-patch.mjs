import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packagePrefix = "node_modules/@glideapps/glide-data-grid/";
const fail = message => { throw new Error(`Glide native-popout patch: ${message}`); };
export const sha256 = content => createHash("sha256").update(content).digest("hex");

/** Only the pinned unified patch format is accepted: no fuzzy offsets or partial writes. */
export function parsePatch(content) {
  const files = [];
  let file, hunk;
  for (const line of content.replace(/\r\n/g, "\n").split("\n")) {
    if (line.startsWith("diff --git ")) { file = undefined; hunk = undefined; }
    else if (line.startsWith("+++ b/")) {
      const path = line.slice(6);
      if (!path.startsWith(packagePrefix)) fail(`unexpected path ${path}`);
      const target = path.slice(packagePrefix.length);
      if (!target.startsWith("dist/") || target.split("/").some(part => part === ".." || part === "." || !part)) fail(`unsafe path ${target}`);
      file = { path: target, hunks: [] };
      files.push(file);
    }
    else if (line.startsWith("@@ ")) {
      const match = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(line);
      if (!file || !match) fail("invalid hunk header");
      hunk = { oldStart: Number(match[1]), oldCount: Number(match[2] ?? 1), newStart: Number(match[3]), newCount: Number(match[4] ?? 1), lines: [] };
      file.hunks.push(hunk);
    }
    else if (hunk && /^[ +\-]/.test(line)) hunk.lines.push(line);
    else if (line === "\\ No newline at end of file") {
      const operation = hunk?.lines.at(-1)?.[0];
      if (!operation) fail("orphan newline marker");
      if (operation !== "+") hunk.oldNoNewline = true;
      if (operation !== "-") hunk.newNoNewline = true;
    }
  }
  if (!files.length || new Set(files.map(file => file.path)).size !== files.length) fail("empty patch or duplicate targets");
  return files;
}

export function applyHunks(source, hunks) {
  const input = source === "" ? [] : source.split("\n");
  if (input.length) {
    if (input.at(-1) === "") input.pop();
  }
  const output = [];
  let cursor = 0;
  for (const hunk of hunks) {
    const start = Math.max(0, hunk.oldStart - 1);
    if (start < cursor || start > input.length) fail("invalid hunk position");
    output.push(...input.slice(cursor, start)); cursor = start;
    if (output.length !== Math.max(0, hunk.newStart - 1)) fail("new hunk position mismatch");
    let removed = 0, added = 0;
    for (const line of hunk.lines) {
      const op = line[0], value = line.slice(1);
      if (op !== "+") {
        if (input[cursor] !== value) fail(`context mismatch at line ${cursor + 1}`);
        cursor++; removed++;
      }
      if (op !== "-") { output.push(value); added++; }
    }
    if (removed !== hunk.oldCount || added !== hunk.newCount) fail("hunk size mismatch");
  }
  output.push(...input.slice(cursor));
  const finalNewline = !hunks.some(hunk => hunk.newNoNewline) && (source === "" || source.endsWith("\n") || hunks.some(hunk => hunk.oldNoNewline));
  return output.join("\n") + (finalNewline ? "\n" : "");
}

export function patchGlide(desktopRoot) {
  const packageRoot = resolve(desktopRoot, packagePrefix);
  const manifest = JSON.parse(readFileSync(resolve(desktopRoot, "patches/glide-6.0.3-hashes.json"), "utf8"));
  const installed = JSON.parse(readFileSync(resolve(packageRoot, "package.json"), "utf8"));
  if (installed.version !== "6.0.3" || manifest.version !== "6.0.3") fail(`expected 6.0.3, found ${installed.version}`);
  const patch = readFileSync(resolve(desktopRoot, "patches/@glideapps+glide-data-grid+6.0.3.patch"), "utf8");
  if (sha256(patch.replace(/\r\n/g, "\n")) !== manifest.patch_sha256) fail("tracked patch digest mismatch");
  const files = parsePatch(patch), targets = Object.keys(manifest.files);
  if (files.length !== targets.length || files.some(file => !targets.includes(file.path))) fail("patch/manifest targets differ");
  const writes = [];
  // Validate every original and every generated result before writing any target.
  for (const file of files) {
    const target = resolve(packageRoot, file.path), local = relative(packageRoot, target);
    if (isAbsolute(local) || local.startsWith("..")) fail(`target escapes package: ${file.path}`);
    const expected = manifest.files[file.path];
    const current = existsSync(target) ? readFileSync(target) : undefined;
    const currentHash = current === undefined ? null : sha256(current);
    if (currentHash === expected.patched) continue;
    if (currentHash !== expected.original) fail(`unexpected installed content: ${file.path}`);
    const patched = applyHunks(current?.toString("utf8") ?? "", file.hunks);
    if (sha256(patched) !== expected.patched) fail(`patched digest mismatch: ${file.path}`);
    writes.push([target, patched]);
  }
  for (const [target, content] of writes) {
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, content, "utf8");
  }
  return writes.length;
}

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const count = patchGlide(desktopRoot);
  console.log(`Glide 6.0.3 native-popout patch: ${count ? `${count} verified files patched` : "already applied"}.`);
}
