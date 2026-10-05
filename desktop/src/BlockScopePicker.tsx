import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, LoaderCircle, RefreshCw, Search } from "lucide-react";
import { translate as t, useLocale } from "./i18n";
import { errorText } from "./runtime";
import { observeElementDocument } from "./documentWindows";
import { contextMenuPosition } from "./contextMenuModel";
import { blockScopeOptions, filterScopeOptions, hasSchemaScope, scopeListWindow, scopeOptionIndex,
  type BlockScope, type ScopeField, type ScopeOptions } from "./blockScopeModel";
import type { ExplorerContext } from "./explorer";
import "./blockScopePicker.css";

export interface BlockScopePickerProps {
  sessionId: string;
  blockId?: string;
  scopeInherited?: boolean;
  connectionId?: string;
  dbType?: string;
  database?: string;
  schema?: string;
  connected?: boolean;
  disabled?: boolean;
  refresh?: number;
  showSchema?: boolean;
  onChange: (context: ExplorerContext, field: ScopeField) => Promise<void> | void;
  onError?: (message: string) => void;
}

interface ScopePopover {
  field: ScopeField;
  owner: Document;
  button: HTMLButtonElement;
}

/** Database and schema remain visible; metadata is fetched only when the picker opens. */
export function BlockScopePicker({ sessionId, blockId, scopeInherited, connectionId, dbType, database, schema,
  connected = true, disabled = false, refresh = 0, showSchema = hasSchemaScope(dbType), onChange, onError }: BlockScopePickerProps) {
  useLocale();
  const container = useRef<HTMLDivElement>(null);
  const selectedTrigger = useRef<HTMLButtonElement>();
  const [popover, setPopover] = useState<ScopePopover>();
  const [selecting, setSelecting] = useState(false);
  const scope = useMemo<BlockScope>(() => ({ session_id: sessionId, block_id: blockId, ...(blockId || scopeInherited!==undefined?{scope_inherited:Boolean(scopeInherited)}:{}),connection_id: connectionId,
    db_type: dbType, database, schema, revision: refresh }), [sessionId, blockId, scopeInherited, connectionId, dbType, database, schema, refresh]);
  useEffect(() => { setPopover(undefined); }, [sessionId, connectionId, database, schema, disabled, connected]);
  useEffect(() => {
    const element = container.current;
    return element ? observeElementDocument(element, () => setPopover(undefined)) : undefined;
  }, []);
  useLayoutEffect(() => {
    if (selecting) return;
    const button = selectedTrigger.current; selectedTrigger.current = undefined;
    // Applying a context temporarily disables its trigger. Restore focus once
    // it is enabled, unless the user has already moved to another control.
    if (button?.isConnected && !button.disabled && button.ownerDocument.activeElement === button.ownerDocument.body) {
      button.focus({ preventScroll: true });
    }
  }, [selecting]);
  const databaseLabel = dbType === "databricks" ? t("Catálogo") : t("Banco");
  const schemaLabel = schema === "" ? t("Nenhum") : schema ?? t("Padrão");
  async function select(value: string, field: ScopeField) {
    selectedTrigger.current = popover?.button;
    setPopover(undefined); setSelecting(true);
    try {
      await onChange(field === "database" ? { database: value } : { database, schema: value }, field);
    } catch (failure) { onError?.(errorText(failure)); }
    finally { setSelecting(false); }
  }
  function trigger(field: ScopeField, event: React.MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();
    const button = event.currentTarget;
    setPopover(prior => prior?.field === field ? undefined : { field, owner: button.ownerDocument, button });
  }
  return <div className="block-scope-picker" ref={container}>
    {dbType === "sqlite" ? <span className="block-scope-current" title={`${databaseLabel}: ${database || ":memory:"}`}>
      <span className="block-scope-label">{databaseLabel}</span><span className="block-scope-value">{database?.split(/[\\/]/).at(-1) || ":memory:"}</span>
    </span> : <button type="button" className="block-scope-trigger" disabled={disabled || !connected || selecting}
      aria-label={t("Selecionar {label}", { label: databaseLabel })} aria-haspopup="listbox" aria-expanded={popover?.field === "database"}
      title={`${databaseLabel}: ${database || t("Padrão")}`} onClick={event => trigger("database", event)}>
      <span className="block-scope-label">{databaseLabel}</span><span className="block-scope-value">{database || t("Padrão")}</span><ChevronDown size={11} />
    </button>}
    {showSchema && <button type="button" className="block-scope-trigger" disabled={disabled || !connected || selecting}
      aria-label={t("Selecionar schema")} aria-haspopup="listbox" aria-expanded={popover?.field === "schema"}
      title={`${t("Schema")}: ${schemaLabel}`} onClick={event => trigger("schema", event)}>
      <span className="block-scope-label">{t("Schema")}</span><span className="block-scope-value">{schemaLabel}</span><ChevronDown size={11} />
    </button>}
    {popover && <ScopeSearchPopover key={`${popover.field}:${sessionId}:${connectionId}`} host={popover}
      scope={scope} label={popover.field === "database" ? databaseLabel : t("Schema")}
      current={popover.field === "database" ? database : schema} onSelect={value => void select(value, popover.field)}
      onClose={() => setPopover(undefined)} />}
  </div>;
}

