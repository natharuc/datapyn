"""Notification delivery helpers and background workers."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, Optional

import keyring
import requests
from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from src.workers import BaseWorker, execute_worker

logger = logging.getLogger(__name__)

NOTIFICATION_KEYRING_SERVICE = "DataPyn.notifications"
TELEGRAM_TOKEN_KEY = "telegram_bot_token"
EMAIL_PASSWORD_KEY = "email_password"


def get_notification_secret(secret_name: str) -> str:
    try:
        return keyring.get_password(NOTIFICATION_KEYRING_SERVICE, secret_name) or ""
    except Exception as exc:
        logger.warning("Failed to load notification secret '%s': %s", secret_name, exc)
        return ""


def set_notification_secret(secret_name: str, value: str):
    try:
        if value:
            keyring.set_password(NOTIFICATION_KEYRING_SERVICE, secret_name, value)
            return

        try:
            keyring.delete_password(NOTIFICATION_KEYRING_SERVICE, secret_name)
        except keyring.errors.PasswordDeleteError:
            return
    except Exception as exc:
        logger.warning("Failed to persist notification secret '%s': %s", secret_name, exc)


def _split_recipients(raw_value: str) -> list[str]:
    return [item.strip() for item in raw_value.replace(";", ",").split(",") if item.strip()]


def load_notification_transport_settings() -> Dict[str, Any]:
    settings = QSettings("DataPyn", "DataPyn")

    telegram_chat_id = str(settings.value("notifications/telegram/chat_id", "") or "").strip()
    telegram_bot_token = get_notification_secret(TELEGRAM_TOKEN_KEY).strip()

    email_host = str(settings.value("notifications/email/host", "") or "").strip()
    email_username = str(settings.value("notifications/email/username", "") or "").strip()
    email_password = get_notification_secret(EMAIL_PASSWORD_KEY)
    email_from = str(settings.value("notifications/email/from", "") or "").strip()
    email_to = str(settings.value("notifications/email/to", "") or "").strip()
    email_recipients = _split_recipients(email_to)

    telegram = {
        "enabled": settings.value("notifications/telegram/enabled", False, type=bool),
        "chat_id": telegram_chat_id,
        "bot_token": telegram_bot_token,
    }
    telegram["configured"] = bool(telegram_chat_id and telegram_bot_token)

    email = {
        "enabled": settings.value("notifications/email/enabled", False, type=bool),
        "host": email_host,
        "port": settings.value("notifications/email/port", 587, type=int),
        "use_tls": settings.value("notifications/email/use_tls", True, type=bool),
        "use_ssl": settings.value("notifications/email/use_ssl", False, type=bool),
        "username": email_username,
        "password": email_password,
        "from_address": email_from,
        "to": email_to,
        "recipients": email_recipients,
    }
    email["configured"] = bool(
        email_host
        and email["port"]
        and email_from
        and email_recipients
        and (not email_username or email_password)
    )

    return {
        "notifications_enabled": settings.value("notifications/enabled", True, type=bool),
        "telegram": telegram,
        "email": email,
    }


def get_notification_channel_availability() -> Dict[str, bool]:
    transport = load_notification_transport_settings()
    return {
        "telegram": bool(transport["telegram"]["configured"]),
        "email": bool(transport["email"]["configured"]),
    }


class TelegramNotificationWorker(BaseWorker):
    delivery_succeeded = pyqtSignal(str, str)
    delivery_failed = pyqtSignal(str, str)

    def __init__(self, bot_token: str, chat_id: str, title: str, message: str):
        super().__init__()
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.title = title
        self.message = message

    def run(self):
        self.started.emit()

        try:
            text_parts = [part for part in [self.title.strip(), self.message.strip()] if part]
            response = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": "\n".join(text_parts) or "DataPyn notification",
                },
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok", False):
                raise RuntimeError(payload.get("description") or "Telegram delivery failed")
            self.delivery_succeeded.emit("telegram", "ok")
        except Exception as exc:
            error_text = str(exc)
            self.error.emit(error_text)
            self.delivery_failed.emit("telegram", error_text)
        finally:
            self.finished.emit()


class EmailNotificationWorker(BaseWorker):
    delivery_succeeded = pyqtSignal(str, str)
    delivery_failed = pyqtSignal(str, str)

    def __init__(self, config: Dict[str, Any], title: str, message: str, success: bool):
        super().__init__()
        self.config = config
        self.title = title
        self.message = message
        self.success = success

    def run(self):
        self.started.emit()

        try:
            msg = EmailMessage()
            msg["Subject"] = self.title.strip() or "DataPyn notification"
            msg["From"] = self.config["from_address"]
            msg["To"] = ", ".join(self.config["recipients"])

            status_label = "Success" if self.success else "Error"
            body_parts = [status_label]
            if self.title.strip():
                body_parts.append(self.title.strip())
            if self.message.strip():
                body_parts.append("")
                body_parts.append(self.message.strip())
            msg.set_content("\n".join(body_parts))

            if self.config.get("use_ssl"):
                server = smtplib.SMTP_SSL(self.config["host"], self.config["port"], timeout=15)
            else:
                server = smtplib.SMTP(self.config["host"], self.config["port"], timeout=15)

            with server:
                if self.config.get("use_tls") and not self.config.get("use_ssl"):
                    server.starttls()
                if self.config.get("username"):
                    server.login(self.config["username"], self.config.get("password", ""))
                server.send_message(msg)

            self.delivery_succeeded.emit("email", "ok")
        except Exception as exc:
            error_text = str(exc)
            self.error.emit(error_text)
            self.delivery_failed.emit("email", error_text)
        finally:
            self.finished.emit()


class NotificationDeliveryService(QObject):
    delivery_succeeded = pyqtSignal(str, str)
    delivery_failed = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._active_threads = []

    def deliver(self, title: str, message: str, success: bool, channels: Optional[Dict[str, bool]] = None):
        transport = load_notification_transport_settings()
        if not transport["notifications_enabled"]:
            return

        active_channels = channels or {}
        if active_channels.get("telegram"):
            telegram = transport["telegram"]
            if telegram["enabled"] and telegram["configured"]:
                worker = TelegramNotificationWorker(
                    bot_token=telegram["bot_token"],
                    chat_id=telegram["chat_id"],
                    title=title,
                    message=message,
                )
                self._start_worker(worker)
            else:
                self.delivery_failed.emit("telegram", "not_configured")

        if active_channels.get("email"):
            email = transport["email"]
            if email["enabled"] and email["configured"]:
                worker = EmailNotificationWorker(email, title=title, message=message, success=success)
                self._start_worker(worker)
            else:
                self.delivery_failed.emit("email", "not_configured")

    def send_test_telegram(self, title: str, message: str):
        self.deliver(title=title, message=message, success=True, channels={"telegram": True})

    def send_test_email(self, title: str, message: str):
        self.deliver(title=title, message=message, success=True, channels={"email": True})

    def _start_worker(self, worker: BaseWorker):
        worker.delivery_succeeded.connect(self._on_delivery_succeeded)
        worker.delivery_failed.connect(self._on_delivery_failed)
        thread = execute_worker(worker)
        self._active_threads.append(thread)
        thread.finished.connect(self._on_thread_finished)

    def _on_delivery_succeeded(self, channel: str, detail: str):
        self.delivery_succeeded.emit(channel, detail)

    def _on_delivery_failed(self, channel: str, error_text: str):
        logger.warning("Notification delivery failed for %s: %s", channel, error_text)
        self.delivery_failed.emit(channel, error_text)

    def _on_thread_finished(self):
        thread = self.sender()
        if thread in self._active_threads:
            self._active_threads.remove(thread)


_notification_delivery_service: Optional[NotificationDeliveryService] = None


def get_notification_delivery_service(parent: Optional[QObject] = None) -> NotificationDeliveryService:
    global _notification_delivery_service

    if _notification_delivery_service is None:
        _notification_delivery_service = NotificationDeliveryService()

    return _notification_delivery_service