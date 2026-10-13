import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { ObjectExplorer } from "../src/ObjectExplorer";
import { runtime } from "../src/runtime";
import { quoteIdentifier, type ExplorerDetails, type ExplorerNode } from "../src/explorer";
import "../src/styles.css";

const nodes: ExplorerNode[] = [
  { id: "orders", name: "Orders", qualified_name: "public.Orders", kind: "table", database: "warehouse", schema: "public", has_children: true },
  { id: "view", name: "ActiveOrders", qualified_name: "public.ActiveOrders", kind: "view", database: "warehouse", schema: "public", has_children: false },
  { id: "proc", name: "RefreshOrders", qualified_name: "public.RefreshOrders", kind: "procedure", database: "warehouse", schema: "public", has_children: false },
  { id: "func", name: "OrderTotal", qualified_name: "public.OrderTotal", kind: "function", database: "warehouse", schema: "public", has_children: false },
  { id: "schema", name: "analytics", kind: "schema", database: "warehouse", has_children: true },
  { id: "database", name: "warehouse", kind: "database", has_children: true },
  { id: "catalog", name: "catalog", kind: "catalog", has_children: true },
  { id: "category", name: "Tables", kind: "category", has_children: true },
];
const columns: ExplorerNode[] = [{ id: "order-id", name: "Order ID", kind: "column", database: "warehouse", schema: "public", data_type: "BIGINT", has_children: false }];
const calls: Array<{ method: string; params: Record<string, unknown> }> = [], inserts: Array<{ code: string; language?: string; newBlock?: boolean }> = [], errors: string[] = [], contexts: unknown[] = [], copied: string[] = [];
let dialect = "sqlserver", fail: string | undefined, missing: string | undefined, held: string | undefined;
let resolveHeld: ((value: unknown) => void) | undefined;
const details = (): ExplorerDetails => ({ columns: [{ name: "Order ID", data_type: "BIGINT" }, { name: "Total", data_type: "DECIMAL" }], indexes: [{ name: "PK_Orders", columns: "Order ID" }], definition: "CREATE TABLE Orders (id BIGINT);" });
runtime.request = async <T,>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
  calls.push({ method, params });
  if (fail === method) { fail = undefined; throw new Error("Permissão de metadados negada"); }
  if (held === method) { held = undefined; return await new Promise<T>(resolve => { resolveHeld = value => resolve(value as T); }); }
  if (method === "explorer.list") return { nodes: params.node ? (params.node as ExplorerNode).id === "orders" ? columns : [] : nodes } as T;
  if (method === "explorer.details") { const value = details(); if (missing) { if (missing === "columns") value.columns = []; else value.definition = ""; missing = undefined; } return value as T; }
  if (method === "explorer.query") return { code: `${dialect === "sqlserver" ? "SELECT TOP (1000) *" : "SELECT *"}\nFROM ${quoteIdentifier(`public.${params.name}`, dialect)}${dialect === "sqlserver" ? ";" : "\nLIMIT 1000;"}` } as T;
  if (method === "explorer.use_database") return {} as T;
  throw new Error(`Unexpected explorer fixture request: ${method}`);
};
Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (value: string) => { copied.push(value); } } });

function Fixture() {
  const [scope, setScope] = useState({ dbType: "sqlserver", sessionId: "session", blockId: "block" }), [disabled, setDisabled] = useState(false), [useCallback, setUseCallback] = useState(true);
  Object.assign(window, { __EXPLORER_TEST__: { calls, inserts, errors, contexts, copied,
    setDialect: (dbType: string) => { dialect = dbType; setScope(prior => ({ ...prior, dbType })); },
    changeBlock: () => setScope(prior => ({ ...prior, blockId: prior.blockId === "block" ? "other-block" : "block" })),
    setDisabled, setUseCallback, failNext: (method: string) => { fail = method; }, missingNext: (part: string) => { missing = part; },
    holdNext: (method: string) => { held = method; }, release: (value: unknown) => { const resolve = resolveHeld; resolveHeld = undefined; resolve?.(value); },
    get pending() { return Boolean(resolveHeld); },
  } });
  return <><button id="outside">Outside</button><div style={{ height: "calc(100vh - 55px)", width: "min(360px, 100vw)" }}>
    <ObjectExplorer {...scope} connectionId={`connection-${scope.dbType}`} database="warehouse" schema="public" scopeInherited={false} disabled={disabled}
      onInsert={(code, language, newBlock) => inserts.push({ code, language, newBlock })} onError={message => errors.push(message)}
      onContextChange={useCallback ? context => { contexts.push(context); } : undefined} />
  </div></>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
