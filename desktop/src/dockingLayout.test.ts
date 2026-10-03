import { describe, expect, it } from "vitest";
import { createDefaultDockLayout, PANEL_IDS, prepareDockLayout, rememberPanelPlacement, resolvePanelPlacement, type DataPynDockLayout, type PanelId } from "./dockingLayout";

const titles = Object.fromEntries(PANEL_IDS.map(id => [id, id])) as Record<PanelId, string>;
const canonical = () => createDefaultDockLayout({ width: 1440, height: 820, leftWidth: 260, rightWidth: 280, resultHeight: 240 }, titles);
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
function detachedFixture() {
  const layout = canonical(), root = layout.grid.root.data as Array<{ type: "leaf" | "branch"; data: unknown; size?: number }>;
  const left = root[0].data as { views: string[]; activeView: string }, center = root[1].data as Array<{ data: { id: string; views: string[]; activeView?: string }; visible?: boolean; size?: number }>;
  const explorer = rememberPanelPlacement(layout, "explorer")!, summary = rememberPanelPlacement(layout, "summary")!;
  left.views = ["connections"];
  center[1].data.views = []; delete center[1].data.activeView; center[1].visible = false;
  layout.floatingGroups = [{ data: { id: "floating-output", views: ["output"], activeView: "output" }, position: { left: 100, top: 100, width: 600, height: 440 } }];
  layout.popoutGroups = [{ data: { id: "popout-bottom", views: ["results", "pyniaOutput"], activeView: "pyniaOutput" }, gridReferenceGroup: "datapyn-bottom", position: { left: 377, top: 659, width: 845, height: 310 }, url: "/popout.html" }];
  delete layout.panels.explorer; delete layout.panels.summary;
  layout.datapyn = { version: 1, hiddenPanels: { explorer, summary: { ...summary, groupId: "popout-bottom", location: "popout", position: layout.popoutGroups[0].position!, references: [] } } };
  return layout;
}

