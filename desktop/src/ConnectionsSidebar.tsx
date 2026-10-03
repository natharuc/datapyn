import { translate as t, useLocale } from "./i18n";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ChevronDown, ChevronRight, Copy, Database, Download, Folder, FolderPlus, LoaderCircle, Pencil, Plug, RefreshCw, Search, Settings2, Star, Trash2, Upload, X } from "lucide-react";
import { open, save } from "@tauri-apps/plugin-dialog";
import { connections, connectionRows, effectiveConnectionColor, effectiveGroupColor, groupDescendants, CONNECTION_MIME, GROUP_MIME, type ConnectionGroup, type ConnectionTreeRow, type SavedConnection, type ConnectionsController } from "./connections";
import { ConnectionDialog } from "./ConnectionDialog";
import { Modal } from "./PanelControls";
import { errorText, isDesktop } from "./runtime";
import "./connections.css";

export interface ConnectionsSidebarProps {
  activeConnectionId?: string; onConnect: (connection: SavedConnection, newTab?: boolean) => Promise<void> | void;
  onDisconnect?: () => Promise<void> | void; onError?: (message: string) => void; disabled?: boolean;
  controller?: ConnectionsController; compact?: boolean;
}

function readExpanded(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem("datapyn.desktop.connection-groups.v1") ?? "[]")); } catch { return new Set(); }
}

