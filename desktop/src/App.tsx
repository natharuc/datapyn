import {translate as translateUi} from "./i18n";
import { lazy, memo, Suspense, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { open, save, confirm } from "@tauri-apps/plugin-dialog";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { requestPermission } from "@tauri-apps/plugin-notification";
import { Activity, AlertTriangle, ChevronDown, ChevronRight, Circle, Database, FileCode2, FolderOpen, GripVertical, Layers3, LoaderCircle, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Play, Plus, RefreshCw, Save, Settings2, Square, Table2, Terminal, Variable, X } from "lucide-react";
import { ContextMenu } from "./ContextMenu";
import { MoreHorizontal, Bell } from "lucide-react";
import logo from "./assets/datapyn-logo.svg";
import { errorText, isDesktop, runtime } from "./runtime";
import { WorkspaceController, encodeDocument, type Block, type SessionDocument, type WorkspaceStorage } from "./workspace";
import { disposeModel, focusEditor, insertInEditor, selectedCode, setCompletionContext,setCompletionContextResolver, editorAction, formatEditor, forceAutocomplete, transformEditorSelection, getRegisteredEditor,revealEditorRange } from "./editorRegistry";
import { BlockSyntaxDiagnostics } from "./BlockSyntaxDiagnostics";
import type { EditorPreferences } from "./MonacoBlock";
import { ResultGrid } from "./ResultGrid";
import { CommandResults } from "./CommandResults";
import { ConnectionDialog } from "./ConnectionDialog";
import { DEFAULT_SHORTCUTS, commandForEvent, EDITOR_COMMANDS, type Command } from "./shortcuts";
import { SettingsDialog } from "./SettingsDialog";
import { DEFAULT_PREFERENCES, loadPreferences, normalizePreferences, savePreferences, type Preferences } from "./preferences";
import { NativeDrafts, type ProfileState, type NativeWorkspaceState } from "./nativeDrafts";
import type {ConfigurationPreview,ConfigurationTransferActions} from "./ConfigurationTransfer";
import { ParameterPanel, useParameterScan, type ParameterDefinition } from "./ParameterPanel";
import { ConnectionsSidebar, ConnectionPicker } from "./ConnectionsSidebar";
import { connections, CONNECTION_MIME, effectiveConnectionColor, type SavedConnection } from "./connections";
import { ObjectExplorer } from "./ObjectExplorer";
import { subscribeServiceEvents, type ServiceEvent } from "./serviceEvents";
import { handlePyniaTool } from "./pyniaTools";
import type { NotificationConfig, NotificationContext, NotificationResult } from "./NotificationsDialog";
import type { ChartConfig, DataView } from "./dataTypes";
import {activeSavedChart,chartSourceView,ChartSourceCache,normalizeChartConfig,type SavedChart} from "./chartModel";
import type { ResultRef, Variable as RuntimeVariable } from "./runtime";
import {identifierAtCursor} from "./sqlIdentifier";
import {setLocale,useTranslation} from "./i18n";
import type {ColumnFormats} from "./gridFormat";
import {documentCopySettings,documentExportSettings,mergeConfigurationDefaults,type ConfigurationDefaults} from "./configurationDefaults";
import {Modal} from "./PanelControls";
import {useOwnerDocumentRevision} from "./useOwnerDocument";
import {readNotificationFlags,saveNotificationFlags} from "./notificationPreferences";
import {startupEditorId} from "./splashProtocol";
import {useStartupSplash} from "./useStartupSplash";
import {PANEL_IDS,isBottomPanel,type BottomPanelId,type DockingControls,type PanelId} from "./dockingLayout";
import {normalizeMainWindowLayout,type MainWindowLayout} from "./windowLayout";
import {useWindowLayout} from "./useWindowLayout";
import {flushNativePopoutLayouts,nativePopoutLabel} from "./nativePopoutLayout";
import { findInDocuments, hasFocusedDocument } from "./documentWindows";
import {OutputRevealTracker} from "./outputReveal";
import {hasVisibleShortcutDialog} from "./shortcutModalGuard";
import {SessionCompletionIndex,SessionLanguageContexts,completionConnectionScope,inheritsSessionScope} from "./sessionCompletion";
import {BlockScopePicker} from "./BlockScopePicker";
import {prepareExecutionContextAfterEvent} from "./executionContextRefresh";
import {blockScopeOptions} from "./blockScopeModel";
import {ScopePreparation} from "./ScopePreparation";
import {connectionPending,SessionConnectionStatus} from "./SessionConnectionStatus";
import {dataImportPending} from "./dataImport";
import {DataImportStatus} from "./DataImportStatus";
import {useTauriUpdates} from "./useTauriUpdates";
import type {ExplorerContext} from "./explorer";
import {exportContext} from "./exportContext";
import {downloadDirectory} from "./queryDownload";
import type {QueryDownloadRequest} from "./QueryDownloadDialog";
import { NotificationCenter, activateNotificationTarget, shouldNotify, shouldDisplayExecutionNotification, type NotificationEntry, type NotificationTarget } from "./executionNotifications";
import { NotificationHistory, NotificationToasts } from "./NotificationCenterView";
import { bindNativeNotifications, focusNativeNotificationWindow, nativeNotificationError, showNativeNotification } from "./nativeExecutionNotifications";
const DataActions = lazy(()=>import("./DataActions").then(m=>({default:m.DataActions})));
const QueryDownloadDialog = lazy(()=>import("./QueryDownloadDialog").then(m=>({default:m.QueryDownloadDialog})));
const VariableInspector = lazy(()=>import("./VariableInspector").then(m=>({default:m.VariableInspector})));
const VariableArchive = lazy(()=>import("./VariableArchive").then(m=>({default:m.VariableArchive})));
const SavedChartView = lazy(()=>import("./SavedChartView").then(m=>({default:m.SavedChartView})));
const PackageManagerDialog = lazy(()=>import("./PackageManagerDialog").then(m=>({default:m.PackageManagerDialog})));
const MarkdownBlock = lazy(()=>import("./MarkdownBlock").then(m=>({default:m.MarkdownBlock})));
const PyniaPanel = lazy(()=>import("./PyniaPanel").then(m=>({default:m.PyniaPanel})));
const PyniaOutputPanel = lazy(()=>import("./PyniaOutputPanel").then(m=>({default:m.PyniaOutputPanel})));
const LayoutDialog = lazy(()=>import("./LayoutDialog").then(m=>({default:m.LayoutDialog})));
const NotificationsDialog = lazy(()=>import("./NotificationsDialog").then(m=>({default:m.NotificationsDialog})));
const VariableSnapshotPanel = lazy(()=>import("./VariableSnapshotPanel").then(m=>({default:m.VariableSnapshotPanel})));
const MonacoBlock = lazy(()=>import("./MonacoBlock").then(m=>({default:m.MonacoBlock})));
const DockingWorkbench = lazy(()=>import("./DockingWorkbench").then(m=>({default:m.DockingWorkbench})));
const EntityInfoDialog=lazy(()=>import("./EntityInfoDialog").then(m=>({default:m.EntityInfoDialog})));
const WorkspaceManagerDialog = lazy(()=>import("./WorkspaceManagerDialog").then(m=>({default:m.WorkspaceManagerDialog})));
const SummaryPanel=lazy(()=>import("./SummaryPanel").then(m=>({default:m.SummaryPanel})));
const AboutDialog=lazy(()=>import("./AboutDialog").then(m=>({default:m.AboutDialog})));
const UpdateDialog=lazy(()=>import("./UpdateDialog").then(m=>({default:m.UpdateDialog})));
const RichResults=lazy(()=>import("./RichResults").then(m=>({default:m.RichResults})));

let storage: WorkspaceStorage | undefined;
try { storage = localStorage; } catch { /* Desktop still supports explicit save. */ }
export const workspace = new WorkspaceController(runtime, storage, {nativePersistence:isDesktop()});
const reportMessage = (message: string) => workspace.message(message);
function blockConnectionConfig(session:SessionDocument,block:Block) {
  const id=block.connection_id ?? session.savedConnectionId;
  return connections.getSnapshot().catalog.connections.find(connection=>connection.id===id)?.config ??
    (block.connection_id===undefined || block.connection_id===session.savedConnectionId ? session.connection : undefined);
}
const blockScope=(session:SessionDocument,block:Block)=>({...completionConnectionScope(session,block,blockConnectionConfig(session,block)),scopeInherited:inheritsSessionScope(block)});
const statusLabel = { idle: "", queued: "Na fila", running: "Executando", cancelling: "Cancelando", succeeded: "Concluído", failed: "Erro", cancelled: "Cancelado" };

function IconButton({ title, children, onClick, disabled = false, className = "" }: { title: string; children: React.ReactNode; onClick?: () => void; disabled?: boolean; className?: string }) {
  return <button type="button" className={`icon-button ${className}`} title={translateUi(title)} aria-label={translateUi(title)} onClick={onClick} disabled={disabled}>{children}</button>;
}

export function App() {
  const {t}=useTranslation();
  const catalogState=useSyncExternalStore(connections.subscribe,connections.getSnapshot);
  const state = useSyncExternalStore(workspace.subscribe, workspace.getSnapshot);
  const session = state.sessions.find((item) => item.id === state.activeId)!;
  const openingConnection=connectionPending(session.connectionState);
  const connectionBlocked=openingConnection||session.connectionState?.phase==="error";
  const retryConnectionId=session.connectionState?.phase==="error"&&session.connectionState.name?session.connectionState.connectionId:session.connectionState?.connectionId??session.savedConnectionId;
  const languageContexts=useRef(new SessionLanguageContexts()),completionIndex=useRef(new SessionCompletionIndex());
  const [languageRevision,setLanguageRevision]=useState(0),[preparationRevision,setPreparationRevision]=useState(0);
  const preparation=useRef(new ScopePreparation(runtime,scope=>{
    if(languageContexts.current.invalidate(scope.sessionId,scope.connectionId,scope.database,scope.schema,scope.blockId,scope.scopeInherited))setLanguageRevision(n=>n+1);
  }));
  const scopeMetadata=useCallback((current:SessionDocument,block:Block)=>{
    const scope=blockScope(current,block);
    return languageContexts.current.get(current.id,scope.connectionId,scope.database,scope.schema,block.id,scope.scopeInherited);
  },[]);
  const applyBlockScope=useCallback(async(sessionId:string,blockId:string,context:ExplorerContext)=>{
    workspace.setContext(sessionId,context,blockId);workspace.focusBlock(sessionId,blockId);
    const current=workspace.session(sessionId),block=current?.blocks.find(item=>item.id===blockId);
    if(!current || !block)return;
    await workspace.ensureSession(sessionId);
    await preparation.current.request({sessionId,blockId,...blockScope(current,block),dbType:blockConnectionConfig(current,block)?.db_type},block.code,true);
    setExplorerRefresh(n=>n+1);
  },[]);
  const diagnosticContext = useCallback((sessionId: string) => { const current = workspace.session(sessionId); return current ? completionIndex.current.diagnosticsContext(current) : { globalImports: "", preamble: "" }; }, []);
  const diagnosticRevisionFor = useCallback((current: SessionDocument, block: Block) => {
    const connection = blockScope(current, block);
    const scope = languageContexts.current.get(current.id, connection.connectionId, connection.database, connection.schema,block.id,connection.scopeInherited);
    return block.language === "python" ? `${scope?.namespaceVersion ?? 0}:${completionIndex.current.diagnosticsRevision(current)}` : String(scope?.version ?? 0);
  }, []);
  useEffect(()=>setCompletionContextResolver(blockId=>{
    const snapshot=workspace.getSnapshot(),active=workspace.session();
    const owner=active?.blocks.some(b=>b.id===blockId) ? active : snapshot.sessions.find(s=>s.blocks.some(b=>b.id===blockId));
    return owner ? completionIndex.current.context(owner,blockId,languageContexts.current,blockConnectionConfig(owner,owner.blocks.find(b=>b.id===blockId)!)) : undefined;
  }),[]);
  useEffect(()=>{
    let disposed=false,cleanup:(()=>void)|undefined;
    void runtime.subscribe(event=>{
      if(event.event==="execution.finished" && event.payload.context_change){
        const current=workspace.session(event.payload.session_id);
        const blockId=event.payload.block_id ?? (current?.currentExecutionId===event.payload.execution_id?current.currentBlockId:undefined);
        if(!blockId)return;
        const block=current?.blocks.find(item=>item.id===blockId);
        event={...event,payload:{...event.payload,block_id:blockId,scope_inherited:event.payload.scope_inherited ?? (block?inheritsSessionScope(block):undefined)}};
      }
      preparation.current.accept(event);
      if(languageContexts.current.accept(event))setLanguageRevision(n=>n+1);
      if(event.event==="language.context_updated" && event.payload.metadata_invalidated){blockScopeOptions.clear();setPreparationRevision(n=>n+1);setExplorerRefresh(n=>n+1);}
      if(event.event==="execution.finished" && event.payload.context_change){
        blockScopeOptions.clear();setPreparationRevision(n=>n+1);setExplorerRefresh(n=>n+1);
        void prepareExecutionContextAfterEvent(event.payload,id=>workspace.session(id),preparation.current).catch(failure=>reportMessage(errorText(failure)));
      }
      if(event.event==="language.context_updated" && event.payload.metadata_state==="error")reportMessage(event.payload.schema_error || translateUi("Não foi possível carregar os metadados SQL."));
    }).then(fn=>{if(disposed)fn();else cleanup=fn;});
    return()=>{disposed=true;cleanup?.();};
  },[]);
  const [preferences, setPreferences] = useState(loadPreferences);
  const [leftVisible, setLeftVisible] = useState(preferences.leftVisible), [rightVisible, setRightVisible] = useState(preferences.rightVisible);
  const [connectionDialog, setConnectionDialog] = useState(false), [settingsDialog, setSettingsDialog] = useState(false);
  const [aboutDialog,setAboutDialog]=useState(false);
  const [updateDialog,setUpdateDialog]=useState(false);
  const [connectionPicker, setConnectionPicker] = useState<string>(), [connectionsManager, setConnectionsManager] = useState(false);
  const [explorerRefresh, setExplorerRefresh] = useState(0);
  const connectionSignatures=useRef<Map<string,string>>();
  useEffect(()=>{
    const next=new Map(catalogState.catalog.connections.map(item=>[item.id,JSON.stringify(item.config)]));
    const previous=connectionSignatures.current;connectionSignatures.current=next;
    if(!previous)return;
    const changed=new Set([...previous.keys(),...next.keys()].filter(id=>previous.get(id)!==next.get(id)));
    if(!changed.size)return;
    for(const current of workspace.getSnapshot().sessions){
      let affected=false;
      for(const id of changed){
        languageContexts.current.invalidateConnection(current.id,id);
        if(current.savedConnectionId===id || current.blocks.some(block=>block.connection_id===id))affected=true;
      }
      if(affected)preparation.current.reset(current.id);
    }
    blockScopeOptions.clear();setLanguageRevision(n=>n+1);setPreparationRevision(n=>n+1);setExplorerRefresh(n=>n+1);
  },[catalogState.catalog]);
  const [packageDialog, setPackageDialog] = useState(false);
  const [gridView, setGridView] = useState<DataView>();
  const gridViewOwner=useRef<{sessionId:string;resultId:string}>();
  const [queryDownload,setQueryDownload]=useState<QueryDownloadRequest>();
  const [formatColumnRequest,setFormatColumnRequest] = useState<{sessionId:string;resultId:string;column:string;revision:number}>();
  const [dockLayout,setDockLayout]=useState<unknown>(),[dockReset,setDockReset]=useState(0);
  const docking=useRef<DockingControls>(),[dockControls,setDockControls]=useState<DockingControls>();
  const [dockPanels,setDockPanels]=useState<PanelId[]>([...PANEL_IDS]),[layoutDialog,setLayoutDialog]=useState(false);
  const [visibleDockPanels,setVisibleDockPanels]=useState<PanelId[]>([]);
  const [mainWindowLayout,setMainWindowLayout]=useState<MainWindowLayout>();
  const dockPanelsChanged=useCallback((ids:PanelId[])=>{setDockPanels(ids);setLeftVisible(ids.includes("connections") || ids.includes("explorer"));setRightVisible(ids.includes("variables") || ids.includes("pynia"));},[]);
  const [entityInfo,setEntityInfo]=useState<{identifier:string;blockId:string}>();
  const [tabContext,setTabContext]=useState<{id:string;x:number;y:number}>();
  const [closingMany,setClosingMany]=useState<string[]>(),[editingChart,setEditingChart]=useState<{id:string;title:string}>();
  const activeChart = activeSavedChart(session.extras);
  const chartSources=useRef(new ChartSourceCache());
  const setActiveChart = (id?:string,sessionId=workspace.getSnapshot().activeId) => workspace.patchSession(sessionId,s=>s.extras.desktop_chart_id === (id ?? null) ? s : {...s,modified:true,extras:{...s.extras,desktop_chart_id:id ?? null}});
  const [appMenu,setAppMenu]=useState<{owner:Document;anchor:{x:number;y:number};button:HTMLElement}>();
  const [rightPanel,setRightPanel] = useState<"variables"|"pynia">("variables");
  const [recentFiles,setRecentFiles] = useState<string[]>(()=>{try{return JSON.parse(localStorage.getItem("datapyn.desktop.recent-files.v1") ?? "[]");}catch{return [];}});
  const [recentVisible,setRecentVisible] = useState(false);
  const [notificationDialog,setNotificationDialog] = useState(false), [snapshotVisible,setSnapshotVisible] = useState(false);
  const [notificationHistory,setNotificationHistory] = useState(false);
  const [notificationCenter] = useState(() => new NotificationCenter());
  const notificationState = useSyncExternalStore(notificationCenter.subscribe, notificationCenter.getSnapshot);
  const notificationActivation = useRef<(target: NotificationTarget) => Promise<void>>(async () => {});
  const notificationNavigation = useRef(0);
  const lastNotificationContexts = useRef(new Map<string, NotificationContext>());
  const [profile,setProfile] = useState<ProfileState>(), [workspaceManager,setWorkspaceManager] = useState(false), [switchingProfile,setSwitchingProfile] = useState(false);
  const windowLayout=useWindowLayout(mainWindowLayout,profile?.active_id,setMainWindowLayout);
  const [preparedSession,setPreparedSession] = useState<string>();
  const popoutKeyboard=useRef<(event:KeyboardEvent)=>void>();
  const attachPopoutKeyboard=useCallback((target:Window)=>{const handle=(event:KeyboardEvent)=>popoutKeyboard.current?.(event);target.addEventListener("keydown",handle,true);return()=>target.removeEventListener("keydown",handle,true);},[]);
  const [profileLoadError,setProfileLoadError]=useState(""),[profileRetry,setProfileRetry]=useState(0);
  const [startupLayout,setStartupLayout]=useState<string>(),[startupEditors,setStartupEditors]=useState<ReadonlySet<string>>(()=>new Set());
  const [startupFilesReady,setStartupFilesReady]=useState(!isDesktop()),[startupFilesError,setStartupFilesError]=useState("");
  const requiredEditor=profile ? startupEditorId(session.blocks,session.focusedBlockId,session.maximizedBlockId) : undefined;
  const startupActive=useStartupSplash({runtime:state.runtimeStatus,runtimeError:state.message,profileError:profileLoadError || startupFilesError,profile:Boolean(profile),layout:startupLayout === profile?.active_id && windowLayout.ready,editor:!requiredEditor || startupEditors.has(`${profile?.active_id}:${requiredEditor}`),files:startupFilesReady,onRetry:()=>{setProfileLoadError("");setStartupFilesError("");setStartupFilesReady(false);setProfileRetry(n=>n+1);if(state.runtimeStatus === "unavailable")void workspace.retryRuntime();}});
  const startupEditorInitialized=useCallback((id:string)=>{if(!startupActive)return;const key=`${profile?.active_id}:${id}`;setStartupEditors(previous=>previous.has(key) ? previous : new Set([...previous,key]));},[profile?.active_id,startupActive]);
  const updates=useTauriUpdates(Boolean(profile && !startupActive));
  const [closingWorkspace,setClosingWorkspace]=useState(false);
  const editingLocked=switchingProfile || closingWorkspace || updates.state.phase === "installing";
  useEffect(()=>{workspace.setEditingLocked(editingLocked);},[editingLocked,updates.state.phase]);
  const outputReveals=useRef(new OutputRevealTracker()),outputRevealAllowed=useRef(false);
  outputRevealAllowed.current=Boolean(profile && startupLayout === profile.active_id && !editingLocked);
  const workspaceExtras=useRef<Record<string,unknown>>({}),layoutExtras=useRef<Record<string,unknown>>({});
  const configurationDefaults=(workspaceExtras.current.imported_defaults ?? {}) as ConfigurationDefaults;
  const exportOptions=documentExportSettings(session.extras,configurationDefaults),copyOptions=documentCopySettings(session.extras,configurationDefaults);
  const updateConfigurationDefaults=(patch:ConfigurationDefaults)=>{workspaceExtras.current.imported_defaults=mergeConfigurationDefaults((workspaceExtras.current.imported_defaults ?? {}) as ConfigurationDefaults,patch);};
  const captureLayout=useRef<()=>unknown>(()=>undefined),flushWorkspace=useRef<()=>Promise<void>>(()=>Promise.resolve());
  const nativeDrafts=useRef(new NativeDrafts(runtime,failure=>reportMessage(errorText(failure))));
  const serviceHandler = useRef<(event:ServiceEvent)=>void>(()=>{});
  const notify = (title:string,message:string,success:boolean,sessionId:string) => {
    const source=workspace.session(sessionId);
    if(!source || !profile)return;
    const target={workspace_id:profile.active_id,session_id:source.id,block_id:source.focusedBlockId,execution_id:crypto.randomUUID()};
    const display=shouldDisplayExecutionNotification(target,{workspaceId:profile.active_id,sessionId:workspace.getSnapshot().activeId,focused:hasFocusedDocument()});
    notificationCenter.publish({title,message,success,target},{toast:display,read:!display});
  };
  const notificationContext = (target:SessionDocument,success=true):NotificationContext => ({success,tab_name:target.title,
    rows:target.results.at(-1)?.row_count ?? 0,blocks:target.blocks.length,block_name:target.blocks.find(b=>b.id === target.focusedBlockId)?.block_name,
    connection:target.connection?.name,database:target.database,type:target.blocks.find(b=>b.id === target.focusedBlockId)?.language,error:target.blocks.find(b=>b.id === target.focusedBlockId)?.error,result_id:target.results.at(-1)?.result_id,...lastNotificationContexts.current.get(target.id)});
  notificationActivation.current = async target => {
    if (!activateNotificationTarget(workspace, profile?.active_id, target)) {
      reportMessage(t("A sessão ou o bloco desta notificação não está disponível neste workspace.")); return;
    }
    setNotificationHistory(false); notificationCenter.markRead(JSON.stringify(target)); notificationCenter.dismiss(JSON.stringify(target));
    const revision = ++notificationNavigation.current;
    if (isDesktop()) {
      try { await focusNativeNotificationWindow(); }
      catch (failure) { reportMessage(errorText(failure)); }
    }
    const stillSelected = () => !workspace.isEditingLocked() && notificationCenter.getWorkspaceIdentity() === target.workspace_id && notificationNavigation.current === revision && workspace.getSnapshot().activeId === target.session_id && workspace.session(target.session_id)?.focusedBlockId === target.block_id;
    if (!stillSelected()) return;
    docking.current?.show("editor");
    // pendingFocus survives lazy mounting; focus only after React reveals the tab/block.
    requestAnimationFrame(() => {
      if (!stillSelected()) return;
      focusEditor(target.block_id);
      const node=findInDocuments(`[data-block-id="${CSS.escape(target.block_id)}"]`),view=node?.ownerDocument.defaultView,label=view && nativePopoutLabel(view);
      if(isDesktop() && label)void focusNativeNotificationWindow(label).catch(failure=>reportMessage(errorText(failure)));
    });
  };
  const openNotification = (entry: NotificationEntry) => { if (entry.target) void notificationActivation.current(entry.target); };
  useEffect(() => {
    notificationCenter.setWorkspace(profile?.active_id);
    workspace.setWorkspaceIdentity(profile?.active_id);
    notificationNavigation.current++;
    lastNotificationContexts.current.clear();
    if (!profile || !isDesktop()) return;
    let disposed = false, cleanup: (() => void) | undefined;
    void bindNativeNotifications(target => notificationActivation.current(target), (target, message) => notificationCenter.deliveryError(target, message))
      .then(stop => { if (disposed) stop(); else cleanup = stop; }).catch(failure => reportMessage(nativeNotificationError(failure)));
    return () => { disposed = true; cleanup?.(); };
  }, [notificationCenter, profile?.active_id]);
  workspace.onQueueFinished = (target,success,completion)=>{
    lastNotificationContexts.current.set(target.id,completion.context);
    if (!profile) return;
    const destination: NotificationTarget = { workspace_id: completion.workspaceId ?? profile.active_id, session_id: target.id, block_id: completion.blockId, execution_id: completion.executionId };
    const response: NotificationResult = completion.notification ?? {
      enabled: preferences.notifications, sound: preferences.notificationSound, success, suppressed: false, send_external: false, channels: {telegram:false,email:false},
      title: completion.status === "cancelled" ? t("Execução cancelada") : `${completion.context.block_name || completion.context.type || target.title} · ${success ? t("Concluído") : t("Erro")}`,
      message: completion.status === "cancelled" ? t("Execução cancelada.") : completion.context.error || (success ? t("Execução concluída.") : t("Não foi possível concluir a execução.")),
    };
    if (!shouldNotify(response)) return;
    const display = shouldDisplayExecutionNotification(destination,{workspaceId:profile.active_id,sessionId:workspace.getSnapshot().activeId,focused:hasFocusedDocument()});
    const entry = notificationCenter.publish({ title:response.title,message:response.message,color:response.color || (completion.status === "cancelled" ? undefined : success ? "#4ba979" : "#df646b"),success,target:destination,status:completion.status },{toast:display,read:!display});
    if (!entry || !display) return;
    if (isDesktop()) void showNativeNotification(entry,response.sound).catch(failure=>notificationCenter.deliveryError(destination,nativeNotificationError(failure)));
  };
  useEffect(() => {
    if (!profile) return;
    let disposed=false,cleanup:(()=>void)|undefined;
    void runtime.subscribe(event=>{
      if (disposed || event.event !== "notifications.delivery_finished" || !event.payload.block_id || !event.payload.workspace_id) return;
      const errors=Object.entries(event.payload.deliveries).filter(([,delivery])=>delivery.status === "failed").map(([channel])=>`${channel}: ${t("Não foi possível entregar a notificação.")}`);
      if(errors.length)notificationCenter.deliveryError({workspace_id:event.payload.workspace_id,session_id:event.payload.session_id,block_id:event.payload.block_id,execution_id:event.payload.execution_id},errors.join(" "));
    }).then(stop=>{if(disposed)stop();else cleanup=stop;});
    return()=>{disposed=true;cleanup?.();};
  },[notificationCenter,profile?.active_id,t]);
  serviceHandler.current = event=>{
    if(event.event !== "pynia.tool_request" || typeof event.payload.request_id !== "string") return;
    void handlePyniaTool(workspace,event,{notify:(title,message,success)=>notify(title,message,success,event.payload.session_id as string),extraContext:id=>({charts:workspace.session(id)?.extras.charts ?? []}),chart:async(args,sessionId)=>{
      const target=workspace.session(sessionId);if(!target)throw new Error("Sessão não encontrada.");
      const saved=(target.extras.charts ?? []) as SavedChart[],operation=args.operation ?? "list";
      if(operation === "list")return{charts:saved,chart_sources:target.results.map(r=>({label:r.variable_name,rows:r.row_count,columns:r.columns.map(c=>c.name),numeric_columns:r.columns.filter(c=>/int|float|decimal|double|numeric|number|real/i.test(c.dtype)).map(c=>c.name)}))};
      const found=typeof args.chart_id === "string" ? saved.find(c=>c.id === args.chart_id) : saved[typeof args.chart_index === "number" ? args.chart_index : 0];
      if(operation === "get")return found ?? {error:"Gráfico não encontrado"};
      if(operation === "delete"){workspace.patchSession(sessionId,s=>({...s,modified:true,extras:{...s.extras,charts:saved.filter(c=>c.id !== found?.id)}}));return{deleted:!!found};}
      if(operation === "export"){if(!found)throw new Error("Gráfico não encontrado.");if(typeof args.path !== "string")throw new Error("Informe o destino do gráfico.");const savedView=(target.extras.table_views as Record<string,DataView>|undefined)?.[found.variable_name];return runtime.request("result.chart_export",{session_id:sessionId,variable_name:found.variable_name,...chartSourceView(found.config,savedView),config:found.config,path:args.path,format:args.format ?? "html"});}
      if(operation !== "create" && operation !== "edit")throw new Error(`Operação de gráfico não suportada: ${String(operation)}`);
      if(operation === "edit" && !found)throw new Error("Gráfico não encontrado.");
      const config=(args.config && typeof args.config === "object" ? args.config : args) as ChartConfig;
      const name=String(args.variable_name ?? config.source_label ?? found?.variable_name ?? target.results.at(-1)?.variable_name ?? "df");
      const chartTitle=String(config.title ?? args.title ?? found?.title ?? `Gráfico ${saved.length+1}`);
      const source=target.results.find(r=>r.variable_name === name);
      const chart:SavedChart = {id:operation === "edit" ? found!.id : crypto.randomUUID(),title:chartTitle,variable_name:name,config:{...(operation === "edit" ? found!.config : source ? normalizeChartConfig(source) : {}),...config,title:chartTitle,source_label:name}};
      workspace.patchSession(sessionId,s=>({...s,modified:true,extras:{...s.extras,charts:operation === "edit"?saved.map(c=>c.id === chart.id?chart:c):[...saved,chart],desktop_chart_id:chart.id}}));workspace.activate(sessionId);activateBottom("results");return{chart};
    }}).then(result=>runtime.request("pynia.tool_reply",{request_id:event.payload.request_id,result}),failure=>runtime.request("pynia.tool_reply",{request_id:event.payload.request_id,error:errorText(failure)})).catch(failure=>reportMessage(errorText(failure)));
  };
  useEffect(()=>{let disposed=false,cleanup:(()=>void)|undefined;void subscribeServiceEvents(event=>serviceHandler.current(event)).then(fn=>{if(disposed)fn();else cleanup=fn;});return()=>{disposed=true;cleanup?.();};},[]);
  const [closingId, setClosingId] = useState<string>(), [editingTitle, setEditingTitle] = useState<string>();
  const [titleDraft, setTitleDraft] = useState("");
  const [panel, setPanel] = useState<BottomPanelId>("results"), [resultHeight, setResultHeight] = useState(preferences.resultHeight);
  const activateBottom=useCallback((next:BottomPanelId)=>{docking.current?.show(next);setPanel(next);},[]);
  const toggleDockGroup=(ids:PanelId[])=>{if(editingLocked || !docking.current)return;const visible=ids.some(id=>dockPanels.includes(id));ids.forEach(id=>visible ? docking.current?.hide(id) : docking.current?.show(id));};
  const restoreDockLayout=(resetSizes=false)=>{
    if(editingLocked)return;
    if(resetSizes){setPreferences(p=>({...p,leftWidth:DEFAULT_PREFERENCES.leftWidth,rightWidth:DEFAULT_PREFERENCES.rightWidth,resultHeight:DEFAULT_PREFERENCES.resultHeight}));setResultHeight(DEFAULT_PREFERENCES.resultHeight);}
    if(docking.current)docking.current.reset(resetSizes ? {leftWidth:DEFAULT_PREFERENCES.leftWidth,rightWidth:DEFAULT_PREFERENCES.rightWidth,resultHeight:DEFAULT_PREFERENCES.resultHeight} : undefined);else setDockReset(n=>n+1);
    workspace.maximizeBlock(workspace.getSnapshot().activeId);
  };
  const [periodicSeconds, setPeriodicSeconds] = useState(30), [elapsed, setElapsed] = useState(0);
  const [activeResult, setActiveResult] = useState<Record<string, string>>({}), [copySignal, setCopySignal] = useState(0);
  const [shortcuts, setShortcuts] = useState<Record<Command, string>>(() => {
    try { return { ...DEFAULT_SHORTCUTS, ...JSON.parse(localStorage.getItem("datapyn.desktop.shortcuts.v1") ?? "{}") }; } catch { return DEFAULT_SHORTCUTS; }
  });
  const codeArea = useRef<HTMLDivElement>(null);
  const activeSessionRef = useRef(session); activeSessionRef.current = session;
  const sharedParameters = (session.extras.shared_parameters ?? []) as ParameterDefinition[];
  const sessionCodes=useMemo(()=>session.blocks.map(b=>b.code),[session.blocks]);
  const charts = (session.extras.charts ?? []) as SavedChart[];
  useParameterScan(sessionCodes, sharedParameters, true, preferences.sharedDelimiter,
    parameters => workspace.patchSession(session.id, s => ({ ...s, modified: true, extras: { ...s.extras, shared_parameters: parameters } })));
  useEffect(() => {
    const root = document.documentElement;
    root.style.fontFamily = `${preferences.uiFont}, sans-serif`; root.style.fontSize = `${preferences.uiFontSize}px`;
    root.dataset.theme = preferences.theme === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : preferences.theme;
    root.style.setProperty("--editor-font", preferences.editorFont);
    setLocale(preferences.locale);
    workspace.setSharedDelimiter(preferences.sharedDelimiter);
    root.style.setProperty("--left-width", `${preferences.leftWidth}px`); root.style.setProperty("--right-width", `${preferences.rightWidth}px`);
    try { savePreferences({ ...preferences, leftVisible, rightVisible, resultHeight }); } catch { /* Explicit .dpw saves remain available. */ }
  }, [preferences, leftVisible, rightVisible, resultHeight]);
  useEffect(()=>{if(preferences.theme !== "system")return;const query=matchMedia("(prefers-color-scheme: light)"),update=()=>{document.documentElement.dataset.theme=query.matches?"light":"dark";};query.addEventListener("change",update);return()=>query.removeEventListener("change",update);},[preferences.theme]);
  useEffect(() => {
    let current=true;
    if (state.runtimeStatus === "ready" && profile && !switchingProfile) run(workspace.prepareSession(session.id).then(()=>{if(current)setPreparedSession(`${profile.active_id}:${session.id}`);}));
    requestAnimationFrame(() => focusEditor(session.focusedBlockId));
    return()=>{current=false;};
  }, [session.id, session.savedConnectionId,state.runtimeStatus,profile?.active_id,switchingProfile]);
  const applyProfile=(loaded:ProfileState,defaults:ConfigurationDefaults={})=>{
    chartSources.current.clear();
    workspaceExtras.current=Object.fromEntries(Object.entries(loaded.state ?? {}).filter(([key])=>!["documents","activeIndex","preferences","shortcuts","layout","saved_at","revision"].includes(key)));
    updateConfigurationDefaults(mergeConfigurationDefaults(defaults,(workspaceExtras.current.imported_defaults ?? {}) as ConfigurationDefaults));
    layoutExtras.current=loaded.state?.layout ?? {};
    setMainWindowLayout(normalizeMainWindowLayout(loaded.state?.layout?.mainWindow));docking.current=undefined;setDockControls(undefined);captureLayout.current=()=>undefined;
    outputRevealAllowed.current=false;outputReveals.current.clear();setVisibleDockPanels([]);
    state.sessions.forEach(s=>s.blocks.forEach(b=>disposeModel(b.id)));
    if(loaded.state?.documents)workspace.restoreSnapshot(loaded.state);else if(profile)workspace.restoreSnapshot({});else workspace.restoreBrowserDraftMigration();
    const prefs=normalizePreferences((loaded.state?.preferences ?? DEFAULT_PREFERENCES) as Partial<Preferences>);
    if(loaded.state || profile){setPreferences(prefs);setLeftVisible(prefs.leftVisible);setRightVisible(prefs.rightVisible);setResultHeight(prefs.resultHeight);setShortcuts({...DEFAULT_SHORTCUTS,...loaded.state?.shortcuts} as Record<Command,string>);}
    setDockLayout(loaded.state?.layout?.docking);
    const restoredPanel=loaded.state?.layout?.panel;setPanel(isBottomPanel(restoredPanel) ? restoredPanel : "results");setRightPanel(loaded.state?.layout?.rightPanel === "pynia" ? "pynia" : "variables");
    setActiveResult({});setProfile(loaded);setGridView(undefined);setFormatColumnRequest(undefined);setExplorerRefresh(n=>n+1);
  };
  const applyProfileRef=useRef(applyProfile);applyProfileRef.current=applyProfile;
  useEffect(()=>{if(state.runtimeStatus !== "ready" || profile)return;let active=true;setProfileLoadError("");void Promise.all([nativeDrafts.current.load(),connections.refresh(),runtime.request<{defaults:ConfigurationDefaults}>("configurations.defaults.get")]).then(([loaded,,settings])=>{if(active)applyProfileRef.current(loaded,settings.defaults);}).catch(failure=>{if(active){setProfileLoadError(errorText(failure));reportMessage(errorText(failure));}});return()=>{active=false;};},[state.runtimeStatus,profile,profileRetry]);
  flushWorkspace.current=async()=>{workspace.persist();if(profile){await flushNativePopoutLayouts();const mainWindow=await windowLayout.capture().catch(()=>mainWindowLayout);nativeDrafts.current.schedule(profile.active_id,{...workspaceExtras.current,...workspace.nativeSnapshot(),preferences:{...preferences,leftVisible,rightVisible,resultHeight},shortcuts:{...shortcuts},layout:{...layoutExtras.current,panel,rightPanel,mainWindow,docking:captureLayout.current() ?? dockLayout}});}await nativeDrafts.current.flush();if(state.runtimeStatus === "ready"){const flushed=await runtime.request<{sessions:Array<{error?:string;saved?:boolean;session_id:string}>}>("system.flush_workspace");const failures=flushed.sessions.filter(s=>s.error);if(failures.length)throw new Error(failures.map(s=>`${s.session_id}: ${s.error}`).join("; "));}};
  useEffect(()=>{if(!profile || switchingProfile || state.runtimeStatus !== "ready" || startupLayout !== profile.active_id || !windowLayout.ready)return;const snapshot:NativeWorkspaceState={...workspaceExtras.current,...workspace.nativeSnapshot(),preferences:{...preferences,leftVisible,rightVisible,resultHeight},shortcuts:{...shortcuts},layout:{...layoutExtras.current,panel,rightPanel,mainWindow:mainWindowLayout,docking:dockLayout}};nativeDrafts.current.schedule(profile.active_id,snapshot);},[profile?.active_id,state.documentRevision,preferences,shortcuts,leftVisible,rightVisible,resultHeight,panel,rightPanel,dockLayout,mainWindowLayout,startupLayout,windowLayout.ready,switchingProfile,state.runtimeStatus]);
  useEffect(()=>{if(state.runtimeStatus !== "ready" || !profile)return;let active=true;void readNotificationFlags(runtime).then(flags=>{if(active)setPreferences(p=>({...p,...flags}));}).catch(failure=>reportMessage(errorText(failure)));return()=>{active=false;};},[state.runtimeStatus,profile?.active_id]);
  useEffect(()=>{if(state.runtimeStatus === "ready" && profile)void runtime.request("connection.idle_timeout",{seconds:preferences.connectionIdleSeconds}).catch(failure=>reportMessage(errorText(failure)));},[state.runtimeStatus,profile?.active_id,preferences.connectionIdleSeconds]);
  useEffect(()=>{
    if(!isDesktop())return;let disposed=false,unlisten:(()=>void)|undefined,closing=false;
    void getCurrentWindow().onCloseRequested(event=>{
      event.preventDefault();if(closing)return;closing=true;setClosingWorkspace(true);workspace.setEditingLocked(true);
      void (async()=>{const running=workspace.getSnapshot().sessions.filter(s=>s.busy);if(running.length){const accepted=await confirm(translateUi("Há execuções em andamento. Cancelar e fechar?"),{title:translateUi("Execução em andamento"),kind:"warning"});if(!accepted){closing=false;setClosingWorkspace(false);workspace.setEditingLocked(false);return;}await Promise.all(running.map(s=>workspace.cancel(s.id)));}await flushWorkspace.current();await getCurrentWindow().destroy();})().catch(failure=>{closing=false;setClosingWorkspace(false);workspace.setEditingLocked(false);reportMessage(`Não foi possível salvar o workspace antes de fechar: ${errorText(failure)}`);});
    }).then(fn=>{if(disposed)fn();else unlisten=fn;});
    return()=>{disposed=true;unlisten?.();};
  },[]);
  useEffect(()=>{
    if(!profile || !catalogState.loaded || switchingProfile)return;
    const target=workspace.session();if(!target || target.savedConnectionId || !target.extras.connection_name)return;
    const matching=catalogState.catalog.connections.filter(c=>c.name === target.extras.connection_name && (target.extras.connection_group == null || (catalogState.catalog.groups.find(g=>g.id === c.group_id)?.name ?? "") === target.extras.connection_group));
    if(matching.length === 1)workspace.patchSession(target.id,s=>({...s,savedConnectionId:matching[0].id}));
  },[profile?.active_id,session.id,catalogState,switchingProfile]);
  const selectProfile=async(profileId:string)=>{
    if(state.sessions.some(s=>s.busy||dataImportPending(s.dataImport)))throw new Error("Aguarde ou cancele as execuções e importações antes de trocar de workspace.");
    setSwitchingProfile(true);workspace.setEditingLocked(true);try{await flushWorkspace.current();const selected=await nativeDrafts.current.select(profileId);const [,settings]=await Promise.all([connections.refresh(),runtime.request<{defaults:ConfigurationDefaults}>("configurations.defaults.get")]);applyProfile(selected,settings.defaults);setWorkspaceManager(false);}finally{workspace.setEditingLocked(false);setSwitchingProfile(false);}
  };
  const configurationActions:ConfigurationTransferActions={
    busy:!profile || switchingProfile || state.sessions.some(s=>s.busy||dataImportPending(s.dataImport)),
    inspect:path=>runtime.request<ConfigurationPreview>("configurations.inspect",{path}),
    export:async path=>{
      await flushWorkspace.current();
      return runtime.request("configurations.export",{path,preferences:{...preferences,leftVisible,rightVisible,resultHeight},shortcuts,defaults:workspaceExtras.current.imported_defaults ?? {}});
    },
    import:async(path,preview)=>{
      if(!profile || switchingProfile || workspace.getSnapshot().sessions.some(s=>s.busy||dataImportPending(s.dataImport)))throw new Error(t("Finalize as execuções e importações antes de transferir configurações."));
      setSwitchingProfile(true);workspace.setEditingLocked(true);
      try{
        await flushWorkspace.current();
        const imported=await runtime.request<ConfigurationPreview>("configurations.import",{path,preview_token:preview.preview_token});
        await connections.refresh();
        const nextPreferences=normalizePreferences({...preferences,...imported.preferences} as Partial<Preferences>);
        const nextShortcuts={...shortcuts,...imported.shortcuts} as Record<Command,string>;
        updateConfigurationDefaults(imported.defaults ?? {});
        setPreferences(nextPreferences);setLeftVisible(nextPreferences.leftVisible);setRightVisible(nextPreferences.rightVisible);setResultHeight(nextPreferences.resultHeight);setShortcuts(nextShortcuts);
        nativeDrafts.current.schedule(profile.active_id,{...workspaceExtras.current,...workspace.nativeSnapshot(),preferences:{...nextPreferences},shortcuts:nextShortcuts,layout:{...layoutExtras.current,panel,rightPanel,mainWindow:mainWindowLayout,docking:captureLayout.current() ?? dockLayout}});
        await nativeDrafts.current.flush();
        setExplorerRefresh(n=>n+1);reportMessage(translateUi("Configurações importadas e aplicadas."));
      }finally{workspace.setEditingLocked(false);setSwitchingProfile(false);}
    },
  };
  useEffect(() => {
    if (!session.busy || !session.executionStartedAt) { setElapsed(session.lastDurationMs ?? 0); return; }
    const update = () => setElapsed(Date.now() - session.executionStartedAt!); update();
    const timer = setInterval(update, 100); return () => clearInterval(timer);
  }, [session.busy, session.executionStartedAt, session.lastDurationMs]);

  useEffect(() => { void workspace.initialize(); const persist = () => workspace.persist(); window.addEventListener("beforeunload", persist); return () => window.removeEventListener("beforeunload", persist); }, []);
  const run = useCallback((task: Promise<unknown>) => { void task.catch((failure) => reportMessage(errorText(failure))); }, []);
  const showResult = (result: ResultRef, variables?: RuntimeVariable[], generatedCode?:string) => {
    if(generatedCode){const block=workspace.addBlock(session.id,"python",generatedCode,session.focusedBlockId);requestAnimationFrame(()=>{if(workspace.getSnapshot().activeId===session.id)focusEditor(block.id);});}
    workspace.patchSession(session.id,s=>({...s,results:[...s.results.filter(r=>r.result_id !== result.result_id),result],variables:variables ?? s.variables,resultRevision:s.resultRevision+1}));
    setActiveResult(previous=>({...previous,[session.id]:result.result_id}));if(workspace.getSnapshot().activeId===session.id){setActiveChart(undefined);activateBottom("results");}
  };
  const createChart = () => {
    if (!result) return;
    const title=`Gráfico ${charts.length+1}`;
    const chart: SavedChart = {id:crypto.randomUUID(),title,variable_name:result.variable_name,config:normalizeChartConfig(result,{title,source_label:result.variable_name})};
    workspace.patchSession(session.id,s=>({...s,modified:true,extras:{...s.extras,charts:[...charts,chart]}}));
    setActiveChart(chart.id);activateBottom("results");
  };
  const connectSaved = useCallback(async (connection: SavedConnection, newTab = false) => {
    const target = newTab ? workspace.createSession() : workspace.session(); if (!target) return;
    await workspace.connectSaved(target.id, connection.id, connection.name);
    workspace.patchSession(target.id, s => ({ ...s, connection: {...(s.connection??connection.config),name:connection.name},extras:{...s.extras,connection_name:connection.name,connection_group:connections.getSnapshot().catalog.groups.find(g=>g.id === connection.group_id)?.name ?? ""} }));
    setExplorerRefresh(n => n + 1);
    requestAnimationFrame(() => focusEditor(workspace.session(target.id)?.focusedBlockId ?? target.focusedBlockId));
  }, []);
  const runCurrent = useCallback((advance = false) => {
    const current = workspace.session(); if (!current) return;
    const id = current.focusedBlockId;
    const task = workspace.runBlock(current.id, id, undefined, advance);
    run(task.then(() => { if (advance) requestAnimationFrame(() => focusEditor(workspace.session(current.id)?.focusedBlockId ?? id)); }));
  }, [run]);
  const downloadBlock = useCallback(async(blockId:string)=>{
    const current=workspace.session(),block=current?.blocks.find(b=>b.id === blockId);if(!current || !block || !isDesktop())return;
    const defaults=(workspaceExtras.current.imported_defaults ?? {}) as ConfigurationDefaults;
    setQueryDownload({sessionId:current.id,blockId:block.id,title:block.block_name || "consulta",selection:selectedCode(block.id,block.code),settings:documentExportSettings(current.extras,defaults),lastDirectory:typeof current.extras.download_last_dir === "string" ? current.extras.download_last_dir : undefined,openFolder:(current.extras.export_open_folder ?? defaults.export_open_folder) !== false});
  },[]);
  const addBlock = useCallback((language?: "sql" | "python") => {
    const current = workspace.session(); if (!current) return;
    const focused = current.blocks.find((block) => block.id === current.focusedBlockId);
    const block = workspace.addBlock(current.id, language ?? focused?.language ?? "sql", "", current.focusedBlockId);
    requestAnimationFrame(() => focusEditor(block.id));
  }, []);
  const rememberFile = (path:string) => setRecentFiles(previous=>{const next=[path,...previous.filter(p=>p !== path)].slice(0,20);try{localStorage.setItem("datapyn.desktop.recent-files.v1",JSON.stringify(next));}catch{/* Optional history. */}return next;});
  const openFiles = useCallback(async (paths:string[]) => {
    const dataTargetId=workspace.session()?.id;
    for (const path of paths) {
      try {
        const extension = path.split(".").at(-1)?.toLowerCase();
        if (extension === "dpw") {
          const document=await runtime.request<unknown>("workspace.read",{path});
          workspace.importDocuments(document,path.split(/[\\/]/).at(-1) ?? "Análise",path);
        } else if (["sql","py","ipynb"].includes(extension ?? "")) {
          const target=workspace.createSession();await workspace.ensureSession(target.id);
          const document=await runtime.request<Record<string,unknown>>("document.read",{session_id:target.id,path});
          const imported=workspace.importDocument({...document,original_file_type:extension},path.split(/[\\/]/).at(-1) ?? "Análise",path);
          await workspace.closeSession(target.id);
          workspace.activate(imported.id);
        } else {
          const target=workspace.session(dataTargetId);if(!target) return;
          if(workspace.getSnapshot().activeId===target.id)activateBottom("results");
          const imported=await workspace.importData(target.id,path);
          setActiveResult(previous=>({...previous,[target.id]:imported.result.result_id}));
          if(workspace.getSnapshot().activeId===target.id)setActiveChart(undefined);
        }
        rememberFile(path);
        const target=workspace.session();if(target && ["dpw","sql","py","ipynb"].includes(extension??"") && preferences.maximizeFirstBlock) workspace.maximizeBlock(target.id,target.blocks[0].id);
      } catch(failure) { reportMessage(/\bimport cancelled\b/i.test(errorText(failure))?t("Importação cancelada."):`${path}: ${errorText(failure)}`); }
    }
  },[preferences.maximizeFirstBlock,activateBottom]);
  const openDocument = useCallback(async () => {
    if (!isDesktop()) throw new Error("Abrir arquivos está disponível no aplicativo desktop.");
    const paths = await open({ multiple: true, filters: [{ name: "DataPyn, scripts e dados", extensions: ["dpw","sql","py","ipynb","csv","tsv","json","parquet","xlsx","xls"] }] });
    if (!paths) return;await openFiles(typeof paths === "string" ? [paths] : paths);
  }, [openFiles]);
  const saveDocument = useCallback(async (saveAs = false, sessionId?: string) => {
    const current = workspace.session(sessionId); if (!current) return;
    if (!isDesktop()) throw new Error("Salvar arquivos está disponível no aplicativo desktop. Seu rascunho permanece neste navegador.");
    const path = !saveAs && current.filePath ? current.filePath : await save({ defaultPath: `${current.title.replace(/\.(dpw|py|sql|ipynb)$/i, "")}.dpw`, filters: [{ name: "DataPyn Workspace", extensions: ["dpw"] }] });
    if (!path) return;
    const document = encodeDocument(current);
    const extension=path.split(".").at(-1)?.toLowerCase();
    if (extension === "dpw") await runtime.request("workspace.write", { path, document });
    else { await workspace.ensureSession(current.id); await runtime.request("document.script_export",{session_id:current.id,path,format:extension,blocks:document.blocks,overwrite:true,notebook_metadata:current.extras.notebook_metadata,shared_parameters:current.extras.shared_parameters_enabled === false ? [] : current.extras.shared_parameters,shared_parameters_enabled:current.extras.shared_parameters_enabled,db_type:exportContext(current,connections.getSnapshot().catalog.connections).connectionType,shared_delimiter:preferences.sharedDelimiter}); }
    workspace.saved(current.id, path, document);
    rememberFile(path);
  }, [preferences.sharedDelimiter]);
  const exportScript = useCallback(async()=>{
    const current=workspace.session();if(!current || !isDesktop()) return;
    const path=await save({defaultPath:`${current.title.replace(/\.[^.]+$/,"")}.py`,filters:[{name:"Python",extensions:["py"]},{name:"SQL",extensions:["sql"]},{name:"Jupyter",extensions:["ipynb"]}]});if(!path)return;
    await workspace.ensureSession(current.id);await runtime.request("document.script_export",{session_id:current.id,path,blocks:encodeDocument(current).blocks,overwrite:true,notebook_metadata:current.extras.notebook_metadata,shared_parameters:current.extras.shared_parameters_enabled === false ? [] : current.extras.shared_parameters,shared_parameters_enabled:current.extras.shared_parameters_enabled,db_type:exportContext(current,connections.getSnapshot().catalog.connections).connectionType,shared_delimiter:preferences.sharedDelimiter});reportMessage(`Script exportado: ${path}`);
  },[preferences.sharedDelimiter]);
  useEffect(()=>{
    if (!isDesktop() || !profile) return;
    setStartupFilesReady(false);
    let disposed=false;const cleanups:Array<()=>void>=[];
    const bind=async()=>{
      const unlisten=await listen<string[]>("datapyn-open-files",event=>{void openFiles(event.payload);});if(disposed)unlisten();else cleanups.push(unlisten);
      if(disposed)return;
      const drop=await getCurrentWebviewWindow().onDragDropEvent(event=>{if(event.payload.type === "drop") void openFiles(event.payload.paths);});if(disposed)drop();else cleanups.push(drop);
      if(disposed)return;
      const paths=await invoke<string[]>("startup_files");if(!disposed && paths.length) await openFiles(paths);
      if(!disposed)setStartupFilesReady(true);
    };void bind().catch(failure=>{if(!disposed){setStartupFilesError(errorText(failure));reportMessage(errorText(failure));}});
    return()=>{disposed=true;cleanups.forEach(clean=>clean());};
  },[openFiles,profile?.active_id,profileRetry]);
  const closeSession = useCallback(async (id: string) => {
    const current = workspace.session(id); if (!current) return;
    if (current.busy) throw new Error("Cancele a execução antes de fechar esta aba.");
    if (current.modified) { setClosingId(id); return; }
    await workspace.closeSession(id); current.blocks.forEach((block) => disposeModel(block.id));
  }, []);
  const closeConfirmed = useCallback(async (shouldSave: boolean) => {
    if (!closingId) return;
    const current = workspace.session(closingId); if (!current) return;
    if (shouldSave) { await saveDocument(false, closingId); if (workspace.session(closingId)?.modified) return; }
    await workspace.closeSession(closingId); current.blocks.forEach((block) => disposeModel(block.id)); setClosingId(undefined);
  }, [closingId, saveDocument]);

  const commands = useRef<(command: Command) => void>(() => {});
  commands.current = (command) => {
    if(!profile || editingLocked)return;
    const current = workspace.session(); if (!current) return;
    switch (command) {
      case "run": runCurrent(); break;
      case "runAdvance": runCurrent(true); break;
      case "runAll": run(workspace.runAll(current.id)); break;
      case "addBlock": addBlock(); break;
      case "newSession": workspace.createSession(); break;
      case "newTab": workspace.createSession(); break;
      case "closeSession": run(closeSession(current.id)); break;
      case "save": run(saveDocument()); break;
      case "saveAs": run(saveDocument(true)); break;
      case "exportScript": run(exportScript()); break;
      case "exit": if(isDesktop()) run(getCurrentWindow().close());break;
      case "open": run(openDocument()); break;
      case "cancel": if (dataImportPending(current.dataImport)) run(workspace.cancelImport(current.id)); else if (current.busy) run(workspace.cancel(current.id)); break;
      case "settings": setSettingsDialog(true); break;
      case "copyHeaders": if (panel === "results") setCopySignal((value) => value + 1); break;
      case "clearResults": workspace.clearResults(current.id); break;
      case "manageConnections": setConnectionsManager(true); break;
      case "newConnection": setConnectionDialog(true); break;
      case "reloadSchema": {
        setExplorerRefresh(n => n + 1);
        const current=workspace.session(),block=current?.blocks.find(item=>item.id===current.focusedBlockId);
        if(current && block?.language==="sql")run(preparation.current.request({sessionId:current.id,blockId:block.id,...blockScope(current,block),dbType:blockConnectionConfig(current,block)?.db_type},block.code,true));
        break;
      }
      case "restoreView": restoreDockLayout(); break;
      case "resetLayout": restoreDockLayout(true); break;
      case "find": run(Promise.resolve(editorAction(current.focusedBlockId,"actions.find"))); break;
      case "replace": run(Promise.resolve(editorAction(current.focusedBlockId,"editor.action.startFindReplaceAction"))); break;
      case "formatCode": run(formatEditor(current.focusedBlockId)); break;
      case "entityInfo": {const editor=getRegisteredEditor(current.focusedBlockId),position=editor?.getPosition(),model=editor?.getModel();const identifier=selectedCode(current.focusedBlockId) ?? (model && position?identifierAtCursor(model.getLineContent(position.lineNumber),position.column):undefined);if(identifier)setEntityInfo({identifier,blockId:current.focusedBlockId});else reportMessage("Selecione ou posicione o cursor sobre uma entidade SQL.");break;}
      case "autocomplete": forceAutocomplete(current.focusedBlockId); break;
      case "editorDuplicateLine": transformEditorSelection(current.focusedBlockId,"duplicate"); break;
      case "editorDeleteLine": transformEditorSelection(current.focusedBlockId,"deleteLine"); break;
      case "editorLowercase": transformEditorSelection(current.focusedBlockId,"lower"); break;
      case "editorUppercase": transformEditorSelection(current.focusedBlockId,"upper"); break;
      case "editorCutLine": getRegisteredEditor(current.focusedBlockId)?.trigger("datapyn","editor.action.clipboardCutAction",{}); break;
      case "editorNewline": getRegisteredEditor(current.focusedBlockId)?.trigger("datapyn","editor.action.insertLineAfter",{}); break;
      case "editorTransposeLine": getRegisteredEditor(current.focusedBlockId)?.trigger("datapyn","editor.action.moveLinesUpAction",{}); break;
    }
  };
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if(workspace.isEditingLocked()){event.preventDefault();event.stopPropagation();return;}
      const eventDocument=(event.target as Node | null)?.ownerDocument ?? document;
      if (eventDocument.activeElement?.closest('[role="menu"]')) return;
      if (connectionDialog || settingsDialog || closingId || connectionPicker || connectionsManager || hasVisibleShortcutDialog(document) || (eventDocument !== document && hasVisibleShortcutDialog(eventDocument))) {
        if (event.key === "Escape") { event.preventDefault(); setSettingsDialog(false); if (!connectionDialog) setClosingId(undefined); }
        return;
      }
      if (event.key === "Escape") {
        // Keep Escape available to Monaco's completion/find widgets.
        if (eventDocument.activeElement?.closest(".monaco-editor") || !activeSessionRef.current.busy) return;
      }
      const command = commandForEvent(event.repeat ? { key: event.key, ctrlKey: event.ctrlKey, metaKey: event.metaKey, altKey: event.altKey, shiftKey: event.shiftKey, repeat: false } : event, shortcuts); if (!command) return;
      if (EDITOR_COMMANDS.has(command) && !eventDocument.activeElement?.closest(".monaco-editor")) return;
      if (eventDocument.activeElement?.matches("input,textarea,select") && !eventDocument.activeElement.closest(".monaco-editor") && !["save","saveAs","open","settings"].includes(command)) return;
      event.preventDefault(); event.stopPropagation(); if (!event.repeat) commands.current(command);
    };
    popoutKeyboard.current=handle;
    window.addEventListener("keydown", handle, true); return () => window.removeEventListener("keydown", handle, true);
  }, [shortcuts, connectionDialog, settingsDialog, closingId, connectionPicker, connectionsManager]);
  useEffect(() => {
    const observe = () => {
      const snapshot=workspace.getSnapshot(),reveal=outputReveals.current.observe(snapshot.sessions,snapshot.activeId);
      if (!reveal || !outputRevealAllowed.current || workspace.isEditingLocked()) return;
      activateBottom(reveal.panel);
      if (reveal.rich) setActiveResult(previous=>({...previous,[reveal.sessionId]:"__images__"}));
      else if (reveal.commands) setActiveResult(previous=>({...previous,[reveal.sessionId]:"__commands__"}));
      else if (reveal.resultId) setActiveResult(previous=>({...previous,[reveal.sessionId]:reveal.resultId!}));
      if (reveal.panel === "results") setActiveChart(undefined);
    };
    observe(); const unsubscribe=workspace.subscribe(observe); return () => {unsubscribe();};
  }, [activateBottom]);
  useEffect(() => {
    const ids = new Set(state.sessions.map(s=>s.id)); languageContexts.current.retain(ids); completionIndex.current.retain(ids); preparation.current.retain(ids);
    for(const id of lastNotificationContexts.current.keys())if(!ids.has(id))lastNotificationContexts.current.delete(id);
    const context=completionIndex.current.context(session,session.focusedBlockId,languageContexts.current,blockConnectionConfig(session,session.blocks.find(b=>b.id===session.focusedBlockId) ?? session.blocks[0]));
    if(context)setCompletionContext(session.focusedBlockId,context);
  }, [session.id, session.focusedBlockId, session.blocks, session.variables, session.results, session.savedConnectionId, session.database, session.schema,languageRevision,state.sessions,catalogState.catalog]);

  const commandExecutions = session.commandExecutions ?? [];
  const executionOutput = session.executionOutput;
  const selectedExecutionOutputs = useRef(new Map<string,string>());
  // Background completions select their own output when the user returns to the tab.
  useEffect(() => {
    if (!executionOutput) { selectedExecutionOutputs.current.delete(session.id); return; }
    const key = `${executionOutput.executionId}:${executionOutput.kind}`;
    if (selectedExecutionOutputs.current.get(session.id) === key) return;
    selectedExecutionOutputs.current.set(session.id,key);
    const target = executionOutput.kind === "commands" ? "__commands__" : executionOutput.kind === "rich" ? "__images__" : executionOutput.resultId;
    if (target) setActiveResult(previous=>({...previous,[session.id]:target}));
    setActiveChart(undefined);
  }, [session.id, executionOutput?.executionId, executionOutput?.kind]);
  const showingCommands = commandExecutions.length > 0 && (activeResult[session.id] === "__commands__" || !session.results.length && !session.richOutputs?.length && !session.images.length);
  const result = showingCommands || activeResult[session.id] === "__images__" && (session.richOutputs?.length || session.images.length) ? undefined : session.results.find((item) => item.result_id === activeResult[session.id]) ?? session.results.at(-1);
  const focusedBlock = session.blocks.find((block) => block.id === session.focusedBlockId);
  const focusedScope = focusedBlock ? blockScope(session, focusedBlock) : {connectionId:session.savedConnectionId,database:session.database,schema:session.schema,scopeInherited:true};
  const entityScope = entityInfo ? blockScope(session, session.blocks.find(block=>block.id===entityInfo.blockId) ?? session.blocks[0]) : focusedScope;
  // Warm the focused scope once on focus/context changes, never on each keystroke.
  useEffect(()=>{
    if(state.runtimeStatus!=="ready" || editingLocked || connectionBlocked || preparedSession!==`${profile?.active_id}:${session.id}` || focusedBlock?.language!=="sql" || !(focusedScope.connectionId || session.connection))return;
    void preparation.current.request({sessionId:session.id,blockId:focusedBlock.id,...focusedScope,dbType:blockConnectionConfig(session,focusedBlock)?.db_type},focusedBlock.code).catch(failure=>reportMessage(errorText(failure)));
  },[session.id,session.focusedBlockId,focusedBlock?.language,focusedScope.connectionId,focusedScope.database,focusedScope.schema,focusedScope.scopeInherited,state.runtimeStatus,preparedSession,profile?.active_id,editingLocked,connectionBlocked,preparationRevision,session.connection,catalogState.catalog]);
  const exportScope=exportContext(session,catalogState.catalog.connections);
  const exportConnections=useMemo(()=>catalogState.catalog.connections.map(item=>({id:item.id,name:item.name,db_type:item.config.db_type,database:item.config.database})),[catalogState.catalog]);
  const insertSql=(code:string)=>{
    const block=workspace.addBlock(session.id,"sql",code,session.focusedBlockId);
    workspace.updateBlock(session.id,block.id,{connection_id:exportScope.connectionId,database_name:exportScope.database,schema:exportScope.schema});
    requestAnimationFrame(()=>focusEditor(block.id));
  };
  const runDisabled = editingLocked || session.busy || dataImportPending(session.dataImport) || openingConnection || (session.connectionState?.phase==="error"&&focusedBlock?.language==="sql"&&!focusedBlock.connection_id) || state.runtimeStatus !== "ready" || !profile || switchingProfile || Boolean(session.runtimeError);
  return <div className="app-shell">
    <header className="app-header">
      <div className="brand"><img src={logo} alt="" /><span>{translateUi("DataPyn")}</span></div>
      <nav className="app-menu" aria-label={translateUi("Arquivos e configurações")}>
        <button onClick={() => run(openDocument())}>{translateUi("Abrir")}<kbd>{translateUi("Ctrl O")}</kbd></button>
        <button onClick={() => run(saveDocument())}>{translateUi("Salvar")}<kbd>{translateUi("Ctrl S")}</kbd></button>
        <button onClick={() => run(saveDocument(true))}>{translateUi("Salvar como")}</button>
        <button onClick={() => setSettingsDialog(true)}>{translateUi("Configurações")}</button>
        <button disabled={!dockControls || editingLocked} aria-haspopup="dialog" aria-expanded={layoutDialog} onClick={()=>setLayoutDialog(true)}>{translateUi("Exibir")}</button>
        {updates.state.phase === "downloaded" && <button className="app-update-ready" onClick={()=>setUpdateDialog(true)}><RefreshCw size={14}/>{translateUi("Atualização pronta")}</button>}
        <button className="app-notifications" aria-label={translateUi("Notificações")} title={translateUi("Notificações")} onClick={()=>setNotificationHistory(true)}><Bell size={14}/>{notificationState.unread > 0 && <span className="notification-menu-count">{notificationState.unread}</span>}</button>
        <button aria-haspopup="menu" aria-expanded={Boolean(appMenu)} onClick={e=>{const rect=e.currentTarget.getBoundingClientRect();setAppMenu({owner:e.currentTarget.ownerDocument,anchor:{x:rect.left,y:rect.bottom},button:e.currentTarget});}}><MoreHorizontal size={15}/>{translateUi("Mais")}</button>
      </nav>
    </header>
    {appMenu && <ContextMenu ownerDocument={appMenu.owner} anchor={appMenu.anchor} returnFocus={appMenu.button} label={translateUi("Mais opções")} onClose={()=>setAppMenu(undefined)} items={[
      {label:translateUi("Pacotes Python"),onSelect:()=>setPackageDialog(true)},
      {label:translateUi("Recentes"),onSelect:()=>setRecentVisible(true)},
      {label:translateUi("Workspace"),onSelect:()=>setWorkspaceManager(true)},
      {label:translateUi("Atualizações"),separator:true,onSelect:()=>setUpdateDialog(true)},
      {label:translateUi("Sobre"),onSelect:()=>setAboutDialog(true)},
    ]}/>}
    {recentVisible && <div className="recent-files"><button onClick={()=>{setRecentFiles([]);localStorage.removeItem("datapyn.desktop.recent-files.v1");}}>{translateUi("Limpar recentes")}</button>{recentFiles.map(path=><div key={path}><button title={path} onClick={()=>{run(openFiles([path]));setRecentVisible(false);}}>{path}</button><button title={translateUi("Mostrar na pasta")} onClick={()=>run(revealItemInDir(path))}><FolderOpen size={13}/></button></div>)}</div>}
    <div className="session-bar" role="tablist" aria-label={translateUi("Sessões")}>
      {state.sessions.map((item) => <div onContextMenu={e=>{e.preventDefault();setTabContext({id:item.id,x:e.clientX,y:e.clientY});}} key={item.id} style={{borderTopColor:effectiveConnectionColor(item.savedConnectionId ?? "",catalogState.catalog)}} className={`session-tab ${session.id === item.id ? "active" : ""}`}>
        {editingTitle === item.id ? <input autoFocus className="tab-title-input" value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)} onBlur={() => { workspace.renameSession(item.id, titleDraft); setEditingTitle(undefined); }} onKeyDown={(event) => { if (event.key === "Enter") { workspace.renameSession(item.id, titleDraft); setEditingTitle(undefined); } if (event.key === "Escape") setEditingTitle(undefined); }} /> : <button role="tab" aria-selected={session.id === item.id} aria-busy={item.busy||connectionPending(item.connectionState)||dataImportPending(item.dataImport)} title={item.dataImport?.error??item.connectionState?.error} onClick={() => workspace.activate(item.id)} onDoubleClick={() => { setEditingTitle(item.id); setTitleDraft(item.title); }}>
          {item.busy || connectionPending(item.connectionState) || dataImportPending(item.dataImport) ? <LoaderCircle size={13} className="spin" aria-label={t(dataImportPending(item.dataImport)?"Importando dados…":item.busy?"Executando…":"Abrindo conexão")}/> : item.dataImport?.phase==="error"||item.connectionState?.phase==="error" ? <AlertTriangle size={13} className="session-connection-error" aria-label={t(item.dataImport?.phase==="error"?"Falha ao importar arquivo":"Falha na conexão")}/> : <FileCode2 size={13} />}<span>{item.title}{item.modified ? " •" : ""}</span></button>}
        <IconButton title={`Fechar ${item.title}`} onClick={() => run(closeSession(item.id))}><X size={12} /></IconButton>
      </div>)}
      <IconButton title={translateUi("Nova sessão (Ctrl+N / Ctrl+T)")} onClick={() => workspace.createSession()} className="new-session"><Plus size={17} /></IconButton>
    </div>
    <div className="workspace-toolbar">
      <IconButton title={leftVisible ? "Ocultar conexões" : "Mostrar conexões"} disabled={editingLocked} onClick={() => toggleDockGroup(["connections","explorer"])}>{leftVisible ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}</IconButton>
      <button className="connection-button" onClick={() => setConnectionDialog(true)}><Database size={14} /><span>{session.connection?.name || session.connection?.database || "Conectar ao banco"}</span><ChevronDown size={12} /></button>
      {session.connection?.schema && <span className="context-chip">{session.connection.schema}</span>}
      <span className="toolbar-divider" />
      <button className="primary-button run-button" disabled={runDisabled} onClick={() => runCurrent()} title={translateUi("Executar bloco ou seleção (F5 / Ctrl+Enter)")}><Play size={14} fill="currentColor" />{translateUi("Executar")}<kbd>{translateUi("F5")}</kbd></button>
      <button className="text-button" disabled={runDisabled} onClick={() => run(workspace.runAll(session.id))} title={translateUi("Executar todos os blocos ativos (Ctrl+F5)")}><Layers3 size={15} /> {translateUi("Executar todos")}</button>
      <button className="text-button stop-button" disabled={!session.busy&&!dataImportPending(session.dataImport)||session.dataImport?.phase==="cancelling"} onClick={() => run(dataImportPending(session.dataImport)?workspace.cancelImport(session.id):workspace.cancel(session.id))} title={t(dataImportPending(session.dataImport)?"Cancelar importação":"Interromper esta sessão e descartar seu namespace")}><Square size={13} fill="currentColor" /> {translateUi("Cancelar")}</button>
      <span className="toolbar-spacer" />
      <label className="periodic-control" title={translateUi("Executar todos periodicamente nesta aba")}><input type="number" min="1" max="86400" value={periodicSeconds} onChange={e => setPeriodicSeconds(Math.max(1,+e.target.value))} aria-label={translateUi("Intervalo em segundos")}/>{translateUi("s")}<button className={session.periodicSeconds ? "active" : ""} disabled={runDisabled && !session.periodicSeconds} onClick={() => session.periodicSeconds ? workspace.stopPeriodic(session.id) : run(workspace.startPeriodic(session.id, periodicSeconds))}>{t(session.periodicSeconds ? "Parar repetição" : "Repetir")}</button></label>
      <span className="execution-time">{(elapsed / 1000).toFixed(1)}{translateUi("s")}</span>
      <span className="toolbar-hint">{session.blocks.length} {translateUi("blocos")}</span>
      <IconButton title={rightVisible ? "Ocultar variáveis" : "Mostrar variáveis"} disabled={editingLocked} onClick={() => toggleDockGroup(["variables","pynia"])}>{rightVisible ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}</IconButton>
    </div>
    {isDesktop() && !profile && <div className="workspace-loading" role="status" aria-live="polite">{profileLoadError || state.runtimeStatus === "unavailable" ? <><span>{profileLoadError || state.message}</span><button className="text-button" onClick={()=>state.runtimeStatus === "unavailable" ? run(workspace.retryRuntime()) : setProfileRetry(n=>n+1)}>{translateUi("Tentar novamente")}</button></> : <><LoaderCircle className="spin" size={22}/><span>{translateUi(state.runtimeStatus === "ready" ? "Restaurando workspace…" : "Iniciando runtime Python…")}</span></>}</div>}
    {state.runtimeStatus === "unavailable" && <div className="runtime-banner"><Activity size={14} /><span>{isDesktop() ? state.message : "Prévia da interface. O runtime Python está disponível no aplicativo desktop."}</span>{isDesktop() && <button className="text-button" onClick={() => run(workspace.retryRuntime())}><RefreshCw size={12} /> {translateUi("Reconectar")}</button>}</div>}
    <main className="workbench">{(!isDesktop() || profile) && <Suspense fallback={<p className="explorer-empty">{translateUi("Carregando painéis…")}</p>}><DockingWorkbench key={profile?.active_id ?? "startup"} initialLayout={dockLayout} locked={editingLocked} onControlsReady={controls=>{docking.current=controls;setDockControls(controls);}} onPanelsChange={dockPanelsChanged} onVisiblePanelsChange={setVisibleDockPanels} onRestoreError={reportMessage} onInitialized={()=>setStartupLayout(profile?.active_id)} onPopoutReady={attachPopoutKeyboard} onCaptureReady={capture=>{captureLayout.current=capture;}} onLayoutChange={setDockLayout} theme={preferences.theme} leftWidth={preferences.leftWidth} rightWidth={preferences.rightWidth} resultHeight={resultHeight} leftVisible={leftVisible} rightVisible={rightVisible} activeBottom={panel} activeRight={rightPanel} resetRevision={dockReset} onActivate={id=>{if(isBottomPanel(id))setPanel(id);if(id === "variables" || id === "pynia")setRightPanel(id);}} panels={{
      connections:<ConnectionsSidebar activeConnectionId={session.savedConnectionId} onConnect={connectSaved} onDisconnect={() => workspace.disconnect(session.id)} onError={reportMessage} disabled={session.busy || dataImportPending(session.dataImport) || openingConnection || !profile || switchingProfile}/>,
      explorer:<ObjectExplorer sessionId={session.id} blockId={focusedBlock?.id} scopeInherited={focusedScope.scopeInherited} connectionId={focusedScope.connectionId} database={focusedScope.database} schema={focusedScope.schema} dbType={catalogState.catalog.connections.find(item=>item.id===focusedScope.connectionId)?.config.db_type ?? session.connection?.db_type} connected={!connectionBlocked && preparedSession === `${profile?.active_id}:${session.id}` && Boolean(session.connection || focusedBlock?.connection_id || session.savedConnectionId)} refresh={explorerRefresh} disabled={session.busy} onError={reportMessage}
          onInsert={(code, language = "sql", newBlock = false) => { if (newBlock) { const block = workspace.addBlock(session.id,language,code,session.focusedBlockId); if (focusedBlock) workspace.updateBlock(session.id,block.id,{connection_id:focusedScope.connectionId,database_name:focusedScope.database,schema:focusedScope.schema}); requestAnimationFrame(()=>focusEditor(block.id)); } else insertInEditor(session.focusedBlockId,code); }}
          onContextChange={context => applyBlockScope(session.id,session.focusedBlockId,context)}/>,
      editor:<div className={`editor-area${session.maximizedBlockId ? " has-maximized-block" : ""}`} ref={codeArea}>
          <SessionConnectionStatus state={session.connectionState??(state.runtimeStatus!=="ready"?{phase:state.runtimeStatus==="connecting"?"preparing":"error",error:state.message}:undefined)}
            retryLabel={retryConnectionId||state.runtimeStatus!=="ready"?"Tentar novamente":"Editar conexão"}
            onRetry={session.runtimeError?undefined:()=>run((async()=>{
              if(state.runtimeStatus!=="ready")await workspace.retryRuntime();
              const id=retryConnectionId;
              if(id){const saved=catalogState.catalog.connections.find(c=>c.id===id);await workspace.connectSaved(session.id,id,saved?.name,session.connectionState?.connectionId?session.connectionState.scope:{database:session.database,schema:session.schema});setExplorerRefresh(n=>n+1);}
              else if(session.connectionState?.phase==="error"&&session.connectionState.name)setConnectionDialog(true);
              else await workspace.prepareSession(session.id);
              setPreparedSession(`${profile?.active_id}:${session.id}`);
            })())}/>
          {session.notice && <div className="session-notice" role="status">{session.notice}</div>}
          <ParameterPanel title={translateUi("Parâmetros compartilhados")} parameters={sharedParameters} enabled={session.extras.shared_parameters_enabled !== false} disabled={session.busy} onEnabled={enabled => workspace.patchSession(session.id,s=>({...s,modified:true,extras:{...s.extras,shared_parameters_enabled:enabled}}))} onChange={parameters => workspace.patchSession(session.id,s=>({...s,modified:true,extras:{...s.extras,shared_parameters:parameters}}))}/>
          {session.blocks.map((block, index) => <BlockCard scopeMetadata={scopeMetadata} onScopeChange={applyBlockScope} scopeRefresh={explorerRefresh} scopeReady={!connectionBlocked&&preparedSession === `${profile?.active_id}:${session.id}`} diagnosticsReady={!openingConnection&&state.runtimeStatus === "ready"} diagnosticRevision={diagnosticRevisionFor(session, block)} diagnosticContext={diagnosticContext} locked={editingLocked} forceMount={startupActive && requiredEditor === block.id} onEditorReady={startupEditorInitialized} key={block.id} block={block} index={index} count={session.blocks.length} session={session} disabled={runDisabled} preferences={preferences} onFontSizeChange={editorFontSize=>setPreferences(p=>({...p,editorFontSize}))} onPickConnection={() => setConnectionPicker(block.id)} onDownload={()=>run(downloadBlock(block.id))}
            onRun={() => run(workspace.runBlock(session.id, block.id))} />)}
          <div className="add-block-row"><button title={shortcuts.addBlock} onClick={() => addBlock("sql")}><Plus size={14} /><span className="sql-color">{translateUi("SQL")}</span></button><button title={shortcuts.addBlock} onClick={() => addBlock("python")}><Plus size={14} /><span className="python-color">{translateUi("Python")}</span></button></div>
        </div>,
      results:<section className="results-panel">
            <DataImportStatus state={session.dataImport} onCancel={()=>run(workspace.cancelImport(session.id))} onDismiss={()=>workspace.clearImportStatus(session.id)}/>
            <Suspense fallback={null}><DataActions hideResultActions={showingCommands} onImportData={(path,settings)=>workspace.importData(session.id,path,settings)} importState={session.dataImport} onCancelImport={()=>workspace.cancelImport(session.id)} sessionId={session.id} result={result} connectionType={exportScope.connectionType} availableConnections={exportConnections} currentConnectionId={exportScope.connectionId} currentDatabase={exportScope.database} currentSchema={exportScope.schema} onInsertSql={insertSql} onTableExported={()=>setExplorerRefresh(n=>n+1)} disabled={session.busy || dataImportPending(session.dataImport) || state.runtimeStatus !== "ready"} view={gridView} initialExportSettings={exportOptions} defaultOpenFolder={Boolean(session.extras.export_open_folder ?? configurationDefaults.export_open_folder ?? true)} onOpenFolderChange={export_open_folder=>{updateConfigurationDefaults({export_open_folder});workspace.patchSession(session.id,s=>({...s,extras:{...s.extras,export_open_folder}}));}} onExportSettingsChange={export_settings=>{updateConfigurationDefaults({export_settings});workspace.patchSession(session.id,s=>({...s,extras:{...s.extras,export_settings}}));}} onImported={showResult} onChart={createChart} onMessage={reportMessage}/></Suspense>
            {charts.length > 0 && <div className="result-tabs chart-tabs"><button className={!activeChart?"active":""} onClick={()=>setActiveChart(undefined)}>{translateUi("Dados")}</button>{charts.map(chart=><div className="chart-tab" key={chart.id}><button className={activeChart === chart.id?"active":""} onClick={()=>setActiveChart(chart.id)} onDoubleClick={()=>setEditingChart({id:chart.id,title:chart.title})}>{chart.title}</button><button aria-label={`Excluir ${chart.title}`} onClick={()=>{workspace.patchSession(session.id,s=>({...s,modified:true,extras:{...s.extras,charts:charts.filter(c=>c.id !== chart.id)}}));if(activeChart === chart.id)setActiveChart(undefined);}}>{translateUi("×")}</button></div>)}</div>}
            {(session.results.length > 0 || commandExecutions.length > 0 || (session.richOutputs?.length ?? session.images.length) > 0) && <div className="result-tabs">{session.results.map((item) => <div className="chart-tab" key={item.result_id} style={{borderTop:`2px solid ${effectiveConnectionColor(session.blocks.find(b=>b.results?.some(r=>r.result_id === item.result_id))?.connection_id ?? session.savedConnectionId ?? "",catalogState.catalog) ?? "transparent"}`}}><button className={result?.result_id === item.result_id ? "active" : ""} onClick={() => {setActiveResult((previous) => ({ ...previous, [session.id]: item.result_id }));setActiveChart(undefined);}}><Table2 size={12} />{item.variable_name || t("Resultado")}<span>{item.row_count.toLocaleString(preferences.locale)}</span></button><button aria-label={`${t("Fechar resultado")} ${item.variable_name}`} disabled={session.busy} onClick={()=>{workspace.closeResult(session.id,item.result_id);setGridView(undefined);}}><X size={11}/></button></div>)}{commandExecutions.length > 0 && <button className={showingCommands ? "active" : ""} onClick={() => {setActiveChart(undefined);setActiveResult(previous=>({...previous,[session.id]:"__commands__"}));}}><Terminal size={12}/>{translateUi("Mensagens")}</button>}{(session.richOutputs?.length ?? session.images.length) > 0 && <button className={!result && !showingCommands ? "active" : ""} onClick={() => {setActiveChart(undefined);setActiveResult((previous) => ({ ...previous, [session.id]: "__images__" }));}}>{translateUi("Resultados Python")}<span>{session.richOutputs?.length ?? session.images.length}</span></button>}</div>}
            {activeChart ? (()=>{const chart=charts.find(c=>c.id === activeChart);return chart ? <Suspense fallback={<p>{translateUi("Carregando gráfico…")}</p>}><SavedChartView key={`${session.id}:${chart.id}`} session={session} chart={chart} sourceCache={chartSources.current} prepareSource={()=>workspace.ensureSession(session.id)} currentResult={result} view={gridViewOwner.current?.sessionId === session.id && gridViewOwner.current.resultId === result?.result_id ? gridView : undefined}
              active={visibleDockPanels.includes("results")} disabled={session.busy || dataImportPending(session.dataImport) || state.runtimeStatus !== "ready"} theme={preferences.theme} onMessage={reportMessage}
              onChange={next=>workspace.patchSession(session.id,s=>({...s,modified:true,extras:{...s.extras,charts:((s.extras.charts ?? []) as SavedChart[]).map(c=>c.id === next.id?next:c)}}))}
              onDuplicate={()=>{const copy={...structuredClone(chart),id:crypto.randomUUID(),title:`${chart.title} · cópia`};copy.config.title=copy.title;workspace.patchSession(session.id,s=>({...s,modified:true,extras:{...s.extras,charts:[...charts,copy],desktop_chart_id:copy.id}}));}}
              canMoveLeft={charts.indexOf(chart)>0} canMoveRight={charts.indexOf(chart)<charts.length-1} onMove={direction=>{const next=[...charts],index=next.findIndex(c=>c.id===chart.id),destination=index+direction;if(destination<0 || destination>=next.length)return;[next[index],next[destination]]=[next[destination],next[index]];workspace.patchSession(session.id,s=>({...s,modified:true,extras:{...s.extras,charts:next}}));}}/>
              </Suspense> : null;})() : showingCommands ? <CommandResults executions={commandExecutions} blockLabels={Object.fromEntries(session.blocks.map((block,index)=>[block.id,t("Bloco {number}",{number:index+1})]))}/> : result ? <ResultGrid key={`${session.id}:${result.result_id}`} sessionId={session.id} result={result} transport={runtime} onMessage={reportMessage} copySignal={copySignal} onViewChange={view=>{gridViewOwner.current={sessionId:session.id,resultId:result.result_id};setGridView(view);const saved={filter:view.filter,sort:view.sort};workspace.patchSession(session.id,s=>{const prior=(s.extras.table_views ?? {}) as Record<string,unknown>;return JSON.stringify(prior[result.variable_name] ?? {}) === JSON.stringify(saved) ? s : {...s,modified:true,extras:{...s.extras,table_views:{...prior,[result.variable_name]:saved}}};});}} initialView={(session.extras.table_views as Record<string,DataView>)?.[result.variable_name]} refreshRevision={session.resultRevision} formatColumnRequest={formatColumnRequest?.sessionId === session.id && formatColumnRequest.resultId === result.result_id ? formatColumnRequest : undefined} displayRowLimit={preferences.displayRowLimit} theme={preferences.theme} uiFont={preferences.gridFont} uiFontSize={preferences.gridFontSize} onFontSizeChange={gridFontSize=>setPreferences(p=>({...p,gridFontSize}))} dbType={exportScope.connectionType} onInsertSql={insertSql} columnFormats={((session.extras.result_view_state as Record<string,unknown>)?.column_formats ?? {}) as ColumnFormats} onColumnFormatsChange={column_formats=>workspace.patchSession(session.id,s=>({...s,modified:true,extras:{...s.extras,result_view_state:{...(s.extras.result_view_state as object),column_formats}}}))} copySeparator={copyOptions.separator} nullDisplay={copyOptions.nullDisplay} onCopySettingsChange={settings=>{updateConfigurationDefaults({copy_separator:settings.copySeparator,copy_null_display:settings.nullDisplay});workspace.patchSession(session.id,s=>({...s,extras:{...s.extras,copy_separator:settings.copySeparator,copy_null_display:settings.nullDisplay}}));}} /> : session.richOutputs?.length ? <Suspense fallback={<p>{translateUi("Carregando resultados Python…")}</p>}><RichResults sessionId={session.id} outputs={session.richOutputs} onMessage={reportMessage}/></Suspense> : session.images.length ? <div className="figure-results">{session.images.map((image, index) => <img key={index} src={`data:${image.mime};base64,${image.data}`} alt={`Gráfico Python ${index + 1}`} />)}</div> : <div className="empty-results"><span>{t(session.busy ? "Executando…" : "Sem resultados.")}</span></div>}
</section>,
      summary:<Suspense fallback={<p>{translateUi("Carregando resumo…")}</p>}><SummaryPanel sessionId={session.id} result={result} view={gridView} active={visibleDockPanels.includes("summary")} disabled={session.busy || dataImportPending(session.dataImport) || state.runtimeStatus !== "ready"} onMessage={reportMessage} onFormatColumn={column=>{if(!result)return;setActiveChart(undefined);activateBottom("results");setFormatColumnRequest(previous=>({sessionId:session.id,resultId:result.result_id,column,revision:(previous?.revision ?? 0)+1}));}}/></Suspense>,
      output:<OutputPanel session={session} />,
      pynia:<Suspense fallback={<p>{translateUi("Carregando Pynia…")}</p>}><PyniaPanel defaults={configurationDefaults.pynia} sessionId={session.id} sessionTitle={session.title} initialState={session.extras.pynia_chat_state as Record<string,unknown>} context={{focused_block_id:session.focusedBlockId,blocks:session.blocks,selection:selectedCode(session.focusedBlockId),database:session.database,schema:session.schema}} onInsert={(code,language)=>{const block=workspace.addBlock(session.id,language,code,session.focusedBlockId);requestAnimationFrame(()=>focusEditor(block.id));}} onState={pynia_chat_state=>workspace.patchSession(session.id,s=>JSON.stringify(s.extras.pynia_chat_state) === JSON.stringify(pynia_chat_state) ? s : {...s,extras:{...s.extras,pynia_chat_state}})}/></Suspense>,
      pyniaOutput:<Suspense fallback={<p>{translateUi("Carregando Pynia…")}</p>}><PyniaOutputPanel defaults={configurationDefaults.pynia} sessionId={session.id} sessionTitle={session.title} initialState={session.extras.pynia_chat_state as Record<string,unknown>}/></Suspense>,
      variables:<>

        <Suspense fallback={<p className="explorer-empty">{translateUi("Carregando variáveis…")}</p>}><VariableInspector sessionId={session.id} variables={session.variables} connectionType={exportScope.connectionType} availableConnections={exportConnections} currentConnectionId={exportScope.connectionId} currentDatabase={exportScope.database} currentSchema={exportScope.schema} onInsertSql={insertSql} onTableExported={()=>setExplorerRefresh(n=>n+1)} initialExportSettings={exportOptions} onExportSettingsChange={export_settings=>{updateConfigurationDefaults({export_settings});workspace.patchSession(session.id,s=>({...s,extras:{...s.extras,export_settings}}));}} disabled={session.busy} onResult={showResult} onVariables={variables => workspace.patchSession(session.id,s=>({...s,variables,resultRevision:s.resultRevision+1}))} onInsert={name=>insertInEditor(session.focusedBlockId,name)}/></Suspense>
        <Suspense fallback={null}><VariableArchive sessionId={session.id} disabled={session.busy || dataImportPending(session.dataImport) || state.runtimeStatus !== "ready"} onMessage={reportMessage} onImported={(results,variables)=>{
          workspace.patchSession(session.id,s=>({...s,results:[...s.results.filter(prior=>!results.some(next=>next.variable_name===prior.variable_name)),...results],variables,resultRevision:s.resultRevision+1}));
          if(results.length){setActiveResult(previous=>({...previous,[session.id]:results[0].result_id}));setActiveChart(undefined);activateBottom("results");}
        }}/></Suspense>
        <button className="text-button" onClick={()=>setSnapshotVisible(!snapshotVisible)}>{translateUi("Armazenamento de variáveis")}</button>{snapshotVisible && <Suspense fallback={null}><VariableSnapshotPanel sessionId={session.id} disabled={session.busy} onMessage={reportMessage} onRestored={(results,variables)=>workspace.patchSession(session.id,s=>({...s,results,variables,resultRevision:s.resultRevision+1}))}/></Suspense>}
</>,
    }}/></Suspense>}</main>
    <footer className="statusbar"><span className={`status-runtime ${state.runtimeStatus}`}><Circle size={7} fill="currentColor" />{t(state.runtimeStatus === "ready" ? "Runtime conectado" : "Runtime offline")}</span><span className="status-message" role="status" title={state.message}>{state.message}</span><span className="status-file" title={session.filePath}>{session.filePath?.split(/[\\/]/).at(-1) || t("Rascunho local")}</span><span className="status-language">{focusedBlock?.language.toUpperCase()}</span><IconButton title={translateUi("Configurar atalhos")} onClick={() => setSettingsDialog(true)}><Settings2 size={12} /></IconButton></footer>
    {queryDownload && !editingLocked && <Suspense fallback={null}><QueryDownloadDialog request={queryDownload} onClose={()=>setQueryDownload(undefined)} onDownload={(path,format,settings)=>{
      const request=queryDownload;setQueryDownload(undefined);
      updateConfigurationDefaults({export_settings:settings,export_open_folder:settings.open_folder});
      workspace.patchSession(request.sessionId,s=>({...s,extras:{...s.extras,download_last_dir:downloadDirectory(path),export_settings:settings,export_open_folder:settings.open_folder}}));
      run(workspace.runToFile(request.sessionId,request.blockId,{path,format,options:{...settings,header:settings.include_header,overwrite:true}},request.selection).then(async completed=>{
        if(completed?.status === "succeeded" && completed.export?.files.length && settings.open_folder)await revealItemInDir(completed.export.files[0].path);
      }));
    }}/></Suspense>}
    {layoutDialog && dockControls && !editingLocked && <Suspense fallback={null}><LayoutDialog controls={dockControls} visiblePanels={dockPanels} restoreShortcut={shortcuts.restoreView} resetShortcut={shortcuts.resetLayout} onRestore={()=>restoreDockLayout()} onReset={()=>restoreDockLayout(true)} canSave={Boolean(profile) && !editingLocked} onSave={async()=>{await flushWorkspace.current();reportMessage(translateUi("Layout salvo."));}} onMessage={reportMessage} onClose={()=>setLayoutDialog(false)}/></Suspense>}
    {entityInfo && <Suspense fallback={null}><EntityInfoDialog identifier={entityInfo.identifier} scope={{session_id:session.id,block_id:entityInfo.blockId,scope_inherited:entityScope.scopeInherited,connection_id:entityScope.connectionId,database:entityScope.database,schema:entityScope.schema}} onClose={()=>setEntityInfo(undefined)}/></Suspense>}
    {tabContext && <><div className="context-dismiss" onClick={()=>setTabContext(undefined)}/><div className="tab-context" style={{left:Math.min(tabContext.x,innerWidth-190),top:Math.min(tabContext.y,innerHeight-190)}}><button onClick={()=>{workspace.duplicateSession(tabContext.id);setTabContext(undefined);}}>{translateUi("Duplicar análise")}</button><button onClick={()=>{const target=workspace.session(tabContext.id);if(target){setEditingTitle(target.id);setTitleDraft(target.title);}setTabContext(undefined);}}>{translateUi("Renomear")}</button><button onClick={()=>{run(closeSession(tabContext.id));setTabContext(undefined);}}>{translateUi("Fechar")}</button><button onClick={()=>{setClosingMany(state.sessions.filter(s=>s.id !== tabContext.id).map(s=>s.id));setTabContext(undefined);}}>{translateUi("Fechar outras")}</button><button onClick={()=>{setClosingMany(state.sessions.map(s=>s.id));setTabContext(undefined);}}>{translateUi("Fechar todas")}</button></div></>}
    {closingMany && <Modal title={translateUi("Fechar análises")} onClose={()=>setClosingMany(undefined)}><div className="confirm-copy"><p>{closingMany.length} {translateUi("análises. Alterações permanecem no workspace até serem salvas ou descartadas.")}</p><ul>{closingMany.map(id=><li key={id}>{workspace.session(id)?.title}{workspace.session(id)?.modified?" •":""}</li>)}</ul></div><footer className="modal-footer"><button onClick={()=>setClosingMany(undefined)}>{translateUi("Voltar")}</button><button disabled={closingMany.some(id=>workspace.session(id)?.busy)} onClick={()=>run((async()=>{for(const id of closingMany){const target=workspace.session(id);if(target){await workspace.closeSession(id);target.blocks.forEach(b=>disposeModel(b.id));}}setClosingMany(undefined);})())}>{translateUi("Descartar e fechar")}</button><button className="primary-button" disabled={closingMany.some(id=>workspace.session(id)?.busy)} onClick={()=>run((async()=>{for(const id of closingMany){const target=workspace.session(id);if(!target)continue;if(target.modified){await saveDocument(false,id);if(workspace.session(id)?.modified)return;}await workspace.closeSession(id);target.blocks.forEach(b=>disposeModel(b.id));}setClosingMany(undefined);})())}>{translateUi("Salvar e fechar")}</button></footer></Modal>}
    {editingChart && <Modal title={translateUi("Nome do gráfico")} onClose={()=>setEditingChart(undefined)}><div className="confirm-copy"><input autoFocus aria-label={translateUi("Nome do gráfico")} value={editingChart.title} onChange={e=>setEditingChart({...editingChart,title:e.target.value})}/></div><footer className="modal-footer"><button className="primary-button" onClick={()=>{workspace.patchSession(session.id,s=>({...s,modified:true,extras:{...s.extras,charts:charts.map(c=>c.id === editingChart.id?{...c,title:editingChart.title.trim() || c.title,config:{...c.config,title:editingChart.title.trim() || c.title}}:c)}}));setEditingChart(undefined);}}>{translateUi("Salvar")}</button></footer></Modal>}
    {aboutDialog && <Suspense fallback={null}><AboutDialog onClose={()=>setAboutDialog(false)} onMessage={reportMessage}/></Suspense>}
    {updateDialog && <Suspense fallback={null}><UpdateDialog controller={updates.controller} onClose={()=>setUpdateDialog(false)} beforeInstall={async()=>{workspace.setEditingLocked(true);try{const activity=await runtime.request<{busy:boolean}>("system.activity");if(activity.busy)throw new Error(t("Aguarde ou cancele as operações antes de instalar."));await flushWorkspace.current();}catch(error){workspace.setEditingLocked(false);throw error;}}}/></Suspense>}
    {packageDialog && <Suspense fallback={null}><PackageManagerDialog onClose={()=>setPackageDialog(false)} onError={reportMessage}/></Suspense>}
    {notificationDialog && <Suspense fallback={null}><NotificationsDialog sessionId={session.id} config={session.extras.notification_config as NotificationConfig} context={notificationContext(session)} onDefaults={flags=>setPreferences(p=>({...p,...flags}))} onSave={notification_config=>workspace.patchSession(session.id,s=>({...s,modified:true,extras:{...s.extras,notification_config}}))} onClose={()=>setNotificationDialog(false)}/></Suspense>}
    {workspaceManager && <Suspense fallback={null}><WorkspaceManagerDialog busy={state.sessions.some(s=>s.busy) || switchingProfile} onSelect={selectProfile} onClose={()=>setWorkspaceManager(false)} onMessage={reportMessage}/></Suspense>}
    <NotificationToasts center={notificationCenter} entries={notificationState.toasts} onActivate={openNotification}/>
    {notificationHistory && <NotificationHistory center={notificationCenter} entries={notificationState.entries} onActivate={openNotification} onSettings={()=>{setNotificationHistory(false);setNotificationDialog(true);}} onClose={()=>setNotificationHistory(false)}/>}
    {connectionDialog && <ConnectionDialog initial={session.connection} onClose={() => setConnectionDialog(false)} onConnect={async (config) => { await workspace.connect(session.id, config); setExplorerRefresh(n=>n+1); }} />}
    {settingsDialog && <SettingsDialog preferences={preferences} shortcuts={shortcuts} transfer={configurationActions} onClose={() => setSettingsDialog(false)} onSave={async(p,next) => { await saveNotificationFlags(runtime,p);setPreferences(p);if(p.notifications && !preferences.notifications && isDesktop())run(requestPermission());setShortcuts(next); workspace.patchSession(session.id,s=>({...s,extras:{...s.extras,shared_delimiter:p.sharedDelimiter}})); try { localStorage.setItem("datapyn.desktop.shortcuts.v1", JSON.stringify(next)); } catch { reportMessage("Atalhos aplicados. Não foi possível persistir nesta máquina."); } setSettingsDialog(false); }} />}
    {connectionPicker && <ConnectionPicker currentId={session.blocks.find(b=>b.id === connectionPicker)?.connection_id ?? session.savedConnectionId} onSelect={c => { if (connectionPicker === session.blocks[0].id) run(connectSaved(c).then(()=>workspace.updateBlock(session.id,session.blocks[0].id,{connection_id:undefined,database_name:undefined,schema:undefined}))); else workspace.updateBlock(session.id,connectionPicker,{connection_id:c.id,database_name:undefined,schema:undefined}); setConnectionPicker(undefined); requestAnimationFrame(()=>focusEditor(session.focusedBlockId)); }} onDefault={()=>{workspace.updateBlock(session.id,connectionPicker,{connection_id:undefined,database_name:undefined,schema:undefined});setConnectionPicker(undefined);}} onClose={()=>setConnectionPicker(undefined)}/>}
    {connectionsManager && <div className="modal-overlay"><section className="modal connection-manager" role="dialog" aria-modal="true" aria-label={translateUi("Gerenciar conexões")}><header className="modal-header"><h2>{translateUi("Gerenciar conexões")}</h2><button onClick={()=>setConnectionsManager(false)}>{translateUi("×")}</button></header><ConnectionsSidebar activeConnectionId={session.savedConnectionId} onConnect={connectSaved} onError={reportMessage}/></section></div>}
    {closingId && <div className="modal-overlay"><section className="modal confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="close-title"><header className="modal-header"><Save size={18} /><div><h2 id="close-title">{translateUi("Salvar alterações?")}</h2><p>{workspace.session(closingId)?.title}</p></div></header><p className="confirm-copy">{translateUi("Salve a análise em um arquivo .dpw antes de fechar a aba.")}</p><footer className="modal-footer"><button className="secondary-button" onClick={() => setClosingId(undefined)}>{translateUi("Voltar")}</button><button className="secondary-button" onClick={() => run(closeConfirmed(false))}>{translateUi("Descartar")}</button><button className="primary-button" onClick={() => run(closeConfirmed(true))}>{translateUi("Salvar e fechar")}</button></footer></section></div>}
  </div>;
}

