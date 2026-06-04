"""Helpers for cross-database SQL autocomplete and schema validation."""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Set, Tuple

try:
    import sqlglot
    from sqlglot import exp

    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False

# T-SQL: database..table (empty schema → dbo)
_RE_TSQL_DB_DOUBLE_DOT = re.compile(
    r"(?<![.\w])"
    r"((?:\[[^\]]+\]|[A-Za-z_][\w$]*))"
    r"\s*\.\s*\.\s*"
    r"((?:\[[^\]]+\]|[A-Za-z_][\w$]*))",
    re.IGNORECASE,
)

_IDENTIFIER_QUOTES = {"[", "]", "`", '"'}

DEFAULT_MSSQL_SCHEMAS = ("dbo",)


def strip_sql_identifier(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text[0] in _IDENTIFIER_QUOTES and text[-1] in _IDENTIFIER_QUOTES:
        return text[1:-1]
    return text


def _normalize_db_name(name: str) -> str:
    return strip_sql_identifier(name).lower()


def extract_referenced_catalogs(
    sql: str,
    *,
    current_database: str = "",
    db_type: str = "",
) -> Set[str]:
    """Return database/catalog names referenced outside the active database."""
    if not sql or not sql.strip():
        return set()

    current_lower = _normalize_db_name(current_database)
    referenced: Set[str] = set()
    normalized_db_type = str(db_type or "").lower()

    for match in _RE_TSQL_DB_DOUBLE_DOT.finditer(sql):
        catalog = strip_sql_identifier(match.group(1))
        if catalog and _normalize_db_name(catalog) != current_lower:
            referenced.add(catalog)

    if not HAS_SQLGLOT:
        return referenced

    dialect = "tsql" if normalized_db_type in ("mssql", "sqlserver") else None
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception:
        return referenced

    for statement in statements:
        if statement is None:
            continue
        for table in statement.find_all(exp.Table):
            catalog = strip_sql_identifier(str(table.catalog or ""))
            schema = strip_sql_identifier(str(table.db or ""))
            if normalized_db_type in ("mssql", "sqlserver"):
                if catalog and _normalize_db_name(catalog) != current_lower:
                    referenced.add(catalog)
            elif normalized_db_type in ("mysql", "mariadb"):
                if schema and _normalize_db_name(schema) != current_lower:
                    referenced.add(schema)
            elif normalized_db_type == "databricks":
                if catalog and _normalize_db_name(catalog) != current_lower:
                    referenced.add(catalog)

    return referenced


def extract_referenced_table_refs(
    sql: str,
    *,
    current_database: str = "",
    db_type: str = "",
) -> List[Tuple[str, str, str]]:
    """Return (catalog_or_database, schema, table) tuples used in SQL."""
    if not sql or not sql.strip():
        return []

    refs: List[Tuple[str, str, str]] = []
    seen: Set[Tuple[str, str, str]] = set()
    normalized_db_type = str(db_type or "").lower()

    def add_ref(catalog: str, schema: str, table: str) -> None:
        catalog = strip_sql_identifier(catalog)
        schema = strip_sql_identifier(schema)
        table = strip_sql_identifier(table)
        if not table:
            return
        if normalized_db_type in ("mssql", "sqlserver") and catalog and not schema:
            schema = DEFAULT_MSSQL_SCHEMAS[0]
        key = (catalog.lower(), schema.lower(), table.lower())
        if key in seen:
            return
        seen.add(key)
        refs.append((catalog, schema, table))

    for match in _RE_TSQL_DB_DOUBLE_DOT.finditer(sql):
        add_ref(match.group(1), DEFAULT_MSSQL_SCHEMAS[0], match.group(2))

    if not HAS_SQLGLOT:
        return refs

    dialect = "tsql" if normalized_db_type in ("mssql", "sqlserver") else None
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception:
        return refs

    for statement in statements:
        if statement is None:
            continue
        for table in statement.find_all(exp.Table):
            catalog = strip_sql_identifier(str(table.catalog or ""))
            schema = strip_sql_identifier(str(table.db or ""))
            name = strip_sql_identifier(str(table.name or ""))
            if normalized_db_type in ("mssql", "sqlserver"):
                add_ref(catalog, schema, name)
            elif normalized_db_type in ("mysql", "mariadb"):
                add_ref("", schema, name)
            else:
                add_ref(catalog, schema, name)

    return refs


def collect_sql_text_from_widget(widget) -> str:
    """Concatenate SQL block contents from a session widget editor."""
    editor = getattr(widget, "editor", None)
    if not editor or not hasattr(editor, "get_blocks"):
        return ""

    chunks: List[str] = []
    for block in editor.get_blocks():
        lang = block.get_language() if hasattr(block, "get_language") else ""
        if lang != "sql":
            continue
        get_code = getattr(block, "get_code", None)
        if callable(get_code):
            code = get_code() or ""
            if code.strip():
                chunks.append(code)
    return "\n".join(chunks)


def prepare_editor_sql_schema(
    schema: dict,
    *,
    db_type: str = "",
    referenced_catalogs: Optional[Set[str]] = None,
) -> dict:
    """Build Monaco/validator schema including cross-database objects.

    When *referenced_catalogs* is ``None``, every table already present in the
    merged Object Explorer cache is kept (lazy-loaded auxiliary databases).
    When it is a set, only the active database plus those catalogs are included.
    """
    if not isinstance(schema, dict):
        return {}

    normalized_db_type = str(db_type or schema.get("db_type", "") or "").lower()
    current_database = str(schema.get("database", "") or "")
    tables = list(schema.get("tables", []) or [])

    if normalized_db_type == "databricks" or not current_database or not tables:
        return schema

    table_entries = [table for table in tables if isinstance(table, dict)]
    if not table_entries:
        return schema

    has_database_scoped_tables = any(str(table.get("database", "") or "") for table in table_entries)
    if not has_database_scoped_tables:
        return schema

    referenced_lower: Optional[Set[str]] = None
    if referenced_catalogs is not None:
        referenced_lower = {_normalize_db_name(name) for name in referenced_catalogs if name}

    filtered_tables = []
    allowed_column_keys: Set[str] = set()
    current_database_lower = current_database.lower()

    for table in tables:
        if not isinstance(table, dict):
            filtered_tables.append(table)
            allowed_column_keys.add(str(table or ""))
            continue

        table_name = str(table.get("name", "") or "")
        table_schema = str(table.get("schema", "") or "")
        table_catalog = str(table.get("catalog", "") or "")
        table_database = str(table.get("database", "") or "")

        include = False
        if not table_database:
            include = True
        elif table_database.lower() == current_database_lower:
            include = True
        elif referenced_lower is None:
            include = True
        elif table_database.lower() in referenced_lower:
            include = True

        if not include:
            continue

        filtered_tables.append(table)

        table_key = str(table.get("key", "") or "")
        if table_key:
            allowed_column_keys.add(table_key)
        if table_name:
            allowed_column_keys.add(table_name)
        if table_schema and table_name:
            allowed_column_keys.add(f"{table_schema}.{table_name}")
        if table_database and table_name:
            allowed_column_keys.add(f"{table_database}.{table_name}")
            allowed_column_keys.add(f"{table_database}..{table_name}")
        if table_database and table_schema and table_name:
            allowed_column_keys.add(f"{table_database}.{table_schema}.{table_name}")
        if table_catalog and table_schema and table_name:
            allowed_column_keys.add(f"{table_catalog}.{table_schema}.{table_name}")

    filtered_columns = {
        key: value
        for key, value in (schema.get("columns", {}) or {}).items()
        if key in allowed_column_keys
    }

    return {
        **schema,
        "tables": filtered_tables,
        "columns": filtered_columns,
    }


def schema_has_columns_for_table(schema: dict, catalog: str, schema_name: str, table_name: str) -> bool:
    """Return True if column metadata for the table is already cached."""
    if not isinstance(schema, dict):
        return False

    columns_map = schema.get("columns", {}) or {}
    catalog = strip_sql_identifier(catalog)
    schema_name = strip_sql_identifier(schema_name)
    table_name = strip_sql_identifier(table_name)
    candidates = [table_name]
    if schema_name and table_name:
        candidates.append(f"{schema_name}.{table_name}")
    if catalog and schema_name and table_name:
        candidates.append(f"{catalog}.{schema_name}.{table_name}")
    if catalog and table_name:
        candidates.append(f"{catalog}.{table_name}")
        candidates.append(f"{catalog}..{table_name}")

    for key in candidates:
        if columns_map.get(key):
            return True
    return False


def merge_sql_texts(texts: Iterable[str]) -> str:
    return "\n".join(text for text in texts if text and str(text).strip())
