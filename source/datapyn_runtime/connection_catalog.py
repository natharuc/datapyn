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

    def save_connection(self, connection, *, password=None, save_password=None):
        if not isinstance(connection, dict) or not isinstance(connection.get("config"), dict):
            raise ValueError("connection and config must be objects")
        with self._lock:
            existing = self._find("connections", connection["id"]) if connection.get("id") else None
            identifier = existing["id"] if existing else uuid.uuid4().hex
            name = _text(connection.get("name"), "name")
            group_id = self._group(connection.get("group_id"))
            if any(c["id"] != identifier and c["name"].casefold() == name.casefold()
                   and c.get("group_id") == group_id for c in self.data["connections"]):
                raise ValueError("A connection with this name already exists in this group")
            config = deepcopy(connection["config"])
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
            item = {
                "id": identifier, "name": name, "group_id": group_id,
                "color": str(connection.get("color", "")), "favorite": bool(connection.get("favorite", False)),
                "order": existing.get("order", 0) if existing else len(self.data["connections"]),
                "config": config, "has_password": bool(existing and existing.get("has_password")),
                "created_at": existing.get("created_at", _now()) if existing else _now(),
                "last_used": existing.get("last_used") if existing else None,
            }
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

    def save_group(self, group):
        if not isinstance(group, dict):
            raise ValueError("group must be an object")
        with self._lock:
            existing = self._find("groups", group["id"]) if group.get("id") else None
            identifier = existing["id"] if existing else uuid.uuid4().hex
            name = _text(group.get("name"), "group name")
            parent = self._group(group.get("parent_id"))
            ancestor = parent
            while ancestor:
                if ancestor == identifier:
                    raise ValueError("A group cannot contain itself or one of its ancestors")
                ancestor = self._find("groups", ancestor).get("parent_id")
            if any(g["id"] != identifier and g["name"].casefold() == name.casefold()
                   and g.get("parent_id") == parent for g in self.data["groups"]):
                raise ValueError("A group with this name already exists in this folder")
            item = {"id": identifier, "name": name, "parent_id": parent,
                    "color": str(group.get("color", "")),
                    "order": existing.get("order", 0) if existing else len(self.data["groups"])}
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
                path = Path(_text(params.get("path"), "path")).expanduser().resolve()
                if path == self.path.resolve():
                    raise ValueError("Export cannot overwrite the active connection catalog")
                document = self.list()
                for item in document["connections"]:
                    item["has_password"] = False
                path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
                return {"path": str(path), "connection_count": len(document["connections"]), "passwords_included": False}
            else:
                raise ValueError(f"Unknown catalog method: {method}")
            self._save()
            return self.list()

    def import_file(self, path):
        with self._lock:
            before = deepcopy(self.data)
            self._defer_save = True
            try:
                result = self._import_file(path)
            except BaseException:
                old_ids = {item["id"] for item in before["connections"]}
                for item in self.data["connections"]:
                    if item["id"] not in old_ids and item.get("has_password"):
                        try:
                            self.credentials.delete(item["id"])
                        except Exception:
                            pass
                self.data = before
                raise
            finally:
                self._defer_save = False
                self._save()
            return result

    def _import_file(self, path):
        path = Path(_text(path, "path")).expanduser().resolve()
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Connection import exceeds 8 MiB")
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError("Connection import must be a JSON object")
        groups, profiles = [], []
        if isinstance(document.get("connections"), list):
            groups = document.get("groups", [])
            profiles = document["connections"]
        else:
            source = document.get("connections", document)
            legacy_groups = document.get("groups", {})
            groups = [{"id": name, "name": name, "parent_id": config.get("parent") or None,
                       "color": config.get("color", "")} for name, config in legacy_groups.items()]
            if source and all(isinstance(value, dict) and "db_type" in value for value in source.values()):
                for name, config in source.items():
                    profiles.append({"name": name, "group_id": config.get("group") or None, "config": config,
                                     "color": config.get("color", ""), "favorite": config.get("favorite", False)})
            else:
                for group, bucket in source.items():
                    if not isinstance(bucket, dict):
                        continue
                    for name, config in bucket.items():
                        if isinstance(config, dict) and "db_type" in config:
                            profiles.append({"name": name, "group_id": group or None, "config": config,
                                             "color": config.get("color", ""), "favorite": config.get("favorite", False)})
            present = {g["id"] for g in groups}
            for profile in profiles:
                group = profile.get("group_id")
                if group and group not in present:
                    groups.append({"id": group, "name": group})
                    present.add(group)
        # Validate into a fresh in-memory catalog before changing the current one.
        imported = deepcopy(self.data)
        mapping = {}
        pending = list(groups)
        while pending:
            progressed = False
            for group in list(pending):
                parent = group.get("parent_id")
                if parent and parent not in mapping:
                    continue
                match = next((g for g in self.data["groups"] if g["name"] == group["name"]
                              and g.get("parent_id") == mapping.get(parent)), None)
                saved = match or self.save_group({"name": group["name"], "color": group.get("color", ""), "parent_id": mapping.get(parent)})
                mapping[group.get("id", group["name"])] = saved["id"]
                pending.remove(group)
                progressed = True
            if not progressed:
                self.data = imported
                self._save()
                raise ValueError("Imported groups have invalid parents or a cycle")
        count = 0
        try:
            for profile in profiles:
                profile = deepcopy(profile)
                profile.pop("id", None)
                profile["group_id"] = mapping.get(profile.get("group_id"))
                name = str(profile.get("name", ""))
                names = {c["name"].casefold() for c in self.data["connections"] if c.get("group_id") == profile["group_id"]}
                suffix = 2
                while profile["name"].casefold() in names:
                    profile["name"] = f"{name} ({suffix})"
                    suffix += 1
                has_secret = any(profile.get("config", {}).get(key) for key in SECRET_KEYS)
                self.save_connection(profile, save_password=has_secret)
                count += 1
        except BaseException:
            added = {item["id"] for item in self.data["connections"]} - {item["id"] for item in imported["connections"]}
            for identifier in added:
                self.credentials.delete(identifier)
            self.data = imported
            self._save()
            raise
        return {"catalog": self.list(), "imported_connections": count, "path": str(path)}
