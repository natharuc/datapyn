"""Normalize ACP session config options (model + reasoning)."""

from __future__ import annotations

from typing import Any, Optional


def _option_id(option: dict[str, Any]) -> str:
    return str(option.get("id") or option.get("configId") or "")


def _choice_items(option: dict[str, Any]) -> list:
    return option.get("options") or option.get("values") or option.get("availableModels") or []


def _select_values(option: dict[str, Any]) -> list[dict[str, str]]:
    values = []
    for item in _choice_items(option):
        if isinstance(item, dict):
            value = str(item.get("value") or item.get("id") or item.get("modelId") or "")
            name = str(item.get("name") or item.get("label") or value)
            description = str(item.get("description") or "").strip()
        else:
            value = str(item or "")
            name = value
            description = ""
        if not value:
            continue
        entry = {"value": value, "name": name or value}
        if description:
            entry["description"] = description
        values.append(entry)
    return values


def _from_models_field(models: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not isinstance(models, dict):
        return None
    available = models.get("availableModels") or models.get("models") or []
    values = []
    for item in available:
        if isinstance(item, dict):
            value = str(item.get("modelId") or item.get("id") or item.get("value") or "")
            name = str(item.get("name") or value)
            description = str(item.get("description") or "").strip()
        else:
            value = str(item)
            name = value
            description = ""
        if not value:
            continue
        entry = {"value": value, "name": name}
        if description:
            entry["description"] = description
        values.append(entry)
    if not values:
        return None
    current = str(models.get("currentModelId") or models.get("currentValue") or values[0]["value"])
    return {
        "id": "model",
        "category": "model",
        "label": "LLM",
        "current": current,
        "values": values,
        "hidden": False,
        "loading": False,
    }


def _selector_from_option(option: dict[str, Any], *, category: str, label: str) -> Optional[dict[str, Any]]:
    values = _select_values(option)
    current = option.get("currentValue")
    if current is None:
        current = option.get("value")
    if not values and current is not None and str(current).strip():
        values = [{"value": str(current), "name": str(current)}]
    if not values:
        return None
    return {
        "id": _option_id(option) or category,
        "category": category,
        "label": label,
        "current": str(current if current is not None else values[0]["value"]),
        "values": values,
        "hidden": False,
        "loading": False,
    }


def _match_model(options: list[dict]) -> Optional[dict[str, Any]]:
    for option in options:
        if not isinstance(option, dict):
            continue
        if str(option.get("type") or "select") == "boolean":
            continue
        category = str(option.get("category") or "").lower()
        oid = _option_id(option).lower()
        if category == "mode" or category == "model_config":
            continue
        if category == "model" or oid == "model":
            return _selector_from_option(option, category="model", label="LLM")
    return None


def _match_reasoning(options: list[dict]) -> Optional[dict[str, Any]]:
    for option in options:
        if not isinstance(option, dict):
            continue
        if str(option.get("type") or "select") == "boolean":
            continue
        category = str(option.get("category") or "").lower()
        oid = _option_id(option).lower()
        name = str(option.get("name") or "").lower()
        if category == "mode":
            continue
        if (
            category == "thought_level"
            or oid in {"thought_level", "thought", "reasoning"}
            or "thought" in category
            or name in {"reasoning", "thought", "thought level"}
        ):
            return _selector_from_option(option, category="thought_level", label="Reasoning")
    return None


def _prefer(selector: dict[str, Any], preferred: str) -> None:
    """Set current only when the agent actually offers that value."""
    preferred = (preferred or "").strip()
    if not preferred:
        return
    values = selector.get("values") or []
    ids = {item["value"] for item in values}
    if preferred in ids:
        selector["current"] = preferred


def _empty_model(*, loading: bool) -> dict[str, Any]:
    return {
        "id": "model",
        "category": "model",
        "label": "LLM",
        "current": "",
        "values": [],
        "hidden": not loading,
        "loading": loading,
    }


def _empty_reasoning(*, loading: bool, hidden: bool = True) -> dict[str, Any]:
    return {
        "id": "thought_level",
        "category": "thought_level",
        "label": "Reasoning",
        "current": "",
        "values": [],
        "hidden": hidden,
        "loading": loading,
    }


def merge_config_snapshot(
    previous: Optional[dict[str, Any]],
    incoming: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Merge ACP config payloads without dropping the previous option lists."""
    prev = dict(previous or {})
    new = incoming if isinstance(incoming, dict) else {}
    if not new:
        return prev
    prev_opts = [item for item in (prev.get("configOptions") or []) if isinstance(item, dict)]
    new_opts = new.get("configOptions")
    merged = {**prev, **new}
    if isinstance(new_opts, list) and new_opts:
        incoming_opts = [item for item in new_opts if isinstance(item, dict)]
        by_id = {_option_id(item): item for item in prev_opts}
        out = []
        for option in incoming_opts:
            old = by_id.get(_option_id(option)) or {}
            combined = {**old, **option}
            if not _choice_items(option) and _choice_items(old):
                if old.get("options"):
                    combined["options"] = old["options"]
                elif old.get("values"):
                    combined["values"] = old["values"]
                elif old.get("availableModels"):
                    combined["availableModels"] = old["availableModels"]
            out.append(combined)
        merged["configOptions"] = out
    elif "configOptions" in new and prev_opts:
        merged["configOptions"] = prev_opts
    return merged


def filter_values(values: list[dict[str, str]], query: str) -> list[dict[str, str]]:
    """Case-insensitive filter used by the LLM search picker."""
    needle = (query or "").strip().lower()
    if not needle:
        return list(values or [])
    out = []
    for item in values or []:
        blob = " ".join(
            str(item.get(key) or "")
            for key in ("name", "value", "description")
        ).lower()
        if needle in blob:
            out.append(item)
    return out


def composer_selectors(
    session_result: Optional[dict[str, Any]] = None,
    *,
    model_id: str = "",
    thought_level: str = "",
    loading: bool = False,
) -> dict[str, Any]:
    """LLM + Reasoning controls for the chat composer."""
    if loading:
        return {
            "model": _empty_model(loading=True),
            "reasoning": _empty_reasoning(loading=True, hidden=True),
        }

    raw = session_result or {}
    options = [item for item in (raw.get("configOptions") or []) if isinstance(item, dict)]
    model = _match_model(options) or _from_models_field(raw.get("models") or {})
    reasoning = _match_reasoning(options)

    if model is None:
        model = _empty_model(loading=False)
    else:
        model["label"] = "LLM"
        model["hidden"] = not (model.get("values") or [])
        model["loading"] = False
        _prefer(model, model_id)

    if reasoning is None:
        reasoning = _empty_reasoning(loading=False, hidden=True)
    else:
        reasoning["label"] = "Reasoning"
        reasoning["hidden"] = not (reasoning.get("values") or [])
        reasoning["loading"] = False
        _prefer(reasoning, thought_level)

    return {"model": model, "reasoning": reasoning}
