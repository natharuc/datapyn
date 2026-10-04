import { memo, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { AlertCircle, AlertTriangle, Check, ChevronDown, ChevronRight, Circle, LoaderCircle, RefreshCw } from "lucide-react";
import { diagnosticRefreshers } from "./editorRegistry";
import { featureTranslate as t } from "./featureTranslations";
import { useLocale } from "./i18n";
import type { LanguageMarker } from "./editorLanguage";
import type { Language } from "./runtime";
import { syntaxDiagnostics } from "./syntaxDiagnostics";
import "./syntaxDiagnostics.css";

interface Props {
  id: string; code: string; language: Language; enabled: boolean; ready: boolean; focused: boolean;
  contextKey: string; params: () => Record<string, unknown>; onReveal: (marker: LanguageMarker) => void;
}
export const BlockSyntaxDiagnostics = memo(function BlockSyntaxDiagnostics(props: Props) {
  useLocale();
  const latest = useRef(props); latest.current = props;
  const state = useSyncExternalStore(listener => syntaxDiagnostics.subscribe(props.id, listener), () => syntaxDiagnostics.snapshot(props.id));
  const [expanded, setExpanded] = useState(false), [limit, setLimit] = useState(20);
  useEffect(() => {
    const refresh = () => { const current = latest.current; syntaxDiagnostics.update(current.id, { ...current, params: () => latest.current.params() }); };
    refresh(); diagnosticRefreshers.set(props.id, () => syntaxDiagnostics.refresh(props.id));
    return () => { diagnosticRefreshers.delete(props.id); syntaxDiagnostics.remove(props.id); };
  }, [props.id]);
  useEffect(() => { syntaxDiagnostics.update(props.id, { ...props, params: () => latest.current.params() }); }, [props.id, props.code, props.language, props.contextKey, props.ready, props.enabled, props.focused]);
  if (!props.enabled) return null;
  const errors = state.markers.filter(marker => marker.severity === "error").length;
  const warnings = state.markers.filter(marker => marker.severity === "warning").length;
  const busy = state.status === "checking" || state.status === "scheduled";
  const tone = errors ? "error" : state.status === "partial" || state.status === "unavailable" || warnings ? "warning" : state.status === "complete" ? "valid" : "quiet";
  const label = errors ? errors === 1 ? t("1 erro de sintaxe") : t("{count} erros de sintaxe", { count: errors }) : state.status === "partial" ? t("Validação parcial") : state.status === "unavailable" ? t("Validação indisponível") : busy ? t("Validando sintaxe…") : warnings ? warnings === 1 ? t("1 aviso") : t("{count} avisos", { count: warnings }) : state.status === "complete" ? t("Sintaxe válida") : t("Bloco vazio");
  const first = state.markers.find(marker => marker.severity === "error") ?? state.markers[0];
  const hasDetails = Boolean(first || state.message);
  const message = state.message ? t(state.message) : undefined;
  return <div className={`syntax-diagnostics ${tone}`}>
    <div className="syntax-summary">
      <button className="syntax-toggle" disabled={!hasDetails} aria-expanded={expanded && hasDetails} aria-label={t("Diagnósticos de sintaxe do bloco")} onClick={() => { setExpanded(value => !value); setLimit(20); }} title={message ?? first?.message ?? label}>
        {busy ? <LoaderCircle size={12} className="spin" /> : errors ? <AlertCircle size={12} /> : tone === "warning" ? <AlertTriangle size={12} /> : tone === "valid" ? <Check size={12} /> : <Circle size={10} />}
        <span>{label}</span>{hasDetails && (expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />)}
      </button>
      {first && <button className="syntax-first" onClick={() => props.onReveal(first)} title={first.message}><span className="syntax-position">{t("L{line}:C{column}", { line: first.start_line, column: first.start_column })}</span><span>{first.message}</span></button>}
      {state.status === "unavailable" && <button className="syntax-retry" aria-label={t("Tentar validar novamente")} onClick={() => syntaxDiagnostics.refresh(props.id)}><RefreshCw size={12} /></button>}
    </div>
    {expanded && hasDetails && <div className="syntax-details">
      {message && <p>{message}</p>}
      {state.markers.slice(0, limit).map((marker, index) => <button key={index} className={`syntax-issue ${marker.severity}`} onClick={() => props.onReveal(marker)}>
        <span className="syntax-severity">{t(marker.severity === "error" ? "Erro" : marker.severity === "warning" ? "Aviso" : "Informação")}</span>
        <span className="syntax-position">{t("Linha {line}, coluna {column}", { line: marker.start_line, column: marker.start_column })}</span><span>{marker.message}</span>
      </button>)}
      {state.markers.length > limit && <button className="syntax-more" onClick={() => setLimit(value => value + 20)}>{t("Mostrar mais diagnósticos ({count})", { count: state.markers.length - limit })}</button>}
    </div>}
  </div>;
});