const BlockCard = memo(function BlockCard({ block, index, count, session, disabled, locked, onRun, preferences, onPickConnection, onDownload, onFontSizeChange, forceMount, onEditorReady, diagnosticsReady, diagnosticRevision, diagnosticContext, scopeMetadata, onScopeChange, scopeRefresh, scopeReady }: { scopeMetadata:(session:SessionDocument,block:Block)=>ReturnType<SessionLanguageContexts["get"]>;onScopeChange:(sessionId:string,blockId:string,context:ExplorerContext)=>Promise<void>;scopeRefresh:number;scopeReady:boolean;block: Block; index: number; count: number; session: SessionDocument; disabled: boolean; locked:boolean; onRun: () => void; preferences: Preferences; onPickConnection: () => void; onDownload:()=>void; onFontSizeChange:(size:number)=>void;forceMount:boolean;onEditorReady:(id:string)=>void;diagnosticsReady:boolean;diagnosticRevision:string;diagnosticContext:(sessionId:string)=>{globalImports:string;preamble:string} }) {
  const [height, setHeight] = useState(typeof block.height === "number" ? Math.max(130, block.height) : block.language === "sql" ? 210 : 190);
  const maximized = session.maximizedBlockId === block.id;
  const [actions,setActions]=useState<{owner:Document;anchor:{x:number;y:number};button:HTMLElement}>();
  const catalog = useSyncExternalStore(connections.subscribe, connections.getSnapshot);
  const customConnection = catalog.catalog.connections.find(c => c.id === (block.connection_id ?? session.savedConnectionId));
  const dialect = blockConnectionConfig(session,block)?.db_type;
  const scope = blockScope(session, block),metadata=scopeMetadata(session,block);
  const diagnosticKey = JSON.stringify([session.id, scope.connectionId, scope.database, scope.schema, scope.scopeInherited, dialect, preferences.sharedDelimiter, preferences.locale, diagnosticRevision]);
  useParameterScan(block.language === "sql" ? [block.code] : [], (block.sql_parameters ?? []) as ParameterDefinition[], false, preferences.sharedDelimiter,
    parameters => workspace.updateBlock(session.id,block.id,{sql_parameters:parameters}));
  return <article style={{pointerEvents:locked ? "none" : undefined,...(session.maximizedBlockId && session.maximizedBlockId !== block.id ? {display:"none"} : {}),borderLeftColor:effectiveConnectionColor(block.connection_id ?? session.savedConnectionId ?? "",catalog.catalog)}} className={`code-block ${block.language} ${session.focusedBlockId === block.id ? "focused" : ""} ${session.maximizedBlockId === block.id ? "maximized" : ""}`} data-block-id={block.id}
    onDragOver={e=>{if (e.dataTransfer.types.includes("application/x-datapyn-block") || e.dataTransfer.types.includes(CONNECTION_MIME)) e.preventDefault();}}
    onDrop={e=>{e.preventDefault();const source = e.dataTransfer.getData("application/x-datapyn-block");const connection = e.dataTransfer.getData(CONNECTION_MIME);if(source) workspace.reorderBlock(session.id,source,block.id);if(connection && index > 0) workspace.updateBlock(session.id,block.id,{connection_id:connection,database_name:undefined,schema:undefined});}}>
    <div className="block-header" onClick={()=>workspace.focusBlock(session.id,block.id)} onDoubleClick={event=>{
      if(event.target === event.currentTarget || (event.target as Element).matches(".block-header-controls, .block-header-details")) workspace.maximizeBlock(session.id,block.id);
    }}>
      <div className="block-header-controls"><span draggable={!session.busy} onDragStart={e=>{e.dataTransfer.setData("application/x-datapyn-block",block.id);e.dataTransfer.effectAllowed="move";}}><GripVertical className="block-grip" size={13} /></span><button title={block.collapsed ? "Expandir bloco" : "Recolher bloco"} onClick={()=>workspace.updateBlock(session.id,block.id,{collapsed:!block.collapsed})}>{block.collapsed ? <ChevronRight size={12}/> : <ChevronDown size={12}/>}</button>
        <button className="block-run" disabled={disabled} onClick={onRun} aria-label={translateUi("Executar bloco ou seleção")} title={translateUi("Executar bloco ou seleção")}><Play size={12} fill="currentColor" /></button>
        <span className="block-index">{String(index + 1).padStart(2, "0")}</span><select className={`language-select ${block.language}`} aria-label={`Linguagem do bloco ${index + 1}`} value={block.language} disabled={session.busy} onChange={(event) => workspace.updateBlock(session.id, block.id, { language: event.target.value as "sql" | "python" })}><option value="sql">{translateUi("SQL")}</option><option value="python">{translateUi("Python")}</option></select>
      </div>
      <div className="block-header-details">
      <input className="block-name" value={block.block_name} placeholder={translateUi(block.language === "sql" ? "Nome do resultado (df)" : "Nome do bloco")} aria-label={`Nome do bloco ${index + 1}`} onChange={(event) => workspace.updateBlock(session.id, block.id, { block_name: event.target.value })} />
      {block.language === "sql" && <><button className="block-scope" disabled={session.busy} title={customConnection?.name ?? session.connection?.name ?? translateUi("Conexão da aba")} onClick={onPickConnection}><Database size={12}/><span>{customConnection?.name ?? session.connection?.name ?? translateUi("Conexão da aba")}</span></button>
        <BlockScopePicker sessionId={session.id} blockId={block.id} scopeInherited={scope.scopeInherited} connectionId={scope.connectionId} dbType={dialect} database={metadata?.schemaSnapshot?.database ?? scope.database} schema={metadata?.schemaSnapshot?.current_schema ?? scope.schema}
          connected={scopeReady && Boolean(scope.connectionId || session.connection)} disabled={session.busy || locked} refresh={scopeRefresh} onError={reportMessage}
          onChange={context=>onScopeChange(session.id,block.id,context)} /></>}
      {!block.is_active && <span className="block-inactive">{translateUi("Desativado")}</span>}
      {block.status !== "idle" && <span className={`block-status ${block.status}`} title={translateUi(statusLabel[block.status])} aria-label={translateUi(statusLabel[block.status])}>{block.status === "running" || block.status === "cancelling" ? <><LoaderCircle size={12} className="spin"/>{translateUi(statusLabel[block.status])}</> : block.status !== "succeeded" ? translateUi(statusLabel[block.status]) : null}{block.duration_ms !== undefined && ["succeeded","failed"].includes(block.status) && <span>{(block.duration_ms/1000).toFixed(2)} s</span>}</span>}
      <button className="icon-button" aria-label={translateUi("Ações do bloco")} title={translateUi("Ações do bloco")} aria-haspopup="menu" aria-expanded={Boolean(actions)} onClick={e=>{const rect=e.currentTarget.getBoundingClientRect();setActions({owner:e.currentTarget.ownerDocument,anchor:{x:rect.right,y:rect.bottom},button:e.currentTarget});}}><MoreHorizontal size={15}/></button>
      {actions && <ContextMenu ownerDocument={actions.owner} anchor={actions.anchor} returnFocus={actions.button} label={translateUi("Ações do bloco")} onClose={()=>setActions(undefined)} items={[
        {label:translateUi(block.is_active ? "Desativar na execução de todos" : "Ativar na execução de todos"),disabled:session.busy,onSelect:()=>workspace.updateBlock(session.id,block.id,{is_active:!block.is_active})},
        {label:translateUi("Mover bloco para cima"),disabled:index===0 || session.busy,onSelect:()=>workspace.moveBlock(session.id,block.id,-1)},
        {label:translateUi("Mover bloco para baixo"),disabled:index===count-1 || session.busy,onSelect:()=>workspace.moveBlock(session.id,block.id,1)},
        {label:translateUi("Duplicar bloco"),disabled:session.busy,onSelect:()=>workspace.duplicateBlock(session.id,block.id)},
        ...(block.language === "sql" ? [{label:translateUi("Baixar consulta"),disabled,onSelect:onDownload}] : []),
        {label:translateUi("Maximizar ou restaurar bloco"),onSelect:()=>workspace.maximizeBlock(session.id,block.id)},
        {label:translateUi("Excluir bloco"),separator:true,danger:true,disabled:session.busy,onSelect:()=>{workspace.removeBlock(session.id,block.id);disposeModel(block.id);}},
      ]}/>}
      </div>
    </div>
    <div className="block-body" hidden={block.collapsed}>
    {block.cell_type && block.cell_type !== "code" ? <Suspense fallback={<pre>{block.code}</pre>}><MarkdownBlock code={block.code} raw={block.cell_type === "raw"} onChange={code=>workspace.updateBlock(session.id,block.id,{code})}/></Suspense> : <ViewportEditor forceMount={forceMount || maximized} onReady={onEditorReady} id={block.id} code={block.code} language={block.language} height={maximized ? "100%" : height} preferences={{readOnly:locked,theme:preferences.theme,fontFamily:preferences.editorFont,fontSize:preferences.editorFontSize,wordWrap:preferences.wordWrap,minimap:preferences.minimap,lineNumbers:preferences.lineNumbers,tabSize:preferences.tabSize,autocomplete:preferences.autocomplete,aiAutocomplete:preferences.aiAutocomplete}} onFontSizeChange={onFontSizeChange} onChange={(code) => workspace.updateBlock(session.id, block.id, { code })} onFocus={() => workspace.focusBlock(session.id, block.id)} />}
    <ParameterPanel title={translateUi("Parâmetros SQL")} parameters={(block.sql_parameters ?? []) as ParameterDefinition[]} enabled={block.sql_parameters_enabled !== false} disabled={session.busy} onEnabled={enabled=>workspace.updateBlock(session.id,block.id,{sql_parameters_enabled:enabled})} onChange={parameters=>workspace.updateBlock(session.id,block.id,{sql_parameters:parameters})}/>
    <div className="block-resizer" onPointerDown={(event) => { event.preventDefault(); const owner=event.currentTarget.ownerDocument.defaultView ?? window; const startY = event.clientY, startHeight = height; let nextHeight = height;
      const move = (pointer: PointerEvent) => { nextHeight = Math.max(130, Math.min(900, startHeight + pointer.clientY - startY)); setHeight(nextHeight); };
      const up = () => { workspace.updateBlock(session.id, block.id, { height: nextHeight }); owner.removeEventListener("pointermove", move); owner.removeEventListener("pointerup", up); };
      owner.addEventListener("pointermove", move); owner.addEventListener("pointerup", up, { once: true }); }} />
    </div>
    <BlockSyntaxDiagnostics id={block.id} code={block.code} language={block.language} enabled={!block.cell_type || block.cell_type === "code"} ready={diagnosticsReady} focused={session.focusedBlockId === block.id} contextKey={diagnosticKey}
      params={() => { const context = block.language === "python" ? diagnosticContext(session.id) : undefined; return { session_id: session.id, block_id:block.id, scope_inherited:scope.scopeInherited,connection_id: scope.connectionId, database: scope.database, schema: scope.schema, db_type: dialect, shared_delimiter: preferences.sharedDelimiter, locale: preferences.locale, global_imports: context?.globalImports, preamble: context?.preamble }; }}
      onReveal={marker => { workspace.updateBlock(session.id, block.id, { collapsed: false }); workspace.focusBlock(session.id, block.id); revealEditorRange(block.id, { startLineNumber: marker.start_line, startColumn: marker.start_column, endLineNumber: marker.end_line, endColumn: marker.end_column }); }} />
  </article>;
}, (before,after)=>before.block === after.block && before.index === after.index && before.count === after.count && before.disabled === after.disabled && before.locked === after.locked && before.forceMount === after.forceMount && before.onEditorReady === after.onEditorReady && before.preferences === after.preferences && before.scopeReady === after.scopeReady && before.scopeRefresh === after.scopeRefresh && before.scopeMetadata === after.scopeMetadata && before.onScopeChange === after.onScopeChange && before.diagnosticsReady === after.diagnosticsReady && before.diagnosticRevision === after.diagnosticRevision && before.session.focusedBlockId === after.session.focusedBlockId && before.session.maximizedBlockId === after.session.maximizedBlockId && before.session.connection === after.session.connection && before.session.savedConnectionId === after.session.savedConnectionId && before.session.database === after.session.database && before.session.schema === after.session.schema && before.session.busy === after.session.busy);

