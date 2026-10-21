import {useSyncExternalStore} from "react";
import {AlertTriangle} from "lucide-react";
import {Modal} from "./PanelControls";
import {useTranslation} from "./i18n";
import {sqlConfirmations} from "./sqlConfirmation";
import "./sqlSafety.css";

export function SqlSafetyConfirmation() {
  const {t} = useTranslation();
  const pending = useSyncExternalStore(sqlConfirmations.subscribe, sqlConfirmations.getSnapshot);
  if (!pending) return null;
  const {review, id} = pending;
  const context = [
    ["Bloco", [review.tab_name, review.block_name].filter(Boolean).join(" / ")],
    ["Conexão", review.connection_name], ["Banco", review.database], ["Schema", review.schema],
  ].filter(([, value]) => value);
  return <Modal key={id} title={t("Confirmar execução SQL")} className="sql-safety-dialog" onClose={() => sqlConfirmations.respond(id, false)}>
    <div className="sql-safety-body">
      <p className="sql-safety-summary"><AlertTriangle size={17}/>{t("Esta execução altera dados ou estruturas do banco.")}</p>
      {!!context.length && <dl className="sql-safety-context">{context.map(([label, value]) => <div key={label}><dt>{t(label!)}</dt><dd>{value}</dd></div>)}</dl>}
      <ol className="sql-safety-commands">{review.risks.map((risk, index) => <li key={index}>
        <div className="sql-safety-command-label"><strong>{risk.operation}</strong>{risk.target && <code>{risk.target}</code>}
          {risk.unfiltered && <span className="sql-safety-unfiltered">{t(["DELETE", "UPDATE"].includes(risk.operation) ? "Sem WHERE · todas as linhas" : "Objeto inteiro")}</span>}
        </div>
        <pre>{risk.preview}</pre>
      </li>)}</ol>
      {review.code && <details className="sql-safety-source"><summary>{t("Código a executar")}</summary><pre>{review.code}</pre></details>}
    </div>
    <footer className="modal-footer"><button className="secondary-button" onClick={() => sqlConfirmations.respond(id, false)}>{t("Cancelar")}</button><button className="primary-button" onClick={() => sqlConfirmations.respond(id, true)}>{t("Executar")}</button></footer>
  </Modal>;
}
