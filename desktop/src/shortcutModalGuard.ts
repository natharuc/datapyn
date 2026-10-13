/** Modal portals share a stacking layer; the last visible dialog owns its window's keyboard. */
export function topmostShortcutDialog(owner: Document): HTMLElement | undefined {
  return Array.from(owner.querySelectorAll<HTMLElement>('[role="dialog"],[role="alertdialog"]')).filter(dialog => {
    if (dialog.getAttribute("aria-modal") !== "true") return false;
    if (dialog.closest('[hidden],[inert],[aria-hidden="true"]')) return false;
    if (!dialog.getClientRects().length) return false;
    const style = owner.defaultView?.getComputedStyle(dialog);
    return style?.visibility !== "hidden" && style?.visibility !== "collapse" && style?.display !== "none";
  }).at(-1);
}

/** Editor widgets may use role="dialog" without blocking application shortcuts. */
export function hasVisibleShortcutDialog(owner: Document): boolean { return Boolean(topmostShortcutDialog(owner)); }

/** Independent of focus: disabled form controls can leave activeElement on body during saves. */
export function hasLocalShortcutDialog(owner: Document): boolean {
  return topmostShortcutDialog(owner)?.getAttribute("data-local-shortcut-dialog") === "true";
}
