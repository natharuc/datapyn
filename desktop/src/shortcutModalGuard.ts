/** Only actual modals block app shortcuts; editor widgets may use role="dialog". */
export function hasVisibleShortcutDialog(owner: Document): boolean {
  return Array.from(owner.querySelectorAll<HTMLElement>('[role="dialog"],[role="alertdialog"]')).some(dialog => {
    if (dialog.getAttribute("aria-modal") !== "true") return false;
    if (dialog.closest('[hidden],[inert],[aria-hidden="true"]')) return false;
    if (!dialog.getClientRects().length) return false;
    const style = owner.defaultView?.getComputedStyle(dialog);
    return style?.visibility !== "hidden" && style?.visibility !== "collapse" && style?.display !== "none";
  });
}
