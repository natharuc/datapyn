import { afterEach, describe, expect, it, vi } from "vitest";
import type { RuntimeEvent, RuntimeTransport } from "./runtime";
import { WorkspaceController } from "./workspace";
import { sqlSafetyReview, type SqlExecutionReview, type SqlSafetyReview } from "./sqlSafety";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(accept => { resolve = accept; });
  return { promise, resolve };
}

const risk = (operation = "DELETE", unfiltered = true) => ({
  statement: 1, operation, target: "orders", preview: `${operation} orders`, has_where: !unfiltered, unfiltered,
});

class SafetyTransport implements RuntimeTransport {
  requests: Array<{ method: string; params: Record<string, unknown> }> = [];
  listener?: (event: RuntimeEvent) => void;
  review: (params: Record<string, unknown>) => unknown | Promise<unknown> = () => ({ confirmation_required: false, risks: [] });
  async subscribe(listener: (event: RuntimeEvent) => void) { this.listener = listener; return () => {}; }
  async request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    this.requests.push({ method, params });
    if (method === "system.info") return { protocol_version: 1, python_version: "3.12", capabilities: {} } as T;
    if (method === "execution.review") return await this.review(params) as T;
    return { status: "queued" } as T;
  }
  calls(method: string) { return this.requests.filter(request => request.method === method); }
  finish(index = 0) {
    const params = this.calls("execution.run")[index].params;
    this.listener?.({ event: "execution.finished", payload: {
      session_id: String(params.session_id), execution_id: String(params.execution_id),
      status: "succeeded", duration_ms: 1, results: [], variables: [],
    } });
  }
  require(operation = "DELETE", unfiltered = true) {
    this.review = () => ({ confirmation_required: true, confirmation_token: `ticket-${this.calls("execution.review").length}`, risks: [risk(operation, unfiltered)] });
  }
}

const controllers: WorkspaceController[] = [];
function setup(code = "DELETE FROM orders") {
  const transport = new SafetyTransport(), controller = new WorkspaceController(transport, undefined, { nativePersistence: true });
  controllers.push(controller);
  const session = controller.session()!, block = session.blocks[0];
  controller.updateBlock(session.id, block.id, { code, block_name: "Orders" });
  return { transport, controller, session, block };
}
afterEach(() => { controllers.splice(0).forEach(controller => controller.dispose()); vi.useRealTimers(); });