function ViewportEditor({forceMount,...props}:{id:string;code:string;language:"sql"|"python";height:number|"100%";preferences:EditorPreferences;onFontSizeChange:(size:number)=>void;onChange:(code:string)=>void;onFocus:()=>void;forceMount:boolean;onReady:(id:string)=>void}) {
  const container=useRef<HTMLDivElement>(null), [visible,setVisible]=useState(false),[startupPinned,setStartupPinned]=useState(forceMount);
  const documentRevision=useOwnerDocumentRevision(container);
  useEffect(()=>{if(forceMount)setStartupPinned(true);},[forceMount]);
  useEffect(()=>{const node=container.current;if(!node)return;const Observer=node.ownerDocument.defaultView?.IntersectionObserver ?? IntersectionObserver;const observer=new Observer(([entry])=>{setVisible(entry.isIntersecting);if(entry.isIntersecting)setStartupPinned(false);},{root:node.closest(".editor-area"),rootMargin:"350px"});observer.observe(node);return()=>observer.disconnect();},[documentRevision]);
  return <div className="block-editor-viewport" ref={container} style={{height:props.height}}>{(visible || forceMount || startupPinned) && <Suspense fallback={<div className="editor-loading">{translateUi("Carregando editor…")}</div>}><MonacoBlock {...props}/></Suspense>}</div>;
}

function OutputPanel({ session }: { session: SessionDocument }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [session.logs]);
  return <div className="output-panel">{session.logs.length ? session.logs.map((line) => <div key={line.id} className={`output-entry ${line.stream}`}><span>{line.time}</span><span className="output-stream">{line.stream === "stderr" ? "ERR" : line.stream === "system" ? "SYS" : "OUT"}</span><pre>{line.text}</pre></div>) : <div className="output-empty"><Terminal size={19} /><span>{translateUi("Sem saída.")}</span></div>}<div ref={end} /></div>;
}
