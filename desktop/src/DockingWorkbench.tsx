import {createContext,useContext,useEffect,useRef,type ReactNode} from "react";
import {DockviewReact,themeDark,themeLight,type DockviewApi,type DockviewReadyEvent,type IDockviewPanelProps,type SerializedDockview,type IDockviewHeaderActionsProps} from "dockview-react";
import {Layers3,ExternalLink} from "lucide-react";
import {useTranslation} from "./i18n";
import { copyLazyStylesheets, copyRootPresentation, PopoutBindings, refreshOwnerDocuments, registerDocument } from "./documentWindows";
import "dockview-react/dist/styles/dockview.css";
import "./docking.css";

export type PanelId="editor"|"connections"|"explorer"|"results"|"summary"|"output"|"variables"|"pynia";
const titles:Record<PanelId,string>={editor:"Análise",connections:"Conexões",explorer:"Object Explorer",results:"Resultados",summary:"Resumo",output:"Saída",variables:"Variáveis",pynia:"Pynia"};
const Content=createContext<Partial<Record<PanelId,ReactNode>>>({});
function Panel({api}:IDockviewPanelProps) {
  const element=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    let disposed=false;
    const moved=()=>queueMicrotask(()=>{if(!disposed&&element.current)refreshOwnerDocuments(element.current);});
    const subscription=api.onDidLocationChange(moved);moved();
    return()=>{disposed=true;subscription.dispose();};
  },[api]);
  return <div ref={element} className={`dock-content dock-${api.id}`}>{useContext(Content)[api.id as PanelId]}</div>;
}
function GroupActions({containerApi,group,location}:IDockviewHeaderActionsProps){const {t}=useTranslation();return <div className="dock-group-actions"><button title={t("Flutuar painel")} disabled={location?.type !== "grid"} onClick={()=>containerApi.addFloatingGroup(group,{width:600,height:440})}><Layers3 size={12}/></button><button title={t("Abrir painel em outra janela")} disabled={location?.type === "popout"} onClick={()=>void containerApi.addPopoutGroup(group,{popoutUrl:"/popout.html"})}><ExternalLink size={12}/></button></div>;}
const components={content:Panel};
export interface DockingWorkbenchProps {
  panels:Partial<Record<PanelId,ReactNode>>;initialLayout?:unknown;onLayoutChange:(layout:SerializedDockview)=>void;
  theme:"dark"|"light"|"system";leftWidth:number;rightWidth:number;resultHeight:number;leftVisible:boolean;rightVisible:boolean;
  activeBottom:"results"|"summary"|"output";activeRight:"variables"|"pynia";onActivate:(id:PanelId)=>void;resetRevision:number;
  onCaptureReady?:(capture:()=>SerializedDockview)=>void;
  onPopoutReady?:(window:Window)=>(()=>void)|void;
}
export function DockingWorkbench(props:DockingWorkbenchProps) {
  const {t,locale}=useTranslation();
  const api=useRef<DockviewApi>(),current=useRef(props);current.current=props;
  const disposables=useRef<Array<{dispose:()=>void}>>([]),saveTimer=useRef<ReturnType<typeof setTimeout>>();
  const popouts=useRef<PopoutBindings>();
  if(!popouts.current)popouts.current=new PopoutBindings(view=>{
    copyRootPresentation(document,view.document);copyLazyStylesheets(document,view.document);
    view.document.querySelector(".dv-popout-window")?.classList.add("datapyn-dock");
    const unregister=registerDocument(view.document),cleanup=current.current.onPopoutReady?.(view);
    return()=>{try{cleanup?.();}finally{unregister();}};
  });
  const add=(id:PanelId)=>{
    const a=api.current!;if(a.getPanel(id))return;
    const reference=id === "explorer" ? a.getPanel("connections") : id === "output" || id === "summary" ? a.getPanel("results") : id === "pynia" ? a.getPanel("variables") : a.getPanel("editor");
    const direction=id === "connections" ? "left" : id === "variables" ? "right" : id === "results" || id === "explorer" ? "below" : "within";
    a.addPanel({id,title:t(titles[id]),component:"content",renderer:"always",inactive:id === "output" || id === "summary" || id === "pynia",position:reference?{referencePanel:reference,direction}:undefined,initialWidth:id === "connections"?current.current.leftWidth:id === "variables"?current.current.rightWidth:undefined,initialHeight:id === "results"?current.current.resultHeight:undefined});
  };
  const reset=()=>{const a=api.current;if(!a)return;a.clear();add("editor");add("results");add("summary");add("output");if(current.current.leftVisible){add("connections");add("explorer");}if(current.current.rightVisible){add("variables");add("pynia");}a.getPanel(current.current.activeBottom)?.api.setActive();a.getPanel("editor")?.api.setActive();};
  const ready=({api:next}:DockviewReadyEvent)=>{
    api.current=next;
    current.current.onCaptureReady?.(()=>next.toJSON());
    disposables.current.push(next.onDidAddPopoutGroup(({window:view})=>popouts.current?.add(view)));
    disposables.current.push(next.onDidRemovePopoutGroup(()=>popouts.current?.update(next.getPopouts().map(entry=>entry.window))));
    disposables.current.push(next.onWillClosePopoutWindow(({window:view})=>popouts.current?.remove(view)));
    try{if(current.current.initialLayout)next.fromJSON(current.current.initialLayout as SerializedDockview);else reset();}catch{reset();}
    for(const id of ["editor","results","summary","output"] as PanelId[])add(id);
    disposables.current.push(next.onDidLayoutChange(()=>{if(saveTimer.current)clearTimeout(saveTimer.current);saveTimer.current=setTimeout(()=>current.current.onLayoutChange(next.toJSON()),150);}));
    disposables.current.push(next.onDidActivePanelChange(event=>{if(event.panel)current.current.onActivate(event.panel.id as PanelId);}));
    popouts.current?.update(next.getPopouts().map(entry=>entry.window));
  };
  useEffect(()=>{const a=api.current;if(!a)return;for(const [ids,visible] of [[(["connections","explorer"] as PanelId[]),props.leftVisible],[(["variables","pynia"] as PanelId[]),props.rightVisible]] as const){for(const id of ids){if(visible)add(id);else{const panel=a.getPanel(id);if(panel)a.removePanel(panel);}}}},[props.leftVisible,props.rightVisible]);
  useEffect(()=>{if(!api.current)return;add(props.activeBottom);api.current.getPanel(props.activeBottom)?.api.setActive();},[props.activeBottom]);
  useEffect(()=>{api.current?.getPanel(props.activeRight)?.api.setActive();},[props.activeRight]);
  useEffect(()=>{api.current?.panels.forEach(panel=>panel.api.setTitle(t(titles[panel.id as PanelId] ?? panel.id)));},[locale]);
  const initialReset=useRef(props.resetRevision);useEffect(()=>{if(initialReset.current === props.resetRevision)return;initialReset.current=props.resetRevision;reset();},[props.resetRevision]);
  useEffect(()=>{
    const update=()=>popouts.current?.forEach(view=>{if(!view.closed)copyRootPresentation(document,view.document);});
    const observer=new MutationObserver(update);
    observer.observe(document.documentElement,{attributes:true,attributeFilter:["style","data-theme","lang","dir"]});
    update();return()=>observer.disconnect();
  },[]);
  useEffect(()=>{
    const update=()=>popouts.current?.forEach(view=>{if(!view.closed)copyLazyStylesheets(document,view.document);});
    const observer=new MutationObserver(update);observer.observe(document.head,{childList:true});
    return()=>observer.disconnect();
  },[]);
  useEffect(()=>()=>{if(saveTimer.current)clearTimeout(saveTimer.current);disposables.current.forEach(d=>d.dispose());disposables.current=[];popouts.current?.dispose();},[]);
  const light=props.theme === "light" || (props.theme === "system" && matchMedia("(prefers-color-scheme: light)").matches);
  return <Content.Provider value={props.panels}><DockviewReact className="datapyn-dock" components={components} onReady={ready} theme={light?themeLight:themeDark} rightHeaderActionsComponent={GroupActions} popoutUrl="/popout.html" getTabContextMenuItems={({panel})=>panel.id === "editor"?["maximize","float","popout"]:["close","separator","maximize","float","popout"]}/></Content.Provider>;
}