export function ConnectionsSidebar({ activeConnectionId, onConnect, onDisconnect, onError, disabled = false, controller = connections, compact = false }: ConnectionsSidebarProps) {
  useLocale();
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  const [query, setQuery] = useState(""), [favorites, setFavorites] = useState(false), [expanded, setExpanded] = useState(readExpanded);
  const [selected, setSelected] = useState<string>(), [menu, setMenu] = useState<ConnectionTreeRow>(), [edit, setEdit] = useState<SavedConnection | "new">();
  const [groupEdit, setGroupEdit] = useState<ConnectionGroup | "new">(), [deleting, setDeleting] = useState<ConnectionTreeRow>();
  const [manager, setManager] = useState(false), [busy, setBusy] = useState(false), [scroll, setScroll] = useState(0), [height, setHeight] = useState(320);
  const viewport = useRef<HTMLDivElement>(null), tree = useRef<HTMLDivElement>(null);
  const rows = useMemo(() => connectionRows(state.catalog, expanded, query, favorites), [state.catalog, expanded, query, favorites]);
  useEffect(() => { void controller.ensureLoaded(); }, [controller]);
  useEffect(() => { const element = viewport.current; if (!element) return; const observer = new ResizeObserver(([entry]) => setHeight(entry.contentRect.height)); observer.observe(element); return () => observer.disconnect(); }, []);
  useEffect(() => { try { localStorage.setItem("datapyn.desktop.connection-groups.v1", JSON.stringify([...expanded])); } catch { /* Optional view preference. */ } }, [expanded]);
  useEffect(() => { if (!state.loaded) return; setExpanded((prior) => new Set([...prior, ...state.catalog.groups.filter((group) => !group.parent_id).map((group) => group.id)])); }, [state.loaded]);
  const rowHeight = 32, first = Math.max(0, Math.floor(scroll / rowHeight) - 6), end = Math.min(rows.length, Math.ceil((scroll + height) / rowHeight) + 6);
  const active = state.catalog.connections.find((connection) => connection.id === activeConnectionId);
  const perform = async (task: () => Promise<unknown> | unknown) => {
    setBusy(true); try { await task(); } catch (failure) { onError?.(errorText(failure)); } finally { setBusy(false); }
  };
  const toggle = (id: string) => setExpanded((previous) => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  async function transfer(importing: boolean) {
    if (!isDesktop()) throw new Error(t("Importação e exportação estão disponíveis no desktop."));
    const options = { filters: [{ name: t("Conexões DataPyn"), extensions: ["json"] }] };
    const path = importing ? await open({ ...options, multiple: false }) : await save({ ...options, defaultPath: "datapyn-connections.json" });
    if (typeof path !== "string") return;
    await controller.mutate(importing ? "connections.import" : "connections.export", { path });
  }
  function keyboard(event: React.KeyboardEvent) {
    const index = rows.findIndex((row) => row.key === selected), current = rows[index];
    if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Home" || event.key === "End") {
      event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1 : Math.max(0, Math.min(rows.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)));
      setSelected(rows[next]?.key); if (viewport.current) { if (next * rowHeight < scroll) viewport.current.scrollTop = next * rowHeight; else if ((next + 1) * rowHeight > scroll + height) viewport.current.scrollTop = (next + 1) * rowHeight - height; }
    } else if (current?.group && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
      event.preventDefault(); if (expanded.has(current.group.id) !== (event.key === "ArrowRight")) toggle(current.group.id);
    } else if (current && event.key === "Enter") {
      event.preventDefault(); if (current.connection) void perform(() => onConnect(current.connection!, event.ctrlKey || event.metaKey)); else if (current.group) toggle(current.group.id);
    } else if (current && (event.key === "F2" || event.key === "Delete" || (event.shiftKey && event.key === "F10"))) {
      event.preventDefault(); if (event.key === "Delete") setDeleting(current); else if (event.key === "F2") { if (current.connection) setEdit(current.connection); else if (current.group) setGroupEdit(current.group); } else setMenu(current);
    }
  }
  async function drop(event: React.DragEvent, target: ConnectionTreeRow | null) {
    event.preventDefault(); const connectionId = event.dataTransfer.getData(CONNECTION_MIME), groupId = event.dataTransfer.getData(GROUP_MIME);
    const groupTarget = target?.group?.id ?? target?.connection?.group_id ?? null;
    if (connectionId && target?.connection && connectionId !== target.connection.id) {
      const ordered = [...state.catalog.connections].sort((a, b) => a.order - b.order).map((connection) => connection.id).filter((id) => id !== connectionId);
      ordered.splice(ordered.indexOf(target.connection.id), 0, connectionId);
      await controller.mutate("connections.move", { connection_id: connectionId, group_id: groupTarget });
      await controller.mutate("connections.reorder", { connection_ids: ordered });
    } else if (connectionId) await controller.mutate("connections.move", { connection_id: connectionId, group_id: groupTarget });
    else if (groupId && groupId !== groupTarget) {
      const group = state.catalog.groups.find((item) => item.id === groupId);
      if (group && !groupDescendants(state.catalog.groups, groupId).has(groupTarget ?? "")) await controller.mutate("groups.save", { group: { ...group, parent_id: groupTarget } });
    }
    if (groupTarget) setExpanded((previous) => new Set([...previous, groupTarget]));
  }
  const selection = rows.find((row) => row.key === selected);
  return <section className={`connections-sidebar ${compact ? "compact" : ""}`} aria-label={t("Conexões")}>
    {!compact && <div className="connections-active"><Database size={17} style={{ color: active ? effectiveConnectionColor(active,state.catalog) : undefined }} /><div><strong>{active?.name ?? t("Conexão da sessão")}</strong><small>{active ? `${active.config.db_type} · ${active.config.database}` : t("Escolha uma conexão salva")}</small></div>{onDisconnect && activeConnectionId && <button className="icon-button" title={t("Desconectar")} aria-label={t("Desconectar")} disabled={disabled || busy} onClick={() => void perform(onDisconnect)}><X size={14} /></button>}</div>}
    <div className="connections-toolbar"><strong>{t("Conexões salvas")}</strong><button className="icon-button" title={t("Nova conexão")} aria-label={t("Nova conexão")} onClick={() => setEdit("new")}><Database size={14} /></button><button className="icon-button" title={t("Novo grupo")} aria-label={t("Novo grupo")} onClick={() => setGroupEdit("new")}><FolderPlus size={14} /></button><button className="icon-button" title={t("Gerenciar conexões")} aria-label={t("Gerenciar conexões")} onClick={() => setManager(true)}><Settings2 size={14} /></button><button className="icon-button" title={t("Atualizar conexões")} aria-label={t("Atualizar conexões")} onClick={() => void controller.refresh()} disabled={state.loading}><RefreshCw size={14} /></button></div>
    <div className="connections-search"><Search size={14} /><input aria-label={t("Buscar conexões")} value={query} onChange={(event) => { setQuery(event.target.value); if (viewport.current) viewport.current.scrollTop = 0; }} placeholder={t("Nome, servidor, banco ou grupo…")} /><button className={`icon-button ${favorites ? "selected" : ""}`} title={t("Mostrar favoritas")} aria-label={t("Mostrar favoritas")} aria-pressed={favorites} onClick={() => setFavorites(!favorites)}><Star size={14} fill={favorites ? "currentColor" : "none"} /></button></div>
    {state.error && <p className="catalog-error" role="alert">{t(state.error)}</p>}
    {state.loading && !state.loaded && <p className="catalog-empty"><LoaderCircle size={15} className="spin" /> {t("Carregando catálogo…")}</p>}
    <div className="connection-tree-viewport" ref={viewport} onScroll={(event) => setScroll(event.currentTarget.scrollTop)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => void perform(() => drop(event, null))}>
      <div ref={tree} role="tree" tabIndex={0} aria-label={t("Conexões salvas agrupadas")} aria-activedescendant={selected ? `connection-row-${selected}` : undefined} style={{ height: Math.max(rows.length * rowHeight, 32), position: "relative" }} onKeyDown={keyboard}>
        {rows.slice(first, end).map((row, offset) => <div id={`connection-row-${row.key}`} key={row.key} role="treeitem" aria-level={row.depth + 1} aria-selected={selected === row.key} aria-expanded={row.group ? expanded.has(row.group.id) || !!query : undefined} className={`connection-tree-row ${row.group ? "group" : "leaf"} ${selected === row.key ? "selected" : ""} ${activeConnectionId === row.connection?.id ? "active" : ""}`} style={{ position: "absolute", top: (first + offset) * rowHeight, height: rowHeight, paddingLeft: 8 + row.depth * 14,borderLeftColor:activeConnectionId===row.connection?.id&&row.connection?effectiveConnectionColor(row.connection,state.catalog):undefined }}
          title={row.connection ? `${row.connection.config.db_type}\n${row.connection.config.host}\n${row.connection.config.database}` : row.group?.name}
          draggable={!busy} onDragStart={(event) => { event.dataTransfer.effectAllowed = "copyMove"; if (row.connection) { event.dataTransfer.setData(CONNECTION_MIME, row.connection.id); event.dataTransfer.setData("application/x-connection-name", row.connection.name); } else if (row.group) event.dataTransfer.setData(GROUP_MIME, row.group.id); }}
          onDragOver={(event) => { event.preventDefault(); event.stopPropagation(); }} onDrop={(event) => { event.stopPropagation(); void perform(() => drop(event, row)); }}
          onClick={() => { setSelected(row.key); tree.current?.focus(); if (row.group) toggle(row.group.id); }} onDoubleClick={(event) => { if (row.connection && !disabled) void perform(() => onConnect(row.connection!, event.ctrlKey || event.metaKey)); }}
          onAuxClick={(event) => { if (event.button === 1 && row.connection && !disabled) { event.preventDefault(); void perform(() => onConnect(row.connection!, true)); } }} onContextMenu={(event) => { event.preventDefault(); setSelected(row.key); setMenu(row); }}>
          {row.group ? <>{expanded.has(row.group.id) || query ? <ChevronDown size={13} /> : <ChevronRight size={13} />}<Folder size={14} style={{ color: effectiveGroupColor(row.group,state.catalog) }} /><span>{row.group.name}</span></> : <><Database size={14} style={{ color: row.connection?effectiveConnectionColor(row.connection,state.catalog):undefined }} /><span>{row.connection?.name}</span>{row.connection?.favorite && <Star size={12} fill="currentColor" />}{activeConnectionId === row.connection?.id && <Plug size={12} />}</>}
        </div>)}
      </div>
      {!rows.length && !state.loading && <p className="catalog-empty">{query || favorites ? t("Nenhuma conexão corresponde ao filtro.") : t("Nenhuma conexão salva. Crie uma conexão ou importe o catálogo do DataPyn.")}</p>}
    </div>
    {edit && <ConnectionDialog mode="save" connectionId={edit === "new" ? undefined : edit.id} initial={edit === "new" ? undefined : { ...edit.config, name: edit.name }} initialGroupId={edit === "new" ? selection?.group?.id ?? null : edit.group_id} initialColor={edit === "new" ? undefined : edit.color} hasPassword={edit !== "new" && edit.has_password} groups={state.catalog.groups} onClose={() => setEdit(undefined)} onConnect={async (config, metadata) => { await controller.save({ id: edit === "new" ? undefined : edit.id, name: config.name!.trim(), config, group_id: metadata?.group_id ?? null, color: metadata?.color, favorite: edit !== "new" && edit.favorite }, config.password || undefined, metadata?.save_password); }} />}
    {groupEdit && <GroupDialog initial={groupEdit === "new" ? undefined : groupEdit} groups={state.catalog.groups} defaultParent={selection?.group?.id ?? null} onClose={() => setGroupEdit(undefined)} onSave={async (group) => { await controller.mutate("groups.save", { group }); setExpanded((prior) => new Set([...prior, ...(group.parent_id ? [group.parent_id] : [])])); }} />}
    {menu && <Modal title={menu.connection?.name ?? menu.group!.name} className="connection-action-menu" onClose={() => setMenu(undefined)}><div className="connection-actions">
      {menu.connection && <><button disabled={disabled} onClick={() => { setMenu(undefined); void perform(() => onConnect(menu.connection!)); }}><Plug size={15} />{t("Conectar nesta aba")}</button><button disabled={disabled} onClick={() => { setMenu(undefined); void perform(() => onConnect(menu.connection!, true)); }}><Database size={15} />{t("Conectar em nova aba")}</button><button onClick={() => { setEdit(menu.connection!); setMenu(undefined); }}><Pencil size={15} />{t("Editar conexão")}</button><button onClick={() => { const connection = menu.connection!; setMenu(undefined); void perform(() => controller.mutate("connections.clone", { connection_id: connection.id, name: t("{name} (cópia)",{name:connection.name}) })); }}><Copy size={15} />{t("Duplicar conexão")}</button><button onClick={() => { const connection = menu.connection!; setMenu(undefined); void perform(() => controller.save({ ...connection, favorite: !connection.favorite }, undefined, connection.has_password)); }}><Star size={15} />{menu.connection.favorite ? t("Remover favorita") : t("Marcar como favorita")}</button></>}
      {menu.group && <><button onClick={() => { setGroupEdit(menu.group!); setMenu(undefined); }}><Pencil size={15} />{t("Editar grupo e cor")}</button><button onClick={() => { setGroupEdit("new"); setSelected(menu.key); setMenu(undefined); }}><FolderPlus size={15} />{t("Criar subgrupo")}</button></>}
      <button className="danger" onClick={() => { setDeleting(menu); setMenu(undefined); }}><Trash2 size={15} />{menu.connection ? t("Excluir conexão") : t("Excluir grupo")}</button>
    </div></Modal>}
    {deleting && <Modal title={t("Excluir {kind}",{kind:deleting.connection?t("conexão"):t("grupo")})} onClose={() => setDeleting(undefined)}><p className="catalog-modal-copy">{deleting.connection ? t("Excluir “{name}” do catálogo?",{name:deleting.connection.name}) : t("Excluir “{name}”? As conexões e subgrupos serão movidos para o grupo pai.",{name:deleting.group!.name})}</p><footer className="modal-footer"><button className="secondary-button" onClick={() => setDeleting(undefined)}>{t("Cancelar")}</button><button className="primary-button" disabled={busy} onClick={() => void perform(async () => { await controller.mutate(deleting.connection ? "connections.delete" : "groups.delete", deleting.connection ? { connection_id: deleting.connection.id } : { group_id: deleting.group!.id }); setDeleting(undefined); })}>{t("Excluir")}</button></footer></Modal>}
    {manager && <Modal title={t("Gerenciar conexões")} className="connection-manager" onClose={() => setManager(false)}><p className="catalog-modal-copy">{t("Arraste conexões entre grupos, arraste grupos para criar subgrupos e use o menu de contexto para editar, duplicar ou excluir. Ctrl + duplo clique ou clique do meio abre uma nova aba.")}</p><div className="connection-manager-buttons"><button className="secondary-button" onClick={() => { setManager(false); setEdit("new"); }}><Database size={15} />{t("Nova conexão")}</button><button className="secondary-button" onClick={() => { setManager(false); setGroupEdit("new"); }}><FolderPlus size={15} />{t("Novo grupo")}</button><button className="secondary-button" disabled={busy} onClick={() => void perform(() => transfer(true))}><Upload size={15} />{t("Importar JSON do legado")}</button><button className="secondary-button" disabled={busy} onClick={() => void perform(() => transfer(false))}><Download size={15} />{t("Exportar sem senhas")}</button></div><p className="catalog-modal-copy">{state.catalog.connections.length} {t("conexões ·")} {state.catalog.groups.length} {t("grupos. Senhas permanecem no runtime e não são exportadas.")}</p><footer className="modal-footer"><button className="primary-button" onClick={() => setManager(false)}>{t("Concluído")}</button></footer></Modal>}
  </section>;
}

