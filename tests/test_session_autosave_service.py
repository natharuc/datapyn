"""Tests for debounced session autosave."""

import json
import time
from pathlib import Path

import pytest
from PyQt6.QtCore import QTimer

from src.services.session_autosave_service import SessionAutosavePayload, SessionAutosaveService


@pytest.fixture
def autosave_paths(tmp_path):
    sessions_path = tmp_path / "sessions.json"
    workspace_path = tmp_path / "workspace.json"
    return sessions_path, workspace_path


def test_debounced_save_writes_after_quiet_period(qapp, qtbot, autosave_paths):
    sessions_path, workspace_path = autosave_paths
    calls = []

    def collect():
        calls.append(time.monotonic())
        return SessionAutosavePayload(
            sessions_path=sessions_path,
            sessions_data={"version": 1, "sessions": {}, "session_order": []},
            workspace_path=workspace_path,
            workspace_data={"tabs": [], "dock_visible": True},
        )

    service = SessionAutosaveService()
    service.configure(collect)
    service.schedule()
    service.schedule()
    service.schedule()

    qtbot.waitUntil(lambda: sessions_path.exists(), timeout=3000)

    data = json.loads(sessions_path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(calls) == 1


def test_flush_now_writes_immediately(qapp, autosave_paths):
    sessions_path, workspace_path = autosave_paths
    service = SessionAutosaveService()
    service.configure(
        lambda: SessionAutosavePayload(
            sessions_path=sessions_path,
            sessions_data={"version": 1, "sessions": {"a": {"title": "Tab"}}, "session_order": ["a"]},
        )
    )
    service.flush_now()
    assert sessions_path.exists()
    assert json.loads(sessions_path.read_text(encoding="utf-8"))["sessions"]["a"]["title"] == "Tab"
