"""Model metadata helpers for the Copilot chat integration."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple


REASONING_EFFORTS = ("auto", "low", "medium", "high", "xhigh")


FALLBACK_MODELS: List[Dict[str, Any]] = [
    {"id": "gpt-4.1", "name": "GPT-4.1", "multiplier": 1.0},
    {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini", "multiplier": 0.33},
    {"id": "gpt-4o", "name": "GPT-4o", "multiplier": 1.0},
    {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "multiplier": 0.33},
    {"id": "o3", "name": "o3", "multiplier": 10.0},
    {"id": "o3-mini", "name": "o3-mini", "multiplier": 1.0},
    {"id": "o4-mini", "name": "o4-mini", "multiplier": 1.0},
    {"id": "claude-3.5-sonnet", "name": "Claude 3.5 Sonnet", "multiplier": 1.0},
    {"id": "claude-3.7-sonnet", "name": "Claude 3.7 Sonnet", "multiplier": 1.0},
    {"id": "claude-sonnet-4", "name": "Claude Sonnet 4", "multiplier": 1.0},
]


def normalize_reasoning_effort(value: Any) -> str:
    """Return a supported reasoning effort value."""
    effort = str(value or "auto").strip().lower().replace("-", "")
    aliases = {
        "mediumhigh": "high",
        "medhigh": "high",
        "xhight": "xhigh",
        "x_height": "xhigh",
        "xheight": "xhigh",
        "x_high": "xhigh",
        "extra_high": "xhigh",
        "extrahigh": "xhigh",
    }
    effort = aliases.get(effort, effort)
    return effort if effort in REASONING_EFFORTS else "auto"


def _camel_key(key: str) -> str:
    parts = key.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _get_attr_or_key(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value.get(key, default)
        return value.get(_camel_key(key), default)
    if hasattr(value, key):
        return getattr(value, key)
    camel = _camel_key(key)
    return getattr(value, camel, default)


def _billing_multiplier(model: Any) -> Optional[float]:
    multiplier = _get_attr_or_key(model, "multiplier")
    if multiplier is None:
        billing = _get_attr_or_key(model, "billing")
        multiplier = _get_attr_or_key(billing, "multiplier") if billing is not None else None
    try:
        return float(multiplier) if multiplier is not None else None
    except (TypeError, ValueError):
        return None


def _capability_value(raw_model: Any, key: str) -> Optional[bool]:
    capabilities = _get_attr_or_key(raw_model, "capabilities")
    if isinstance(capabilities, dict) and key in capabilities:
        return bool(capabilities[key])
    supports = _get_attr_or_key(capabilities, "supports") if capabilities is not None else None
    if supports is not None:
        supports_key = key[len("supports_"):] if key.startswith("supports_") else key
        value = _get_attr_or_key(supports, supports_key)
        if value is not None:
            return bool(value)
    value = _get_attr_or_key(raw_model, key)
    if value is not None:
        return bool(value)
    return None


def _model_supported_reasoning_efforts(raw_model: Any, supports_reasoning: bool) -> List[str]:
    raw_efforts = _get_attr_or_key(raw_model, "supported_reasoning_efforts")
    efforts: List[str] = []
    if isinstance(raw_efforts, (list, tuple)):
        for effort in raw_efforts:
            normalized = normalize_reasoning_effort(effort)
            if normalized != "auto" and normalized not in efforts:
                efforts.append(normalized)
    if supports_reasoning and not efforts:
        efforts = list(REASONING_EFFORTS[1:])
    return efforts


def infer_supports_vision(model_id: str, raw_model: Any = None) -> bool:
    """Infer whether a model accepts image attachments."""
    explicit = _capability_value(raw_model, "supports_vision")
    if explicit is not None:
        return explicit
    explicit = _capability_value(raw_model, "vision")
    if explicit is not None:
        return explicit

    model_id_lower = str(model_id or "").lower()
    if not model_id_lower:
        return False

    vision_markers = (
        "4o",
        "gpt-5",
        "gpt-4.1",
        "claude-3",
        "claude-sonnet",
        "claude-opus",
        "gemini",
        "vision",
    )
    return any(marker in model_id_lower for marker in vision_markers)


def infer_supports_reasoning_effort(model_id: str, raw_model: Any = None) -> bool:
    """Infer whether a model can accept a reasoning effort option."""
    explicit = _capability_value(raw_model, "supports_reasoning_effort")
    if explicit is not None:
        return explicit

    model_id_lower = str(model_id or "").lower()
    if not model_id_lower:
        return False

    reasoning_prefixes = ("o1", "o3", "o4", "gpt-5")
    reasoning_markers = ("reasoning", "thinking")
    return model_id_lower.startswith(reasoning_prefixes) or any(marker in model_id_lower for marker in reasoning_markers)


def normalize_model(raw_model: Any, *, fallback: bool = False) -> Dict[str, Any]:
    """Normalize SDK/API model objects into the shape used by the UI."""
    model_id = str(
        _get_attr_or_key(raw_model, "id")
        or _get_attr_or_key(raw_model, "model")
        or _get_attr_or_key(raw_model, "name")
        or ""
    ).strip()
    name = str(_get_attr_or_key(raw_model, "name") or model_id).strip() or model_id
    price_label = str(_get_attr_or_key(raw_model, "price_label") or "").strip()
    multiplier = _billing_multiplier(raw_model)
    if multiplier is None and not price_label:
        multiplier = 1.0

    supports_streaming = _capability_value(raw_model, "supports_streaming")
    if supports_streaming is None:
        supports_streaming = True

    supports_tools = _capability_value(raw_model, "supports_tools")
    if supports_tools is None:
        supports_tools = True

    supports_vision = _capability_value(raw_model, "supports_vision")
    if supports_vision is None:
        supports_vision = _capability_value(raw_model, "vision")
    if supports_vision is None:
        supports_vision = infer_supports_vision(model_id)

    max_prompt_images = None
    max_prompt_image_size = None
    capabilities = _get_attr_or_key(raw_model, "capabilities")
    limits = _get_attr_or_key(capabilities, "limits") if capabilities is not None else None
    vision_limits = _get_attr_or_key(limits, "vision") if limits is not None else None
    if vision_limits is not None:
        max_prompt_images = _get_attr_or_key(vision_limits, "max_prompt_images")
        max_prompt_image_size = _get_attr_or_key(vision_limits, "max_prompt_image_size")

    supports_reasoning = infer_supports_reasoning_effort(model_id, raw_model)
    supported_reasoning_efforts = _model_supported_reasoning_efforts(raw_model, supports_reasoning)
    default_reasoning_effort = normalize_reasoning_effort(_get_attr_or_key(raw_model, "default_reasoning_effort"))

    result = {
        "id": model_id,
        "name": name,
        "multiplier": multiplier,
        "supports_reasoning_effort": supports_reasoning,
        "supported_reasoning_efforts": supported_reasoning_efforts,
        "default_reasoning_effort": None if default_reasoning_effort == "auto" else default_reasoning_effort,
        "supports_streaming": bool(supports_streaming),
        "supports_tools": bool(supports_tools),
        "supports_vision": bool(supports_vision),
        "max_prompt_images": max_prompt_images,
        "max_prompt_image_size": max_prompt_image_size,
        "fallback": bool(fallback),
    }
    if price_label:
        result["price_label"] = price_label
    return result


def normalize_models(models: Iterable[Any], *, fallback: bool = False) -> List[Dict[str, Any]]:
    """Normalize and de-duplicate model metadata."""
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for raw_model in models or []:
        model = normalize_model(raw_model, fallback=fallback)
        model_id = model.get("id", "")
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        normalized.append(model)
    return normalized


def fallback_models() -> List[Dict[str, Any]]:
    """Return normalized fallback models for offline/enterprise cases."""
    return normalize_models(FALLBACK_MODELS, fallback=True)


def find_model(models: Iterable[Dict[str, Any]], model_id: str) -> Optional[Dict[str, Any]]:
    """Find a model by id in a normalized list."""
    target = str(model_id or "")
    for model in models or []:
        if str(model.get("id", "")) == target:
            return model
    return None


def model_supports_reasoning_effort(models: Iterable[Dict[str, Any]], model_id: str) -> bool:
    """Return whether the selected model supports reasoning effort."""
    model = find_model(models, model_id)
    if model is not None:
        return bool(model.get("supports_reasoning_effort", False))
    return infer_supports_reasoning_effort(model_id)


def model_supports_vision(models: Iterable[Dict[str, Any]], model_id: str) -> bool:
    """Return whether the selected model supports image attachments."""
    model = find_model(models, model_id)
    if model is not None:
        return bool(model.get("supports_vision", False))
    return infer_supports_vision(model_id)


def model_supported_reasoning_efforts(models: Iterable[Dict[str, Any]], model_id: str) -> List[str]:
    """Return the concrete effort values supported by a model."""
    model = find_model(models, model_id)
    if model is not None:
        efforts = model.get("supported_reasoning_efforts") or []
        normalized = [normalize_reasoning_effort(effort) for effort in efforts]
        return [effort for effort in normalized if effort != "auto"]
    if infer_supports_reasoning_effort(model_id):
        return list(REASONING_EFFORTS[1:])
    return []


def usage_snapshot_for_model(models: Iterable[Dict[str, Any]], model_id: str) -> Dict[str, Any]:
    """Build an honest usage snapshot when exact quota data is unavailable."""
    model = find_model(models, model_id) or normalize_model({"id": model_id, "name": model_id})
    return {
        "available": False,
        "source": "model_metadata",
        "status": "unavailable",
        "used": None,
        "total": None,
        "model_id": model.get("id", model_id),
        "model_name": model.get("name", model_id),
        "multiplier": model.get("multiplier", 1.0),
        "subscription_url": "https://github.com/settings/copilot",
    }


def _number_or_none(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _display_number(value: Optional[float]) -> Optional[int | float]:
    if value is None:
        return None
    return int(value) if value == int(value) else round(value, 2)


def _quota_snapshots(quota_data: Any) -> Dict[str, Any]:
    snapshots = _get_attr_or_key(quota_data, "quota_snapshots")
    return snapshots if isinstance(snapshots, dict) else {}


def _select_quota_snapshot(quota_data: Any) -> Tuple[Optional[str], Optional[Any]]:
    snapshots = _quota_snapshots(quota_data)
    if not snapshots:
        return None, None
    preferred_keys = (
        "premium_interactions",
        "premium_requests",
        "premium",
        "chat",
        "completions",
    )
    for key in preferred_keys:
        if key in snapshots:
            return key, snapshots[key]
    first_key = next(iter(snapshots))
    return first_key, snapshots[first_key]


def usage_snapshot_from_quota(
    quota_data: Any,
    models: Iterable[Dict[str, Any]],
    model_id: str,
    *,
    source: str = "quota",
) -> Dict[str, Any]:
    """Build a usage snapshot from Copilot account quota data."""
    base = usage_snapshot_for_model(models, model_id)
    quota_key, quota_snapshot = _select_quota_snapshot(quota_data)
    if quota_snapshot is None:
        return base

    used = _number_or_none(_get_attr_or_key(quota_snapshot, "used_requests"))
    total = _number_or_none(_get_attr_or_key(quota_snapshot, "entitlement_requests"))
    remaining = _number_or_none(_get_attr_or_key(quota_snapshot, "remaining_percentage"))
    overage = _number_or_none(_get_attr_or_key(quota_snapshot, "overage"))

    if used is None and total is not None and remaining is not None:
        used = max(total * (100.0 - remaining) / 100.0, 0.0)

    base.update({
        "available": used is not None or total is not None or remaining is not None,
        "source": source,
        "status": "available",
        "quota_key": quota_key,
        "used": _display_number(used),
        "total": _display_number(total),
        "remaining_percentage": _display_number(remaining),
        "overage": _display_number(overage),
        "reset_date": _get_attr_or_key(quota_snapshot, "reset_date"),
        "overage_allowed_with_exhausted_quota": bool(
            _get_attr_or_key(quota_snapshot, "overage_allowed_with_exhausted_quota", False)
        ),
    })
    return base


def usage_snapshot_from_event(data: Any, models: Iterable[Dict[str, Any]], model_id: str) -> Dict[str, Any]:
    """Build a usage snapshot from SDK session usage events."""
    quota_snapshots = _get_attr_or_key(data, "quota_snapshots")
    if isinstance(quota_snapshots, dict) and quota_snapshots:
        return usage_snapshot_from_quota(
            {"quota_snapshots": quota_snapshots},
            models,
            model_id,
            source="session_event",
        )

    event_model = _get_attr_or_key(data, "model") or _get_attr_or_key(data, "current_model") or model_id
    base = usage_snapshot_for_model(models, event_model)
    premium_requests = _number_or_none(_get_attr_or_key(data, "total_premium_requests"))
    input_tokens = _number_or_none(_get_attr_or_key(data, "input_tokens"))
    output_tokens = _number_or_none(_get_attr_or_key(data, "output_tokens"))
    cache_read_tokens = _number_or_none(_get_attr_or_key(data, "cache_read_tokens"))
    cache_write_tokens = _number_or_none(_get_attr_or_key(data, "cache_write_tokens"))

    if premium_requests is not None or input_tokens is not None or output_tokens is not None:
        base.update({
            "available": True,
            "source": "session_event",
            "status": "partial",
            "used": _display_number(premium_requests),
            "total": None,
            "input_tokens": _display_number(input_tokens),
            "output_tokens": _display_number(output_tokens),
            "cache_read_tokens": _display_number(cache_read_tokens),
            "cache_write_tokens": _display_number(cache_write_tokens),
        })
    return base