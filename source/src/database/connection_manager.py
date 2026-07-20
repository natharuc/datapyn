"""
Multiple database connections manager
"""

from __future__ import annotations

from typing import Dict, Optional, List
from .database_connector import DatabaseConnector, normalize_sqlserver_auth_mode, SQLSERVER_AUTH_WINDOWS
import json
from pathlib import Path
from datetime import datetime

from src.core.connection_ref import ConnectionRef, resolve_by_name_only


class DuplicateConnectionError(ValueError):
    """Raised when saving a connection that already exists in the same group."""


def _is_flat_connections(connections: dict) -> bool:
    """True when connections map is flat name -> config (legacy format)."""
    if not connections:
        return False
    first = next(iter(connections.values()))
    return isinstance(first, dict) and "db_type" in first


def _migrate_flat_to_nested(connections: dict) -> dict:
    nested: dict[str, dict] = {}
    for name, config in connections.items():
        if not isinstance(config, dict):
            continue
        group = str(config.get("group") or "")
        nested.setdefault(group, {})[name] = config
    return nested


class ConnectionManager:
    """Manages multiple saved connections with groups/folders support"""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            from src.core.workspace_service import get_workspace_service
            config_path = get_workspace_service().get_config_path("connections.json")

        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        self.connections: Dict[str, DatabaseConnector] = {}
        self.saved_configs: dict = self._load_configs()
        self.active_connection: Optional[str] = None

    def _load_configs(self) -> dict:
        """Load saved configurations"""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "groups" not in data:
                    data = {"groups": {}, "connections": data}
                connections = data.get("connections", {})
                if _is_flat_connections(connections):
                    data["connections"] = _migrate_flat_to_nested(connections)
                return data
        return {"groups": {}, "connections": {}}

    def _save_configs(self):
        """Save configurations"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.saved_configs, f, indent=2)

    def _connections_root(self) -> dict:
        if "connections" not in self.saved_configs:
            self.saved_configs["connections"] = {}
        return self.saved_configs["connections"]

    def _group_bucket(self, group: str) -> dict:
        group = group or ""
        root = self._connections_root()
        if group not in root:
            root[group] = {}
        return root[group]

    def connection_exists(self, group: str, name: str) -> bool:
        group = group or ""
        return name in self._connections_root().get(group, {})

    def save_connection_config(
        self,
        name: str,
        db_type: str,
        host: str,
        port: int,
        database: str,
        username: str = "",
        save_password: bool = False,
        password: str = "",
        group: str = "",
        use_windows_auth: bool = False,
        color: str = "",
        trust_server_certificate: bool = False,
        http_path: str = "",
        sqlserver_auth_mode: str = "",
        *,
        allow_overwrite: bool = False,
    ):
        """Save a connection configuration keyed by (group, name)."""
        group = group or ""
        if not allow_overwrite and self.connection_exists(group, name):
            raise DuplicateConnectionError(
                f"Connection '{name}' already exists in group '{group or '(ungrouped)'}'"
            )

        normalized_sqlserver_auth_mode = ""
        if db_type == "sqlserver":
            normalized_sqlserver_auth_mode = normalize_sqlserver_auth_mode(sqlserver_auth_mode, use_windows_auth)
            use_windows_auth = normalized_sqlserver_auth_mode == SQLSERVER_AUTH_WINDOWS

        config = {
            "db_type": db_type,
            "host": host,
            "port": port,
            "database": database,
            "username": username,
            "group": group,
            "use_windows_auth": use_windows_auth,
            "trust_server_certificate": trust_server_certificate,
            "color": color,
            "created_at": datetime.now().isoformat(),
            "last_used": None,
        }

        if db_type == "sqlserver":
            config["sqlserver_auth_mode"] = normalized_sqlserver_auth_mode

        if db_type == "databricks" and http_path:
            config["http_path"] = http_path

        if save_password and password:
            config["password"] = password

        self._group_bucket(group)[name] = config
        self._save_configs()

    def get_saved_connections(self) -> List[ConnectionRef]:
        """Return all saved connection refs."""
        refs: list[ConnectionRef] = []
        for group, bucket in self._connections_root().items():
            if not isinstance(bucket, dict):
                continue
            for conn_name in bucket:
                refs.append(ConnectionRef(group=group or "", name=conn_name))
        return refs

    def iter_saved_connections(self) -> List[tuple[str, str, dict]]:
        """Return (group, name, config) tuples for UI lists."""
        items: list[tuple[str, str, dict]] = []
        for group, bucket in self._connections_root().items():
            if not isinstance(bucket, dict):
                continue
            for conn_name, config in bucket.items():
                if isinstance(config, dict):
                    items.append((group or "", conn_name, config))
        return items

    def get_connection_config(self, group: str, name: str = "") -> Optional[dict]:
        """Return configuration by (group, name). Legacy: single name arg."""
        if not name:
            return self.get_connection_config_by_name(group)
        group = group or ""
        return self._connections_root().get(group, {}).get(name)

    def get_connection_config_by_name(self, name: str) -> Optional[dict]:
        """Legacy lookup by name only (unique or best-effort)."""
        ref = resolve_by_name_only(self, name)
        if ref is None:
            return None
        return self.get_connection_config(ref.group, ref.name)

    def get_connection_ref_by_name(self, name: str) -> Optional[ConnectionRef]:
        return resolve_by_name_only(self, name)

    def update_connection_config(
        self,
        old_group: str,
        old_name: str,
        new_name: str,
        db_type: str,
        host: str,
        port: int,
        database: str,
        username: str = "",
        save_password: bool = False,
        password: str = "",
        group: str = "",
        use_windows_auth: bool = False,
        color: str = "",
        trust_server_certificate: bool = False,
        http_path: str = "",
        sqlserver_auth_mode: str = "",
    ):
        """Update an existing connection configuration (may move between groups)."""
        old_group = old_group or ""
        group = group or ""
        old_config = self.get_connection_config(old_group, old_name)
        if old_config is None:
            return

        created_at = old_config.get("created_at", datetime.now().isoformat())
        moved = old_group != group or old_name != new_name

        if moved:
            if (old_group, old_name) != (group, new_name) and self.connection_exists(group, new_name):
                raise DuplicateConnectionError(
                    f"Connection '{new_name}' already exists in group '{group or '(ungrouped)'}'"
                )
            self.delete_connection_config(old_group, old_name, save=False)

        self.save_connection_config(
            new_name,
            db_type,
            host,
            port,
            database,
            username,
            save_password,
            password,
            group,
            use_windows_auth,
            color,
            trust_server_certificate,
            http_path,
            sqlserver_auth_mode,
            allow_overwrite=True,
        )
        self._group_bucket(group)[new_name]["created_at"] = created_at
        self._save_configs()

    def delete_connection_config(self, group: str, name: str = "", *, save: bool = True):
        """Remove a saved configuration. Legacy: single name arg."""
        if not name:
            ref = resolve_by_name_only(self, group)
            if ref is None:
                return
            group, name = ref.group, ref.name
        group = group or ""
        bucket = self._connections_root().get(group, {})
        if name in bucket:
            del bucket[name]
            if not bucket and group in self._connections_root():
                del self._connections_root()[group]
            if save:
                self._save_configs()

    def create_group(self, name: str, color: str = "", parent: str = ""):
        """Create a group/folder to organize connections"""
        if "groups" not in self.saved_configs:
            self.saved_configs["groups"] = {}

        self.saved_configs["groups"][name] = {
            "color": color,
            "parent": parent,
            "created_at": datetime.now().isoformat(),
        }
        self._save_configs()

    def get_groups(self) -> Dict[str, dict]:
        """Return all groups"""
        return self.saved_configs.get("groups", {})

    def delete_group(self, name: str):
        """Remove a group (move connections to root)"""
        if name in self.saved_configs.get("groups", {}):
            bucket = self._connections_root().get(name, {})
            if bucket:
                root_bucket = self._group_bucket("")
                for conn_name, conn_config in list(bucket.items()):
                    conn_config["group"] = ""
                    root_bucket[conn_name] = conn_config
                del self._connections_root()[name]

            del self.saved_configs["groups"][name]
            self._save_configs()

    def rename_group(self, old_name: str, new_name: str):
        """Rename a group"""
        if old_name not in self.saved_configs.get("groups", {}):
            return

        bucket = self._connections_root().get(old_name, {})
        if bucket:
            if new_name in self._connections_root():
                raise DuplicateConnectionError(f"Group bucket '{new_name}' already has connections")
            self._connections_root()[new_name] = bucket
            del self._connections_root()[old_name]
            for conn_config in bucket.values():
                conn_config["group"] = new_name

        self.saved_configs["groups"][new_name] = self.saved_configs["groups"][old_name]
        del self.saved_configs["groups"][old_name]
        self._save_configs()

    def get_connections_by_group(self, group: str = None) -> Dict[str, dict]:
        """Return connections from a specific group (None = no group)"""
        group = group or ""
        bucket = self._connections_root().get(group, {})
        return dict(bucket) if isinstance(bucket, dict) else {}

    def mark_connection_used(self, group: str, name: str = ""):
        """Mark last time connection was used. Legacy: single name arg."""
        if not name:
            ref = resolve_by_name_only(self, group)
            if ref is None:
                return
            group, name = ref.group, ref.name
        config = self.get_connection_config(group, name)
        if config is not None:
            config["last_used"] = datetime.now().isoformat()
            self._save_configs()

    def create_connection(
        self,
        ref: ConnectionRef,
        db_type: str,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        **kwargs,
    ) -> DatabaseConnector:
        """Create a new live connection"""
        connector = DatabaseConnector()
        connector.connect(db_type, host, port, database, username, password, **kwargs)
        key = ref.storage_key()
        self.connections[key] = connector
        self.active_connection = key
        return connector

    def get_connection(self, group: str, name: str = "") -> Optional[DatabaseConnector]:
        """Return an existing live connection. Legacy: single name arg."""
        if not name:
            ref = resolve_by_name_only(self, group)
            if ref is None:
                return None
            key = ref.storage_key()
        else:
            key = ConnectionRef(group=group or "", name=name).storage_key()
        return self.connections.get(key)

    def get_connection_by_ref(self, ref: ConnectionRef) -> Optional[DatabaseConnector]:
        return self.connections.get(ref.storage_key())

    def get_connection_by_key(self, storage_key: str) -> Optional[DatabaseConnector]:
        return self.connections.get(storage_key)

    def get_active_connection(self) -> Optional[DatabaseConnector]:
        """Return active connection"""
        if self.active_connection:
            return self.connections.get(self.active_connection)
        return None

    def get_active_connection_ref(self) -> Optional[ConnectionRef]:
        if self.active_connection:
            return ConnectionRef.from_storage_key(self.active_connection)
        return None

    def set_active_connection(self, ref: ConnectionRef):
        """Set active connection"""
        key = ref.storage_key()
        if key in self.connections:
            self.active_connection = key

    def close_connection(self, ref: ConnectionRef):
        """Close a connection"""
        key = ref.storage_key()
        if key in self.connections:
            self.connections[key].disconnect()
            del self.connections[key]
            if self.active_connection == key:
                self.active_connection = None

    def close_all(self):
        """Close all connections"""
        for key in list(self.connections.keys()):
            self.close_connection(ConnectionRef.from_storage_key(key))
