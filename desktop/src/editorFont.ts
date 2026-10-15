import { normalizeEditorFontSize } from "./preferences";

export function editorFontOptions(value: unknown) {
  const fontSize = normalizeEditorFontSize(value);
  // Keep the default 13px/22px spacing while scaling both metrics together.
  return { fontSize, lineHeight: Math.round(fontSize * 22 / 13) };
}

/** Own the gesture instead of Monaco's process-wide, multiplicative EditorZoom. */
export function bindEditorFontZoom(host: HTMLElement, change: (direction: number) => void) {
  let accumulated = 0, direction = 0, previousTime = 0;
  const zoom = (event: WheelEvent) => {
    if (!(event.ctrlKey || event.metaKey) || event.shiftKey || event.altKey || !Number.isFinite(event.deltaY) || event.deltaY === 0) return;
    event.preventDefault();
    event.stopPropagation();
    const nextDirection = event.deltaY < 0 ? 1 : -1;
    if (nextDirection !== direction || event.timeStamp - previousTime > 200) accumulated = 0;
    direction = nextDirection;
    previousTime = event.timeStamp;
    // A physical wheel notch is one step. Accumulate small trackpad/pinch
    // deltas so dozens of events from one gesture do not jump to either limit.
    const threshold = event.deltaMode === 1 ? 3 : event.deltaMode === 2 ? 1 : 50;
    accumulated += Math.abs(event.deltaY);
    if (accumulated >= threshold) {
      accumulated = 0;
      change(direction);
    }
  };
  host.addEventListener("wheel", zoom, { capture: true, passive: false });
  return () => host.removeEventListener("wheel", zoom, { capture: true });
}
