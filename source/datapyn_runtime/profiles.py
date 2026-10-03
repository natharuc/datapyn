"""Preview workspaces isolate catalogs, drafts and preferences; removal is archival."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
import uuid

from .data_tools import atomic_destination

METHODS = frozenset({"workspace.profiles.list", "workspace.profiles.create", "workspace.profiles.rename",
                     "workspace.profiles.clone", "workspace.profiles.delete", "workspace.profiles.restore",
                     "workspace.profiles.select", "workspace.profiles.state", "workspace.profiles.save"})
LOCK = threading.RLock()
MAX_STATE_BYTES = 16 * 1024 * 1024
CONFIG_FILES = ("connections.json", "notifications.json", "snapshot_settings.json")


def base_path():
    path = Path(os.environ.get("DATAPYN_RUNTIME_STATE_PATH") or Path.home() / ".datapyn-tauri-preview").expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    if len(text.encode("utf-8")) > MAX_STATE_BYTES:
        raise ValueError("Workspace data exceeds 16 MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_destination(path) as temporary:
        temporary.write_text(text, encoding="utf-8")


def _registry():
    path = base_path() / "workspace_profiles.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("profiles"), list):
            raise ValueError("Unsupported workspace registry")
        return data
    data = {"version": 1, "active_id": "default", "profiles": [{"id": "default", "name": "Padrão", "archived": False, "created_at": time.time()}]}
    _write(path, data)
    return data


def _profile(registry, identifier=None, allow_archived=False):
    identifier = identifier or registry["active_id"]
    if identifier != "default" and not isinstance(identifier, str):
        raise ValueError("Invalid workspace identifier")
    if identifier != "default" and not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise ValueError("Invalid workspace identifier")
    profile = next((item for item in registry["profiles"] if item["id"] == identifier), None)
    if not profile or profile.get("archived") and not allow_archived:
        raise KeyError("Workspace is unavailable")
    return profile


def profile_path(identifier=None):
    with LOCK:
        registry = _registry()
        profile = _profile(registry, identifier, allow_archived=True)
        base = base_path()
        path = base if profile["id"] == "default" else (base / "profiles" / profile["id"]).resolve()
        if profile["id"] != "default" and path.parent != (base / "profiles").resolve():
            raise ValueError("Workspace path must remain in the preview directory")
        path.mkdir(parents=True, exist_ok=True)
        return path


def _public(profile):
    return {**deepcopy(profile), "path": str(profile_path(profile["id"]))}


def _name(value, registry, excluding=None):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 100:
        raise ValueError("Workspace name must contain 1 to 100 characters")
    name = value.strip()
    if any(item["id"] != excluding and not item.get("archived") and item["name"].casefold() == name.casefold() for item in registry["profiles"]):
        raise ValueError("An active workspace already has this name")
    return name


def list_profiles(params=None):
    with LOCK:
        registry = _registry()
        return {"active_id": registry["active_id"], "profiles": [_public(item) for item in registry["profiles"] if (params or {}).get("include_archived") or not item.get("archived")],
                "packages_shared": True}


def create(params):
    with LOCK:
        registry = _registry()
        profile = {"id": uuid.uuid4().hex, "name": _name(params.get("name"), registry), "archived": False, "created_at": time.time()}
        registry["profiles"].append(profile)
        _write(base_path() / "workspace_profiles.json", registry)
        return _public(profile)


def rename(params):
    with LOCK:
        registry = _registry()
        profile = _profile(registry, params.get("profile_id"))
        profile["name"] = _name(params.get("name"), registry, profile["id"])
        _write(base_path() / "workspace_profiles.json", registry)
        return _public(profile)


def state(params=None):
    with LOCK:
        registry = _registry()
        profile = _profile(registry, (params or {}).get("profile_id"))
        path = profile_path(profile["id"]) / "workspace_state.json"
        document = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        return {"active_id": registry["active_id"], "profile": _public(profile), "state": document}


def _validate_state(value):
    if not isinstance(value, dict) or not isinstance(value.get("documents", []), list):
        raise ValueError("Workspace state requires a document list")
    if len(value.get("documents", [])) > 1000:
        raise ValueError("Workspaces support at most 1000 open analyses")
    for record in value.get("documents", []):
        if not isinstance(record, dict) or not isinstance(record.get("document"), dict):
            raise ValueError("Each open analysis requires its document")
        if not isinstance(record.get("title", ""), str):
            raise ValueError("Analysis titles must be strings")
    active = value.get("activeIndex", 0)
    if isinstance(active, bool) or not isinstance(active, int) or active < 0:
        raise ValueError("activeIndex must be a non-negative integer")
    for key in ("preferences", "shortcuts", "layout"):
        if key in value and not isinstance(value[key], dict):
            raise ValueError(f"{key} must be an object")
    return deepcopy(value)


def save(params):
    with LOCK:
        registry = _registry()
        profile = _profile(registry, params.get("profile_id"))
        document = _validate_state(params.get("state"))
        document["saved_at"] = time.time()
        _write(profile_path(profile["id"]) / "workspace_state.json", document)
        return {"profile_id": profile["id"], "saved_at": document["saved_at"]}


def select(params):
    """Supervisor must refuse active execution and dispose old kernels first."""
    with LOCK:
        registry = _registry()
        profile = _profile(registry, params.get("profile_id"))
        registry["active_id"] = profile["id"]
        _write(base_path() / "workspace_profiles.json", registry)
        return state({"profile_id": profile["id"]})


def archive(params, restore=False):
    with LOCK:
        registry = _registry()
        profile = _profile(registry, params.get("profile_id"), allow_archived=True)
        if not restore and (profile["id"] == "default" or profile["id"] == registry["active_id"]):
            raise ValueError("Switch away before archiving a workspace; the default cannot be archived")
        if restore:
            _name(profile["name"], registry, profile["id"])
        profile["archived"] = not restore
        profile["archived_at"] = None if restore else time.time()
        _write(base_path() / "workspace_profiles.json", registry)
        return _public(profile)


def _remap(value, connections, groups):
    if isinstance(value, list):
        return [_remap(item, connections, groups) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {"connection_id", "savedConnectionId"} and isinstance(item, str):
            result[key] = connections.get(item, item)
        elif key in {"group_id", "parent_id"} and isinstance(item, str):
            result[key] = groups.get(item, item)
        else:
            result[key] = _remap(item, connections, groups)
    return result


def _snapshot_root(workspace):
    base = os.environ.get("DATAPYN_SNAPSHOT_ROOT")
    if not base:
        cache = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
        base = str(Path(cache or str(Path.home() / ".cache")) / "DataPynTauriPreview" / "session_snapshots")
    return Path(base).expanduser().resolve() / hashlib.sha256(str(workspace).encode()).hexdigest()[:24]


def _clone_snapshots(source, target):
    source_root, target_root = _snapshot_root(source), _snapshot_root(target)
    if not source_root.is_dir():
        return
    target_root.mkdir(parents=True, exist_ok=True)
    for session in source_root.iterdir():
        if not session.is_dir() or session.is_symlink() or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session.name):
            continue
        pointer = session / "current.json"
        if not pointer.is_file() or pointer.is_symlink():
            continue
        generation = json.loads(pointer.read_text()).get("generation")
        if not isinstance(generation, str) or not re.fullmatch(r"g-[0-9a-f]{32}", generation):
            continue
        source_generation = session / generation
        if source_generation.is_symlink() or source_generation.resolve().parent != session.resolve():
            continue
        target_generation = target_root / session.name / generation
        target_generation.mkdir(parents=True, exist_ok=True)
        for file in source_generation.iterdir():
            if file.is_symlink() or not file.is_file() or not (file.name == "manifest.json" or re.fullmatch(r"frame-\d{6}\.parquet", file.name)):
                continue
            shutil.copy2(file, target_generation / file.name)
        manifest_path = target_generation / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["workspace"] = str(target)
            _write(manifest_path, manifest)
            _write(target_root / session.name / "current.json", {"generation": generation})


def clone(params):
    with LOCK:
        registry = _registry()
        original = _profile(registry, params.get("profile_id"))
        # Register only after the copy is complete. Partial copies remain as an
        # unregistered recoverable directory rather than deleting arbitrary files.
        profile = {"id": uuid.uuid4().hex, "name": _name(params.get("name"), registry), "archived": False, "created_at": time.time()}
        source, target = profile_path(original["id"]), base_path() / "profiles" / profile["id"]
        target.mkdir(parents=True)
        group_ids, connection_ids = {}, {}
        catalog_file = source / "connections.json"
        if catalog_file.is_file():
            catalog = json.loads(catalog_file.read_text(encoding="utf-8-sig"))
            group_ids = {item["id"]: uuid.uuid4().hex for item in catalog.get("groups", [])}
            connection_ids = {item["id"]: uuid.uuid4().hex for item in catalog.get("connections", [])}
            catalog = _remap(catalog, connection_ids, group_ids)
            from .connection_catalog import CredentialStore
            credentials = CredentialStore()
            for group in catalog.get("groups", []):
                group["id"] = group_ids[group["id"]]
            for connection in catalog.get("connections", []):
                old_id = connection["id"]
                connection["id"] = connection_ids[old_id]
                copied_secrets = credentials.get(old_id) if params.get("include_credentials", False) and connection.get("has_password") else {}
                if copied_secrets:
                    credentials.set(connection["id"], copied_secrets)
                connection["has_password"] = bool(copied_secrets)
            _write(target / "connections.json", catalog)
        for name in CONFIG_FILES:
            if name == "connections.json":
                continue
            file = source / name
            if file.is_file() and not file.is_symlink():
                _write(target / name, json.loads(file.read_text(encoding="utf-8")))
        document = state({"profile_id": original["id"]})["state"]
        if document is not None:
            _write(target / "workspace_state.json", _remap(document, connection_ids, group_ids))
        pynia = source / "pynia"
        if pynia.is_dir() and not pynia.is_symlink():
            for file in pynia.glob("*.json"):
                if file.is_file() and not file.is_symlink():
                    _write(target / "pynia" / file.name, _remap(json.loads(file.read_text(encoding="utf-8")), connection_ids, group_ids))
        if params.get("include_snapshots", True):
            _clone_snapshots(source, target)
        if params.get("include_credentials", False):
            import keyring
            old_service = "DataPyn.Tauri.preview.notifications." + hashlib.sha256(str(source).encode()).hexdigest()[:20]
            new_service = "DataPyn.Tauri.preview.notifications." + hashlib.sha256(str(target).encode()).hexdigest()[:20]
            for name in ("telegram_bot_token", "email_password"):
                value = keyring.get_password(old_service, name)
                if value:
                    keyring.set_password(new_service, name, value)
        registry["profiles"].append(profile)
        _write(base_path() / "workspace_profiles.json", registry)
        return _public(profile)


def dispatch(method, params):
    handlers = {"workspace.profiles.list": list_profiles, "workspace.profiles.create": create,
                "workspace.profiles.rename": rename, "workspace.profiles.clone": clone,
                "workspace.profiles.select": select, "workspace.profiles.state": state,
                "workspace.profiles.save": save}
    if method in handlers:
        return handlers[method](params)
    if method == "workspace.profiles.delete":
        return archive(params)
    if method == "workspace.profiles.restore":
        return archive(params, restore=True)
    raise ValueError(f"Unknown workspace operation: {method}")
