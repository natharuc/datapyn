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
    cleanup.current?.(); const owner = event.currentTarget.ownerDocument, pointerId = event.pointerId, origin = { x: event.clientX, y: event.clientY };
    let active = false, ended = false, next: ConnectionDragState | undefined, hover: string | undefined, hoverSince = 0;
    let captured: HTMLDivElement | undefined;
    const view = owner.defaultView;
    const resolve = (x: number, y: number) => {
      const hit = owner.elementFromPoint(x, y), inTree = Boolean(hit && viewport.current?.contains(hit));
      const key = hit?.closest<HTMLElement>("[data-connection-row-key]")?.dataset.connectionRowKey;
      const target = key ? current.current.rows.find(row => row.key === key) ?? null : null;
      const block = source.connection && hit?.closest(".code-block[data-block-id]");
      return { hit, block, target, valid: Boolean(block) || inTree && current.current.allowed(source, target) };
    };
    function update(pointer: PointerEvent) {
      if (pointer.pointerId !== pointerId) return;
      // A release outside the WebView may arrive as movement without pointerup.
      if (!(pointer.buttons & 1)) { stop(); return; }
      if (!active && Math.hypot(pointer.clientX - origin.x, pointer.clientY - origin.y) < 5) return;
      if (!active && viewport.current?.ownerDocument === owner) {
        // Capture the stable viewport only after dragging starts, preserving clicks.
        try { viewport.current.setPointerCapture(pointerId); captured = viewport.current; } catch { /* Document listeners also cover WebViews without capture. */ }
      }
      active = true; suppressClick.current = true; pointer.preventDefault();
      const resolved = resolve(pointer.clientX, pointer.clientY);
      next = { source, target: resolved.target, valid: resolved.valid, x: pointer.clientX, y: pointer.clientY }; setDrag(next);
      const groupId = resolved.target?.group?.id;
      if (hover !== groupId) { hover = groupId; hoverSince = Date.now(); }
    }
    function stop() {
      if (ended) return; ended = true;
      owner.removeEventListener("pointermove", update, true); owner.removeEventListener("pointerup", finish, true);
      owner.removeEventListener("pointercancel", cancel, true); owner.removeEventListener("lostpointercapture", cancel, true);
      owner.removeEventListener("keydown", escape, true); owner.removeEventListener("visibilitychange", visibility);
      view?.removeEventListener("blur", stop); view?.removeEventListener("pagehide", stop);
      clearInterval(timer); cleanup.current = undefined; setDrag(undefined);
      if (captured?.hasPointerCapture(pointerId)) captured.releasePointerCapture(pointerId);
      // The synthetic click follows pointerup; only that click is suppressed.
      setTimeout(() => { suppressClick.current = false; }, 0);
    }
    function finish(pointer: PointerEvent) {
      if (pointer.pointerId !== pointerId) return;
      const resolved = active ? resolve(pointer.clientX, pointer.clientY) : undefined;
      stop();
      if (active) {
        pointer.preventDefault();
        const DropEvent = view?.CustomEvent ?? CustomEvent;
        if (resolved?.block && source.connection) resolved.block.dispatchEvent(new DropEvent("datapyn:connection-drop", { bubbles: true, detail: { connectionId: source.connection.id } }));
        else if (resolved?.valid) current.current.move(source, resolved.target);
      }
    }
    function cancel(pointer: PointerEvent) { if (pointer.pointerId === pointerId) stop(); }
    function visibility() { if (owner.hidden) stop(); }
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
    // Capture listeners still receive events consumed by tree/editor components.
    owner.addEventListener("pointermove", update, { passive: false, capture: true }); owner.addEventListener("pointerup", finish, true);
    owner.addEventListener("pointercancel", cancel, true); owner.addEventListener("lostpointercapture", cancel, true);
    owner.addEventListener("keydown", escape, true); owner.addEventListener("visibilitychange", visibility);
    view?.addEventListener("blur", stop); view?.addEventListener("pagehide", stop);
  }
  function consumeClick() { if (!suppressClick.current) return false; suppressClick.current = false; return true; }
  return { drag, start, consumeClick };
}
