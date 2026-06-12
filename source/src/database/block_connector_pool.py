"""Isolated DatabaseConnector instances per SQL block."""

from __future__ import annotations

import logging
from typing import Dict, Optional

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


class BlockConnectorPool:
    """Keeps one live connector per block key (isolated sessions)."""

    def __init__(self) -> None:
        self._entries: Dict[str, dict] = {}

    def get(
        self,
        block_key: str,
        connection_name: str,
        config: dict,
        *,
        password: str = "",
        database: Optional[str] = None,
        database_context: Optional[str] = None,
    ) -> DatabaseConnector:
        entry = self._entries.get(block_key)
        if entry and entry.get("connection_name") == connection_name:
            connector = entry.get("connector")
            if connector is not None and connector.is_connected():
                self._apply_database(connector, database, database_context)
                return connector
            self.release(block_key)

        connector = connect_connector_from_config(
            config,
            password=password,
            database=database,
            database_context=database_context,
        )
        self._entries[block_key] = {
            "connector": connector,
            "connection_name": connection_name,
        }
        return connector

    def register(self, block_key: str, connection_name: str, connector: DatabaseConnector) -> None:
        """Adopt an already-connected connector (e.g. after auto-connect worker)."""
        existing = self._entries.get(block_key)
        if existing and existing.get("connector") is not connector:
            self._disconnect(existing.get("connector"))
        self._entries[block_key] = {
            "connector": connector,
            "connection_name": connection_name,
        }

    def release(self, block_key: str) -> None:
        entry = self._entries.pop(block_key, None)
        if entry:
            self._disconnect(entry.get("connector"))

    def release_all(self) -> None:
        for key in list(self._entries):
            self.release(key)

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
