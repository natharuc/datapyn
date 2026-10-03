import { describe, expect, it } from "vitest";
import { PyniaController, emptyPyniaState, mergeToolActivity, type PyniaState } from "./pynia";
import type { RuntimeTransport } from "./runtime";
describe("Pynia state transport", () => {
  it("keeps streamed messages pinned to their session when switching tabs", () => {
    const controller = new PyniaController();
    controller.onEvent({ event: "pynia.state", payload: { session_id: "first", state: { ...emptyPyniaState(), messages: [{ role: "user", content: "First question" }] } } });
    controller.onEvent({ event: "pynia.state", payload: { session_id: "second", state: { ...emptyPyniaState(), messages: [{ role: "user", content: "Second question" }] } } });
    controller.onEvent({ event: "pynia.chunk", payload: { session_id: "first", text: "Hello " } });
    controller.onEvent({ event: "pynia.chunk", payload: { session_id: "first", text: "world" } }); controller.flushChunks();
    expect(controller.getSnapshot().sessions.first.messages.at(-1)?.content).toBe("Hello world");
    expect(controller.getSnapshot().sessions.second.messages).toHaveLength(1); controller.dispose();
  });
  it("uses final broker snapshots without duplicating buffered chunks", () => {
    const controller = new PyniaController();
    controller.onEvent({ event: "pynia.chunk", payload: { session_id: "s", text: "partial" } });
    controller.onEvent({ event: "pynia.state", payload: { session_id: "s", state: { ...emptyPyniaState(), messages: [{ role: "assistant", content: "partial complete" }] } } });
    controller.flushChunks(); expect(controller.getSnapshot().sessions.s.messages).toEqual([{ role: "assistant", content: "partial complete" }]); controller.dispose();
  });
  it("does not overwrite live updates with an older initial state response", async () => {
    let resolve!: (value: PyniaState) => void;
    const transport = { request: () => new Promise((done) => { resolve = done as (value: PyniaState) => void; }), subscribe: async () => () => {} } as RuntimeTransport;
    const controller = new PyniaController(transport, async () => () => {}), attached = controller.attach("s");
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    controller.onEvent({ event: "pynia.state", payload: { session_id: "s", state: { ...emptyPyniaState(), agent_id: "codex" } } });
    resolve({ ...emptyPyniaState(), agent_id: "old" }); await attached;
    expect(controller.getSnapshot().sessions.s.agent_id).toBe("codex"); controller.dispose();
  });
  it("merges tool updates by their actual id without losing the title", () => {
    const initial = mergeToolActivity([], { toolCallId: "1", title: "datapyn-datapyn_query", status: "in_progress" });
    expect(mergeToolActivity(initial, { toolCallId: "1", sessionUpdate: "tool_call_update", status: "completed" })).toEqual([{ id: "1", title: "datapyn_query", status: "completed" }]);
  });
  it("clears pending ACP activity after the broker exits without duplicating buffered text",()=>{
    const controller=new PyniaController();controller.onEvent({event:"pynia.state",payload:{session_id:"s",state:{...emptyPyniaState(),busy:true,permissions:[{request_id:"p",params:{}}]}}});
    controller.onEvent({event:"pynia.chunk",payload:{session_id:"s",text:"unconfirmed"}});controller.onEvent({event:"backend.exited",payload:{}});controller.flushChunks();
    const state=controller.getSnapshot().sessions.s;expect(state.busy).toBe(false);expect(state.permissions).toEqual([]);expect(state.messages).toEqual([]);expect(state.error).toMatch(/runtime/);controller.dispose();
  });
});
