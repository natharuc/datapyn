import type { SerializedDockview } from "dockview-react";

export const PANEL_IDS = ["editor", "connections", "explorer", "results", "summary", "output", "pyniaOutput", "variables", "pynia"] as const;
export type PanelId = typeof PANEL_IDS[number];
export type BottomPanelId = "results" | "summary" | "output" | "pyniaOutput";
export type DockDirection = "left" | "right" | "above" | "below" | "within";
export type DockPosition = { left?: number; right?: number; top?: number; bottom?: number; width: number; height: number };
export interface HiddenPanelPlacement {
  groupId: string;
  peers: PanelId[];
  index: number;
  references: Array<{ panels: PanelId[]; direction: DockDirection }>;
  width?: number;
  height?: number;
  location: "grid" | "floating" | "popout";
  position?: DockPosition;
}
export type DataPynDockLayout = SerializedDockview & {
  datapyn?: { version: 1; hiddenPanels: Partial<Record<PanelId, HiddenPanelPlacement>> };
};
export interface DockingControls {
  capture(): DataPynDockLayout;
  show(id: PanelId): void;
  hide(id: PanelId): void;
  restore(layout: unknown): boolean;
  reset(options?: { leftWidth?: number; rightWidth?: number; resultHeight?: number }): void;
  move(id: PanelId, direction: DockDirection, referenceId?: PanelId): void;
  float(id: PanelId): void;
  popout(id: PanelId): Promise<boolean>;
  dockAll(): void;
}

type JsonObject = Record<string, unknown>;
type GridNode = { type: "leaf" | "branch"; data: JsonObject | GridNode[]; size?: number };
const object = (value: unknown): value is JsonObject => !!value && typeof value === "object" && !Array.isArray(value);
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= 100_000;
export const isPanelId = (id: unknown): id is PanelId => typeof id === "string" && (PANEL_IDS as readonly string[]).includes(id);
export const isBottomPanel = (id: unknown): id is BottomPanelId => id === "results" || id === "summary" || id === "output" || id === "pyniaOutput";

export function createDefaultDockLayout(dimensions: { width: number; height: number; leftWidth: number; rightWidth: number; resultHeight: number; leftVisible?: boolean; rightVisible?: boolean }, titles: Record<PanelId, string>): DataPynDockLayout {
  const width = Math.max(600, dimensions.width), height = Math.max(360, dimensions.height);
  const left = Math.min(Math.max(160, dimensions.leftWidth), width * .3), right = Math.min(Math.max(160, dimensions.rightWidth), width * .3), bottom = Math.min(Math.max(120, dimensions.resultHeight), height * .65);
  const layout: DataPynDockLayout = {
    grid: { width, height, orientation: "HORIZONTAL" as SerializedDockview["grid"]["orientation"], root: { type: "branch", data: [
      { type: "leaf", size: left, data: { id: "datapyn-left", views: ["connections", "explorer"], activeView: "connections" } },
      { type: "branch", size: width - left - right, data: [
        { type: "leaf", size: height - bottom, data: { id: "datapyn-editor", views: ["editor"], activeView: "editor" } },
        { type: "leaf", size: bottom, data: { id: "datapyn-bottom", views: ["results", "summary", "output", "pyniaOutput"], activeView: "results" } },
      ] },
      { type: "leaf", size: right, data: { id: "datapyn-right", views: ["variables", "pynia"], activeView: "variables" } },
    ] } },
    panels: Object.fromEntries(PANEL_IDS.map(id => [id, { id, title: titles[id], contentComponent: "content", renderer: "always" }])) as SerializedDockview["panels"],
    activeGroup: "datapyn-editor", datapyn: { version: 1, hiddenPanels: {} },
  };
  const hidden: PanelId[] = [...(dimensions.leftVisible === false ? ["connections", "explorer"] as PanelId[] : []), ...(dimensions.rightVisible === false ? ["variables", "pynia"] as PanelId[] : [])];
  for (const id of hidden) {
    const placement = rememberPanelPlacement(layout, id);
    if (placement) layout.datapyn!.hiddenPanels[id] = { ...placement, width: id === "connections" || id === "explorer" ? left : right, height };
  }
  const children = layout.grid.root.data as GridNode[], center = children[1];
  center.size = width - (dimensions.leftVisible === false ? 0 : left) - (dimensions.rightVisible === false ? 0 : right);
  layout.grid.root.data = children.filter((_node, index) => !(index === 0 && dimensions.leftVisible === false) && !(index === 2 && dimensions.rightVisible === false)) as typeof layout.grid.root.data;
  hidden.forEach(id => delete layout.panels[id]);
  return layout;
}

