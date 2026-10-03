import { describe, expect, it, vi } from "vitest";
import { WorkspaceController, applyRuntimeEvent, decodeDocument, encodeDocument, newSession } from "./workspace";
import type { ExecutionFinished, RuntimeEvent, RuntimeTransport } from "./runtime";

class FakeTransport implements RuntimeTransport {
  requests: Array<{ method: string; params: Record<string, unknown> }> = [];
  listener?: (event: RuntimeEvent) => void;
  subscriptions = 0;
  unavailable = false;
  async request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    this.requests.push({ method, params });
    if (this.unavailable) throw new Error("Runtime indisponível");
    if (method === "system.info") return { protocol_version: 1, python_version: "3.12.0", capabilities: { languages: ["sql", "python"], qt: false } } as T;
    return { session_id: params.session_id, execution_id: params.execution_id, status: "queued" } as T;
  }
  async subscribe(listener: (event: RuntimeEvent) => void) { this.subscriptions++; this.listener = listener; return () => {}; }
  executions() { return this.requests.filter((request) => request.method === "execution.run"); }
  finish(index: number, status: ExecutionFinished["status"] = "succeeded") {
    const request = this.executions()[index];
    this.listener?.({ event: "execution.finished", payload: {
      session_id: String(request.params.session_id), execution_id: String(request.params.execution_id), status,
      duration_ms: 12, error: status === "failed" ? "Syntax error" : undefined,
      results: status === "succeeded" ? [{ result_id: `result-${index}`, variable_name: "df", columns: [{ name: "value", dtype: "int64" }], row_count: 1 }] : [],
      variables: status === "succeeded" ? [{ name: "df", type: "DataFrame", preview: "1 row" }] : [],
    } });
  }
}

describe("Documentos .dpw", () => {
  it("preserva configurações de blocos, parâmetros, notificações e charts ao salvar", () => {
    const source = { version: "1.0", blocks: [{ language: "sql", code: "SELECT @day", block_name: "sales", is_active: false,
      height: 240, connection_name: "Prod", connection_group: "Company", database_name: "reports", sql_parameters: [{ name: "day", value: "today" }] }],
      shared_parameters: [{ name: "day", value: "today" }], shared_parameters_enabled: false,
      notification_config: { enabled: true, title: "{{rows}}" }, result_view_state: { charts: { configs: [{ type: "bar" }] } } };
    const document = decodeDocument(source);
    const encoded = encodeDocument(document);
    expect(encoded.shared_parameters_enabled).toBe(false);
    expect(encoded.notification_config).toEqual(source.notification_config);
    expect(encoded.result_view_state).toEqual(source.result_view_state);
    expect((encoded.blocks as Record<string, unknown>[])[0]).toMatchObject(source.blocks[0]);
    expect((encoded.blocks as Record<string, unknown>[])[0]).not.toHaveProperty("status");
    expect((encoded.blocks as Record<string, unknown>[])[0]).not.toHaveProperty("duration_ms");
  });
  it("rejeita linguagens/documentos inválidos sem executar conteúdo", () => {
    expect(() => decodeDocument({ blocks: [{ language: "html", code: "alert(1)" }] })).toThrow("não suportada");
    expect(() => decodeDocument({ tabs: [] })).toThrow("não contém");
    expect(() => decodeDocument({ blocks: [{ language: "sql", code: 1 }] })).toThrow("inválido");
  });
  it("aceita resposta workspace.read envelopada em document", () => {
    expect(decodeDocument({ document: { blocks: [{ language: "python", code: "x=1" }] } }).blocks[0].code).toBe("x=1");
  });
  it("edição durante gravação conserva o aviso de alterações não salvas", () => {
    const controller = new WorkspaceController(new FakeTransport()), session = controller.session()!;
    controller.updateBlock(session.id, session.blocks[0].id, { code: "SELECT saved" });
    const savedDocument = encodeDocument(controller.session(session.id)!);
    controller.updateBlock(session.id, session.blocks[0].id, { code: "SELECT edited while saving" });
    controller.saved(session.id, "C:/temp/analysis.dpw", savedDocument);
    expect(controller.session()?.modified).toBe(true); expect(controller.getSnapshot().message).toContain("ainda não salvas");
    expect(controller.session()?.blocks[0].code).toBe("SELECT edited while saving");
  });
  it("ACK de gravação marca como salvo apenas o documento que foi escrito", () => {
    const controller = new WorkspaceController(new FakeTransport()), session = controller.session()!;
    controller.updateBlock(session.id, session.blocks[0].id, { code: "SELECT saved" });
    controller.saved(session.id, "C:/temp/analysis.dpw", encodeDocument(controller.session(session.id)!));
    expect(controller.session()?.modified).toBe(false); expect(controller.session()?.filePath).toBe("C:/temp/analysis.dpw");
  });
});

