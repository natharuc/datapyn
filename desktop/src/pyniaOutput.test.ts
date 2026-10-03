import { describe, expect, it } from "vitest";
import { PyniaController, emptyPyniaState, type PyniaMessage, type PyniaState } from "./pynia";
import { cutPyniaOutput, outputToolStatus, pyniaOutputHistory } from "./pyniaOutput";
import type { RuntimeTransport } from "./runtime";

const response = (id: string, thinking = ""): PyniaMessage => ({ role: "assistant", content: "Answer", activity: { thinking, tools: [{ id, title: id, status: "completed" }] } });
const state = (fields: Partial<PyniaState> = {}): PyniaState => ({ ...emptyPyniaState(), ...fields });

describe("independent Pynia output history", () => {
  it("renders a bounded chronological history and a separate live operation", () => {
    const snapshot = state({ messages: Array.from({ length: 90 }, (_, index) => response(String(index))), busy: true,
      thinking: "Inspecting data", tools: [{ id: "live", status: "in_progress" }] });
    const history = pyniaOutputHistory(snapshot, 40);
    expect(history.hasOlder).toBe(true);
    expect(history.activities).toHaveLength(41);
    expect(history.activities[0].tools[0].id).toBe("50");
    expect(history.activities.at(-2)?.tools[0].id).toBe("89");
    expect(history.activities.at(-1)).toMatchObject({ live: true, thinking: "Inspecting data", tools: [{ id: "live", status: "in_progress" }] });
  });

  it("does not show the final operation twice if both broker fields contain it", () => {
    const snapshot = state({ messages: [response("query", "Done")], tools: [{ id: "query", title: "query", status: "completed" }], thinking: "Done" });
    expect(pyniaOutputHistory(snapshot).activities).toHaveLength(1);
    expect(pyniaOutputHistory(snapshot).activities[0].live).toBe(false);
  });

  it("clears only the local view and retains later progress even when the current response is sealed", () => {
    const snapshot = state({ busy: true, acp_session_id: "same", messages: [response("previous"), { role: "user", content: "Continue" }, { role: "assistant", content: "Starting" }],
      thinking: "Before clear", tools: [{ id: "query", title: "Query", status: "running" }] });
    const before = JSON.stringify(snapshot), cut = cutPyniaOutput(snapshot);
    expect(pyniaOutputHistory(snapshot, 40, cut).activities.at(-1)).toMatchObject({ live: true, thinking: "", tools: [] });
    const progress = state({ ...snapshot, thinking: "Before clear and after", tools: [{ id: "query", title: "Query", status: "completed" }, { id: "save", status: "running" }] });
    expect(pyniaOutputHistory(progress, 40, cut).activities.at(-1)).toMatchObject({ thinking: " and after", tools: progress.tools });
    const final = state({ ...progress, busy: false, thinking: "", tools: [], messages: [...snapshot.messages.slice(0, -1), { role: "assistant", content: "Done", activity: { thinking: progress.thinking, tools: progress.tools } }] });
    const history = pyniaOutputHistory(final, 40, cut);
    expect(history.activities).toHaveLength(1);
    expect(history.activities[0]).toMatchObject({ live: false, thinking: " and after", tools: progress.tools });
    expect(JSON.stringify(snapshot)).toBe(before);
  });

  it("starts displaying a new conversation after clearing the previous output", () => {
    const original = state({ acp_session_id: "old", messages: [response("old")], tools: [{ id: "stale", status: "completed" }] });
    const cut = cutPyniaOutput(original);
    expect(pyniaOutputHistory(original, 40, cut).activities).toEqual([]);
    const restarted = state({ acp_session_id: "new", messages: [response("new")] });
    expect(pyniaOutputHistory(restarted, 40, cut).activities[0].tools[0].id).toBe("new");
    expect(pyniaOutputHistory(original).activities.length).toBeGreaterThan(0);
  });

  it("normalizes statuses and ends running indicators when the turn is no longer busy", () => {
    expect(outputToolStatus({ id: "one", status: "in_progress" }, true)).toBe("running");
    expect(outputToolStatus({ id: "one", status: "running" }, false)).toBe("interrupted");
    expect(outputToolStatus({ id: "two", status: "ok" }, false)).toBe("completed");
    expect(outputToolStatus({ id: "three", status: "completed", error: "Database refused the query" }, false)).toBe("error");
    expect(outputToolStatus({ id: "four", status: "timed_out" }, true)).toBe("error");
    expect(outputToolStatus({ id: "five", status: "provider-specific" }, false)).toBe("unknown");
  });

  it("limits displayed payloads and accepts malformed legacy activity without failing the workbench", () => {
    const snapshot = state({ messages: [{ role: "assistant", content: "Saved", activity: { thinking: "x".repeat(20000), tools: [null, { id: "t", title: "Query", error: "e".repeat(10000) }] } } as unknown as PyniaMessage] });
    const frame = pyniaOutputHistory(snapshot).activities[0];
    expect(frame.thinking).toHaveLength(8000);
    expect(frame.tools).toHaveLength(1);
    expect(frame.tools[0].error).toHaveLength(4000);
    expect(pyniaOutputHistory(undefined)).toEqual({ activities: [], hasOlder: false });
  });

  it("shares one initial broker request when chat and output attach concurrently", async () => {
    const calls: string[] = [];
    const transport = { request: async (method: string) => { calls.push(method); return state({ agent_id: "codex" }); }, subscribe: async () => () => {} } as RuntimeTransport;
    const controller = new PyniaController(transport, async () => () => {});
    await Promise.all([controller.attach("analysis", undefined, { default_agent_id: "codex" }), controller.attach("analysis", undefined, { default_agent_id: "codex" })]);
    expect(calls).toEqual(["pynia.state"]);
    expect(controller.getSnapshot().sessions.analysis.agent_id).toBe("codex");
    controller.dispose();
  });
});
