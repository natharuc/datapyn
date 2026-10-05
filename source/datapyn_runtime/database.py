"""Database adapters. Existing production drivers are reused without Qt."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from collections import OrderedDict
import hashlib
import json
import time


class SQLiteConnector:
    """Small offline connector for the migration pilot and deterministic tests."""

    def __init__(self, database: str):
        import sqlalchemy
        from sqlalchemy.pool import StaticPool

        self.database = database
        self.connection = sqlite3.connect(database)
        # A real SQLAlchemy engine keeps pd.read_sql(..., db_engine) compatible.
        self.engine = sqlalchemy.create_engine(
            "sqlite://", creator=lambda: self.connection, poolclass=StaticPool
        )
        self.db_type = "sqlite"
        self.connection_params = {"database": database, "host": "", "port": 0, "username": ""}

    def execute_query(self, query: str, parameters=None):
        import pandas as pd

        if isinstance(parameters, list):
            from src.utils.sql_parameter_service import prepare_generic_sql
            prepared = prepare_generic_sql(query, parameters)
            query, parameters = prepared.query, prepared.params

        statements = []
        buffer = ""
        # complete_statement handles semicolons in SQL strings and comments.
        for char in query:
            buffer += char
            if char == ";" and sqlite3.complete_statement(buffer):
                statements.append(buffer)
                buffer = ""
        if buffer.strip():
            statements.append(buffer)
        results = []
        try:
            for statement in statements:
                cursor = self.connection.execute(statement, parameters or {})
                if cursor.description:
                    results.append(pd.DataFrame.from_records(cursor.fetchall(), columns=[c[0] for c in cursor.description]))
                cursor.close()
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        if not results:
            return pd.DataFrame({"Result": ["Command(s) executed successfully."]})
        return results[0] if len(results) == 1 else results

    def schema(self):
        tables = []
        for name, kind in self.connection.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name LIMIT 1000"
        ):
            escaped = name.replace('"', '""')
            columns = [
                {"name": row[1], "dtype": row[2] or "unknown", "nullable": not bool(row[3])}
                for row in self.connection.execute(f'PRAGMA table_info("{escaped}")')
            ]
            tables.append({"name": name, "schema": "main", "kind": kind, "columns": columns})
        return {"db_type": "sqlite", "database": self.database, "schemas": ["main"], "tables": tables}

    def disconnect(self):
        self.engine.dispose()
        self.connection.close()


def connect(config: dict):
    os.environ.setdefault("DATAPYN_SHARED_PARAMETER_DELIMITER", "{{name}}")
    db_type = str(config.get("db_type", "")).lower()
    if db_type == "databricks" and config.get("databricks_auth_mode") == "oauth":
        config = {**config, "password": ""}
    if db_type == "sqlite":
        return SQLiteConnector(str(config.get("database") or ":memory:"))

    from src.database.database_connector import DatabaseConnector

    if db_type not in DatabaseConnector.SUPPORTED_DATABASES:
        raise ValueError(f"Unsupported database type: {db_type}")
    connector = DatabaseConnector()
    options = dict(config)
    for key in ("db_type", "host", "port", "database", "username", "password", "workspace_path", "name", "group", "color", "created_at", "last_used", "favorite", "order", "save_password", "databricks_auth_mode"):
        options.pop(key, None)
    try:
        connected = connector.connect(
            db_type=db_type,
            host=str(config.get("host", "")),
            port=int(config.get("port", 0)),
            database=str(config.get("database", "")),
            username=str(config.get("username", "")),
            password=str(config.get("password", "")),
            **options,
        )
        if not connected or not connector.is_connected():
            raise ConnectionError("Database connection could not be established")
        if db_type == "sqlserver" and config.get("schema"):
            # SQL Server's reused driver does not retain a selected metadata
            # schema. Keep this editor focus without altering the login/user.
            connector.connection_params["schema"] = str(config["schema"])
        return connector
    except BaseException:
        connector.disconnect()
        raise


def schema(connector):
    if connector is None:
        raise ConnectionError("Connect this session to a database first")
    if isinstance(connector, SQLiteConnector):
        return connector.schema()
    from sqlalchemy import inspect

    inspector = inspect(connector.engine)
    schemas = inspector.get_schema_names()
    tables = []
    for schema_name in schemas[:100]:
        if schema_name in {"information_schema", "pg_catalog"}:
            continue
        for name in inspector.get_table_names(schema=schema_name):
            columns = [
                {"name": column["name"], "dtype": str(column["type"]), "nullable": bool(column.get("nullable", True))}
                for column in inspector.get_columns(name, schema=schema_name)
            ]
            tables.append({"name": name, "schema": schema_name, "kind": "table", "columns": columns})
            if len(tables) >= 1000:
                break
        if len(tables) >= 1000:
            break
    return {"db_type": connector.db_type, "database": connector.connection_params.get("database", ""), "schemas": schemas, "tables": tables}


class ConnectorPool:
    """Session-local engines keyed by profile and database/schema context."""

    def __init__(self, idle_timeout=300):
        self.items = OrderedDict()
        self.explorers = {}
        self.active_key = None
        self.default_config = None
        self.default_id = None
        self.default_active_key = None
        self.last_used = {}
        self.idle_timeout = idle_timeout
        self.configs = {}
        self.block_affinity = {}
        self.namespace_settings = OrderedDict()

    @staticmethod
    def _normalized_config(config):
        config = dict(config)
        engine = str(config.get("db_type") or "").lower()
        explicit_schema = "schema" in config and config["schema"] is not None
        schema = config.get("schema") if explicit_schema else config.get("postgresql_schema") or config.get("databricks_schema")
        if engine in {"mysql", "mariadb"}:
            schema = schema if explicit_schema else config.get("database") or ""
        elif engine == "postgresql":
            schema = schema if explicit_schema else schema or "public"
        elif engine == "databricks":
            schema = schema or "default"
        for field in ("postgresql_schema", "databricks_schema", "databricks_catalog", "postgresql_search_path"):
            config.pop(field, None)
        config["schema"] = str(schema or "")
        return config

    @classmethod
    def _key(cls, identifier, config):
        normalized = cls._normalized_config(config)
        return (identifier or "transient", hashlib.sha256(json.dumps(normalized, sort_keys=True, default=str).encode()).hexdigest())

    def _forget(self, key):
        self.explorers.pop(key, None)
        self.last_used.pop(key, None)
        self.configs.pop(key, None)
        self.block_affinity = {block: item for block, item in self.block_affinity.items() if item != key}
        if self.default_active_key == key:
            self.default_active_key = None

    def reindex_active(self, context, params):
        """Move a changed session without reconnecting or keeping an old alias."""
        old_key = self.active_key
        if old_key is None:
            return
        config = dict(self.configs[old_key])
        config.update(database=context["database"], schema=context["schema"])
        if "postgresql_search_path" in self.active.connection_params:
            config["postgresql_search_path"] = self.active.connection_params["postgresql_search_path"]
        for field in ("postgresql_schema", "databricks_schema", "databricks_catalog"):
            config.pop(field, None)
        new_key = self._key(old_key[0], config)
        block_id = params.get("block_id")
        if new_key != old_key and new_key in self.items:
            # A physical connection in this context already exists. Keep both:
            # they can own different temporary tables in the same database.
            suffix = time.monotonic_ns()
            candidate = (*new_key, str(suffix))
            while candidate in self.items:
                suffix += 1
                candidate = (*new_key, str(suffix))
            new_key = candidate
        if new_key != old_key:
            connector = self.items.pop(old_key)
            explorer = self.explorers.pop(old_key, None)
            last_used = self.last_used.pop(old_key, time.monotonic())
            self.configs.pop(old_key, None)
            self.items[new_key] = connector
            if explorer is not None:
                self.explorers[new_key] = explorer
            self.last_used[new_key] = last_used
            self.active_key = new_key
            self.block_affinity = {block: new_key if item == old_key else item for block, item in self.block_affinity.items()}
        self.configs[new_key] = config
        if "postgresql_search_path" in config:
            settings_key = new_key[:2]
            self.namespace_settings[settings_key] = config["postgresql_search_path"]
            self.namespace_settings.move_to_end(settings_key)
            while len(self.namespace_settings) > 64:
                self.namespace_settings.popitem(last=False)
        if block_id:
            self.block_affinity[str(block_id)] = new_key
        inherits = params.get("scope_inherited") is True or ("scope_inherited" not in params and not params.get("database") and not params.get("schema"))
        if inherits and old_key[0] == (self.default_id or "transient"):
            self.default_config = config
            self.default_active_key = new_key
        elif self.default_active_key == old_key:
            self.default_active_key = None

    def activate(self, params, *, default=False):
        config = params.get("_connection_config") or params.get("config")
        identifier = params.get("connection_id")
        if config is None:
            if identifier is not None:
                raise ConnectionError("Saved connection configuration was not supplied")
            config = self.default_config
            identifier = self.default_id
        if config is None:
            if self.active_key is not None and not params.get("database") and not params.get("schema"):
                return self.items[self.active_key]
            raise ConnectionError("Connect this session to a database first")
        config = dict(config)
        database_override = params.get("database")
        schema_override = params.get("schema")
        if database_override and config.get("db_type") != "sqlite":
            if str(database_override) != str(config.get("database") or "") and not schema_override:
                # Schema defaults belong to a database/catalog. An inherited
                # schema from the previous database can be absent in the new one.
                for field in ("schema", "postgresql_schema", "databricks_schema"):
                    config.pop(field, None)
            config["database"] = str(database_override)
        if schema_override is not None and config.get("db_type") != "sqlite":
            config["schema"] = str(schema_override)
        key = self._key(identifier, config)
        affinity = self.block_affinity.get(str(params.get("block_id") or ""))
        if params.get("scope_inherited") and self.default_active_key in self.items and self.default_active_key[:2] == key:
            key = self.default_active_key
        elif affinity in self.items and affinity[:2] == key:
            key = affinity
        elif not params.get("block_id") and self.active_key in self.items and self.active_key[:2] == key:
            key = self.active_key
        elif key not in self.items and not config.get("schema") and config.get("db_type") == "sqlserver":
            # The resolved login schema is not an explicit selector override.
            # Match the moved physical connector when requesting its database.
            for candidate in [self.active_key, *self.items]:
                if candidate not in self.configs or candidate[0] != key[0]:
                    continue
                stored = dict(self.configs[candidate])
                stored.pop("schema", None)
                if self._key(identifier, stored) == key:
                    key = candidate
                    break
        if key not in self.items:
            if len(self.items) >= 8:
                evict = next((item for item, existing in self.items.items()
                              if item != self.active_key and not getattr(existing, "has_temporary_tables", False)), None)
                if evict is None:
                    raise ConnectionError("This session retains eight connections with temporary tables; disconnect one before opening another")
                old_connector = self.items.pop(evict)
                self._forget(evict)
                if self.active_key == evict:
                    self.active_key = None
                old_connector.disconnect()
            if key[:2] in self.namespace_settings:
                config["postgresql_search_path"] = self.namespace_settings[key[:2]]
            connector = connect(config)
            self.items[key] = connector
            self.configs[key] = config
        else:
            connector = self.items[key]
            self.items.move_to_end(key)
        self.active_key = key
        self.last_used[key] = time.monotonic()
        if default or (params.get("scope_inherited") and self.default_active_key is None):
            self.default_config = dict(config)
            self.default_id = identifier
            self.default_active_key = key
        return connector

    @property
    def active(self):
        return self.items.get(self.active_key)

    def explorer(self):
        from .explorer import ObjectExplorer
        if self.active is None:
            raise ConnectionError("Connect this session to a database first")
        if self.active_key not in self.explorers:
            self.explorers[self.active_key] = ObjectExplorer(self.active)
        return self.explorers[self.active_key]

    def disconnect(self, identifier=None):
        for key, connector in list(self.items.items()):
            if identifier is None or key[0] == identifier:
                connector.disconnect()
                del self.items[key]
                self._forget(key)
                if self.active_key == key:
                    self.active_key = None
        if identifier is None or identifier == self.default_id:
            self.default_config = None
            self.default_id = None

    def touch_active(self):
        if self.active_key is not None:
            self.last_used[self.active_key] = time.monotonic()

    def reap_idle(self):
        if not self.idle_timeout:
            return []
        now, closed = time.monotonic(), []
        for key, connector in list(self.items.items()):
            if getattr(connector, "has_temporary_tables", False):
                continue
            # Closing an in-memory SQLite database destroys its contents.
            if isinstance(connector, SQLiteConnector) and connector.database == ":memory:":
                continue
            if now - self.last_used.get(key, now) >= self.idle_timeout:
                try:
                    connector.disconnect()
                except Exception:
                    # Idle cleanup must preserve the session's Python namespace.
                    pass
                finally:
                    del self.items[key]
                    self._forget(key)
                    if self.active_key == key:
                        self.active_key = None
                closed.append(key[0])
        return list(dict.fromkeys(closed))


def test_connection(params):
    config = params.get("_connection_config") or params.get("config")
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    config = dict(config)
    if params.get("_connection_config") and isinstance(params.get("config"), dict):
        for key, value in params["config"].items():
            if key not in {"password", "token", "access_token", "client_secret"} or value:
                config[key] = value
    if params.get("password") is not None:
        config["password"] = str(params["password"])
    connector = connect(config)
    try:
        return {"success": True, "db_type": connector.db_type, "message": "Connection established"}
    finally:
        connector.disconnect()
