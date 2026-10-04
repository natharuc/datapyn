import { Bell, CheckCircle2, CircleSlash, Settings2, X, XCircle } from "lucide-react";
import { translate as t, useLocale } from "./i18n";
import { Modal } from "./PanelControls";
import type { NotificationCenter, NotificationEntry } from "./executionNotifications";
import "./notificationCenter.css";

function StatusIcon({ entry }: { entry: NotificationEntry }) {
  return entry.status === "cancelled" ? <CircleSlash size={18}/> : entry.success ? <CheckCircle2 size={18}/> : <XCircle size={18}/>;
}
function NotificationText({ entry }: { entry: NotificationEntry }) {
  return <><strong>{entry.title || t("DataPyn")}</strong><p>{entry.message}</p>{entry.target && <small>{t("Ir para o bloco")}</small>}</>;
}
export function NotificationToasts({ center, entries, onActivate }: { center: NotificationCenter; entries: readonly NotificationEntry[]; onActivate: (entry: NotificationEntry) => void }) {
  useLocale();
  return <div className="notification-toasts" aria-live="polite" aria-relevant="additions">
    {entries.map(entry => <article key={entry.id} className={`notification-toast notification-card ${entry.success ? "success" : "failure"} ${entry.status === "cancelled" ? "cancelled" : ""}`}
      style={{ borderLeftColor: entry.color }} onMouseEnter={() => center.pause(entry.id)} onMouseLeave={() => center.resume(entry.id)} onFocus={() => center.pause(entry.id)} onBlur={() => center.resume(entry.id)}>
      {entry.target ? <button className="notification-open" onClick={() => onActivate(entry)}><StatusIcon entry={entry}/><div><NotificationText entry={entry}/></div></button> : <div className="notification-open"><StatusIcon entry={entry}/><div><NotificationText entry={entry}/></div></div>}
      <button className="notification-close" aria-label={t("Fechar notificação")} onClick={() => center.dismiss(entry.id)}><X size={15}/></button>
    </article>)}
  </div>;
}
export function NotificationHistory({ center, entries, onActivate, onSettings, onClose }: { center: NotificationCenter; entries: readonly NotificationEntry[]; onActivate: (entry: NotificationEntry) => void; onSettings: () => void; onClose: () => void }) {
  useLocale();
  return <Modal title={t("Notificações")} className="notification-history" onClose={onClose}>
    <div className="notification-history-toolbar"><span>{t("Execuções recentes")}</span><button onClick={onSettings}><Settings2 size={14}/>{t("Configurar notificações")}</button></div>
    <div className="notification-history-list">
      {entries.length ? entries.map(entry => <article key={entry.id} className={`notification-history-entry ${entry.read ? "read" : "unread"}`} style={{ borderLeftColor: entry.color || (entry.status === "cancelled" ? "var(--muted)" : entry.success ? "#4ba979" : "#df646b") }}>
        <button className="notification-history-open" disabled={!entry.target} onClick={() => onActivate(entry)}><StatusIcon entry={entry}/><div><NotificationText entry={entry}/><time>{new Date(entry.createdAt).toLocaleTimeString()}</time>{entry.deliveryError && <span className="notification-delivery-error">{entry.deliveryError}</span>}</div></button>
      </article>) : <div className="notification-history-empty"><Bell size={26}/><strong>{t("Nenhuma execução recente")}</strong></div>}
    </div>
    {entries.length > 0 && <div className="notification-history-footer"><button onClick={() => center.markRead()}>{t("Marcar todas como lidas")}</button><button onClick={() => center.clear()}>{t("Limpar histórico")}</button></div>}
  </Modal>;
}
