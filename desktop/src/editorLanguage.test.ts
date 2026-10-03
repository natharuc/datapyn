import { describe, expect, it } from "vitest";
import { LanguageRequestGate, languageParams, mergeCompletions, type LanguageCompletion } from "./editorLanguage";
import type { RuntimeTransport } from "./runtime";
describe("editor language requests", () => {
  it("sends the focused block's database scope and cursor without changing indexes", () => {
    expect(languageParams({ variables: [], tables: [], sessionId: "s", connectionId: "c", database: "catalog", schema: "schema" }, { language: "sql", code: "SELECT a.", line: 1, column: 10 })).toMatchObject({ session_id: "s", connection_id: "c", database: "catalog", schema: "schema", line: 1, column: 10 });
  });
  it("rejects late completions after a newer keystroke or changed connection", async () => {
    const resolvers: Array<(value: { items: LanguageCompletion[] }) => void> = [];
    const transport = { request: () => new Promise((resolve) => resolvers.push(resolve as typeof resolvers[number])), subscribe: async () => () => {} } as RuntimeTransport;
    const gate = new LanguageRequestGate(), old = gate.complete(transport, {}, () => true), current = gate.complete(transport, {}, () => true);
    resolvers[1]({ items: [{ label: "current" }] }); expect(await current).toEqual([{ label: "current" }]); resolvers[0]({ items: [{ label: "old" }] }); expect(await old).toEqual([]);
    const changed = gate.complete(transport, {}, () => true); gate.invalidate(); resolvers[2]({ items: [{ label: "wrong_database" }] }); expect(await changed).toEqual([]);
  });
  it("lets contextual insert text win duplicates and bounds suggestion payloads", () => {
    expect(mergeCompletions([{ label: "orders", insert_text: '"orders"', detail: "server" }], [{ label: "orders", insert_text: '"orders"' }, { label: "SELECT" }])).toHaveLength(2);
    expect(mergeCompletions(Array.from({ length: 2000 }, (_, i) => ({ label: String(i) })), [])).toHaveLength(1000);
  });
});
