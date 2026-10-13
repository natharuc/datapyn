import {memo, useEffect, useState} from "react";
import {LoaderCircle} from "lucide-react";
import {translate as t, useLocale} from "./i18n";
import type {Block} from "./workspace";
import "./blockExecutionStatus.css";

const labels = {idle:"", queued:"Na fila", running:"Executando", cancelling:"Cancelando", succeeded:"Concluído", failed:"Erro", cancelled:"Cancelado"};

export function formatExecutionTime(milliseconds:number):string {
  const total=Math.floor(Number.isFinite(milliseconds)?Math.max(0,milliseconds):0);
  const seconds=Math.floor(total/1000),fraction=String(total%1000).padStart(3,"0");
  if(seconds<60)return `${seconds}.${fraction} s`;
  const minutes=Math.floor(seconds/60),second=String(seconds%60).padStart(2,"0");
  if(minutes<60)return `${minutes}:${second}.${fraction}`;
  return `${Math.floor(minutes/60)}:${String(minutes%60).padStart(2,"0")}:${second}.${fraction}`;
}

function useExecutionElapsed(active:boolean,started:number|undefined,duration:number|undefined):number|undefined {
  const [measurement,setMeasurement]=useState<{started?:number;elapsed:number}>({elapsed:0});
  useEffect(()=>{
    if(!active || started===undefined)return;
    // Wall time anchors a remounted/popped-out block; monotonic ticks ignore clock adjustments.
    const initial=Math.max(0,Date.now()-started),anchor=performance.now();
    const tick=()=>setMeasurement({started,elapsed:initial+Math.max(0,performance.now()-anchor)});
    tick(); const timer=setInterval(tick,100);
    return()=>clearInterval(timer);
  },[active,started]);
  return active?(started===undefined?0:measurement.started===started?measurement.elapsed:Math.max(0,Date.now()-started)):duration;
}

/** Only the small clocks tick; editor models and result grids remain untouched. */
export const SessionExecutionTime=memo(function SessionExecutionTime({active,started,duration}:{active:boolean;started?:number;duration?:number}) {
  useLocale();
  const elapsed=useExecutionElapsed(active,started,duration);
  return <time className="execution-time" aria-label={t("Tempo de execução")}>{formatExecutionTime(elapsed??0)}</time>;
});

export const BlockExecutionStatus=memo(function BlockExecutionStatus({block}:{block:Block}) {
  useLocale();
  const active=block.status==="running" || block.status==="cancelling";
  const started=typeof block.executionStartedAt==="number"?block.executionStartedAt:undefined;
  const duration=useExecutionElapsed(active,started,block.duration_ms);
  if(block.status==="idle")return null;
  return <span className={`block-status ${block.status}`} title={t(labels[block.status])} aria-label={t(labels[block.status])}>
    {active && <LoaderCircle size={12} className="spin" aria-hidden="true"/>}
    {block.status!=="succeeded" && <span className="block-status-label">{t(labels[block.status])}</span>}
    {!active && block.transactionState?.pending === true && <span className="block-transaction-state" title={t("Use COMMIT ou ROLLBACK neste bloco para finalizar a transação.")}>{t("Transação aberta")}</span>}
    {!active && block.transactionState?.pending === null && <span className="block-transaction-state" title={t("A conexão foi interrompida ou não foi possível verificar a transação.")}>{t("Transação: estado desconhecido")}</span>}
    {duration!==undefined && <time className="block-elapsed" aria-label={t("Tempo de execução")}>{formatExecutionTime(duration)}</time>}
  </span>;
});

export function BlockExecutionLine({active}:{active:boolean}) {
  return active?<div className="block-execution-line" aria-hidden="true"><span/></div>:null;
}