/** Validate before Dockview clears the live view; layout files can be damaged or come from another application. */
export function prepareDockLayout(value: unknown): DataPynDockLayout | undefined {
  let layout: JsonObject;
  try {
    const serialized = JSON.stringify(value);
    if (!serialized || serialized.length > 250_000) return;
    const clone: unknown = JSON.parse(serialized);
    if (!object(clone)) return;
    layout = clone;
  } catch { return; }
  if (!object(layout.panels) || !object(layout.grid)) return;
  const panels = layout.panels, ids = Object.keys(panels);
  if (!ids.includes("editor") || ids.some(id => !isPanelId(id))) return;
  for (const [id, panel] of Object.entries(panels)) {
    if (!object(panel) || panel.id !== id) return;
    // Every DataPyn panel uses its existing React content, including in another document.
    panel.contentComponent = "content";
    panel.renderer = "always";
    delete panel.tabComponent;
  }
  const popoutReferences = new Set<string>();
  if (layout.popoutGroups !== undefined) {
    if (!Array.isArray(layout.popoutGroups)) return;
    for (const window of layout.popoutGroups) {
      if (!object(window)) return;
      if (window.gridReferenceGroup === undefined) continue;
      if (typeof window.gridReferenceGroup !== "string" || !window.gridReferenceGroup || window.gridReferenceGroup.length > 200) return;
      popoutReferences.add(window.gridReferenceGroup);
    }
  }
  const seenPanels = new Set<string>(), seenGroups = new Set<string>(), popoutGroupIds = new Set<string>();
  const group = (data: unknown, allowEmptyAnchor = false): boolean => {
    if (!object(data) || typeof data.id !== "string" || !data.id || data.id.length > 200 || seenGroups.has(data.id) || !Array.isArray(data.views)) return false;
    seenGroups.add(data.id);
    if (data.views.length === 0 && !allowEmptyAnchor || data.views.some(id => !isPanelId(id) || !panels[id] || seenPanels.has(id))) return false;
    for (const id of data.views) { if (seenPanels.has(id)) return false; seenPanels.add(id); }
    return data.activeView === undefined || data.views.includes(data.activeView);
  };
  const node = (data: unknown, depth = 0, allowMainGridAnchors = false): boolean => {
    if (depth > 14 || !object(data) || (data.size !== undefined && (!finite(data.size) || data.size < 0))) return false;
    if (data.type === "leaf") return group(data.data, allowMainGridAnchors && data.visible === false && object(data.data) && typeof data.data.id === "string" && popoutReferences.has(data.data.id));
    return data.type === "branch" && Array.isArray(data.data) && data.data.length <= PANEL_IDS.length && data.data.every(child => node(child, depth + 1, allowMainGridAnchors));
  };
  const grid = (data: unknown, allowMainGridAnchors = false): boolean => {
    if (!object(data) || !finite(data.width) || data.width < 0 || !finite(data.height) || data.height < 0 || (data.orientation !== "HORIZONTAL" && data.orientation !== "VERTICAL") || !object(data.root) || data.root.type !== "branch" || !node(data.root, 0, allowMainGridAnchors)) return false;
    if (data.maximizedNode !== undefined) {
      if (!object(data.maximizedNode) || !Array.isArray(data.maximizedNode.location) || data.maximizedNode.location.length > 14) return false;
      let target = data.root;
      for (const index of data.maximizedNode.location) {
        if (!Number.isInteger(index) || Number(index) < 0 || target.type !== "branch" || !Array.isArray(target.data) || !object(target.data[Number(index)])) return false;
        target = target.data[Number(index)] as JsonObject;
      }
      if (target.type !== "leaf" || !object(target.data) || !Array.isArray(target.data.views) || target.data.views.length === 0) return false;
    }
    return true;
  };
  if (!grid(layout.grid, true)) return;
  const bounds = (value: unknown): boolean => object(value) && finite(value.width) && value.width > 0 && finite(value.height) && value.height > 0 && (finite(value.left) || finite(value.right)) && (finite(value.top) || finite(value.bottom)) && ["left", "right", "top", "bottom"].every(key => value[key] === undefined || finite(value[key]));
  for (const key of ["floatingGroups", "popoutGroups"]) {
    const windows = layout[key];
    if (windows === undefined) continue;
    if (!Array.isArray(windows) || windows.length > PANEL_IDS.length) return;
    for (const window of windows) {
      const previousGroups = new Set(seenGroups);
      if (!object(window) || (!!window.grid === !!window.data) || !(window.grid ? grid(window.grid) : group(window.data))) return;
      // A detached window must contain at least one real panel, never an empty grid/anchor.
      if (seenGroups.size === previousGroups.size) return;
      if (key === "popoutGroups") for (const id of seenGroups) if (!previousGroups.has(id)) popoutGroupIds.add(id);
      if (key === "floatingGroups" ? !bounds(window.position) : window.position !== null && window.position !== undefined && !bounds(window.position)) return;
      if (key === "popoutGroups") window.url = "/popout.html";
    }
  }
  if (layout.edgeGroups !== undefined) {
    if (!object(layout.edgeGroups)) return;
    for (const edge of Object.values(layout.edgeGroups)) if (!object(edge) || !finite(edge.size) || edge.size < 0 || !group(edge.group)) return;
  }
  for (const reference of popoutReferences) if (!seenGroups.has(reference) || popoutGroupIds.has(reference)) return;
  if (seenPanels.size !== ids.length) return;
  if (typeof layout.activeGroup !== "string" || !seenGroups.has(layout.activeGroup)) delete layout.activeGroup;
  const hiddenPanels: Partial<Record<PanelId, HiddenPanelPlacement>> = {};
  if (object(layout.datapyn) && layout.datapyn.version === 1 && object(layout.datapyn.hiddenPanels)) {
    for (const [id, candidate] of Object.entries(layout.datapyn.hiddenPanels)) {
      if (!isPanelId(id) || id === "editor" || panels[id] || !object(candidate) || typeof candidate.groupId !== "string" || !Array.isArray(candidate.peers) || !candidate.peers.every(isPanelId) || !Number.isInteger(candidate.index) || Number(candidate.index) < 0 || !Array.isArray(candidate.references)) continue;
      if (!["grid", "floating", "popout"].includes(String(candidate.location)) || (candidate.width !== undefined && !finite(candidate.width)) || (candidate.height !== undefined && !finite(candidate.height))) continue;
      const references = candidate.references.filter(reference => object(reference) && Array.isArray(reference.panels) && reference.panels.every(isPanelId) && ["left", "right", "above", "below", "within"].includes(String(reference.direction)));
      hiddenPanels[id] = { ...candidate, peers: candidate.peers.slice(), references, position: bounds(candidate.position) ? candidate.position : undefined } as unknown as HiddenPanelPlacement;
    }
  }
  layout.datapyn = { version: 1, hiddenPanels };
  return layout as unknown as DataPynDockLayout;
}

