import React, { useState, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { SettingsDialog } from "../src/SettingsDialog";
import { DataActions } from "../src/DataActions";
import { VariableInspector } from "../src/VariableInspector";
import { runtime, type RuntimeEvent, type ResultRef } from "../src/runtime";
import { DEFAULT_SHORTCUTS } from "../src/shortcuts";
import { loadPreferences, savePreferences } from "../src/preferences";
import { readTransactionSettings, saveTransactionSettings } from "../src/transactionPreferences";
import { setLocale, useLocale } from "../src/i18n";
import "../src/styles.css";

// The isolated Vite test plugin exposes the actual production BlockCard; it does not mount App startup.
const calls: Array<{ method: string; params: Record<string, unknown> }> = [], listeners = new Set<(event: RuntimeEvent) => void>();
const frame: ResultRef = { result_id: "frame", variable_name: "df", columns: [{ name: "id", dtype: "int64" }], row_count: 2 };
runtime.subscribe = async listener => { listeners.add(listener); return () => { listeners.delete(listener); }; };
runtime.request = async <T,>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
  calls.push({ method, params });
  if (method === "transactions.settings.get") return { automatic_transactions: localStorage.getItem("transaction-fixture-global") !== "false" } as T;
  if (method === "transactions.settings.set") { localStorage.setItem("transaction-fixture-global", String(params.automatic_transactions)); return { automatic_transactions: params.automatic_transactions } as T; }
  if (method === "system.info") return { protocol_version: 1, python_version: "fixture", capabilities: [] } as T;
  if (method === "session.create") return { session_id: params.session_id, status: "created", ready: true } as T;
  if (method === "connections.list") return { version: 2, groups: [], connections: [], ssh_tunnels: [] } as T;
  if (method === "execution.run") {
    setTimeout(() => { const event: RuntimeEvent = { event: "execution.finished", payload: { session_id: String(params.session_id), execution_id: String(params.execution_id), block_id: String(params.block_id), status: "succeeded", duration_ms: 1, results: [], variables: [] } }; listeners.forEach(listener => listener(event)); }, 0);
    return { status: "queued", execution_id: params.execution_id } as T;
  }
  if (method === "result.export_table") return { row_count: 2 } as T;
  if (method === "variable.inspect") return { name: "df", type: "DataFrame", preview: "2 rows", result: frame, offset: 0, total_entries: 0, entries: [] } as T;
  if (method === "result.page") return { columns: frame.columns, rows: [[1], [2]], total_rows: 2, offset: 0 } as T;
  throw new Error(`Unexpected transaction fixture call: ${method}`);
};
const app = await import("../src/App") as unknown as { workspace: import("../src/workspace").WorkspaceController; BlockCard: React.ComponentType<Record<string, unknown>> };
const { workspace, BlockCard } = app;
workspace.patchSession(workspace.session()!.id, session => ({ ...session, blocks: session.blocks.map(block => ({ ...block, cell_type: "code", collapsed: true, code: "SELECT 1" })), connection: { db_type: "sqlserver", host: "fixture.invalid", port: 1433, username: "", database: "FixtureDB" }, database: "FixtureDB", schema: "dbo" }));
const globalSettings = await readTransactionSettings(runtime);
const query = new URLSearchParams(location.search), locale = query.get("locale") === "en-US" ? "en-US" : "pt-BR";
setLocale(locale); document.documentElement.dataset.theme = query.get("theme") === "light" ? "light" : "dark";
const noop = () => {}, emptyContext = () => ({ globalImports: "", preamble: "" });

function Fixture() {
  useLocale();
  const state = useSyncExternalStore(workspace.subscribe, workspace.getSnapshot), session = workspace.session()!, block = session.blocks[0];
  const [preferences, setPreferences] = useState({ ...loadPreferences(), locale, theme: document.documentElement.dataset.theme as "light" | "dark", automaticTransactions: globalSettings.automatic_transactions }), [settingsOpen, setSettingsOpen] = useState(false), [error, setError] = useState("");
  workspace.setAutomaticTransactions(preferences.automaticTransactions);
  const transactionScope = { block_id: block.id, automatic_transactions: preferences.automaticTransactions && block.disable_automatic_transactions !== true, disable_automatic_transactions: block.disable_automatic_transactions === true, scope_inherited: true };
  const exportProps = { transactionScope, connectionType: "sqlserver", currentConnectionId: "warehouse", currentDatabase: "FixtureDB", currentSchema: "dbo", availableConnections: [{ id: "warehouse", name: "Fixture", db_type: "sqlserver", database: "FixtureDB" }] };
  Object.assign(window, { __TRANSACTION_TEST__: { calls, snapshot: () => workspace.nativeSnapshot(), document: () => workspace.nativeSnapshot().documents[0].document, block: () => workspace.session()!.blocks[0], updatePreferences: () => setPreferences(prior => ({ ...prior, automaticTransactions: true, notifications: false })), setBusy: (busy: boolean) => workspace.patchSession(session.id, prior => ({ ...prior, busy })), persist: () => { workspace.persist(); savePreferences(preferences); }, global: () => preferences.automaticTransactions } });
  return <main><button id="settings" onClick={() => setSettingsOpen(true)}>Settings</button><span role="status">{error}</span>
    <BlockCard block={block} index={0} count={session.blocks.length} session={session} disabled={Boolean(session.busy)} locked={false} onRun={() => { void workspace.runBlock(session.id, block.id).catch(failure => setError(String(failure))); }} preferences={preferences} onPickConnection={noop} onDownload={noop} onFontSizeChange={noop} forceMount={false} onEditorReady={noop} diagnosticsReady={false} diagnosticRevision="" diagnosticContext={emptyContext} scopeMetadata={noop} onScopeChange={async () => {}} scopeRefresh={0} scopeReady={false} />
    <div id="result-actions"><DataActions {...exportProps} sessionId={session.id} result={frame} onImported={noop} onChart={noop} onMessage={noop} hideImport hideChart /></div>
    <VariableInspector {...exportProps} sessionId={session.id} variables={[{ name: "df", type: "DataFrame", preview: "2 rows" }]} onVariables={noop} onResult={noop} />
    {settingsOpen && <SettingsDialog preferences={preferences} shortcuts={DEFAULT_SHORTCUTS} initialTab="general" onClose={() => setSettingsOpen(false)} onSave={async value => { await saveTransactionSettings(runtime, value.automaticTransactions); setPreferences(value); savePreferences(value); workspace.persist(); setSettingsOpen(false); }} />}
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
