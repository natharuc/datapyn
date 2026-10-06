import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CommandResults } from "./CommandResults";
import { setLocale, type Locale } from "./i18n";
import { OutputRevealTracker } from "./outputReveal";
import type { ExecutionFinished, ResultRef, RuntimeEvent, RuntimeTransport, SqlCommandResult } from "./runtime";
import { applyRuntimeEvent, decodeDocument, encodeDocument, newBlock, newSession, WorkspaceController, type CommandExecution, type SessionDocument } from "./workspace";

afterEach(() => setLocale("pt-BR"));

const command = (rows: number | null = 4, commandName = "UPDATE", index = 1): SqlCommandResult => ({ statement_index: index, command: commandName, rows_affected: rows });
const frame = (id = "previous-result"): ResultRef => ({ result_id: id, variable_name: "df", row_count: 3, columns: [{ name: "value", dtype: "int64" }] });
const running = (session = newSession(), executionId = "execution-1", blockId = session.blocks[0].id): SessionDocument => ({
  ...session, busy: true, currentExecutionId: executionId, currentBlockId: blockId,
  blocks: session.blocks.map(block => block.id === blockId ? { ...block, status: "running" } : block),
});
const finished = (session: SessionDocument, overrides: Partial<ExecutionFinished> = {}): RuntimeEvent => ({ event: "execution.finished", payload: {
  session_id: session.id, execution_id: session.currentExecutionId!, block_id: session.currentBlockId,
  status: "succeeded", duration_ms: 1234, results: [], variables: [], command_results: [command()], ...overrides,
} });
const completed = (session: SessionDocument, overrides: Partial<ExecutionFinished> = {}) => applyRuntimeEvent(session, finished(session, overrides));
const execution = (overrides: Partial<CommandExecution> = {}): CommandExecution => ({
  executionId: "execution-1", blockId: "block-1", blockName: "Atualização", commands: [command()],
  status: "succeeded", durationMs: 1250, hasResults: false, ...overrides,
});

