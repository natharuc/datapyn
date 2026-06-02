"""Tests for PyniaAuthService auto-login coordination."""

from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QApplication

from src.services.pynia.auth_service import PyniaAuthService, reset_pynia_auth_service


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def auth_service(qapp):
    reset_pynia_auth_service()
    svc = PyniaAuthService()
    client = MagicMock()
    client.provider_id = "openai"
    client.is_authenticated = False
    svc.set_agent_client(client)
    svc._settings = MagicMock(should_auto_auth=lambda _pid: True)
    return svc, client


def test_trigger_auto_auth_on_open_returns_false_when_already_authenticated(auth_service):
    svc, client = auth_service
    client.is_authenticated = True
    assert svc.trigger_auto_auth_on_open() is False


def test_trigger_auto_auth_on_open_returns_false_when_auth_in_progress(auth_service):
    svc, _client = auth_service
    svc._auth_in_progress = True
    assert svc.trigger_auto_auth_on_open() is False


def test_trigger_auto_auth_on_open_schedules_for_api_provider(auth_service, monkeypatch):
    svc, _client = auth_service
    scheduled = []

    def fake_shot(_delay, fn):
        scheduled.append(fn)

    monkeypatch.setattr("src.services.pynia.auth_service.QTimer.singleShot", fake_shot)
    assert svc.trigger_auto_auth_on_open(delay_ms=0) is True
    assert scheduled
