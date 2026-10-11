import { useEffect, useSyncExternalStore } from "react";
import { translate as t, useLocale } from "./i18n";
import { Modal } from "./PanelControls";
import { sshHostTrust, type SshHostTrustController } from "./sshHostTrust";
import "./connections.css";

/** A single queue covers connection tests and every workspace, including detached panels. */
export function SshHostTrustDialog({ controller = sshHostTrust }: { controller?: SshHostTrustController }) {
  useLocale();
  const request = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  useEffect(() => () => controller.cancel(), [controller]);
  if (!request) return null;
  const { id, details } = request;
  return <Modal key={id} title={t("Confirmar servidor SSH")} className="ssh-host-trust-dialog" onClose={() => controller.decline(id)}>
    <div className="ssh-host-trust-content">
      <p>{t("Primeiro acesso a este servidor. Confira a fingerprint com o administrador antes de confiar.")}</p>
      <dl>
        <dt>{t("Servidor SSH")}</dt><dd>{details.host}:{details.port}</dd>
        <dt>{t("Tipo da chave")}</dt><dd>{details.key_type}</dd>
        <dt>Fingerprint</dt><dd><code>{details.fingerprint}</code></dd>
      </dl>
    </div>
    <footer className="modal-footer"><button type="button" className="secondary-button" onClick={() => controller.decline(id)}>{t("Cancelar")}</button><button type="button" className="primary-button" onClick={() => controller.confirm(id)}>{t("Confiar e continuar")}</button></footer>
  </Modal>;
}
