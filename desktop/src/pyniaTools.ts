import type { WorkspaceController, SessionDocument, Block } from "./workspace";
import { disposeModel, focusEditor, getRegisteredEditor, insertInEditor, replaceEditorCode, selectedCode } from "./editorRegistry";
import { runtime, type Language } from "./runtime";
import type { ServiceEvent } from "./serviceEvents";
import { editCodeLines, validateWholeBlockReplace } from "./pyniaEdits";

export interface PyniaToolCallbacks {
  chart?: (arguments_: Record<string, unknown>, sessionId: string) => Promise<unknown> | unknown;
  notify?: (title: string, message: string, success: boolean) => void;
  extraContext?: (sessionId: string) => Record<string, unknown>;
}
const editHistory = new Map<string, string[]>();
function language(value: unknown, fallback: Language = "python"): Language {
  if (value == null || value === "") return fallback;
  if (value !== "python" && value !== "sql") throw new Error(`Linguagem de bloco não suportada: ${String(value)}.`);
  return value;
}
function source(value: unknown, required = false): string {
  if (typeof value !== "string" || (required && !value.trim())) throw new Error("Código deve ser uma string não vazia.");
  if (new TextEncoder().encode(value).byteLength > 1024 * 1024) throw new Error("Código excede 1 MB.");
  return value;
}
function resolveBlock(session: SessionDocument, args: Record<string, unknown>): Block {
  if (typeof args.block_name === "string" && args.block_name) {
    const matching = session.blocks.filter((block) => block.block_name === args.block_name);
    if (matching.length > 1) throw new Error("Nome de bloco ambíguo; use block_index.");
    if (!matching.length) throw new Error(`Bloco não encontrado: ${args.block_name}.`);
    return matching[0];
  }
  if (args.block_index != null) {
    const index = args.block_index;
    if (typeof index !== "number" || !Number.isInteger(index) || index < 0 || index >= session.blocks.length) throw new Error("block_index fora do intervalo (índice começa em 0).");
    return session.blocks[index];
  }
  const block = session.blocks.find((item) => item.id === session.focusedBlockId);
  if (!block) throw new Error("Nenhum bloco está em foco nesta sessão."); return block;
}
function summary(session: SessionDocument, block: Block) {
  return { block_index: session.blocks.indexOf(block), block_id: block.id, block_name: block.block_name, language: block.language, active: block.is_active,
    line_count: block.code.split("\n").length, characters: block.code.length, status: block.status, focused: session.focusedBlockId === block.id,
    connection_id: block.connection_id ?? session.savedConnectionId, database: block.database_name ?? session.database, schema: block.schema ?? session.schema };
}
function remember(block: Block) { editHistory.set(block.id, [...(editHistory.get(block.id) ?? []).slice(-19), block.code]); }
function updateCode(workspace: WorkspaceController, sessionId: string, block: Block, code: string) { remember(block); replaceEditorCode(block.id, code); workspace.updateBlock(sessionId, block.id, { code }); }

