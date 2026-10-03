/** Document references are shared by moved React portals, without copying workspace state. */
const documents = new Map<Document, number>();
const elements = new Map<HTMLElement, { document: Document; changed: () => void }>();

export function registerDocument(document: Document): () => void {
  documents.set(document, (documents.get(document) ?? 0) + 1);
  let released = false;
  return () => {
    if (released) return; released = true;
    const count = (documents.get(document) ?? 1) - 1;
    if (count) documents.set(document, count); else documents.delete(document);
  };
}

export function findInDocuments(selector: string, preferred?: Document): HTMLElement | null {
  const candidates = new Set<Document>([...(preferred ? [preferred] : []), ...documents.keys(), document]);
  for (const candidate of candidates) {
    const element = candidate.querySelector<HTMLElement>(selector);
    if (element) return element;
  }
  return null;
}

/** Select the actual focused native document when an application-level dialog opens. */
export function getFocusedDocument(fallback: Document = document): Document {
  const candidates = new Set<Document>([...documents.keys(), fallback]);
  for (const candidate of candidates) {
    if (candidate.defaultView?.closed) continue;
    if (candidate.hasFocus?.()) return candidate;
  }
  return fallback;
}

export function observeElementDocument(element: HTMLElement, changed: () => void): () => void {
  const registration = { document: element.ownerDocument, changed };
  elements.set(element, registration);
  return () => { if (elements.get(element) === registration) elements.delete(element); };
}

/** Dockview emits location changes after the panel DOM has reached its destination. */
export function refreshOwnerDocuments(root: HTMLElement): void {
  for (const [element, registration] of elements) {
    if (root.contains(element) && element.ownerDocument !== registration.document) {
      registration.document = element.ownerDocument;
      registration.changed();
    }
  }
}

export function copyRootPresentation(source: Document, target: Document): void {
  for (const attribute of ["data-theme", "lang", "dir"]) {
    const value = source.documentElement.getAttribute(attribute);
    if (value === null) target.documentElement.removeAttribute(attribute);
    else target.documentElement.setAttribute(attribute, value);
  }
  // This includes user fonts, sizes and custom properties; copied stylesheets supply theme defaults.
  target.documentElement.style.cssText = source.documentElement.style.cssText;
  target.body.style.minWidth = "0"; target.body.style.minHeight = "0";
}

/** Styles for lazy panels may arrive after Dockview took its initial stylesheet snapshot. */
export function copyLazyStylesheets(source: Document, target: Document): void {
  for (const link of source.head.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')) {
    if ([...target.head.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')].some(existing => existing.href === link.href)) continue;
    const copy = target.createElement("link"); copy.rel = "stylesheet"; copy.href = link.href;
    target.head.appendChild(copy);
  }
}

/** A single binding per Window, even if multiple tab groups inhabit it. */
export class PopoutBindings {
  private readonly bindings = new Map<Window, () => void>();
  constructor(private readonly setup: (window: Window) => (() => void) | void) {}
  add(window: Window): void {
    if (this.bindings.has(window)) return;
    const cleanup = this.setup(window);
    this.bindings.set(window, () => { cleanup?.(); });
  }
  remove(window: Window): void {
    const cleanup = this.bindings.get(window); if (!cleanup) return;
    this.bindings.delete(window); cleanup();
  }
  update(present: readonly Window[]): void {
    const active = new Set(present);
    for (const window of this.bindings.keys()) if (!active.has(window)) this.remove(window);
    for (const window of present) this.add(window);
  }
  forEach(callback: (window: Window) => void): void { this.bindings.forEach((_cleanup, window) => callback(window)); }
  dispose(): void { for (const window of [...this.bindings.keys()]) this.remove(window); }
}
