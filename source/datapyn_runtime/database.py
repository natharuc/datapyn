"""Database adapters. Existing production drivers are reused without Qt."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3


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
    workspace = config.get("workspace_path")
    if workspace:
        os.environ["DATAPYN_WORKSPACE_PATH"] = str(Path(workspace).expanduser().resolve())
    db_type = str(config.get("db_type", "")).lower()
    if db_type == "sqlite":
        return SQLiteConnector(str(config.get("database") or ":memory:"))

    from src.database.database_connector import DatabaseConnector

    if db_type not in DatabaseConnector.SUPPORTED_DATABASES:
        raise ValueError(f"Unsupported database type: {db_type}")
    connector = DatabaseConnector()
    options = dict(config)
    for key in ("db_type", "host", "port", "database", "username", "password", "workspace_path"):
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
