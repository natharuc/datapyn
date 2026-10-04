import { describe, expect, it } from "vitest";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
// @ts-expect-error Maintenance script is an independently executable Node module.
import { after, before, DOCKVIEW_PATCH_TARGETS, patchDockview, sha256 } from "../scripts/apply-dockview-patch.mjs";
// @ts-expect-error Maintenance script is an independently executable Node module.
import { reverseDockviewLifecycle } from "../scripts/apply-dockview-lifecycle-patch.mjs";

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packagePath = "node_modules/dockview-core", manifestName = "dockview-core-8.4.0-pointer-hashes.json";
const manifestText = readFileSync(join(desktop, "patches", manifestName), "utf8"), manifest = JSON.parse(manifestText);
const installed = { version: "8.4.0", exports: { ".": { import: "./dist/package/main.esm.mjs", require: "./dist/package/main.cjs.js" } } };

function fixture(test: (root: string) => void) {
  const root = mkdtempSync(join(tmpdir(), "datapyn-dockview-patch-"));
  try {
    mkdirSync(join(root, "patches")); mkdirSync(join(root, packagePath, "dist/package"), { recursive: true });
    writeFileSync(join(root, "patches", manifestName), manifestText);
    writeFileSync(join(root, packagePath, "package.json"), JSON.stringify(installed));
    for (const path of DOCKVIEW_PATCH_TARGETS) {
      const patched = readFileSync(join(desktop, packagePath, path), "utf8");
      expect(patched.split(after)).toHaveLength(2);
      const original = reverseDockviewLifecycle(patched).replace(after, before);
      expect(sha256(original)).toBe(manifest.files[path].original);
      writeFileSync(join(root, packagePath, path), original);
    }
    test(root);
  } finally {
    if (dirname(root) !== resolve(tmpdir()) || !basename(root).startsWith("datapyn-dockview-patch-")) throw new Error("Unexpected temporary fixture path");
    rmSync(root, { recursive: true, force: true });
  }
}

describe("Dockview floating pointer compatibility", () => {
  it("hands plain mouse drag to the floating move overlay, preserving Shift redocking and touch/pen long press", () => {
    // Execute the exact patched upstream hook, with its own lexical this and capability lookup.
    const source = after.trim().slice("isCancelled: ".length, -1);
    const cancellation = (location: string, options: { pointer?: boolean; moveHandle?: boolean; size?: number } = {}) => {
      const context = { accessor: { options }, group: { api: { location: { type: location } }, size: options.size ?? 1 }, isFloatingMoveHandle: () => options.moveHandle ?? true };
      return new Function("resolveDndCapabilities", `return (${source});`).call(context, () => ({ pointer: options.pointer ?? true })) as (event: { pointerType: string; shiftKey: boolean }) => boolean;
    };
    const event = (pointerType: string, shiftKey = false) => ({ pointerType, shiftKey });
    expect(cancellation("floating")(event("mouse"))).toBe(true);
    expect(cancellation("floating")(event("mouse", true))).toBe(false);
    expect(cancellation("floating")(event("touch"))).toBe(false);
    expect(cancellation("floating")(event("pen"))).toBe(false);
    expect(cancellation("floating", { moveHandle: false })(event("mouse"))).toBe(false);
    expect(cancellation("grid")(event("mouse"))).toBe(false);
    expect(cancellation("popout")(event("mouse"))).toBe(false);
    expect(cancellation("grid", { pointer: false })(event("touch"))).toBe(true);
    expect(cancellation("edge", { size: 0 })(event("touch"))).toBe(true);
  });

  it("patches both actual ESM and CommonJS exports once and is idempotent", () => fixture(root => {
    expect(patchDockview(root)).toBe(2);
    for (const path of DOCKVIEW_PATCH_TARGETS) expect(sha256(readFileSync(join(root, packagePath, path)))).toBe(manifest.files[path].patched);
    expect(patchDockview(root)).toBe(0);
  }));

  it("rejects unexpected CommonJS content before writing the valid ESM target", () => fixture(root => {
    const esm = join(root, packagePath, DOCKVIEW_PATCH_TARGETS[0]), original = readFileSync(esm);
    writeFileSync(join(root, packagePath, DOCKVIEW_PATCH_TARGETS[1]), "unknown upstream code\n");
    expect(() => patchDockview(root)).toThrow("unexpected installed content");
    expect(readFileSync(esm)).toEqual(original);
  }));

  it("fails closed on a dependency upgrade, changed exports, or changed patch definition", () => fixture(root => {
    const metadata = join(root, packagePath, "package.json");
    writeFileSync(metadata, JSON.stringify({ ...installed, version: "8.4.1" }));
    expect(() => patchDockview(root)).toThrow("expected 8.4.0, found 8.4.1");
    writeFileSync(metadata, JSON.stringify({ ...installed, exports: { ".": { import: "./new-entry.mjs" } } }));
    expect(() => patchDockview(root)).toThrow("active ESM/CommonJS entry points changed");
    writeFileSync(metadata, JSON.stringify(installed));
    writeFileSync(join(root, "patches", manifestName), JSON.stringify({ ...manifest, patch_sha256: "modified" }));
    expect(() => patchDockview(root)).toThrow("tracked patch digest mismatch");
  }));
});
