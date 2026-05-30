"""Image attachment helpers for Copilot chat (SDK 0.3+)."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .copilot_models import find_model, model_supports_vision

SUPPORTED_IMAGE_MIME_TYPES = frozenset({
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
    "image/bmp",
})

DEFAULT_MAX_ATTACHMENTS = 4
DEFAULT_MAX_IMAGE_BYTES = 4 * 1024 * 1024


class AttachmentValidationError(ValueError):
    """Raised when chat image attachments fail validation."""


def _normalize_mime_type(value: Any) -> str:
    mime = str(value or "").strip().lower()
    if mime == "image/jpg":
        return "image/jpeg"
    return mime


def _decode_base64(data: str) -> bytes:
    raw = str(data or "").strip()
    if raw.startswith("data:"):
        _, _, raw = raw.partition(",")
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttachmentValidationError("Invalid image data encoding.") from exc


def _vision_limits(raw_model: Any) -> Tuple[Optional[int], Optional[int]]:
    if raw_model is None:
        return None, None
    if isinstance(raw_model, dict):
        caps = raw_model.get("capabilities") or {}
        limits = caps.get("limits") or {}
        vision = limits.get("vision") or {}
        return vision.get("max_prompt_images"), vision.get("max_prompt_image_size")

    caps = getattr(raw_model, "capabilities", None)
    limits = getattr(caps, "limits", None) if caps is not None else None
    vision = getattr(limits, "vision", None) if limits is not None else None
    if vision is None:
        return None, None
    return (
        getattr(vision, "max_prompt_images", None),
        getattr(vision, "max_prompt_image_size", None),
    )


def attachment_limits_for_model(
    models: Iterable[Dict[str, Any]],
    model_id: str,
    *,
    raw_model: Any = None,
) -> Dict[str, int]:
    """Return max attachment count and per-image byte size for a model."""
    model = find_model(models, model_id)
    max_images = DEFAULT_MAX_ATTACHMENTS
    max_bytes = DEFAULT_MAX_IMAGE_BYTES

    if model is not None:
        if model.get("max_prompt_images") is not None:
            max_images = int(model["max_prompt_images"])
        if model.get("max_prompt_image_size") is not None:
            max_bytes = int(model["max_prompt_image_size"])

    if raw_model is not None:
        raw_max_images, raw_max_bytes = _vision_limits(raw_model)
        if raw_max_images is not None:
            max_images = int(raw_max_images)
        if raw_max_bytes is not None:
            max_bytes = int(raw_max_bytes)

    return {
        "max_attachments": max(DEFAULT_MAX_ATTACHMENTS, max_images),
        "max_image_bytes": max(256 * 1024, max_bytes),
    }


def normalize_attachment(raw: Any) -> Dict[str, Any]:
    """Normalize a UI attachment payload into a serializable dict."""
    if not isinstance(raw, dict):
        raise AttachmentValidationError("Attachment must be an object.")

    mime_type = _normalize_mime_type(raw.get("mimeType") or raw.get("mime_type"))
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise AttachmentValidationError(f"Unsupported image type: {mime_type or 'unknown'}")

    data = raw.get("data") or raw.get("base64") or ""
    if not data:
        raise AttachmentValidationError("Image attachment is missing data.")

    image_bytes = _decode_base64(data)
    if not image_bytes:
        raise AttachmentValidationError("Image attachment is empty.")

    name = str(raw.get("name") or raw.get("displayName") or "image.png").strip() or "image.png"
    if not re.search(r"\.(png|jpe?g|gif|webp|bmp)$", name, re.IGNORECASE):
        ext = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
        }.get(mime_type, ".png")
        name = f"{name}{ext}"

    return {
        "name": name,
        "mimeType": mime_type,
        "data": base64.b64encode(image_bytes).decode("ascii"),
        "size": len(image_bytes),
        "source": str(raw.get("source") or "user"),
    }


def parse_attachments_payload(payload: Iterable[Any]) -> List[Dict[str, Any]]:
    """Parse attachment objects from the WebView send payload."""
    normalized: List[Dict[str, Any]] = []
    for item in payload or []:
        normalized.append(normalize_attachment(item))
    return normalized


def validate_attachments_for_model(
    attachments: Iterable[Dict[str, Any]],
    models: Iterable[Dict[str, Any]],
    model_id: str,
    *,
    raw_model: Any = None,
) -> List[Dict[str, Any]]:
    """Validate attachments against model vision support and size limits."""
    items = [normalize_attachment(item) for item in attachments or []]
    if not items:
        return []

    if not model_supports_vision(models, model_id):
        raise AttachmentValidationError("The selected model does not support image input.")

    limits = attachment_limits_for_model(models, model_id, raw_model=raw_model)
    max_count = limits["max_attachments"]
    max_bytes = limits["max_image_bytes"]

    if len(items) > max_count:
        raise AttachmentValidationError(
            f"Too many images attached ({len(items)}). Maximum for this model is {max_count}."
        )

    for item in items:
        size = int(item.get("size") or 0)
        if size > max_bytes:
            limit_mb = max(1, max_bytes // (1024 * 1024))
            raise AttachmentValidationError(
                f"Image '{item.get('name', 'image')}' is too large. Maximum size is about {limit_mb} MB."
            )

    return items


def build_sdk_attachments(attachments: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert normalized attachments into Copilot SDK blob attachments."""
    sdk_items: List[Dict[str, Any]] = []
    for item in attachments or []:
        normalized = normalize_attachment(item)
        sdk_items.append({
            "type": "blob",
            "data": normalized["data"],
            "mimeType": normalized["mimeType"],
            "displayName": normalized["name"],
        })
    return sdk_items


def attachments_for_message_storage(attachments: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a compact attachment shape suitable for chat session persistence."""
    stored: List[Dict[str, Any]] = []
    for item in attachments or []:
        normalized = normalize_attachment(item)
        stored.append({
            "name": normalized["name"],
            "mimeType": normalized["mimeType"],
            "data": normalized["data"],
            "size": normalized["size"],
            "source": normalized.get("source", "user"),
        })
    return stored
