import { useEffect, useSyncExternalStore } from "react";
import { ArrowDownToLine, CircleCheck, LoaderCircle, RefreshCw, RotateCw } from "lucide-react";
import { Modal } from "./PanelControls";
import { useTranslation } from "./i18n";
import { type UpdateController } from "./updater";
import "./updater.css";

export function UpdateDialog({ controller, onClose, beforeInstall }: { controller: UpdateController; onClose: () => void; beforeInstall: () => Promise<void> }) {
  const { t } = useTranslation();
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  useEffect(() => { void controller.initialize(); }, [controller]);
  const busy = ["loading", "checking", "downloading", "installing"].includes(state.phase);
  const locked = state.phase === "installing";
  const ratio = state.total ? Math.min(1, state.downloaded / state.total) : undefined;
  const size = (bytes: number) => `${(bytes / 1048576).toLocaleString(undefined, { maximumFractionDigits: 1 })} MB`;
  return <Modal title={t("Atualizações do DataPyn")} onClose={() => { if (!locked) onClose(); }} className="update-dialog">
    <div className="update-identity"><div><strong>DataPyn Tauri</strong><p>{t("Canal estável")}</p></div><span className="update-version">{state.configuration?.current_version || "—"}</span></div>
    <div className="update-content" aria-live="polite">
      {state.phase === "loading" && <p className="update-status"><LoaderCircle className="spin" size={17} />{t("Carregando configuração…")}</p>}
      {state.phase === "unavailable" && <><h3>{t("Atualizador indisponível neste build")}</h3><p>{t(state.configuration?.reason || "Não foi possível consultar a configuração de atualização.")}</p></>}
      {state.phase === "idle" && <p>{t("Novas versões são verificadas e baixadas automaticamente.")}</p>}
      {state.phase === "checking" && <p className="update-status"><LoaderCircle className="spin" size={17} />{t("Verificando atualizações…")}</p>}
      {state.phase === "current" && <p className="update-status"><CircleCheck size={20} />{t("Você está usando a versão mais recente deste canal.")}</p>}
      {state.version && ["available", "downloading", "downloaded", "installing"].includes(state.phase) && <><h3>{t("Nova versão disponível")}: {state.version}</h3>{state.date && <p className="update-date">{new Date(state.date).toLocaleDateString()}</p>}</>}
      {state.notes && <pre className="update-notes">{state.notes}</pre>}
      {state.phase === "downloading" && <div className="update-download"><progress max={1} value={ratio} aria-label={t("Download da atualização")} /><p>{size(state.downloaded)}{state.total ? ` / ${size(state.total)} · ${Math.round((ratio ?? 0) * 100)}%` : ""}</p><p>{t("O download continua em segundo plano ao fechar esta janela.")}</p></div>}
      {state.phase === "downloaded" && <p>{t("Download concluído e assinatura verificada. Seus documentos serão salvos antes da instalação.")}</p>}
      {state.phase === "installing" && <p className="update-status"><LoaderCircle className="spin" size={17} />{t("Salvando documentos e instalando…")}</p>}
      {state.phase === "installed" && <p className="update-status"><CircleCheck size={20} />{t("Atualização instalada. Reinicie para abrir a nova versão.")}</p>}
      {state.error && <p className="form-error" role="alert">{state.error}</p>}
    </div>
    <footer className="modal-footer"><button className="secondary-button" disabled={locked} onClick={onClose}>{t("Fechar")}</button><span className="toolbar-spacer" />
      {state.phase === "available" ? <button className="primary-button" onClick={() => void controller.download()}><ArrowDownToLine size={15} />{t("Baixar atualização")}</button>
        : state.phase === "downloaded" ? <button className="primary-button" onClick={() => void controller.install(beforeInstall)}><RotateCw size={15} />{t("Salvar e instalar")}</button>
        : state.phase === "installed" ? <button className="primary-button" onClick={() => void controller.relaunch(beforeInstall)}><RotateCw size={15} />{t("Reiniciar agora")}</button>
        : <button className="primary-button" disabled={busy || !state.configuration?.available} onClick={() => void controller.check()}>{busy ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}{t("Verificar atualizações")}</button>}
    </footer>
  </Modal>;
}
