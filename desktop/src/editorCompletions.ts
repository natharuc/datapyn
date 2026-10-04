import type { CompletionContext, LanguageCompletion } from "./editorLanguage";
import type { Language } from "./runtime";

const SQL_KEYWORDS = "SELECT FROM WHERE AND OR NOT IN BETWEEN LIKE IS NULL JOIN INNER LEFT RIGHT FULL OUTER CROSS ON AS ORDER BY GROUP HAVING LIMIT OFFSET DISTINCT INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE DROP ALTER COUNT SUM AVG MIN MAX CASE WHEN THEN ELSE END EXISTS UNION ALL TOP WITH OVER PARTITION ROW_NUMBER RANK DENSE_RANK LAG LEAD ASC DESC USE EXEC CALL DECLARE BEGIN COMMIT ROLLBACK COALESCE CAST CONVERT".split(" ");
const PYTHON_KEYWORDS = "def class if elif else for while return import from as try except finally with lambda yield True False None and or not in is pass break continue async await raise assert del global nonlocal match case".split(" ");
const PYTHON_BUILTINS = "abs all any bool bytes callable chr dict dir enumerate filter float format getattr hasattr int isinstance issubclass iter len list map max min next object open ord print range repr reversed round set setattr sorted str sum super tuple type zip".split(" ");
const PYTHON_HARD_KEYWORDS = new Set(PYTHON_KEYWORDS.filter(keyword => keyword !== "match" && keyword !== "case"));
const IDENTIFIER = /^[\p{L}_][\p{L}\p{N}_]*$/u;
const WORD = /[\p{L}\p{N}_$]+$/u;
const SQL_IDENTIFIER = String.raw`(?:\[(?:\]\]|[^\]])+\]|"(?:""|[^"])+"|\x60(?:\x60\x60|[^\x60])+\x60|[\p{L}_][\p{L}\p{N}_$]*)`;
interface SqlIdentifierPart { name: string; quoted: boolean }

export interface CompletionSite {
  prefix: string; startColumn: number; endColumn: number; member?: string;
  quote?: string; stringColumn?: boolean; blocked?: boolean;
  memberParts?: SqlIdentifierPart[];
}