describe("SQL command feedback in the workspace", () => {
  it("preserves an existing grid for command-only completion and attributes feedback to the executing block after focus changes", () => {
    const initial = newSession(), target = { ...initial.blocks[0], block_name: "update_customers" }, other = newBlock("sql", "SELECT 1");
    const previous = [frame()];
    const before = running({ ...initial, blocks: [target, other], focusedBlockId: other.id, results: previous }, "update", target.id);
    const commands = [command(0, "UPDATE"), command(null, "CREATE", 2)];
    const after = completed(before, { command_results: commands });
    expect(after.results).toBe(previous);
    expect(after.focusedBlockId).toBe(other.id);
    expect(after.commandExecutions).toEqual([execution({
      executionId: "update", blockId: target.id, blockName: "update_customers", commands, durationMs: 1234,
    })]);
    expect(after.executionOutput).toEqual({ executionId: "update", kind: "commands" });
    expect(after.blocks[0]).toMatchObject({ status: "succeeded", duration_ms: 1234 });
    expect(after.blocks[1]).toBe(before.blocks[1]);
  });

  it("aggregates multiple executed blocks and replaces repeated terminal feedback instead of duplicating it", () => {
    const initial = newSession(), second = newBlock("sql", "DELETE FROM items");
    const first = completed(running({ ...initial, blocks: [initial.blocks[0], second] }, "update"));
    const after = completed(running(first, "delete", second.id), { command_results: [command(2, "DELETE")] });
    const repeated = completed(after, { command_results: [command(2, "DELETE")], duration_ms: 7 });
    expect(repeated.commandExecutions?.map(item => item.executionId)).toEqual(["update", "delete"]);
    expect(repeated.commandExecutions?.map(item => item.blockId)).toEqual([initial.blocks[0].id, second.id]);
    expect(repeated.commandExecutions?.[1]).toMatchObject({ commands: [command(2, "DELETE")], durationMs: 7 });
  });

  it("keeps command feedback alongside a fresh SELECT result without treating it as a command-only execution", () => {
    const after = completed(running({ ...newSession(), results: [frame()] }), { results: [frame("fresh-result")], command_results: [command(5)] });
    expect(after.results.map(item => item.result_id)).toEqual(["fresh-result"]);
    expect(after.commandExecutions?.[0]).toMatchObject({ commands: [command(5)], hasResults: true });
    expect(after.executionOutput).toEqual({ executionId: "execution-1", kind: "results", resultId: "fresh-result" });
  });

  it.each(["stale execution", "another session"])("ignores command feedback belonging to %s", kind => {
    const before = running(newSession());
    const event = finished(before, kind === "stale execution" ? { execution_id: "older" } : { session_id: "other-session" });
    expect(applyRuntimeEvent(before, event)).toBe(before);
    expect(before.commandExecutions).toEqual([]);
  });

  it("accepts older runtime payloads without command_results and does not invent or remove completed messages", () => {
    const existing = [execution()], before = running({ ...newSession(), commandExecutions: existing });
    const event = finished(before);
    if (event.event !== "execution.finished") throw new Error("Unexpected fixture event");
    delete event.payload.command_results;
    const after = applyRuntimeEvent(before, event);
    expect(after.blocks[0].status).toBe("succeeded");
    expect(after.commandExecutions).toBe(existing);
    const legacy = newSession();
    delete legacy.commandExecutions;
    expect(completed(running(legacy), { command_results: undefined }).commandExecutions).toBeUndefined();
  });

  it("keeps a failure without any completed command in Output instead of creating an empty message group", () => {
    const tracker = new OutputRevealTracker(), before = running(newSession());
    tracker.observe([before], before.id);
    const after = completed(before, { status: "failed", command_results: [], error: "Invalid SQL" });
    expect(after.commandExecutions).toEqual([]);
    expect(after.logs.at(-1)?.text).toContain("Invalid SQL");
    expect(tracker.observe([after], after.id)).toEqual({ panel: "output", sessionId: after.id, rich: false });
  });

  it.each(["failed", "cancelled"] as const)("retains completed statement feedback when the remaining batch is %s and the runtime resets", status => {
    const before = running({ ...newSession(), results: [frame()], variables: [{ name: "df", type: "DataFrame", preview: "3 rows" }] });
    const after = completed(before, { status, command_results: [command(8, "UPDATE"), command(null, "CREATE", 2)], error: status === "failed" ? "Third statement failed" : undefined });
    expect(after.commandExecutions?.[0]).toMatchObject({ status, commands: [command(8, "UPDATE"), command(null, "CREATE", 2)] });
    const reset = applyRuntimeEvent(after, { event: "session.reset", payload: { session_id: after.id, reason: "cancelled" } });
    expect(reset.commandExecutions).toBe(after.commandExecutions);
    expect(reset.executionOutput).toEqual({ executionId: before.currentExecutionId, kind: "commands" });
    expect(reset.results).toEqual([]);
    expect(reset.variables).toEqual([]);
  });

  it("keeps command feedback out of portable documents while preserving executable code and block names", () => {
    const initial = newSession();
    initial.blocks[0] = { ...initial.blocks[0], code: "UPDATE items SET value = 2", block_name: "update_items" };
    const after = completed(running(initial));
    const document = encodeDocument(after), restored = decodeDocument(document);
    expect(document).not.toHaveProperty("commandExecutions");
    expect(document).not.toHaveProperty("executionOutput");
    expect(JSON.stringify(document)).not.toContain("rows_affected");
    expect(restored.commandExecutions).toEqual([]);
    expect(restored.executionOutput).toBeUndefined();
    expect(restored.blocks[0]).toMatchObject({ code: initial.blocks[0].code, block_name: "update_items", status: "idle" });
  });
});

