import { Check, CircleAlert, Square } from "lucide-react";
import { useTranslation } from "./i18n";
import type { CommandExecution } from "./workspace";

export function CommandResults({ executions, blockLabels }: { executions: CommandExecution[]; blockLabels: Record<string, string> }) {
  const { t, locale } = useTranslation();
  return <div className="command-results" aria-label={t("Mensagens de execução")}>
    {executions.map(execution => <section className="command-execution" key={execution.executionId}>
      <div className="command-execution-heading">
        <span>{execution.blockName || blockLabels[execution.blockId ?? ""] || t("SQL")}</span>
        <span>{(execution.durationMs / 1000).toLocaleString(locale, { maximumFractionDigits: 2 })} s</span>
      </div>
      <ol className="command-message-list">
        {execution.commands.map(command => <li className="command-message" key={command.statement_index}>
          <Check size={14} aria-hidden="true" />
          <span className="command-message-label">{command.statement_index}. {command.command}</span>
          <span>{command.rows_affected === null ? t("Comando executado.") : t(command.rows_affected === 1 ? "{rows} linha afetada." : "{rows} linhas afetadas.", { rows: command.rows_affected.toLocaleString(locale) })}</span>
        </li>)}
      </ol>
      {execution.status === "failed" && <div className="command-execution-error"><CircleAlert size={14} aria-hidden="true"/><span>{execution.error || t("Erro na execução.")}</span></div>}
      {execution.status === "cancelled" && <div className="command-execution-cancelled"><Square size={12} aria-hidden="true"/><span>{t("Execução cancelada.")}</span></div>}
    </section>)}
  </div>;
}
