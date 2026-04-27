"""Tests for Telegram and email notification delivery."""

import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import QSettings


@pytest.fixture(autouse=True)
def _clean_notification_transport_settings():
    settings = QSettings("DataPyn", "DataPyn")
    keys = [
        "notifications/enabled",
        "notifications/telegram/enabled",
        "notifications/telegram/chat_id",
        "notifications/email/enabled",
        "notifications/email/host",
        "notifications/email/port",
        "notifications/email/use_tls",
        "notifications/email/use_ssl",
        "notifications/email/username",
        "notifications/email/from",
        "notifications/email/to",
    ]
    originals = {key: settings.value(key) for key in keys}
    for key in keys:
        settings.remove(key)
    yield
    for key in keys:
        settings.remove(key)
        if originals[key] is not None:
            settings.setValue(key, originals[key])


class TestNotificationTransportSettings:
    def test_load_transport_settings_reads_qsettings_and_keyring(self):
        from src.services.notification_delivery_service import load_notification_transport_settings

        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue("notifications/enabled", True)
        settings.setValue("notifications/telegram/enabled", True)
        settings.setValue("notifications/telegram/chat_id", "12345")
        settings.setValue("notifications/email/enabled", True)
        settings.setValue("notifications/email/host", "smtp.example.com")
        settings.setValue("notifications/email/port", 587)
        settings.setValue("notifications/email/use_tls", True)
        settings.setValue("notifications/email/use_ssl", False)
        settings.setValue("notifications/email/username", "mailer")
        settings.setValue("notifications/email/from", "from@example.com")
        settings.setValue("notifications/email/to", "a@example.com; b@example.com")

        def _get_password(_service_name, secret_name):
            if secret_name == "telegram_bot_token":
                return "telegram-secret"
            if secret_name == "email_password":
                return "smtp-secret"
            return ""

        with patch("src.services.notification_delivery_service.keyring.get_password", side_effect=_get_password):
            transport = load_notification_transport_settings()

        assert transport["notifications_enabled"] is True
        assert transport["telegram"]["configured"] is True
        assert transport["telegram"]["bot_token"] == "telegram-secret"
        assert transport["email"]["configured"] is True
        assert transport["email"]["password"] == "smtp-secret"
        assert transport["email"]["recipients"] == ["a@example.com", "b@example.com"]


class TestNotificationWorkers:
    def test_telegram_worker_posts_message(self):
        from src.services.notification_delivery_service import TelegramNotificationWorker

        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": True}
        events = []

        with patch("src.services.notification_delivery_service.requests.post", return_value=response) as post:
            worker = TelegramNotificationWorker("token", "123", "Title", "Message")
            worker.delivery_succeeded.connect(lambda channel, detail: events.append((channel, detail)))
            worker.run()

        post.assert_called_once()
        assert events == [("telegram", "ok")]

    def test_email_worker_sends_message(self):
        from src.services.notification_delivery_service import EmailNotificationWorker

        smtp_context = MagicMock()
        smtp_context.__enter__.return_value = smtp_context
        smtp_context.__exit__.return_value = False
        events = []

        config = {
            "host": "smtp.example.com",
            "port": 587,
            "use_tls": True,
            "use_ssl": False,
            "username": "mailer",
            "password": "secret",
            "from_address": "from@example.com",
            "recipients": ["to@example.com"],
        }

        with patch("src.services.notification_delivery_service.smtplib.SMTP", return_value=smtp_context) as smtp_cls:
            worker = EmailNotificationWorker(config, "Title", "Message", True)
            worker.delivery_succeeded.connect(lambda channel, detail: events.append((channel, detail)))
            worker.run()

        smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=15)
        smtp_context.starttls.assert_called_once()
        smtp_context.login.assert_called_once_with("mailer", "secret")
        smtp_context.send_message.assert_called_once()
        assert events == [("email", "ok")]


class TestNotificationDeliveryService:
    def test_service_starts_workers_for_enabled_channels(self):
        from src.services.notification_delivery_service import (
            EmailNotificationWorker,
            NotificationDeliveryService,
            TelegramNotificationWorker,
        )

        service = NotificationDeliveryService()
        transport = {
            "notifications_enabled": True,
            "telegram": {
                "enabled": True,
                "configured": True,
                "bot_token": "token",
                "chat_id": "123",
            },
            "email": {
                "enabled": True,
                "configured": True,
                "host": "smtp.example.com",
                "port": 587,
                "use_tls": True,
                "use_ssl": False,
                "username": "mailer",
                "password": "secret",
                "from_address": "from@example.com",
                "to": "to@example.com",
                "recipients": ["to@example.com"],
            },
        }

        with patch("src.services.notification_delivery_service.load_notification_transport_settings", return_value=transport), \
                patch.object(service, "_start_worker") as start_worker:
            service.deliver("Title", "Message", True, channels={"telegram": True, "email": True})

        assert start_worker.call_count == 2
        assert isinstance(start_worker.call_args_list[0].args[0], TelegramNotificationWorker)
        assert isinstance(start_worker.call_args_list[1].args[0], EmailNotificationWorker)

    def test_service_emits_failure_for_unconfigured_channel(self):
        from src.services.notification_delivery_service import NotificationDeliveryService

        service = NotificationDeliveryService()
        failures = []
        service.delivery_failed.connect(lambda channel, error: failures.append((channel, error)))

        transport = {
            "notifications_enabled": True,
            "telegram": {
                "enabled": False,
                "configured": False,
                "bot_token": "",
                "chat_id": "",
            },
            "email": {
                "enabled": False,
                "configured": False,
                "host": "",
                "port": 587,
                "use_tls": True,
                "use_ssl": False,
                "username": "",
                "password": "",
                "from_address": "",
                "to": "",
                "recipients": [],
            },
        }

        with patch("src.services.notification_delivery_service.load_notification_transport_settings", return_value=transport), \
                patch.object(service, "_start_worker") as start_worker:
            service.deliver("Title", "Message", True, channels={"telegram": True})

        start_worker.assert_not_called()
        assert failures == [("telegram", "not_configured")]