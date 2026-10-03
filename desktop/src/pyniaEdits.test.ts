import { describe, expect, it } from "vitest";
import { editCodeLines, validateWholeBlockReplace } from "./pyniaEdits";
describe("Pynia edits", () => {
  it("preserves unrelated lines and terminal newline during partial edits", () => { expect(editCodeLines("one\ntwo\nthree\n", 2, 2, "updated")).toBe("one\nupdated\nthree\n"); });
  it("supports insertion and deletion with the legacy 1-based indexes", () => { expect(editCodeLines("one\ntwo", 2, undefined, "new", "insert")).toBe("one\nnew\ntwo"); expect(editCodeLines("one\ntwo\nthree", 2, 2, "", "delete")).toBe("one\nthree"); });
  it("rejects invalid ranges rather than erasing the wrong lines", () => { expect(() => editCodeLines("one\ntwo", 0, 1, "bad")).toThrow(); expect(() => editCodeLines("one\ntwo", 1, 9, "bad")).toThrow(); expect(() => editCodeLines("one\ntwo", 1.5, 2, "bad")).toThrow(); });
  it("keeps the legacy guard against accidental whole-block truncation", () => { const original = Array.from({ length: 60 }, (_, i) => `line ${i}`).join("\n"); expect(() => validateWholeBlockReplace(original, "tiny snippet", false)).toThrow(); expect(() => validateWholeBlockReplace(original, "tiny snippet", true)).not.toThrow(); });
});
