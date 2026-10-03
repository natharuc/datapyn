import { describe, expect, it } from "vitest";
import { PyniaController, advertisedPyniaDefaults, emptyPyniaState, isFreshPyniaConversation, mergeToolActivity, pyniaAgentPreferences, type PyniaDefaults, type PyniaState } from "./pynia";
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

describe("Pynia conversation defaults", () => {
  const defaults: PyniaDefaults = {
    default_agent_id: "codex", model_id: "global-model", thought_level: "high",
    agent_prefs: { codex: { model_id: "agent-model" }, claude: { model_id: "claude-model", thought_level: "low" } },
  };
  function recorder(initial: PyniaState = emptyPyniaState()) {
    const calls: Array<{ method: string; params?: Record<string, unknown> }> = [];
    const transport = { request: async (method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params }); return method === "pynia.state" ? initial : { status: "queued" };
    }, subscribe: async () => () => {} } as RuntimeTransport;
    const controller = new PyniaController(transport, async () => () => {});
    return { controller, calls };
  }

  it("uses per-agent preferences and limits global fallback to the default agent", () => {
    expect(pyniaAgentPreferences(defaults, "codex")).toEqual({ model_id: "agent-model", thought_level: "high" });
    expect(pyniaAgentPreferences(defaults, "claude")).toEqual({ model_id: "claude-model", thought_level: "low" });
    expect(pyniaAgentPreferences(defaults, "cursor")).toEqual({});
    expect(pyniaAgentPreferences({ default_agent_id: "codex", thought_level: "auto" }, "codex")).toEqual({});
    expect(pyniaAgentPreferences({ ...defaults, agent_prefs: { codex: { thought_level: "auto" } } }, "codex").thought_level).toBe("auto");
  });

  it("passes defaults when attaching a fresh chat without selecting or configuring the agent twice", async () => {
    const ready = { ...emptyPyniaState(), agent_id: "codex", fresh_conversation: true };
    const { controller, calls } = recorder(ready);
    await controller.attach("new", undefined, defaults);
    expect(calls).toEqual([{ method: "pynia.state", params: { session_id: "new", data: undefined, defaults } }]);
    expect(controller.getSnapshot().sessions.new).toEqual(ready);
    await controller.attach("new", undefined, { ...defaults, model_id: "changed" });
    expect(calls).toHaveLength(1); controller.dispose();
  });

  it("never forwards new defaults over a restored agent, transcript, ACP id or configuration", async () => {
    const restored = [
      { agent_id: "claude" }, { messages: [{ role: "user", content: "Earlier question" }] },
      { acp_session_id: "saved-acp" }, { config_snapshot: { models: { currentModelId: "saved-model" } } },
      { fresh_conversation: false }, { agent_id: "codex", fresh_conversation: true, acp_session_id: "live" },
    ];
    for (const data of restored) {
      const { controller, calls } = recorder({ ...emptyPyniaState(), ...data });
      await controller.attach("existing", data, defaults);
      expect(calls[0].params).not.toHaveProperty("defaults");
      expect(controller.getSnapshot().sessions.existing).toMatchObject(data);
      controller.dispose();
    }
  });

  it("lets a fresh manual agent choice receive its preferences while guarding existing ACP conversations", async () => {
    const { controller, calls } = recorder();
    controller.onEvent({ event: "pynia.state", payload: { session_id: "fresh", state: { ...emptyPyniaState(), agent_id: "codex", fresh_conversation: true } } });
    await controller.request("pynia.select_agent", "fresh", { agent_id: "claude" }, defaults);
    expect(calls[0]).toEqual({ method: "pynia.select_agent", params: { session_id: "fresh", agent_id: "claude", defaults } });
    controller.onEvent({ event: "pynia.state", payload: { session_id: "existing", state: { ...emptyPyniaState(), agent_id: "codex", acp_session_id: "actual-session", fresh_conversation: false } } });
    await controller.request("pynia.select_agent", "existing", { agent_id: "codex" }, defaults);
    expect(calls[1].params).not.toHaveProperty("defaults");
    await controller.request("pynia.config", "existing", { config_id: "real-model", value: "user-choice" }, defaults);
    expect(calls[2].params).not.toHaveProperty("defaults");
    expect(controller.getSnapshot().sessions.existing.acp_session_id).toBe("actual-session"); controller.dispose();
  });

  it("passes the current profile defaults only after explicit chat clearing", async () => {
    const { controller, calls } = recorder();
    controller.onEvent({ event: "pynia.state", payload: { session_id: "existing", state: { ...emptyPyniaState(), locked: true, agent_id: "claude", messages: [{ role: "assistant", content: "Saved answer" }] } } });
    const profileDefaults = { default_agent_id: "cursor", agent_prefs: { cursor: { model_id: "profile-model" } } };
    await controller.request("pynia.clear", "existing", {}, profileDefaults);
    expect(calls[0]).toEqual({ method: "pynia.clear", params: { session_id: "existing", defaults: profileDefaults } });
    // Only the broker's emitted result may replace the current transcript.
    expect(controller.getSnapshot().sessions.existing.messages[0].content).toBe("Saved answer"); controller.dispose();
  });

  it("marks only options advertised by the ACP agent and leaves the current selection intact", () => {
    const state: PyniaState = { ...emptyPyniaState(), agent_id: "codex", acp_session_id: "new-acp", defaults_applied: true,
      selectors: { model: { id: "announced-model-id", current: "live-model", values: [{ value: "live-model", name: "Live" }, { value: "agent-model", name: "Preferred" }] },
        reasoning: { id: "announced-reasoning-id", current: "low", values: [{ value: "low", name: "Low" }] } } };
    expect(advertisedPyniaDefaults(defaults, state)).toEqual({ model: "agent-model" });
    expect(state.selectors?.model?.current).toBe("live-model");
    expect(advertisedPyniaDefaults(defaults, { ...state, selectors: { ...state.selectors, model: { ...state.selectors!.model!, loading: true } } })).toEqual({});
    expect(advertisedPyniaDefaults(defaults, { ...state, selectors: { ...state.selectors, model: { ...state.selectors!.model!, hidden: true } } })).toEqual({});
    expect(advertisedPyniaDefaults(defaults, { ...state, messages: [{ role: "user", content: "Existing chat" }] })).toEqual({});
    expect(isFreshPyniaConversation({ ...state, fresh_conversation: true })).toBe(false);
  });
});
