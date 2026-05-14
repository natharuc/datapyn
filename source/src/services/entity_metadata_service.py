"""
Entity metadata service.

Provides background-safe database introspection used by the SQL editor
entity information dialog and shared type formatting helpers for schema UI.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

RECOVERABLE_METADATA_ERROR_TOKENS = (
    "permission denied",
    "does not have permission",
    "access denied",
    "not authorized",
    "authorization failed",
    "insufficient privilege",
    "view database performance state",
    "view server performance state",
    "the select permission was denied",
)


def _normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key).lower(): value for key, value in dict(row).items()}


def _records(df) -> list[dict[str, Any]]:
    if df is None or len(df) == 0:
        return []
    return [_normalize_row(row) for row in df.to_dict("records")]


def _first_record(df) -> dict[str, Any] | None:
    rows = _records(df)
    return rows[0] if rows else None


def _first_value(df) -> Any:
    if df is None or len(df) == 0:
        return None
    return df.iloc[0, 0]


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"1", "true", "t", "yes", "y"}


def _is_recoverable_metadata_error(exc: Exception) -> bool:
    message = str(exc).strip().lower()
    return any(token in message for token in RECOVERABLE_METADATA_ERROR_TOKENS)


def sql_literal(value: str) -> str:
    return value.replace("'", "''")


def strip_identifier_quotes(value: str) -> str:
    text = value.strip()
    for left, right in (("[", "]"), ('"', '"'), ("`", "`")):
        while text.startswith(left) and text.endswith(right) and len(text) >= 2:
            text = text[1:-1].strip()
    return text


def split_qualified_name(identifier: str) -> list[str]:
    parts = [strip_identifier_quotes(part) for part in identifier.strip().split(".")]
    return [part for part in parts if part]


def quote_identifier(db_type: str, *parts: str) -> str:
    clean_parts = [part for part in (strip_identifier_quotes(p) for p in parts) if part]
    if not clean_parts:
        return ""

    normalized = (db_type or "").lower()
    if normalized in {"sqlserver", "mssql"}:
        return ".".join(f"[{part}]" for part in clean_parts)
    if normalized in {"mysql", "mariadb", "databricks"}:
        return ".".join(f"`{part}`" for part in clean_parts)
    return ".".join(f'"{part}"' for part in clean_parts)


def _postgres_regclass_literal(*parts: str) -> str:
    quoted = ".".join(f'"{strip_identifier_quotes(part)}"' for part in parts if part)
    return sql_literal(quoted)


def build_display_data_type(column_info: Mapping[str, Any], db_type: str) -> str:
    info = _normalize_row(column_info)
    raw_type = str(info.get("display_type") or info.get("data_type") or info.get("type") or "").strip()
    if not raw_type:
        return ""

    if any(token in raw_type for token in ("(", "<", "[]")):
        return raw_type

    normalized_db = (db_type or "").lower()
    normalized_type = raw_type.lower()
    aliases = {
        "character varying": "varchar",
        "character": "char",
    }
    base_type = aliases.get(normalized_type, normalized_type)

    if normalized_db == "postgresql":
        udt_name = str(info.get("udt_name") or "").strip()
        if normalized_type == "array" and udt_name.startswith("_"):
            return f"{udt_name[1:]}[]"
        if normalized_type == "user-defined" and udt_name:
            return udt_name

    length = _int_or_none(
        info.get("character_maximum_length")
        or info.get("max_length")
        or info.get("character_length")
    )
    precision = _int_or_none(info.get("numeric_precision") or info.get("precision"))
    scale = _int_or_none(info.get("numeric_scale") or info.get("scale"))
    datetime_precision = _int_or_none(info.get("datetime_precision"))

    if base_type in {"varchar", "nvarchar", "char", "nchar", "string", "varbinary", "binary"} and length is not None:
        length_text = "max" if length < 0 else str(length)
        return f"{base_type}({length_text})"

    if base_type in {"decimal", "numeric", "number"} and precision is not None:
        if scale is None:
            return f"{base_type}({precision})"
        return f"{base_type}({precision},{scale})"

    if base_type in {"datetime2", "datetimeoffset", "time", "timestamp"} and datetime_precision is not None:
        return f"{base_type}({datetime_precision})"

    return base_type


def format_size(size_bytes: Any) -> str:
    size_value = _int_or_none(size_bytes)
    if size_value is None or size_value < 0:
        return ""

    value = float(size_value)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.2f} {units[unit_index]}"


def _group_indexes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in rows:
        name = str(row.get("index_name") or row.get("indexname") or "").strip()
        if not name:
            continue

        column_name = str(row.get("column_name") or row.get("attname") or "").strip()
        ordinal = _int_or_none(row.get("key_ordinal") or row.get("seq_in_index") or row.get("ordinality")) or 0
        unique = _bool_value(row.get("is_unique", not _bool_value(row.get("non_unique"))))
        primary = _bool_value(row.get("is_primary_key") or row.get("indisprimary") or (name == "PRIMARY"))
        type_desc = str(row.get("type_desc") or row.get("index_type") or row.get("indexdef") or "").strip()

        index_info = grouped.setdefault(
            name,
            {
                "name": name,
                "unique": unique,
                "primary": primary,
                "type": type_desc,
                "columns": [],
            },
        )
        index_info["unique"] = index_info["unique"] or unique
        index_info["primary"] = index_info["primary"] or primary
        if type_desc and not index_info["type"]:
            index_info["type"] = type_desc
        if column_name:
            index_info["columns"].append((ordinal, column_name))

    results = []
    for index_info in grouped.values():
        ordered_columns = ", ".join(
            column_name for _, column_name in sorted(index_info["columns"], key=lambda item: item[0])
        )
        if index_info["primary"]:
            label = "PRIMARY KEY"
        elif index_info["unique"]:
            label = "UNIQUE"
        elif index_info["type"]:
            label = index_info["type"]
        else:
            label = "INDEX"

        results.append(
            {
                "name": index_info["name"],
                "type": label,
                "columns": ordered_columns,
                "unique": index_info["unique"],
                "primary": index_info["primary"],
            }
        )

    return sorted(results, key=lambda item: (not item["primary"], not item["unique"], item["name"].lower()))


class EntityMetadataService:
    """Database introspection service for relation metadata."""

    def fetch_entity_info(self, connector, entity_name: str) -> dict[str, Any]:
        db_type = str(getattr(connector, "db_type", "") or "").lower()
        parts = split_qualified_name(entity_name)
        if not parts:
            raise ValueError("No entity name provided")

        if db_type in {"sqlserver", "mssql"}:
            return self._fetch_sqlserver_info(connector, parts)
        if db_type == "postgresql":
            return self._fetch_postgresql_info(connector, parts)
        if db_type in {"mysql", "mariadb"}:
            return self._fetch_mysql_info(connector, parts, db_type)
        if db_type == "databricks":
            return self._fetch_databricks_info(connector, parts)
        raise ValueError(f"Unsupported database type: {db_type}")

    def _execute_scalar(self, connector, query: str) -> Any:
        return _first_value(connector.execute_query(query))

    def _execute_optional_scalar(self, connector, query: str, *, context: str) -> Any:
        try:
            return self._execute_scalar(connector, query)
        except Exception as exc:
            if _is_recoverable_metadata_error(exc):
                logger.info("Optional metadata query failed for %s: %s", context, exc)
                return None
            raise

    def _execute_optional_records(
        self,
        connector,
        query: str,
        *,
        context: str,
    ) -> list[dict[str, Any]] | None:
        try:
            return _records(connector.execute_query(query))
        except Exception as exc:
            if _is_recoverable_metadata_error(exc):
                logger.info("Optional metadata query failed for %s: %s", context, exc)
                return None
            raise

    def _load_columns(self, connector, query: str, db_type: str) -> list[dict[str, Any]]:
        rows = _records(connector.execute_query(query))
        results = []
        for row in rows:
            results.append(
                {
                    "name": str(row.get("column_name") or row.get("name") or ""),
                    "display_type": build_display_data_type(row, db_type),
                    "nullable": str(row.get("is_nullable") or row.get("nullable") or "YES"),
                    "default": row.get("column_default") or row.get("default_value") or "",
                    "ordinal_position": _int_or_none(row.get("ordinal_position")) or 0,
                }
            )
        return results

    def _base_result(
        self,
        connector,
        *,
        database: str,
        catalog: str,
        schema: str,
        entity_name: str,
        entity_type: str,
        row_count: int | None,
        size_bytes: int | None,
        columns: list[dict[str, Any]],
        indexes: list[dict[str, Any]],
        indexes_supported: bool = True,
        parameters: list[dict[str, Any]] | None = None,
        section_type: str = "table",
        definition: str = "",
    ) -> dict[str, Any]:
        return {
            "db_type": str(getattr(connector, "db_type", "") or "").lower(),
            "database": database,
            "catalog": catalog,
            "schema": schema,
            "entity_name": entity_name,
            "entity_type": entity_type,
            "qualified_name": ".".join(part for part in (catalog, schema, entity_name) if part),
            "row_count": row_count,
            "size_bytes": size_bytes,
            "size_pretty": format_size(size_bytes),
            "columns": sorted(columns, key=lambda item: item["ordinal_position"]),
            "indexes": indexes,
            "indexes_supported": indexes_supported,
            "parameters": parameters or [],
            "section_type": section_type,
            "definition": definition,
        }

    def _sqlserver_row_count(self, connector, schema_name: str, entity_name: str, entity_type: str) -> int | None:
        if entity_type.upper() == "VIEW":
            return None
        return _int_or_none(
            self._execute_optional_scalar(
                connector,
                f"""
                SELECT CAST(SUM(p.rows) AS BIGINT)
                FROM sys.tables t
                JOIN sys.schemas s ON s.schema_id = t.schema_id
                JOIN sys.partitions p ON p.object_id = t.object_id
                WHERE s.name = '{sql_literal(schema_name)}'
                  AND t.name = '{sql_literal(entity_name)}'
                  AND p.index_id IN (0, 1)
                """,
                context=f"SQL Server row count for {schema_name}.{entity_name}",
            )
        )

    def _sqlserver_size_bytes(self, connector, schema_name: str, entity_name: str, entity_type: str) -> int | None:
        if entity_type.upper() == "VIEW":
            return None
        return _int_or_none(
            self._execute_optional_scalar(
                connector,
                f"""
                SELECT CAST(SUM(a.total_pages) * 8192 AS BIGINT)
                FROM sys.tables t
                JOIN sys.schemas s ON s.schema_id = t.schema_id
                JOIN sys.indexes i ON i.object_id = t.object_id
                JOIN sys.partitions p ON p.object_id = i.object_id AND p.index_id = i.index_id
                JOIN sys.allocation_units a
                    ON a.container_id = CASE WHEN a.type IN (1, 3) THEN p.hobt_id ELSE p.partition_id END
                WHERE s.name = '{sql_literal(schema_name)}'
                  AND t.name = '{sql_literal(entity_name)}'
                  AND i.index_id IN (0, 1)
                """,
                context=f"SQL Server size for {schema_name}.{entity_name}",
            )
        )

    def _sqlserver_indexes(self, connector, schema_name: str, entity_name: str) -> tuple[list[dict[str, Any]], bool]:
        rows = self._execute_optional_records(
            connector,
            f"""
            SELECT
                i.name AS index_name,
                i.type_desc AS type_desc,
                i.is_unique AS is_unique,
                i.is_primary_key AS is_primary_key,
                c.name AS column_name,
                ic.key_ordinal AS key_ordinal
            FROM sys.indexes i
            JOIN sys.index_columns ic
                ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            JOIN sys.columns c
                ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            JOIN sys.objects o ON i.object_id = o.object_id
            JOIN sys.schemas s ON o.schema_id = s.schema_id
            WHERE s.name = '{sql_literal(schema_name)}'
              AND o.name = '{sql_literal(entity_name)}'
              AND i.is_hypothetical = 0
              AND i.name IS NOT NULL
            ORDER BY i.is_primary_key DESC, i.is_unique DESC, i.name, ic.key_ordinal
            """,
            context=f"SQL Server indexes for {schema_name}.{entity_name}",
        )
        if rows is None:
            return [], False
        return _group_indexes(rows), True

    def _postgres_row_count(self, connector, schema_name: str, entity_name: str, entity_type: str) -> int | None:
        if entity_type.upper() == "VIEW":
            return None
        return _int_or_none(
            self._execute_scalar(
                connector,
                f"""
                SELECT CAST(COALESCE(stat.n_live_tup, cls.reltuples, 0) AS BIGINT)
                FROM pg_class cls
                JOIN pg_namespace ns ON ns.oid = cls.relnamespace
                LEFT JOIN pg_stat_all_tables stat ON stat.relid = cls.oid
                WHERE ns.nspname = '{sql_literal(schema_name)}'
                  AND cls.relname = '{sql_literal(entity_name)}'
                LIMIT 1
                """,
            )
        )

    def _mysql_row_count(self, resolved: Mapping[str, Any], entity_type: str) -> int | None:
        if entity_type.upper() == "VIEW":
            return None
        return _int_or_none(resolved.get("table_rows"))

    def _databricks_row_count(self, detail: Mapping[str, Any] | None, entity_type: str) -> int | None:
        if entity_type.upper() == "VIEW" or not detail:
            return None
        return _int_or_none(detail.get("numrows"))

    def _sqlserver_parameters(
        self, connector, schema_name: str, routine_name: str, db_type: str
    ) -> list[dict[str, Any]]:
        rows = self._execute_optional_records(
            connector,
            f"""
            SELECT
                COALESCE(PARAMETER_NAME, '') AS parameter_name,
                DATA_TYPE AS data_type,
                COALESCE(PARAMETER_MODE, 'IN') AS parameter_mode,
                CHARACTER_MAXIMUM_LENGTH AS character_maximum_length,
                NUMERIC_PRECISION AS numeric_precision,
                NUMERIC_SCALE AS numeric_scale,
                ORDINAL_POSITION AS ordinal_position
            FROM INFORMATION_SCHEMA.PARAMETERS
            WHERE SPECIFIC_SCHEMA = '{sql_literal(schema_name)}'
              AND SPECIFIC_NAME = '{sql_literal(routine_name)}'
            ORDER BY ORDINAL_POSITION
            """,
            context=f"SQL Server parameters for {schema_name}.{routine_name}",
        )
        if not rows:
            return []
        result = []
        for row in rows:
            result.append(
                {
                    "name": str(row.get("parameter_name") or ""),
                    "display_type": build_display_data_type(row, db_type),
                    "direction": str(row.get("parameter_mode") or "IN"),
                    "default": "",
                    "ordinal_position": _int_or_none(row.get("ordinal_position")) or 0,
                }
            )
        return result

    def _sqlserver_trigger_columns(
        self, connector, schema_name: str, trigger_name: str
    ) -> list[dict[str, Any]]:
        records = self._execute_optional_records(
            connector,
            f"""
            SELECT
                t.name AS trigger_name,
                p.name AS parent_table,
                ps.name AS parent_schema,
                CASE t.is_instead_of_trigger WHEN 1 THEN 'INSTEAD OF' ELSE 'AFTER' END AS timing,
                CONCAT(
                    CASE WHEN OBJECTPROPERTY(t.object_id, 'ExecIsInsertTrigger') = 1 THEN 'INSERT ' ELSE '' END,
                    CASE WHEN OBJECTPROPERTY(t.object_id, 'ExecIsUpdateTrigger') = 1 THEN 'UPDATE ' ELSE '' END,
                    CASE WHEN OBJECTPROPERTY(t.object_id, 'ExecIsDeleteTrigger') = 1 THEN 'DELETE' ELSE '' END
                ) AS events,
                CASE WHEN t.is_disabled = 1 THEN 'Disabled' ELSE 'Enabled' END AS status
            FROM sys.triggers t
            JOIN sys.objects p ON t.parent_id = p.object_id
            JOIN sys.schemas ps ON p.schema_id = ps.schema_id
            WHERE t.name = '{sql_literal(trigger_name)}'
            """,
            context=f"SQL Server trigger info for {trigger_name}",
        )
        row = (records or [{}])[0]
        return [
            {"name": "Parent Table", "display_type": str(row.get("parent_schema") or "") + "." + str(row.get("parent_table") or ""), "direction": "", "default": "", "ordinal_position": 1},
            {"name": "Events", "display_type": str(row.get("events") or "").strip(), "direction": "", "default": "", "ordinal_position": 2},
            {"name": "Timing", "display_type": str(row.get("timing") or ""), "direction": "", "default": "", "ordinal_position": 3},
            {"name": "Status", "display_type": str(row.get("status") or ""), "direction": "", "default": "", "ordinal_position": 4},
        ]

    def _fetch_sqlserver_info(self, connector, parts: list[str]) -> dict[str, Any]:
        preferred_schema = parts[-2] if len(parts) >= 2 else "dbo"
        schema_filter = (
            f"AND s.name = '{sql_literal(parts[-2])}'" if len(parts) >= 2 else ""
        )
        entity_name = parts[-1]
        resolved = _first_record(
            connector.execute_query(
                f"""
                SELECT TOP 1
                    s.name AS schema_name,
                    o.name AS entity_name,
                    CASE o.type
                        WHEN 'U' THEN 'TABLE'
                        WHEN 'V' THEN 'VIEW'
                        WHEN 'P' THEN 'PROCEDURE'
                        WHEN 'FN' THEN 'FUNCTION'
                        WHEN 'IF' THEN 'FUNCTION'
                        WHEN 'TF' THEN 'FUNCTION'
                        WHEN 'TR' THEN 'TRIGGER'
                        ELSE RTRIM(o.type_desc)
                    END AS entity_type,
                    o.type AS object_type_code
                FROM sys.objects o
                JOIN sys.schemas s ON s.schema_id = o.schema_id
                WHERE o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF', 'TR')
                  AND o.name = '{sql_literal(entity_name)}'
                  {schema_filter}
                ORDER BY CASE WHEN s.name = '{sql_literal(preferred_schema)}' THEN 0 ELSE 1 END, s.name
                """
            )
        )
        if not resolved:
            raise ValueError(f"Entity not found: {entity_name}")

        schema_name = str(resolved["schema_name"])
        resolved_name = str(resolved["entity_name"])
        entity_type = str(resolved["entity_type"])
        database_name = str(getattr(connector, "get_current_database", lambda: "")() or "")

        if entity_type in ("PROCEDURE", "FUNCTION"):
            params = self._sqlserver_parameters(connector, schema_name, resolved_name, "sqlserver")
            return self._base_result(
                connector,
                database=database_name,
                catalog="",
                schema=schema_name,
                entity_name=resolved_name,
                entity_type=entity_type,
                row_count=None,
                size_bytes=None,
                columns=[],
                indexes=[],
                indexes_supported=False,
                parameters=params,
                section_type="routine",
            )

        if entity_type == "TRIGGER":
            trigger_cols = self._sqlserver_trigger_columns(connector, schema_name, resolved_name)
            return self._base_result(
                connector,
                database=database_name,
                catalog="",
                schema=schema_name,
                entity_name=resolved_name,
                entity_type=entity_type,
                row_count=None,
                size_bytes=None,
                columns=[],
                indexes=[],
                indexes_supported=False,
                parameters=trigger_cols,
                section_type="trigger",
            )

        row_count = self._sqlserver_row_count(connector, schema_name, resolved_name, entity_type)
        size_bytes = self._sqlserver_size_bytes(connector, schema_name, resolved_name, entity_type)

        columns = self._load_columns(
            connector,
            f"""
            SELECT
                COLUMN_NAME,
                DATA_TYPE,
                CHARACTER_MAXIMUM_LENGTH,
                NUMERIC_PRECISION,
                NUMERIC_SCALE,
                DATETIME_PRECISION,
                IS_NULLABLE,
                COLUMN_DEFAULT,
                ORDINAL_POSITION
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = '{sql_literal(schema_name)}'
              AND TABLE_NAME = '{sql_literal(resolved_name)}'
            ORDER BY ORDINAL_POSITION
            """,
            "sqlserver",
        )
        indexes, indexes_supported = self._sqlserver_indexes(connector, schema_name, resolved_name)

        return self._base_result(
            connector,
            database=database_name,
            catalog="",
            schema=schema_name,
            entity_name=resolved_name,
            entity_type=entity_type,
            row_count=row_count,
            size_bytes=size_bytes,
            columns=columns,
            indexes=indexes,
            indexes_supported=indexes_supported,
        )

    def _fetch_postgresql_info(self, connector, parts: list[str]) -> dict[str, Any]:
        preferred_schema = parts[-2] if len(parts) >= 2 else str(
            self._execute_scalar(connector, "SELECT current_schema()")
            or "public"
        )
        schema_filter = (
            f"AND table_schema = '{sql_literal(parts[-2])}'" if len(parts) >= 2 else ""
        )
        entity_name = parts[-1]

        resolved = _first_record(
            connector.execute_query(
                f"""
                SELECT table_schema AS schema_name, table_name AS entity_name, table_type AS entity_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                  AND table_name = '{sql_literal(entity_name)}'
                  {schema_filter}
                ORDER BY CASE WHEN table_schema = '{sql_literal(preferred_schema)}' THEN 0 ELSE 1 END, table_schema
                LIMIT 1
                """
            )
        )

        if not resolved:
            # Check routines
            routine_schema_filter = (
                f"AND routine_schema = '{sql_literal(parts[-2])}'" if len(parts) >= 2 else ""
            )
            resolved = _first_record(
                self._execute_optional_records(
                    connector,
                    f"""
                    SELECT routine_schema AS schema_name, routine_name AS entity_name,
                           routine_type AS entity_type
                    FROM information_schema.routines
                    WHERE routine_schema NOT IN ('pg_catalog', 'information_schema')
                      AND routine_name = '{sql_literal(entity_name)}'
                      {routine_schema_filter}
                    ORDER BY CASE WHEN routine_schema = '{sql_literal(preferred_schema)}' THEN 0 ELSE 1 END, routine_schema
                    LIMIT 1
                    """,
                    context=f"PostgreSQL routines for {entity_name}",
                )
                or []
            )

        if not resolved:
            raise ValueError(f"Entity not found: {entity_name}")

        schema_name = str(resolved["schema_name"])
        resolved_name = str(resolved["entity_name"])
        entity_type = str(resolved["entity_type"]).upper()
        if entity_type == "BASE TABLE":
            entity_type = "TABLE"

        database_name = str(getattr(connector, "get_current_database", lambda: "")() or "")

        if entity_type in ("PROCEDURE", "FUNCTION"):
            params = self._execute_optional_records(
                connector,
                f"""
                SELECT
                    COALESCE(parameter_name, '') AS parameter_name,
                    data_type,
                    COALESCE(parameter_mode, 'IN') AS parameter_mode,
                    character_maximum_length,
                    numeric_precision,
                    numeric_scale,
                    ordinal_position
                FROM information_schema.parameters
                WHERE specific_schema = '{sql_literal(schema_name)}'
                  AND specific_name = '{sql_literal(resolved_name)}'
                ORDER BY ordinal_position
                """,
                context=f"PostgreSQL parameters for {schema_name}.{resolved_name}",
            ) or []
            parameters = [
                {
                    "name": str(r.get("parameter_name") or ""),
                    "display_type": build_display_data_type(r, "postgresql"),
                    "direction": str(r.get("parameter_mode") or "IN"),
                    "default": "",
                    "ordinal_position": _int_or_none(r.get("ordinal_position")) or 0,
                }
                for r in params
            ]
            return self._base_result(
                connector,
                database=database_name,
                catalog="",
                schema=schema_name,
                entity_name=resolved_name,
                entity_type=entity_type,
                row_count=None,
                size_bytes=None,
                columns=[],
                indexes=[],
                indexes_supported=False,
                parameters=parameters,
                section_type="routine",
            )

        regclass_name = _postgres_regclass_literal(schema_name, resolved_name)

        row_count = self._postgres_row_count(connector, schema_name, resolved_name, entity_type)
        size_bytes = _int_or_none(
            self._execute_scalar(
                connector,
                f"SELECT pg_total_relation_size('{regclass_name}'::regclass)",
            )
        )

        columns = self._load_columns(
            connector,
            f"""
            SELECT
                column_name,
                data_type,
                udt_name,
                character_maximum_length,
                numeric_precision,
                numeric_scale,
                datetime_precision,
                is_nullable,
                column_default,
                ordinal_position
            FROM information_schema.columns
            WHERE table_schema = '{sql_literal(schema_name)}'
              AND table_name = '{sql_literal(resolved_name)}'
            ORDER BY ordinal_position
            """,
            "postgresql",
        )
        indexes = _group_indexes(
            _records(
                connector.execute_query(
                    f"""
                    SELECT
                        i.relname AS index_name,
                        ix.indisunique AS is_unique,
                        ix.indisprimary AS is_primary_key,
                        a.attname AS column_name,
                        key_columns.ordinality AS ordinality
                    FROM pg_class t
                    JOIN pg_namespace ns ON ns.oid = t.relnamespace
                    JOIN pg_index ix ON t.oid = ix.indrelid
                    JOIN pg_class i ON i.oid = ix.indexrelid
                    JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS key_columns(attnum, ordinality) ON true
                    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = key_columns.attnum
                    WHERE ns.nspname = '{sql_literal(schema_name)}'
                      AND t.relname = '{sql_literal(resolved_name)}'
                    ORDER BY ix.indisprimary DESC, ix.indisunique DESC, i.relname, key_columns.ordinality
                    """
                )
            )
        )

        return self._base_result(
            connector,
            database=database_name,
            catalog="",
            schema=schema_name,
            entity_name=resolved_name,
            entity_type=entity_type,
            row_count=row_count,
            size_bytes=size_bytes,
            columns=columns,
            indexes=indexes,
        )

    def _fetch_mysql_info(self, connector, parts: list[str], db_type: str) -> dict[str, Any]:
        preferred_schema = parts[-2] if len(parts) >= 2 else str(
            getattr(connector, "get_current_database", lambda: "")() or ""
        )
        schema_filter = (
            f"AND TABLE_SCHEMA = '{sql_literal(parts[-2])}'" if len(parts) >= 2 else ""
        )
        entity_name = parts[-1]
        resolved = _first_record(
            connector.execute_query(
                f"""
                SELECT
                    TABLE_SCHEMA AS schema_name,
                    TABLE_NAME AS entity_name,
                    TABLE_TYPE AS entity_type,
                    TABLE_ROWS AS table_rows,
                    DATA_LENGTH + INDEX_LENGTH AS size_bytes
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_NAME = '{sql_literal(entity_name)}'
                  {schema_filter}
                ORDER BY CASE WHEN TABLE_SCHEMA = '{sql_literal(preferred_schema)}' THEN 0 ELSE 1 END, TABLE_SCHEMA
                LIMIT 1
                """
            )
        )

        if not resolved:
            # Check routines
            routine_schema_filter = (
                f"AND ROUTINE_SCHEMA = '{sql_literal(parts[-2])}'" if len(parts) >= 2 else ""
            )
            resolved = _first_record(
                self._execute_optional_records(
                    connector,
                    f"""
                    SELECT
                        ROUTINE_SCHEMA AS schema_name,
                        ROUTINE_NAME AS entity_name,
                        ROUTINE_TYPE AS entity_type
                    FROM INFORMATION_SCHEMA.ROUTINES
                    WHERE ROUTINE_NAME = '{sql_literal(entity_name)}'
                      {routine_schema_filter}
                    ORDER BY CASE WHEN ROUTINE_SCHEMA = '{sql_literal(preferred_schema)}' THEN 0 ELSE 1 END, ROUTINE_SCHEMA
                    LIMIT 1
                    """,
                    context=f"MySQL routines for {entity_name}",
                )
                or []
            )
            if resolved:
                resolved.setdefault("table_rows", None)
                resolved.setdefault("size_bytes", None)

        if not resolved:
            raise ValueError(f"Entity not found: {entity_name}")

        schema_name = str(resolved["schema_name"])
        resolved_name = str(resolved["entity_name"])
        entity_type = str(resolved["entity_type"]).upper()
        if entity_type == "BASE TABLE":
            entity_type = "TABLE"

        database_name = str(getattr(connector, "get_current_database", lambda: "")() or "")

        if entity_type in ("PROCEDURE", "FUNCTION"):
            params = self._execute_optional_records(
                connector,
                f"""
                SELECT
                    COALESCE(PARAMETER_NAME, '') AS parameter_name,
                    DATA_TYPE AS data_type,
                    COALESCE(PARAMETER_MODE, 'IN') AS parameter_mode,
                    CHARACTER_MAXIMUM_LENGTH AS character_maximum_length,
                    NUMERIC_PRECISION AS numeric_precision,
                    NUMERIC_SCALE AS numeric_scale,
                    ORDINAL_POSITION AS ordinal_position
                FROM INFORMATION_SCHEMA.PARAMETERS
                WHERE SPECIFIC_SCHEMA = '{sql_literal(schema_name)}'
                  AND SPECIFIC_NAME = '{sql_literal(resolved_name)}'
                ORDER BY ORDINAL_POSITION
                """,
                context=f"MySQL parameters for {schema_name}.{resolved_name}",
            ) or []
            parameters = [
                {
                    "name": str(r.get("parameter_name") or ""),
                    "display_type": build_display_data_type(r, db_type),
                    "direction": str(r.get("parameter_mode") or "IN"),
                    "default": "",
                    "ordinal_position": _int_or_none(r.get("ordinal_position")) or 0,
                }
                for r in params
            ]
            return self._base_result(
                connector,
                database=database_name,
                catalog="",
                schema=schema_name,
                entity_name=resolved_name,
                entity_type=entity_type,
                row_count=None,
                size_bytes=None,
                columns=[],
                indexes=[],
                indexes_supported=False,
                parameters=parameters,
                section_type="routine",
            )

        row_count = self._mysql_row_count(resolved, entity_type)
        size_bytes = _int_or_none(resolved.get("size_bytes"))

        columns = self._load_columns(
            connector,
            f"""
            SELECT
                COLUMN_NAME,
                DATA_TYPE,
                CHARACTER_MAXIMUM_LENGTH,
                NUMERIC_PRECISION,
                NUMERIC_SCALE,
                DATETIME_PRECISION,
                IS_NULLABLE,
                COLUMN_DEFAULT,
                ORDINAL_POSITION
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = '{sql_literal(schema_name)}'
              AND TABLE_NAME = '{sql_literal(resolved_name)}'
            ORDER BY ORDINAL_POSITION
            """,
            db_type,
        )
        indexes = _group_indexes(
            _records(
                connector.execute_query(
                    f"""
                    SELECT
                        INDEX_NAME AS index_name,
                        NON_UNIQUE AS non_unique,
                        COLUMN_NAME AS column_name,
                        SEQ_IN_INDEX AS seq_in_index
                    FROM INFORMATION_SCHEMA.STATISTICS
                    WHERE TABLE_SCHEMA = '{sql_literal(schema_name)}'
                      AND TABLE_NAME = '{sql_literal(resolved_name)}'
                    ORDER BY INDEX_NAME, SEQ_IN_INDEX
                    """
                )
            )
        )

        return self._base_result(
            connector,
            database=database_name,
            catalog="",
            schema=schema_name,
            entity_name=resolved_name,
            entity_type=entity_type,
            row_count=row_count,
            size_bytes=size_bytes,
            columns=columns,
            indexes=indexes,
        )

    def _fetch_databricks_info(self, connector, parts: list[str]) -> dict[str, Any]:
        current_catalog = str(getattr(connector, "get_current_catalog", lambda: "")() or "")
        current_schema = str(getattr(connector, "get_current_schema", lambda: "default")() or "default")

        if len(parts) >= 3:
            target_catalog, preferred_schema, entity_name = parts[-3], parts[-2], parts[-1]
        elif len(parts) == 2:
            target_catalog, preferred_schema, entity_name = current_catalog, parts[0], parts[1]
        else:
            target_catalog, preferred_schema, entity_name = current_catalog, current_schema, parts[0]

        if target_catalog and target_catalog != current_catalog:
            connector.change_database(f"CATALOG:{target_catalog}")
        if preferred_schema and preferred_schema != current_schema:
            connector.change_database(f"SCHEMA:{preferred_schema}")

        schema_filter = (
            f"AND table_schema = '{sql_literal(preferred_schema)}'" if preferred_schema else ""
        )
        resolved = _first_record(
            connector.execute_query(
                f"""
                SELECT table_schema AS schema_name, table_name AS entity_name, table_type AS entity_type
                FROM information_schema.tables
                WHERE table_name = '{sql_literal(entity_name)}'
                  {schema_filter}
                ORDER BY CASE WHEN table_schema = '{sql_literal(preferred_schema)}' THEN 0 ELSE 1 END, table_schema
                LIMIT 1
                """
            )
        )
        if not resolved:
            raise ValueError(f"Entity not found: {entity_name}")

        schema_name = str(resolved["schema_name"])
        resolved_name = str(resolved["entity_name"])
        entity_type = str(resolved["entity_type"])
        quoted_name = quote_identifier("databricks", target_catalog, schema_name, resolved_name)

        detail = None
        size_bytes = None
        try:
            detail = _first_record(connector.execute_query(f"DESCRIBE DETAIL {quoted_name}"))
            if detail:
                size_bytes = _int_or_none(detail.get("sizeinbytes"))
        except Exception as exc:
            logger.info("Databricks DESCRIBE DETAIL unavailable for %s: %s", quoted_name, exc)
        row_count = self._databricks_row_count(detail, entity_type)

        columns = self._load_columns(
            connector,
            f"""
            SELECT
                column_name,
                data_type,
                is_nullable,
                ordinal_position
            FROM information_schema.columns
            WHERE table_schema = '{sql_literal(schema_name)}'
              AND table_name = '{sql_literal(resolved_name)}'
            ORDER BY ordinal_position
            """,
            "databricks",
        )

        return self._base_result(
            connector,
            database=target_catalog,
            catalog=target_catalog,
            schema=schema_name,
            entity_name=resolved_name,
            entity_type=entity_type,
            row_count=row_count,
            size_bytes=size_bytes,
            columns=columns,
            indexes=[],
            indexes_supported=False,
        )


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
                            trust_server_certificate=config.get("trust_server_certificate", False),
                            http_path=config.get("http_path", ""),
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
