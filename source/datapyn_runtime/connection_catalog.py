"""Preview-owned connection catalog. Credentials live in the OS keyring only."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid

SECRET_KEYS = {"password", "token", "access_token", "client_secret"}
DATABASE_TYPES = {"sqlite", "sqlserver", "postgresql", "mysql", "mariadb", "databricks"}


class CredentialStore:
    service = "DataPyn.Tauri.Preview.Connections"

    def get(self, identifier):
        import keyring
        value = keyring.get_password(self.service, identifier)
        return json.loads(value) if value else {}

    def set(self, identifier, secrets):
        import keyring
        if secrets:
            keyring.set_password(self.service, identifier, json.dumps(secrets))
        else:
            self.delete(identifier)

    def delete(self, identifier):
        import keyring
        from keyring.errors import PasswordDeleteError
        try:
            keyring.delete_password(self.service, identifier)
        except PasswordDeleteError:
            pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value, name, *, empty=False):
    if not isinstance(value, str) or len(value) > 256 or (not value.strip() and not empty):
        raise ValueError(f"{name} must be a string of at most 256 characters")
    return value.strip()


def _path(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 32768:
        raise ValueError("path must be a nonempty filesystem path")
    return Path(value).expanduser().resolve()


def without_secrets(value):
    """Keep extension metadata, while never transferring credential fields."""
    if isinstance(value, dict):
        return {key: without_secrets(item) for key, item in value.items() if str(key).lower() not in SECRET_KEYS}
    if isinstance(value, list):
        return [without_secrets(item) for item in value]
    return deepcopy(value)


class ConnectionCatalog:
    def __init__(self, path=None, credentials=None):
        root = Path(os.environ.get("DATAPYN_WORKSPACE_PATH") or os.environ.get("DATAPYN_RUNTIME_STATE_PATH") or Path.home() / ".datapyn-tauri-preview")
        self.path = Path(path) if path else root / "connections.json"
        self.credentials = credentials or CredentialStore()
        self._lock = threading.RLock()
        self._defer_save = False
        self.data = {"version": 1, "groups": [], "connections": []}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if data.get("version") != 1 or not isinstance(data.get("connections"), list) or not isinstance(data.get("groups"), list):
                raise ValueError("Unsupported preview connection catalog")
            self.data = data

    def _save(self):
        if self._defer_save:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(self.data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def list(self):
        with self._lock:
            return deepcopy(self.data)

    def _find(self, collection, identifier):
        item = next((entry for entry in self.data[collection] if entry["id"] == identifier), None)
        if item is None:
            raise KeyError(f"Unknown {collection[:-1]}: {identifier}")
        return item

    def _group(self, group_id):
        if group_id:
            self._find("groups", group_id)
        return group_id or None

    def config(self, identifier):
        with self._lock:
            item = self._find("connections", identifier)
            result = deepcopy(item["config"])
            if item.get("has_password"):
                result.update(self.credentials.get(identifier))
            return result

    def resolve_ref(self, group, name):
        with self._lock:
            groups = {g["id"]: g["name"] for g in self.data["groups"]}
            matches = [c for c in self.data["connections"] if c["name"] == name
                       and (group is None or groups.get(c.get("group_id"), "") == group)]
            if len(matches) != 1:
                raise ValueError(f"Connection reference is missing or ambiguous: {group or ''}/{name}")
            return matches[0]["id"]

    def mark_used(self, identifier):
        with self._lock:
            self._find("connections", identifier)["last_used"] = _now()
            self._save()

    def save_connection(self, connection, *, password=None, save_password=None, case_sensitive=False):
        if not isinstance(connection, dict) or not isinstance(connection.get("config"), dict):
            raise ValueError("connection and config must be objects")
        with self._lock:
            existing = self._find("connections", connection["id"]) if connection.get("id") else None
            identifier = existing["id"] if existing else uuid.uuid4().hex
            name = _text(connection.get("name"), "name")
            if case_sensitive:
                name = connection["name"]
            group_id = self._group(connection.get("group_id"))
            if any(c["id"] != identifier and c["name"] == name
                   and c.get("group_id") == group_id for c in self.data["connections"]):
                raise ValueError("A connection with this name already exists in this group")
            config = deepcopy(existing["config"]) if existing else {}
            config.update(deepcopy(connection["config"]))
            db_type = str(config.get("db_type", "")).lower()
            if db_type not in DATABASE_TYPES:
                raise ValueError("Unsupported database type")
            config["db_type"] = db_type
            config.pop("workspace_path", None)  # A saved profile cannot redirect application storage.
            secrets = {key: str(config.pop(key)) for key in SECRET_KEYS if config.get(key) is not None}
            for key in SECRET_KEYS:
                config.pop(key, None)
            if password is not None:
                secrets["password"] = str(password)
            if db_type == "postgresql":
                config["schema"] = str(config.get("schema") or "public")
            item = without_secrets({**(existing or {}), **connection})
            item.update({
                "id": identifier, "name": name, "group_id": group_id,
                "color": str(connection.get("color", "")), "favorite": bool(connection.get("favorite", False)),
                "order": connection.get("order", existing.get("order", 0) if existing else len(self.data["connections"])),
                "config": config, "has_password": bool(existing and existing.get("has_password")),
                "created_at": connection.get("created_at", existing.get("created_at", _now()) if existing else _now()),
                "last_used": connection.get("last_used", existing.get("last_used") if existing else None),
            })
            if save_password is True and secrets:
                self.credentials.set(identifier, secrets)
                item["has_password"] = True
            elif save_password is False:
                if item["has_password"]:
                    self.credentials.delete(identifier)
                item["has_password"] = False
            if existing:
                existing.clear()
                existing.update(item)
            else:
                self.data["connections"].append(item)
            self._save()
            return deepcopy(item)

    def save_group(self, group, *, case_sensitive=False):
        if not isinstance(group, dict):
            raise ValueError("group must be an object")
        with self._lock:
            existing = self._find("groups", group["id"]) if group.get("id") else None
            identifier = existing["id"] if existing else uuid.uuid4().hex
            name = _text(group.get("name"), "group name")
            if case_sensitive:
                name = group["name"]
            parent = self._group(group.get("parent_id"))
            ancestor = parent
            while ancestor:
                if ancestor == identifier:
                    raise ValueError("A group cannot contain itself or one of its ancestors")
                ancestor = self._find("groups", ancestor).get("parent_id")
            if any(g["id"] != identifier and g["name"] == name for g in self.data["groups"]):
                raise ValueError("A group with this name already exists; PyQt6 group names must be globally unique")
            item = without_secrets({**(existing or {}), **group})
            item.update({"id": identifier, "name": name, "parent_id": parent,
                    "color": str(group.get("color", "")),
                    "order": group.get("order", existing.get("order", 0) if existing else len(self.data["groups"]))})
            if existing:
                existing.clear()
                existing.update(item)
            else:
                self.data["groups"].append(item)
            self._save()
            return deepcopy(item)

    def dispatch(self, method, params):
        with self._lock:
            if method == "connections.list":
                return self.list()
            if method == "connections.save":
                return self.save_connection(params.get("connection"), password=params.get("password"), save_password=params.get("save_password"))
            if method == "groups.save":
                return self.save_group(params.get("group"))
            if method == "connections.delete":
                item = self._find("connections", params.get("connection_id"))
                if item.get("has_password"):
                    self.credentials.delete(item["id"])
                self.data["connections"].remove(item)
            elif method in {"connections.clone", "connections.move"}:
                source = self._find("connections", params.get("connection_id"))
                item = deepcopy(source)
                item["group_id"] = params.get("group_id", source.get("group_id"))
                if method == "connections.clone":
                    item.pop("id")
                    item["name"] = params.get("name") or f"{source['name']} copy"
                    secrets = self.credentials.get(source["id"]) if source.get("has_password") else {}
                    item["config"].update(secrets)
                    return self.save_connection(item, save_password=bool(secrets))
                item["name"] = params.get("name", source["name"])
                return self.save_connection(item)
            elif method == "connections.reorder":
                for collection, key in (("connections", "connection_ids"), ("groups", "group_ids")):
                    identifiers = params.get(key)
                    if identifiers is None:
                        continue
                    if not isinstance(identifiers, list) or len(set(identifiers)) != len(identifiers):
                        raise ValueError(f"{key} must contain unique IDs")
                    known = {item["id"] for item in self.data[collection]}
                    if set(identifiers) - known:
                        raise ValueError(f"{key} contains unknown IDs")
                    order = identifiers + [item["id"] for item in self.data[collection] if item["id"] not in identifiers]
                    for index, identifier in enumerate(order):
                        self._find(collection, identifier)["order"] = index
            elif method == "groups.delete":
                group = self._find("groups", params.get("group_id"))
                parent = group.get("parent_id")
                moving = [c for c in self.data["connections"] if c.get("group_id") == group["id"]]
                destination = {c["name"].casefold() for c in self.data["connections"] if c.get("group_id") == parent}
                for item in moving:
                    base, candidate, suffix = item["name"], item["name"], 2
                    while candidate.casefold() in destination:
                        candidate = f"{base} ({suffix})"
                        suffix += 1
                    item["name"], item["group_id"] = candidate, parent
                    destination.add(candidate.casefold())
                for child in self.data["groups"]:
                    if child.get("parent_id") == group["id"]:
                        child["parent_id"] = parent
                self.data["groups"].remove(group)
            elif method == "connections.import":
                return self.import_file(params.get("path"))
            elif method == "connections.export":
                path = _path(params.get("path"))
                if path == self.path.resolve():
                    raise ValueError("Export cannot overwrite the active connection catalog")
                format_name = params.get("format", "pyqt6")
                if format_name not in {"pyqt6", "tauri"}:
                    raise ValueError("Connection export format must be pyqt6 or tauri")
                document = self.export_document(format_name)
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    try:
                        json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
                        stream.flush()
                        os.fsync(stream.fileno())
                    except BaseException:
                        temporary.unlink(missing_ok=True)
                        raise
                try:
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
                return {"path": str(path), "format": format_name, "connection_count": len(self.data["connections"]), "passwords_included": False}
            else:
                raise ValueError(f"Unknown catalog method: {method}")
            self._save()
            return self.list()

    def export_document(self, format_name="pyqt6"):
        with self._lock:
            if format_name == "tauri":
                result = without_secrets(self.data)
                for item in result["connections"]:
                    item["has_password"] = False
                return result
            groups = {group["id"]: group for group in self.data["groups"]}
            names = [group["name"] for group in groups.values()]
            if len(set(names)) != len(names):
                raise ValueError("PyQt6 requires globally unique group names; use the Tauri format for these folders")
            result = without_secrets(self.data.get("legacy_metadata", {}))
            result["connections"], result["groups"] = {}, {}
            buckets = result["connections"]
            for item in sorted(self.data["connections"], key=lambda entry: entry.get("order", 0)):
                group = groups.get(item.get("group_id"))
                group_name = group["name"] if group else ""
                config = without_secrets(item["config"])
                config.setdefault("host", "")
                config.setdefault("port", 1433)
                config.setdefault("database", "")
                config.setdefault("username", "")
                config.update(group=group_name, color=item.get("color", ""))
                for key in ("favorite", "order", "created_at", "last_used"):
                    config[key] = deepcopy(item.get(key))
                buckets.setdefault(group_name, {})[item["name"]] = config
            for group in sorted(groups.values(), key=lambda entry: entry.get("order", 0)):
                config = without_secrets(group.get("legacy_metadata", {}))
                parent = groups.get(group.get("parent_id"))
                config.update(color=group.get("color", ""), parent=parent["name"] if parent else config.get("parent", ""))
                config["order"] = group.get("order", 0)
                if "created_at" in group:
                    config["created_at"] = deepcopy(group["created_at"])
                result["groups"][group["name"]] = config
                if group.get("legacy_bucket"):
                    buckets.setdefault(group["name"], {})
            if self.data.get("legacy_ungrouped_bucket"):
                buckets.setdefault("", {})
            # The legacy dialog detects nesting from the first bucket. Place an
            # occupied bucket first so it can also import exports with empty groups.
            result["connections"] = dict(sorted(buckets.items(), key=lambda entry: not bool(entry[1]))) if self.data["connections"] else {}
            return result

    def import_file(self, path):
        path = _path(path)
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Connection import exceeds 8 MiB")
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        return self.import_document(document, path=str(path))

    def import_document(self, document, *, path=None):
        with self._lock:
            before = deepcopy(self.data)
            self._defer_save = True
            try:
                result, credentials_to_remove = self._import_document(document)
            except BaseException:
                self.data = before
                raise
            finally:
                self._defer_save = False
                self._save()
            for identifier in credentials_to_remove:
                self.credentials.delete(identifier)
            result["path"] = path
            return result

    def _import_document(self, document):
        if not isinstance(document, dict):
            raise ValueError("Connection import must be a JSON object")
        groups, profiles = [], []
        if isinstance(document.get("connections"), list):
            groups = document.get("groups", [])
            profiles = document["connections"]
            if not isinstance(groups, list):
                raise ValueError("Imported groups must be an array")
            self.data["legacy_metadata"] = without_secrets(document.get("legacy_metadata", self.data.get("legacy_metadata", {})))
            self.data["legacy_ungrouped_bucket"] = bool(document.get("legacy_ungrouped_bucket", False))
        else:
            source = document.get("connections", document)
            legacy_groups = document.get("groups", {})
            if not isinstance(source, dict) or not isinstance(legacy_groups, dict):
                raise ValueError("Legacy connections and groups must be objects")
            self.data.setdefault("legacy_metadata", {}).update(without_secrets({key: value for key, value in document.items()
                if key not in {"connections", "groups", "version"}}) if "connections" in document else {})
            for name, config in legacy_groups.items():
                if not isinstance(config, dict):
                    raise ValueError("Group metadata must be an object")
                groups.append({"id": name, "name": name, "parent_id": config.get("parent") or None,
                               "color": config.get("color", ""), "order": config.get("order", len(groups)),
                               **({"created_at": config["created_at"]} if "created_at" in config else {}),
                               "legacy_metadata": without_secrets(config)})
            flat = any(isinstance(value, dict) and "db_type" in value for value in source.values())
            if flat:
                for name, config in source.items():
                    if not isinstance(config, dict) or "db_type" not in config:
                        raise ValueError("Flat imports must contain connection objects")
                    profiles.append({"name": name, "group_id": config.get("group") or None, "config": config,
                                     "color": config.get("color", ""), "favorite": config.get("favorite", False)})
            else:
                for group, bucket in source.items():
                    if not isinstance(bucket, dict):
                        raise ValueError("Connection groups must contain objects")
                    if not group:
                        self.data["legacy_ungrouped_bucket"] = True
                    elif not any(item["id"] == group for item in groups):
                        groups.append({"id": group, "name": group, "legacy_bucket": True})
                    else:
                        next(item for item in groups if item["id"] == group)["legacy_bucket"] = True
                    for name, config in bucket.items():
                        if not isinstance(config, dict) or "db_type" not in config:
                            raise ValueError("Imported connections must include db_type")
                        profiles.append({"name": name, "group_id": group or config.get("group") or None, "config": config,
                                         "color": config.get("color", ""), "favorite": config.get("favorite", False)})
            present = {g["id"] for g in groups}
            for profile in profiles:
                group = profile.get("group_id")
                if group and group not in present:
                    groups.append({"id": group, "name": group})
                    present.add(group)
        if any(not isinstance(group, dict) for group in groups) or any(not isinstance(profile, dict) for profile in profiles):
            raise ValueError("Imported groups and connections must be objects")
        mapping = {}
        pending = list(groups)
        while pending:
            progressed = False
            for group in list(pending):
                parent = group.get("parent_id")
                if parent and parent not in mapping:
                    continue
                match = next((g for g in self.data["groups"] if g["name"] == group["name"]), None)
                incoming = deepcopy(group)
                incoming.pop("id", None)
                incoming["parent_id"] = mapping.get(parent)
                if match:
                    incoming["id"] = match["id"]
                saved = self.save_group(incoming, case_sensitive=True)
                mapping[group.get("id", group["name"])] = saved["id"]
                pending.remove(group)
                progressed = True
            if not progressed:
                raise ValueError("Imported groups have invalid parents or a cycle")
        count = 0
        credentials_to_remove = []
        for profile in profiles:
            profile = without_secrets(profile)
            profile.pop("id", None)
            original_group = profile.get("group_id")
            if original_group and original_group not in mapping:
                raise ValueError("Imported connection references an unknown group")
            profile["group_id"] = mapping.get(original_group)
            config = profile.get("config")
            if not isinstance(config, dict):
                raise ValueError("Imported connection config must be an object")
            for key in ("created_at", "last_used", "order"):
                if key in config and key not in profile:
                    profile[key] = deepcopy(config[key])
            match = next((entry for entry in self.data["connections"] if entry["name"] == profile.get("name")
                          and entry.get("group_id") == profile["group_id"]), None)
            if match:
                profile["id"] = match["id"]
                if match.get("has_password"):
                    credentials_to_remove.append(match["id"])
            saved = self.save_connection(profile, case_sensitive=True)
            self._find("connections", saved["id"])["has_password"] = False
            count += 1
        return {"catalog": self.list(), "imported_connections": count, "passwords_imported": False}, credentials_to_remove