describe("SQL command dock reveal behavior", () => {
  it("reveals a command-only completion once, even with an old grid retained, and stays closed during edits or terminal cleanup", () => {
    const tracker = new OutputRevealTracker(), before = running({ ...newSession(), results: [frame()] });
    tracker.observe([before], before.id);
    const after = completed(before);
    expect(tracker.observe([after], after.id)).toEqual({ panel: "results", sessionId: after.id, rich: false, commands: true });
    const edited = { ...after, blocks: after.blocks.map(block => ({ ...block, code: "UPDATE corrected" })) };
    expect(tracker.observe([edited], edited.id)).toBeUndefined();
    const idle = { ...edited, busy: false, currentExecutionId: undefined, currentBlockId: undefined };
    expect(tracker.observe([idle], idle.id)).toBeUndefined();
    expect(tracker.observe([{ ...idle, commandExecutions: idle.commandExecutions?.map(item => ({ ...item })) }], idle.id)).toBeUndefined();
  });

  it("prefers a fresh SELECT grid to command messages for mixed execution", () => {
    const tracker = new OutputRevealTracker(), before = running(newSession());
    tracker.observe([before], before.id);
    const after = completed(before, { results: [frame("new-select")] });
    expect(tracker.observe([after], after.id)).toEqual({ panel: "results", sessionId: after.id, rich: false, resultId: "new-select" });
  });

  it("silently consumes background command completion and never replays it when switching tabs", () => {
    const tracker = new OutputRevealTracker(), active = newSession(), background = running(newSession("Background"));
    tracker.observe([active, background], active.id);
    const after = completed(background);
    expect(tracker.observe([active, after], active.id)).toBeUndefined();
    expect(tracker.observe([active, after], after.id)).toBeUndefined();
    expect(tracker.observe([active, { ...after, title: "Renamed" }], after.id)).toBeUndefined();
  });

  it("establishes a silent baseline for existing command messages and never reopens them for title or focus changes", () => {
    const tracker = new OutputRevealTracker(), restored = completed(running(newSession()));
    expect(tracker.observe([restored], restored.id)).toBeUndefined();
    expect(tracker.observe([{ ...restored, title: "Renamed", focusedBlockId: "other-block" }], restored.id)).toBeUndefined();
  });

  it.each(["results", "rich"] as const)("retains command history but selects the later %s output from the same background queue", kind => {
    const tracker = new OutputRevealTracker(), active = newSession();
    const initial = newSession("Background queue"), second = newBlock(kind === "rich" ? "python" : "sql", kind === "rich" ? "display(chart)" : "SELECT * FROM items");
    const before = running({ ...initial, blocks: [initial.blocks[0], second] }, "command-execution");
    tracker.observe([active, before], active.id);
    const commands = completed(before);
    expect(commands.executionOutput).toEqual({ executionId: "command-execution", kind: "commands" });
    expect(tracker.observe([active, commands], active.id)).toBeUndefined();
    const nextRunning = running(commands, "later-execution", second.id);
    expect(tracker.observe([active, nextRunning], active.id)).toBeUndefined();
    const after = completed(nextRunning, kind === "results"
      ? { command_results: [], results: [frame("later-select")] }
      : { command_results: [], rich_outputs: [{ type: "html", artifact_id: "later-chart", data: "<b>Chart</b>" }] });
    expect(after.commandExecutions).toBe(commands.commandExecutions);
    expect(after.executionOutput).toEqual(kind === "results"
      ? { executionId: "later-execution", kind: "results", resultId: "later-select" }
      : { executionId: "later-execution", kind: "rich" });
    expect(tracker.observe([active, after], active.id)).toBeUndefined();
    expect(tracker.observe([active, after], after.id)).toBeUndefined();
    const edited = { ...after, blocks: after.blocks.map(block => ({ ...block, code: `${block.code}\n-- edited` })) };
    expect(edited.executionOutput).toBe(after.executionOutput);
    expect(tracker.observe([active, edited], edited.id)).toBeUndefined();
    const reset = applyRuntimeEvent(edited, { event: "session.reset", payload: { session_id: edited.id } });
    expect(reset.executionOutput).toEqual({ executionId: "command-execution", kind: "commands" });
    expect(reset.commandExecutions).toBe(commands.commandExecutions);
  });

  it("does not preserve a SELECT output selection after reset when no completed command exists", () => {
    const before = completed(running(newSession()), { command_results: [], results: [frame("select-only")] });
    expect(before.executionOutput?.kind).toBe("results");
    const reset = applyRuntimeEvent(before, { event: "session.reset", payload: { session_id: before.id } });
    expect(reset.executionOutput).toBeUndefined();
  });
});

describe("SQL command messages", () => {
  const cases: Array<{ locale: Locale; zero: string; one: string; many: string; unknown: string; cancelled: string; error: string }> = [
    { locale: "pt-BR", zero: "0 linhas afetadas.", one: "1 linha afetada.", many: "1.234.567 linhas afetadas.", unknown: "Comando executado.", cancelled: "Execução cancelada.", error: "Erro na execução." },
    { locale: "en-US", zero: "0 rows affected.", one: "1 row affected.", many: "1,234,567 rows affected.", unknown: "Command executed.", cancelled: "Execution cancelled.", error: "Execution error." },
  ];

  it.each(cases)("renders zero, singular, localized large counts and unknown counts distinctly in $locale", values => {
    setLocale(values.locale);
    const markup = renderToStaticMarkup(createElement(CommandResults, { executions: [execution({ commands: [command(0), command(1, "INSERT", 2), command(1234567, "DELETE", 3), command(null, "CREATE", 4)] })], blockLabels: {} }));
    for (const text of [values.zero, values.one, values.many, values.unknown]) expect(markup).toContain(text);
    expect(markup).toContain("1. UPDATE");
    expect(markup).toContain("4. CREATE");
    expect(markup.replace(/<[^>]+>/g, "")).not.toContain("-1");
  });

  it.each(cases)("renders completed commands together with failure and cancellation feedback in $locale", values => {
    setLocale(values.locale);
    const markup = renderToStaticMarkup(createElement(CommandResults, {
      executions: [execution({ status: "failed", error: "Constraint <items> failed" }), execution({ executionId: "cancelled", status: "cancelled", commands: [command(0)] })], blockLabels: {},
    }));
    expect(markup).toContain("Constraint &lt;items&gt; failed");
    expect(markup).toContain(values.cancelled);
    expect(markup).toContain(values.zero);
    const fallback = renderToStaticMarkup(createElement(CommandResults, { executions: [execution({ status: "failed", error: undefined })], blockLabels: {} }));
    expect(fallback).toContain(values.error);
  });

  it("uses captured block names first and falls back to current block labels for unnamed blocks", () => {
    const markup = renderToStaticMarkup(createElement(CommandResults, {
      executions: [execution({ blockName: "Executed block" }), execution({ executionId: "unnamed", blockName: "", blockId: "second" })],
      blockLabels: { "block-1": "Renamed later", second: "SQL 2" },
    }));
    expect(markup).toContain("Executed block");
    expect(markup).not.toContain("Renamed later");
    expect(markup).toContain("SQL 2");
  });
});