describe("Eventos isolados por sessão e execução", () => {
  it("session.ready e eventos desconhecidos não alteram namespace/resultados de uma aba ociosa", () => {
    const session = { ...newSession(), images: [{ data: "image-data", mime: "image/png" }] };
    expect(applyRuntimeEvent(session, { event: "session.ready", payload: { session_id: session.id } })).toBe(session);
    expect(applyRuntimeEvent(session, { event: "future.event", payload: { session_id: session.id } } as unknown as RuntimeEvent)).toBe(session);
  });
  it("cancelar operação na fila preserva namespace até o evento session.reset", () => {
    const session = { ...newSession(), currentExecutionId: "pending", variables: [{ name: "keep", type: "int", preview: "42" }], images: [{ data: "image-data", mime: "image/png" }] };
    const cancelled = applyRuntimeEvent(session, { event: "execution.finished", payload: { session_id: session.id, execution_id: "pending", status: "cancelled", duration_ms: 0, results: [], variables: [] } });
    expect(cancelled.variables).toBe(session.variables); expect(cancelled.images).toBe(session.images);
    const reset = applyRuntimeEvent(cancelled, { event: "session.reset", payload: { session_id: session.id } });
    expect(reset.variables).toEqual([]); expect(reset.images).toEqual([]);
  });
  it("recarrega handles de DataFrame preservados após alteração in-place sem novo resultado", () => {
    const session = { ...newSession(), currentExecutionId: "mutation", results: [{ result_id: "existing", variable_name: "df", row_count: 1, columns: [{ name: "value", dtype: "int64" }] }] };
    const changed = applyRuntimeEvent(session, { event: "execution.finished", payload: { session_id: session.id, execution_id: "mutation", status: "succeeded", duration_ms: 1, results: [], variables: [{ name: "df", type: "DataFrame", preview: "2 rows" }] } });
    expect(changed.results).toBe(session.results); expect(changed.resultRevision).toBe(session.resultRevision + 1); expect(changed.variables[0].preview).toBe("2 rows");
  });
  it("ignora resultados atrasados de execução anterior", () => {
    const session = { ...newSession(), currentExecutionId: "current" };
    const stale: RuntimeEvent = { event: "execution.finished", payload: { session_id: session.id, execution_id: "previous", status: "succeeded", duration_ms: 1,
      results: [{ result_id: "old", variable_name: "old", row_count: 100, columns: [] }], variables: [] } };
    expect(applyRuntimeEvent(session, stale)).toBe(session);
  });
  it("execution.started marca o bloco registrado mesmo após mudar o foco", () => {
    const base = newSession(), first = { ...base.blocks[0], status: "queued" as const }, second = { ...first, id: "second-block" };
    const session = { ...base, blocks: [first, second], focusedBlockId: second.id, currentBlockId: first.id, currentExecutionId: "current" };
    const started = applyRuntimeEvent(session, { event: "execution.started", payload: { session_id: session.id, execution_id: "current" } });
    expect(started.blocks[0].status).toBe("running"); expect(started.blocks[1].status).toBe("queued");
  });
  it("um reset invalida resultados, variáveis e conexão desta aba", () => {
    const session = { ...newSession(), variables: [{ name: "x", type: "int", preview: "10" }], results: [{ result_id: "r", variable_name: "df", row_count: 1, columns: [] }],
      connection: { db_type: "sqlite" as const, host: "", port: 0, database: ":memory:", username: "" } };
    const reset = applyRuntimeEvent(session, { event: "session.reset", payload: { session_id: session.id } });
    expect(reset.variables).toEqual([]); expect(reset.results).toEqual([]); expect(reset.connection).toBeUndefined(); expect(reset.notice).toContain("descartadas");
    expect(applyRuntimeEvent(session, { event: "session.reset", payload: { session_id: "another-session" } })).toBe(session);
  });
});