describe("Workspace docking persistence", () => {
  it("restores PyQt's tab groups and all nine panels, with bounded initial dimensions", () => {
    const original = canonical(), restored = prepareDockLayout(original)!;
    expect(restored.panels).toHaveProperty("pyniaOutput");
    expect(Object.keys(restored.panels)).toHaveLength(9);
    expect(restored.grid).toEqual(original.grid);
    expect(restored.activeGroup).toBe("datapyn-editor");
    const panels = JSON.stringify(restored.grid);
    expect(panels).toContain('"views":["connections","explorer"]');
    expect(panels).toContain('"views":["results","summary","output","pyniaOutput"]');
    expect(panels).toContain('"views":["variables","pynia"]');
  });

  it("keeps hidden docks hidden and preserves active tab, split sizes and maximization", () => {
    const layout = canonical(), children = layout.grid.root.data as Array<{ type: string; data: unknown }>;
    const left = children[0].data as { views: string[]; activeView: string };
    left.views = ["explorer"]; left.activeView = "explorer";
    delete layout.panels.connections;
    const center = children[1].data as Array<{ data: { views: string[]; activeView: string }; size: number }>;
    center[1].data.activeView = "pyniaOutput"; center[1].size = 311;
    (layout.grid as unknown as Record<string, unknown>).maximizedNode = { location: [1, 0] };
    layout.activeGroup = "datapyn-bottom";
    const prepared = prepareDockLayout(layout)!;
    expect(prepared).toBeDefined();
    expect(prepared.panels.connections).toBeUndefined();
    expect(prepared.grid).toEqual(layout.grid);
    expect(prepared.activeGroup).toBe("datapyn-bottom");
  });

  it("honours sidebar preferences only for a fresh workspace while keeping reopen positions", () => {
    const layout = createDefaultDockLayout({ width: 1440, height: 820, leftWidth: 260, rightWidth: 280, resultHeight: 240, leftVisible: false, rightVisible: false }, titles);
    const prepared = prepareDockLayout(layout)!;
    expect(Object.keys(prepared.panels)).toEqual(["editor", "results", "summary", "output", "pyniaOutput"]);
    expect(Object.keys(prepared.datapyn!.hiddenPanels)).toEqual(["connections", "explorer", "variables", "pynia"]);
    expect(resolvePanelPlacement(prepared.datapyn!.hiddenPanels.connections, ["editor", "results"])).toMatchObject({ referenceId: "editor", direction: "left" });
    expect(Object.keys(canonical().panels)).toHaveLength(9);
  });

  it("preserves nested float and popout groups while forcing the trusted local document", () => {
    const layout = canonical(), root = layout.grid.root.data as Array<{ type: "leaf" | "branch"; data: unknown; size?: number }>;
    const right = root.pop()!.data as { id: string; views: string[]; activeView: string };
    const left = root.shift()!.data as { id: string; views: string[]; activeView: string };
    layout.floatingGroups = [{ data: right, position: { right: 24, bottom: 32, width: 540, height: 400 } }];
    layout.popoutGroups = [{ grid: { root: { type: "branch", data: [{ type: "leaf", data: left, size: 320 }] }, width: 320, height: 580, orientation: layout.grid.orientation }, position: { left: -1280, top: 40, width: 320, height: 580 }, url: "javascript:alert(1)" }];
    const prepared = prepareDockLayout(layout)!;
    expect(prepared.floatingGroups).toEqual(layout.floatingGroups);
    expect(prepared.popoutGroups?.[0].grid).toEqual(layout.popoutGroups[0].grid);
    expect(prepared.popoutGroups?.[0].position).toEqual(layout.popoutGroups[0].position);
    expect(prepared.popoutGroups?.[0].url).toBe("/popout.html");
    expect(layout.popoutGroups[0].url).toBe("javascript:alert(1)");
  });

  it("round-trips Dockview's invisible empty popout anchor together with floated and hidden panels", () => {
    const layout = detachedFixture(), prepared = prepareDockLayout(layout)!;
    expect(prepared).toBeDefined();
    expect(prepared.grid).toEqual(layout.grid);
    expect(prepared.floatingGroups).toEqual(layout.floatingGroups);
    expect(prepared.popoutGroups).toEqual(layout.popoutGroups);
    expect(prepared.datapyn).toEqual(layout.datapyn);
    expect(prepared.panels.explorer).toBeUndefined();
    expect(prepared.panels.summary).toBeUndefined();
  });

  it("rejects visible/orphan empty groups, missing popout references, duplicate IDs and empty detached windows", () => {
    const mutations = [
      (layout: DataPynDockLayout) => { delete layout.popoutGroups![0].gridReferenceGroup; },
      (layout: DataPynDockLayout) => { layout.popoutGroups![0].gridReferenceGroup = "missing-anchor"; },
      (layout: DataPynDockLayout) => { delete layout.popoutGroups; },
      (layout: DataPynDockLayout) => { const center = (layout.grid.root.data as Array<{ data: unknown }>)[1].data as Array<{ visible?: boolean }>; center[1].visible = true; },
      (layout: DataPynDockLayout) => { const center = (layout.grid.root.data as Array<{ data: unknown }>)[1].data as Array<{ visible?: boolean }>; delete center[1].visible; },
      (layout: DataPynDockLayout) => { layout.popoutGroups![0].data!.id = "datapyn-bottom"; },
      (layout: DataPynDockLayout) => { layout.popoutGroups![0].data!.views = []; delete layout.popoutGroups![0].data!.activeView; },
      (layout: DataPynDockLayout) => { delete layout.popoutGroups![0].data; layout.popoutGroups![0].grid = { ...layout.grid, root: { type: "branch", data: [] } }; },
      (layout: DataPynDockLayout) => { layout.floatingGroups![0].data!.views = []; delete layout.floatingGroups![0].data!.activeView; },
    ];
    for (const mutate of mutations) { const layout = detachedFixture(); mutate(layout); expect(prepareDockLayout(layout)).toBeUndefined(); }
  });

  it("rejects damaged or foreign layouts before any live Dockview mutation", () => {
    const damaged = canonical(), duplicates = canonical(), dangling = canonical(), malformedMaximize = canonical();
    delete damaged.panels.editor;
    const leaves = duplicates.grid.root.data as Array<{ data: { views?: string[] } }>;
    leaves[0].data.views!.push("variables");
    const other = dangling.grid.root.data as Array<{ data: { views?: string[] } }>;
    other[0].data.views!.push("unregistered-panel");
    (malformedMaximize.grid as unknown as Record<string, unknown>).maximizedNode = { location: [1, 999] };
    for (const candidate of [undefined, null, {}, damaged, duplicates, dangling, malformedMaximize, { grid: { root: { type: "leaf" } }, panels: {} }]) expect(prepareDockLayout(candidate)).toBeUndefined();
    const circular: Record<string, unknown> = {}; circular.circular = circular;
    expect(prepareDockLayout(circular)).toBeUndefined();
  });

  it("reuses local content with always-rendered widgets and leaves input untouched", () => {
    const layout = canonical(); layout.panels.results.renderer = "onlyWhenVisible"; layout.panels.results.contentComponent = "unknown"; layout.panels.results.tabComponent = "foreign";
    const before = clone(layout), prepared = prepareDockLayout(layout)!;
    expect(prepared.panels.results).toMatchObject({ renderer: "always", contentComponent: "content" });
    expect(prepared.panels.results.tabComponent).toBeUndefined();
    expect(layout).toEqual(before);
  });

  it("remembers reopened tab order and the nearest surviving split without reviving closed neighbours", () => {
    const layout = canonical(), explorer = rememberPanelPlacement(layout, "explorer")!, output = rememberPanelPlacement(layout, "output")!;
    expect(resolvePanelPlacement(explorer, ["editor", "connections"])).toEqual({ referenceId: "connections", direction: "within", index: 1 });
    expect(resolvePanelPlacement(explorer, ["editor", "variables"])).toEqual({ referenceId: "editor", direction: "left" });
    expect(resolvePanelPlacement(output, ["editor", "results"])).toEqual({ referenceId: "results", direction: "within", index: 2 });
    expect(resolvePanelPlacement(output, ["editor"])).toEqual({ referenceId: "editor", direction: "below" });
    expect(resolvePanelPlacement(output, [])).toBeUndefined();
  });

  it("remembers detached geometry and sanitizes hidden placement metadata", () => {
    const layout = canonical(), root = layout.grid.root.data as Array<{ data: unknown }>;
    const right = root.pop()!.data as { id: string; views: string[]; activeView: string };
    layout.floatingGroups = [{ data: right, position: { left: 120, top: 90, width: 550, height: 410 } }];
    const placement = rememberPanelPlacement(layout, "pynia")!;
    expect(placement).toMatchObject({ location: "floating", groupId: "datapyn-right", peers: ["variables"], index: 1, position: { left: 120, top: 90, width: 550, height: 410 } });
    right.views = ["variables"]; right.activeView = "variables"; delete layout.panels.pynia;
    layout.datapyn = { version: 1, hiddenPanels: { pynia: placement, editor: placement, connections: { ...placement, peers: ["foreign"] as unknown as PanelId[] } } };
    const prepared = prepareDockLayout(layout)!;
    expect(prepared.datapyn?.hiddenPanels).toEqual({ pynia: placement });
    expect(resolvePanelPlacement(prepared.datapyn?.hiddenPanels.pynia, ["editor", "variables"])).toEqual({ referenceId: "variables", direction: "within", index: 1 });
  });

  it("accepts an empty main grid when the protected editor is in another window", () => {
    const layout: DataPynDockLayout = { grid: { width: 1200, height: 800, orientation: canonical().grid.orientation, root: { type: "branch", data: [] } }, panels: { editor: canonical().panels.editor }, popoutGroups: [{ data: { id: "floating-editor", views: ["editor"], activeView: "editor" }, position: null }] };
    expect(prepareDockLayout(layout)?.popoutGroups?.[0].data?.views).toEqual(["editor"]);
  });
});
