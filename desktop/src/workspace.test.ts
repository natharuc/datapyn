import { describe, expect, it, vi } from "vitest";
import { captureEditorViewState,models,restoreEditorViewState,takeRestoredEditorViewState } from "./editorRegistry";
import { diffNativeWorkspace } from "./nativeDrafts";
import { WorkspaceController, applyRuntimeEvent, decodeDocument, encodeDocument, newSession } from "./workspace";
import type { ExecutionFinished, RuntimeEvent, RuntimeTransport } from "./runtime";

describe("incremental workspace recovery",()=>{
  it("keeps large unaffected document/record references and sends only the edited session",()=>{
    const controller=new WorkspaceController(new FakeTransport(),undefined,{nativePersistence:true}),first=controller.session()!;
    const large=controller.createSession();controller.updateBlock(large.id,large.blocks[0].id,{code:"x".repeat(2_000_000)});
    const before=controller.nativeSnapshot();controller.updateBlock(first.id,first.blocks[0].id,{code:"SELECT changed"});const after=controller.nativeSnapshot();
    expect(after.documents[1]).toBe(before.documents[1]);expect(after.documents[1].document).toBe(before.documents[1].document);
    expect(diffNativeWorkspace("p",after,before)!.upserts!.map(record=>record.sessionId)).toEqual([first.id]);controller.dispose();
  });
  it("persists focus/view state in private headers while keeping public code payload unchanged",()=>{
    const controller=new WorkspaceController(new FakeTransport(),undefined,{nativePersistence:true}),session=controller.session()!,second=controller.addBlock(session.id,"python","print(1)");
    controller.focusBlock(session.id,session.blocks[0].id);const before=controller.nativeSnapshot();controller.focusBlock(session.id,second.id);
    const view={cursorState:[],viewState:{scrollTop:250,scrollLeft:0},contributionsState:{}};
    models.set(second.id,{model:{},viewState:null,editor:{saveViewState:()=>view}} as never);captureEditorViewState(second.id);
    const after=controller.nativeSnapshot();expect(after.documents[0].document).toBe(before.documents[0].document);
    expect(after.documents[0].editorViewState?.[second.id]).toEqual(view);expect(diffNativeWorkspace("p",after,before)!.upserts![0]).not.toHaveProperty("document");
    expect(encodeDocument(controller.session()!)).not.toHaveProperty("editorViewState");models.delete(second.id);controller.dispose();
  });
  it("restores active tab, stable block IDs, focus and cursor without starting Python or timers",()=>{
    const first=new WorkspaceController(new FakeTransport(),undefined,{nativePersistence:true}),extra=first.createSession(),block=first.addBlock(extra.id,"python","raise RuntimeError('must not run')");
    const saved=first.nativeSnapshot(),view={cursorState:[],viewState:{scrollTop:99},contributionsState:{}};
    saved.documents[1]={...saved.documents[1],editorViewState:{[block.id]:view}};
    const transport=new FakeTransport(),restored=new WorkspaceController(transport,undefined,{nativePersistence:true});restored.restoreSnapshot(saved);
    expect(restored.session()!.id).toBe(extra.id);expect(restored.session()!.focusedBlockId).toBe(block.id);expect(restored.session()!.blocks[1].id).toBe(block.id);
    expect(takeRestoredEditorViewState(block.id)).toEqual(view);expect(transport.requests).toEqual([]);expect(restored.session()!.busy).toBe(false);first.dispose();restored.dispose();
  });
  it("does not read/write synchronous browser recovery in native mode and migrates it only once on demand",()=>{
    const record={title:"Legacy",document:{blocks:[{language:"python",code:"saved=1"}]}};
    const getItem=vi.fn((key:string)=>key.endsWith("v1")?JSON.stringify({sessions:[record]}):null),setItem=vi.fn();
    const controller=new WorkspaceController(new FakeTransport(),{getItem,setItem},{nativePersistence:true});controller.persist();expect(getItem).not.toHaveBeenCalled();expect(setItem).not.toHaveBeenCalled();
    expect(controller.restoreBrowserDraftMigration()).toBe(true);expect(controller.session()!.blocks[0].code).toBe("saved=1");const reads=getItem.mock.calls.length;
    expect(controller.restoreBrowserDraftMigration()).toBe(false);expect(getItem).toHaveBeenCalledTimes(reads);controller.dispose();
  });
  it("browser fallback writes only dirty records and preserves active tab on reload",()=>{
    const values=new Map<string,string>(),writes:string[]=[],storage={getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value);writes.push(key);},removeItem:(key:string)=>values.delete(key)};
    const controller=new WorkspaceController(new FakeTransport(),storage),first=controller.session()!,second=controller.createSession();controller.persist();writes.length=0;
    controller.updateBlock(first.id,first.blocks[0].id,{code:"SELECT edited"});controller.persist();
    expect(writes.filter(key=>key!=="datapyn.desktop.documents.v2")).toEqual([`datapyn.desktop.documents.v2.${first.id}`]);
    const restored=new WorkspaceController(new FakeTransport(),storage);expect(restored.session()!.id).toBe(second.id);expect(restored.session(first.id)!.blocks[0].code).toBe("SELECT edited");controller.dispose();restored.dispose();
  });
});

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

