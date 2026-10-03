"""Portable defaults shared by explicit configuration transfer and new chats."""

from copy import deepcopy
import json
from pathlib import Path

CSV_DEFAULTS = {"delimiter": ";", "decimal": ".", "encoding": "utf-8-sig", "include_header": True, "open_folder": True}


def normalize_pynia(value):
    if not isinstance(value, dict):
        raise ValueError("Pynia defaults must be an object")
    result = {}
    for field in ("default_agent_id", "model_id", "thought_level"):
        if field in value:
            if not isinstance(value[field], str) or len(value[field]) > 256:
                raise ValueError("Invalid Pynia default")
            result[field] = value[field]
    preferences = value.get("agent_prefs")
    if preferences is not None:
        if not isinstance(preferences, dict) or len(preferences) > 64:
            raise ValueError("Pynia agent preferences must be a bounded object")
        result["agent_prefs"] = {}
        for identifier, settings in preferences.items():
            if not isinstance(identifier, str) or len(identifier) > 128 or not isinstance(settings, dict):
                raise ValueError("Invalid Pynia agent preference")
            fields = {}
            for key in ("model_id", "thought_level"):
                if key in settings:
                    if not isinstance(settings[key], str) or len(settings[key]) > 256:
                        raise ValueError("Invalid Pynia agent preference")
                    fields[key] = settings[key]
            result["agent_prefs"][identifier] = fields
    return result


def normalize_defaults(value):
    if not isinstance(value, dict):
        raise ValueError("Configuration defaults must be an object")
    result = {}
    if "export_settings" in value:
        incoming = value["export_settings"]
        if not isinstance(incoming, dict):
            raise ValueError("CSV defaults must be an object")
        csv = {key: incoming[key] for key in CSV_DEFAULTS if key in incoming}
        if "delimiter" in csv and csv["delimiter"] not in {";", ",", "\t", "|"} or "decimal" in csv and csv["decimal"] not in {".", ","}:
            raise ValueError("Invalid CSV delimiter or decimal default")
        if "encoding" in csv and csv["encoding"] not in {"utf-8-sig", "utf-8", "cp1252", "latin-1"}:
            raise ValueError("Unsupported legacy CSV encoding")
        if any(not isinstance(csv[key], bool) for key in ("include_header", "open_folder") if key in csv):
            raise ValueError("CSV header and open-folder defaults must be boolean")
        if csv:
            result["export_settings"] = csv
    for key in ("copy_separator", "copy_null_display"):
        if key in value:
            if not isinstance(value[key], str) or len(value[key]) > 64:
                raise ValueError("Invalid clipboard default")
            result[key] = value[key]
    if "export_open_folder" in value:
        if not isinstance(value["export_open_folder"], bool):
            raise ValueError("Export open-folder default must be boolean")
        result["export_open_folder"] = value["export_open_folder"]
    if "pynia" in value:
        result["pynia"] = normalize_pynia(value["pynia"])
    return result


def merge_defaults(previous, incoming):
    result = deepcopy(previous)
    for key, value in incoming.items():
        if key == "export_settings":
            result.setdefault(key, {}).update(value)
        elif key == "pynia":
            old = result.setdefault(key, {})
            old.update({name: item for name, item in value.items() if name != "agent_prefs"})
            for agent, preferences in value.get("agent_prefs", {}).items():
                old.setdefault("agent_prefs", {}).setdefault(agent, {}).update(preferences)
        else:
            result[key] = deepcopy(value)
    return result


def load_defaults(workspace):
    path = Path(workspace) / "configuration_defaults.json"
    if not path.is_file():
        return {}
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Configuration defaults exceed 8 MiB")
    document = json.loads(path.read_text(encoding="utf-8"))
    return normalize_defaults(document.get("defaults", document))
