import { runtime, errorText, type RuntimeTransport } from "./runtime";
import type { ConnectionConfig } from "./workspace";

export interface ConnectionGroup { id: string; name: string; parent_id: string | null; color: string; order: number }
export interface SavedConnection {
  id: string; name: string; group_id: string | null; color: string; favorite: boolean; order: number;
  config: ConnectionConfig; has_password: boolean; created_at?: string; last_used?: string;
}
export interface ConnectionCatalog { version: number; groups: ConnectionGroup[]; connections: SavedConnection[] }
export interface CatalogSnapshot { catalog: ConnectionCatalog; loading: boolean; error: string; loaded: boolean }
export const CONNECTION_MIME = "application/x-datapyn-connection";
export const GROUP_MIME = "application/x-datapyn-group";

/** Resolve the nearest explicit group color; malformed imported cycles cannot loop. */
export function effectiveGroupColor(group: ConnectionGroup | string, catalog: ConnectionCatalog): string | undefined {
  let current = typeof group === "string" ? catalog.groups.find(item => item.id === group) : group;
  const visited = new Set<string>();
  while (current && !visited.has(current.id)) {
    visited.add(current.id);
    const color = current.color?.trim(); if (color) return color;
    const parent = current.parent_id;
    current = parent ? catalog.groups.find(item => item.id === parent) : undefined;
  }
  return undefined;
}

/** A connection's own color wins; otherwise inherit its closest colored group ancestor. */
export function effectiveConnectionColor(connection: SavedConnection | string, catalog: ConnectionCatalog): string | undefined {
  const entry = typeof connection === "string" ? catalog.connections.find(item => item.id === connection) : connection;
  if (!entry) return undefined;
  return entry.color?.trim() || (entry.group_id ? effectiveGroupColor(entry.group_id, catalog) : undefined);
}

/** Credentials stay in the broker; only catalog metadata enters React state. */
export class ConnectionsController {
  private state: CatalogSnapshot = { catalog: { version: 1, groups: [], connections: [] }, loading: false, error: "", loaded: false };
  private listeners = new Set<() => void>();
  private generation = 0;
  private pending?: Promise<void>;
  constructor(private transport: RuntimeTransport) {}
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private update(patch: Partial<CatalogSnapshot>) { this.state = { ...this.state, ...patch }; this.listeners.forEach((listener) => listener()); }
  refresh() {
    const generation = ++this.generation;
    this.update({ loading: true, error: "" });
    const request = this.transport.request<ConnectionCatalog>("connections.list").then((catalog) => {
      if (generation === this.generation) this.update({ catalog, loading: false, loaded: true });
    }, (error) => { if (generation === this.generation) this.update({ loading: false, error: errorText(error) }); });
    this.pending = request;
    void request.finally(()=>{if(this.pending===request)this.pending=undefined;});
    return request;
  }
  ensureLoaded() { return this.state.loaded ? Promise.resolve() : this.pending ?? this.refresh(); }
  async mutate<T>(method: string, params: Record<string, unknown>) {
    // Invalidate a preceding read before mutation, otherwise its old data can win the race.
    ++this.generation;
    const result = await this.transport.request<T>(method, params);
    await this.refresh();
    return result;
  }
  save(connection: { id?: string; name: string; group_id?: string | null; color?: string; favorite?: boolean; config: ConnectionConfig }, password?: string, savePassword = false) {
    const { password: _secret, ...config } = connection.config;
    return this.mutate<SavedConnection>("connections.save", { connection: { ...connection, config }, password, save_password: savePassword });
  }
}
export const connections = new ConnectionsController(runtime);

export interface ConnectionTreeRow { key: string; depth: number; group?: ConnectionGroup; connection?: SavedConnection }
const compare = (a: { order: number; name: string }, b: { order: number; name: string }) => (a.order ?? 0) - (b.order ?? 0) || a.name.localeCompare(b.name);
export function connectionSearchText(connection: SavedConnection, groups: ConnectionGroup[]): string {
  const group = groups.find((item) => item.id === connection.group_id);
  const config = connection.config;
  return [connection.name, group?.name, config.host, config.database, config.db_type, config.username, config.port,
    config.http_path, connection.color, config.sqlserver_auth_mode, config.use_windows_auth ? "windows auth" : ""].filter(Boolean).join(" ").toLocaleLowerCase();
}

/** Flattens only visible nodes. Group cycles from old files cannot hang the interface. */
export function connectionRows(catalog: ConnectionCatalog, expanded: Set<string>, query = "", favorites = false): ConnectionTreeRow[] {
  const search = query.trim().toLocaleLowerCase();
  const filtered = catalog.connections.filter((connection) => (!favorites || connection.favorite) && (!search || connectionSearchText(connection, catalog.groups).includes(search)));
  const visibleGroups = new Set<string>();
  for (const connection of filtered) {
    let id = connection.group_id;
    const seen = new Set<string>();
    while (id && !seen.has(id)) { seen.add(id); visibleGroups.add(id); id = catalog.groups.find((group) => group.id === id)?.parent_id ?? null; }
  }
  const rows: ConnectionTreeRow[] = [], visited = new Set<string>();
  function visit(parentId: string | null, depth: number) {
    for (const group of catalog.groups.filter((item) => item.parent_id === parentId).sort(compare)) {
      if (visited.has(group.id) || ((search || favorites) && !visibleGroups.has(group.id))) continue;
      visited.add(group.id); rows.push({ key: `g:${group.id}`, group, depth });
      if (search || favorites || expanded.has(group.id)) visit(group.id, depth + 1);
    }
    for (const connection of filtered.filter((item) => item.group_id === parentId).sort(compare)) rows.push({ key: `c:${connection.id}`, connection, depth });
  }
  visit(null, 0);
  // Invalid imported parents are still discoverable and editable.
  for (const connection of filtered) if (!rows.some((row) => row.connection?.id === connection.id) && (!connection.group_id || !catalog.groups.some((group) => group.id === connection.group_id))) rows.push({ key: `c:${connection.id}`, connection, depth: 0 });
  return rows;
}

export function groupDescendants(groups: ConnectionGroup[], id: string): Set<string> {
  const descendants = new Set([id]);
  for (let changed = true; changed;) {
    changed = false;
    for (const group of groups) if (group.parent_id && descendants.has(group.parent_id) && !descendants.has(group.id)) { descendants.add(group.id); changed = true; }
  }
  return descendants;
}
