import { describe, expect, it, vi } from "vitest";
import { OutputRevealTracker } from "./outputReveal";
import { WorkspaceController, type SessionDocument } from "./workspace";
import type { ResultRef, RuntimeEvent, RuntimeTransport } from "./runtime";

const result = (id = "result-1"): ResultRef => ({ result_id: id, variable_name: "df", row_count: 2, columns: [] });
const session = (id = "session-1"): SessionDocument => ({ id, title: id, blocks: [{ id: "block-1", block_name: "", language: "python", code: "print(1)", is_active: true, status: "idle" }], focusedBlockId: "block-1", results: [], variables: [], images: [], logs: [], busy: false, resultRevision: 0, modified: false, extras: {} });
const run = (s: SessionDocument, execution = "execution-1"): SessionDocument => ({ ...s, currentExecutionId: execution, blocks: s.blocks.map(block => ({ ...block, status: "running", error: undefined })) });
const fail = (s: SessionDocument): SessionDocument => ({ ...s, blocks: s.blocks.map(block => ({ ...block, status: "failed", error: "Syntax error" })) });

describe("Dock output reveals", () => {
  it("establishes a silent startup baseline for restored errors, tables and rich output", () => {
    const tracker = new OutputRevealTracker(), restored = { ...fail(session()), results: [result()], richOutputs: [{ type: "html", artifact_id: "saved", data: "saved" } as const] };
    expect(tracker.observe([restored], restored.id)).toBeUndefined();
    expect(tracker.observe([{ ...restored, title: "Renamed" }], restored.id)).toBeUndefined();
  });
  it("reveals each new failure once and keeps a closed output dock hidden while editing the failed block", () => {
    const tracker = new OutputRevealTracker(), baseline = session(), running = run(baseline), failed = fail(running);
    tracker.observe([baseline], baseline.id); tracker.observe([running], baseline.id);
    expect(tracker.observe([failed], baseline.id)?.panel).toBe("output");
    const edited = { ...failed, blocks: failed.blocks.map(block => ({ ...block, code: "corrected()" })) };
    expect(tracker.observe([edited], baseline.id)).toBeUndefined();
    expect(tracker.observe([{ ...edited, currentExecutionId: undefined, busy: false }], baseline.id)).toBeUndefined();
    const rerun = run(edited, "execution-2"); tracker.observe([rerun], baseline.id);
    expect(tracker.observe([fail(rerun)], baseline.id)?.panel).toBe("output");
  });
  it("consumes background completion and does not reopen docks when switching tabs", () => {
    const tracker = new OutputRevealTracker(), active = session(), background = session("background");
    tracker.observe([active, background], active.id);
    const completed = { ...background, results: [result()] };
    expect(tracker.observe([active, completed], active.id)).toBeUndefined();
    expect(tracker.observe([active, completed], completed.id)).toBeUndefined();
    expect(tracker.observe([active, { ...completed, results: [result()] }], completed.id)).toBeUndefined();
  });
  it("reveals renewed result data for a new execution even when the result id is reused, and deduplicates later updates", () => {
    const tracker = new OutputRevealTracker(), baseline = { ...session(), results: [result()] }, running = run(baseline);
    tracker.observe([baseline], baseline.id); tracker.observe([running], baseline.id);
    const completed = { ...running, resultRevision: 1, results: [result()] };
    expect(tracker.observe([completed], baseline.id)).toMatchObject({ panel: "results", rich: false });
    expect(tracker.observe([{ ...completed, resultRevision: 2, results: [result()] }], baseline.id)).toBeUndefined();
    const rerun = run(completed, "execution-2"); tracker.observe([rerun], baseline.id);
    expect(tracker.observe([{ ...rerun, resultRevision: 3, results: [result()] }], baseline.id)?.panel).toBe("results");
  });
  it("does not reveal retained old tables after a successful execution without new results", () => {
    const tracker = new OutputRevealTracker(), baseline = { ...session(), results: [result()] }, running = run(baseline);
    tracker.observe([baseline], baseline.id); tracker.observe([running], baseline.id);
    expect(tracker.observe([{ ...running, resultRevision: 1 }], baseline.id)).toBeUndefined();
  });
  it("selects new rich output once and recognizes a rebuilt list of the same artifact ids", () => {
    const tracker = new OutputRevealTracker(), baseline = session(), running = run(baseline);
    tracker.observe([baseline], baseline.id); tracker.observe([running], baseline.id);
    const rich = { ...running, resultRevision: 1, richOutputs: [{ type: "html", artifact_id: "chart-1", data: "chart" } as const] };
    expect(tracker.observe([rich], baseline.id)).toMatchObject({ panel: "results", rich: true });
    expect(tracker.observe([{ ...rich, richOutputs: rich.richOutputs.map(output => ({ ...output })) }], baseline.id)).toBeUndefined();
    const rerun = run(rich, "execution-2"); tracker.observe([rerun], baseline.id);
    expect(tracker.observe([{ ...rerun, resultRevision: 2, richOutputs: rich.richOutputs.map(output => ({ ...output })) }], baseline.id)?.rich).toBe(true);
  });
  it("clears baselines across profiles and forgets closed sessions", () => {
    const tracker = new OutputRevealTracker(), initial = session(); tracker.observe([initial], initial.id);
    tracker.clear(); expect(tracker.observe([{ ...initial, results: [result()] }], initial.id)).toBeUndefined();
    tracker.observe([], ""); expect(tracker.observe([fail(initial)], initial.id)).toBeUndefined();
  });
  it("observes real queue completion before execution ids are cleared and never replays output after edits", async () => {
    const requests: Record<string, unknown>[] = [];
    let listener: ((event: RuntimeEvent) => void) | undefined;
    const transport: RuntimeTransport = {
      request: async <T>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
        if (method === "system.info") return { protocol_version: 1, python_version: "3.12.0", capabilities: { languages: ["sql", "python"], qt: false } } as T;
        if (method === "execution.run") requests.push(params);
        return {} as T;
      },
      subscribe: async callback => { listener = callback; return () => {}; },
    };
    const controller = new WorkspaceController(transport, undefined, { nativePersistence: true }), tracker = new OutputRevealTracker(), reveals: string[] = [];
    const observe = () => { const state = controller.getSnapshot(), reveal = tracker.observe(state.sessions, state.activeId); if (reveal) reveals.push(reveal.panel); };
    const current = controller.session()!; controller.updateBlock(current.id, current.focusedBlockId, { code: "SELECT 1" }); observe();
    const unsubscribe = controller.subscribe(observe);
    try {
      const first = controller.runBlock(current.id, current.focusedBlockId); await vi.waitFor(() => expect(requests).toHaveLength(1));
      listener!({ event: "execution.finished", payload: { session_id: current.id, execution_id: String(requests[0].execution_id), status: "succeeded", duration_ms: 1, results: [result()], variables: [] } }); await first;
      expect(controller.session()!.currentExecutionId).toBeUndefined(); expect(reveals).toEqual(["results"]);
      controller.updateBlock(current.id, current.focusedBlockId, { code: "SELECT invalid" }); expect(reveals).toEqual(["results"]);
      const second = controller.runBlock(current.id, current.focusedBlockId); await vi.waitFor(() => expect(requests).toHaveLength(2));
      listener!({ event: "execution.finished", payload: { session_id: current.id, execution_id: String(requests[1].execution_id), status: "failed", duration_ms: 1, error: "Invalid SQL", results: [], variables: [] } }); await second;
      expect(reveals).toEqual(["results", "output"]);
      controller.updateBlock(current.id, current.focusedBlockId, { code: "SELECT corrected" }); expect(reveals).toEqual(["results", "output"]);
    } finally { unsubscribe(); controller.dispose(); }
  });
});
