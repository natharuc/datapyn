"""
Multiple database connections manager
"""

from typing import Dict, Optional, List
from .database_connector import DatabaseConnector
import json
import os
from pathlib import Path
from datetime import datetime


class ConnectionManager:
    """Manages multiple saved connections with groups/folders support"""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path.home() / ".datapyn" / "connections.json"

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
                # Migrate old format to new (with groups)
                if isinstance(data, dict) and "groups" not in data:
                    # Old format: just dict of connections
                    return {"groups": {}, "connections": data}
                return data
        return {"groups": {}, "connections": {}}

    def _save_configs(self):
        """Save configurations"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.saved_configs, f, indent=2)

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
    ):
        """Save a connection configuration"""
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

        # Databricks-specific field
        if db_type == "databricks" and http_path:
            config["http_path"] = http_path

        if save_password and password:
            # TODO: Implement secure password storage (keyring)
            config["password"] = password

        self.saved_configs["connections"][name] = config
        self._save_configs()

    def get_saved_connections(self) -> list:
        """Return list of saved connections"""
        return list(self.saved_configs.get("connections", {}).keys())

    def get_connection_config(self, name: str) -> Optional[dict]:
        """Return configuration of a saved connection"""
        return self.saved_configs.get("connections", {}).get(name)

    def update_connection_config(
        self,
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
    ):
        """Update an existing connection configuration"""
        if old_name in self.saved_configs.get("connections", {}):
            # Keep creation date
            old_config = self.saved_configs["connections"][old_name]
            created_at = old_config.get("created_at", datetime.now().isoformat())

            # Remove old connection if name changed
            if old_name != new_name:
                del self.saved_configs["connections"][old_name]

            # Save with new name
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
            )

            # Restore creation date
            self.saved_configs["connections"][new_name]["created_at"] = created_at
            self._save_configs()

    def delete_connection_config(self, name: str):
        """Remove a saved configuration"""
        if name in self.saved_configs.get("connections", {}):
            del self.saved_configs["connections"][name]
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
            # Move all connections from this group to root
            for conn_name, conn_config in self.saved_configs.get("connections", {}).items():
                if conn_config.get("group") == name:
                    conn_config["group"] = ""

            del self.saved_configs["groups"][name]
            self._save_configs()

    def rename_group(self, old_name: str, new_name: str):
        """Rename a group"""
        if old_name in self.saved_configs.get("groups", {}):
            # Update references in connections
            for conn_config in self.saved_configs.get("connections", {}).values():
                if conn_config.get("group") == old_name:
                    conn_config["group"] = new_name

            # Rename group
            self.saved_configs["groups"][new_name] = self.saved_configs["groups"][old_name]
            del self.saved_configs["groups"][old_name]
            self._save_configs()

    def get_connections_by_group(self, group: str = None) -> Dict[str, dict]:
        """Return connections from a specific group (None = no group)"""
        group = group or ""
        return {
            name: config
            for name, config in self.saved_configs.get("connections", {}).items()
            if config.get("group", "") == group
        }

    def mark_connection_used(self, name: str):
        """Mark last time connection was used"""
        if name in self.saved_configs.get("connections", {}):
            self.saved_configs["connections"][name]["last_used"] = datetime.now().isoformat()
            self._save_configs()

    def create_connection(
        self, name: str, db_type: str, host: str, port: int, database: str, username: str, password: str, **kwargs
    ) -> DatabaseConnector:
        """Create a new connection"""
        connector = DatabaseConnector()
        connector.connect(db_type, host, port, database, username, password, **kwargs)
        self.connections[name] = connector
        self.active_connection = name
        return connector

    def get_connection(self, name: str) -> Optional[DatabaseConnector]:
        """Return an existing connection"""
        return self.connections.get(name)

    def get_active_connection(self) -> Optional[DatabaseConnector]:
        """Return active connection"""
        if self.active_connection:
            return self.connections.get(self.active_connection)
        return None

    def set_active_connection(self, name: str):
        """Set active connection"""
        if name in self.connections:
            self.active_connection = name

    def close_connection(self, name: str):
        """Close a connection"""
        if name in self.connections:
            self.connections[name].disconnect()
            del self.connections[name]
            if self.active_connection == name:
                self.active_connection = None

    def close_all(self):
        """Close all connections"""
        for name in list(self.connections.keys()):
            self.close_connection(name)