export async function handlePyniaTool(workspace: WorkspaceController, event: ServiceEvent, callbacks: PyniaToolCallbacks = {}): Promise<unknown> {
  const payload = event.payload, sessionId = payload.session_id;
  if (event.event !== "pynia.tool_request" || typeof sessionId !== "string" || typeof payload.name !== "string") throw new Error("Solicitação de ferramenta Pynia inválida.");
  const session = workspace.session(sessionId);
  if (!session) throw new Error("A aba desta conversa já foi fechada.");
  const args = payload.arguments && typeof payload.arguments === "object" && !Array.isArray(payload.arguments) ? payload.arguments as Record<string, unknown> : {};
  const name = payload.name.replace(/^datapyn[-/.](?=datapyn_)/i, "");
  if (name === "datapyn_snapshot") {
    const blocks = session.blocks.map((block) => summary(session, block));
    if (args.action === "blocks") return { blocks };
    return { tab_id: session.id, tab_name: session.title, tab_index: workspace.getSnapshot().sessions.indexOf(session), is_connected: !!session.connection,
      is_running: session.busy, focused_block: blocks.find((block) => block.focused), blocks: args.action === "full" ? session.blocks.map((block) => ({ ...summary(session, block), code_preview: block.code.slice(0, 800), code_truncated: block.code.length > 800 })) : blocks,
      connection: session.connection, database: session.database, schema: session.schema, variables: session.variables,
      execution_state: { active_result: session.results.at(-1), results: session.results }, ...callbacks.extraContext?.(sessionId) };
  }
  if (name === "datapyn_inspect") {
    if (args.kind === "selection") {
      const block = resolveBlock(session, args), editor = getRegisteredEditor(block.id);
      return { text: selectedCode(block.id) ?? "", block: summary(session, block), selection: editor?.getSelection(), cursor: editor?.getPosition() };
    }
    if (args.kind === "reference") {
      const reference = String(args.reference ?? ""), match = reference.match(/^#?(tab|block)(?::(.+)|(\d+))$/i);
      if (!match) throw new Error("Referência inválida. Use #block1, #block:nome, #tab1 ou #tab:nome.");
      if (match[1].toLowerCase() === "tab") {
        const sessions = workspace.getSnapshot().sessions, tab = match[2] ? sessions.find((item) => item.title === match[2]) : sessions[Number(match[3]) - 1];
        if (!tab) throw new Error("Aba referenciada não encontrada.");
        return { type: "tab", tab_id: tab.id, tab_name: tab.title, blocks: tab.blocks.map((block) => ({ ...summary(tab, block), code_preview: block.code.slice(0, 800) })) };
      }
      const block = resolveBlock(session, match[2] ? { block_name: match[2] } : { block_index: Number(match[3]) - 1 });
      const code = block.code.split("\n").slice(0, 400).join("\n").slice(0, 24000);
      return { ...summary(session, block), type: "block", code, truncated: code.length !== block.code.length };
    }
    const block = resolveBlock(session, args), detail = String(args.detail ?? "result");
    if (detail === "structure") return summary(session, block);
    if (detail === "execution") return { ...summary(session, block), error: block.error, duration_ms: block.duration_ms, results: session.results };
    if (detail === "result") {
      const result = Array.isArray(block.results) ? block.results.at(-1) : block.block_name ? session.results.find((item) => item.variable_name === block.block_name) : undefined;
      if (!result) return { ...summary(session, block), result: null };
      const requested = args.max_rows == null ? 20 : Number(args.max_rows);
      if (!Number.isInteger(requested) || requested < 1) throw new Error("max_rows deve ser um inteiro positivo.");
      const page = await runtime.request("result.page", { session_id: sessionId, result_id: result.result_id, offset: 0, limit: Math.min(1000, requested) });
      return { ...summary(session, block), result, page };
    }
    if (detail !== "code") throw new Error(`Tipo de inspeção desconhecido: ${detail}.`);
    const lines = block.code.split("\n"); let start = Number(args.start_line ?? 1), end = Number(args.end_line ?? Math.min(lines.length, start + 119));
    if (args.around != null) { const index = lines.findIndex((line) => line.includes(String(args.around))); if (index < 0) throw new Error("Âncora não encontrada no bloco."); start = Math.max(1, index - 10); end = Math.min(lines.length, index + 30); }
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start || end > lines.length) throw new Error("Intervalo de linhas inválido.");
    return { ...summary(session, block), start_line: start, end_line: end, code: lines.slice(start - 1, end).join("\n") };
  }
  if (name === "datapyn_notify") {
    const title = String(args.title ?? "Pynia"), message = String(args.message ?? ""); workspace.message(`${title}: ${message}`); callbacks.notify?.(title, message, args.success !== false); return { shown: true };
  }
  if (name === "datapyn_chart") {
    if (!callbacks.chart) throw new Error("O painel de gráficos não está disponível nesta janela."); return callbacks.chart(args, sessionId);
  }
  if (name === "datapyn_blocks") {
    const operation = String(args.operation ?? "create");
    if (operation === "tab") { const next = workspace.createSession(); if (args.title) workspace.renameSession(next.id, String(args.title)); return { tab_id: next.id, title: workspace.session(next.id)?.title }; }
    if (operation === "focus") { const block = resolveBlock(session, args); workspace.activate(sessionId); workspace.focusBlock(sessionId, block.id); requestAnimationFrame(() => focusEditor(block.id)); return summary(session, block); }
    if (session.busy) throw new Error("Aguarde a execução para alterar blocos desta sessão.");
    if (operation === "duplicate") { const copy = workspace.duplicateBlock(sessionId, resolveBlock(session, args).id); return copy ? summary(workspace.session(sessionId)!, copy) : { error: "Bloco não encontrado." }; }
    if (operation !== "create") throw new Error(`Operação de blocos desconhecida: ${operation}.`);
    const block = workspace.addBlock(sessionId, language(args.language), args.code == null ? "" : source(args.code), session.focusedBlockId);
    if (args.block_name) workspace.updateBlock(sessionId, block.id, { block_name: String(args.block_name) });
    return summary(workspace.session(sessionId)!, workspace.session(sessionId)!.blocks.find((item) => item.id === block.id)!);
  }
  if (name === "datapyn_edit") {
    if (session.busy) throw new Error("Aguarde a execução para editar esta sessão.");
    const block = resolveBlock(session, args), operation = String(args.operation ?? "replace");
    if (operation === "delete") { workspace.removeBlock(sessionId, block.id); disposeModel(block.id); editHistory.delete(block.id); return { deleted: true, block_id: block.id }; }
    if (operation === "rename") { const newName = String(args.new_name ?? "").trim(); if (!newName) throw new Error("new_name é obrigatório."); workspace.updateBlock(sessionId, block.id, { block_name: newName }); return { block_id: block.id, block_name: newName }; }
    if (operation === "language") { const value = language(args.language, block.language); workspace.updateBlock(sessionId, block.id, { language: value }); return { block_id: block.id, language: value }; }
    if (["undo", "restore"].includes(operation)) {
      const history = editHistory.get(block.id), old = history?.pop(); if (old == null) throw new Error("Não há edição da Pynia para desfazer neste bloco."); replaceEditorCode(block.id, old); workspace.updateBlock(sessionId, block.id, { code: old }); return { restored: true, block_id: block.id };
    }
    const content = source(args.content ?? args.code ?? "");
    if (operation === "selection") {
      const editor = getRegisteredEditor(block.id); if (!editor) throw new Error("O editor deste bloco não está visível. Foque o bloco antes de editar a seleção.");
      remember(block); insertInEditor(block.id, content); return { block_id: block.id, replaced_selection: true };
    }
    if (operation === "lines" || (operation === "replace" && (args.start_line != null || args.end_line != null))) updateCode(workspace, sessionId, block, editCodeLines(block.code, args.start_line ?? 1, args.end_line, content, String(args.line_operation ?? "replace")));
    else if (operation === "replace") { validateWholeBlockReplace(block.code, content, args.force); updateCode(workspace, sessionId, block, content); }
    else throw new Error(`Operação de edição desconhecida: ${operation}.`);
    return { updated: true, block_id: block.id, characters: workspace.session(sessionId)!.blocks.find((item) => item.id === block.id)!.code.length };
  }
  if (name === "datapyn_run") {
    const mode = String(args.mode ?? "block");
    if (mode === "all") { await workspace.runAll(sessionId); return { statuses: workspace.session(sessionId)?.blocks.map((block) => ({ block_id: block.id, status: block.status, error: block.error })) }; }
    let block: Block, executionCode: string | undefined;
    if (mode === "write") {
      if (session.busy) throw new Error("Aguarde a execução antes de escrever um bloco.");
      const code = source(args.code, true), matching = args.block_name ? session.blocks.find((item) => item.block_name === args.block_name) : args.block_index != null ? resolveBlock(session, args) : undefined;
      executionCode = code;
      if (matching) { validateWholeBlockReplace(matching.code, code, args.force); updateCode(workspace, sessionId, matching, code); workspace.updateBlock(sessionId, matching.id, { language: language(args.language, matching.language) }); block = matching; }
      else { block = workspace.addBlock(sessionId, language(args.language), code, session.focusedBlockId); if (args.block_name) workspace.updateBlock(sessionId, block.id, { block_name: String(args.block_name) }); }
    } else if (mode === "block") block = resolveBlock(session, args); else throw new Error(`Modo de execução desconhecido: ${mode}.`);
    // Write mode explicitly runs the supplied code, never a range from the old editor.
    await workspace.runBlock(sessionId, block.id, executionCode);
    const completed = workspace.session(sessionId)!.blocks.find((item) => item.id === block.id)!;
    if (completed.status === "failed") throw new Error(completed.error || "A execução do bloco falhou.");
    return { ...summary(workspace.session(sessionId)!, completed), duration_ms: completed.duration_ms, results: workspace.session(sessionId)!.results };
  }
  throw new Error(`Ferramenta não suportada pelo host de interface: ${name}.`);
}
