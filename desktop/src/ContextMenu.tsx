import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { contextMenuIndex, contextMenuPosition, type MenuPoint } from "./contextMenuModel";
import "./contextMenu.css";

export interface ContextMenuItem {
  id?: string;
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
  danger?: boolean;
  separator?: boolean;
  onSelect: () => void;
}

export function ContextMenu({ ownerDocument, anchor, returnFocus, label, items, onClose }: {
  ownerDocument: Document;
  anchor: MenuPoint;
  returnFocus?: HTMLElement | null;
  label: string;
  items: ContextMenuItem[];
  onClose: () => void;
}) {
  const menu = useRef<HTMLDivElement>(null), buttons = useRef<Array<HTMLButtonElement | null>>([]);
  const previous = useRef(returnFocus ?? ownerDocument.activeElement as HTMLElement | null);
  const closeHandler = useRef(onClose); closeHandler.current = onClose;
  const restoring = useRef(true), closed = useRef(false);
  const [position, setPosition] = useState({ left: -10_000, top: -10_000 });
  function close(restore = true) {
    if (closed.current) return;
    closed.current = true; restoring.current = restore; closeHandler.current();
  }

  useLayoutEffect(() => {
    closed.current = false; restoring.current = true;
    const index = contextMenuIndex(items.map(item => Boolean(item.disabled)), -1, "Home");
    (buttons.current[index] ?? menu.current)?.focus({ preventScroll: true });
    return () => {
      if (restoring.current && !ownerDocument.defaultView?.closed && previous.current?.isConnected) previous.current.focus({ preventScroll: true });
    };
  }, [ownerDocument, returnFocus]);

  useLayoutEffect(() => {
    const host = ownerDocument.defaultView;
    const update = () => {
      const bounds = menu.current?.getBoundingClientRect();
      if (!bounds) return;
      const next = contextMenuPosition(anchor, bounds, {
        width: host?.innerWidth ?? ownerDocument.documentElement.clientWidth,
        height: host?.innerHeight ?? ownerDocument.documentElement.clientHeight,
      });
      setPosition(previous => previous.left === next.left && previous.top === next.top ? previous : next);
    };
    update();
    const Resize = (host as (Window & typeof globalThis) | null)?.ResizeObserver;
    const observer = Resize ? new Resize(update) : undefined;
    if (menu.current) observer?.observe(menu.current);
    host?.addEventListener("resize", update);
    return () => { observer?.disconnect(); host?.removeEventListener("resize", update); };
  }, [ownerDocument, anchor.x, anchor.y]);

  useEffect(() => {
    const outside = (event: PointerEvent) => { if (!menu.current?.contains(event.target as Node)) close(false); };
    const scroll = (event: Event) => { if (!menu.current?.contains(event.target as Node)) close(false); };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
    };
    const leave = () => close(false);
    ownerDocument.addEventListener("pointerdown", outside, true);
    ownerDocument.addEventListener("scroll", scroll, true);
    ownerDocument.addEventListener("keydown", escape, true);
    ownerDocument.defaultView?.addEventListener("blur", leave);
    ownerDocument.defaultView?.addEventListener("pagehide", leave);
    return () => {
      ownerDocument.removeEventListener("pointerdown", outside, true);
      ownerDocument.removeEventListener("scroll", scroll, true);
      ownerDocument.removeEventListener("keydown", escape, true);
      ownerDocument.defaultView?.removeEventListener("blur", leave);
      ownerDocument.defaultView?.removeEventListener("pagehide", leave);
    };
  }, [ownerDocument]);

  return createPortal(<div ref={menu} className="datapyn-context-menu" role="menu" aria-label={label} tabIndex={-1}
    style={position} onClick={event=>event.stopPropagation()} onContextMenu={event => event.preventDefault()} onKeyDown={event => {
      // A menu consumes application shortcuts while preserving native button activation.
      event.stopPropagation();
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault(); event.stopPropagation();
        const current = buttons.current.findIndex(button => button === ownerDocument.activeElement);
        const next = contextMenuIndex(items.map(item => Boolean(item.disabled)), current, event.key);
        buttons.current[next]?.focus({ preventScroll: true });
      } else if (event.key === "Tab") { event.preventDefault(); event.stopPropagation(); close(); }
      else if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey && event.key !== " ") {
        const current = buttons.current.findIndex(button => button === ownerDocument.activeElement);
        const normalize = (text: string) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();
        for (let offset = 1; offset <= items.length; offset++) {
          const index = (current + offset + items.length) % items.length;
          if (!items[index].disabled && normalize(items[index].label).startsWith(normalize(event.key))) {
            event.preventDefault(); event.stopPropagation(); buttons.current[index]?.focus({ preventScroll: true }); break;
          }
        }
      }
    }}>
    {items.map((item, index) => <div className="context-menu-entry" role="none" key={item.id ?? `${index}:${item.label}`}>
      {item.separator && <div className="context-menu-separator" role="separator" />}
      <button ref={element => { buttons.current[index] = element; }} role="menuitem" type="button" tabIndex={-1}
        disabled={item.disabled} className={item.danger ? "danger" : undefined}
        onClick={() => { if (!item.disabled) { close(); item.onSelect(); } }}>
        {item.icon}<span>{item.label}</span>
      </button>
    </div>)}
  </div>, ownerDocument.body);
}
