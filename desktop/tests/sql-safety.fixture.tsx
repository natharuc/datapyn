import React, {useState, useSyncExternalStore} from "react";
import {createRoot} from "react-dom/client";
import {WorkspaceController} from "../src/workspace";
import {SqlSafetyConfirmation} from "../src/SqlSafetyConfirmation";
import {sqlConfirmations} from "../src/sqlConfirmation";
import {DataActions} from "../src/DataActions";
import {SettingsDialog} from "../src/SettingsDialog";
import {applySqlSafetyPreferences} from "../src/safetySettings";
import {loadPreferences, savePreferences} from "../src/preferences";
import {DEFAULT_SHORTCUTS} from "../src/shortcuts";
import {runtime, type RuntimeEvent, type RuntimeTransport, type ResultRef} from "../src/runtime";
import {setLocale, translate} from "../src/i18n";
import {featureTranslate} from "../src/featureTranslations";
import "../src/styles.css";

// This fixture mounts real execution, confirmation, settings and export components
// against one local fake transport. No application startup or real database runs.
const query = new URLSearchParams(location.search);
const locale = query.get("locale") === "en-US" ? "en-US" : "pt-BR";
const theme = query.get("theme") === "light" ? "light" : "dark";
setLocale(locale); document.documentElement.dataset.theme = theme;
const long = query.has("long");
const names = {
  connection: long ? `Grupo / Subgrupo / ${"VeryLongConnectionName".repeat(9)}` : "Fixture / Warehouse",
  database: long ? `Warehouse_${"VeryLongDatabaseName".repeat(10)}` : "FixtureDB",
  schema: long ? `schema_${"very_long_schema_name".repeat(7)}` : "dbo",
  table: long ? `orders_${"very_long_target_name".repeat(11)}` : "orders",
};
const calls: Array<{method: string; params: Record<string, unknown>}> = [];
const listeners = new Set<(event: RuntimeEvent) => void>();
const tickets = new Map<string, string>(), violations: string[] = [], failures: string[] = [];
let safetyEnabled = true, sequence = 0;
const payload = (params: Record<string, unknown>) => Object.fromEntries(Object.entries(params).filter(([key]) => !["method", "confirmation_token"].includes(key)));
const signature = (params: Record<string, unknown>) => JSON.stringify(payload(params));
const protectedCall = (method: string, params: Record<string, unknown>) => method === "result.export_table" ? params.if_exists === "replace" : /\b(?:DELETE|UPDATE|TRUNCATE|DROP|ALTER|MERGE)\b/i.test(String(params.code));
const transport: RuntimeTransport = {
  subscribe: async listener => {listeners.add(listener); return () => {listeners.delete(listener);};},
  request: async <T,>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
    calls.push({method, params: structuredClone(params)});
    if (method === "system.info") return {protocol_version: 1, python_version: "fixture", capabilities: []} as T;
    if (method === "session.create") return {session_id: params.session_id, status: "created", ready: true} as T;
    if (method === "sql.safety.settings.get") return {confirm_destructive_sql: safetyEnabled} as T;
    if (method === "sql.safety.settings.set") {safetyEnabled = params.confirm_destructive_sql === true; return {confirm_destructive_sql: safetyEnabled} as T;}
    if (method === "execution.review") {
      const operation = params.method === "result.export_table" ? "REPLACE TABLE" : /\b(DELETE|UPDATE|TRUNCATE|DROP|ALTER|MERGE)\b/i.exec(String(params.code))?.[1]?.toUpperCase();
      if (!safetyEnabled || !operation) return {confirmation_required: false, risks: []} as T;
      const token = `fixture-ticket-${++sequence}`;
      tickets.set(token, signature(params));
      return {confirmation_required: true, confirmation_token: token,
        ...(params.method === "result.export_table" ? {connection_name: "Resolved export warehouse"} : {}),
        risks: [{statement: 1, operation, target: String(params.table ?? names.table), unfiltered: true, has_where: false, preview: String(params.code ?? `REPLACE TABLE ${params.database}.${params.schema}.${params.table}`).slice(0, 500)}]} as T;
    }
    if (method === "execution.run" || method === "result.export_table") {
      if (safetyEnabled && protectedCall(method, params)) {
        const token = String(params.confirmation_token ?? ""), expected = tickets.get(token);
        tickets.delete(token);
        if (!expected || expected !== signature(params)) {violations.push(`Invalid approval: ${method}`); throw new Error("Missing or changed approval in fixture");}
      }
      if (method === "result.export_table") return {row_count: 2} as T;
      setTimeout(() => {
        const event: RuntimeEvent = {event: "execution.finished", payload: {session_id: String(params.session_id), execution_id: String(params.execution_id), status: "succeeded", duration_ms: 1, results: [], variables: []}};
        listeners.forEach(listener => listener(event));
      }, 0);
      return {status: "queued", execution_id: params.execution_id} as T;
    }
    throw new Error(`Unexpected SQL safety fixture call: ${method}`);
  },
};
runtime.request = transport.request; runtime.subscribe = transport.subscribe;
const workspace = new WorkspaceController(transport, undefined, {nativePersistence: true});
const first = workspace.session()!, second = workspace.createSession({inheritConnection: false});
const sessions = {a: first.id, b: second.id};
for (const [key, id] of Object.entries(sessions)) {
  workspace.patchSession(id, session => ({...session, title: `Analysis ${key.toUpperCase()}`, savedConnectionId: `fixture-${key}`, database: names.database, schema: names.schema,
    extras: {connection_name: `${names.connection} ${key.toUpperCase()}`, shared_parameters: [{name: "id", value: "original"}]},
    blocks: session.blocks.map(block => ({...block, block_name: `orders_${key}`, code: `DELETE FROM ${names.schema}.${names.table};`, sql_parameters: [{name: "limit", value: "10"}]}))}));
}
workspace.activate(first.id);
workspace.onConfirmSqlExecution = sqlConfirmations.request;
const frame: ResultRef = {result_id: "fixture-frame", variable_name: "orders_export", columns: [{name: "id", dtype: "int64"}], row_count: 2};
let selection: string | undefined;
const run = (key: keyof typeof sessions) => {
  const session = workspace.session(sessions[key])!;
  return workspace.runBlock(session.id, session.blocks[0].id, selection).catch(error => {failures.push(String(error));});
};