class FeedbackTransport implements RuntimeTransport {
  executions: Record<string, unknown>[] = [];
  listener?: (event: RuntimeEvent) => void;
  async request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    if (method === "system.info") return { protocol_version: 1, python_version: "3.12.0", capabilities: { languages: ["sql", "python"], qt: false } } as T;
    if (method === "execution.run") this.executions.push(params);
    return { session_id: params.session_id, execution_id: params.execution_id, status: "queued" } as T;
  }
  async subscribe(listener: (event: RuntimeEvent) => void) { this.listener = listener; return () => {}; }
  finish(index: number, commands: SqlCommandResult[], results: ResultRef[] = []) {
    const request = this.executions[index];
    this.listener?.({ event: "execution.finished", payload: {
      session_id: String(request.session_id), execution_id: String(request.execution_id), block_id: String(request.block_id),
      status: "succeeded", duration_ms: 3, results, variables: [], command_results: commands,
    } });
  }
}

describe("SQL command feedback in real execution queues", () => {
  it("clears the previous batch on run, aggregates queued blocks despite focus changes, ignores stale completion and clears messages with results", async () => {
    const transport = new FeedbackTransport(), controller = new WorkspaceController(transport, undefined, { nativePersistence: true });
    const initial = controller.session()!, first = initial.blocks[0];
    controller.updateBlock(initial.id, first.id, { code: "UPDATE items SET value = 1; SELECT * FROM items", block_name: "update_items" });
    try {
      const seed = controller.runBlock(initial.id, first.id);
      await vi.waitFor(() => expect(transport.executions).toHaveLength(1));
      transport.finish(0, [command(1)], [frame()]);
      await seed;
      expect(controller.session(initial.id)?.commandExecutions).toHaveLength(1);
      controller.updateBlock(initial.id, first.id, { code: "UPDATE items SET value = 2" });
      const second = controller.addBlock(initial.id, "sql", "DELETE FROM obsolete");
      controller.updateBlock(initial.id, second.id, { block_name: "delete_obsolete" });
      const queue = controller.runAll(initial.id);
      expect(controller.session(initial.id)?.commandExecutions).toEqual([]);
      expect(controller.session(initial.id)?.executionOutput).toBeUndefined();
      await vi.waitFor(() => expect(transport.executions).toHaveLength(2));
      transport.finish(0, [command(999)]);
      expect(controller.session(initial.id)?.commandExecutions).toEqual([]);
      controller.focusBlock(initial.id, second.id);
      const background = controller.createSession();
      transport.finish(1, [command(3)]);
      await vi.waitFor(() => expect(transport.executions).toHaveLength(3));
      transport.finish(2, [command(0, "DELETE")]);
      await queue;
      const after = controller.session(initial.id)!;
      expect(after.busy).toBe(false);
      expect(after.currentExecutionId).toBeUndefined();
      expect(after.focusedBlockId).toBe(second.id);
      expect(controller.getSnapshot().activeId).toBe(background.id);
      expect(after.commandExecutions?.map(item => ({ blockId: item.blockId, blockName: item.blockName, commands: item.commands }))).toEqual([
        { blockId: first.id, blockName: "update_items", commands: [command(3)] },
        { blockId: second.id, blockName: "delete_obsolete", commands: [command(0, "DELETE")] },
      ]);
      expect(after.results.map(item => item.result_id)).toEqual(["previous-result"]);
      expect(after.executionOutput).toEqual({ executionId: String(transport.executions[2].execution_id), kind: "commands" });
      controller.clearResults(initial.id);
      expect(controller.session(initial.id)?.commandExecutions).toEqual([]);
      expect(controller.session(initial.id)?.results).toEqual([]);
      expect(controller.session(initial.id)?.executionOutput).toBeUndefined();
    } finally { controller.dispose(); }
  });
});
