import { runtime, type RuntimeTransport } from "./runtime";
export interface ExplorerContext { database?: string; schema?: string }
export interface ExplorerNode extends ExplorerContext { id: string; name: string; kind: string; has_children: boolean; qualified_name?: string; data_type?: string; nullable?: boolean; [key: string]: unknown }
export interface ExplorerResult { nodes: ExplorerNode[]; context?: ExplorerContext }
export interface ExplorerDetails { columns?: Array<Record<string, unknown>>; indexes?: Array<Record<string, unknown>>; keys?: Array<Record<string, unknown>>; definition?: string; [key: string]: unknown }
export interface ExplorerScope extends ExplorerContext { session_id: string; block_id?: string; scope_inherited?: boolean; connection_id?: string }

export class ExplorerController {
  private generation = 0;
  private scope?: ExplorerScope;
  private cache = new Map<string, ExplorerNode[]>();
  private pending = new Map<string, Promise<ExplorerNode[]>>();
  constructor(private transport: RuntimeTransport = runtime) {}
  setScope(scope: ExplorerScope) {
    if (JSON.stringify(this.scope) !== JSON.stringify(scope)) { this.scope = scope; this.clear(); }
  }
  clear() { ++this.generation; this.cache.clear(); this.pending.clear(); }
  async list(node?: ExplorerNode, refresh = false): Promise<ExplorerNode[]> {
    if (!this.scope) return [];
    const key = node?.id ?? "$root";
    if (!refresh && this.cache.has(key)) return this.cache.get(key)!;
    if (!refresh && this.pending.has(key)) return this.pending.get(key)!;
    const generation = this.generation, scope = this.scope;
    const request = this.transport.request<ExplorerResult>("explorer.list", { ...scope, node, refresh }).then((result) => {
      // Late metadata from the previously connected database must never appear in the new tree.
      if (generation !== this.generation) return [];
      const nodes=(result.nodes??[]).map(node=>node.kind==="column"?{...node,data_type:String(node.data_type??node.dtype??node.type??"")}:node);
      this.cache.set(key,nodes); return nodes;
    }).finally(() => { if (generation === this.generation) this.pending.delete(key); });
    this.pending.set(key, request); return request;
  }
}

/** Refresh only branches the user opened, retaining stable IDs and rejecting context changes. */
export async function reloadExpanded(controller:ExplorerController,expanded:Set<string>,isCurrent:()=>boolean) {
  controller.clear();
  const roots=await controller.list(undefined,true);if(!isCurrent())return;
  const children:Record<string,ExplorerNode[]>={},queue=[...roots],seen=new Set<string>(),kept=new Set<string>();
  while(queue.length){const node=queue.shift()!;if(seen.has(node.id))continue;seen.add(node.id);
    if(!expanded.has(node.id)||!node.has_children)continue;kept.add(node.id);
    const nodes=await controller.list(node,true);if(!isCurrent())return;
    children[node.id]=nodes;queue.push(...nodes);
  }
  return {roots,children,expanded:kept};
}

/** Split already quoted names without confusing a dot inside a quoted identifier. */
export function identifierParts(name: string): string[] {
  const parts: string[] = []; let part = "", quote = "";
  for (let index = 0; index < name.length; index++) {
    const character = name[index];
    if (quote) {
      const end = quote === "[" ? "]" : quote;
      if (character === end) { if (name[index + 1] === end) { part += end; index++; } else quote = ""; } else part += character;
    } else if (["[", '"', "`"].includes(character)) quote = character;
    else if (character === ".") { parts.push(part); part = ""; } else part += character;
  }
  parts.push(part); return parts;
}
export function quoteIdentifier(name: string, dbType: string = "sqlserver"): string {
  return identifierParts(name).map((part) => dbType === "sqlserver" ? `[${part.replaceAll("]", "]]" )}]` : ["mysql", "mariadb", "databricks"].includes(dbType) ? `\`${part.replaceAll("`", "``")}\`` : `"${part.replaceAll('"', '""')}"`).join(".");
}
export function quoteIdentifierPart(name: string, dbType: string = "sqlserver"): string { return quoteIdentifier(`"${name.replaceAll('"', '""')}"`, dbType); }
export function explorerRows(roots: ExplorerNode[], children: Record<string, ExplorerNode[]>, expanded: Set<string>, query: string): Array<{ node: ExplorerNode; depth: number }> {
  const search = query.trim().toLocaleLowerCase(), rows: Array<{ node: ExplorerNode; depth: number }> = [], visited = new Set<string>();
  function matches(node: ExplorerNode, seen = new Set<string>()): boolean {
    if (!search || node.name.toLocaleLowerCase().includes(search) || String(node.qualified_name ?? "").toLocaleLowerCase().includes(search)) return true;
    if (seen.has(node.id)) return false;
    seen.add(node.id); return (children[node.id] ?? []).some((child) => matches(child, seen));
  }
  function visit(nodes: ExplorerNode[], depth: number) {
    for (const node of nodes) {
      if (visited.has(node.id) || !matches(node)) continue;
      visited.add(node.id); rows.push({ node, depth });
      if (expanded.has(node.id) || search) visit(children[node.id] ?? [], depth + 1);
    }
  }
  visit(roots, 0); return rows;
}