/** Columns are Monaco UTF-16 indexes; replacement owns the suffix, not only typed text. */
export function completionSite(language: Language, line: string, column: number): CompletionSite {
  const offset = Math.max(0, Math.min(line.length, column - 1)), before = line.slice(0, offset), after = line.slice(offset);
  const prefix = before.match(WORD)?.[0] ?? "", suffix = after.match(/^[\p{L}\p{N}_$]*/u)?.[0] ?? "";
  const site: CompletionSite = { prefix, startColumn: offset - prefix.length + 1, endColumn: offset + suffix.length + 1 };
  let quote = "", quoteStart = -1;
  for (let index = 0; index < before.length; ++index) {
    const ch = before[index], next = before[index + 1];
    if (quote) {
      if (language === "python" && ch === "\\") { ++index; continue; }
      const end = quote === "[" ? "]" : quote;
      if (ch === end) {
        if (language === "sql" && next === end) { ++index; continue; }
        quote = "";
      }
    } else {
      if ((language === "python" && ch === "#") || (language === "sql" && ch === "-" && next === "-")) return { ...site, blocked: true };
      if (ch === "'" || ch === '"' || (language === "sql" && (ch === "[" || ch === "`"))) { quote = ch; quoteStart = index; }
    }
  }
  if (language === "python" && quote) {
    const receiver = before.slice(0, quoteStart).match(/([\p{L}_][\p{L}\p{N}_]*)\s*\[\s*$/u)?.[1];
    if (!receiver) return { ...site, blocked: true };
    const end = closingQuote(after, quote, language);
    return { prefix: decodePythonString(before.slice(quoteStart + 1)), startColumn: quoteStart + 2, endColumn: end < 0 ? offset + 1 : offset + end + 1, member: receiver, quote, stringColumn: true };
  }
  if (language === "sql" && quote) {
    if (quote === "'") return { ...site, blocked: true };
    const endQuote = quote === "[" ? "]" : quote, end = closingQuote(after, quote, language);
    const memberParts = memberQualifier(before.slice(0, quoteStart));
    return { prefix: before.slice(quoteStart + 1).replaceAll(endQuote + endQuote, endQuote), startColumn: quoteStart + 1, endColumn: end < 0 ? offset + 1 : offset + end + 2, member: memberParts?.map(part => part.name).join("."), memberParts, quote };
  }
  const memberParts = memberQualifier(before.slice(0, offset - prefix.length));
  site.member = memberParts?.map(part => part.name).join(".");
  if (language === "sql") site.memberParts = memberParts;
  return site;
}

function closingQuote(after: string, quote: string, language: Language): number {
  const end = quote === "[" ? "]" : quote;
  for (let index = 0; index < after.length; ++index) {
    if (language === "python" && after[index] === "\\") { ++index; continue; }
    if (after[index] !== end) continue;
    if (language === "sql" && after[index + 1] === end) { ++index; continue; }
    return index;
  }
  return -1;
}

function identifierParts(raw: string): SqlIdentifierPart[] | undefined {
  const parts: SqlIdentifierPart[] = [], token = new RegExp(SQL_IDENTIFIER, "uy"); let offset = 0;
  while (offset < raw.length) {
    token.lastIndex = offset; const match = token.exec(raw); if (!match) return;
    const value = match[0], quoted = /^[\["`]/.test(value), end = value[0] === "[" ? "]" : value[0];
    parts.push({ name: quoted ? value.slice(1, -1).replaceAll(end + end, end) : value, quoted });
    offset = token.lastIndex; const separator = raw.slice(offset).match(/^\s*\.\s*/)?.[0];
    if (!separator) return offset === raw.length ? parts : undefined;
    offset += separator.length;
  }
}
function memberQualifier(before: string): SqlIdentifierPart[] | undefined {
  const raw = before.match(new RegExp(String.raw`(${SQL_IDENTIFIER}(?:\s*\.\s*${SQL_IDENTIFIER})*)\s*\.\s*$`, "u"))?.[1];
  return raw ? identifierParts(raw) : undefined;
}
function normalizedSqlName(parts: SqlIdentifierPart[] | undefined, fallback: string, dbType?: string): string {
  return parts?.map(part => dbType === "postgresql" && !part.quoted ? part.name.toLowerCase() : part.name).join(".") ?? fallback;
}

function quoteSqlPart(name: string, dbType = "sqlserver") {
  if (dbType === "sqlserver" || dbType === "mssql") return `[${name.replace(/\]/g, "]]")}]`;
  if (dbType === "mysql" || dbType === "mariadb" || dbType === "databricks") return `\`${name.replace(/`/g, "``")}\``;
  // Quote every identifier, matching the runtime without a partial keyword list.
  return `"${name.replace(/"/g, '""')}"`;
}
function sqlName(name: string, dbType?: string) { return name.split(".").map(part => quoteSqlPart(part, dbType)).join("."); }
function tableInsertion(key: string, context: CompletionContext | undefined, qualifier?: string): string {
  const metadata=context?.schemaSnapshot?.tables?.[key],name=metadata?.name,dbType=context?.schemaSnapshot?.db_type;
  if(!name)return sqlName(qualifier?key.slice(qualifier.length+1):key,dbType);
  const prefix=key===name?"":key.endsWith(`.${name}`)?key.slice(0,-name.length-1):metadata.schema??"";
  const schema=metadata.schema;
  const parts=schema&&(prefix===schema||prefix.endsWith(`.${schema}`))
    ? [...(prefix===schema?[]:prefix.slice(0,-schema.length-1).split(".")),schema,name]
    : [...(prefix?prefix.split("."):[]),name];
  if(qualifier)for(let count=1;count<parts.length;count++)if(parts.slice(0,count).join(".").toLowerCase()===qualifier.toLowerCase())return parts.slice(count).map(part=>quoteSqlPart(part,dbType)).join(".");
  return parts.map(part=>quoteSqlPart(part,dbType)).join(".");
}
const sqlContextCache = new WeakMap<CompletionContext, { names: Set<string>; items: LanguageCompletion[] }>();
function sqlContext(context?: CompletionContext) {
  if (context) { const cached = sqlContextCache.get(context); if (cached) return cached; }
  const names = new Set([...Object.keys(context?.schemaSnapshot?.tables ?? {}), ...(context?.tables ?? [])]);
  const value = { names, items: [...names].map(name => ({ label: name, kind: "table", insert_text: tableInsertion(name,context), sortText: `0:${name}` })) };
  if (context) sqlContextCache.set(context, value); return value;
}
function resolveTable(name: string | undefined, context: CompletionContext | undefined, names: Set<string>): string | undefined {
  if (!name) return;
  const tables = context?.schemaSnapshot?.tables ?? {}, query = name.toLowerCase(), strictCase = context?.schemaSnapshot?.db_type === "postgresql";
  if(names.has(name))return name;
  const keys=[...names],folded=strictCase?[]:keys.filter(key=>key.toLowerCase()===query);
  if(folded.length)return folded.length===1?folded[0]:undefined;
  const chooseScope=(candidates:string[])=>{
    const temporary=candidates.filter(key=>tables[key]?.temporary);
    if(temporary.length)return temporary.length===1?temporary[0]:undefined;
    const schemaOf=(key:string)=>tables[key]?.schema??key.split(".").at(-2);
    if(context?.schema!==undefined){
      const exactScope=candidates.filter(key=>schemaOf(key)===context.schema);
      if(exactScope.length)return exactScope.length===1?exactScope[0]:undefined;
      const foldedScope=strictCase?[]:candidates.filter(key=>schemaOf(key)?.toLowerCase()===context.schema!.toLowerCase());
      if(foldedScope.length)return foldedScope.length===1?foldedScope[0]:undefined;
    }
    return candidates.length===1?candidates[0]:undefined;
  };
  const bareName=(key:string)=>tables[key]?.name??key.split(".").at(-1);
  const exactBare=keys.filter(key=>bareName(key)===name);
  return exactBare.length?chooseScope(exactBare):strictCase?undefined:chooseScope(keys.filter(key=>bareName(key)?.toLowerCase()===query));
}

export function localCompletions(language: Language, site: CompletionSite, context: CompletionContext | undefined,
  textBefore: string, currentSymbols: LanguageCompletion[] = [], documentSource = textBefore): LanguageCompletion[] {
  if (site.blocked) return [];
  const items: LanguageCompletion[] = [];
  if (language === "python") {
    if (site.member) {
      const variable = context?.variables.find(item => item.name === site.member);
      for (const name of variable?.columns ?? []) if (site.stringColumn || (IDENTIFIER.test(name)&&!PYTHON_HARD_KEYWORDS.has(name))) items.push({ label: name, kind: "field", detail: `${site.member} column`, insert_text: name, sortText: `0:${name}` });
      return filterCompletions(items, site.prefix, language);
    }
    items.push(...(context?.variables ?? []).map(variable => ({ label: variable.name, kind: "variable", detail: variable.type, sortText: `0:${variable.name}` })), ...currentSymbols);
    items.push(...pythonContextSymbols(context));
    items.push(...PYTHON_KEYWORDS.map(label => ({ label, kind: "keyword", sortText: `2:${label}` })), ...PYTHON_BUILTINS.map(label => ({ label, kind: "function", sortText: `2:${label}` })));
  } else {
    const tables = context?.schemaSnapshot?.tables ?? {}, dbType = context?.schemaSnapshot?.db_type;
    const { names, items: tableItems } = sqlContext(context);
    if (site.member) {
      const member = normalizedSqlName(site.memberParts, site.member, dbType);
      let tableName = resolveTable(member, context, names);
      if (!tableName) {
        // Resolve common aliases immediately; advanced CTE/subquery inference is asynchronous.
        const source = documentSource.replace(new RegExp(String.raw`(${SQL_IDENTIFIER})|--[^\n]*|'(?:''|[^'])*'|\/\*[\s\S]*?\*\/`, "gu"), (match, identifier: string | undefined) => identifier ?? " ");
        const aliases = new RegExp(String.raw`\b(?:FROM|JOIN|UPDATE|INTO)\s+(${SQL_IDENTIFIER}(?:\s*\.\s*${SQL_IDENTIFIER})*)\s+(?:AS\s+)?(${SQL_IDENTIFIER})`, "giu");
        for (const match of source.matchAll(aliases)) {
          const aliasParts = identifierParts(match[2]), tableParts = identifierParts(match[1]);
          if (!aliasParts || !tableParts) continue;
          const alias = normalizedSqlName(aliasParts, match[2], dbType);
          if (dbType === "postgresql" ? alias === member : alias.toLowerCase() === member.toLowerCase()) tableName = resolveTable(normalizedSqlName(tableParts, match[1], dbType), context, names);
        }
      }
      const metadata = tableName && tables[tableName];
      if (metadata) for (const column of metadata.columns ?? []) items.push({ label: column.name, kind: "column", detail: `${tableName} · ${column.data_type ?? column.type ?? ""}`, insert_text: quoteSqlPart(column.name, dbType), sortText: `0:${column.name}` });
      if (!metadata) for (const name of names) if (name.toLowerCase().startsWith(`${site.member.toLowerCase()}.`)) {
        const tail = name.slice(site.member.length + 1);
        items.push({ label: tail, kind: "table", insert_text: tableInsertion(name,context,site.member), sortText: `0:${tail}` });
      }
      return filterCompletions(items, site.prefix, language);
    }
    const relation = /\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+[^\s]*$/i.test(textBefore);
    items.push(...tableItems);
    if (!relation) items.push(...SQL_KEYWORDS.map(label => ({ label, kind: "keyword", sortText: `2:${label}` })));
  }
  if (!site.member) for (const sibling of context?.siblings ?? []) {
    if (sibling.language !== language || sibling.cellType === "markdown" || !sibling.code || (site.prefix && !(language === "sql" ? sibling.name.toLowerCase().startsWith(site.prefix.toLowerCase()) : sibling.name.startsWith(site.prefix)))) continue;
    items.push({ label: `block: ${sibling.name}`, filterText: sibling.name, kind: "snippet", category: "block", is_snippet: false,
      detail: `${language} · ${sibling.code.slice(0, 72).split("\n")[0]}`, documentation: sibling.code.slice(0, 2_000),
      insert_text: sibling.code.endsWith("\n") ? sibling.code : `${sibling.code}\n`, sortText: `3:${sibling.name}` });
  }
  return filterCompletions(items, site.prefix, language);
}

const contextSymbolCache = new WeakMap<CompletionContext, LanguageCompletion[]>();
function pythonContextSymbols(context?: CompletionContext) {
  if (!context) return [];
  const cached = contextSymbolCache.get(context); if (cached) return cached;
  const items = pythonSymbols(`${context.globalImports ?? ""}\n${context.preamble ?? ""}`);
  contextSymbolCache.set(context, items); return items;
}

/** Static names only; source is never executed and the scanning budget is bounded. */
export function pythonSymbols(source: string): LanguageCompletion[] {
  const names = new Map<string, LanguageCompletion>();
  for (const line of source.slice(-200_000).split("\n")) {
    const declaration = line.match(/^\s*(?:(?:async\s+)?(def|class)\s+)?([\p{L}_][\p{L}\p{N}_]*)\s*(?:[:=(])/u);
    if (declaration && !PYTHON_KEYWORDS.includes(declaration[2])) names.set(declaration[2], { label: declaration[2], kind: declaration[1] === "def" ? "function" : declaration[1] === "class" ? "class" : "variable", sortText: `1:${declaration[2]}` });
    const imported = line.match(/^\s*(?:from\s+[\w.]+\s+)?import\s+(.+)$/);
    if (imported) for (const raw of imported[1].split(",")) {
      const match = raw.trim().match(/^([\w.]+)(?:\s+as\s+(\w+))?/); if (!match) continue;
      const name = match[2] ?? (line.trimStart().startsWith("from ") ? match[1] : match[1].split(".")[0]);
      if (IDENTIFIER.test(name)) names.set(name, { label: name, kind: "module", detail: match[1], sortText: `1:${name}` });
    }
    if (names.size >= 1_000) break;
  }
  return [...names.values()];
}

/** Prefix filtering happens before the bound, so late-alphabet schema items stay reachable. */
export function filterCompletions(items: LanguageCompletion[], prefix: string, language: Language): LanguageCompletion[] {
  const query = language === "sql" ? prefix.toLowerCase() : prefix;
  const matching = items.filter(item => {
    const label = item.filterText ?? item.label, candidate = language === "sql" ? label.toLowerCase() : label;
    return !query || candidate.startsWith(query) || (language === "sql" && candidate.split(".").at(-1)?.startsWith(query));
  });
  return matching.slice(0, 500);
}

export function completionInsertion(item: LanguageCompletion, site: CompletionSite, language: Language): string {
  let text = item.insert_text ?? item.insertText ?? item.label;
  if (language === "python" && site.stringColumn && ["field", "column"].includes(item.kind ?? "")) return escapePythonString(item.label, site.quote ?? '"');
  if (language === "sql" && site.quote && !site.stringColumn) {
    const end = site.quote === "[" ? "]" : site.quote;
    // Range owns an existing quote pair, so insert exactly one pair in the user's style.
    text = sqlInsertionParts(text).map(plain => `${site.quote}${plain.replaceAll(end, end + end)}${end}`).join(".");
  }
  return text;
}

export function escapePythonString(value: string, quote: string): string { return value.replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/\r/g, "\\r").replace(/\t/g, "\\t").replaceAll(quote, `\\${quote}`); }
function decodePythonString(value: string) {
  return value.replace(/\\(?:([\\'"nrt])|x([0-9a-fA-F]{2})|u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8}))/g, (_all, escaped: string | undefined, x: string | undefined, u: string | undefined, big: string | undefined) => {
    if (escaped) return ({ n: "\n", r: "\r", t: "\t" } as Record<string, string>)[escaped] ?? escaped;
    const point = Number.parseInt(x ?? u ?? big ?? "0", 16); return point <= 0x10ffff ? String.fromCodePoint(point) : _all;
  });
}
function sqlInsertionParts(text: string) {
  const parts: string[] = []; let value = "", quote = "";
  for (let index = 0; index < text.length; ++index) {
    const char = text[index];
    if (quote) {
      const end = quote === "[" ? "]" : quote;
      if (char === end) { if (text[index + 1] === end) { value += end; ++index; } else quote = ""; }
      else value += char;
    } else if (char === "[" || char === '"' || char === "`") quote = char;
    else if (char === ".") { parts.push(value); value = ""; }
    else value += char;
  }
  parts.push(value); return parts;
}
