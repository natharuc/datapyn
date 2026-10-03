"""Explicit, previewed transfer of the legacy workspace configuration folder.

Windows Registry settings are deliberately not discovered: an explicitly
provided DataPyn.ini is a portable QSettings representation, not a promise that
the old Windows application automatically loads it as its global settings.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlsplit, urlunsplit, unquote
import uuid

from .connection_catalog import ConnectionCatalog, without_secrets, _path
from .legacy_settings import (PREFERENCE_KEYS, ini_values, patch_ini, preferences_from_ini,
                              shortcuts_from_document, shortcuts_to_document, strip_ini_secrets, typed, ini_string_list)
from .configuration_defaults import CSV_DEFAULTS, load_defaults, normalize_defaults, merge_defaults

METHODS = frozenset({"configurations.inspect", "configurations.import", "configurations.export", "configurations.defaults.get"})
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FILES = 128
EXCLUDED = {"sessions.json", "workspace.json", "workspace_state.json", "workspace-state.json", "session_store.db",
            "session_store.db-shm", "session_store.db-wal", "profiles.json", "workspace_profiles.json", "workspaces.ini", "notificationsecrets.ini",
            "notifications.json", "snapshot_settings.json", "pynia_settings.json", "package_sources.json", "configuration_defaults.json"}
CATEGORIES = {"connections.json": "connections", "shortcuts.json": "shortcuts", "datapyn.ini": "preferences",
              "pyniasettings.ini": "pynia", "mainwindow.ini": "legacy_layout", "dockinglayout.ini": "legacy_layout",
              "csvexport.ini": "export", "exportsettings.ini": "export", "packagemanager.ini": "packages",
              "tauri-settings.json": "tauri_preferences"}
REGISTRY_WARNING = "On Windows, the PyQt6 application stores global preferences in the Windows Registry. Folder transfer preserves supplied INI files but does not read or write that Registry."


class _NoCredentials:
    def delete(self, identifier):
        pass


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def _json(raw, name, *, object_required=True):
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"Invalid JSON configuration: {name}") from error
    if object_required and not isinstance(value, dict):
        raise ValueError(f"Configuration {name} must contain a JSON object")
    return value


def _preferences(value):
    if not isinstance(value, dict):
        raise ValueError("Preferences must be an object")
    booleans = {"wordWrap", "lineNumbers", "minimap", "autocomplete", "maximizeFirstBlock", "aiAutocomplete",
                "leftVisible", "rightVisible", "notifications", "notificationSound"}
    limits = {"uiFontSize": (8, 24), "editorFontSize": (8, 40), "gridFontSize": (7, 40), "tabSize": (1, 8),
              "connectionIdleSeconds": (0, 86400), "leftWidth": (160, 640), "rightWidth": (160, 640),
              "resultHeight": (100, 1200), "displayRowLimit": (0, 1_000_000)}
    strings = {"uiFont", "editorFont", "gridFont"}
    result = {}
    for key, item in value.items():
        if key in booleans:
            if not isinstance(item, bool):
                raise ValueError(f"Preference {key} must be a boolean")
            result[key] = item
        elif key in limits:
            low, high = limits[key]
            if isinstance(item, bool) or not isinstance(item, (int, float)) or not low <= item <= high:
                raise ValueError(f"Preference {key} is outside the supported range")
            result[key] = int(item)
        elif key in strings:
            if not isinstance(item, str) or len(item) > 1000:
                raise ValueError(f"Invalid font preference: {key}")
            result[key] = item
        elif key in {"locale", "theme"}:
            allowed = {"pt-BR", "en-US"} if key == "locale" else {"dark", "light", "system"}
            if item not in allowed:
                raise ValueError(f"Unsupported preference: {key}")
            result[key] = item
        elif key == "sharedDelimiter":
            if not isinstance(item, str) or item.count("name") != 1 or len(item) > 40 or item == "name":
                raise ValueError("Invalid shared parameter delimiter")
            result[key] = item
    return result


def _notification_settings(values, previous=None):
    from .notifications import DEFAULTS, _normalize_settings
    result = _normalize_settings(previous) if previous else deepcopy(DEFAULTS)
    found = False
    for key, default in DEFAULTS.items():
        if isinstance(default, dict):
            for field, initial in default.items():
                name = "from" if field == "from_address" else field
                source = f"notifications/{key}/{name}"
                if source in values:
                    result[key][field] = typed(values[source], type(initial))
                    found = True
        elif f"notifications/{key}" in values:
            result[key] = typed(values[f"notifications/{key}"], type(default))
            found = True
    return _normalize_settings(result) if found else None


def _notification_keys(settings):
    result = {}
    for key, value in settings.items():
        if isinstance(value, dict):
            for field, item in value.items():
                if field != "configured":
                    result[f"notifications/{key}/{'from' if field == 'from_address' else field}"] = item
        elif key not in {"secrets_present", "credential_error"}:
            result[f"notifications/{key}"] = value
    return result


class ConfigurationTransfer:
    def __init__(self, workspace, catalog, package_service=None):
        self.workspace = Path(workspace).resolve()
        self.catalog = catalog
        self.archive = self.workspace / ".pyqt-configuration"
        self.package_service = package_service

    def _package_sources(self):
        if self.package_service is None or not self.package_service.config.is_file():
            return []
        document = _json(self.package_service.config.read_bytes(), "package sources", object_required=False)
        return document.get("sources", []) if isinstance(document, dict) else document

    def _read(self, path):
        source = _path(path)
        if not source.is_dir():
            raise ValueError("Configuration import must select a folder")
        if source == self.workspace or self.workspace in source.parents:
            raise ValueError("Select an external configuration folder, not the active Tauri workspace")
        blobs, excluded, total = {}, [], 0
        entries = sorted(source.iterdir(), key=lambda entry: entry.name.casefold())
        if len(entries) > MAX_FILES:
            raise ValueError("Configuration folder contains more than 128 entries")
        for entry in entries:
            lower = entry.name.lower()
            if entry.is_symlink() or not entry.is_file() or lower in EXCLUDED or entry.suffix.lower() not in {".ini", ".json"}:
                excluded.append(entry.name)
                continue
            size = entry.stat().st_size
            total += size
            if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError("Configuration transfer exceeds the 8 MiB per file or 32 MiB total limit")
            raw = entry.read_bytes()
            if len(raw) != size:
                raise ValueError("Configuration file changed while it was being inspected")
            if entry.suffix.lower() == ".ini":
                clean = strip_ini_secrets(raw)
            else:
                document = _json(raw, entry.name, object_required=lower in {"connections.json", "shortcuts.json", "tauri-settings.json"})
                safe = without_secrets(document)
                clean = raw if safe == document else _json_bytes(safe)
            if any(name.casefold() == lower for name in blobs):
                raise ValueError("Configuration filenames differ only by letter case")
            blobs[entry.name] = clean
        if not blobs:
            raise ValueError("The selected folder contains no transferable INI or JSON configuration")
        return source, blobs, excluded

    def _prepare(self, path):
        source, blobs, excluded = self._read(path)
        by_name = {name.lower(): raw for name, raw in blobs.items()}
        preferences, shortcuts = {}, {}
        if "datapyn.ini" in by_name:
            preferences.update(preferences_from_ini(by_name["datapyn.ini"]))
        if "pyniasettings.ini" in by_name:
            values = ini_values(by_name["pyniasettings.ini"])
            if "autocomplete_enabled" in values:
                preferences["aiAutocomplete"] = typed(values["autocomplete_enabled"], bool)
        if "tauri-settings.json" in by_name:
            portable = _json(by_name["tauri-settings.json"], "tauri-settings.json")
            preferences.update(_preferences(portable.get("preferences", {})))
        preferences = _preferences(preferences)
        if "shortcuts.json" in by_name:
            shortcuts = shortcuts_from_document(_json(by_name["shortcuts.json"], "shortcuts.json"))
        defaults = {}
        if "csvexport.ini" in by_name:
            values = ini_values(by_name["csvexport.ini"])
            settings = {}
            for field, initial in CSV_DEFAULTS.items():
                native = "header" if field == "include_header" else field
                if native in values:
                    settings[field] = typed(values[native], type(initial))
            if settings:
                defaults["export_settings"] = settings
        if "exportsettings.ini" in by_name:
            values = ini_values(by_name["exportsettings.ini"])
            for key, source, kind in (("copy_separator", "copy_separator", str), ("copy_null_display", "null_display", str),
                                      ("export_open_folder", "open_folder", bool)):
                if source in values:
                    defaults[key] = typed(values[source], kind)
        if "pyniasettings.ini" in by_name:
            values = ini_values(by_name["pyniasettings.ini"])
            pynia = {name: values[name] for name in ("default_agent_id", "model_id", "thought_level") if name in values}
            for key, value in values.items():
                parts = key.split("/")
                if len(parts) == 3 and parts[0] == "agent_prefs" and parts[2] in {"model_id", "thought_level"}:
                    pynia.setdefault("agent_prefs", {}).setdefault(parts[1], {})[parts[2]] = value
            if pynia:
                defaults["pynia"] = pynia
        if "tauri-settings.json" in by_name:
            defaults = merge_defaults(defaults, normalize_defaults(portable.get("defaults", {})))
        defaults = normalize_defaults(defaults)
        package_sources = None
        if "packagemanager.ini" in by_name and ini_string_list(by_name["packagemanager.ini"], "extra_index_urls") is not None:
            raw = by_name["packagemanager.ini"]
            urls = ini_string_list(raw, "extra_index_urls")
            package_sources = []
            for url in urls:
                parts = urlsplit(url.strip())
                if parts.scheme not in {"http", "https"} or not parts.netloc:
                    raise ValueError("Legacy package source URLs must use http or https")
                clean_url = urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, parts.query, parts.fragment))
                package_sources.append({"url": clean_url, "username": unquote(parts.username or "")})
            name = next(name for name in blobs if name.lower() == "packagemanager.ini")
            blobs[name] = patch_ini(raw, {"extra_index_urls": [source["url"] for source in package_sources]})
        digest = hashlib.sha256()
        for name, raw in blobs.items():
            digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(raw).digest())
        digest.update(_json_bytes(self.catalog.list()))
        digest.update(_json_bytes(load_defaults(self.workspace)))
        for filename in ("notifications.json", "snapshot_settings.json"):
            current = self.workspace / filename
            if current.is_file():
                digest.update(filename.encode() + hashlib.sha256(current.read_bytes()).digest())
        if package_sources is not None:
            digest.update(_json_bytes(self._package_sources()))
        prepared = ConnectionCatalog(self.workspace / ".configuration-validation-only", _NoCredentials())
        prepared.data = self.catalog.list()
        prepared._defer_save = True
        imported_connections = 0
        if "connections.json" in by_name:
            outcome, _ = prepared._import_document(_json(by_name["connections.json"], "connections.json"))
            imported_connections = outcome["imported_connections"]
        values = ini_values(by_name.get("datapyn.ini", b""))
        notification_path = self.workspace / "notifications.json"
        previous_notifications = _json(notification_path.read_bytes(), "notifications.json") if notification_path.is_file() else None
        notification_settings = _notification_settings(values, previous_notifications)
        snapshot_settings = None
        if "session_results/enabled" in values or "session_results/max_size_mb" in values:
            from .variable_snapshot import _normalize
            snapshot_path = self.workspace / "snapshot_settings.json"
            snapshots = _json(snapshot_path.read_bytes(), "snapshot_settings.json") if snapshot_path.is_file() else {}
            for source, key, kind in (("session_results/enabled", "enabled", bool), ("session_results/max_size_mb", "max_size_mb", int)):
                if source in values:
                    snapshots[key] = typed(values[source], kind)
            snapshot_settings = _normalize(snapshots)
        response = {"path": str(source), "preview_token": digest.hexdigest(),
                    "files": [{"name": name, "category": CATEGORIES.get(name.lower(), "preserved_extension"), "bytes": len(raw)} for name, raw in blobs.items()],
                    "excluded_files": excluded, "warnings": [REGISTRY_WARNING], "preferences": preferences, "shortcuts": shortcuts,
                    "connections": imported_connections, "groups": len(prepared.data["groups"]), "passwords_included": False}
        response["defaults"] = defaults
        if package_sources is not None:
            response["package_sources"] = package_sources
        if any("layout" in file["category"] for file in response["files"]):
            response["warnings"].append("Qt dock geometry is retained for PyQt6; it cannot be converted into a Dockview layout.")
        if any(name.lower() == "packagemanager.ini" for name in blobs):
            response["warnings"].append("The opaque sources_v2 package credential container is omitted. Supply password-free extra_index_urls to transfer legacy package sources.")
        return response, blobs, prepared.data, notification_settings, snapshot_settings, defaults, package_sources

    def inspect(self, params):
        return self._prepare(params.get("path"))[0]

    @staticmethod
    def _write(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def import_folder(self, params):
        response, blobs, catalog_data, notifications, snapshots, defaults, package_sources = self._prepare(params.get("path"))
        token = params.get("preview_token")
        if not isinstance(token, str) or token != response["preview_token"]:
            raise ValueError("Inspect this configuration folder again before importing; its preview is missing or stale")
        changes = {self.archive / name: raw for name, raw in blobs.items()}
        if notifications is not None:
            changes[self.workspace / "notifications.json"] = _json_bytes(notifications)
        if snapshots is not None:
            changes[self.workspace / "snapshot_settings.json"] = _json_bytes(snapshots)
        if defaults:
            merged = merge_defaults(load_defaults(self.workspace), defaults)
            changes[self.workspace / "configuration_defaults.json"] = _json_bytes({"version": 1, "defaults": merged})
        if package_sources is not None and self.package_service is not None:
            existing_sources = self._package_sources()
            sources = []
            for source in package_sources:
                match = next((entry for entry in existing_sources if entry.get("url") == source["url"]
                              and (not source["username"] or entry.get("username", "") == source["username"])), {})
                sources.append({"id": match.get("id") or uuid.uuid4().hex, "url": source["url"],
                                "username": source["username"] or match.get("username", ""), "has_password": bool(match.get("has_password", False))})
            changes[self.package_service.config] = _json_bytes({"sources": sources})
        changes[self.catalog.path] = _json_bytes(catalog_data)
        backups = {path: path.read_bytes() if path.exists() else None for path in changes}
        previous_data = self.catalog.list()
        committed = []
        try:
            for path, raw in changes.items():
                self._write(path, raw)
                committed.append(path)
            self.catalog.data = deepcopy(catalog_data)
        except BaseException:
            for path in reversed(committed):
                if backups[path] is None:
                    path.unlink(missing_ok=True)
                else:
                    self._write(path, backups[path])
            self.catalog.data = previous_data
            raise
        response["catalog"] = self.catalog.list()
        response["imported_connections"] = response["connections"]
        if notifications is not None:
            response["notification_settings"] = notifications
        if snapshots is not None:
            response["snapshot_settings"] = snapshots
        return response

    def export_folder(self, params):
        target = _path(params.get("path"))
        if target == self.workspace or self.workspace in target.parents or target in self.workspace.parents:
            raise ValueError("Configuration export must be outside the active Tauri workspace")
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError("Choose an empty or new folder for configuration export")
        blobs = {}
        if self.archive.exists():
            for entry in sorted(self.archive.iterdir()):
                if entry.is_file() and not entry.is_symlink():
                    blobs[entry.name] = entry.read_bytes()
        def name_for(lower):
            return next((name for name in blobs if name.lower() == lower), None)
        blobs[name_for("connections.json") or "connections.json"] = _json_bytes(self.catalog.export_document())
        preferences = _preferences(params.get("preferences", {}))
        defaults = merge_defaults(load_defaults(self.workspace), normalize_defaults(params.get("defaults", {})))
        main_name = name_for("datapyn.ini") or "DataPyn.ini"
        updates = {key: preferences[field] for key, (field, _) in PREFERENCE_KEYS.items() if field in preferences}
        for filename, mapper in (("notifications.json", _notification_keys), ("snapshot_settings.json", lambda value: {
            "session_results/enabled": value.get("enabled", False), "session_results/max_size_mb": value.get("max_size_mb", 50)})):
            path = self.workspace / filename
            if path.is_file():
                updates.update(mapper(_json(path.read_bytes(), filename)))
        if updates:
            blobs[main_name] = patch_ini(blobs.get(main_name, b""), updates)
        if "aiAutocomplete" in preferences:
            name = name_for("pyniasettings.ini") or "PyniaSettings.ini"
            blobs[name] = patch_ini(blobs.get(name, b""), {"autocomplete_enabled": preferences["aiAutocomplete"]})
        if "export_settings" in defaults:
            name = name_for("csvexport.ini") or "CSVExport.ini"
            updates = {"header" if key == "include_header" else key: value for key, value in defaults["export_settings"].items()}
            blobs[name] = patch_ini(blobs.get(name, b""), updates)
        if any(key in defaults for key in ("copy_separator", "copy_null_display", "export_open_folder")):
            name = name_for("exportsettings.ini") or "ExportSettings.ini"
            updates = {native: defaults[field] for field, native in (("copy_separator", "copy_separator"), ("copy_null_display", "null_display"),
                       ("export_open_folder", "open_folder")) if field in defaults}
            blobs[name] = patch_ini(blobs.get(name, b""), updates)
        if "pynia" in defaults:
            name = name_for("pyniasettings.ini") or "PyniaSettings.ini"
            updates = {key: value for key, value in defaults["pynia"].items() if key != "agent_prefs"}
            for agent, settings in defaults["pynia"].get("agent_prefs", {}).items():
                updates.update({f"agent_prefs/{agent}/{key}": value for key, value in settings.items()})
            blobs[name] = patch_ini(blobs.get(name, b""), updates)
        if self.package_service is not None:
            name = name_for("packagemanager.ini") or "PackageManager.ini"
            urls = []
            for source in self._package_sources():
                parts = urlsplit(source["url"])
                urls.append(urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, parts.query, parts.fragment)))
            blobs[name] = patch_ini(blobs.get(name, b""), {"extra_index_urls": urls})
        if preferences or defaults:
            name = name_for("tauri-settings.json") or "tauri-settings.json"
            portable = _json(blobs[name], name) if name in blobs else {"version": 1}
            portable["preferences"] = {**portable.get("preferences", {}), **preferences}
            if defaults:
                portable["defaults"] = defaults
            blobs[name] = _json_bytes(without_secrets(portable))
        if params.get("shortcuts") is not None:
            name = name_for("shortcuts.json") or "shortcuts.json"
            prior = _json(blobs[name], name) if name in blobs else {}
            blobs[name] = _json_bytes(without_secrets(shortcuts_to_document(prior, params["shortcuts"])))
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".datapyn-config-", dir=target.parent))
        try:
            for name, raw in blobs.items():
                self._write(stage / name, raw)
            existed = target.exists()
            if existed:
                target.rmdir()  # Verified empty above; concurrent additions prevent this operation.
            try:
                os.replace(stage, target)
            except BaseException:
                if existed:
                    target.mkdir(exist_ok=True)
                raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return {"path": str(target), "files": [{"name": name, "category": CATEGORIES.get(name.lower(), "preserved_extension"), "bytes": len(raw)} for name, raw in blobs.items()],
                "warnings": [REGISTRY_WARNING], "passwords_included": False, "connection_count": len(self.catalog.data["connections"])}

    def dispatch(self, method, params):
        with self.catalog._lock:
            if method == "configurations.inspect":
                return self.inspect(params)
            if method == "configurations.import":
                return self.import_folder(params)
            if method == "configurations.export":
                return self.export_folder(params)
            if method == "configurations.defaults.get":
                return {"defaults": load_defaults(self.workspace)}
            raise ValueError(f"Unknown configuration transfer method: {method}")
