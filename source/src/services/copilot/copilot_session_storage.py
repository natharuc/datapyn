"""Persist Copilot chat sessions and image attachments on disk."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


def copilot_sessions_root() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "DataPyn" / "Copilot" / "sessions"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _attachments_root() -> Path:
    root = copilot_sessions_root() / "attachments"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_session_id(session_id: str) -> str:
    cleaned = re.sub(r"[^\w\-]", "", str(session_id or "default"))
    return cleaned or "default"


def _ext_from_mime(mime_type: str) -> str:
    return _MIME_EXT.get(str(mime_type or "").lower(), ".png")


def _decode_data(data: str) -> bytes:
    raw = str(data or "").strip()
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    return base64.b64decode(raw)


def _encode_data(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def persist_messages_for_storage(session_id: str, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return messages with attachment bytes stored on disk instead of inline base64."""
    sid = _safe_session_id(session_id)
    att_dir = _attachments_root() / sid
    att_dir.mkdir(parents=True, exist_ok=True)

    stored_messages: List[Dict[str, Any]] = []
    for msg_index, message in enumerate(messages or []):
        if not isinstance(message, dict):
            continue
        msg_copy = dict(message)
        attachments: List[Dict[str, Any]] = []
        for att_index, item in enumerate(message.get("attachments") or []):
            if not isinstance(item, dict):
                continue
            att_copy = {
                key: value
                for key, value in item.items()
                if key not in {"data", "blobUrl", "previewUrl"}
            }
            storage_key = item.get("storageKey")
            data = item.get("data") or ""
            if data:
                ext = _ext_from_mime(item.get("mimeType") or item.get("mime_type") or "image/png")
                storage_key = storage_key or f"{msg_index}_{att_index}{ext}"
                path = att_dir / storage_key
                try:
                    path.write_bytes(_decode_data(data))
                    att_copy["storageKey"] = storage_key
                except Exception as exc:
                    logger.warning("Failed to store attachment %s: %s", storage_key, exc)
                    att_copy["data"] = data
            elif storage_key:
                att_copy["storageKey"] = storage_key
            attachments.append(att_copy)
        if attachments:
            msg_copy["attachments"] = attachments
        stored_messages.append(msg_copy)
    return stored_messages


def hydrate_messages_from_storage(session_id: str, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Load attachment bytes from disk refs for UI/API use."""
    sid = _safe_session_id(session_id)
    att_dir = _attachments_root() / sid
    hydrated: List[Dict[str, Any]] = []

    for message in messages or []:
        if not isinstance(message, dict):
            continue
        msg_copy = dict(message)
        attachments: List[Dict[str, Any]] = []
        for item in message.get("attachments") or []:
            if not isinstance(item, dict):
                continue
            att_copy = dict(item)
            storage_key = att_copy.get("storageKey")
            if storage_key and not att_copy.get("data"):
                path = att_dir / storage_key
                if path.exists():
                    try:
                        att_copy["data"] = _encode_data(path.read_bytes())
                    except Exception as exc:
                        logger.warning("Failed to load attachment %s: %s", storage_key, exc)
            attachments.append(att_copy)
        if attachments:
            msg_copy["attachments"] = attachments
        hydrated.append(msg_copy)
    return hydrated


def save_session_messages(session_id: str, messages: List[Dict[str, Any]]) -> None:
    sid = _safe_session_id(session_id)
    persisted = persist_messages_for_storage(sid, messages)
    path = copilot_sessions_root() / f"{sid}.json"
    path.write_text(json.dumps(persisted, ensure_ascii=False), encoding="utf-8")


def load_session_messages(session_id: str) -> List[Dict[str, Any]]:
    sid = _safe_session_id(session_id)
    path = copilot_sessions_root() / f"{sid}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read session %s: %s", sid, exc)
        return []
    if not isinstance(payload, list):
        return []
    return hydrate_messages_from_storage(sid, payload)


def resolve_session_messages(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Load messages from disk, falling back to legacy inline session payloads."""
    session_id = str(session.get("id") or "")
    disk_messages = load_session_messages(session_id)
    if disk_messages:
        return disk_messages
    inline = session.get("messages")
    if isinstance(inline, list) and inline:
        return hydrate_messages_from_storage(session_id, inline)
    return []


def delete_session_storage(session_id: str) -> None:
    sid = _safe_session_id(session_id)
    session_file = copilot_sessions_root() / f"{sid}.json"
    if session_file.exists():
        try:
            session_file.unlink()
        except OSError as exc:
            logger.warning("Failed to delete session file %s: %s", session_file, exc)
    att_dir = _attachments_root() / sid
    if att_dir.exists():
        shutil.rmtree(att_dir, ignore_errors=True)
