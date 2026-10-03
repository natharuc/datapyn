"""Atomic JSON .dpw I/O, preserving legacy and unknown document fields."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

MAX_DOCUMENT_BYTES = 16 * 1024 * 1024


def validate_document(document: object) -> dict:
    if not isinstance(document, dict):
        raise ValueError("Workspace document must be a JSON object")
    tabs = document.get("tabs", document.get("sessions"))
    if tabs is not None and not isinstance(tabs, list):
        raise ValueError("Workspace tabs/sessions must be a list")
    return document


def read_document(path: str) -> dict:
    target = Path(path).expanduser().resolve()
    if target.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError("Workspace exceeds the 16 MiB document limit")
    # utf-8-sig also reads older Windows documents with a BOM.
    document = validate_document(json.loads(target.read_text(encoding="utf-8-sig")))
    return {"path": str(target), "document": document}


def write_document(path: str, document: dict) -> dict:
    document = validate_document(document)
    text = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise ValueError("Workspace exceeds the 16 MiB document limit")
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, prefix=f".{target.name}.", delete=False) as file:
            temporary = Path(file.name)
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
        return {"path": str(target), "bytes_written": len(encoded)}
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
