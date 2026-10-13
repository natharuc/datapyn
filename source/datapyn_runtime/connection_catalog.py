"""Tauri-owned connection catalog. Credentials live in the OS keyring only."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid

from .paths import workspace_root

SECRET_KEYS = {"password", "token", "access_token", "client_secret", "passphrase", "private_key",
               "sslpassword", "ssl_key_password"}
SSH_SECRET_KEYS = {"password", "passphrase"}
DATABASE_TYPES = {"sqlite", "sqlserver", "postgresql", "mysql", "mariadb", "databricks"}


class CredentialStore:
    service = "DataPyn.Tauri.Connections"

    @staticmethod
    def _backend():
        """Refuse file/plaintext fallbacks, including a chainer that can select one."""
        import keyring
        backend = keyring.get_keyring()
        secure_modules = {"keyring.backends.Windows", "keyring.backends.macOS",
                          "keyring.backends.SecretService", "keyring.backends.libsecret",
                          "keyring.backends.kwallet"}

        def secure(candidate):
            if type(candidate).__module__ == "keyring.backends.chainer":
                choices = list(candidate.backends)
                return bool(choices) and all(secure(choice) for choice in choices)
            return type(candidate).__module__ in secure_modules and candidate.priority > 0

        if not secure(backend):
            raise RuntimeError("Secure OS credential storage is unavailable; credentials were not saved or read")
        return backend

    def get(self, identifier):
        value = self._backend().get_password(self.service, identifier)
        return json.loads(value) if value else {}

    def set(self, identifier, secrets):
        if secrets:
            self._backend().set_password(self.service, identifier, json.dumps(secrets))
        else:
            self.delete(identifier)

    def delete(self, identifier):
        from keyring.errors import PasswordDeleteError
        try:
            self._backend().delete_password(self.service, identifier)
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
        return {key: without_secrets(item) for key, item in value.items()
                if str(key).lower() not in SECRET_KEYS and key not in {"_ssh_trust_path", "_ssh_catalog_path", "_tunnel_revision"}}
    if isinstance(value, list):
        return [without_secrets(item) for item in value]
    return deepcopy(value)


def ssh_identity(config):
    """Credentials belong to one SSH endpoint, account and authentication method."""
    ssh = config.get("ssh") or {}
    return (str(ssh.get("host") or "").strip().casefold(), int(ssh.get("port") or 22),
            str(ssh.get("username") or "").strip(), ssh.get("auth_method") or "password",
            str(ssh.get("private_key_path") or "") if ssh.get("auth_method") == "private_key" else "")


def normalized_ssh(value):
    if not isinstance(value, dict):
        raise ValueError("ssh must be an object")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("SSH enabled must be a boolean")
    result = without_secrets(value)
    result.pop("_identity", None)
    result["enabled"] = enabled
    port = value.get("port", 22)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("SSH port must be between 1 and 65535")
    result["port"] = port
    result["auth_method"] = value.get("auth_method", "password")
    if result["auth_method"] not in {"password", "private_key"}:
        raise ValueError("SSH authentication must be password or private_key")
    for name in ("host", "username"):
        result[name] = _text(value.get(name, ""), f"SSH {name}", empty=not enabled)
    if enabled and result["auth_method"] == "private_key":
        path = value.get("private_key_path")
        if not isinstance(path, str) or not path.strip() or len(path) > 32768:
            raise ValueError("SSH private key path is required")
        result["private_key_path"] = path
    return result


class ConnectionCatalog:
    def __init__(self, path=None, credentials=None):
        root = workspace_root()
        self.path = Path(path) if path else root / "connections.json"
        self.credentials = credentials or CredentialStore()
        self._lock = threading.RLock()
        self._defer_save = False
        self.data = {"version": 1, "groups": [], "connections": [], "ssh_tunnels": []}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if data.get("version") != 1 or not isinstance(data.get("connections"), list) or not isinstance(data.get("groups"), list):
                raise ValueError("Unsupported preview connection catalog")
            self.data = without_secrets(data)
            self.data.setdefault("ssh_tunnels", [])
            if not isinstance(self.data["ssh_tunnels"], list):
                raise ValueError("SSH tunnels must be an array")
            self._migrate_inline_tunnels()

    @staticmethod
    def tunnel_credential_id(identifier):
        return f"tunnel:{identifier}:ssh"

    def tunnel_config(self, identifier, *, resolve_credentials=True):
        """Read the current endpoint; a deleted reference never becomes direct TCP."""
        from .ssh_tunnel import SshTunnelError
        if not isinstance(identifier, str) or not identifier or len(identifier) > 128:
            raise SshTunnelError("Selecione um túnel SSH cadastrado.", code="ssh_tunnel_missing")
        with self._lock:
            try:
                item = self._find("ssh_tunnels", identifier)
            except KeyError:
                raise SshTunnelError("O túnel SSH desta conexão não existe. Selecione outro túnel nas configurações.",
                                     code="ssh_tunnel_missing") from None
            config = normalized_ssh({**item["config"], "enabled": True})
            config["_tunnel_revision"] = item.get("updated_at", item.get("created_at", ""))
            if resolve_credentials and (item.get("has_password") or item.get("has_passphrase")):
                secrets = self.credentials.get(self.tunnel_credential_id(identifier))
                if tuple(secrets.get("_identity") or ()) == ssh_identity({"ssh": config}):
                    config.update({key: secrets[key] for key in SSH_SECRET_KEYS if secrets.get(key)})
            return config

    def resolve_ssh(self, config, *, resolve_credentials=True):
        result = deepcopy(config)
        if "ssh_tunnel_id" not in result:
            return result  # Compatibility for unsaved pre-catalog drafts.
        result.pop("ssh", None)
        identifier = result.get("ssh_tunnel_id")
        if identifier is None or identifier == "":
            result["ssh_tunnel_id"] = None
            return result
        if result.get("db_type") not in {"postgresql", "mysql", "mariadb", "sqlserver"}:
            raise ValueError("SSH tunnels support PostgreSQL, MySQL, MariaDB and SQL Server connections")
        result["ssh"] = self.tunnel_config(identifier, resolve_credentials=resolve_credentials)
        return result

    def save_tunnel(self, tunnel, *, password=None, passphrase=None, save_credentials=None):
        if not isinstance(tunnel, dict) or not isinstance(tunnel.get("config"), dict):
            raise ValueError("tunnel and config must be objects")
        if save_credentials is not None and not isinstance(save_credentials, bool):
            raise ValueError("save_credentials must be a boolean")
        with self._lock:
            existing = self._find("ssh_tunnels", tunnel["id"]) if tunnel.get("id") else None
            identifier = existing["id"] if existing else uuid.uuid4().hex
            name = _text(tunnel.get("name"), "tunnel name")
            if any(item["id"] != identifier and item["name"].casefold() == name.casefold()
                   for item in self.data["ssh_tunnels"]):
                raise ValueError("A tunnel with this name already exists")
            raw = {**(existing["config"] if existing else {}), **deepcopy(tunnel["config"]), "enabled": True}
            config = normalized_ssh(raw)
            identity = ssh_identity({"ssh": config})
            same = bool(existing and ssh_identity({"ssh": existing["config"]}) == identity)
            secret_key = "password" if config["auth_method"] == "password" else "passphrase"
            supplied = password if secret_key == "password" else passphrase
            if supplied is None:
                supplied = raw.get(secret_key)
            present = bool(existing and (existing.get("has_password") or existing.get("has_passphrase")))
            changes = bool(supplied and save_credentials is not False or present and (not same or save_credentials is False))
            secrets = {secret_key: str(supplied), "_identity": list(identity)} if supplied and save_credentials is not False else {}
            item = {"id": identifier, "name": name, "config": config,
                    "has_password": bool(same and existing.get("has_password")),
                    "has_passphrase": bool(same and existing.get("has_passphrase")),
                    "created_at": existing.get("created_at", _now()) if existing else _now(), "updated_at": _now()}
            if changes:
                item["has_password"] = bool(secrets.get("password"))
                item["has_passphrase"] = bool(secrets.get("passphrase"))
            if self._defer_save:
                item["has_password"] = item["has_passphrase"] = False
            before = deepcopy(self.data)
            credential_id = self.tunnel_credential_id(identifier)
            previous = None
            try:
                if changes and not self._defer_save:
                    previous = self.credentials.get(credential_id) if present else {}
                    self.credentials.set(credential_id, secrets)
                if existing:
                    existing.clear()
                    existing.update(item)
                else:
                    self.data["ssh_tunnels"].append(item)
                self._save()
            except BaseException:
                self.data = before
                if previous is not None:
                    self.credentials.set(credential_id, previous)
                raise
            return deepcopy(item)

    def _migrate_inline_tunnels(self):
        """Move existing credentials atomically, keeping different accounts/passwords distinct."""
        before = deepcopy(self.data)
        updates, removed, changed = [], [], False
        try:
            for connection in self.data["connections"]:
                config = connection.get("config") or {}
                if "ssh_tunnel_id" in config or not (config.get("ssh") or {}).get("enabled"):
                    continue
                public = normalized_ssh(config["ssh"])
                secrets = {}
                if connection.get("has_ssh_password") or connection.get("has_ssh_passphrase"):
                    old_key = f"{connection['id']}:ssh"
                    saved = self.credentials.get(old_key)
                    if tuple(saved.get("_identity") or ()) == ssh_identity(config):
                        secrets = {key: saved[key] for key in SSH_SECRET_KEYS if saved.get(key)}
                    removed.append(old_key)
                match = None
                for tunnel in self.data["ssh_tunnels"]:
                    if tunnel["config"] != public:
                        continue
                    if self._defer_save and (tunnel.get("has_password") or tunnel.get("has_passphrase")):
                        continue  # Import previews never consult the OS keyring.
                    current = self.tunnel_config(tunnel["id"])
                    if {key: current[key] for key in SSH_SECRET_KEYS if current.get(key)} == secrets:
                        match = tunnel
                        break
                if match is None:
                    name = f"{public['username']}@{public['host']}"[:240]
                    base, suffix = name, 2
                    while any(item["name"].casefold() == name.casefold() for item in self.data["ssh_tunnels"]):
                        name, suffix = f"{base} ({suffix})", suffix + 1
                    match = {"id": uuid.uuid4().hex, "name": name, "config": public,
                             "has_password": bool(secrets.get("password")), "has_passphrase": bool(secrets.get("passphrase")),
                             "created_at": _now(), "updated_at": _now()}
                    key = self.tunnel_credential_id(match["id"])
                    if secrets:
                        updates.append(key)
                        self.credentials.set(key, {**secrets, "_identity": list(ssh_identity(config))})
                    self.data["ssh_tunnels"].append(match)
                config.pop("ssh", None)
                config["ssh_tunnel_id"] = match["id"]
                connection["has_ssh_password"] = connection["has_ssh_passphrase"] = False
                changed = True
            if changed:
                self._save()
        except BaseException:
            self.data = before
            for key in reversed(updates):
                self.credentials.delete(key)
            raise
        for key in removed:
            self.credentials.delete(key)

    def _save(self):
        if self._defer_save:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(without_secrets(self.data), stream, ensure_ascii=False, indent=2, allow_nan=False)
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
            return without_secrets(self.data)

    def _find(self, collection, identifier):
        item = next((entry for entry in self.data[collection] if entry["id"] == identifier), None)
        if item is None:
            raise KeyError(f"Unknown {collection[:-1]}: {identifier}")
        return item

    def _group(self, group_id):
        if group_id:
            self._find("groups", group_id)
        return group_id or None

    def config(self, identifier, *, resolve_database_password=True, resolve_ssh_credentials=True):
        with self._lock:
            item = self._find("connections", identifier)
            result = deepcopy(item["config"])
            if resolve_database_password and item.get("has_password"):
                result.update(self.credentials.get(identifier))
            if resolve_ssh_credentials and (result.get("ssh") or {}).get("enabled") and (item.get("has_ssh_password") or item.get("has_ssh_passphrase")):
                saved = self.credentials.get(f"{identifier}:ssh")
                if tuple(saved.get("_identity") or ()) == ssh_identity(result):
                    result["ssh"].update({key: saved[key] for key in SSH_SECRET_KEYS if key in saved})
            return self.resolve_ssh(result, resolve_credentials=resolve_ssh_credentials)

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

    def save_connection(self, connection, *, password=None, save_password=None, ssh_password=None,
                        ssh_passphrase=None, save_ssh_credentials=None, case_sensitive=False):
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
            config.pop("_ssh_trust_path", None)
            config.pop("_ssh_catalog_path", None)
            if "ssh_tunnel_id" in config:
                # A reference is authoritative even if an older client sends an embedded copy.
                self.resolve_ssh(config, resolve_credentials=False)
                config.pop("ssh", None)
                config["ssh_tunnel_id"] = config.get("ssh_tunnel_id") or None
            secrets = {key: str(config.pop(key)) for key in SECRET_KEYS if config.get(key) is not None}
            for key in SECRET_KEYS:
                config.pop(key, None)
            if password is not None:
                secrets["password"] = str(password)
            if db_type == "postgresql":
                config["schema"] = str(config.get("schema") or "public")
            ssh_secrets = {}
            ssh_changes = False
            if "ssh" in config:
                raw_ssh = config["ssh"]
                config["ssh"] = normalized_ssh(raw_ssh)
                if config["ssh"]["enabled"] and db_type not in {"postgresql", "mysql", "mariadb", "sqlserver"}:
                    raise ValueError("SSH tunnels support PostgreSQL, MySQL, MariaDB and SQL Server connections")
                same_identity = bool(existing and ssh_identity(existing["config"]) == ssh_identity(config))
                supplied = {key: str(raw_ssh[key]) for key in SSH_SECRET_KEYS if raw_ssh.get(key)}
                if ssh_password:
                    supplied["password"] = str(ssh_password)
                if ssh_passphrase:
                    supplied["passphrase"] = str(ssh_passphrase)
                auth = config["ssh"]["auth_method"]
                supplied = {key: value for key, value in supplied.items()
                            if key == ("password" if auth == "password" else "passphrase")}
                if save_ssh_credentials is not None and not isinstance(save_ssh_credentials, bool):
                    raise ValueError("save_ssh_credentials must be a boolean")
                old_has_ssh = bool(existing and (existing.get("has_ssh_password") or existing.get("has_ssh_passphrase")))
                # Imports never read/write keyring until the whole document validates.
                if not self._defer_save and save_ssh_credentials is not False:
                    if same_identity and old_has_ssh and supplied:
                        ssh_secrets = self.credentials.get(f"{identifier}:ssh")
                    ssh_secrets.update(supplied)
                ssh_changes = bool(supplied and save_ssh_credentials is not False
                                   or old_has_ssh and (save_ssh_credentials is False or not same_identity))
                if ssh_secrets:
                    ssh_secrets["_identity"] = list(ssh_identity(config))
            item = without_secrets({**(existing or {}), **connection})
            item.update({
                "id": identifier, "name": name, "group_id": group_id,
                "color": str(connection.get("color", "")), "favorite": bool(connection.get("favorite", False)),
                "order": connection.get("order", existing.get("order", 0) if existing else len(self.data["connections"])),
                "config": config, "has_password": bool(existing and existing.get("has_password")),
                "has_ssh_password": False, "has_ssh_passphrase": False,
                "created_at": connection.get("created_at", existing.get("created_at", _now()) if existing else _now()),
                "last_used": connection.get("last_used", existing.get("last_used") if existing else None),
            })
            credential_updates = []
            if "ssh" in config and not self._defer_save:
                if ssh_changes:
                    credential_updates.append((f"{identifier}:ssh", ssh_secrets, old_has_ssh))
                    item["has_ssh_password"] = bool(ssh_secrets.get("password"))
                    item["has_ssh_passphrase"] = bool(ssh_secrets.get("passphrase"))
                elif existing:
                    item["has_ssh_password"] = bool(existing.get("has_ssh_password"))
                    item["has_ssh_passphrase"] = bool(existing.get("has_ssh_passphrase"))
            if save_password is True and secrets:
                credential_updates.append((identifier, secrets, item["has_password"]))
                item["has_password"] = True
            elif save_password is False:
                if item["has_password"]:
                    credential_updates.append((identifier, {}, True))
                item["has_password"] = False
            before = deepcopy(existing) if existing else None
            rollback = []
            try:
                for key, value, present in credential_updates:
                    previous = self.credentials.get(key) if present else {}
                    self.credentials.set(key, value)
                    rollback.append((key, previous))
                if existing:
                    existing.clear()
                    existing.update(item)
                else:
                    self.data["connections"].append(item)
                self._save()
            except BaseException:
                if existing:
                    existing.clear()
                    existing.update(before)
                elif item in self.data["connections"]:
                    self.data["connections"].remove(item)
                for key, previous in reversed(rollback):
                    self.credentials.set(key, previous)
                raise
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
            visited = set()
            while ancestor:
                if ancestor == identifier:
                    raise ValueError("A group cannot contain itself or one of its ancestors")
                if ancestor in visited:
                    raise ValueError("The destination group has an invalid parent cycle")
                visited.add(ancestor)
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
            if method == "ssh.tunnels.list":
                return {"ssh_tunnels": without_secrets(self.data["ssh_tunnels"])}
            if method == "ssh.tunnels.save":
                return self.save_tunnel(params.get("tunnel"), password=params.get("password"),
                                        passphrase=params.get("passphrase"), save_credentials=params.get("save_credentials"))
            if method == "ssh.tunnels.delete":
                tunnel = self._find("ssh_tunnels", params.get("tunnel_id"))
                names = [item["name"] for item in self.data["connections"]
                         if item.get("config", {}).get("ssh_tunnel_id") == tunnel["id"]]
                if names:
                    raise ValueError("O túnel está em uso pelas conexões: " + ", ".join(names[:8]))
                before = deepcopy(self.data)
                present = tunnel.get("has_password") or tunnel.get("has_passphrase")
                key = self.tunnel_credential_id(tunnel["id"])
                previous = self.credentials.get(key) if present else {}
                try:
                    if present:
                        self.credentials.delete(key)
                    self.data["ssh_tunnels"].remove(tunnel)
                    self._save()
                except BaseException:
                    self.data = before
                    if present:
                        self.credentials.set(key, previous)
                    raise
                return {"ssh_tunnels": without_secrets(self.data["ssh_tunnels"])}
            if method == "connections.list":
                return self.list()
            if method == "connections.export_config":
                include_password = params.get("include_password", False)
                if not isinstance(include_password, bool):
                    raise ValueError("include_password must be a boolean")
                item = self._find("connections", params.get("connection_id"))
                config = without_secrets(item["config"])
                included = False
                if include_password and item.get("has_password"):
                    # Explicit clipboard export only; do not save or mutate catalog data.
                    secrets = self.credentials.get(item["id"])
                    if secrets.get("password") is not None:
                        config["password"] = str(secrets["password"])
                        included = True
                return {"config": config, "password_included": included}
            if method == "connections.save":
                return self.save_connection(params.get("connection"), password=params.get("password"),
                                            save_password=params.get("save_password"),
                                            ssh_password=params.get("ssh_password"), ssh_passphrase=params.get("ssh_passphrase"),
                                            save_ssh_credentials=params.get("save_ssh_credentials"))
            if method == "groups.save":
                return self.save_group(params.get("group"))
            if method == "connections.delete":
                item = self._find("connections", params.get("connection_id"))
                if item.get("has_password"):
                    self.credentials.delete(item["id"])
                if item.get("has_ssh_password") or item.get("has_ssh_passphrase"):
                    self.credentials.delete(f"{item['id']}:ssh")
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
                    if source.get("has_ssh_password") or source.get("has_ssh_passphrase"):
                        ssh_secrets = self.credentials.get(f"{source['id']}:ssh")
                        if tuple(ssh_secrets.get("_identity") or ()) == ssh_identity(source["config"]):
                            item["config"]["ssh"].update({key: ssh_secrets[key] for key in SSH_SECRET_KEYS if key in ssh_secrets})
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
                    item["has_ssh_password"] = False
                    item["has_ssh_passphrase"] = False
                for tunnel in result["ssh_tunnels"]:
                    tunnel["has_password"] = tunnel["has_passphrase"] = False
                return result
            groups = {group["id"]: group for group in self.data["groups"]}
            names = [group["name"] for group in groups.values()]
            if len(set(names)) != len(names):
                raise ValueError("PyQt6 requires globally unique group names; use the Tauri format for these folders")
            result = without_secrets(self.data.get("legacy_metadata", {}))
            result["connections"], result["groups"] = {}, {}
            tunnels = without_secrets(self.data["ssh_tunnels"])
            if tunnels:
                for tunnel in tunnels:
                    tunnel["has_password"] = tunnel["has_passphrase"] = False
                result["ssh_tunnels"] = tunnels
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
        tunnels = document.get("ssh_tunnels", [])
        if not isinstance(tunnels, list):
            raise ValueError("Imported SSH tunnels must be an array")
        tunnel_mapping = {}
        for tunnel in tunnels:
            if not isinstance(tunnel, dict) or not isinstance(tunnel.get("config"), dict):
                raise ValueError("Imported SSH tunnels must contain config objects")
            original_id = tunnel.get("id")
            if not isinstance(original_id, str) or not original_id or original_id in tunnel_mapping:
                raise ValueError("Imported SSH tunnel IDs must be unique nonempty strings")
            public = normalized_ssh({**tunnel["config"], "enabled": True})
            name = _text(tunnel.get("name"), "tunnel name")
            match = next((item for item in self.data["ssh_tunnels"] if item["config"] == public
                          and item["name"] == name), None)
            if match is None:
                base, suffix = name[:240], 2
                while any(item["name"].casefold() == name.casefold() for item in self.data["ssh_tunnels"]):
                    name, suffix = f"{base} ({suffix})", suffix + 1
                match = self.save_tunnel({"name": name, "config": public})
            tunnel_mapping[original_id] = match["id"]
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
                if key not in {"connections", "groups", "version", "ssh_tunnels"}}) if "connections" in document else {})
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
            if config.get("ssh_tunnel_id"):
                if config["ssh_tunnel_id"] not in tunnel_mapping:
                    raise ValueError("Imported connection references an unknown SSH tunnel")
                config["ssh_tunnel_id"] = tunnel_mapping[config["ssh_tunnel_id"]]
            for key in ("created_at", "last_used", "order"):
                if key in config and key not in profile:
                    profile[key] = deepcopy(config[key])
            match = next((entry for entry in self.data["connections"] if entry["name"] == profile.get("name")
                          and entry.get("group_id") == profile["group_id"]), None)
            if match:
                profile["id"] = match["id"]
                if match.get("has_password"):
                    credentials_to_remove.append(match["id"])
                if match.get("has_ssh_password") or match.get("has_ssh_passphrase"):
                    credentials_to_remove.append(f"{match['id']}:ssh")
            saved = self.save_connection(profile, case_sensitive=True)
            self._find("connections", saved["id"])["has_password"] = False
            self._find("connections", saved["id"])["has_ssh_password"] = False
            self._find("connections", saved["id"])["has_ssh_passphrase"] = False
            count += 1
        self._migrate_inline_tunnels()
        return {"catalog": self.list(), "imported_connections": count, "passwords_imported": False}, credentials_to_remove
