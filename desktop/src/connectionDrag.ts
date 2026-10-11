import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import type { ConnectionTreeRow } from "./connections";

export interface ConnectionDragState { source: ConnectionTreeRow; target: ConnectionTreeRow | null; valid: boolean; x: number; y: number }

/** Pointer dragging works in WebView2 while Tauri retains native file-drop handling. */
export function useConnectionDrag(viewport: RefObject<HTMLDivElement>, options: {
  rows: ConnectionTreeRow[]; allowed: (source: ConnectionTreeRow, target: ConnectionTreeRow | null) => boolean;
  move: (source: ConnectionTreeRow, target: ConnectionTreeRow | null) => void;
  expand: (id: string) => void;
}) {
  const [drag, setDrag] = useState<ConnectionDragState>();
  const current = useRef(options); current.current = options;
  const cleanup = useRef<() => void>(), suppressClick = useRef(false);
  useEffect(() => () => cleanup.current?.(), []);
  function start(event: ReactPointerEvent<HTMLElement>, source: ConnectionTreeRow) {
    if (event.button !== 0 || event.pointerType === "touch") return;
    cleanup.current?.(); const owner = event.currentTarget.ownerDocument, origin = { x: event.clientX, y: event.clientY };
    let active = false, next: ConnectionDragState | undefined, hover: string | undefined, hoverSince = 0;
    const view = owner.defaultView;
    const resolve = (x: number, y: number) => {
      const hit = owner.elementFromPoint(x, y), inTree = Boolean(hit && viewport.current?.contains(hit));
      const key = hit?.closest<HTMLElement>("[data-connection-row-key]")?.dataset.connectionRowKey;
      const target = key ? current.current.rows.find(row => row.key === key) ?? null : null;
      const block = source.connection && hit?.closest(".code-block[data-block-id]");
      return { hit, block, target, valid: Boolean(block) || inTree && current.current.allowed(source, target) };
    };
    function update(pointer: PointerEvent) {
      if (pointer.pointerId !== event.pointerId) return;
      if (!active && Math.hypot(pointer.clientX - origin.x, pointer.clientY - origin.y) < 5) return;
      active = true; suppressClick.current = true; pointer.preventDefault();
      const resolved = resolve(pointer.clientX, pointer.clientY);
      next = { source, target: resolved.target, valid: resolved.valid, x: pointer.clientX, y: pointer.clientY }; setDrag(next);
      const groupId = resolved.target?.group?.id;
      if (hover !== groupId) { hover = groupId; hoverSince = Date.now(); }
    }
    function stop() { owner.removeEventListener("pointermove", update); owner.removeEventListener("pointerup", finish); owner.removeEventListener("pointercancel", stop); owner.removeEventListener("keydown", escape); view?.removeEventListener("blur", stop); clearInterval(timer); cleanup.current = undefined; setDrag(undefined); view?.setTimeout(() => { suppressClick.current = false; }, 0); }
    function finish(pointer: PointerEvent) {
      if (pointer.pointerId !== event.pointerId) return;
      if (active) {
        pointer.preventDefault(); const resolved = resolve(pointer.clientX, pointer.clientY);
        if (resolved.block && source.connection) resolved.block.dispatchEvent(new CustomEvent("datapyn:connection-drop", { bubbles: true, detail: { connectionId: source.connection.id } }));
        else if (resolved.valid) current.current.move(source, resolved.target);
      }
      stop();
      // The synthetic click follows pointerup; only that click is suppressed.
      view?.setTimeout(() => { suppressClick.current = false; }, 0);
    }
    function escape(key: KeyboardEvent) { if (key.key === "Escape") { key.preventDefault(); stop(); } }
    const timer = setInterval(() => {
      if (!active || !next) return;
      if (hover && Date.now() - hoverSince >= 650) { current.current.expand(hover); hover = undefined; }
      const element = viewport.current; if (!element) return; const bounds = element.getBoundingClientRect();
      if (next.x >= bounds.left && next.x <= bounds.right) {
        const delta = next.y < bounds.top + 30 ? -16 : next.y > bounds.bottom - 30 ? 16 : 0;
        if (delta) element.scrollTop += delta;
      }
    }, 50);
    cleanup.current = stop;
    owner.addEventListener("pointermove", update, { passive: false }); owner.addEventListener("pointerup", finish); owner.addEventListener("pointercancel", stop); owner.addEventListener("keydown", escape); view?.addEventListener("blur", stop);
  }
  function consumeClick() { if (!suppressClick.current) return false; suppressClick.current = false; return true; }
  return { drag, start, consumeClick };
}
