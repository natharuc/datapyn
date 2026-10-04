import { runtime, type RuntimeTransport } from "./runtime";
import type { ExplorerContext, ExplorerNode, ExplorerResult } from "./explorer";

export type ScopeField = "database" | "schema";
export interface BlockScope extends ExplorerContext {
  session_id: string;
  connection_id?: string;
  db_type?: string;
  revision?: number;
}
export interface ScopeOption { name: string; search: string }
export interface ScopeOptions {
  options: ScopeOption[];
  context?: ExplorerContext & { db_type?: string };
}

export const scopeSearchText = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();
export const hasSchemaScope = (dbType?: string) => ["postgres", "postgresql", "databricks", "sqlserver", "mssql"].includes(dbType ?? "");
const nameOrder = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

export function scopeOptionList(nodes: ExplorerNode[], field: ScopeField): ScopeOption[] {
  const kinds = field === "database" ? new Set(["database", "catalog"]) : new Set(["schema"]);
  const names = new Set<string>();
  for (const node of nodes) if (kinds.has(node.kind) && node.name) names.add(node.name);
  return [...names].sort(nameOrder.compare)
    .map(name => ({ name, search: scopeSearchText(name) }));
}

/** Search runs over loaded metadata only; typing never issues a database request. */
export function filterScopeOptions(options: ScopeOption[], query: string): ScopeOption[] {
  const terms = scopeSearchText(query.trim()).split(/\s+/).filter(Boolean);
  return terms.length ? options.filter(option => terms.every(term => option.search.includes(term))) : options;
}

export function scopeOptionIndex(length: number, selected: number, key: string): number {
  if (!length) return -1;
  if (key === "Home") return 0;
  if (key === "End") return length - 1;
  if (key === "ArrowUp") return selected < 0 ? length - 1 : Math.max(0, selected - 1);
  return Math.min(length - 1, selected + 1);
}

export function scopeListWindow(length: number, scroll: number, height: number, rowHeight = 28, overscan = 3) {
  const first = Math.max(0, Math.floor(Math.max(0, scroll) / rowHeight) - overscan);
  return { first: Math.min(length, first), end: Math.min(length, Math.ceil((Math.max(0, scroll) + Math.max(0, height)) / rowHeight) + overscan) };
}

/** Shared across blocks, bounded, deduplicated, and isolated by connection and database. */
export class ScopeOptionsClient {
  private cache = new Map<string, { value: ScopeOptions; expires: number }>();
  private pending = new Map<string, Promise<ScopeOptions>>();
  private revisions = new Map<string, number>();
  private epoch = 0;
  constructor(private transport: RuntimeTransport = runtime, private now: () => number = Date.now,
    private ttl = 120_000, private maximum = 64) {}

  clear() { ++this.epoch; this.cache.clear(); this.pending.clear(); this.revisions.clear(); }

  async list(scope: BlockScope, field: ScopeField, refresh = false): Promise<ScopeOptions> {
    const key = JSON.stringify([scope.session_id, scope.connection_id ?? "", scope.db_type ?? "", scope.database ?? "", scope.schema ?? "", scope.revision ?? 0, field]);
    const cached = this.cache.get(key);
    if (!refresh && cached && cached.expires > this.now()) {
      this.cache.delete(key); this.cache.set(key, cached); return cached.value;
    }
    if (!refresh && this.pending.has(key)) return this.pending.get(key)!;
    const epoch = this.epoch, generation = (this.revisions.get(key) ?? 0) + 1;
    this.revisions.set(key, generation);
    // A database node resolves its own schema list. Do not send the old schema
    // when selecting a different database (especially for PostgreSQL catalogs).
    const node = field === "schema" ? {
      id: `scope:${scope.database ?? ""}`, kind: "database",
      name: scope.database ?? "", database: scope.database, has_children: true,
    } : undefined;
    const params = {
      session_id: scope.session_id, connection_id: scope.connection_id,
      database: scope.database, ...(field === "database" ? { schema: scope.schema } : {}), node, refresh,
    };
    const request = this.transport.request<ExplorerResult>("explorer.list", params).then(result => {
      const value = { options: scopeOptionList(result.nodes ?? [], field), context: result.context };
      if (this.epoch === epoch && this.revisions.get(key) === generation) {
        this.cache.delete(key); this.cache.set(key, { value, expires: this.now() + this.ttl });
        while (this.cache.size > this.maximum) {
          const oldest = this.cache.keys().next().value!;
          this.cache.delete(oldest);
          if (!this.pending.has(oldest)) this.revisions.delete(oldest);
        }
      }
      return value;
    }).finally(() => {
      if (this.epoch === epoch && this.revisions.get(key) === generation) {
        this.pending.delete(key);
        if (!this.cache.has(key)) this.revisions.delete(key);
      }
    });
    this.pending.set(key, request);
    return request;
  }
}

export const blockScopeOptions = new ScopeOptionsClient();
