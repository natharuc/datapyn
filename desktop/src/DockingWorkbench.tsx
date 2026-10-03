import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { DockviewDefaultTab, DockviewReact, themeDark, themeLight, type DockviewApi, type DockviewGroupPanel, type DockviewReadyEvent, type IDockviewPanelProps, type IDockviewPanelHeaderProps, type SerializedDockview, type IDockviewHeaderActionsProps } from "dockview-react";
import { Layers3, ExternalLink, PanelsTopLeft, Maximize2, Minimize2 } from "lucide-react";
import { useTranslation } from "./i18n";
import { copyLazyStylesheets, copyRootPresentation, PopoutBindings, refreshOwnerDocuments, registerDocument } from "./documentWindows";
import {createNativePopoutLayoutTracker, type NativePopoutLayoutTracker} from "./nativePopoutLayout";
import { createDefaultDockLayout, isBottomPanel, isPanelId, PANEL_IDS, prepareDockLayout, rememberPanelPlacement, resolvePanelPlacement, type BottomPanelId, type DataPynDockLayout, type DockingControls, type HiddenPanelPlacement, type PanelId } from "./dockingLayout";
import "dockview-react/dist/styles/dockview.css";
import "./docking.css";
import { DockPanelVisibility } from "./dockPanelVisibility";

export type { PanelId, BottomPanelId, DockingControls } from "./dockingLayout";
const titles: Record<PanelId, string> = { editor: "Análise", connections: "Conexões", explorer: "Object Explorer", results: "Resultados", summary: "Resumo", output: "Saída", pyniaOutput: "Pynia Output", variables: "Variáveis", pynia: "Pynia" };
const Content = createContext<Partial<Record<PanelId, ReactNode>>>({});
const Controls = createContext<DockingControls | undefined>(undefined);
const Notices = createContext<(message: string) => void>(() => {});
const Locked = createContext(false);
const positions = { left: "left", right: "right", above: "top", below: "bottom", within: "center" } as const;

function Panel({ api }: IDockviewPanelProps) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let disposed = false;
    const moved = () => queueMicrotask(() => { if (!disposed && element.current) refreshOwnerDocuments(element.current); });
    const subscription = api.onDidLocationChange(moved); moved();
    return () => { disposed = true; subscription.dispose(); };
  }, [api]);
  return <div ref={element} className={`dock-content dock-${api.id}`}>{useContext(Content)[api.id as PanelId]}</div>;
}

function Tab(props: IDockviewPanelHeaderProps) {
  const controls = useContext(Controls), locked = useContext(Locked);
  return <DockviewDefaultTab {...props} hideClose={props.api.id === "editor" || locked} closeActionOverride={() => { if (isPanelId(props.api.id)) controls?.hide(props.api.id); }} />;
}

function dockGroup(containerApi: DockviewApi, group: DockviewGroupPanel) {
  containerApi.exitMaximizedGroup();
  const editor = containerApi.getPanel("editor"), id = group.activePanel?.id;
  if (!editor || editor.group === group) { group.api.moveTo({ position: "left" }); return; }
  group.api.moveTo({ group: editor.group, position: id === "connections" || id === "explorer" ? "left" : isBottomPanel(id) ? "bottom" : "right" });
}

function GroupActions({ containerApi, group, location }: IDockviewHeaderActionsProps) {
  const { t } = useTranslation(), [maximized, setMaximized] = useState(group.api.isMaximized());
  const notice = useContext(Notices);
  const locked = useContext(Locked);
  useEffect(() => {
    setMaximized(group.api.isMaximized());
    const subscription = containerApi.onDidMaximizedGroupChange(() => setMaximized(group.api.isMaximized()));
    return () => subscription.dispose();
  }, [containerApi, group]);
  return <div className="dock-group-actions">
    {location?.type === "grid" ? <button disabled={locked} aria-label={t(maximized ? "Restaurar tamanho do painel" : "Maximizar painel")} title={t(maximized ? "Restaurar tamanho do painel" : "Maximizar painel")} onClick={() => maximized ? group.api.exitMaximized() : group.api.maximize()}>{maximized ? <Minimize2 size={12} /> : <Maximize2 size={12} />}</button> : <button disabled={locked} aria-label={t("Acoplar à janela principal")} title={t("Acoplar à janela principal")} onClick={() => dockGroup(containerApi, group)}><PanelsTopLeft size={12} /></button>}
    <button aria-label={t("Flutuar painel")} title={t("Flutuar painel")} disabled={locked || location?.type === "floating"} onClick={() => { containerApi.exitMaximizedGroup(); containerApi.addFloatingGroup(group, { width: Math.min(600, containerApi.width), height: Math.min(440, containerApi.height) }); }}><Layers3 size={12} /></button>
    <button aria-label={t("Abrir painel em outra janela")} title={t("Abrir painel em outra janela")} disabled={locked || location?.type === "popout"} onClick={() => { containerApi.exitMaximizedGroup(); void containerApi.addPopoutGroup(group, { popoutUrl: "/popout.html" }).then(opened => { if (!opened) notice(t("Não foi possível abrir outra janela. O painel permanece disponível na janela principal.")); }).catch(() => notice(t("Não foi possível abrir outra janela. O painel permanece disponível na janela principal."))); }}><ExternalLink size={12} /></button>
  </div>;
}

