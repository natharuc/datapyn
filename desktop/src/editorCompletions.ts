import type { CompletionContext, LanguageCompletion } from "./editorLanguage";
import type { Language } from "./runtime";
import { dataframeLibrary, dataframeMemberNames, dataframeMembers } from "./dataframeMembers";
import { sqlCompletionScope, sqlStringEscapesBackslash } from "./sqlCompletionScope";
import { plainSqlIdentifier } from "./sqlIdentifierKeywords";

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
  columnContext?: "index" | "loc" | "sort_values" | "sort";
  memberParts?: SqlIdentifierPart[];
}

/** Columns are Monaco UTF-16 indexes; replacement owns the suffix, not only typed text. */
export function completionSite(language: Language, line: string, column: number, sqlDbType?: string): CompletionSite {
  const offset = Math.max(0, Math.min(line.length, column - 1)), before = line.slice(0, offset), after = line.slice(offset);
  const prefix = before.match(WORD)?.[0] ?? "", suffix = after.match(/^[\p{L}\p{N}_$]*/u)?.[0] ?? "";
  const site: CompletionSite = { prefix, startColumn: offset - prefix.length + 1, endColumn: offset + suffix.length + 1 };
  let quote = "", quoteStart = -1;
  for (let index = 0; index < before.length; ++index) {
    const ch = before[index], next = before[index + 1];
    if (quote) {
      if (ch === "\\" && (language === "python" || (quote === "'" && sqlStringEscapesBackslash(before, quoteStart, sqlDbType)))) { ++index; continue; }
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
    const receiver = pythonColumnReceiver(before.slice(0, quoteStart));
    if (!receiver) return { ...site, blocked: true };
    const end = closingQuote(after, quote, language);
    return { prefix: decodePythonString(before.slice(quoteStart + 1)), startColumn: quoteStart + 2, endColumn: end < 0 ? offset + 1 : offset + end + 1, member: receiver.member, quote, stringColumn: true, columnContext: receiver.columnContext };
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

const PYTHON_RECEIVER = String.raw`(?<![\p{L}\p{N}_.])([\p{L}_][\p{L}\p{N}_]*)`;
const INDEX_RECEIVER = new RegExp(`${PYTHON_RECEIVER}\\s*$`, "u");
const LOC_RECEIVER = new RegExp(`${PYTHON_RECEIVER}\\s*\\.\\s*loc\\s*$`, "u");
const SORT_RECEIVER = new RegExp(`${PYTHON_RECEIVER}\\s*\\.\\s*(sort_values|sort)\\s*$`, "u");
interface PythonOpening { char: string; index: number }
/** Recognize column positions, not arbitrary strings, using a bounded lexical window. */
function pythonColumnReceiver(beforeQuote: string): Pick<CompletionSite, "member" | "columnContext"> | undefined {
  const source = beforeQuote.slice(-8192), masked = source.split(""), stack: PythonOpening[] = [];
  for (let index = 0; index < source.length; index++) {
    const char = source[index];
    if (char === "#") return;
    if (char === "'" || char === '"') {
      const triple = source.slice(index, index + 3) === char.repeat(3), delimiter = triple ? char.repeat(3) : char;
      const start = index; let end = index + delimiter.length, closed = false;
      while (end < source.length) {
        if (source[end] === "\\") { end += 2; continue; }
        if (source.slice(end, end + delimiter.length) === delimiter) { end += delimiter.length; closed = true; break; }
        end++;
      }
      if (!closed) return;
      for (let position = start; position < end; position++) masked[position] = position === start ? "\0" : " ";
      index = end - 1; continue;
    }
    if ("([{".includes(char)) stack.push({ char, index });
    else if (")]}".includes(char)) {
      const opening = stack.pop(); if (!opening || "([{".indexOf(opening.char) !== ")]}".indexOf(char)) return;
    }
  }
  const text = masked.join(""), opening = stack.at(-1); if (!opening) return;
  const classify = (parent: PythonOpening, body: string): Pick<CompletionSite, "member" | "columnContext"> | undefined => {
    const head = text.slice(0, parent.index), argument = lastPythonArgument(body);
    if (parent.char === "[") {
      const index = head.match(INDEX_RECEIVER); if (index && !body.trim()) return { member: index[1], columnContext: "index" };
      const loc = head.match(LOC_RECEIVER); if (loc && argument.hasComma && !argument.text.trim()) return { member: loc[1], columnContext: "loc" };
    } else if (parent.char === "(") {
      const sort = head.match(SORT_RECEIVER);
      if (sort && ((!argument.hasComma && !body.trim()) || /^\s*by\s*=\s*$/.test(argument.text))) return { member: sort[1], columnContext: sort[2] as "sort_values" | "sort" };
    }
  };
  const direct = classify(opening, text.slice(opening.index + 1)); if (direct) return direct;
  // Column lists permit only completed literal strings before the editable string.
  if (opening.char !== "[" || !/^\s*(?:\0\s*,\s*)*$/.test(text.slice(opening.index + 1))) return;
  const parent = stack.at(-2); return parent ? classify(parent, text.slice(parent.index + 1, opening.index)) : undefined;
}
function lastPythonArgument(body: string): { text: string; hasComma: boolean } {
  let depth = 0, last = -1;
  for (let index = 0; index < body.length; index++) {
    if ("([{".includes(body[index])) depth++;
    else if (")]}".includes(body[index])) depth--;
    else if (body[index] === "," && depth === 0) last = index;
  }
  return { text: body.slice(last + 1), hasComma: last >= 0 };
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
  if (plainSqlIdentifier(name, dbType)) return name;
  if (dbType === "sqlserver" || dbType === "mssql") return `[${name.replace(/\]/g, "]]")}]`;
  if (dbType === "mysql" || dbType === "mariadb" || dbType === "databricks") return `\`${name.replace(/`/g, "``")}\``;
  // PostgreSQL preserves physical identifier case; special/reserved names in
  // other dialects still need delimiters even when ordinary names remain plain.
  return `"${name.replace(/"/g, '""')}"`;
}
function ownTable(tables: SqlTables | undefined, key: string) { return tables && Object.hasOwn(tables, key) ? tables[key] : undefined; }
function tableParts(key: string, context: CompletionContext | undefined): string[] {
  const metadata=ownTable(context?.schemaSnapshot?.tables,key),name=metadata?.name;
  if(!name)return key.split(".");
  const prefix=key===name?"":key.endsWith(`.${name}`)?key.slice(0,-name.length-1):metadata.schema??"";
  const schema=metadata.schema;
  return schema&&(prefix===schema||prefix.endsWith(`.${schema}`))
    ? [...(prefix===schema?[]:metadata.catalog?[metadata.catalog]:prefix.slice(0,-schema.length-1).split(".")),schema,name]
    : [...(prefix?prefix.split("."):[]),name];
}
function sameNamespace(left:string|undefined,right:string|undefined,dbType?:string):boolean {
  return Boolean(left&&right)&&(dbType==="postgresql"?left===right:left!.toLowerCase()===right!.toLowerCase());
}
function tableNamespace(key:string,context:CompletionContext|undefined) {
  const metadata=ownTable(context?.schemaSnapshot?.tables,key),parts=tableParts(key,context);
  return {parts,name:metadata?.name??parts.at(-1)!,schema:metadata?.schema??parts.at(-2),
    catalog:metadata?.catalog??(parts.length===3?parts[0]:undefined),temporary:metadata?.temporary};
}
type SqlTables = NonNullable<NonNullable<CompletionContext["schemaSnapshot"]>["tables"]>;
type NameLookup = Map<string, string | string[]>;
interface SearchName { key: string; folded: string; bare: string; order: number }
interface SqlIndex {
  tables: SqlTables; names: string[]; extras: Set<string>;
  bare?: NameLookup; foldedBare?: NameLookup; foldedRoots?: NameLookup; foldedFull?: NameLookup;
  search?: { names: SearchName[]; full: SearchName[]; bare: SearchName[] };
  matches: Map<string, string[]>;
  items: Map<string, Map<string, LanguageCompletion>>;
}
const EMPTY_SQL_TABLES: SqlTables = {}, EMPTY_SQL_NAMES: string[] = [];
// Namespace changes replace CompletionContext objects but retain immutable SQL
// metadata. Share the index by those sources, rather than rebuilding 100k items.
const sqlContextCache = new WeakMap<object, WeakMap<object, SqlIndex>>();
function sqlContext(context?: CompletionContext): SqlIndex {
  const tables = context?.schemaSnapshot?.tables ?? EMPTY_SQL_TABLES, additional = context?.tables ?? EMPTY_SQL_NAMES;
  let variants = sqlContextCache.get(tables);
  if (!variants) { variants = new WeakMap(); sqlContextCache.set(tables, variants); }
  let value = variants.get(additional);
  if (value) return value;
  const names = Object.keys(tables), extras = new Set<string>();
  for (const name of additional) if (!Object.hasOwn(tables, name) && !extras.has(name)) { extras.add(name); names.push(name); }
  value = { tables, names, extras, items: new Map(), matches: new Map() }; variants.set(additional, value); return value;
}
function addName(index: NameLookup, name: string, key: string) {
  const existing = index.get(name);
  if (existing === undefined) index.set(name, key);
  else if (typeof existing === "string") index.set(name, [existing, key]);
  else existing.push(key);
}
function lookupNames(index: NameLookup, name: string): string[] {
  const value = index.get(name); return value === undefined ? [] : typeof value === "string" ? [value] : value;
}
function bareNames(index: SqlIndex) {
  if (index.bare) return;
  const exact: NameLookup = new Map(), folded: NameLookup = new Map(), roots: NameLookup = new Map();
  for (const key of index.names) {
    const name = ownTable(index.tables, key)?.name ?? key.slice(key.lastIndexOf(".") + 1), lower = name.toLowerCase();
    addName(exact, name, key);
    // Already lowercase names use the exact map in both paths. Storing only
    // case variants avoids a second 100k-entry map for ordinary catalogs.
    if (name !== lower) addName(folded, lower, key);
    if (!key.includes(".") && key !== key.toLowerCase()) addName(roots, key.toLowerCase(), key);
  }
  index.bare = exact; index.foldedBare = folded; index.foldedRoots = roots;
}
function fullNames(index: SqlIndex) {
  if (!index.foldedFull) {
    index.foldedFull = new Map();
    for (const key of index.names) addName(index.foldedFull, key.toLowerCase(), key);
  }
  return index.foldedFull;
}
function resolveTable(name: string | undefined, context: CompletionContext | undefined, getIndex: () => SqlIndex): string | undefined {
  if (!name) return;
  const tables = context?.schemaSnapshot?.tables ?? {}, query = name.toLowerCase(), strictCase = (context?.dbType ?? context?.schemaSnapshot?.db_type) === "postgresql";
  if (Object.hasOwn(tables, name)) return name;
  const index = getIndex();
  if (index.extras.has(name)) return name;
  const database=context?.database??context?.schemaSnapshot?.database,
    qualified=name.includes(".")&&database?`${database}.${name}`:undefined;
  if(qualified&&(Object.hasOwn(tables,qualified)||index.extras.has(qualified)))return qualified;
  bareNames(index);
  const folded = strictCase ? [] : name.includes(".") ? [...lookupNames(fullNames(index),query),...(qualified?lookupNames(fullNames(index),qualified.toLowerCase()):[])]
    : [...(Object.hasOwn(tables, query) || index.extras.has(query) ? [query] : []), ...lookupNames(index.foldedRoots!, query)];
  if(folded.length)return folded.length===1?folded[0]:undefined;
  const chooseScope=(candidates:string[])=>{
    const temporary=candidates.filter(key=>ownTable(tables,key)?.temporary);
    if(temporary.length)return temporary.length===1?temporary[0]:undefined;
    const catalogOf=(key:string)=>tableNamespace(key,context).catalog;
    const selectedCatalog=context?.database ?? context?.schemaSnapshot?.database;
    if(selectedCatalog){const sameCatalog=candidates.filter(key=>!catalogOf(key)|| (strictCase?catalogOf(key)===selectedCatalog:catalogOf(key)?.toLowerCase()===selectedCatalog.toLowerCase()));if(sameCatalog.length)candidates=sameCatalog;}
    const schemaOf=(key:string)=>ownTable(tables,key)?.schema??key.split(".").at(-2),dbType=context?.dbType??context?.schemaSnapshot?.db_type,
      selectedSchema=context?.schema ?? context?.schemaSnapshot?.current_schema ?? ((dbType==="mysql"||dbType==="mariadb")?selectedCatalog:undefined);
    if(selectedSchema!==undefined){
      const exactScope=candidates.filter(key=>schemaOf(key)===selectedSchema);
      if(exactScope.length)return exactScope.length===1?exactScope[0]:undefined;
      const foldedScope=strictCase?[]:candidates.filter(key=>schemaOf(key)?.toLowerCase()===selectedSchema.toLowerCase());
      if(foldedScope.length)return foldedScope.length===1?foldedScope[0]:undefined;
    }
    return candidates.length===1?candidates[0]:undefined;
  };
  const exactBare = lookupNames(index.bare!, name);
  return exactBare.length ? chooseScope(exactBare) : strictCase ? undefined
    : chooseScope([...lookupNames(index.bare!, query), ...lookupNames(index.foldedBare!, query)]);
}

function searchNames(index: SqlIndex) {
  if (!index.search) {
    const names = index.names.map((key, order) => ({ key, order, folded: key.toLowerCase(), bare: key.slice(key.lastIndexOf(".") + 1).toLowerCase() }));
    const compare = (field: "folded" | "bare") => (a: SearchName, b: SearchName) => a[field] < b[field] ? -1 : a[field] > b[field] ? 1 : a.order - b.order;
    index.search = { names, full: names.slice().sort(compare("folded")), bare: names.slice().sort(compare("bare")) };
  }
  return index.search;
}
function prefixRange(names: SearchName[], query: string, field: "folded" | "bare") {
  const bound = (after: boolean) => {
    let start = 0, end = names.length;
    while (start < end) {
      const middle = (start + end) >>> 1, value = names[middle][field];
      if (value < query || after && value.startsWith(query)) start = middle + 1; else end = middle;
    }
    return start;
  };
  return { start: bound(false), end: bound(true) };
}
/** Filter names first; construct and escape at most the visible 500 suggestions. */
function matchingTableNames(index: SqlIndex, prefix: string, qualifier?: string,strictNamespace=false,database?:string): string[] {
  const query=prefix.toLowerCase(),qualifiers=qualifier?[qualifier,...(database&&!qualifier.includes(".")?[`${database}.${qualifier}`]:[])]:[],
    namespaces=qualifiers.map(name=>`${name.toLowerCase()}.`);
  if (!query && !namespaces.length) return index.names.slice(0, 500);
  const cacheKey=JSON.stringify([query,namespaces,strictNamespace?qualifiers:undefined]),cached=index.matches.get(cacheKey);
  if(cached)return cached;
  const search=searchNames(index),fullQueries=namespaces.length?namespaces.map(namespace=>namespace+query):[query],
    full=fullQueries.map(value=>prefixRange(search.full,value,"folded")),bare=query?prefixRange(search.bare,query,"bare"):{start:0,end:0};
  const inNamespace=(entry:SearchName)=>!namespaces.length||qualifiers.some((value,index)=>strictNamespace?entry.key.startsWith(`${value}.`):entry.folded.startsWith(namespaces[index]));
  const matches = (entry: SearchName) => inNamespace(entry)
    && (!query || fullQueries.some(value=>entry.folded.startsWith(value)) || entry.bare.startsWith(query));
  let result:string[];
  if (full.reduce((count,range)=>count+range.end-range.start,0) + bare.end - bare.start > 5_000) {
    // Broad matches need only the first 500 in metadata order, without
    // collecting or sorting an entire matching namespace on each key.
    result = [];
    for (const entry of search.names) if (matches(entry)) { result.push(entry.key); if (result.length === 500) break; }
  }else{
    const candidates = new Map<number, SearchName>();
    for(const range of full)for (let index = range.start; index < range.end; index++) { const entry = search.full[index]; if (matches(entry)) candidates.set(entry.order, entry); }
    for (let index = bare.start; index < bare.end; index++) { const entry = search.bare[index]; if (matches(entry)) candidates.set(entry.order, entry); }
    result=[...candidates.values()].sort((a, b) => a.order - b.order).slice(0, 500).map(entry => entry.key);
  }
  // SQL object search also accepts an embedded word (ft_movimentos_premio),
  // while keeping exact/prefix matches ahead of those broader matches. Cache
  // the bounded result so opening/enriching a widget never rescans a catalog.
  if(query.length>1&&result.length<500){
    const seen=new Set(result);
    for(const entry of search.names)if(inNamespace(entry)&&entry.bare.includes(query)&&!seen.has(entry.key)){
      result.push(entry.key);if(result.length===500)break;
    }
  }
  index.matches.set(cacheKey,result);
  while(index.matches.size>64)index.matches.delete(index.matches.keys().next().value!);
  return result;
}
function qualifierTail(parts:string[],qualifier:string,dbType:string|undefined,database:string|undefined):string[]|undefined {
  const starts=parts.length===3&&sameNamespace(parts[0],database,dbType)?[0,1]:[0];
  for(const start of starts)for(let count=start+1;count<parts.length;count++)
    if(sameNamespace(parts.slice(start,count).join("."),qualifier,dbType))return parts.slice(count);
}
function focusedParts(parts:string[],schema:string|undefined,catalog:string|undefined,temporary:boolean|undefined,
  context:CompletionContext|undefined,canUseBare:boolean,qualifier?:string,insertion=true):string[]{
  const dbType=context?.dbType??context?.schemaSnapshot?.db_type;
  if(qualifier)return qualifierTail(parts,qualifier,dbType,context?.database??context?.schemaSnapshot?.database)??parts;
  const name=parts.at(-1)!,database=context?.database??context?.schemaSnapshot?.database,
    selectedSchema=context?.schema||context?.schemaSnapshot?.current_schema;
  const inDatabase=!catalog||sameNamespace(catalog,database,dbType),inScope=temporary||
    ((dbType==="mysql"||dbType==="mariadb")?sameNamespace(schema,database,dbType):sameNamespace(schema,selectedSchema,dbType));
  // A SQL Server schema picker cannot alter a login's physical default schema.
  // Only its actual default can omit the schema; explicit typed qualifiers own it.
  const needsSchema=insertion&&(dbType==="sqlserver"||dbType==="mssql")&&Boolean(schema)&&
    !sameNamespace(schema,context?.schemaSnapshot?.default_schema??"dbo",dbType);
  // A short name must resolve to this exact object in the focused namespace.
  // Other schemas/catalogs and shadowed permanent tables retain qualification.
  if(parts.length===1)return needsSchema?[schema!,name]:parts;
  if(parts.length<=3&&!needsSchema&&inDatabase&&inScope&&canUseBare)return [name];
  if(parts.length===3&&sameNamespace(parts[0],database,dbType))return parts.slice(1);
  return parts;
}
function namedTableCompletion(parts:string[],detail:string,dbType?:string,displayParts=parts):LanguageCompletion {
  const label=displayParts.join(".");
  return {label,kind:"table",detail:"table",documentation:detail,insert_text:parts.map(part=>quoteSqlPart(part,dbType)).join("."),filterText:label,sortText:`0:${displayParts.length===1?"0":"1"}:${label}`};
}
function tableDocumentation(path:string,documentation?:string):string {
  return documentation?documentation.includes(path)?documentation:`${documentation}\n\n${path}`:path;
}
function tableCompletion(key:string,context:CompletionContext|undefined,getIndex:()=>SqlIndex,qualifier?:string):LanguageCompletion{
  const {parts,name,schema,catalog,temporary}=tableNamespace(key,context),canUseBare=resolveTable(name,context,getIndex)===key;
  return namedTableCompletion(focusedParts(parts,schema,catalog,temporary,context,canUseBare,qualifier),key,context?.dbType??context?.schemaSnapshot?.db_type,
    focusedParts(parts,schema,catalog,temporary,context,canUseBare,qualifier,false));
}
function completionIdentifierParts(item:LanguageCompletion):string[]|undefined {
  if(item.is_snippet)return;
  const inserted=identifierParts(item.insert_text??item.insertText??item.label),labelled=identifierParts(item.label);
  // A quoted literal dot belongs to one physical identifier, not a namespace.
  return (inserted&&(inserted.length>1||inserted[0].name.includes(".")||!labelled)?inserted:labelled??inserted)?.map(part=>part.name);
}
/** Remote inference must not restore fully qualified names after local results. */
export function contextualCompletions(items:LanguageCompletion[],site:CompletionSite,context:CompletionContext|undefined,language:Language,local:LanguageCompletion[]=[]):LanguageCompletion[]{
  if(language!=="sql")return items;
  let index:SqlIndex|undefined;const getIndex=()=>index??=sqlContext(context),dbType=context?.dbType??context?.schemaSnapshot?.db_type,
    qualifier=site.member?normalizedSqlName(site.memberParts,site.member,dbType):undefined;
  return items.flatMap(item=>{
    if(!site.member&&["column","field"].includes(item.kind?.toLowerCase()??"")){
      const qualified=local.filter(entry=>entry.kind==="column"&&entry.filterText===item.label&&entry.label!==item.label);
      if(qualified.length)return qualified.map(entry=>({...item,...entry,documentation:item.documentation}));
    }
    const kind=(item.kind??item.category)?.toLowerCase(),parts=completionIdentifierParts(item);
    if(kind!=="table")return parts&&["column","field","schema","database","catalog"].includes(kind??"")
      ? [{...item,insert_text:parts.map(part=>quoteSqlPart(part,dbType)).join(".")}] : [item];
    const raw=parts?.join(".")??item.label;
    const key=(qualifier?resolveTable(`${qualifier}.${raw}`,context,getIndex):undefined)??resolveTable(raw,context,getIndex);
    if(!key){
      if(!parts)return [item];
      // Inference may arrive before the immutable catalog. Qualified RPC names
      // still prove their namespace; never let enrichment restore a full prefix.
      if(qualifier&&parts.length>1&&!qualifierTail(parts,qualifier,dbType,context?.database??context?.schemaSnapshot?.database))return [];
      const name=parts.at(-1)!,resolved=resolveTable(name,context,getIndex),index=getIndex();bareNames(index);
      const known=index.bare!.has(name)||index.bare!.has(name.toLowerCase())||index.foldedBare!.has(name.toLowerCase());
      const schema=parts.at(-2)??(parts.length===1?context?.schema||context?.schemaSnapshot?.current_schema:undefined),
        catalog=parts.length===3?parts[0]:undefined;
      const canUseBare=!known||resolved===raw,focused=focusedParts(parts,schema,catalog,false,context,canUseBare,qualifier);
      return [{...item,...namedTableCompletion(focused,raw,dbType,focusedParts(parts,schema,catalog,false,context,canUseBare,qualifier,false)),documentation:tableDocumentation(raw,item.documentation)}];
    }
    if(qualifier){
      const parts=tableParts(key,context);
      if(!qualifierTail(parts,qualifier,dbType,context?.database??context?.schemaSnapshot?.database))return [];
    }
    return [{...item,...tableCompletion(key,context,getIndex,qualifier),documentation:tableDocumentation(key,item.documentation)}];
  });
}
function tableSuggestions(index: SqlIndex, context: CompletionContext | undefined, prefix: string, qualifier?: string) {
  const scope = JSON.stringify([context?.dbType ?? context?.schemaSnapshot?.db_type, context?.database ?? context?.schemaSnapshot?.database,
    context?.schema ?? context?.schemaSnapshot?.current_schema,context?.schemaSnapshot?.default_schema]);
  let cache = index.items.get(scope);
  if (!cache) {
    cache = new Map(); index.items.set(scope, cache);
    while (index.items.size > 8) index.items.delete(index.items.keys().next().value!);
  }
  return matchingTableNames(index,prefix,qualifier,(context?.dbType??context?.schemaSnapshot?.db_type)==="postgresql",context?.database??context?.schemaSnapshot?.database).map(key => {
    const itemKey = JSON.stringify([key, qualifier]), existing = cache!.get(itemKey);
    if (existing) return existing;
    const item=tableCompletion(key,context,()=>index,qualifier);
    cache!.set(itemKey, item);
    while (cache!.size > 2_048) cache!.delete(cache!.keys().next().value!);
    return item;
  });
}

export function localCompletions(language: Language, site: CompletionSite, context: CompletionContext | undefined,
  textBefore: string, currentSymbols: LanguageCompletion[] = [], documentSource = textBefore, sourceCursor?: number): LanguageCompletion[] {
  if (site.blocked) return [];
  const items: LanguageCompletion[] = [];
  if (language === "python") {
    if (site.member) {
      const variable = context?.variables.find(item => item.name === site.member);
      const library = variable?.type === "DataFrame" ? dataframeLibrary(variable) : undefined;
      if (site.stringColumn && ((library === "polars" && ["loc", "sort_values"].includes(site.columnContext ?? "")) || (library === "pandas" && site.columnContext === "sort"))) return [];
      if (library && !site.stringColumn) items.push(...dataframeMembers(library));
      for (const name of variable?.columns ?? []) if (site.stringColumn || (library !== "polars" && IDENTIFIER.test(name)&&!PYTHON_HARD_KEYWORDS.has(name)&&(!library||!dataframeMemberNames(library).has(name)))) items.push({ label: name, kind: "field", detail: `${site.member} column`, insert_text: name, sortText: `0:${name}` });
      return filterCompletions(items, site.prefix, language);
    }
    items.push(...(context?.variables ?? []).map(variable => ({ label: variable.name, kind: "variable", detail: variable.type, sortText: `0:${variable.name}` })), ...currentSymbols);
    items.push(...pythonContextSymbols(context));
    items.push(...PYTHON_KEYWORDS.map(label => ({ label, kind: "keyword", sortText: `2:${label}` })), ...PYTHON_BUILTINS.map(label => ({ label, kind: "function", sortText: `2:${label}` })));
  } else {
    const tables = context?.schemaSnapshot?.tables ?? {}, dbType = context?.dbType ?? context?.schemaSnapshot?.db_type;
    let index: SqlIndex | undefined;
    const getIndex = () => index ??= sqlContext(context);
    const prefixStart = documentSource.indexOf(textBefore);
    const scope = sqlCompletionScope(documentSource, sourceCursor ?? (prefixStart < 0 ? textBefore.length : prefixStart + textBefore.length), dbType, Boolean(site.quote));
    if (scope.blocked) return [];
    const relations = scope.relations.map(relation => ({ ...relation,
      name: normalizedSqlName(relation.parts, relation.parts.map(part => part.name).join("."), dbType),
      qualifier: relation.alias ? normalizedSqlName([relation.alias], relation.alias.name, dbType) : normalizedSqlName(relation.parts.slice(-1), relation.parts.at(-1)!.name, dbType),
    }));
    if (site.member) {
      const member = normalizedSqlName(site.memberParts, site.member, dbType);
      const binding = [...relations].reverse().find(relation => dbType === "postgresql" ? relation.qualifier === member : relation.qualifier.toLowerCase() === member.toLowerCase());
      // A CTE or derived table owns its alias even if a physical table shares its name.
      const tableName = binding ? binding.virtual ? undefined : resolveTable(binding.name, context, getIndex) : resolveTable(member, context, getIndex);
      const metadata = tableName && ownTable(tables, tableName);
      if (metadata) for (const column of metadata.columns ?? []) items.push({ label: column.name, kind: "column", detail: `${tableName} · ${column.data_type ?? column.type ?? ""}`, insert_text: quoteSqlPart(column.name, dbType), sortText: `0:${column.name}` });
      if (!metadata && !binding) items.push(...tableSuggestions(getIndex(), context, site.prefix, member));
      return filterCompletions(items, site.prefix, language);
    }
    const relation = /\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+[^\s]*$/i.test(scope.before);
    // Once metadata is loaded, SELECT/WHERE/ON suggestions never need an IPC
    // round trip for ordinary FROM/JOIN columns, including unqualified names.
    if (!relation && /\b(?:SELECT|WHERE|ON|HAVING|SET|(?:ORDER|GROUP|PARTITION)\s+BY)\b/i.test(scope.before)) {
      const sources=relations.map(visible=>{const name=!visible.virtual&&resolveTable(visible.name,context,getIndex);return {visible,name,metadata:name&&ownTable(tables,name)};});
      // An unloaded table or virtual relation can contain any of the known
      // names. Until inference supplies its output, keep a valid source alias.
      const unknownSource=sources.some(({metadata})=>!metadata||!metadata.columns?.length);
      const owners=new Map<string,number>(),columnKey=(name:string)=>dbType==="postgresql"?name:name.toLowerCase();
      for(const {metadata} of sources)for(const column of metadata?metadata.columns??[]:[])owners.set(columnKey(column.name),(owners.get(columnKey(column.name))??0)+1);
      for (const {visible,name,metadata} of sources) {
        for (const column of metadata ? metadata.columns ?? [] : []) {
          const detail = `${name} · ${column.data_type ?? column.type ?? ""}`;
          if(unknownSource||(owners.get(columnKey(column.name))??0)>1)items.push({label:`${visible.qualifier}.${column.name}`,filterText:column.name,kind:"column",detail,
            insert_text:`${quoteSqlPart(visible.qualifier,dbType)}.${quoteSqlPart(column.name,dbType)}`,sortText:`0:${column.name}:${visible.qualifier}`});
          else items.push({ label: column.name, kind: "column", detail, insert_text: quoteSqlPart(column.name, dbType), sortText: `0:${column.name}` });
        }
      }
    } else items.push(...tableSuggestions(getIndex(), context, site.prefix));
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
  const matching: LanguageCompletion[] = [];
  for (const item of items) {
    const label = item.filterText ?? item.label, candidate = language === "sql" ? label.toLowerCase() : label;
    if (!query || candidate.startsWith(query) || (language === "sql" && (candidate.slice(candidate.lastIndexOf(".")+1).startsWith(query) || query.length>1&&candidate.includes(query)))) {
      matching.push(item); if (matching.length === 500) break;
    }
  }
  return matching;
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
