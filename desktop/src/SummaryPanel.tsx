import { featureTranslate as t } from "./featureTranslations";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { LoaderCircle, RefreshCw, Settings2, Sigma } from "lucide-react";
import { runtime, errorText, type ResultRef } from "./runtime";
import type { DataView, ResultSummary } from "./dataTypes";
import { useLocale } from "./i18n";
import "./summaryPanel.css";

export interface SummaryPanelProps { sessionId: string; result?: ResultRef; view?: DataView; active: boolean; disabled?: boolean; onMessage?: (message: string) => void; onFormatColumn?: (column: string) => void }
const labels: Record<string,string> = {count:"Valores",numeric_count:"Valores numéricos",null_count:"Nulos",distinct:"Distintos",min:"Mínimo",max:"Máximo",sum:"Soma",mean:"Média",median:"Mediana",std:"Desvio padrão",coefficient:"Coeficiente de variação (%)"};
export function SummaryPanel({ sessionId, result, view, active, disabled, onMessage, onFormatColumn }: SummaryPanelProps) {
  useLocale();
  const [summary,setSummary]=useState<ResultSummary>(),[busy,setBusy]=useState(false),[error,setError]=useState(""),[whole,setWhole]=useState(false),[revision,setRevision]=useState(0),[zoom,setZoom]=useState(100);
  const generation=useRef(0),last=useRef(""),message=useRef(onMessage);message.current=onMessage;
  const selection=Boolean(view?.scope?.rectangles?.length || view?.scope?.row_ranges?.length || view?.scope?.column_indices?.length);
  const params={session_id:sessionId,result_id:result?.result_id,filter:view?.filter,sort:view?.sort,...(!whole&&selection?{scope:view?.scope}:{})};
  const key=JSON.stringify({...params,whole,revision});
  useEffect(()=>{generation.current++;last.current="";setSummary(undefined);setError("");},[key,active,disabled]);
  useEffect(()=>{
    if(!active||disabled||busy||!result||(!selection&&!whole)||last.current===key)return;
    const id=generation.current;
    const timer=window.setTimeout(()=>{
      last.current=key;setBusy(true);
      void runtime.request<ResultSummary>("result.summary",params).then(response=>{if(generation.current===id)setSummary(response);}).catch(failure=>{if(generation.current===id){const text=errorText(failure);setError(text);message.current?.(text);}}).finally(()=>setBusy(false));
    },300);
    return()=>window.clearTimeout(timer);
  },[key,active,disabled,busy,result,selection,whole]);
  useEffect(()=>{setWhole(false);last.current="";},[sessionId,result?.result_id]);
  const display=(value:unknown)=>value===null?"—":typeof value==="number"?value.toLocaleString(undefined,{maximumFractionDigits:6}):String(value);
  const statistics=(entries: Record<string,unknown>)=><dl>{Object.entries(entries).filter(([name])=>name in labels).map(([name,value])=><div key={name}><dt>{t(labels[name])}</dt><dd>{display(value)}</dd></div>)}</dl>;
  return <div className="summary-panel" style={{"--summary-scale":zoom/100} as CSSProperties}><header><span><Sigma size={14}/>{t("Resumo da seleção")}</span><label><input type="checkbox" checked={whole} onChange={event=>setWhole(event.target.checked)}/>{t("Resultado completo")}</label><select aria-label={t("Zoom do resumo")} value={zoom} onChange={event=>setZoom(Number(event.target.value))}>{[85,100,115,130].map(level=><option key={level} value={level}>{level}%</option>)}</select><button disabled={busy||disabled||!result||(!selection&&!whole)} aria-label={t("Atualizar resumo")} onClick={()=>setRevision(value=>value+1)}>{busy?<LoaderCircle size={13} className="spin"/>:<RefreshCw size={13}/>}</button></header>
    {!result?<p className="summary-empty">{t("Execute um bloco para analisar os resultados.")}</p>:!selection&&!whole?<p className="summary-empty">{t("Selecione células, linhas ou colunas na grade para acompanhar as estatísticas.")}</p>:busy&&!summary?<p className="summary-empty">{t("Calculando estatísticas…")}</p>:null}
    {error&&<p className="summary-error" role="alert">{error}</p>}
    {summary&&<div className="summary-content"><p className="summary-source"><strong>{result?.variable_name}</strong><span>{summary.row_count.toLocaleString()} {t("linhas")} {t("·")} {summary.column_count} {t("colunas")}{summary.cell_count!==undefined?` · ${summary.cell_count.toLocaleString()} ${t("células")}`:""}{summary.columns_truncated?` · ${t("primeiras 200 colunas")}`:""}</span></p>{summary.aggregates&&<article className="summary-aggregates"><h4>{t("Totais da seleção")}</h4>{statistics({...summary.aggregates,numeric_count:summary.aggregates.count_numeric})}</article>}{summary.columns.map((column,index)=><article key={`${column.name}:${index}`}><h4>{column.name}<small>{column.dtype}</small>{onFormatColumn&&<button disabled={disabled} aria-label={t("Formatar coluna {name}",{name:column.name})} onClick={()=>onFormatColumn(column.name)}><Settings2 size={13}/></button>}</h4>{statistics({...column})}{(column.sampled||column.distinct_sampled)&&<p className="summary-sample">{t(column.distinct_sampled?"Distintos aproximados:":"Aproximação de texto:")} {column.sample_rows?.toLocaleString()} {t("linhas amostradas")}</p>}{column.top&&<div className="summary-top-values">{column.top.map((item,i)=><span key={i}><code>{item.value}</code><b>{item.count.toLocaleString()}</b></span>)}</div>}</article>)}</div>}
  </div>;
}
