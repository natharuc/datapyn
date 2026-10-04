"""Streaming, dtype-aware SQL generation from the original data values."""

from datetime import date, datetime, time
from decimal import Decimal
import math


DIALECTS = {"sqlserver", "mssql", "postgresql", "postgres", "mysql", "mariadb", "databricks", "sqlite"}


def identifier(name, dialect):
    name = str(name)
    if not name or "\0" in name:
        raise ValueError("SQL identifiers cannot be empty or contain a null character")
    if dialect in {"mysql", "mariadb", "databricks"}:
        return "`" + name.replace("`", "``") + "`"
    if dialect in {"sqlserver", "mssql"}:
        return "[" + name.replace("]", "]]") + "]"
    return '"' + name.replace('"', '""') + '"'


def missing(value):
    return value is None or type(value).__name__ in {"NAType", "NaTType"} or isinstance(value, float) and not math.isfinite(value) or isinstance(value, Decimal) and not value.is_finite()


def value_literal(value, dialect, as_text=False):
    if hasattr(value, "item") and type(value).__module__.startswith("numpy"):
        value = value.item()
    if missing(value):
        return "NULL"
    if as_text and isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        value = str(value)
    if isinstance(value, bool):
        return ("1" if value else "0") if dialect in {"sqlserver", "mssql"} else ("TRUE" if value else "FALSE")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (float, Decimal)):
        return str(value) if isinstance(value, Decimal) else repr(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        text = bytes(value).hex()
        if dialect in {"sqlserver", "mssql"}:
            return "0x" + text
        if dialect in {"postgres", "postgresql"}:
            return f"decode('{text}', 'hex')"
        return f"X'{text}'"
    text = value.isoformat() if isinstance(value, (date, datetime, time)) else str(value)
    text = text.replace("'", "''")
    if dialect in {"mysql", "mariadb", "databricks"}:
        text = text.replace("\\", "\\\\")
    return ("N" if dialect in {"sqlserver", "mssql"} else "") + f"'{text}'"


def column_type(series, dialect, control=None):
    import pandas as pd
    dtype = series.dtype
    mssql = dialect in {"sqlserver", "mssql"}
    if pd.api.types.is_bool_dtype(dtype):
        return "BIT" if mssql else "BOOLEAN"
    if pd.api.types.is_integer_dtype(dtype):
        if dialect == "sqlite" and pd.api.types.is_unsigned_integer_dtype(dtype) and dtype.itemsize == 8:
            return "TEXT"
        return "DECIMAL(20,0)" if pd.api.types.is_unsigned_integer_dtype(dtype) and dtype.itemsize == 8 else "BIGINT"
    if pd.api.types.is_float_dtype(dtype):
        return "FLOAT" if mssql else "DOUBLE" if dialect in {"mysql", "mariadb", "databricks"} else "DOUBLE PRECISION"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "DATETIMEOFFSET" if mssql and getattr(dtype, "tz", None) else "DATETIME2" if mssql else "TIMESTAMPTZ" if dialect in {"postgres", "postgresql"} and getattr(dtype, "tz", None) else "TIMESTAMP"
    example = next((value for value in series if not missing(value)), None)
    if isinstance(example, (bytes, bytearray, memoryview)):
        return "VARBINARY(MAX)" if mssql else "BYTEA" if dialect in {"postgres", "postgresql"} else "BINARY" if dialect == "databricks" else "BLOB"
    if isinstance(example, datetime):
        return "DATETIME2" if mssql else "TIMESTAMP"
    if isinstance(example, date):
        return "DATE"
    if isinstance(example, Decimal):
        scale, integer = 0, 1
        for index, value in enumerate(series):
            if control and index % 1000 == 0:
                control.check()
            if not missing(value) and not isinstance(value, Decimal):
                return "NVARCHAR(MAX)" if mssql else "STRING" if dialect == "databricks" else "TEXT"
            if isinstance(value, Decimal) and value.is_finite():
                _sign, digits, exponent = value.as_tuple()
                scale = max(scale, max(0, -exponent))
                integer = max(integer, len(digits) + exponent)
        precision = integer + scale
        limit = 38 if mssql or dialect == "databricks" else 65 if dialect in {"mysql", "mariadb"} else 1000
        if dialect != "sqlite" and precision <= limit:
            return f"DECIMAL({precision},{scale})"
    return "NVARCHAR(MAX)" if mssql else "STRING" if dialect == "databricks" else "TEXT"


def script_parts(frame, options, control):
    dialect = options.get("db_type", "sqlserver")
    if dialect not in DIALECTS:
        raise ValueError("Choose a supported SQL dialect")
    mode = options.get("sql_mode", "insert")
    if mode not in {"insert", "create", "create_insert"}:
        raise ValueError("sql_mode must be insert, create or create_insert")
    batch_size = options.get("batch_size", 1)
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 100000:
        raise ValueError("SQL batch_size must be between 1 and 100000")
    if dialect in {"sqlserver", "mssql"}:
        batch_size = min(batch_size, 1000)
    from .sql_names import table_parts
    names = table_parts(options.get("table_name", "data"), options.get("schema_name"), options.get("table_name_literal", False), schema_literal=True)
    table = ".".join(identifier(part, dialect) for part in names)
    columns = [str(column) for column in frame.columns]
    if not columns or len(set(columns)) != len(columns):
        raise ValueError("SQL export requires distinct column names")
    yield f"-- DataPyn: {len(frame)} rows x {len(columns)} columns\n"
    transaction = options.get("include_transaction", False)
    if transaction and dialect == "databricks" and mode != "insert":
        raise ValueError("Databricks SQL transactions cannot include CREATE TABLE; export DDL without a transaction")
    if transaction:
        yield "BEGIN TRANSACTION;\n" if dialect in {"sqlserver", "mssql", "sqlite", "databricks"} else "START TRANSACTION;\n" if dialect in {"mysql", "mariadb"} else "BEGIN;\n"
    types = None
    if mode in {"create", "create_insert"}:
        control.check()
        types = [column_type(frame.iloc[:, index], dialect, control) for index in range(len(columns))]
        declarations = [identifier(column, dialect) + " " + datatype for column, datatype in zip(columns, types)]
        yield f"CREATE TABLE {table} (\n    " + ",\n    ".join(declarations) + "\n);\n"
    if mode != "create":
        column_sql = ", ".join(identifier(column, dialect) for column in columns)
        rows = iter(frame.itertuples(index=False, name=None))
        done = 0
        while done < len(frame):
            control.check()
            count = min(batch_size, len(frame) - done)
            yield f"INSERT INTO {table} ({column_sql}) VALUES "
            for index in range(count):
                row = next(rows)
                yield (",\n" if index else "") + "(" + ", ".join(value_literal(value, dialect, as_text=bool(types and types[position] in {"TEXT", "NVARCHAR(MAX)", "STRING"})) for position, value in enumerate(row)) + ")"
            yield ";\n"
            done += count
            control.advance(done)
    if transaction:
        control.check()
        yield "COMMIT;\n"
    if options.get("include_go") and dialect in {"sqlserver", "mssql"}:
        yield "GO\n"