describe("destructive execution approval", () => {
  it.each(["sql", "python"] as const)("reviews %s before execution and does not prompt when no approval is required", async language => {
    const { transport, controller, session, block } = setup(language === "sql" ? "SELECT 1" : "print(1)");
    controller.updateBlock(session.id, block.id, { language });
    controller.onConfirmSqlExecution = vi.fn();
    const run = controller.runBlock(session.id, block.id);
    await vi.waitFor(() => expect(transport.calls("execution.run")).toHaveLength(1));
    expect(transport.requests.findIndex(request => request.method === "execution.review")).toBeLessThan(transport.requests.findIndex(request => request.method === "execution.run"));
    expect(controller.onConfirmSqlExecution).not.toHaveBeenCalled();
    expect(transport.calls("execution.run")[0].params).not.toHaveProperty("confirmation_token");
    transport.finish(); await run;
  });

  it("waits for explicit approval of the selected filtered command, with no running clock or duplicate F5", async () => {
    const { transport, controller, session, block } = setup("DELETE FROM orders; SELECT 1; DROP TABLE orders;");
    transport.require("DELETE", false);
    const answer = deferred<boolean>(), confirm = vi.fn((_review: SqlExecutionReview) => answer.promise);
    controller.onConfirmSqlExecution = confirm;
    const run = controller.runBlock(session.id, block.id, "DELETE FROM orders WHERE id=1;");
    await vi.waitFor(() => expect(confirm).toHaveBeenCalledOnce());
    expect(confirm.mock.calls[0][0]).toMatchObject({ code: "DELETE FROM orders WHERE id=1;", risks: [risk("DELETE", false)] });
    expect(controller.session(session.id)).toMatchObject({ busy: true, executionStartedAt: undefined });
    expect(controller.session(session.id)!.blocks[0]).toMatchObject({ status: "queued", executionStartedAt: undefined });
    expect(transport.calls("execution.run")).toHaveLength(0);
    await expect(controller.runBlock(session.id, block.id)).rejects.toThrow("em andamento");
    answer.resolve(true);
    await vi.waitFor(() => expect(transport.calls("execution.run")).toHaveLength(1));
    expect(transport.calls("execution.run")[0].params).toMatchObject({ code: "DELETE FROM orders WHERE id=1;", confirmation_token: "ticket-1" });
    transport.finish(); await run;
  });

  it.each(["DELETE", "UPDATE", "TRUNCATE", "DROP", "ALTER", "MERGE", "REPLACE"])("declining %s stops the entire queue and does not advance or notify", async operation => {
    const { transport, controller, session, block } = setup(`${operation} orders`);
    transport.require(operation);
    const next = controller.addBlock(session.id, "sql", "SELECT 2");
    controller.focusBlock(session.id, block.id);
    controller.onConfirmSqlExecution = vi.fn(async () => false);
    controller.onQueueFinished = vi.fn();
    await controller.runBlock(session.id, block.id, undefined, true);
    expect(transport.calls("execution.run")).toHaveLength(0);
    expect(controller.onQueueFinished).not.toHaveBeenCalled();
    expect(controller.session(session.id)).toMatchObject({ busy: false, focusedBlockId: block.id });
    expect(controller.session(session.id)!.blocks.find(item => item.id === next.id)!.status).toBe("idle");
  });

  it("refuses a protected command when no confirmation presenter exists", async () => {
    const { transport, controller, session, block } = setup(); transport.require();
    await controller.runBlock(session.id, block.id);
    expect(transport.calls("execution.run")).toHaveLength(0);
    expect(controller.session(session.id)!.busy).toBe(false);
  });

  it("preserves previous execution feedback while reviewing and after cancellation, then clears it only on approved execution", async () => {
    const { transport, controller, session, block } = setup(); transport.require();
    const previous = [{ executionId: "previous", blockId: block.id, blockName: "Orders", status: "succeeded" as const, durationMs: 1, commands: [], hasResults: false }];
    const output = { executionId: "previous", kind: "commands" as const };
    controller.patchSession(session.id, current => ({ ...current, commandExecutions: previous, executionOutput: output }));
    const answer = deferred<boolean>();
    controller.onConfirmSqlExecution = vi.fn(() => answer.promise);
    const declined = controller.runBlock(session.id, block.id);
    await vi.waitFor(() => expect(controller.onConfirmSqlExecution).toHaveBeenCalledOnce());
    expect(controller.session(session.id)!.commandExecutions).toBe(previous);
    expect(controller.session(session.id)!.executionOutput).toBe(output);
    answer.resolve(false); await declined;
    expect(controller.session(session.id)!.commandExecutions).toBe(previous);
    expect(controller.session(session.id)!.executionOutput).toBe(output);
    controller.onConfirmSqlExecution = async () => true;
    const approved = controller.runBlock(session.id, block.id);
    await vi.waitFor(() => expect(transport.calls("execution.run")).toHaveLength(1));
    expect(controller.session(session.id)!.commandExecutions).toEqual([]);
    expect(controller.session(session.id)!.executionOutput).toBeUndefined();
    transport.finish(); await approved;
  });

  it.each([
    {blockConnection: "main", name: undefined, resolved: undefined, expected: "Main warehouse"},
    {blockConnection: "other", name: undefined, resolved: undefined, expected: "other"},
    {blockConnection: "other", name: "Other warehouse", resolved: undefined, expected: "Other warehouse"},
    {blockConnection: "other", name: "Old name", resolved: "Runtime warehouse", expected: "Runtime warehouse"},
  ])("shows the actual scoped connection in review: $expected", async ({blockConnection, name, resolved, expected}) => {
    const {transport, controller, session, block} = setup();
    controller.patchSession(session.id, current => ({...current, savedConnectionId: "main", extras: {connection_name: "Main warehouse"}}));
    controller.updateBlock(session.id, block.id, {connection_id: blockConnection, connection_name: name});
    transport.review = () => ({confirmation_required: true, confirmation_token: "token", connection_name: resolved, risks: [risk()]});
    controller.onConfirmSqlExecution = vi.fn(async () => false);
    await controller.runBlock(session.id, block.id);
    expect(controller.onConfirmSqlExecution).toHaveBeenCalledWith(expect.objectContaining({connection_name: expected}), expect.any(AbortSignal));
    expect(transport.calls("execution.run")).toHaveLength(0);
  });

  it("executes the frozen code, target and deep parameter values even if the document changes while confirming", async () => {
    const { transport, controller, session, block } = setup(); transport.require();
    const parameters = [{ name: "id", value: "old" }], shared = [{ name: "source", value: "initial" }];
    controller.patchSession(session.id, current => ({ ...current, savedConnectionId: "saved", database: "original", schema: "dbo", extras: { shared_parameters: shared } }));
    controller.updateBlock(session.id, block.id, { code: "DELETE FROM orders WHERE id=:id", connection_id: "pinned", database_name: "reviewed", schema: "sales", sql_parameters: parameters });
    const answer = deferred<boolean>(); controller.onConfirmSqlExecution = () => answer.promise;
    const run = controller.runBlock(session.id, block.id);
    await vi.waitFor(() => expect(transport.calls("execution.review")).toHaveLength(1));
    parameters[0].value = "changed"; shared[0].value = "changed";
    controller.updateBlock(session.id, block.id, { code: "DROP TABLE other", connection_id: "other", database_name: "other", schema: "other" });
    controller.patchSession(session.id, current => ({ ...current, database: "other" }));
    answer.resolve(true);
    await vi.waitFor(() => expect(transport.calls("execution.run")).toHaveLength(1));
    expect(transport.calls("execution.run")[0].params).toEqual({ ...transport.calls("execution.review")[0].params, confirmation_token: "ticket-1" });
    expect(transport.calls("execution.run")[0].params).toMatchObject({ code: "DELETE FROM orders WHERE id=:id", connection_id: "pinned", database: "reviewed", schema: "sales", sql_parameters: [{ value: "old" }], shared_parameters: [{ value: "initial" }] });
    transport.finish(); await run;
  });

  it("does not run later Run All blocks after cancelling a confirmation", async () => {
    const { transport, controller, session } = setup("SELECT 1");
    controller.addBlock(session.id, "sql", "DELETE FROM orders");
    controller.addBlock(session.id, "python", "print('must not run')");
    transport.review = params => params.code === "SELECT 1" ? { confirmation_required: false, risks: [] } : { confirmation_required: true, confirmation_token: "second", risks: [risk()] };
    controller.onConfirmSqlExecution = vi.fn(async () => false); controller.onQueueFinished = vi.fn();
    const run = controller.runAll(session.id);
    await vi.waitFor(() => expect(transport.calls("execution.run")).toHaveLength(1)); transport.finish(); await run;
    expect(transport.calls("execution.run").map(request => request.params.code)).toEqual(["SELECT 1"]);
    expect(transport.calls("execution.review")).toHaveLength(2);
    expect(controller.onQueueFinished).not.toHaveBeenCalled();
    expect(controller.session(session.id)!.blocks.at(-1)!.status).toBe("cancelled");
  });

  it("requires a new approval on each periodic iteration and stops repetition when declined", async () => {
    vi.useFakeTimers();
    const { transport, controller, session } = setup(); transport.require();
    controller.onConfirmSqlExecution = vi.fn().mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    const run = controller.startPeriodic(session.id, 1);
    await vi.waitFor(() => expect(transport.calls("execution.run")).toHaveLength(1)); transport.finish(); await run;
    await vi.advanceTimersByTimeAsync(1000);
    expect(controller.onConfirmSqlExecution).toHaveBeenCalledTimes(2);
    expect(transport.calls("execution.run")).toHaveLength(1);
    expect(transport.calls("execution.review")).toHaveLength(2);
    expect(controller.session(session.id)!.periodicSeconds).toBeUndefined();
  });

  it("cancels a pending dialog without sending execution.cancel or accepting a late OK", async () => {
    const { transport, controller, session, block } = setup(); transport.require();
    const answer = deferred<boolean>(); let signal: AbortSignal | undefined;
    controller.onConfirmSqlExecution = vi.fn((_review, current) => { signal = current; return answer.promise; });
    const run = controller.runBlock(session.id, block.id);
    await vi.waitFor(() => expect(controller.onConfirmSqlExecution).toHaveBeenCalledOnce());
    await controller.cancel(session.id); await run;
    expect(signal!.aborted).toBe(true);
    answer.resolve(true); await Promise.resolve();
    expect(transport.calls("execution.run")).toHaveLength(0);
    expect(transport.calls("execution.cancel")).toHaveLength(0);
    expect(controller.session(session.id)!.busy).toBe(false);
  });

  it("cancels while the review RPC is pending and ignores its late response", async () => {
    const { transport, controller, session, block } = setup();
    const answer = deferred<SqlSafetyReview>(); transport.review = () => answer.promise;
    controller.onConfirmSqlExecution = vi.fn();
    const run = controller.runBlock(session.id, block.id);
    await vi.waitFor(() => expect(transport.calls("execution.review")).toHaveLength(1));
    await controller.cancel(session.id); await run;
    answer.resolve({ confirmation_required: true, confirmation_token: "old", risks: [risk()] });
    await Promise.resolve();
    expect(controller.onConfirmSqlExecution).not.toHaveBeenCalled();
    expect(transport.calls("execution.run")).toHaveLength(0);
  });

  it.each(["dispose", "profile", "backend", "session"])("invalidates a pending approval on %s", async change => {
    const { transport, controller, session, block } = setup(); transport.require();
    controller.onConfirmSqlExecution = vi.fn(() => new Promise<boolean>(() => {}));
    const run = controller.runBlock(session.id, block.id);
    await vi.waitFor(() => expect(controller.onConfirmSqlExecution).toHaveBeenCalledOnce());
    if (change === "dispose") controller.dispose();
    else if (change === "profile") controller.setWorkspaceIdentity("different-profile");
    else if (change === "backend") controller.onRuntimeEvent({ event: "backend.exited", payload: { message: "Closed" } });
    else controller.onRuntimeEvent({ event: "session.reset", payload: { session_id: session.id } });
    await run;
    expect(transport.calls("execution.run")).toHaveLength(0);
  });

  it("reviews direct downloads with their selected SQL and frozen destination", async () => {
    const { transport, controller, session, block } = setup("DELETE FROM orders; SELECT 1"); transport.require();
    controller.onConfirmSqlExecution = vi.fn(async () => true);
    const run = controller.runToFile(session.id, block.id, { path: "fixture.csv", format: "csv" }, "DELETE FROM orders WHERE id=1; SELECT 1");
    await vi.waitFor(() => expect(transport.calls("execution.run")).toHaveLength(1));
    expect(transport.calls("execution.review")[0].params).toMatchObject({ code: "DELETE FROM orders WHERE id=1; SELECT 1", export: { path: "fixture.csv", format: "csv" } });
    transport.finish(); await run;
  });

  it.each([undefined, {}, { confirmation_required: false }, { confirmation_required: true, risks: [risk()] }, { confirmation_required: true, confirmation_token: "", risks: [risk()] }])("fails closed on a malformed review response", async response => {
    const { transport, controller, session, block } = setup(); transport.review = () => response;
    await expect(controller.runBlock(session.id, block.id)).rejects.toThrow("validar a segurança");
    expect(transport.calls("execution.run")).toHaveLength(0);
    expect(controller.session(session.id)!.busy).toBe(false);
  });

  it("never accepts an arbitrary truthy callback value as approval", async () => {
    const { transport, controller, session, block } = setup(); transport.require();
    controller.onConfirmSqlExecution = async () => "OK" as unknown as boolean;
    await controller.runBlock(session.id, block.id);
    expect(transport.calls("execution.run")).toHaveLength(0);
  });

  it("validates risk metadata before presenting it", () => {
    expect(() => sqlSafetyReview({ confirmation_required: true, confirmation_token: "ticket", risks: [{ operation: "DELETE" }] })).toThrow("validar a segurança");
  });
});
