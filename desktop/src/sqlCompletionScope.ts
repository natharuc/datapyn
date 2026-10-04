/** A bounded lexical index for instant SQL suggestions; full inference stays in the runtime. */
export interface SqlIdentifierPart { name: string; quoted: boolean }
interface Token { raw: string; start: number; end: number; depth: number; part?: SqlIdentifierPart }
interface Query { start: number; end: number; depth: number }
export interface SqlRelation { parts: SqlIdentifierPart[]; alias?: SqlIdentifierPart; virtual?: boolean }
export interface SqlScope { relations: SqlRelation[]; before: string; blocked: boolean }
const WORD = /^[\p{L}\p{N}_@$#]+/u;
const CLAUSES = new Set("WHERE JOIN INNER LEFT RIGHT FULL OUTER CROSS ON GROUP ORDER HAVING LIMIT OFFSET UNION INTERSECT EXCEPT SELECT SET VALUES RETURNING QUALIFY WINDOW AS".split(" "));
export function sqlStringEscapesBackslash(source: string, quoteStart: number, dbType?: string): boolean {
  return ["mysql", "mariadb"].includes(dbType ?? "") || ([undefined, "postgres", "postgresql"].includes(dbType) &&
    quoteStart > 0 && /[Ee]/.test(source[quoteStart - 1]) && (quoteStart < 2 || !/[\p{L}\p{N}_$]/u.test(source[quoteStart - 2])));
}

function tokens(source: string, cursor: number, dbType?: string, partialQuoted = false): { values: Token[]; blocked: boolean } {
  const values: Token[] = []; let index = 0, depth = 0, blocked = false;
  while (index < source.length) {
    const start = index, char = source[index];
    if (/\s/.test(char)) { index++; continue; }
    if (source.startsWith("--", index) || (char === "#" && ["mysql", "mariadb"].includes(dbType ?? ""))) {
      const end = source.indexOf("\n", index); index = end < 0 ? source.length : end;
      if (start < cursor && cursor <= index) blocked = true;
      continue;
    }
    if (source.startsWith("/*", index)) {
      index += 2; let nesting = 1;
      while (index < source.length && nesting) {
        if (source.startsWith("/*", index)) { nesting++; index += 2; }
        else if (source.startsWith("*/", index)) { nesting--; index += 2; }
        else index++;
      }
      if (start < cursor && (cursor < index || (nesting > 0 && cursor === index))) blocked = true;
      continue;
    }
    const dollar = char === "$" && [undefined, "postgres", "postgresql"].includes(dbType) ? source.slice(index).match(/^\$(?:[A-Za-z_]\w*)?\$/)?.[0] : undefined;
    if (dollar) {
      const end = source.indexOf(dollar, index + dollar.length); index = end < 0 ? source.length : end + dollar.length;
      if (start < cursor && (cursor < index || (end < 0 && cursor === index))) blocked = true;
      continue;
    }
    if (["'", '"', "`", "["].includes(char)) {
      const quote = char === "[" ? "]" : char, escapesBackslash = char === "'" && sqlStringEscapesBackslash(source, start, dbType); let name = "", closed = false; index++;
      while (index < source.length) {
        // An unfinished quoted field cannot consume the FROM clause to its right.
        if (partialQuoted && char !== "'" && start < cursor && index === cursor) {
          const suffix = source.slice(index).match(new RegExp(`^[\\p{L}\\p{N}_$]*${quote === "]" ? "\\]" : quote}`, "u"));
          if (suffix) index += suffix[0].length;
          closed = true; break;
        }
        if (source[index] === quote) {
          index++; if (source[index] === quote) { name += quote; index++; continue; }
          closed = true; break;
        }
        if (escapesBackslash && source[index] === "\\") { index += 2; continue; }
        name += source[index++];
      }
      index = Math.min(index, source.length);
      if (char === "'") { if (start < cursor && (cursor < index || (!closed && cursor === index))) blocked = true; continue; }
      values.push({ raw: source.slice(start, index), start, end: index, depth, part: { name, quoted: true } }); continue;
    }
    const word = source.slice(index).match(WORD)?.[0];
    if (word) { index += word.length; values.push({ raw: word, start, end: index, depth, part: { name: word, quoted: false } }); continue; }
    if (char === ")") depth = Math.max(0, depth - 1);
    values.push({ raw: char, start, end: ++index, depth });
    if (char === "(") depth++;
  }
  return { values, blocked };
}

export function sqlCompletionScope(source: string, cursor: number, dbType?: string, partialQuoted = false): SqlScope {
  cursor = Math.max(0, Math.min(cursor, source.length));
  const lexical = tokens(source, cursor, dbType, partialQuoted), all = lexical.values;
  let start = 0, end = source.length;
  for (const token of all) {
    const go = ["sqlserver", "mssql"].includes(dbType ?? "") && !token.part?.quoted && token.raw.toUpperCase() === "GO" && /(?:^|\n)[ \t]*$/.test(source.slice(0, token.start)) && /^[ \t]*(?:--[^\n]*)?(?:\n|$)/.test(source.slice(token.end));
    if (token.raw !== ";" && !go) continue;
    if (token.end <= cursor) start = token.end;
    else if (token.start >= cursor) { end = token.start; break; }
  }
  const current = all.filter(token => token.start >= start && token.end <= end);
  const queries: Query[] = [];
  for (const token of current) if (!token.part?.quoted && token.raw.toUpperCase() === "SELECT") {
    const closing = current.find(next => next.start > token.start && (next.depth < token.depth || (next.depth === token.depth && !next.part?.quoted && ["UNION", "INTERSECT", "EXCEPT"].includes(next.raw.toUpperCase()))));
    queries.push({ start: token.start, end: closing?.start ?? end, depth: token.depth });
  }
  const enclosing = queries.filter(query => query.start <= cursor && cursor <= query.end).sort((a, b) => a.depth - b.depth || a.start - b.start);
  const scopes = enclosing.length ? enclosing : [{ start, end, depth: 0 }];
  const virtual = new Set<string>();
  for (let index = 0; index < current.length - 2; index++) {
    const name = current[index], next = current[index + 1], opening = current[index + 2];
    if (name.part && !next.part?.quoted && next.raw.toUpperCase() === "AS" && opening.raw === "(" && current.slice(0, index).some(token => !token.part?.quoted && token.raw.toUpperCase() === "WITH")) virtual.add(name.part.name.toLowerCase());
  }
  const relations: SqlRelation[] = [];
  for (const scope of scopes) {
    let inFrom = false;
    for (let index = 0; index < current.length; index++) {
    const token = current[index];
    if (token.start < scope.start || token.start >= scope.end || token.depth !== scope.depth || token.part?.quoted) continue;
    const keyword = token.raw.toUpperCase();
    if (["FROM", "JOIN"].includes(keyword)) inFrom = true;
    else if (["WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET", "UNION", "INTERSECT", "EXCEPT", "QUALIFY", "WINDOW"].includes(keyword)) inFrom = false;
    if (!["FROM", "JOIN", "UPDATE", "INTO"].includes(keyword) && !(token.raw === "," && inFrom)) continue;
    const parts: SqlIdentifierPart[] = []; let next = index + 1, complete = true;
    if (current[next]?.raw === "(") {
      // Reserve a derived table's alias without guessing its output columns.
      // The runtime infers projections; a same-named physical table must never
      // contribute unrelated local fields while that response is pending.
      const closing = current.findIndex((candidate, candidateIndex) => candidateIndex > next && candidate.raw === ")" && candidate.depth === scope.depth);
      if (closing < 0) continue;
      next = closing + 1;
      if (!current[next]?.part?.quoted && current[next]?.raw.toUpperCase() === "AS") next++;
      const candidate = current[next], alias = candidate?.part && (candidate.part.quoted || !CLAUSES.has(candidate.raw.toUpperCase())) ? candidate.part : undefined;
      if (alias) relations.push({ parts: [alias], alias, virtual: true });
      continue;
    }
    if (!current[next]?.part) continue;
    parts.push(current[next++].part!);
    while (current[next]?.raw === ".") {
      next++;
      if (current[next]?.raw === ".") { parts.push({ name: "dbo", quoted: false }); next++; }
      if (!current[next]?.part) { complete = false; break; }
      parts.push(current[next++].part!);
    }
    if (!complete) continue;
    if (!current[next]?.part?.quoted && current[next]?.raw.toUpperCase() === "AS") next++;
    const candidate = current[next], alias = candidate?.part && (candidate.part.quoted || !CLAUSES.has(candidate.raw.toUpperCase())) ? candidate.part : undefined;
    relations.push({ parts, alias, virtual: parts.length === 1 && virtual.has(parts[0].name.toLowerCase()) });
    }
  }
  const focused = scopes.at(-1)!;
  return { relations, before: source.slice(Math.max(start, focused.start), cursor), blocked: lexical.blocked };
}
