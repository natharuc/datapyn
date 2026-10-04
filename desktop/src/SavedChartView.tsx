import {useEffect,useRef,useState} from "react";
import type {SessionDocument} from "./workspace";
import type {ChartConfig,DataView} from "./dataTypes";
import {runtime,errorText,type ResultRef} from "./runtime";
import {latestChartSource,normalizeChartConfig,type SavedChart,type ChartSourceCache} from "./chartModel";
import {ChartPanel} from "./ChartPanel";
import {featureTranslate as t} from "./featureTranslations";

interface Props {
  session:SessionDocument; chart:SavedChart; sourceCache:ChartSourceCache; currentResult?:ResultRef; view?:DataView;
  active:boolean; disabled:boolean; theme:"dark"|"light"|"system";
  prepareSource:()=>Promise<void>;
  onChange:(chart:SavedChart)=>void; onDuplicate:()=>void;
  onMove:(direction:-1|1)=>void; canMoveLeft:boolean; canMoveRight:boolean;
  onMessage:(message:string)=>void;
}

/** Reopens a restored namespace frame without reopening a user-closed result tab. */
export function SavedChartView({session,chart,sourceCache,currentResult,view,active,disabled,theme,prepareSource,onChange,onDuplicate,onMove,canMoveLeft,canMoveRight,onMessage}:Props) {
  const [inspected,setInspected]=useState<{revision:number;result:ResultRef}>(),[error,setError]=useState("");
  const [lookup,setLookup]=useState(false);
  const alive=useRef(true),sourceRequest=useRef(0),latest=useRef({session,chart});latest.current={session,chart};
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;sourceRequest.current++;};},[]);
  // A displayed result can outlive a reassigned Python variable. Resolve the
  // canonical namespace frame once per revision rather than reuse its history.
  const source=inspected?.revision === session.resultRevision && inspected.result.variable_name === chart.variable_name ? inspected.result : undefined;
  const inspect=(name:string)=>sourceCache.resolve(session.id,session.resultRevision,name,async()=>{
    await prepareSource();
    const value=await runtime.request<{result?:ResultRef}>("variable.inspect",{session_id:session.id,name,limit:1});
    if(!value.result)throw new Error(t("A fonte deste gráfico precisa ser um DataFrame ou uma Series."));
    return value.result;
  });
  useEffect(()=>{
    if(source || !active || disabled)return;
    let disposed=false;setLookup(true);setError("");
    void inspect(chart.variable_name).then(result=>{
      if(disposed)return;
      setInspected({revision:session.resultRevision,result});
    },failure=>{if(!disposed)setError(errorText(failure));}).finally(()=>{if(!disposed)setLookup(false);});
    return()=>{disposed=true;};
  },[session.id,session.resultRevision,chart.variable_name,source?.result_id,active,disabled]);
  const names=[...new Set([...session.results.map(r=>r.variable_name),...session.variables.filter(v=>/DataFrame|Series/.test(v.type)).map(v=>v.name),chart.variable_name])];
  const available=names.map(name=>latestChartSource(name,session.results) ?? (source?.variable_name === name ? source : {result_id:"",variable_name:name,row_count:0,columns:[]} as ResultRef));
  async function changeSource(name:string){
    if(!source || name === chart.variable_name)return;
    const token=++sourceRequest.current,revision=session.resultRevision;
    try{
      const nextSource=await inspect(name);
      if(!alive.current || token!==sourceRequest.current || latest.current.session.id!==session.id || latest.current.session.resultRevision!==revision)return;
      if(!nextSource)throw new Error(t("A fonte deste gráfico precisa ser um DataFrame ou uma Series."));
      setInspected({revision:session.resultRevision,result:nextSource});
      const current=latest.current.chart;
      const config:ChartConfig={...normalizeChartConfig(nextSource,current.config),source_label:name};
      const defaults=normalizeChartConfig(nextSource),columns=new Set(nextSource.columns.map(c=>c.name));
      if(config.x_column && !columns.has(config.x_column))config.x_column=defaults.x_column;
      config.y_columns=config.y_columns?.filter(c=>columns.has(c));
      if(!config.y_columns?.length)config.y_columns=defaults.y_columns;
      if(typeof config.group_by === "string" && !columns.has(config.group_by))config.group_by="";
      delete config.selection_view;if(config.source_mode === "selection")config.source_mode="filtered";
      onChange({...current,variable_name:name,config});
    }catch(failure){if(alive.current && token===sourceRequest.current)onMessage(errorText(failure));}
  }
  if(!source)return <div className="chart-source-missing"><p>{lookup ? t("Restaurando fonte do gráfico…") : error || `${t("Execute o bloco que cria")} ${chart.variable_name} ${t("para restaurar este gráfico.")}`}</p></div>;
  const savedView=(session.extras.table_views as Record<string,DataView> | undefined)?.[source.variable_name];
  return <ChartPanel sessionId={session.id} result={source} view={source.variable_name === currentResult?.variable_name ? view ?? savedView : savedView}
    initialConfig={chart.config} title={chart.title} active={active} disabled={disabled} theme={theme} refreshRevision={session.resultRevision}
    availableResults={available} onSourceChange={name=>void changeSource(name)} onDuplicate={onDuplicate}
    onMove={onMove} canMoveLeft={canMoveLeft} canMoveRight={canMoveRight} onMessage={onMessage}
    onConfigChange={config=>onChange({...chart,title:String(config.title || chart.title),config})}/>;
}
