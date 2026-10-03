"""Qt adapter for the reusable entity metadata service."""
from __future__ import annotations

import logging
from typing import Any
from PyQt6.QtCore import QObject, pyqtSignal
from .entity_metadata_service import EntityMetadataService

logger = logging.getLogger(__name__)

class EntityMetadataWorker(QObject):
    """Background worker that resolves a connector and fetches entity metadata."""

    loaded = pyqtSignal(dict)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        *,
        entity_name: str,
        connector=None,
        fallback_connector=None,
        connection_config: dict[str, Any] | None = None,
        database_override: str = "",
    ):
        super().__init__()
        self.entity_name = entity_name
        self.connector = connector
        self.fallback_connector = fallback_connector
        self.connection_config = connection_config or {}
        self.database_override = database_override or ""

    def run(self):
        from src.database.database_connector import DatabaseConnector

        temp_connector = None
        try:
            connector = self.connector
            if connector is None:
                config = self.connection_config
                if config:
                    temp_connector = DatabaseConnector()
                    try:
                        temp_connector.connect(
                            db_type=config["db_type"],
                            host=config["host"],
                            port=config["port"],
                            database=config["database"],
                            username=config.get("username", ""),
                            password=config.get("password", ""),
                            use_windows_auth=config.get("use_windows_auth", False),
                            sqlserver_auth_mode=config.get("sqlserver_auth_mode", ""),
                            trust_server_certificate=config.get("trust_server_certificate", False),
                            http_path=config.get("http_path", ""),
                            schema=config.get("schema") or config.get("databricks_schema") or "",
                        )
                        connector = temp_connector
                    except Exception:
                        if self.fallback_connector is not None and not self.database_override:
                            connector = self.fallback_connector
                            temp_connector = None
                        else:
                            raise
                elif self.fallback_connector is not None:
                    connector = self.fallback_connector
                else:
                    raise ValueError("Missing connection configuration")

            if self.database_override:
                connector.change_database(self.database_override)

            metadata = EntityMetadataService().fetch_entity_info(connector, self.entity_name)
            self.loaded.emit(metadata)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if temp_connector is not None:
                try:
                    temp_connector.disconnect()
                except Exception:
                    logger.debug("Failed to close temporary metadata connector", exc_info=True)
            self.finished.emit()