function GroupDialog({ initial, groups, defaultParent, onClose, onSave }: { initial?: ConnectionGroup; groups: ConnectionGroup[]; defaultParent: string | null; onClose: () => void; onSave: (group: { id?: string; name: string; parent_id: string | null; color: string }) => Promise<void> }) {
  useLocale();
  const [name, setName] = useState(initial?.name ?? ""), [parent, setParent] = useState(initial ? initial.parent_id : defaultParent), [color, setColor] = useState(initial?.color ?? ""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const forbidden = initial ? groupDescendants(groups, initial.id) : new Set<string>();
  return <Modal title={initial ? t("Editar grupo") : t("Novo grupo")} onClose={() => { if (!busy) onClose(); }}><form className="catalog-group-form" onSubmit={(event) => { event.preventDefault(); setBusy(true); void onSave({ id: initial?.id, name: name.trim(), parent_id: parent, color }).then(onClose, (failure) => setError(errorText(failure))).finally(() => setBusy(false)); }}><label className="field">{t("Nome")}<input required value={name} onChange={(event) => setName(event.target.value)} /></label><label className="field">{t("Grupo pai")}<select value={parent ?? ""} onChange={(event) => setParent(event.target.value || null)}><option value="">{t("Raiz")}</option>{groups.filter((group) => !forbidden.has(group.id)).map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label><label className="field">{t("Cor")}<input type="color" disabled={!color} value={color||"#dcdc8b"} onChange={(event) => setColor(event.target.value)} /></label><label className="checkbox-field"><input type="checkbox" checked={!color} onChange={event=>setColor(event.target.checked?"":"#dcdc8b")}/>{t("Herdar cor do grupo pai")}</label>{error && <p className="form-error" role="alert">{t(error)}</p>}<footer className="modal-footer"><button type="button" className="secondary-button" disabled={busy} onClick={onClose}>{t("Cancelar")}</button><button className="primary-button" disabled={busy || !name.trim()}>{t("Salvar grupo")}</button></footer></form></Modal>;
}

export function ConnectionPicker({ title = t("Escolher conexão"), currentId, onSelect, onDefault, onClose }: { title?: string; currentId?: string; onSelect: (connection: SavedConnection) => Promise<void> | void; onDefault?: () => void; onClose: () => void }) {
  useLocale();
  const [error, setError] = useState("");
  return <Modal title={title} className="connection-picker" onClose={onClose}>{onDefault && <button className="secondary-button picker-default" onClick={() => { onDefault(); onClose(); }}>{t("Usar conexão padrão da aba")}</button>}{error && <p className="catalog-error" role="alert">{t(error)}</p>}<ConnectionsSidebar compact activeConnectionId={currentId} onConnect={async (connection) => { await onSelect(connection); onClose(); }} onError={setError} /></Modal>;
}