const components = { content: Panel };
export interface DockingWorkbenchProps {
  panels: Partial<Record<PanelId, ReactNode>>;
  initialLayout?: unknown;
  onLayoutChange: (layout: DataPynDockLayout) => void;
  theme: "dark" | "light" | "system";
  leftWidth: number;
  rightWidth: number;
  resultHeight: number;
  leftVisible: boolean;
  rightVisible: boolean;
  activeBottom: BottomPanelId;
  activeRight: "variables" | "pynia";
  onActivate: (id: PanelId) => void;
  resetRevision: number;
  locked?: boolean;
  onCaptureReady?: (capture: () => DataPynDockLayout) => void;
  onControlsReady?: (controls: DockingControls) => void;
  onPanelsChange?: (ids: PanelId[]) => void;
  onVisiblePanelsChange?: (ids: PanelId[]) => void;
  onInitialized?: () => void;
  onRestoreError?: (message: string) => void;
  onError?: (message: string) => void;
  onPopoutReady?: (window: Window) => (() => void) | void;
}

export function DockingWorkbench(props: DockingWorkbenchProps) {
  const { t, locale } = useTranslation();
  const translation = useRef(t); translation.current = t;
  const api = useRef<DockviewApi>(), current = useRef(props); current.current = props;
  const disposables = useRef<Array<{ dispose: () => void }>>([]), saveTimer = useRef<ReturnType<typeof setTimeout>>();
  const restoreGeneration = useRef(0), restoring = useRef(false), disposed = useRef(false), hidden = useRef<Partial<Record<PanelId, HiddenPanelPlacement>>>({});
  const removalSnapshot = useRef<SerializedDockview>(), popouts = useRef<PopoutBindings>();
  const nativePopouts = useRef<NativePopoutLayoutTracker>();
  if(!nativePopouts.current)nativePopouts.current=createNativePopoutLayoutTracker(()=>scheduleSave());
  const observed = useRef({ left: props.leftVisible, right: props.rightVisible, bottom: props.activeBottom, activeRight: props.activeRight });
  const synchronized = useRef({ ...observed.current });
  const controls = useRef<DockingControls>();
  const panelVisibility = useRef<DockPanelVisibility>();
  if (!panelVisibility.current) panelVisibility.current = new DockPanelVisibility(() => {
    if (!disposed.current && !restoring.current) current.current.onVisiblePanelsChange?.(panelVisibility.current!.visible());
  });
  if (!popouts.current) popouts.current = new PopoutBindings(view => {
    copyRootPresentation(document, view.document); copyLazyStylesheets(document, view.document);
    view.document.querySelector(".dv-popout-window")?.classList.add("datapyn-dock");
    const unregister = registerDocument(view.document), cleanup = current.current.onPopoutReady?.(view),nativeCleanup=nativePopouts.current?.bind(view);
    return () => { try { cleanup?.(); } finally { unregister();nativeCleanup?.(); } };
  });

  const capture = (): DataPynDockLayout => {
    const a=api.current!,snapshot={...a.toJSON(),datapyn:{version:1 as const,hiddenPanels:JSON.parse(JSON.stringify(hidden.current)) as Partial<Record<PanelId,HiddenPanelPlacement>>}};
    return nativePopouts.current?.capture(snapshot,a.getPopouts()) ?? snapshot;
  };
  const visibleIds = (): PanelId[] => api.current?.panels.map(panel => panel.id).filter(isPanelId) ?? [];
  const activate = (id: PanelId) => {
    if (isBottomPanel(id)) synchronized.current.bottom = id;
    if (id === "variables" || id === "pynia") synchronized.current.activeRight = id;
    current.current.onActivate(id);
  };
  const synchronize = () => {
    const a = api.current; if (!a || disposed.current || restoring.current) return;
    const ids = visibleIds();
    synchronized.current.left = ids.includes("connections") || ids.includes("explorer");
    synchronized.current.right = ids.includes("variables") || ids.includes("pynia");
    current.current.onPanelsChange?.(ids);
    current.current.onVisiblePanelsChange?.(panelVisibility.current!.visible());
    const selectedBottom = a.getPanel(current.current.activeBottom), selectedRight = a.getPanel(current.current.activeRight);
    const bottom = selectedBottom?.api.isActive ? selectedBottom.id : a.groups.map(group => group.activePanel?.id).find(isBottomPanel);
    const right = selectedRight?.api.isActive ? selectedRight.id : a.groups.map(group => group.activePanel?.id).find(id => id === "variables" || id === "pynia");
    if (isBottomPanel(bottom)) activate(bottom);
    if (right === "variables" || right === "pynia") activate(right);
    if (isPanelId(a.activePanel?.id)) activate(a.activePanel.id);
  };
  const scheduleSave = () => {
    if (restoring.current || disposed.current) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => { if (!restoring.current && !disposed.current) current.current.onLayoutChange(capture()); }, 150);
  };
  const defaultReference = (id: PanelId) => {
    const a = api.current!;
    const siblings: PanelId[] = id === "connections" || id === "explorer" ? ["connections", "explorer"] : isBottomPanel(id) ? ["results", "summary", "output", "pyniaOutput"] : id === "variables" || id === "pynia" ? ["variables", "pynia"] : [];
    return siblings.filter(peer => peer !== id).map(peer => a.getPanel(peer)).find(Boolean) ?? a.getPanel("editor");
  };
  const add = (id: PanelId, restorePosition = true) => {
    const a = api.current!; const existing = a.getPanel(id); if (existing) return existing;
    const placement = restorePosition ? hidden.current[id] : undefined, savedPosition = resolvePanelPlacement(placement, visibleIds());
    const reference = savedPosition ? a.getPanel(savedPosition.referenceId) : defaultReference(id);
    const direction = savedPosition?.direction ?? (reference && reference.id !== "editor" ? "within" : id === "connections" || id === "explorer" ? "left" : id === "variables" || id === "pynia" ? "right" : isBottomPanel(id) ? "below" : "within");
    const group = placement ? a.groups.find(group => group.id === placement.groupId) : undefined;
    const panel = a.addPanel({ id, title: translation.current(titles[id]), component: "content", renderer: "always", inactive: true,
      position: group ? { referenceGroup: group, direction: "within", index: Math.min(placement!.index, group.panels.length) } : reference && reference.id !== id ? { referencePanel: reference, direction, index: direction === "within" && savedPosition?.index !== undefined ? Math.min(savedPosition.index, reference.group.panels.length) : undefined } : undefined,
      initialWidth: placement?.width ?? (id === "connections" ? current.current.leftWidth : id === "variables" ? current.current.rightWidth : undefined),
      initialHeight: placement?.height ?? (id === "results" ? current.current.resultHeight : undefined),
    });
    if (!group && savedPosition?.direction !== "within" && placement?.location === "floating") a.addFloatingGroup(panel, placement.position ? { position: placement.position as { left: number; top: number }, width: placement.position.width, height: placement.position.height } : { width: 600, height: 440 });
    const reconnectHiddenPeers = () => {
      const previousGroup = placement?.groupId;
      if (previousGroup) for (const peer of Object.values(hidden.current)) if (peer?.groupId === previousGroup) peer.groupId = panel.group.id;
    };
    if (!group && savedPosition?.direction !== "within" && placement?.location === "popout") void a.addPopoutGroup(panel, { popoutUrl: "/popout.html", position: placement.position ? { left: placement.position.left ?? 0, top: placement.position.top ?? 0, width: placement.position.width, height: placement.position.height } : undefined }).then(opened => { if (!disposed.current) { if (!opened) current.current.onRestoreError?.(translation.current("Não foi possível abrir outra janela. O painel permanece disponível na janela principal.")); reconnectHiddenPeers(); scheduleSave(); } }).catch(() => { if (!disposed.current) { current.current.onRestoreError?.(translation.current("Não foi possível abrir outra janela. O painel permanece disponível na janela principal.")); scheduleSave(); } });
    reconnectHiddenPeers();
    delete hidden.current[id];
    return panel;
  };
  const hide = (id: PanelId) => {
    const a = api.current, panel = a?.getPanel(id); if (!a || !panel || id === "editor" || restoring.current || current.current.locked) return;
    const placement = rememberPanelPlacement(capture(), id);
    if (placement) hidden.current[id] = { ...placement, width: panel.group.api.width, height: panel.group.api.height };
    a.removePanel(panel);
  };
  const finishRestore = async (generation: number, initialized: boolean) => {
    const a = api.current!;
    try { await a.popoutRestorationPromise; } catch { current.current.onRestoreError?.(translation.current("Não foi possível abrir outra janela. O painel permanece disponível na janela principal.")); }
    if (disposed.current || generation !== restoreGeneration.current) return;
    restoring.current = false;
    a.panels.forEach(panel => { if (isPanelId(panel.id)) panel.api.setTitle(translation.current(titles[panel.id])); });
    popouts.current?.update(a.getPopouts().map(entry => entry.window));
    await nativePopouts.current?.flush().catch(()=>{});
    if(disposed.current || generation !== restoreGeneration.current)return;
    synchronize();
    current.current.onCaptureReady?.(capture);
    current.current.onControlsReady?.(controls.current!);
    current.current.onLayoutChange(capture());
    if (initialized) current.current.onInitialized?.();
  };
  const load = (layout: DataPynDockLayout, initialized = false): boolean => {
    const a = api.current; if (!a) return false;
    const previous = a.panels.length ? capture() : undefined, generation = ++restoreGeneration.current;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    restoring.current = true;
    try {
      hidden.current = layout.datapyn?.hiddenPanels ?? {};
      a.fromJSON(layout, { reuseExistingPanels: true });
    } catch {
      if (previous) {
        hidden.current = previous.datapyn?.hiddenPanels ?? {};
        try { a.fromJSON(previous, { reuseExistingPanels: true }); } catch { restoring.current = false; reset(undefined, initialized); return false; }
      } else { restoring.current = false; current.current.onRestoreError?.(translation.current("O layout salvo estava inválido. A disposição padrão foi restaurada.")); reset(undefined, initialized); return false; }
      void finishRestore(generation, initialized);
      return false;
    }
    void finishRestore(generation, initialized);
    return true;
  };
  const reset = (options?: { leftWidth?: number; rightWidth?: number; resultHeight?: number }, initialized = false) => {
    const a = api.current; if (!a) return;
    load(createDefaultDockLayout({ width: a.width, height: a.height, leftWidth: options?.leftWidth ?? current.current.leftWidth, rightWidth: options?.rightWidth ?? current.current.rightWidth, resultHeight: options?.resultHeight ?? current.current.resultHeight }, Object.fromEntries(PANEL_IDS.map(id => [id, translation.current(titles[id])])) as Record<PanelId, string>), initialized);
  };
  if (!controls.current) controls.current = {
    capture, hide,
    show: id => { if (!restoring.current && !current.current.locked && api.current) { const panel = add(id); if (api.current.hasMaximizedGroup() && !panel.api.isMaximized()) api.current.exitMaximizedGroup(); panel.api.setActive(); synchronize(); } },
    restore: layout => { if (current.current.locked) return false; const prepared = prepareDockLayout(layout); return !!prepared && load(prepared); },
    reset: options => { if (!current.current.locked) reset(options); },
    move: (id, direction, referenceId = "editor") => {
      const a = api.current; if (!a || restoring.current || current.current.locked) return;
      a.exitMaximizedGroup();
      const panel = add(id), reference = (referenceId !== id ? a.getPanel(referenceId) : undefined) ?? a.panels.find(other => other.id !== id && other.api.location.type === "grid");
      if (!reference || reference.id === id) { if (panel.api.location.type !== "grid") dockGroup(a, panel.group); return; }
      panel.api.moveTo({ group: reference.group, position: positions[direction] });
      panel.api.setActive();
    },
    float: id => { const a = api.current; if (!a || restoring.current || current.current.locked) return; a.exitMaximizedGroup(); const panel = add(id); if (panel.api.location.type !== "floating") a.addFloatingGroup(panel, { width: Math.min(600, a.width), height: Math.min(440, a.height) }); },
    popout: async id => { const a = api.current; if (!a || restoring.current || current.current.locked) return false; a.exitMaximizedGroup(); const panel = add(id); try { return panel.api.location.type === "popout" || await a.addPopoutGroup(panel, { popoutUrl: "/popout.html" }); } catch { return false; } },
    dockAll: () => { const a = api.current; if (!a || restoring.current || current.current.locked) return; const editor = a.getPanel("editor"); if (editor && editor.api.location.type !== "grid") dockGroup(a, editor.group); for (const group of [...a.groups]) if (group.api.location.type === "floating" || group.api.location.type === "popout") dockGroup(a, group); synchronize(); },
  };

  const ready = ({ api: next }: DockviewReadyEvent) => {
    api.current = next; disposed.current = false;
    next.panels.forEach(panel => panelVisibility.current!.add(panel));
    disposables.current.push(next.onDidAddPanel(panel => panelVisibility.current!.add(panel)));
    disposables.current.push(next.onDidAddPopoutGroup(({ window: view }) => popouts.current?.add(view)));
    disposables.current.push(next.onDidRemovePopoutGroup(() => popouts.current?.update(next.getPopouts().map(entry => entry.window))));
    disposables.current.push(next.onWillClosePopoutWindow(({ window: view }) => popouts.current?.remove(view)));
    disposables.current.push(next.onWillMutateLayout(event => { if (event.kind === "remove" && !restoring.current) removalSnapshot.current = capture(); }));
    disposables.current.push(next.onDidRemovePanel(panel => {
      panelVisibility.current!.remove(panel.id);
      if (restoring.current || !removalSnapshot.current || !isPanelId(panel.id)) return;
      const placement = rememberPanelPlacement(removalSnapshot.current, panel.id);
      if (placement && !hidden.current[panel.id]) hidden.current[panel.id] = { ...placement, width: panel.api.width, height: panel.api.height };
    }));
    disposables.current.push(next.onDidMutateLayout(() => { removalSnapshot.current = undefined; if (!restoring.current) { synchronize(); scheduleSave(); } }));
    disposables.current.push(next.onDidLayoutChange(scheduleSave));
    disposables.current.push(next.onDidActivePanelChange(event => { if (!restoring.current && isPanelId(event.panel?.id)) { activate(event.panel.id); current.current.onVisiblePanelsChange?.(panelVisibility.current!.visible()); } }));
    const initial = current.current.initialLayout ? prepareDockLayout(current.current.initialLayout) : undefined;
    if (current.current.initialLayout && !initial) current.current.onRestoreError?.(t("O layout salvo estava inválido. A disposição padrão foi restaurada."));
    const canonical = createDefaultDockLayout({ width: next.width, height: next.height, leftWidth: current.current.leftWidth, rightWidth: current.current.rightWidth, resultHeight: current.current.resultHeight, leftVisible: current.current.initialLayout ? true : current.current.leftVisible, rightVisible: current.current.initialLayout ? true : current.current.rightVisible }, Object.fromEntries(PANEL_IDS.map(id => [id, t(titles[id])])) as Record<PanelId, string>);
    load(initial ?? canonical, true);
  };

  // The persisted layout owns startup visibility and active tabs. Props only represent later commands.
  useEffect(() => {
    const changed = observed.current.left !== props.leftVisible || observed.current.right !== props.rightVisible;
    observed.current.left = props.leftVisible; observed.current.right = props.rightVisible;
    if (!changed || !api.current || restoring.current || current.current.locked) return;
    for (const [key, ids, visible] of [["left", ["connections", "explorer"], props.leftVisible], ["right", ["variables", "pynia"], props.rightVisible]] as const) {
      if (synchronized.current[key] === visible) continue;
      synchronized.current[key] = visible;
      for (const id of ids) { if (visible) add(id); else hide(id); }
    }
    synchronize();
  }, [props.leftVisible, props.rightVisible]);
  useEffect(() => {
    const changed = observed.current.bottom !== props.activeBottom; observed.current.bottom = props.activeBottom;
    if (!changed || !api.current || restoring.current || current.current.locked || synchronized.current.bottom === props.activeBottom) return;
    synchronized.current.bottom = props.activeBottom; add(props.activeBottom).api.setActive();
  }, [props.activeBottom]);
  useEffect(() => {
    const changed = observed.current.activeRight !== props.activeRight; observed.current.activeRight = props.activeRight;
    if (!changed || !api.current || restoring.current || current.current.locked || synchronized.current.activeRight === props.activeRight) return;
    synchronized.current.activeRight = props.activeRight; add(props.activeRight).api.setActive();
  }, [props.activeRight]);
  useEffect(() => { api.current?.panels.forEach(panel => { if (isPanelId(panel.id)) panel.api.setTitle(t(titles[panel.id])); }); }, [locale]);
  const initialReset = useRef(props.resetRevision);
  useEffect(() => { if (initialReset.current === props.resetRevision) return; initialReset.current = props.resetRevision; reset(); }, [props.resetRevision]);
  useEffect(() => {
    const update = () => popouts.current?.forEach(view => { if (!view.closed) copyRootPresentation(document, view.document); });
    const observer = new MutationObserver(update); observer.observe(document.documentElement, { attributes: true, attributeFilter: ["style", "data-theme", "lang", "dir"] });
    update(); return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const update = () => popouts.current?.forEach(view => { if (!view.closed) copyLazyStylesheets(document, view.document); });
    const observer = new MutationObserver(update); observer.observe(document.head, { childList: true });
    return () => observer.disconnect();
  }, []);
  useEffect(() => () => { disposed.current = true; ++restoreGeneration.current; if (saveTimer.current) clearTimeout(saveTimer.current); disposables.current.forEach(d => d.dispose()); disposables.current = []; panelVisibility.current?.dispose(); popouts.current?.dispose();nativePopouts.current?.dispose(); }, []);
  const light = props.theme === "light" || (props.theme === "system" && matchMedia("(prefers-color-scheme: light)").matches);
  return <Locked.Provider value={!!props.locked}><Notices.Provider value={message => (current.current.onError ?? current.current.onRestoreError)?.(message)}><Controls.Provider value={controls.current}><Content.Provider value={props.panels}><DockviewReact className={`datapyn-dock${props.locked ? " datapyn-dock-locked" : ""}`} locked={props.locked} disableDnd={props.locked} components={components} defaultTabComponent={Tab} onReady={ready} theme={light ? themeLight : themeDark} rightHeaderActionsComponent={GroupActions} popoutUrl="/popout.html" dndStrategy="pointer" onWillDrop={event => { if (current.current.locked) event.preventDefault(); }} getTabContextMenuItems={({ panel }) => props.locked ? [] : [
    ...(panel.id === "editor" ? [] : [{ label: t("Ocultar painel"), action: () => { if (isPanelId(panel.id)) controls.current?.hide(panel.id); } }, "separator" as const]),
    { label: t(panel.api.isMaximized() ? "Restaurar tamanho do painel" : "Maximizar painel"), disabled: panel.api.location.type !== "grid", action: () => { if (!current.current.locked) panel.api.isMaximized() ? panel.api.exitMaximized() : panel.api.maximize(); } },
    { label: t("Flutuar painel"), disabled: panel.api.location.type === "floating", action: () => { if (isPanelId(panel.id)) controls.current?.float(panel.id); } },
    { label: t("Abrir painel em outra janela"), disabled: panel.api.location.type === "popout", action: () => { if (isPanelId(panel.id)) void controls.current?.popout(panel.id).then(opened => { if (!opened && !current.current.locked) (current.current.onError ?? current.current.onRestoreError)?.(t("Não foi possível abrir outra janela. O painel permanece disponível na janela principal.")); }); } }, "separator",
    { label: t("Acoplar à janela principal"), disabled: panel.api.location.type === "grid", action: () => { if (!current.current.locked) dockGroup(api.current!, panel.group); } },
    ...([ ["left", "Mover para a esquerda"], ["right", "Mover para a direita"], ["above", "Mover para cima"], ["below", "Mover para baixo"], ["within", "Agrupar com a análise"] ] as const).map(([direction, label]) => ({ label: t(label), disabled: panel.id === "editor" && direction === "within", action: () => { if (isPanelId(panel.id)) controls.current?.move(panel.id, direction); } })),
  ]} /></Content.Provider></Controls.Provider></Notices.Provider></Locked.Provider>;
}