describe("Execução e fila", () => {
  it("download direto usa a seleção e não persiste o destino como parte do bloco",async()=>{
    const transport=new FakeTransport(),controller=new WorkspaceController(transport),session=controller.session()!,block=session.blocks[0];
    controller.updateBlock(session.id,block.id,{code:"SELECT 1; SELECT 2;",connection_id:"other",sql_parameters:[{name:"id",value:42}]});
    const job=controller.runToFile(session.id,block.id,{path:"C:/temp/export.csv",format:"csv"},"SELECT 2;");
    await vi.waitFor(()=>expect(transport.executions()).toHaveLength(1));
    expect(transport.executions()[0].params).toMatchObject({code:"SELECT 2;",connection_id:"other",export:{path:"C:/temp/export.csv",format:"csv"}});
    transport.finish(0);await job;
    expect((encodeDocument(controller.session()!).blocks as object[])[0]).not.toHaveProperty("export");
  });
  it("timer executa imediatamente e agenda apenas depois da fila, sem sobreposição",async()=>{
    vi.useFakeTimers();try{
      const transport=new FakeTransport(),controller=new WorkspaceController(transport),session=controller.session()!;
      controller.updateBlock(session.id,session.blocks[0].id,{code:"SELECT 1"});
      const started=controller.startPeriodic(session.id,1);await vi.advanceTimersByTimeAsync(0);
      expect(transport.executions()).toHaveLength(1);
      await vi.advanceTimersByTimeAsync(5000);expect(transport.executions()).toHaveLength(1);
      transport.finish(0);await started;await vi.advanceTimersByTimeAsync(999);expect(transport.executions()).toHaveLength(1);
      await vi.advanceTimersByTimeAsync(1);expect(transport.executions()).toHaveLength(2);
      controller.stopPeriodic(session.id);transport.finish(1);await vi.advanceTimersByTimeAsync(5000);expect(transport.executions()).toHaveLength(2);
    }finally{vi.useRealTimers();}
  });
  it("restore nativo conserva identidade de sessão e foco por block_key; arquivos externos recebem novo id",()=>{
    const transport=new FakeTransport(),controller=new WorkspaceController(transport),session=controller.session()!,second=controller.addBlock(session.id,"python","value=42");
    controller.focusBlock(session.id,second.id);const snapshot=controller.nativeSnapshot();controller.restoreSnapshot(snapshot);
    const restored=controller.session()!;expect(restored.id).toBe(session.id);expect(restored.blocks.find(b=>b.id === restored.focusedBlockId)?.code).toBe("value=42");
    expect(decodeDocument(encodeDocument(restored)).id).not.toBe(session.id);
  });
  it("eventos de runtime não incrementam a revisão dos documentos nem regravam código",async()=>{
    const transport=new FakeTransport(),controller=new WorkspaceController(transport),session=controller.session()!;
    controller.updateBlock(session.id,session.blocks[0].id,{code:"SELECT 1"});const revision=controller.getSnapshot().documentRevision;
    const job=controller.runAll(session.id);await vi.waitFor(()=>expect(transport.executions()).toHaveLength(1));
    transport.finish(0);await job;expect(controller.getSnapshot().documentRevision).toBe(revision);
  });
  it("um evento de conclusão antes do ACK encerra a fila sem aguardar a resposta atrasada", async () => {
    const transport = new FakeTransport(), baseRequest = transport.request.bind(transport);
    let rejectAck!: (error: Error) => void;
    transport.request = async <T>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
      const value = await baseRequest<T>(method, params);
      if (method === "execution.run") return new Promise<T>((_resolve, reject) => { rejectAck = reject; });
      return value;
    };
    const controller = new WorkspaceController(transport), session = controller.session()!;
    controller.updateBlock(session.id, session.blocks[0].id, { code: "SELECT 1" });
    const job = controller.runAll(session.id); await vi.waitFor(() => expect(transport.executions()).toHaveLength(1));
    transport.finish(0); await job;
    expect(controller.session()?.busy).toBe(false); expect(controller.session()?.blocks[0].status).toBe("succeeded");
    rejectAck(new Error("ACK atrasado")); await Promise.resolve(); await Promise.resolve();
    expect(controller.session()?.blocks[0].status).toBe("succeeded");
  });
  it("erro fatal de uma sessão rejeita job antes do ACK e não afeta outra aba", async () => {
    const transport = new FakeTransport(), baseRequest = transport.request.bind(transport);
    transport.request = async <T>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
      const value = await baseRequest<T>(method, params);
      return method === "execution.run" ? new Promise<T>(() => {}) : value;
    };
    const controller = new WorkspaceController(transport), first = controller.session()!, second = controller.createSession();
    controller.updateBlock(first.id, first.blocks[0].id, { code: "x=1", language: "python" });
    controller.patchSession(second.id, (session) => ({ ...session, variables: [{ name: "keep", type: "int", preview: "10" }] }));
    const job = controller.runAll(first.id), rejected = expect(job).rejects.toThrow("failed to start");
    await vi.waitFor(() => expect(transport.executions()).toHaveLength(1));
    transport.listener?.({ event: "session.error", payload: { session_id: first.id, error: "Session worker repeatedly failed to start" } }); await rejected;
    expect(controller.session(first.id)?.busy).toBe(false); expect(controller.session(first.id)?.blocks[0].status).toBe("failed");
    expect(controller.session(first.id)?.notice).toContain("reabra"); expect(controller.session(second.id)?.variables[0].name).toBe("keep");
    expect(controller.getSnapshot().runtimeStatus).toBe("ready");
    await expect(controller.runAll(first.id)).rejects.toThrow("reabra");
    expect(transport.executions()).toHaveLength(1);
  });
  it("erro de sessão durante session.create impede envio da execução", async () => {
    const transport = new FakeTransport(), baseRequest = transport.request.bind(transport);
    transport.request = async <T>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
      const value = await baseRequest<T>(method, params);
      if (method === "session.create") transport.listener?.({ event: "session.error", payload: { session_id: String(params.session_id), error: "Worker unavailable" } });
      return value;
    };
    const controller = new WorkspaceController(transport), session = controller.session()!;
    controller.updateBlock(session.id, session.blocks[0].id, { code: "x=1", language: "python" });
    await expect(controller.runAll(session.id)).rejects.toThrow("Worker unavailable");
    expect(transport.executions()).toHaveLength(0); expect(controller.session()?.busy).toBe(false);
  });
  it("system.info atrasado não torna o runtime saudável depois de backend.exited", async () => {
    const transport = new FakeTransport(), baseRequest = transport.request.bind(transport);
    let resolveInfo!: (value: unknown) => void;
    transport.request = async <T>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
      const value = await baseRequest<T>(method, params);
      if (method === "system.info") return new Promise<T>((resolve) => { resolveInfo = resolve as (value: unknown) => void; });
      return value;
    };
    const controller = new WorkspaceController(transport), init = controller.initialize();
    await vi.waitFor(() => expect(resolveInfo).toBeTypeOf("function"));
    transport.listener?.({ event: "backend.exited", payload: { message: "Runtime disconnected" } });
    resolveInfo({ protocol_version: 1, python_version: "3.12.0", capabilities: {} }); await init;
    expect(controller.getSnapshot().runtimeStatus).toBe("unavailable"); expect(controller.getSnapshot().runtimeInfo).toBeUndefined();
  });
  it("aguarda cada bloco e interrompe fila no primeiro erro, ignorando blocos inativos", async () => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), session = controller.session()!;
    const first = session.blocks[0], disabled = controller.addBlock(session.id), second = controller.addBlock(session.id), third = controller.addBlock(session.id);
    controller.updateBlock(session.id, first.id, { code: "SELECT 1" });
    controller.updateBlock(session.id, disabled.id, { code: "SELECT skipped", is_active: false });
    controller.updateBlock(session.id, second.id, { code: "SELECT wrong" });
    controller.updateBlock(session.id, third.id, { code: "SELECT 3" });
    const job = controller.runAll(session.id);
    await vi.waitFor(() => expect(transport.executions()).toHaveLength(1));
    expect(transport.executions()[0].params.code).toBe("SELECT 1");
    transport.finish(0);
    await vi.waitFor(() => expect(transport.executions()).toHaveLength(2));
    expect(transport.executions()[1].params.code).toBe("SELECT wrong");
    transport.finish(1, "failed"); await job;
    expect(transport.executions()).toHaveLength(2);
    expect(controller.session(session.id)?.busy).toBe(false);
    expect(controller.session(session.id)?.blocks.find((block) => block.id === third.id)?.status).toBe("cancelled");
    expect(controller.session(session.id)?.results).toEqual([]);
  });
  it("usa somente seleção recebida e evita execução simultânea na mesma aba", async () => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), session = controller.session()!, block = session.blocks[0];
    controller.updateBlock(session.id, block.id, { code: "SELECT 1; SELECT 2;", block_name: "sales" });
    const job = controller.runBlock(session.id, block.id, "SELECT 2;");
    await vi.waitFor(() => expect(transport.executions()).toHaveLength(1));
    expect(transport.executions()[0].params).toMatchObject({ code: "SELECT 2;", variable_name: "sales" });
    await expect(controller.runBlock(session.id, block.id)).rejects.toThrow("em andamento");
    transport.finish(0); await job;
  });
  it("duas abas executam em paralelo sem compartilhar seus resultados", async () => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), first = controller.session()!, second = controller.createSession();
    controller.updateBlock(first.id, first.blocks[0].id, { code: "SELECT 1" }); controller.updateBlock(second.id, second.blocks[0].id, { code: "SELECT 2" });
    const jobs = [controller.runAll(first.id), controller.runAll(second.id)];
    await vi.waitFor(() => expect(transport.executions()).toHaveLength(2));
    transport.finish(1); transport.finish(0); await Promise.all(jobs);
    expect(controller.session(first.id)?.results[0].result_id).toBe("result-0");
    expect(controller.session(second.id)?.results[0].result_id).toBe("result-1");
  });
  it("cancelamento e reset não afetam namespace de outra aba", async () => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), first = controller.session()!, second = controller.createSession();
    controller.patchSession(second.id, (session) => ({ ...session, variables: [{ name: "keep", type: "int", preview: "1" }] }));
    controller.updateBlock(first.id, first.blocks[0].id, { code: "while True: pass", language: "python" });
    const job = controller.runAll(first.id); await vi.waitFor(() => expect(transport.executions()).toHaveLength(1));
    await controller.cancel(first.id); transport.listener?.({ event: "session.reset", payload: { session_id: first.id } }); await job;
    expect(controller.session(first.id)?.notice).toContain("descartadas");
    expect(controller.session(second.id)?.variables[0].name).toBe("keep");
    expect(controller.session(first.id)?.busy).toBe(false);
  });
  it("runtime indisponível nunca produz resultado simulado", async () => {
    const transport = new FakeTransport(); transport.unavailable = true;
    const controller = new WorkspaceController(transport), session = controller.session()!; controller.updateBlock(session.id, session.blocks[0].id, { code: "SELECT 1" });
    await expect(controller.runAll(session.id)).rejects.toThrow("indisponível");
    expect(controller.getSnapshot().runtimeStatus).toBe("unavailable"); expect(controller.session()?.results).toEqual([]); expect(transport.executions()).toHaveLength(0);
  });
  it("brokerdeath rejeita jobs e permite reconectar sem duplicar o listener", async () => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), session = controller.session()!;
    controller.updateBlock(session.id, session.blocks[0].id, { language: "python", code: "x=1" });
    const job = controller.runAll(session.id); const rejected = expect(job).rejects.toThrow("Broker encerrado");
    await vi.waitFor(() => expect(transport.executions()).toHaveLength(1));
    transport.listener?.({ event: "backend.exited", payload: { message: "Broker encerrado" } }); await rejected;
    expect(controller.getSnapshot().runtimeStatus).toBe("unavailable"); expect(controller.session()?.busy).toBe(false);
    await controller.retryRuntime(); expect(controller.getSnapshot().runtimeStatus).toBe("ready"); expect(transport.subscriptions).toBe(1);
    const secondJob = controller.runAll(session.id); await vi.waitFor(() => expect(transport.executions()).toHaveLength(2));
    transport.finish(1); await secondJob; expect(transport.requests.filter((request) => request.method === "session.create")).toHaveLength(2);
  });
  it("fechar um resultado libera seu handle e preserva namespace e outras tabelas", async () => {
    const transport=new FakeTransport(),controller=new WorkspaceController(transport),session=controller.session()!;
    const first={result_id:"a",variable_name:"df",columns:[],row_count:1},second={...first,result_id:"b",variable_name:"other"};
    controller.patchSession(session.id,s=>({...s,results:[first,second],variables:[{name:"df",type:"DataFrame",preview:"one row"}],blocks:s.blocks.map(b=>({...b,results:[first,second]}))}));
    controller.closeResult(session.id,"a");
    expect(controller.session()?.results).toEqual([second]);expect(controller.session()?.blocks[0].results).toEqual([second]);
    expect(controller.session()?.variables[0].name).toBe("df");
    expect(transport.requests).toContainEqual({method:"result.release",params:{session_id:session.id,result_id:"a"}});
  });
  it("a senha não entra no documento ou rascunho persistido", async () => {
    const transport = new FakeTransport(), saved = new Map<string, string>();
    const controller = new WorkspaceController(transport, { getItem: (key) => saved.get(key) ?? null, setItem: (key, value) => { saved.set(key, value); } });
    await controller.connect(controller.session()!.id, { db_type: "postgresql", host: "localhost", port: 5432, database: "reports", username: "user", password: "SECRET_TEST_PASSWORD" });
    controller.persist(); expect([...saved.values()].join()).not.toContain("SECRET_TEST_PASSWORD"); expect(controller.session()?.connection).not.toHaveProperty("password");
  });
  it("restaura rascunho ainda modificado para manter confirmação ao fechar", () => {
    const saved = new Map<string, string>(), storage = { getItem: (key: string) => saved.get(key) ?? null, setItem: (key: string, value: string) => { saved.set(key, value); } };
    const first = new WorkspaceController(new FakeTransport(), storage), session = first.session()!;
    first.updateBlock(session.id, session.blocks[0].id, { code: "SELECT unsaved" }); first.persist();
    const restored = new WorkspaceController(new FakeTransport(), storage);
    expect(restored.session()?.blocks[0].code).toBe("SELECT unsaved"); expect(restored.session()?.modified).toBe(true);
  });
  it("quota de armazenamento não cria um ciclo infinito de tentativas", () => {
    vi.useFakeTimers();
    try {
      const setItem = vi.fn(() => { throw new Error("QuotaExceededError"); });
      const controller = new WorkspaceController(new FakeTransport(), { getItem: () => null, setItem });
      const session = controller.session()!; controller.updateBlock(session.id, session.blocks[0].id, { code: "x=1" });
      vi.advanceTimersByTime(2_000); expect(setItem).toHaveBeenCalledTimes(1);
      expect(controller.getSnapshot().message).toContain("Não foi possível salvar");
    } finally { vi.useRealTimers(); }
  });
});