describe("execution block names", () => {
  it.each(["Tipos após nulos", "python_result"])("keeps Python name '%s' as a display label, without a result destination", async blockName => {
    const transport = new FakeTransport(), baseRequest = transport.request.bind(transport);
    transport.request = async <T>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
      const value = await baseRequest<T>(method, params);
      if (method === "execution.run" && params.variable_name === "Tipos após nulos") {
        throw new Error("variable_name must be a valid Python identifier");
      }
      return value;
    };
    const controller = new WorkspaceController(transport), session = controller.session()!, block = session.blocks[0];
    const code = "frame = pd.DataFrame({'value': [1]})\nframe";
    controller.updateBlock(session.id, block.id, { language: "python", code, block_name: blockName });
    try {
      const job = controller.runBlock(session.id, block.id);
      // Observe request failures immediately, before waiting for the completion event.
      const completed = job.then(() => undefined, error => error);
      await vi.waitFor(() => expect(transport.executions()).toHaveLength(1));
      const request = transport.executions()[0].params;
      expect(request).toMatchObject({ language: "python", code });
      expect(request).not.toHaveProperty("variable_name");
      expect(request.notification).toMatchObject({ context: { block_name: blockName, block_id: block.id } });
      transport.finish(0);
      expect(await completed).toBeUndefined();
      expect(controller.session(session.id)?.blocks[0]).toMatchObject({ block_name: blockName, status: "succeeded", error: undefined });
      expect((encodeDocument(controller.session(session.id)!).blocks as Record<string, unknown>[])[0].block_name).toBe(blockName);
    } finally { controller.dispose(); }
  });
  it("retains the SQL block name as the result destination", async () => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), session = controller.session()!, block = session.blocks[0];
    controller.updateBlock(session.id, block.id, { language: "sql", code: "SELECT 1 AS value", block_name: "sql_result" });
    try {
      const job = controller.runBlock(session.id, block.id);
      await vi.waitFor(() => expect(transport.executions()).toHaveLength(1));
      expect(transport.executions()[0].params).toMatchObject({ language: "sql", code: "SELECT 1 AS value", variable_name: "sql_result" });
      transport.finish(0); await job;
      expect(controller.session(session.id)?.blocks[0].status).toBe("succeeded");
    } finally { controller.dispose(); }
  });
});

