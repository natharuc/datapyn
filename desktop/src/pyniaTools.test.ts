import { describe, expect, it, vi } from "vitest";
vi.mock("./editorRegistry", async(importOriginal) => ({ ...await importOriginal<typeof import("./editorRegistry")>(), disposeModel: vi.fn(), focusEditor: vi.fn(), getRegisteredEditor: vi.fn(), insertInEditor: vi.fn(), replaceEditorCode: vi.fn(), selectedCode: vi.fn() }));
import { WorkspaceController } from "./workspace";
import { handlePyniaTool } from "./pyniaTools";
import { selectedCode } from "./editorRegistry";
import type { RuntimeEvent, RuntimeTransport } from "./runtime";
const transport = { request: async () => ({ protocol_version: 1, python_version: "3.12", capabilities: {} }), subscribe: async () => () => {} } as RuntimeTransport;
const event = (session_id: string, name: string, arguments_: Record<string, unknown>) => ({ event: "pynia.tool_request", payload: { session_id, request_id: "1", name, arguments: arguments_ } });
function executionTransport() {
  let listener: ((event: RuntimeEvent) => void) | undefined;
  return {
    request: vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
      if (method === "execution.run") queueMicrotask(() => listener?.({ event: "execution.finished", payload: {
        session_id: String(params.session_id), execution_id: String(params.execution_id), status: "succeeded", duration_ms: 1, results: [], variables: [],
      } }));
      return { protocol_version: 1, python_version: "3.12", capabilities: {} };
    }),
    subscribe: async (next: (event: RuntimeEvent) => void) => { listener = next; return () => {}; },
  } as RuntimeTransport;
}
describe("Pynia GUI tools", () => {
  it("runs a requested block through the shared selection rule", async () => {
    const transport = executionTransport(), workspace = new WorkspaceController(transport), session = workspace.session()!, block = session.blocks[0];
    workspace.updateBlock(session.id, block.id, { code: "SELECT 1; SELECT 2;" });
    vi.mocked(selectedCode).mockReturnValue("SELECT 2;");
    try {
      await handlePyniaTool(workspace, event(session.id, "datapyn_run", { mode: "block" }));
      expect(transport.request).toHaveBeenCalledWith("execution.run", expect.objectContaining({ code: "SELECT 2;" }));
      expect(workspace.session(session.id)?.blocks[0].code).toBe("SELECT 1; SELECT 2;");
    } finally { vi.mocked(selectedCode).mockReset(); workspace.dispose(); }
  });
  it("runs supplied write-mode code even when the previous editor has a selection", async () => {
    const transport = executionTransport(), workspace = new WorkspaceController(transport), session = workspace.session()!, block = session.blocks[0];
    workspace.updateBlock(session.id, block.id, { block_name: "target", language: "python", code: "old = 1" });
    vi.mocked(selectedCode).mockReturnValue("old");
    try {
      await handlePyniaTool(workspace, event(session.id, "datapyn_run", { mode: "write", block_name: "target", language: "python", code: "fresh = 2", force: true }));
      expect(transport.request).toHaveBeenCalledWith("execution.run", expect.objectContaining({ code: "fresh = 2", language: "python" }));
      expect(workspace.session(session.id)?.blocks[0].code).toBe("fresh = 2");
    } finally { vi.mocked(selectedCode).mockReset(); workspace.dispose(); }
  });
  it("pins mutations to the chat's session even if another tab is active", async () => {
    const workspace = new WorkspaceController(transport), first = workspace.session()!, second = workspace.createSession();
    await handlePyniaTool(workspace, event(first.id, "datapyn_blocks", { operation: "create", language: "python", code: "x = 1", block_name: "script" }));
    expect(workspace.session(first.id)?.blocks).toHaveLength(2); expect(workspace.session(second.id)?.blocks).toHaveLength(1); expect(workspace.getSnapshot().activeId).toBe(second.id);
  });
  it("applies partial edits and undo from an actual document snapshot", async () => {
    const workspace = new WorkspaceController(transport), session = workspace.session()!, block = session.blocks[0]; workspace.updateBlock(session.id, block.id, { code: "one\ntwo\nthree" });
    await handlePyniaTool(workspace, event(session.id, "datapyn_edit", { operation: "lines", start_line: 2, end_line: 2, content: "new" }));
    expect(workspace.session(session.id)?.blocks[0].code).toBe("one\nnew\nthree");
    await handlePyniaTool(workspace, event(session.id, "datapyn_edit", { operation: "undo" })); expect(workspace.session(session.id)?.blocks[0].code).toBe("one\ntwo\nthree");
  });
  it("rejects an ambiguous named block and protects executing sessions", async () => {
    const workspace = new WorkspaceController(transport), session = workspace.session()!; workspace.updateBlock(session.id, session.blocks[0].id, { block_name: "same" }); const block = workspace.addBlock(session.id); workspace.updateBlock(session.id, block.id, { block_name: "same" });
    await expect(handlePyniaTool(workspace, event(session.id, "datapyn_edit", { operation: "rename", block_name: "same", new_name: "oops" }))).rejects.toThrow("ambíguo");
    workspace.patchSession(session.id, (current) => ({ ...current, busy: true })); await expect(handlePyniaTool(workspace, event(session.id, "datapyn_blocks", { operation: "create" }))).rejects.toThrow("Aguarde");
  });
  it("resolves legacy 1-based tab and block references without fabricating results", async () => {
    const workspace = new WorkspaceController(transport), session = workspace.session()!; workspace.updateBlock(session.id, session.blocks[0].id, { code: "SELECT 1;" });
    expect(await handlePyniaTool(workspace, event(session.id, "datapyn_inspect", { kind: "reference", reference: "#block1" }))).toMatchObject({ code: "SELECT 1;", block_index: 0 });
    expect(await handlePyniaTool(workspace, event(session.id, "datapyn_inspect", { kind: "reference", reference: "#tab1" }))).toMatchObject({ tab_id: session.id });
    expect(await handlePyniaTool(workspace, event(session.id, "datapyn_inspect", { kind: "block", detail: "result" }))).toMatchObject({ result: null });
  });
});
