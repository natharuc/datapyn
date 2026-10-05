import { runtime, type RuntimeEvent, type RuntimeTransport } from "./runtime";
import { sqlStringEscapesBackslash } from "./sqlCompletionScope";

export interface PreparationScope {
  sessionId: string;
  blockId?: string;
  scopeInherited?: boolean;
  connectionId?: string;
  database?: string;
  schema?: string;
  /** Used only to distinguish comments and escaped strings in the metadata key. */
  dbType?: string;
}
export interface PreparationResult { status: "queued" | "ready"; context_version: number }
interface PreparationEntry {
  scope: PreparationScope;
  promise: Promise<PreparationResult>;
}
interface MetadataToken { value: string; quoted?: boolean; symbol?: boolean; depth: number }
const WORD = /[\p{L}\p{N}_@$#]/u;
const RELATIONS = new Set(["FROM", "JOIN", "INTO", "UPDATE", "TABLE"]);
const ROUTINES = new Set(["EXEC", "EXECUTE", "CALL"]);
const FROM_END = new Set(["WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET", "UNION", "INTERSECT", "EXCEPT", "QUALIFY", "WINDOW", "RETURNING", "SET", "VALUES"]);

/** Only relations and qualification prefixes matter; editing expressions does not reload metadata. */
export function preparationCodeKey(code: string, dbType?: string): string {
  const tokens: MetadataToken[] = [];
  let index = 0, depth = 0;
  while (index < code.length) {
    const char = code[index], start = index;
    if (/\s/.test(char)) { index++; continue; }
    if (code.startsWith("--", index) || char === "#" && ["mysql", "mariadb"].includes(dbType ?? "")) {
      const end = code.indexOf("\n", index); index = end < 0 ? code.length : end; continue;
    }
    if (code.startsWith("/*", index)) {
      index += 2; let depth = 1;
      while (index < code.length && depth) {
        if (code.startsWith("/*", index)) { depth++; index += 2; }
        else if (code.startsWith("*/", index)) { depth--; index += 2; }
        else index++;
      }
      continue;
    }
    const dollar = char === "$" && [undefined, "postgres", "postgresql"].includes(dbType)
      ? code.slice(index, index + 100).match(/^\$(?:[A-Za-z_]\w*)?\$/)?.[0] : undefined;
    if (dollar) {
      const end = code.indexOf(dollar, index + dollar.length);
      index = end < 0 ? code.length : end + dollar.length; continue;
    }
    if (["'", '"', "`", "["].includes(char)) {
      const closing = char === "[" ? "]" : char;
      const escapes = char === "'" && sqlStringEscapesBackslash(code, index, dbType);
      let value = ""; index++;
      while (index < code.length) {
        if (code[index] === closing) {
          index++;
          if (code[index] === closing) { value += closing; index++; continue; }
          break;
        }
        if (escapes && code[index] === "\\") { index += 2; continue; }
        value += code[index++];
      }
      if (char !== "'") tokens.push({ value, quoted: true, depth });
      continue;
    }
    if (WORD.test(char)) {
      do { index++; } while (index < code.length && WORD.test(code[index]));
      tokens.push({ value: code.slice(start, index), depth }); continue;
    }
    if (char === ")") depth = Math.max(0, depth - 1);
    tokens.push({ value: char, symbol: true, depth }); index++;
    if (char === "(") depth++;
  }
  const normalized = (token: MetadataToken) => token.quoted ? token.value : token.value.toLocaleLowerCase();
  function path(start: number) {
    const parts: string[] = []; let next = start, trailing = false;
    if (!tokens[next] || tokens[next].symbol) return { parts, next, trailing };
    parts.push(normalized(tokens[next++]));
    while (tokens[next]?.value === "." && tokens[next].symbol) {
      next++; trailing = true;
      if (tokens[next]?.value === "." && tokens[next].symbol) { parts.push("dbo"); next++; }
      if (!tokens[next] || tokens[next].symbol) break;
      parts.push(normalized(tokens[next++])); trailing = false;
    }
    return { parts, next, trailing };
  }
  const references = new Set<string>(), prefixes = new Set<string>(), fromDepths = new Set<number>(); let routines = false;
  for (let cursor = 0; cursor < tokens.length; cursor++) {
    const token = tokens[cursor];
    if (token.symbol && token.value === ")") for (const depth of fromDepths) if (depth > token.depth) fromDepths.delete(depth);
    if (token.symbol && token.value === ";") fromDepths.clear();
    if (token.symbol && token.value === "," && fromDepths.has(token.depth)) {
      const relation = path(cursor + 1);
      if (relation.parts.length) references.add(JSON.stringify(relation.parts));
    }
    if (token.symbol || token.quoted) continue;
    const keyword = token.value.toUpperCase();
    if (["FROM", "JOIN"].includes(keyword)) fromDepths.add(token.depth);
    else if (FROM_END.has(keyword)) fromDepths.delete(token.depth);
    if (RELATIONS.has(keyword)) {
      const relation = path(cursor + 1);
      if (relation.parts.length) references.add(JSON.stringify(relation.parts));
    }
    if (ROUTINES.has(keyword)) routines = true;
  }
  for (let cursor = 0; cursor < tokens.length;) {
    const qualified = path(cursor);
    if (qualified.parts.length > 1 || qualified.trailing) {
      prefixes.add(JSON.stringify(qualified.trailing ? qualified.parts : qualified.parts.slice(0, -1)));
    }
    cursor = Math.max(cursor + 1, qualified.next);
  }
  return JSON.stringify([[...references].sort(), [...prefixes].sort(), routines]);
}

const scopeKey = (scope: PreparationScope) => JSON.stringify([scope.connectionId ?? "", scope.database ?? "", scope.schema ?? "", scope.blockId ?? ""]);

/** Preparation follows focus and scope changes, independently of editor typing. */
export class ScopePreparation {
  private sessions = new Map<string, Map<string, PreparationEntry>>();
  private aliases = new Map<string, Map<string, Set<string>>>();
  constructor(private transport: Pick<RuntimeTransport, "request"> = runtime,
    private invalidate?: (scope: PreparationScope) => void, private maximum = 64) {}

  request(scope: PreparationScope, code = "", force = false): Promise<PreparationResult> {
    const normalized = { ...scope };
    const target = scopeKey(normalized), key = JSON.stringify([target, Boolean(scope.scopeInherited), preparationCodeKey(code, scope.dbType)]);
    let entries = this.sessions.get(scope.sessionId);
    if (!entries) { entries = new Map(); this.sessions.set(scope.sessionId, entries); }
    if (force) {
      this.releaseScope(normalized);
      this.invalidate?.(normalized);
    } else {
      const existing = entries.get(key);
      if (existing) { entries.delete(key); entries.set(key, existing); return existing.promise; }
    }
    let entry: PreparationEntry;
    const params = { session_id: normalized.sessionId, ...(normalized.blockId ? {block_id:normalized.blockId} : {}), connection_id: normalized.connectionId,
      ...(normalized.blockId || normalized.scopeInherited!==undefined?{scope_inherited:Boolean(normalized.scopeInherited)}:{}),
      database: normalized.database, schema: normalized.schema, code, ...(force ? { refresh: true } : {}) };
    // Start asynchronously so synchronous transport errors participate in the
    // same retry path, and the entry exists before a runtime event can arrive.
    const promise = Promise.resolve().then(() => this.transport.request<PreparationResult>("language.prepare", params))
      .catch(failure => {
        const current = this.sessions.get(scope.sessionId);
        if (current?.get(key) === entry) {
          current.delete(key);
          if (!current.size) this.sessions.delete(scope.sessionId);
        }
        throw failure;
      });
    entry = { scope: normalized, promise };
    entries.set(key, entry);
    while (entries.size > Math.max(1, this.maximum)) entries.delete(entries.keys().next().value!);
    return promise;
  }

  /** Release acknowledgements and pending cache entries for one exact SQL scope. */
  private releaseScope(scope: PreparationScope) {
    const entries = this.sessions.get(scope.sessionId), target = scopeKey(scope);
    if (entries) for (const [key, entry] of entries) if (scopeKey(entry.scope) === target) entries.delete(key);
  }

  reset(sessionId?: string) {
    if (sessionId === undefined) { this.sessions.clear(); this.aliases.clear(); }
    else { this.sessions.delete(sessionId); this.aliases.delete(sessionId); }
  }

  retain(sessionIds: ReadonlySet<string>) {
    for (const id of this.sessions.keys()) if (!sessionIds.has(id)) this.sessions.delete(id);
    for (const id of this.aliases.keys()) if (!sessionIds.has(id)) this.aliases.delete(id);
  }

  /** Lifecycle invalidations make the next focus eligible to prepare metadata again. */
  accept(event: RuntimeEvent) {
    if (event.event === "backend.exited") { this.reset(); return; }
    if (["session.ready", "session.reset", "session.error"].includes(event.event)) { this.reset(event.payload.session_id); return; }
    if (event.event === "execution.finished" && event.payload.context_change) {
      const payload=event.payload,entries=this.sessions.get(payload.session_id),requested=payload.context_change!.requested_scope;
      if(entries)for(const [key,entry] of entries)if((!payload.block_id || entry.scope.blockId===payload.block_id || payload.scope_inherited && (entry.scope.scopeInherited || !entry.scope.blockId)) && (entry.scope.connectionId ?? "")===(requested.connection_id ?? ""))entries.delete(key);
      return;
    }
    if (event.event !== "language.context_updated") return;
    const payload = event.payload;
    if (payload.requested_scope && (payload.metadata_state === "ready" || payload.schema_snapshot)) {
      let aliases = this.aliases.get(payload.session_id);
      if (!aliases) { aliases = new Map(); this.aliases.set(payload.session_id, aliases); }
      const resolved = payload.connection_id ?? "", requested = payload.requested_scope.connection_id ?? "";
      const connections = aliases.get(resolved) ?? new Set<string>();
      connections.add(requested); aliases.delete(resolved); aliases.set(resolved, connections);
      while (aliases.size > Math.max(1, this.maximum)) aliases.delete(aliases.keys().next().value!);
    }
    if (payload.metadata_invalidated) {
      const connections = new Set([payload.connection_id ?? "", ...(this.aliases.get(payload.session_id)?.get(payload.connection_id ?? "") ?? [])]);
      if (payload.requested_scope) connections.add(payload.requested_scope.connection_id ?? "");
      // The transient runtime label represents the UI's absent connection ID.
      if (payload.connection_id === "transient") connections.add("");
      const entries = this.sessions.get(payload.session_id);
      if (entries) for (const [key, entry] of entries) {
        if (connections.has(entry.scope.connectionId ?? "") && (payload.metadata_invalidation_scope!=="block" || !payload.block_id || entry.scope.blockId===payload.block_id || payload.scope_inherited && (entry.scope.scopeInherited || !entry.scope.blockId))) entries.delete(key);
      }
    }
    if (payload.metadata_state === "error") {
      const requested = payload.requested_scope;
      this.releaseScope({ sessionId: payload.session_id, blockId:payload.block_id, connectionId: requested ? requested.connection_id ?? undefined : payload.connection_id,
        database: requested ? requested.database ?? undefined : payload.database,
        schema: requested ? requested.schema ?? undefined : payload.schema });
    }
  }
}