describe("execution notification identity", () => {
  it("captures the executed block while focus and active tab change", async () => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), session = controller.session()!;
    const first = session.blocks[0], other = controller.addBlock(session.id, "python", "other=1");
    controller.setWorkspaceIdentity("profile-original");
    controller.updateBlock(session.id, first.id, {code:"SELECT 1",block_name:"Consulta",database_name:"block_database",connection_name:"block_connection"});
    const finished = vi.fn(); controller.onQueueFinished = finished;
    const job = controller.runBlock(session.id,first.id);
    await vi.waitFor(()=>expect(transport.executions()).toHaveLength(1));
    controller.focusBlock(session.id,other.id); const next=controller.createSession();
    controller.setWorkspaceIdentity("profile-next");
    transport.finish(0); await job;
    expect(finished).toHaveBeenCalledTimes(1);
    expect(finished.mock.calls[0][2]).toMatchObject({blockId:first.id,executionId:transport.executions()[0].params.execution_id,workspaceId:"profile-original",status:"succeeded",context:{block_name:"Consulta",database:"block_database",connection:"block_connection",rows:1,blocks:1}});
    expect((transport.executions()[0].params.notification as {context:object}).context).toMatchObject({workspace_id:"profile-original"});
    expect(controller.getSnapshot().activeId).toBe(next.id);
    expect(controller.session(session.id)?.focusedBlockId).toBe(other.id); controller.dispose();
  });
  it("emits one queue notification at the failing block with actual attempt count", async () => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), session = controller.session()!;
    const first=session.blocks[0],skip=controller.addBlock(session.id),failure=controller.addBlock(session.id),never=controller.addBlock(session.id);
    controller.updateBlock(session.id,first.id,{code:"SELECT 1"});controller.updateBlock(session.id,skip.id,{code:"SELECT skip",is_active:false});
    controller.updateBlock(session.id,failure.id,{code:"SELECT wrong",block_name:"Falha"});controller.updateBlock(session.id,never.id,{code:"SELECT never"});
    const finished=vi.fn();controller.onQueueFinished=finished;
    const job=controller.runAll(session.id);await vi.waitFor(()=>expect(transport.executions()).toHaveLength(1));transport.finish(0);
    await vi.waitFor(()=>expect(transport.executions()).toHaveLength(2));transport.finish(1,"failed");await job;
    expect(transport.executions().map(request=>(request.params.notification as {emit_notification:boolean}).emit_notification)).toEqual([false,false]);
    expect(finished.mock.calls[0][2]).toMatchObject({blockId:failure.id,status:"failed",context:{blocks:2,rows:0,error:"Syntax error",block_name:"Falha"}});
    expect(finished).toHaveBeenCalledTimes(1);controller.dispose();
  });
  it("explicitly carries the last table of this queue to a final Python block without reusing previous queues",async()=>{
    const transport=new FakeTransport(),controller=new WorkspaceController(transport),session=controller.session()!,first=session.blocks[0];
    controller.updateBlock(session.id,first.id,{code:"SELECT 1"});controller.addBlock(session.id,"python","print('done')");
    const job=controller.runAll(session.id);await vi.waitFor(()=>expect(transport.executions()).toHaveLength(1));transport.finish(0);
    await vi.waitFor(()=>expect(transport.executions()).toHaveLength(2));
    expect(transport.executions()[1].params.notification).toMatchObject({queue_result:{result_id:"result-0",rows:1}});
    transport.finish(1);await job;
    const next=controller.runBlock(session.id,first.id);await vi.waitFor(()=>expect(transport.executions()).toHaveLength(3));
    expect((transport.executions()[2].params.notification as {queue_result?:object}).queue_result).toBeUndefined();transport.finish(2);await next;controller.dispose();
  });
  it("retains rendered notification from the terminal event before a new execution", async () => {
    const transport=new FakeTransport(),controller=new WorkspaceController(transport),session=controller.session()!,block=session.blocks[0];
    controller.updateBlock(session.id,block.id,{code:"SELECT 1"});const finished=vi.fn();controller.onQueueFinished=finished;
    const job=controller.runBlock(session.id,block.id);await vi.waitFor(()=>expect(transport.executions()).toHaveLength(1));
    const request=transport.executions()[0],notification={enabled:true,sound:false,title:"Frozen",message:"old=10",success:true,suppressed:false,send_external:false,channels:{telegram:false,email:false}};
    transport.listener?.({event:"execution.finished",payload:{session_id:session.id,execution_id:String(request.params.execution_id),status:"succeeded",duration_ms:1,results:[],variables:[],notification}});await job;
    expect(finished.mock.calls[0][2].notification).toBe(notification);
    expect((request.params.notification as {context:object;emit_notification:boolean}).emit_notification).toBe(true);
    expect((request.params.notification as {context:object}).context).toMatchObject({block_id:block.id,blocks:1});controller.dispose();
  });
  it("distinguishes cancellation from an old unrelated error", async () => {
    const transport=new FakeTransport(),controller=new WorkspaceController(transport),session=controller.session()!,block=session.blocks[0];
    const old=controller.addBlock(session.id,"python","old=1");controller.updateBlock(session.id,old.id,{status:"failed",error:"old error"});controller.updateBlock(session.id,block.id,{code:"SELECT 1"});
    const finished=vi.fn();controller.onQueueFinished=finished;const job=controller.runBlock(session.id,block.id);
    await vi.waitFor(()=>expect(transport.executions()).toHaveLength(1));transport.finish(0,"cancelled");await job;
    expect(finished.mock.calls[0][2]).toMatchObject({blockId:block.id,status:"cancelled",context:{error:"Execução cancelada.",rows:0}});controller.dispose();
  });
  it("does not reuse a prior success notification when a queue is cancelled between blocks", async () => {
    const transport=new FakeTransport(),controller=new WorkspaceController(transport),session=controller.session()!,block=session.blocks[0];
    controller.updateBlock(session.id,block.id,{code:"SELECT 1"});controller.addBlock(session.id,"sql","SELECT 2");
    const finished=vi.fn();controller.onQueueFinished=finished;const job=controller.runAll(session.id);
    await vi.waitFor(()=>expect(transport.executions()).toHaveLength(1));
    const request=transport.executions()[0],notification={enabled:true,sound:false,title:"Success",message:"old",success:true,suppressed:true,send_external:false,channels:{telegram:false,email:false}};
    transport.listener?.({event:"execution.finished",payload:{session_id:session.id,execution_id:String(request.params.execution_id),status:"succeeded",duration_ms:1,results:[],variables:[],notification}});
    await controller.cancel(session.id);await job;
    expect(transport.executions()).toHaveLength(1);
    expect(finished.mock.calls[0][2]).toMatchObject({blockId:block.id,status:"cancelled",notification:undefined});controller.dispose();
  });
  it("reports startup failure without inventing a successful execution", async () => {
    const transport=new FakeTransport(),controller=new WorkspaceController(transport),session=controller.session()!,block=session.blocks[0];
    controller.updateBlock(session.id,block.id,{code:"SELECT 1"});transport.unavailable=true;
    const finished=vi.fn();controller.onQueueFinished=finished;
    await expect(controller.runBlock(session.id,block.id)).rejects.toThrow("indisponível");
    expect(finished.mock.calls[0][2]).toMatchObject({blockId:block.id,status:"failed",context:{blocks:0,error:"Runtime indisponível"}});controller.dispose();
  });
  it("never fails a completed execution because a notification observer throws", async () => {
    const transport=new FakeTransport(),controller=new WorkspaceController(transport),session=controller.session()!,block=session.blocks[0];
    controller.updateBlock(session.id,block.id,{code:"SELECT 1"});controller.onQueueFinished=()=>{throw new Error("notice failed");};
    const job=controller.runBlock(session.id,block.id);await vi.waitFor(()=>expect(transport.executions()).toHaveLength(1));transport.finish(0);
    await expect(job).resolves.toBeUndefined();expect(controller.session()?.blocks[0].status).toBe("succeeded");controller.dispose();
  });
  it("keeps delivery events from changing result state",()=>{
    const session=newSession();session.currentExecutionId="running";
    const event={event:"notifications.delivery_finished" as const,payload:{session_id:session.id,execution_id:"running",block_id:session.blocks[0].id,deliveries:{email:{status:"failed"}}}};
    expect(applyRuntimeEvent(session,event)).toBe(session);
  });
});

