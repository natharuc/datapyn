"""Clipboard / file attachments for Pynia ACP prompts."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Iterable, Optional

MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024
MAX_ATTACHMENTS = 4
MAX_TEXT_CHARS = 24_000

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_TEXT_EXTS = {
    ".txt",
    ".sql",
    ".py",
    ".csv",
    ".json",
    ".md",
    ".log",
    ".xml",
    ".html",
    ".tsv",
    ".yaml",
    ".yml",
}


def _trim(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return items[:MAX_ATTACHMENTS]


def normalize_attachments(raw: Any) -> list[dict[str, Any]]:
    """Accept JS/JSON payloads and drop empty or oversized items."""
    if not raw:
        return []
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").lower()
        mime = str(item.get("mime") or item.get("mimeType") or "").lower()
        name = str(item.get("name") or "attachment")
        data = str(item.get("data") or "")
        text = str(item.get("text") or "")
        if kind not in {"image", "file"}:
            if mime.startswith("image/") or name.lower().endswith(tuple(_IMAGE_EXTS)):
                kind = "image"
            elif text:
                kind = "file"
            else:
                continue
        if kind == "image":
            if not data:
                continue
            try:
                raw_bytes = base64.b64decode(data, validate=False)
            except Exception:
                continue
            if len(raw_bytes) > MAX_ATTACHMENT_BYTES:
                continue
            out.append(
                {
                    "kind": "image",
                    "name": name or "screenshot.png",
                    "mime": mime or "image/png",
                    "data": data,
                }
            )
        else:
            if not text.strip() and not data:
                continue
            if len(text) > MAX_TEXT_CHARS:
                text = text[:MAX_TEXT_CHARS] + "\n... (truncated)"
            out.append(
                {
                    "kind": "file",
                    "name": name,
                    "mime": mime or "text/plain",
                    "text": text,
                }
            )
        if len(out) >= MAX_ATTACHMENTS:
            break
    return out


def display_attachments(attachments: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact payload stored on the user chat bubble."""
    out: list[dict[str, Any]] = []
    for item in attachments or []:
        kind = item.get("kind")
        name = item.get("name") or "attachment"
        mime = item.get("mime") or ""
        if kind == "image" and item.get("data"):
            out.append(
                {
                    "kind": "image",
                    "name": name,
                    "mime": mime,
                    "src": f"data:{mime or 'image/png'};base64,{item['data']}",
                }
            )
        else:
            out.append({"kind": "file", "name": name, "mime": mime})
    return out


def prompt_blocks_for_attachments(attachments: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for item in attachments or []:
        if item.get("kind") == "image" and item.get("data"):
            blocks.append(
                {
                    "type": "image",
                    "mimeType": item.get("mime") or "image/png",
                    "data": item["data"],
                    "name": item.get("name") or "screenshot.png",
                }
            )
        elif item.get("kind") == "file":
            name = item.get("name") or "file"
            text = item.get("text") or ""
            blocks.append(
                {
                    "type": "text",
                    "text": f"Attached file `{name}`:\n```\n{text}\n```",
                }
            )
    return blocks


def attachments_from_image_bytes(
    data: bytes,
    *,
    mime: str = "image/png",
    name: str = "screenshot.png",
) -> Optional[dict[str, Any]]:
    if not data or len(data) > MAX_ATTACHMENT_BYTES:
        return None
    return {
        "kind": "image",
        "name": name,
        "mime": mime or "image/png",
        "data": base64.b64encode(data).decode("ascii"),
    }


def attachments_from_paths(paths: Iterable[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in paths:
        path = Path(str(raw))
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        mime = mimetypes.guess_type(str(path))[0] or ""
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_ATTACHMENT_BYTES:
            continue
        if suffix in _IMAGE_EXTS or (mime or "").startswith("image/"):
            try:
                data = path.read_bytes()
            except OSError:
                continue
            item = attachments_from_image_bytes(
                data, mime=mime or "image/png", name=path.name
            )
            if item:
                out.append(item)
        elif suffix in _TEXT_EXTS or (mime or "").startswith("text/"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(text) > MAX_TEXT_CHARS:
                text = text[:MAX_TEXT_CHARS] + "\n... (truncated)"
            out.append(
                {
                    "kind": "file",
                    "name": path.name,
                    "mime": mime or "text/plain",
                    "text": text,
                }
            )
        if len(out) >= MAX_ATTACHMENTS:
            break
    return _trim(out)


def attachments_from_qt_mime(mime) -> list[dict[str, Any]]:
    """Read a QMimeData clipboard/drop payload."""
    out: list[dict[str, Any]] = []
    if mime is None:
        return out
    try:
        if mime.hasUrls():
            paths = []
            for url in mime.urls():
                local = url.toLocalFile() if hasattr(url, "toLocalFile") else ""
                if local:
                    paths.append(local)
            out.extend(attachments_from_paths(paths))
        if mime.hasImage() and len(out) < MAX_ATTACHMENTS:
            image = mime.imageData()
            png = _qimage_png_bytes(image)
            if png:
                item = attachments_from_image_bytes(png)
                if item:
                    out.append(item)
    except Exception:
        return _trim(out)
    return _trim(out)


def _qimage_png_bytes(image) -> bytes:
    if image is None:
        return b""
    try:
        from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
        from PyQt6.QtGui import QImage, QPixmap
    except Exception:
        return b""

    qimage = image
    if isinstance(image, QPixmap):
        qimage = image.toImage()
    if not isinstance(qimage, QImage) or qimage.isNull():
        return b""
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not qimage.save(buf, "PNG"):
        return b""
    return bytes(QByteArray(buf.data()))