function Fixture() {
  const state = useSyncExternalStore(workspace.subscribe, workspace.getSnapshot);
  const [settings, setSettings] = useState(false), [message, setMessage] = useState("");
  const [preferences, setPreferences] = useState({...loadPreferences(), locale, theme, confirmDestructiveSql: true});
  Object.assign(window, {__SQL_SAFETY_TEST__: {calls, violations, failures, names, sessions,
    translate: (text: string) => ["Para tabela", "Exportar para tabela", "Exportar", "Tabela", "Se a tabela existir"].includes(text) ? featureTranslate(text) : translate(text),
    snapshot: () => workspace.getSnapshot(),
    run, selection: (code?: string) => {selection = code;},
    mutate: (key: keyof typeof sessions) => {
      const id = sessions[key], session = workspace.session(id)!;
      workspace.patchSession(id, current => ({...current, database: "DifferentDB", schema: "other", extras: {...current.extras, shared_parameters: [{name: "id", value: "changed"}]}}));
      workspace.updateBlock(id, session.blocks[0].id, {code: "DROP TABLE different;", sql_parameters: [{name: "limit", value: "999"}]});
    },
    cancel: (key: keyof typeof sessions) => workspace.cancel(sessions[key]),
    safety: () => safetyEnabled,
  }});
  return <main style={{padding: 20}}>
    <style>{`body{min-width:0!important;min-height:0!important}#root{overflow:auto!important}main>section{border:1px solid var(--border);padding:12px;margin:12px 0}textarea{width:100%;height:80px}main h1{font-size:16px}`}</style>
    <h1>DataPyn SQL safety regression fixture</h1>
    <button id="settings" onClick={() => setSettings(true)}>Settings</button>
    <button id="run-both" onClick={() => {void run("a");void run("b");}}>Run both analyses</button>
    {state.sessions.map(session => <section key={session.id}>
      <strong>{session.title}</strong><span role="status">{session.blocks[0].status}</span>
      <textarea aria-label={`Code ${session.id === sessions.a ? "A" : "B"}`} value={session.blocks[0].code} onChange={event => workspace.updateBlock(session.id, session.blocks[0].id, {code: event.target.value})}/>
      <button id={session.id === sessions.a ? "run-a" : "run-b"} disabled={session.busy} onClick={() => {void run(session.id === sessions.a ? "a" : "b");}}>Run {session.id === sessions.a ? "A" : "B"}</button>
    </section>)}
    <div id="result-actions"><DataActions sessionId={sessions.a} result={frame} connectionType="sqlserver" currentConnectionId="fixture-a" currentDatabase={names.database} currentSchema={names.schema}
      availableConnections={[{id: "fixture-a", name: names.connection, db_type: "sqlserver", database: names.database}]} transactionScope={{block_id: first.blocks[0].id, automatic_transactions: true, disable_automatic_transactions: false, scope_inherited: true}}
      onImported={() => {}} onChart={() => {}} onMessage={setMessage} hideImport hideChart/></div>
    <output>{message}</output>
    {settings && <SettingsDialog preferences={preferences} shortcuts={DEFAULT_SHORTCUTS} initialTab="general" onClose={() => setSettings(false)} onSave={async (next, _shortcuts, changed) => {
      const applied = await applySqlSafetyPreferences(transport, next, changed?.has("confirmDestructiveSql") === true);
      savePreferences(applied); setPreferences(applied); setSettings(false);
    }}/>}
    <SqlSafetyConfirmation/>
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture/>);