describe("Documentos .dpw", () => {
  const chartDocument = (active_index: unknown = 0) => ({blocks: [{language: "python", code: "df"}],
    result_view_state: {column_formats: {amount: {kind: "decimal", decimals: 2}}, future_view: {version: 7},
      charts: {active_index, future_charts: "preserved", configs: [
        {type: "bar", title: "Vendas", source_label: "sales", future_style: {enabled: true}},
        {type: "line", title: "Custos", source_label: "costs"},
        {type: "pie", title: "Regiões", source_label: "regions"},
      ]}},
  });
  it("restaura o índice Qt de gráfico sem aplicar o offset das abas de dados", () => {
    for (const index of [0, 1, 2]) {
      const session = decodeDocument(chartDocument(index));
      const charts = session.extras.charts as Array<{id: string; title: string}>;
      expect(session.extras.desktop_chart_id).toBe(charts[index].id);
      expect(charts[index].title).toBe(["Vendas", "Custos", "Regiões"][index]);
      expect((encodeDocument(session).result_view_state as ReturnType<typeof chartDocument>["result_view_state"]).charts.active_index).toBe(index);
    }
  });
  it("exporta a seleção moderna na lista Qt e preserva configurações e extensões", () => {
    const source = chartDocument(0), session = decodeDocument(source);
    const charts = session.extras.charts as Array<{id: string; title: string; variable_name: string; config: Record<string, unknown>}>;
    charts[2] = {...charts[2], title: "Regiões atualizadas", variable_name: "current_regions",
      config: {...charts[2].config, title: "Título anterior", source_label: "old_source", stacking: "grouped", source_mode: "selection", selection_view: {scope: {row_ranges: [[0, 2]]}}}};
    session.extras.desktop_chart_id = charts[2].id;
    const encoded = JSON.parse(JSON.stringify(encodeDocument(session)));
    expect(encoded.result_view_state).toMatchObject({column_formats: source.result_view_state.column_formats,
      future_view: {version: 7}, charts: {active_index: 2, future_charts: "preserved"}});
    expect(encoded.result_view_state.charts.configs[0]).toEqual(source.result_view_state.charts.configs[0]);
    expect(encoded.result_view_state.charts.configs[2]).toMatchObject({title: "Regiões atualizadas", source_label: "current_regions", stacking: "none", source_mode: "selection", selection_view: {scope: {row_ranges: [[0, 2]]}}});
    expect(charts[2].config.stacking).toBe("grouped");
    const reopened = decodeDocument(encoded);
    expect(reopened.extras.desktop_chart_id).toBe(charts[2].id);
    expect(reopened.extras.charts).toEqual(charts);
  });
  it("conserva Dados como seleção explícita ao reabrir JSON sem apagar o último índice Qt", () => {
    const session = decodeDocument(chartDocument(2));
    session.extras.desktop_chart_id = undefined;
    const encoded = JSON.parse(JSON.stringify(encodeDocument(session)));
    expect(encoded.desktop_chart_id).toBeNull();
    expect(encoded.result_view_state.charts.active_index).toBe(2);
    expect(decodeDocument(encoded).extras.desktop_chart_id).toBeNull();
    session.extras.desktop_chart_id = null;
    expect(decodeDocument(JSON.parse(JSON.stringify(encodeDocument(session)))).extras.desktop_chart_id).toBeNull();
  });
  it("não ressuscita gráfico legado quando o ID moderno está inválido ou pertence a outra sessão", () => {
    for (const desktop_chart_id of ["closed-chart", null, undefined]) {
      const session = decodeDocument({...chartDocument(1), desktop_chart_id});
      expect(session.extras.desktop_chart_id).toBeNull();
      expect(encodeDocument(session).desktop_chart_id).toBeNull();
    }
  });
  it("mantém IDs modernos e converte apenas a seleção do legado quando não existe seleção privada", () => {
    const session = decodeDocument(chartDocument("1"));
    const charts = session.extras.charts as Array<{id: string}>;
    const encoded = encodeDocument(session);
    delete encoded.desktop_chart_id;
    const reopened = decodeDocument(encoded);
    expect(reopened.extras.charts).toEqual(charts);
    expect(reopened.extras.desktop_chart_id).toBe(charts[1].id);
  });
  it("aceita gráficos vazios e ignora índices fora de faixa sem escolher outra aba", () => {
    for (const index of [-1, 3, 1.5, "bad"]) expect(decodeDocument(chartDocument(index)).extras.desktop_chart_id).toBeNull();
    const session = decodeDocument({blocks: [], result_view_state: {charts: {active_index: 8, configs: []}}});
    expect(session.extras.charts).toEqual([]);
    expect(session.extras.desktop_chart_id).toBeNull();
    expect(encodeDocument(session).result_view_state).toEqual({charts: {active_index: 0, configs: []}});
  });
  it("preserva configurações de blocos, parâmetros, notificações e charts ao salvar", () => {
    const source = { version: "1.0", blocks: [{ language: "sql", code: "SELECT @day", block_name: "sales", is_active: false,
      height: 240, connection_name: "Prod", connection_group: "Company", database_name: "reports", sql_parameters: [{ name: "day", value: "today" }] }],
      shared_parameters: [{ name: "day", value: "today" }], shared_parameters_enabled: false,
      notification_config: { enabled: true, title: "{{rows}}" }, result_view_state: { charts: { configs: [{ type: "bar" }] } } };
    const document = decodeDocument(source);
    const encoded = encodeDocument(document);
    expect(encoded.shared_parameters_enabled).toBe(false);
    expect(encoded.notification_config).toEqual(source.notification_config);
    expect(encoded.result_view_state).toEqual({charts: {...source.result_view_state.charts, active_index: 0}});
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
  it("protects the captured workspace during asynchronous switch/close while keeping runtime status available",()=>{
    const controller=new WorkspaceController(new FakeTransport()),session=controller.session()!,block=session.blocks[0];
    controller.setEditingLocked(true);
    controller.updateBlock(session.id,block.id,{code:"late edit"});controller.renameSession(session.id,"late title");controller.createSession();
    expect(controller.getSnapshot().sessions).toHaveLength(1);expect(controller.session()!.blocks[0].code).toBe("");expect(controller.session()!.title).toBe(session.title);
    controller.message("flush error");expect(controller.getSnapshot().message).toBe("flush error");
    controller.restoreSnapshot({documents:[{title:"Restored",sessionId:"restored",document:{blocks:[{language:"python",code:"saved",block_name:"",is_active:true}]}}]});
    expect(controller.session()!.title).toBe("Restored");
    controller.setEditingLocked(false);controller.updateBlock("restored",controller.session()!.blocks[0].id,{code:"new edit"});expect(controller.session()!.blocks[0].code).toBe("new edit");
  });
  it("download direto usa a seleção e não persiste o destino como parte do bloco",async()=>{
    const transport=new FakeTransport(),controller=new WorkspaceController(transport),session=controller.session()!,block=session.blocks[0];
    controller.updateBlock(session.id,block.id,{code:"SELECT 1; SELECT 2;",connection_id:"other",sql_parameters:[{name:"id",value:42}]});
    const job=controller.runToFile(session.id,block.id,{path:"C:/temp/export.csv",format:"csv"},"SELECT 2;");
    await vi.waitFor(()=>expect(transport.executions()).toHaveLength(1));
    expect(transport.executions()[0].params).toMatchObject({code:"SELECT 2;",connection_id:"other",export:{path:"C:/temp/export.csv",format:"csv"}});
    transport.finish(0);expect(await job).toMatchObject({status:"succeeded"});
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
  it.each([undefined, "block_database"])("does not send another connection's defaults during execution (%s)", async database => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), session = controller.session()!, block = session.blocks[0];
    controller.patchSession(session.id, current => ({...current,savedConnectionId:"primary",database:"primary_database",schema:"primary_schema"}));
    controller.updateBlock(session.id, block.id, {code:"SELECT 1",connection_id:"other",database_name:database});
    const job = controller.runBlock(session.id, block.id);
    await vi.waitFor(() => expect(transport.executions()).toHaveLength(1));
    expect(transport.executions()[0].params).toMatchObject({connection_id:"other",database,schema:undefined});
    transport.finish(0); await job; controller.dispose();
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
  it.each([
    ["sql", false, false], ["sql", false, true], ["sql", true, false], ["sql", true, true],
    ["python", false, false], ["python", false, true], ["python", true, false], ["python", true, true],
  ] as const)("executa %s com avanço=%s e seleção=%s pelo mesmo comando", async (language, advance, hasSelection) => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), session = controller.session()!, block = session.blocks[0];
    const snippet = language === "sql" ? "SELECT 'selecionado';\r\n" : "if True:\r\n    selected = 'selecionado'\r\n";
    const full = language === "sql" ? `DELETE FROM guard;\r\n${snippet}DROP TABLE guard;` : `before = True\r\n${snippet}after = True`;
    controller.updateBlock(session.id, block.id, { language, code: full });
    const next = controller.addBlock(session.id, language); controller.focusBlock(session.id, block.id);
    models.set(block.id, { model: { isDisposed: () => false, getValueInRange: () => snippet }, editor: { getSelection: () => ({ isEmpty: () => !hasSelection }) } } as never);
    try {
      const job = controller.runBlock(session.id, block.id, undefined, advance);
      // A toolbar blur/focus change after starting cannot replace the captured code.
      models.delete(block.id);
      await vi.waitFor(() => expect(transport.executions()).toHaveLength(1));
      expect(transport.executions()[0].params).toMatchObject({ language, code: hasSelection ? snippet : full });
      transport.finish(0); await job;
      expect(controller.session(session.id)?.blocks[0].code).toBe(full);
      expect(controller.session(session.id)?.focusedBlockId).toBe(advance ? next.id : block.id);
    } finally { models.delete(block.id); controller.dispose(); }
  });
  it.each(["sql", "python"] as const)("não executa o bloco %s quando a seleção contém apenas espaços", async language => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), session = controller.session()!, block = session.blocks[0];
    controller.updateBlock(session.id, block.id, { language, code: language === "sql" ? "DELETE FROM guard" : "guard = True" });
    models.set(block.id, { model: { isDisposed: () => false, getValueInRange: () => " \r\n\t " }, editor: { getSelection: () => ({ isEmpty: () => false }) } } as never);
    try { await controller.runBlock(session.id, block.id); expect(transport.executions()).toHaveLength(0); }
    finally { models.delete(block.id); controller.dispose(); }
  });
  it.each(["sql", "python"] as const)("executa a seleção %s restaurada antes de montar o editor", async language => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), session = controller.session()!, block = session.blocks[0];
    const snippet = language === "sql" ? "SELECT 'selected';" : "selected = 1";
    controller.updateBlock(session.id, block.id, { language, code: `outside before\r\n${snippet}\r\noutside after` });
    restoreEditorViewState(block.id, { cursorState: [{ selectionStart: { lineNumber: 2, column: 1 }, position: { lineNumber: 2, column: snippet.length + 1 } }], viewState: {}, contributionsState: {} });
    try {
      const job = controller.runBlock(session.id, block.id);
      await vi.waitFor(() => expect(transport.executions()).toHaveLength(1));
      expect(transport.executions()[0].params.code).toBe(snippet); transport.finish(0); await job;
      expect(takeRestoredEditorViewState(block.id)).not.toBeNull();
    } finally { takeRestoredEditorViewState(block.id); controller.dispose(); }
  });
  it.each(["sql", "python"] as const)("não amplia a seleção %s após erro", async language => {
    const transport = new FakeTransport(), controller = new WorkspaceController(transport), session = controller.session()!, block = session.blocks[0];
    controller.updateBlock(session.id, block.id, { language, code: "outside before\nselected error\noutside after" });
    models.set(block.id, { model: { isDisposed: () => false, getValueInRange: () => "selected error" }, editor: { getSelection: () => ({ isEmpty: () => false }) } } as never);
    try {
      const job = controller.runBlock(session.id, block.id);
      await vi.waitFor(() => expect(transport.executions()).toHaveLength(1)); transport.finish(0, "failed"); await job;
      expect(transport.executions()).toHaveLength(1); expect(transport.executions()[0].params.code).toBe("selected error");
      expect(controller.session(session.id)?.blocks[0].status).toBe("failed");
    } finally { models.delete(block.id); controller.dispose(); }
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


describe("block database selection",()=>{
  it("updates the first block explicitly without changing sibling connection defaults",()=>{
    const controller=new WorkspaceController(new FakeTransport()),session=controller.session()!,first=session.blocks[0],second=controller.addBlock(session.id,"sql","SELECT 1");
    controller.patchSession(session.id,s=>({...s,savedConnectionId:"a",database:"original",schema:"private"}));
    controller.updateBlock(session.id,first.id,{database_name:"older",schema:"older_schema"});
    controller.setContext(session.id,{database:"chosen"},first.id);
    expect(controller.session()!.blocks[0]).toMatchObject({database_name:"chosen",schema:undefined});
    expect(controller.session()!.database).toBe("original");expect(controller.session()!.schema).toBe("private");
    expect(controller.session()!.blocks.find(block=>block.id===second.id)?.database_name).toBeUndefined();
    controller.setContext(session.id,{database:"chosen",schema:"public"},first.id);
    expect(controller.session()!.blocks[0].schema).toBe("public");controller.dispose();
  });
});
