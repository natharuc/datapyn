import base64
import json
from pathlib import Path

import pytest

from src.services.copilot.copilot_session_storage import (
    delete_session_storage,
    hydrate_messages_from_storage,
    load_session_messages,
    persist_messages_for_storage,
    save_session_messages,
)


PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def session_root(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    monkeypatch.setattr(
        "src.services.copilot.copilot_session_storage.copilot_sessions_root",
        lambda: root,
    )
    return root


def test_persist_and_hydrate_attachment_roundtrip(session_root):
    session_id = "abc123"
    messages = [{
        "role": "user",
        "content": "look at this",
        "attachments": [{
            "name": "shot.png",
            "mimeType": "image/png",
            "data": PNG_1X1,
            "size": 68,
            "source": "clipboard",
        }],
    }]

    persisted = persist_messages_for_storage(session_id, messages)
    assert persisted[0]["attachments"][0]["storageKey"]
    assert "data" not in persisted[0]["attachments"][0]

    hydrated = hydrate_messages_from_storage(session_id, persisted)
    assert hydrated[0]["attachments"][0]["data"] == PNG_1X1


def test_save_and_load_session_messages(session_root):
    session_id = "sess42"
    messages = [{
        "role": "user",
        "content": "",
        "attachments": [{
            "name": "pasted.png",
            "mimeType": "image/png",
            "data": PNG_1X1,
            "size": 68,
        }],
    }]

    save_session_messages(session_id, messages)
    loaded = load_session_messages(session_id)
    assert loaded[0]["attachments"][0]["data"] == PNG_1X1


def test_delete_session_storage_removes_files(session_root):
    session_id = "gone"
    save_session_messages(session_id, [{
        "role": "user",
        "content": "x",
        "attachments": [{
            "name": "a.png",
            "mimeType": "image/png",
            "data": PNG_1X1,
            "size": 68,
        }],
    }])

    delete_session_storage(session_id)
    assert load_session_messages(session_id) == []
    assert not (session_root / "attachments" / session_id).exists()
