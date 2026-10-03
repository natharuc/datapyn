import { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ArrowDown, Bot, Check, ChevronDown, Clock3, Code2, LoaderCircle, Trash2, TriangleAlert } from "lucide-react";
import { useTranslation } from "./i18n";
import { errorText } from "./runtime";
import { pynia, type PyniaDefaults } from "./pynia";
import { cutPyniaOutput, outputToolStatus, pyniaOutputHistory, type OutputActivity, type OutputCut } from "./pyniaOutput";
import "./pyniaOutput.css";

export interface PyniaOutputPanelProps {
  sessionId: string;
  sessionTitle: string;
  initialState?: Record<string, unknown>;
  defaults?: PyniaDefaults;
}

/** A separate dock over the same conversation; opening it never creates another ACP agent. */
export function PyniaOutputPanel({ sessionId, sessionTitle, initialState, defaults }: PyniaOutputPanelProps) {
  const { t } = useTranslation();
  const getState = useCallback(() => pynia.getSnapshot().sessions[sessionId], [sessionId]);
  const state = useSyncExternalStore(pynia.subscribe, getState);
  const [limit, setLimit] = useState(40), [cut, setCut] = useState<{ sessionId: string; value: OutputCut }>();
  const [failure, setFailure] = useState<{ sessionId: string; message: string }>();
  const [following, setFollowing] = useState(true);
  const scroll = useRef<HTMLDivElement>(null), nearBottom = useRef(true);
  const initial = useRef({ initialState, defaults }); initial.current = { initialState, defaults };
  const history = useMemo(() => pyniaOutputHistory(state, limit, cut?.sessionId === sessionId ? cut.value : undefined),
    [state?.messages, state?.thinking, state?.tools, state?.busy, limit, cut, sessionId]);

  useEffect(() => {
    let disposed = false;
    setLimit(40); nearBottom.current = true; setFollowing(true);
    void pynia.attach(sessionId, initial.current.initialState, initial.current.defaults).then(() => {
      if (!disposed) setFailure(undefined);
    }).catch(error => {
      if (!disposed) setFailure({ sessionId, message: errorText(error) });
    });
    return () => { disposed = true; };
  }, [sessionId]);
  useEffect(() => {
    if (nearBottom.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [sessionId, history, state?.error, state?.permissions]);

  const error = state?.error || (failure?.sessionId === sessionId ? failure.message : "");
  const pendingPermission = Boolean(state?.permissions?.length);
  const busy = Boolean(state?.busy);
  function clearDisplay() {
    setCut({ sessionId, value: cutPyniaOutput(state) }); setLimit(40);
    nearBottom.current = true; setFollowing(true);
  }
  function followOutput() {
    nearBottom.current = true; setFollowing(true);
    if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }

  return <section className="pynia-output-panel" aria-label={t("Pynia Output")}>
    <header className="pynia-output-header">
      <Bot size={15} aria-hidden="true" /><strong>{t("Pynia Output")}</strong>
      <span className="pynia-output-session" title={sessionTitle}>{sessionTitle}</span>
      <span className={`pynia-output-status ${error ? "error" : busy ? "busy" : ""}`} role="status">
        {busy ? <LoaderCircle size={11} className="spin" aria-hidden="true" /> : <span className="pynia-output-dot" />}
        {t(error ? "Erro" : pendingPermission ? "Aguardando autorização" : busy ? "Em andamento" : "Pronto")}
      </span>
      <button className="icon-button" title={t("Limpar saída exibida")} aria-label={t("Limpar saída exibida")}
        disabled={!history.activities.length} onClick={clearDisplay}><Trash2 size={13} /></button>
    </header>
    <div className="pynia-output-scroll" ref={scroll} onScroll={event => {
      const element = event.currentTarget, next = element.scrollHeight - element.scrollTop - element.clientHeight < 60;
      nearBottom.current = next; setFollowing(next);
    }}>
      {cut?.sessionId === sessionId && <button className="pynia-output-history-button" onClick={() => { setCut(undefined); setLimit(40); }}>{t("Mostrar histórico")}</button>}
      {history.hasOlder && limit < 200 && <button className="pynia-output-history-button" onClick={() => { nearBottom.current = false; setFollowing(false); setLimit(value => Math.min(200, value + 40)); }}>{t("Mostrar atividades anteriores")}</button>}
      {history.hasOlder && limit >= 200 && <p className="pynia-output-history-limit">{t("Exibindo as 200 atividades mais recentes.")}</p>}
      {!history.activities.length && !error && <div className="pynia-output-empty"><Code2 size={23} aria-hidden="true" /><strong>{t("Acompanhe a Pynia em tempo real")}</strong><p>{t("Ferramentas, raciocínio e progresso do chat desta aba aparecem aqui.")}</p></div>}
      {history.activities.map(entry => <ActivityEntry key={`${sessionId}:${entry.id}`} entry={entry} busy={busy && entry.live} />)}
      {pendingPermission && <p className="pynia-output-permission"><Clock3 size={13} aria-hidden="true" />{t("Aguardando autorização no chat da Pynia.")}</p>}
      {error && <div className="pynia-output-error" role="alert"><TriangleAlert size={14} aria-hidden="true" /><pre>{error}</pre></div>}
    </div>
    {!following && <button className="pynia-output-follow" onClick={followOutput}><ArrowDown size={12} aria-hidden="true" />{t("Ir para a atividade mais recente")}</button>}
  </section>;
}

const ActivityEntry = memo(function ActivityEntry({ entry, busy }: { entry: OutputActivity; busy: boolean }) {
  const { t } = useTranslation(), [expanded, setExpanded] = useState(false);
  const visible = entry.live || expanded;
  return <article className={`pynia-output-entry ${entry.live ? "live" : "saved"}`}>
    <button className="pynia-output-entry-heading" aria-expanded={visible} disabled={entry.live} onClick={() => setExpanded(value => !value)}>
      {busy ? <LoaderCircle size={12} className="spin" aria-hidden="true" /> : <Check size={12} aria-hidden="true" />}
      <strong>{t(entry.live ? busy ? "Atividade atual" : "Última atividade" : "Resposta concluída")}</strong>
      <span>{entry.tools.length} {t("ferramentas")}</span>
      {!entry.live && <ChevronDown size={12} className={expanded ? "expanded" : ""} aria-hidden="true" />}
    </button>
    {visible && <div className="pynia-output-entry-content">
      {entry.thinking && <details className="pynia-output-thinking"><summary>{t("Raciocínio")}</summary><pre>{entry.thinking}</pre></details>}
      {entry.tools.map((tool, index) => {
        const status = outputToolStatus(tool, busy);
        const label = t(status === "completed" ? "Concluída" : status === "running" ? "Em andamento" : status === "error" ? "Erro" : status === "interrupted" ? "Não concluída" : "Ferramenta");
        return <div key={`${tool.id}:${index}`} className={`pynia-output-tool ${status}`}>
          <span className="pynia-output-tool-icon" title={label}>{status === "completed" ? <Check size={13} /> : status === "running" ? <LoaderCircle size={13} className="spin" /> : status === "error" ? <TriangleAlert size={13} /> : status === "interrupted" ? <Clock3 size={13} /> : <Code2 size={13} />}</span>
          <code>{tool.title || tool.id}</code><small>{label}</small>
          {tool.error && <pre>{tool.error}</pre>}
        </div>;
      })}
      {busy && !entry.thinking && !entry.tools.length && <p className="pynia-output-waiting">{t("Gerando resposta…")}</p>}
    </div>}
  </article>;
});
