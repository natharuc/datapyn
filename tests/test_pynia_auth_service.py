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


def test_copilot_returning_user_never_blocks_on_gh(auth_service, monkeypatch):
    """A returning Copilot user must NOT shell out to `gh auth status` on the UI
    thread — start_auth verifies the session on its own worker thread."""
    svc, client = auth_service
    client.provider_id = "copilot"
    monkeypatch.setattr(svc, "should_auto_auth", lambda _pid=None: True)

    gh_called = []
    monkeypatch.setattr(
        svc, "_run_gh_check", lambda _cb: gh_called.append(True)
    )
    scheduled = []
    monkeypatch.setattr(
        "src.services.pynia.auth_service.QTimer.singleShot",
        lambda _delay, fn: scheduled.append(fn),
    )

    assert svc.trigger_auto_auth_on_open(delay_ms=0) is True
    assert gh_called == []  # no blocking gh subprocess
    assert svc._auto_verify_copilot in scheduled


def test_copilot_first_run_uses_async_gh_check(auth_service, monkeypatch):
    """First-run Copilot (never authed) runs the gh check OFF the UI thread."""
    svc, client = auth_service
    client.provider_id = "copilot"
    monkeypatch.setattr(svc, "should_auto_auth", lambda _pid=None: False)

    started = []
    monkeypatch.setattr(svc, "_run_gh_check", lambda cb: started.append(cb))

    # Returns False (auth not definitely starting) but kicks off the async check.
    assert svc.trigger_auto_auth_on_open(delay_ms=0) is False
    assert len(started) == 1  # async gh check kicked off


def test_login_chat_copilot_runs_gh_check_async(auth_service, monkeypatch):
    """Clicking Sign In for Copilot must NOT block — the gh check is async, and
    the result dispatches to verify (start_auth) or device-login (do_login)."""
    svc, client = auth_service
    client.provider_id = "copilot"
    backend = MagicMock(spec=["do_login"])
    monkeypatch.setattr(svc, "_copilot_backend", lambda: backend)

    captured = {}
    monkeypatch.setattr(svc, "_run_gh_check", lambda cb: captured.setdefault("cb", cb))

    assert svc.login_chat() is True
    assert "cb" in captured  # gh check started off-thread, no blocking call
    client.start_auth.assert_not_called()  # nothing dispatched until the check returns

    # gh logged in → verify via start_auth
    captured["cb"](True)
    client.start_auth.assert_called_once()
    backend.do_login.assert_not_called()


def test_login_chat_copilot_device_flow_when_not_logged_in(auth_service, monkeypatch):
    svc, client = auth_service
    client.provider_id = "copilot"
    backend = MagicMock(spec=["do_login"])
    monkeypatch.setattr(svc, "_copilot_backend", lambda: backend)

    captured = {}
    monkeypatch.setattr(svc, "_run_gh_check", lambda cb: captured.setdefault("cb", cb))

    svc.login_chat()
    captured["cb"](False)  # no gh session → device login flow
    backend.do_login.assert_called_once()
    client.start_auth.assert_not_called()


def test_on_gh_login_check_schedules_verify_only_when_logged_in(auth_service, monkeypatch):
    svc, client = auth_service
    client.provider_id = "copilot"
    client.is_authenticated = False
    scheduled = []
    monkeypatch.setattr(
        "src.services.pynia.auth_service.QTimer.singleShot",
        lambda _delay, fn: scheduled.append(fn),
    )

    svc._on_gh_login_check(False, 0)
    assert scheduled == []  # gh not logged in → nothing

    svc._on_gh_login_check(True, 0)
    assert svc._auto_verify_copilot in scheduled
