import { translate as t, useLocale } from "./i18n";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { getFocusedDocument } from "./documentWindows";

export function Modal({ title, children, onClose, className = "" }: { title: string; children: ReactNode; onClose: () => void; className?: string }) {
  useLocale();
  const container = useRef<HTMLElement>(null), close = useRef(onClose); close.current = onClose;
  const [host] = useState(() => {
    const owner = getFocusedDocument();
    return { owner, previous: owner.activeElement as HTMLElement | null };
  });
  useLayoutEffect(() => {
    const panel = container.current;
    const owner = host.owner, view = owner.defaultView;
    let unloading = false;
    const focusables = () => Array.from(panel?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]:not(:disabled)') ?? []).filter((element) => element.getClientRects().length);
    (focusables()[0] ?? panel)?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close.current(); }
      if (event.key === "Tab") {
        const items = focusables(), index = items.indexOf(owner.activeElement as HTMLElement);
        if (!items.length) { event.preventDefault(); panel?.focus(); }
        else if ((event.shiftKey && index <= 0) || (!event.shiftKey && (index < 0 || index === items.length - 1))) {
          event.preventDefault(); items[event.shiftKey ? items.length - 1 : 0].focus();
        }
      }
    };
    const unload = () => { unloading = true; close.current(); };
    panel?.addEventListener("keydown", handle);
    view?.addEventListener("pagehide", unload);
    view?.addEventListener("unload", unload);
    return () => {
      panel?.removeEventListener("keydown", handle);
      view?.removeEventListener("pagehide", unload);
      view?.removeEventListener("unload", unload);
      if (!unloading && !view?.closed && host.previous?.isConnected) host.previous.focus();
    };
  }, [host]);
  return createPortal(<div className="modal-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={container} tabIndex={-1} className={`modal ${className}`} role="dialog" aria-modal="true" aria-label={title}>
      <header className="modal-header"><h2>{title}</h2><button className="icon-button" type="button" onClick={onClose} title={t("Fechar")} aria-label={t("Fechar")}><X size={17} /></button></header>{children}
    </section>
  </div>, host.owner.body);
}
