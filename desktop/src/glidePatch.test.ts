import { describe, expect, it } from "vitest";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
// @ts-expect-error Maintenance script is an independently executable Node module.
import { applyHunks, parsePatch, patchGlide, sha256 } from "../scripts/apply-glide-patch.mjs";

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packagePath = "node_modules/@glideapps/glide-data-grid";
const patchName = "@glideapps+glide-data-grid+6.0.3.patch";
const patch = readFileSync(join(desktop,"patches",patchName),"utf8");
const manifest = JSON.parse(readFileSync(join(desktop,"patches/glide-6.0.3-hashes.json"),"utf8"));

function fixture(test: (root: string) => void) {
  const root = mkdtempSync(join(tmpdir(), "datapyn-glide-patch-"));
  try {
    mkdirSync(join(root,"patches")); mkdirSync(join(root,packagePath),{recursive:true});
    writeFileSync(join(root,"patches",patchName),patch);
    writeFileSync(join(root,"patches/glide-6.0.3-hashes.json"),JSON.stringify(manifest));
    writeFileSync(join(root,packagePath,"package.json"),JSON.stringify({version:"6.0.3"}));
    for (const file of parsePatch(patch)) {
      if(manifest.files[file.path].original===null)continue;
      const current=readFileSync(join(desktop,packagePath,file.path),"utf8");
      const hunks=file.hunks.map((hunk: {oldStart:number;oldCount:number;newStart:number;newCount:number;oldNoNewline?:boolean;newNoNewline?:boolean;lines:string[]})=>({
        oldStart:hunk.newStart,oldCount:hunk.newCount,newStart:hunk.oldStart,newCount:hunk.oldCount,
        oldNoNewline:hunk.newNoNewline,newNoNewline:hunk.oldNoNewline,
        lines:hunk.lines.map(line=>(line[0]==="+"?"-":line[0]==="-"?"+":" ")+line.slice(1))}));
      const original=applyHunks(current,hunks);
      expect(sha256(original)).toBe(manifest.files[file.path].original);
      mkdirSync(dirname(join(root,packagePath,file.path)),{recursive:true});writeFileSync(join(root,packagePath,file.path),original);
    }
    test(root);
  } finally {
    if(dirname(root)!==resolve(tmpdir())||!basename(root).startsWith("datapyn-glide-patch-"))throw new Error("Unexpected temporary fixture path");
    rmSync(root,{recursive:true,force:true});
  }
}

describe("strict Glide install patch",()=>{
  it("patches pristine 6.0.3 content once, preserves every expected hash, and is idempotent",()=>fixture(root=>{
    expect(patchGlide(root)).toBe(Object.keys(manifest.files).length);
    for(const [path,hashes] of Object.entries(manifest.files))expect(sha256(readFileSync(join(root,packagePath,path)))).toBe((hashes as {patched:string}).patched);
    expect(patchGlide(root)).toBe(0);
  }));
  it("rejects unexpected installed contents before writing any file",()=>fixture(root=>{
    const path="dist/esm/data-editor/data-editor.js",target=join(root,packagePath,path);
    writeFileSync(target,"unrecognized upstream code\n");
    const first=Object.keys(manifest.files)[0],before=readFileSync(join(root,packagePath,first));
    expect(()=>patchGlide(root)).toThrow("unexpected installed content");
    expect(readFileSync(join(root,packagePath,first))).toEqual(before);
    expect(existsSync(join(root,packagePath,"dist/esm/common/owner-document.js"))).toBe(false);
  }));
  it("refuses a dependency upgrade and refuses a changed patch digest",()=>fixture(root=>{
    writeFileSync(join(root,packagePath,"package.json"),JSON.stringify({version:"6.0.4"}));
    expect(()=>patchGlide(root)).toThrow("expected 6.0.3, found 6.0.4");
    writeFileSync(join(root,packagePath,"package.json"),JSON.stringify({version:"6.0.3"}));
    writeFileSync(join(root,"patches",patchName),patch+"\n");
    expect(()=>patchGlide(root)).toThrow("tracked patch digest mismatch");
  }));
});
