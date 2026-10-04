import { afterEach, describe, expect, it, vi } from "vitest";
import { SyntaxDiagnostics, normalizeLanguageMarkers, type DiagnosticResponse, type DiagnosticSource } from "./syntaxDiagnostics";
import type { RuntimeTransport } from "./runtime";
const issue = { start_line: 2, start_column: 5, end_line: 2, end_column: 6, message: "Esperado ':' após if.", severity: "error" };
function fixture() {
  const requests: Array<{ params: Record<string, unknown>; resolve: (value: DiagnosticResponse) => void; reject: (error: Error) => void }> = [];
  const request = vi.fn((method: string, params: Record<string, unknown> = {}) => method === "language.diagnostics.cancel" ? Promise.resolve({ cancelled: true }) : new Promise((resolve, reject) => requests.push({ params, resolve, reject })));
  const controller = new SyntaxDiagnostics({ request, subscribe: async () => () => {} } as RuntimeTransport);
  const params = vi.fn(() => ({ session_id: "s", locale: "pt-BR", shared_delimiter: "{{name}}" }));
  const source = (code = "if x", extra: Partial<DiagnosticSource> = {}): DiagnosticSource => ({ code, language: "python", contextKey: "scope1", ready: true, enabled: true, params, ...extra });
  return { controller, requests, request, params, source };
}
afterEach(() => vi.useRealTimers());
describe("per-block syntax diagnostics", () => {
  it("debounces typing without constructing source payloads and submits only the final text", async () => {
    vi.useFakeTimers(); const f = fixture();
    for (let i = 0; i < 50; i++) { f.controller.update("b", f.source(`value = ${i}`)); await vi.advanceTimersByTimeAsync(10); }
    expect(f.requests).toHaveLength(0); expect(f.params).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(450); expect(f.requests).toHaveLength(1);
    expect(f.requests[0].params).toMatchObject({ code: "value = 49", block_id: "b", language: "python", session_id: "s" }); f.controller.dispose();
  });
  it("caps all visible, offscreen and collapsed blocks at two RPCs and prioritizes the focused block", async () => {
    vi.useFakeTimers(); const f = fixture();
    for (let i = 0; i < 30; i++) f.controller.update(`b${i}`, f.source(`value = ${i}`, { focused: i === 29 }));
    await vi.advanceTimersByTimeAsync(450); expect(f.requests).toHaveLength(2); expect(f.requests[0].params.block_id).toBe("b29");
    f.requests[0].resolve({ markers: [] }); await vi.advanceTimersByTimeAsync(0); expect(f.requests).toHaveLength(3);
    expect(f.controller.snapshot("b29").status).toBe("complete"); f.controller.dispose();
  });
  it("cancels an obsolete revision and never revives its errors when it completes late", async () => {
    vi.useFakeTimers(); const f = fixture(); f.controller.update("b", f.source()); await vi.advanceTimersByTimeAsync(450);
    const old = f.requests[0]; f.controller.update("b", f.source("if x:\n    pass"));
    expect(f.request).toHaveBeenCalledWith("language.diagnostics.cancel", { session_id: "s", block_id: "b", diagnostic_id: old.params.diagnostic_id });
    expect(f.controller.snapshot("b").markers).toEqual([]); await vi.advanceTimersByTimeAsync(450);
    f.requests[1].resolve({ status: "complete", markers: [], duration_ms: 2 }); await vi.advanceTimersByTimeAsync(0);
    old.resolve({ markers: [issue] }); await vi.advanceTimersByTimeAsync(0);
    expect(f.controller.snapshot("b")).toMatchObject({ status: "complete", markers: [], durationMs: 2 }); f.controller.dispose();
  });
  it("does not reparse unchanged code after result output, focus or re-render", async () => {
    vi.useFakeTimers(); const f = fixture(); f.controller.update("b", f.source()); await vi.advanceTimersByTimeAsync(450);
    f.requests[0].resolve({ markers: [issue] }); await vi.advanceTimersByTimeAsync(0);
    const snapshot = f.controller.snapshot("b"); f.controller.update("b", f.source("if x", { focused: true })); await vi.advanceTimersByTimeAsync(1000);
    expect(f.requests).toHaveLength(1); expect(f.controller.snapshot("b")).toBe(snapshot); f.controller.dispose();
  });
  it.each(["sql", "python"] as const)("invalidates %s diagnostics on context/locale/dialect changes", async language => {
    vi.useFakeTimers(); const f = fixture(); f.controller.update("b", f.source("text", { language })); await vi.advanceTimersByTimeAsync(450);
    f.controller.update("b", f.source("text", { language, contextKey: "different-dialect-or-locale" })); await vi.advanceTimersByTimeAsync(450);
    f.requests[0].resolve({ markers: [issue] }); f.requests[1].resolve({ markers: [] }); await vi.advanceTimersByTimeAsync(0);
    expect(f.controller.snapshot("b")).toMatchObject({ status: "complete", markers: [] }); f.controller.dispose();
  });
  it("clears diagnostics on language changes, empty code and notebook text cells", async () => {
    vi.useFakeTimers(); const f = fixture(); f.controller.update("b", f.source()); await vi.advanceTimersByTimeAsync(450);
    f.requests[0].resolve({ markers: [issue] }); await vi.advanceTimersByTimeAsync(0);
    f.controller.update("b", f.source("SELECT 1", { language: "sql" })); expect(f.controller.snapshot("b").markers).toEqual([]);
    f.controller.update("b", f.source("markdown", { enabled: false })); await vi.advanceTimersByTimeAsync(450);
    expect(f.requests).toHaveLength(1); expect(f.controller.snapshot("b").status).toBe("idle");
    f.controller.update("b", f.source(" \n\t ")); await vi.advanceTimersByTimeAsync(450); expect(f.requests).toHaveLength(1); f.controller.dispose();
  });
  it("reports partial validation rather than valid syntax for limited documents", async () => {
    vi.useFakeTimers(); const f = fixture(); f.controller.update("huge", f.source("x".repeat(1024 * 1024 + 1)));
    expect(f.controller.snapshot("huge")).toMatchObject({ status: "partial", markers: [] }); expect(f.params).not.toHaveBeenCalled();
    f.controller.update("b", f.source()); await vi.advanceTimersByTimeAsync(450); f.requests[0].resolve({ status: "partial", markers: [], message: "Limite de análise atingido." }); await vi.advanceTimersByTimeAsync(0);
    expect(f.controller.snapshot("b")).toMatchObject({ status: "partial", message: "Limite de análise atingido." }); f.controller.dispose();
  });
  it("exposes service failure, supports retry and resumes after reconnect", async () => {
    vi.useFakeTimers(); const f = fixture(); f.controller.update("b", f.source("x", { ready: false })); expect(f.controller.snapshot("b").status).toBe("unavailable");
    f.controller.update("b", f.source("x")); await vi.advanceTimersByTimeAsync(450); f.requests[0].reject(new Error("offline")); await vi.advanceTimersByTimeAsync(0);
    expect(f.controller.snapshot("b")).toMatchObject({ status: "unavailable", message: "offline" });
    f.controller.refresh("b"); await vi.advanceTimersByTimeAsync(450); f.requests[1].resolve({ markers: [] }); await vi.advanceTimersByTimeAsync(0);
    expect(f.controller.snapshot("b").status).toBe("complete"); f.controller.dispose();
  });
  it("times out a stalled service without blocking the next block", async () => {
    vi.useFakeTimers(); const f = fixture(); f.controller.update("b", f.source()); f.controller.update("second", f.source()); f.controller.update("third", f.source());
    await vi.advanceTimersByTimeAsync(15_450); expect(f.controller.snapshot("b").status).toBe("unavailable"); expect(f.requests).toHaveLength(3);
    f.requests[0].resolve({ markers: [issue] }); await vi.advanceTimersByTimeAsync(0); expect(f.controller.snapshot("b").markers).toEqual([]); f.controller.dispose();
  });
  it("never leaves a current server-superseded revision spinning indefinitely", async () => {
    vi.useFakeTimers(); const f = fixture(); f.controller.update("b", f.source()); await vi.advanceTimersByTimeAsync(450);
    f.requests[0].resolve({ superseded: true, markers: [] }); await vi.advanceTimersByTimeAsync(0);
    expect(f.controller.snapshot("b")).toMatchObject({ status: "unavailable", markers: [] }); f.controller.refresh("b"); await vi.advanceTimersByTimeAsync(450);
    f.requests[1].resolve({ markers: [] }); await vi.advanceTimersByTimeAsync(0); expect(f.controller.snapshot("b").status).toBe("complete"); f.controller.dispose();
  });
  it("removes closed blocks and rejects their late results without affecting another block", async () => {
    vi.useFakeTimers(); const f = fixture(); f.controller.update("closed", f.source()); f.controller.update("keep", f.source()); await vi.advanceTimersByTimeAsync(450);
    f.controller.remove("closed"); f.requests[0].resolve({ markers: [issue] }); f.requests[1].resolve({ markers: [issue] }); await vi.advanceTimersByTimeAsync(0);
    expect(f.controller.snapshot("closed").status).toBe("idle"); expect(f.controller.snapshot("keep").markers).toEqual([issue]); f.controller.dispose();
  });
  it("bounds and validates marker payloads without changing Unicode UTF-16 coordinates", () => {
    const unicode = { ...issue, start_column: 13, end_column: 20, message: "x".repeat(2000) };
    const result = normalizeLanguageMarkers([unicode, { ...issue, start_line: NaN }, { ...issue, end_line: 1 }, ...Array.from({ length: 1000 }, () => issue)]);
    expect(result.length).toBeLessThanOrEqual(200); expect(result[0]).toMatchObject({ start_column: 13, end_column: 20 }); expect(result[0].message).toHaveLength(1000);
  });
});
