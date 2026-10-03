import { isPanelId, type PanelId } from "./dockingLayout";

interface Disposable { dispose(): void }
export interface VisibilityPanel {
  id: string;
  api: { readonly isVisible: boolean; onDidVisibilityChange: (listener: () => void) => Disposable };
}

/** Open inactive tabs remain mounted; expensive panels depend on actual dock visibility. */
export class DockPanelVisibility {
  private panels = new Map<PanelId, { panel: VisibilityPanel; subscription: Disposable }>();
  constructor(private readonly changed: () => void) {}
  add(panel: VisibilityPanel) {
    if (!isPanelId(panel.id)) return;
    const previous = this.panels.get(panel.id);
    if (previous?.panel === panel) return;
    previous?.subscription.dispose();
    this.panels.set(panel.id, { panel, subscription: panel.api.onDidVisibilityChange(this.changed) });
  }
  remove(id: string) {
    if (!isPanelId(id)) return;
    this.panels.get(id)?.subscription.dispose(); this.panels.delete(id);
  }
  visible(): PanelId[] {
    return Array.from(this.panels.entries()).filter(([, entry]) => entry.panel.api.isVisible).map(([id]) => id);
  }
  dispose() { for (const entry of this.panels.values()) entry.subscription.dispose(); this.panels.clear(); }
}
