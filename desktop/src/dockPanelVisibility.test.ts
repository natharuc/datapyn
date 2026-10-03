import { describe, expect, it, vi } from "vitest";
import { DockPanelVisibility, type VisibilityPanel } from "./dockPanelVisibility";

function panel(id: string, visible: boolean) {
  const listeners = new Set<() => void>();
  const value = { id, api: { isVisible: visible, onDidVisibilityChange: (listener: () => void) => { listeners.add(listener); return { dispose: () => listeners.delete(listener) }; } } } satisfies VisibilityPanel;
  return { value, listeners, setVisible: (next: boolean) => { value.api.isVisible = next; listeners.forEach(listener => listener()); } };
}
describe("Dock panel visibility", () => {
  it("keeps split summary active when results gains focus and excludes mounted inactive tabs", () => {
    const changed = vi.fn(), tracker = new DockPanelVisibility(changed), summary = panel("summary", true), results = panel("results", true), output = panel("output", false);
    [summary, results, output].forEach(item => tracker.add(item.value));
    expect(tracker.visible()).toEqual(["summary", "results"]);
    results.setVisible(true); expect(tracker.visible()).toContain("summary"); expect(changed).toHaveBeenCalledOnce();
    summary.setVisible(false); expect(tracker.visible()).toEqual(["results"]);
    summary.setVisible(true); expect(tracker.visible()).toContain("summary");
  });
  it("avoids duplicate subscriptions, replaces restored panel instances and cleans up removals", () => {
    const changed = vi.fn(), tracker = new DockPanelVisibility(changed), old = panel("summary", true), restored = panel("summary", false);
    tracker.add(old.value); tracker.add(old.value); expect(old.listeners.size).toBe(1);
    tracker.add(restored.value); expect(old.listeners.size).toBe(0); expect(tracker.visible()).toEqual([]);
    old.setVisible(false); expect(changed).not.toHaveBeenCalled();
    restored.setVisible(true); expect(tracker.visible()).toEqual(["summary"]);
    tracker.remove("summary"); expect(restored.listeners.size).toBe(0); expect(tracker.visible()).toEqual([]);
  });
  it("disposes every remaining subscription and ignores unknown extension panels", () => {
    const tracker = new DockPanelVisibility(vi.fn()), summary = panel("summary", true), custom = panel("custom-widget", true);
    tracker.add(summary.value); tracker.add(custom.value); expect(custom.listeners.size).toBe(0);
    tracker.dispose(); expect(summary.listeners.size).toBe(0); expect(tracker.visible()).toEqual([]);
  });
});
