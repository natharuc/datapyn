export interface MenuBounds { width: number; height: number }
export interface MenuPoint { x: number; y: number }

/** Client coordinates and bounds all belong to the window containing the source. */
export function contextMenuPosition(anchor: MenuPoint, menu: MenuBounds, viewport: MenuBounds) {
  const edge = 8;
  const left = Math.max(edge, Math.min(anchor.x, viewport.width - menu.width - edge));
  const top = Math.max(edge, Math.min(anchor.y, viewport.height - menu.height - edge));
  return { left, top };
}

/** Keyboard navigation wraps around enabled commands, skipping separators. */
export function contextMenuIndex(disabled: readonly boolean[], current: number, key: string): number {
  const enabled = disabled.flatMap((value, index) => value ? [] : [index]);
  if (!enabled.length) return -1;
  if (key === "Home") return enabled[0];
  if (key === "End") return enabled[enabled.length - 1];
  const index = enabled.indexOf(current);
  if (index < 0) return key === "ArrowUp" ? enabled[enabled.length - 1] : enabled[0];
  return enabled[(index + (key === "ArrowUp" ? -1 : 1) + enabled.length) % enabled.length];
}