function ScopeSearchPopover({ host, scope, label, current, onSelect, onClose }: {
  host: ScopePopover; scope: BlockScope; label: string; current?: string;
  onSelect: (name: string) => void; onClose: () => void;
}) {
  const [result, setResult] = useState<ScopeOptions>(), [loading, setLoading] = useState(true), [error, setError] = useState("");
  const [query, setQuery] = useState(""), [active, setActive] = useState(-1), [scroll, setScroll] = useState(0), [height, setHeight] = useState(224);
  const [position, setPosition] = useState({ left: -10_000, top: -10_000 });
  const panel = useRef<HTMLDivElement>(null), search = useRef<HTMLInputElement>(null), viewport = useRef<HTMLDivElement>(null);
  const requestVersion = useRef(0), onCloseRef = useRef(onClose), restoreFocus = useRef(true); onCloseRef.current = onClose;
  const id = useId().replace(/:/g, ""), listId = `block-scope-list-${id}`;
  const options = useMemo(() => filterScopeOptions(result?.options ?? [], query), [result, query]);
  const { first, end } = scopeListWindow(options.length, scroll, height);
  async function load(force = false) {
    const revision = ++requestVersion.current;
    setLoading(true); setError("");
    try {
      const value = await blockScopeOptions.list(scope, host.field, force);
      if (requestVersion.current === revision) setResult(value);
    } catch (failure) { if (requestVersion.current === revision) setError(errorText(failure)); }
    finally { if (requestVersion.current === revision) setLoading(false); }
  }
  useEffect(() => {
    setResult(undefined); void load();
    return () => { ++requestVersion.current; };
  }, [scope, host.field]);
  useLayoutEffect(() => {
    search.current?.focus({ preventScroll: true });
    return () => {
      if (restoreFocus.current && !host.owner.defaultView?.closed && host.button.isConnected) host.button.focus({ preventScroll: true });
    };
  }, [host]);
  useLayoutEffect(() => {
    const window = host.owner.defaultView;
    const update = () => {
      const button = host.button.getBoundingClientRect(), bounds = panel.current?.getBoundingClientRect();
      if (!bounds) return;
      const next = contextMenuPosition({ x: button.left, y: button.bottom + 4 }, bounds,
        { width: window?.innerWidth ?? host.owner.documentElement.clientWidth, height: window?.innerHeight ?? host.owner.documentElement.clientHeight });
      setPosition(prior => prior.left === next.left && prior.top === next.top ? prior : next);
    };
    const Resize = (window as (Window & typeof globalThis) | null)?.ResizeObserver;
    const resize = Resize ? new Resize(() => { update(); if (viewport.current) setHeight(viewport.current.clientHeight); }) : undefined;
    if (panel.current) resize?.observe(panel.current);
    if (viewport.current) resize?.observe(viewport.current);
    update(); window?.addEventListener("resize", update);
    return () => { resize?.disconnect(); window?.removeEventListener("resize", update); };
  }, [host]);
  useEffect(() => {
    const close = (restore = false) => { restoreFocus.current = restore; onCloseRef.current(); };
    const outside = (event: PointerEvent) => {
      if (!panel.current?.contains(event.target as Node) && !host.button.contains(event.target as Node)) close();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(true); }
    };
    const scrollOutside = (event: Event) => { if (!panel.current?.contains(event.target as Node)) close(); };
    const leave = () => close();
    host.owner.addEventListener("pointerdown", outside, true);
    host.owner.addEventListener("keydown", escape, true);
    host.owner.addEventListener("scroll", scrollOutside, true);
    host.owner.defaultView?.addEventListener("blur", leave);
    host.owner.defaultView?.addEventListener("pagehide", leave);
    return () => {
      host.owner.removeEventListener("pointerdown", outside, true);
      host.owner.removeEventListener("keydown", escape, true);
      host.owner.removeEventListener("scroll", scrollOutside, true);
      host.owner.defaultView?.removeEventListener("blur", leave);
      host.owner.defaultView?.removeEventListener("pagehide", leave);
    };
  }, [host]);
  useEffect(() => {
    const selected = options.findIndex(option => option.name === current);
    setActive(selected >= 0 ? selected : options.length ? 0 : -1);
    if (viewport.current) viewport.current.scrollTop = selected >= 0 ? selected * 28 : 0;
  }, [options, current]);
  function move(index: number) {
    setActive(index);
    const view = viewport.current;
    if (!view || index < 0) return;
    if (index * 28 < view.scrollTop) view.scrollTop = index * 28;
    else if ((index + 1) * 28 > view.scrollTop + view.clientHeight) view.scrollTop = (index + 1) * 28 - view.clientHeight;
  }
  return createPortal(<div className="block-scope-popover" ref={panel} style={position}
    onClick={event => event.stopPropagation()} onKeyDown={event => {
      event.stopPropagation();
      if (event.target === search.current && (["ArrowDown", "ArrowUp"].includes(event.key) || ["Home", "End"].includes(event.key) && (event.ctrlKey || event.metaKey))) {
        event.preventDefault(); move(scopeOptionIndex(options.length, active, event.key));
      } else if (event.target === search.current && event.key === "Enter" && active >= 0 && !loading) { event.preventDefault(); onSelect(options[active].name); }
      else if (event.key === "Tab") {
        const buttons = Array.from(panel.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
        const focusable: HTMLElement[] = [search.current!, ...buttons].filter(Boolean);
        const index = focusable.indexOf(host.owner.activeElement as HTMLElement);
        if (event.shiftKey && index <= 0 || !event.shiftKey && index === focusable.length - 1) {
          event.preventDefault(); onClose();
        }
      }
    }}>
    <div className="block-scope-search"><Search size={13} /><input ref={search} role="combobox"
      aria-label={t("Pesquisar {label}", { label })} aria-autocomplete="list" aria-expanded="true" aria-controls={listId}
      aria-activedescendant={active >= first && active < end ? `${listId}-${active}` : undefined}
      placeholder={t("Pesquisar {label}…", { label: label.toLocaleLowerCase() })} value={query} onChange={event => setQuery(event.target.value)} />
      <button type="button" className="icon-button" title={t("Atualizar metadados")} aria-label={t("Atualizar metadados")}
        disabled={loading} onClick={() => void load(true)}><RefreshCw size={13} /></button>
    </div>
    {loading && <div className="block-scope-message" role="status"><LoaderCircle size={13} className="spin" />{t("Carregando…")}</div>}
    {error && <div className="block-scope-error" role="alert">{t(error)}<button type="button" onClick={() => void load(true)}>{t("Tentar novamente")}</button></div>}
    <div className="block-scope-list" ref={viewport} id={listId} role="listbox" aria-label={label} aria-busy={loading}
      onScroll={event => setScroll(event.currentTarget.scrollTop)} style={{ height: Math.min(224, options.length * 28) }}>
      <div style={{ height: options.length * 28, position: "relative" }}>
        {options.slice(first, end).map((option, offset) => {
          const index = first + offset;
          return <div key={option.name} id={`${listId}-${index}`} role="option" aria-selected={current === option.name}
            aria-posinset={index + 1} aria-setsize={options.length} title={option.name}
            className={`block-scope-option${active === index ? " active" : ""}${current === option.name ? " current" : ""}`}
            style={{ position: "absolute", top: index * 28, height: 28 }}
            onMouseEnter={() => setActive(index)} onMouseDown={event => event.preventDefault()}
            onClick={() => { if (!loading) onSelect(option.name); }}>{option.name}</div>;
        })}
      </div>
    </div>
    {!loading && !error && !options.length && <div className="block-scope-message">{t("Nenhum resultado.")}</div>}
  </div>, host.owner.body);
}
