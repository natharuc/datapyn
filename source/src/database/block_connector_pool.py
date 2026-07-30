"""Isolated DatabaseConnector instances per SQL block."""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from src.core.connection_ref import ConnectionRef
from src.database.database_connector import DatabaseConnector, get_connector_database_context

logger = logging.getLogger(__name__)


def connect_connector_from_config(
    config: dict,
    *,
    password: str = "",
    database: Optional[str] = None,
    database_context: Optional[str] = None,
) -> DatabaseConnector:
    """Open a new connector from saved connection settings."""
    connector = DatabaseConnector()
    initial_db = database or config.get("database", "")
    try:
        connector.connect(
            db_type=config["db_type"],
            host=config["host"],
            port=config["port"],
            database=initial_db,
            username=config.get("username", ""),
            password=password or config.get("password", ""),
            use_windows_auth=config.get("use_windows_auth", False),
            sqlserver_auth_mode=config.get("sqlserver_auth_mode", ""),
            trust_server_certificate=config.get("trust_server_certificate", False),
            http_path=config.get("http_path", ""),
        )
    except Exception as exc:
        logger.warning(
            "Connector connect failed (%s on %s): %s",
            initial_db,
            config.get("host", ""),
            exc,
        )
        try:
            connector.disconnect()
        except Exception:
            pass
        return connector

    target_context = database_context
    if not target_context and database and database != config.get("database", ""):
        if str(config.get("db_type", "")).lower() != "databricks":
            target_context = database
    if target_context and connector.is_connected():
        try:
            connector.change_database(target_context)
        except Exception as exc:
            logger.warning("Failed to set block database context %s: %s", target_context, exc)
    return connector


def _connection_storage_key(connection_group: str, connection_name: str) -> str:
    return ConnectionRef(group=connection_group or "", name=connection_name).storage_key()


class BlockConnectorPool:
    """Keeps one live connector per block key (isolated sessions)."""

    def __init__(self) -> None:
        self._entries: Dict[str, dict] = {}

    def peek_connected(
        self,
        block_key: str,
        connection_group: str,
        connection_name: str,
        *,
        database: Optional[str] = None,
        database_context: Optional[str] = None,
    ) -> Optional[DatabaseConnector]:
        """Return an existing live connector without opening a new connection."""
        storage_key = _connection_storage_key(connection_group, connection_name)
        entry = self._entries.get(block_key)
        if not entry or entry.get("connection_key") != storage_key:
            return None
        connector = entry.get("connector")
        if connector is None or not connector.is_connected():
            return None
        self._touch(block_key)
        self._apply_database(connector, database, database_context)
        return connector

    def get(
        self,
        block_key: str,
        connection_group: str,
        connection_name: str,
        config: dict,
        *,
        password: str = "",
        database: Optional[str] = None,
        database_context: Optional[str] = None,
    ) -> DatabaseConnector:
        storage_key = _connection_storage_key(connection_group, connection_name)
        entry = self._entries.get(block_key)
        if entry and entry.get("connection_key") == storage_key:
            connector = entry.get("connector")
            if connector is not None and connector.is_connected():
                self._touch(block_key)
                self._apply_database(connector, database, database_context)
                return connector
            self.release(block_key)

        try:
            connector = connect_connector_from_config(
                config,
                password=password,
                database=database,
                database_context=database_context,
            )
        except Exception as exc:
            logger.warning("Block connector connect failed: %s", exc)
            return DatabaseConnector()

        if not connector.is_connected():
            return connector

        self._entries[block_key] = {
            "connector": connector,
            "connection_key": storage_key,
            "last_used_at": time.monotonic(),
        }
        return connector

    def register(
        self,
        block_key: str,
        connection_group: str,
        connection_name: str,
        connector: DatabaseConnector,
    ) -> None:
        """Adopt an already-connected connector (e.g. after auto-connect worker)."""
        existing = self._entries.get(block_key)
        if existing and existing.get("connector") is not connector:
            self._disconnect(existing.get("connector"))
        self._entries[block_key] = {
            "connector": connector,
            "connection_key": _connection_storage_key(connection_group, connection_name),
            "last_used_at": time.monotonic(),
        }

    def release(self, block_key: str) -> None:
        entry = self._entries.pop(block_key, None)
        if entry:
            self._disconnect(entry.get("connector"))

    def release_all(self) -> None:
        for key in list(self._entries):
            self.release(key)

    def reap_idle(self, idle_timeout_sec: float) -> List[str]:
        """Disconnect block connectors idle longer than *idle_timeout_sec*."""
        if idle_timeout_sec <= 0:
            return []

        now = time.monotonic()
        released: List[str] = []
        for block_key in list(self._entries):
            entry = self._entries.get(block_key)
            if not entry:
                continue
            last_used = float(entry.get("last_used_at", 0.0))
            if now - last_used < idle_timeout_sec:
                continue
            connector = entry.get("connector")
            if connector is not None and connector.is_query_busy():
                continue
            self.release(block_key)
            released.append(block_key)
        return released

    def _touch(self, block_key: str) -> None:
        entry = self._entries.get(block_key)
        if entry is not None:
            entry["last_used_at"] = time.monotonic()

    def _apply_database(
        self,
        connector: DatabaseConnector,
        database: Optional[str],
        database_context: Optional[str],
    ) -> None:
        target = database_context or database
        if not target:
            return
        current = get_connector_database_context(connector)
        if current and current.lower() == str(target).lower():
            return
        try:
            connector.change_database(target)
        except Exception as exc:
            logger.warning("Block database switch failed: %s", exc)

    @staticmethod
    def _disconnect(connector: Optional[DatabaseConnector]) -> None:
        if connector is None:
            return
        try:
            if connector.is_connected():
                connector.disconnect()
        except Exception:
            pass