function collectPanels(node: GridNode): PanelId[] {
  return node.type === "leaf" ? (node.data as JsonObject).views as PanelId[] : (node.data as GridNode[]).flatMap(collectPanels);
}

/** Remember neighbouring tabs/splits so reopening one tool never revives its closed neighbours. */
export function rememberPanelPlacement(layout: SerializedDockview, id: PanelId): HiddenPanelPlacement | undefined {
  const find = (node: GridNode, orientation: string, references: HiddenPanelPlacement["references"] = []): HiddenPanelPlacement | undefined => {
    if (node.type === "leaf") {
      const data = node.data as JsonObject, views = data.views as PanelId[];
      return views.includes(id) ? { groupId: String(data.id), peers: views.filter(peer => peer !== id), index: views.indexOf(id), references, location: "grid" } : undefined;
    }
    const children = node.data as GridNode[];
    for (let index = 0; index < children.length; index++) {
      const neighbours = children.flatMap((child, sibling) => sibling === index ? [] : [{ panels: collectPanels(child), direction: orientation === "HORIZONTAL" ? sibling > index ? "left" : "right" : sibling > index ? "above" : "below" } as HiddenPanelPlacement["references"][number]]);
      const result = find(children[index], orientation === "HORIZONTAL" ? "VERTICAL" : "HORIZONTAL", [...neighbours, ...references]);
      if (result) return result;
    }
  };
  const root = find(layout.grid.root as GridNode, layout.grid.orientation);
  if (root) return root;
  for (const [key, location] of [["floatingGroups", "floating"], ["popoutGroups", "popout"]] as const) {
    for (const window of layout[key] ?? []) {
      const node = window.grid?.root ?? { type: "leaf", data: window.data };
      const result = find(node as GridNode, window.grid?.orientation ?? "HORIZONTAL");
      if (result) return { ...result, location, position: window.position ? { ...window.position } : undefined };
    }
  }
  for (const [edge, entry] of Object.entries(layout.edgeGroups ?? {})) {
    const data = entry?.group as JsonObject | undefined;
    if (data && (data.views as string[]).includes(id)) return { groupId: String(data.id), peers: (data.views as PanelId[]).filter(peer => peer !== id), index: (data.views as string[]).indexOf(id), references: [{panels: ["editor"], direction: edge === "top" ? "above" : edge === "bottom" ? "below" : edge as "left" | "right"}], location: "grid" };
  }
}

export function resolvePanelPlacement(placement: HiddenPanelPlacement | undefined, visible: readonly PanelId[]): { referenceId: PanelId; direction: DockDirection; index?: number } | undefined {
  if (!placement) return;
  const peer = placement.peers.find(id => visible.includes(id));
  if (peer) return { referenceId: peer, direction: "within", index: placement.index };
  for (const reference of placement.references) {
    const referenceId = reference.panels.find(id => visible.includes(id));
    if (referenceId) return { referenceId, direction: reference.direction };
  }
}
