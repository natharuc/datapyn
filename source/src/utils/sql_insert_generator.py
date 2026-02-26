"""
Generates SQL INSERT statements from a pandas DataFrame.

Supports multiple database dialects (SQL Server, PostgreSQL, MySQL, MariaDB,
Databricks, SQLite) with proper identifier quoting and value escaping.
"""

import math
from typing import Optional

import numpy as np
import pandas as pd


def quote_identifier(name: str, db_type: str) -> str:
    """Quote a SQL identifier based on the database dialect.

    Args:
        name: Identifier name (table or column name)
        db_type: Database type (sqlserver, postgresql, mysql, mariadb, databricks, sqlite)

    Returns:
        Quoted identifier string
    """
    if db_type in ("mysql", "mariadb"):
        return f"`{name}`"
    if db_type in ("sqlserver", "mssql"):
        return f"[{name}]"
    if db_type == "databricks":
        return f"`{name}`"
    # postgresql, sqlite, and others use ANSI double quotes
    return f'"{name}"'


def format_value(value, db_type: str) -> str:
    """Format a Python value as a SQL literal.

    Handles None/NaN -> NULL, strings -> escaped quotes, booleans,
    dates, and numeric types.

    Args:
        value: Python value to format
        db_type: Database type for dialect-specific formatting

    Returns:
        SQL literal string
    """
    if value is None:
        return "NULL"

    if isinstance(value, (float, np.floating)) and (math.isnan(value) or math.isinf(value)):
        return "NULL"

    if isinstance(value, (bool, np.bool_)):
        if db_type in ("sqlserver", "mssql"):
            return "1" if value else "0"
        return "TRUE" if value else "FALSE"

    if isinstance(value, (int, np.integer)):
        return str(value)

    if isinstance(value, (float, np.floating)):
        return repr(float(value))

    if isinstance(value, bytes):
        hex_str = value.hex()
        if db_type in ("sqlserver", "mssql"):
            return f"0x{hex_str}"
        if db_type in ("postgresql",):
            return f"'\\x{hex_str}'"
        return f"X'{hex_str}'"

    if hasattr(value, "isoformat"):
        iso = value.isoformat()
        return f"'{iso}'"

    # Default: treat as string, escape single quotes
    text = str(value)
    text = text.replace("'", "''")
    if db_type in ("mysql", "mariadb", "databricks"):
        text = text.replace("\\", "\\\\")
    return f"'{text}'"


def generate_inserts(
    df: pd.DataFrame,
    table_name: str,
    db_type: str = "sqlserver",
    batch_size: int = 1,
    schema_name: Optional[str] = None,
    include_go: bool = False,
) -> str:
    """Generate SQL INSERT statements from a DataFrame.

    Args:
        df: Source DataFrame
        table_name: Target table name
        db_type: Database dialect (sqlserver, postgresql, mysql, mariadb, databricks, sqlite)
        batch_size: Number of rows per INSERT (multi-row INSERT). Use 1 for
                    single-row INSERTs (max compatibility). Use >1 for faster
                    bulk INSERTs (supported by all modern DBs).
        schema_name: Optional schema name to qualify the table
        include_go: If True, add GO after every N inserts (SQL Server batch separator)

    Returns:
        String containing all INSERT statements
    """
    if df.empty:
        return f"-- Empty DataFrame, no INSERT statements generated for '{table_name}'\n"

    q = lambda name: quote_identifier(name, db_type)

    # Build qualified table name
    if schema_name:
        qualified_table = f"{q(schema_name)}.{q(table_name)}"
    else:
        qualified_table = q(table_name)

    # Column list
    columns = df.columns.tolist()
    cols_sql = ", ".join(q(c) for c in columns)

    lines = []
    lines.append(f"-- INSERT statements for {qualified_table}")
    lines.append(f"-- Generated from DataFrame: {len(df)} rows x {len(columns)} columns")
    lines.append("")

    if batch_size <= 1:
        # Single-row INSERTs
        for _, row in df.iterrows():
            values = ", ".join(format_value(row[col], db_type) for col in columns)
            lines.append(f"INSERT INTO {qualified_table} ({cols_sql}) VALUES ({values});")
    else:
        # Multi-row INSERTs
        for start in range(0, len(df), batch_size):
            chunk = df.iloc[start : start + batch_size]
            lines.append(f"INSERT INTO {qualified_table} ({cols_sql})")
            lines.append("VALUES")
            row_strs = []
            for _, row in chunk.iterrows():
                values = ", ".join(format_value(row[col], db_type) for col in columns)
                row_strs.append(f"    ({values})")
            lines.append(",\n".join(row_strs) + ";")
            lines.append("")

    if include_go and db_type in ("sqlserver", "mssql"):
        lines.append("GO")

    lines.append("")
    return "\n".join(lines)
