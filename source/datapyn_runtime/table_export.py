"""Transactional batches and session-owned temporary SQL tables."""

from .export_control import ExportControl
from .sql_names import table_parts


def _typed_frame(frame, dialect, control):
    """Keep Decimal exact instead of DBAPI float conversion or unsupported binds."""
    from decimal import Decimal
    import pandas as pd
    from sqlalchemy import Numeric, Text
    from sqlalchemy.dialects.mssql import NVARCHAR
    from .sql_export import column_type, missing
    dtype, prepared = {}, frame
    for index, column in enumerate(frame.columns):
        control.check()
        series = frame.iloc[:, index]
        unsigned_sqlite = dialect == "sqlite" and str(series.dtype).lower() == "uint64"
        inferred = pd.api.types.infer_dtype(series, skipna=True) if series.dtype == object or pd.api.types.is_string_dtype(series.dtype) else None
        if dialect in {"sqlserver", "mssql"} and inferred in {"string", "unicode", "mixed", "mixed-integer", "empty"}:
            dtype[column] = NVARCHAR()
        if not unsigned_sqlite and series.dtype != object:
            continue
        example = None
        for position, value in enumerate(series):
            if position % 1000 == 0:
                control.check()
            if not missing(value):
                example = value
                break
        oversized_sqlite = False
        mixed_decimal = False
        if inferred in {"integer", "mixed", "mixed-integer"}:
            for position, value in enumerate(series):
                if position % 1000 == 0:
                    control.check()
                mixed_decimal |= isinstance(value, Decimal)
                oversized_sqlite |= dialect == "sqlite" and isinstance(value, int) and not -(2**63) <= value < 2**63
        if isinstance(example, Decimal) or mixed_decimal or unsigned_sqlite or oversized_sqlite:
            datatype = column_type(series, dialect, control)
            if datatype.startswith("DECIMAL("):
                precision, scale = map(int, datatype[8:-1].split(","))
                dtype[column] = Numeric(precision=precision, scale=scale, asdecimal=True)
            else:
                if prepared is frame:
                    prepared = frame.copy(deep=False)
                # Conversion is chunked so large object columns remain cancellable.
                converted = []
                for position, value in enumerate(series):
                    if position % 1000 == 0:
                        control.check()
                    converted.append(None if missing(value) else str(value))
                prepared[column] = converted
                dtype[column] = NVARCHAR() if dialect in {"sqlserver", "mssql"} else Text()
    return prepared, dtype


def pin_connection(connector):
    """Retain one DBAPI connection across the kernel's serialized checkouts.

    Preserve the Engine object itself: Python aliases of db_engine must also
    see the temporary table. A new StaticPool uses the configured factory
    (including authentication hooks) and its normal dialect initialization.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    engine = connector.engine
    if not isinstance(engine.pool, StaticPool):
        factory = engine.pool._creator
        options = {}
        if engine.dialect.name == "mssql" and engine.dialect.driver == "pyodbc":
            options["fast_executemany"] = getattr(engine.dialect, "fast_executemany", False)
        pinned = create_engine(engine.url, creator=factory, poolclass=StaticPool, **options)
        # SQLAlchemy's pool recreation uses this same dispatch operation. Keep
        # configured checkout/search_path/USE and on-connect driver hooks.
        pinned.pool.dispatch._update(engine.pool.dispatch, only_propagate=False)
        engine.pool.dispose()
        engine.pool = pinned.pool
        # Pool connection hooks keep their dialect owner alive.
        engine._datapyn_pinned_owner = pinned


def _temporary_exists(connection, name, dialect):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from .sql_export import identifier
    if dialect == "sqlite":
        return connection.execute(text("SELECT 1 FROM sqlite_temp_master WHERE type='table' AND name=:name"), {"name": name}).first() is not None
    if dialect in {"sqlserver", "mssql"}:
        return connection.execute(text("SELECT OBJECT_ID(:name, 'U')"), {"name": "tempdb.." + name}).scalar() is not None
    if dialect in {"postgres", "postgresql"}:
        return connection.execute(text("SELECT to_regclass(:name)"), {"name": 'pg_temp.' + identifier(name, dialect)}).scalar() is not None
    if dialect in {"mysql", "mariadb"}:
        try:
            row = connection.exec_driver_sql("SHOW CREATE TABLE " + identifier(name, dialect)).first()
            return row is not None and "CREATE TEMPORARY TABLE" in str(row[1]).upper()
        except DBAPIError as exc:
            if getattr(exc.orig, "args", [None])[0] == 1146:
                return False
            raise
    if dialect == "databricks":
        rows = connection.exec_driver_sql("SHOW TABLES").mappings()
        return any(row.get("tableName") == name and row.get("isTemporary") in {True, "true"} for row in rows)
    raise ValueError("Temporary tables are unsupported by this SQL dialect")


def refresh_temporary_tables(connector):
    """Validate exported temporary names once after DDL, never per keystroke."""
    registry = getattr(connector, "_datapyn_temporary_tables", None)
    if not registry:
        return
    try:
        dialect = connector.db_type
        with connector.engine.connect() as connection:
            if dialect == "databricks":
                existing = {row.get("tableName") for row in connection.exec_driver_sql("SHOW TABLES").mappings()
                            if row.get("isTemporary") in {True, "true"}}
                removed = [name for name in registry if name not in existing]
            else:
                removed = [name for name in registry if not _temporary_exists(connection, name, dialect)]
        for name in removed:
            registry.pop(name, None)
        connector.has_temporary_tables = bool(registry)
    except Exception:
        # Failed metadata access does not prove a temporary table disappeared.
        # Retain the physical session until the next successful DDL refresh.
        return


def export_table(frame, params, connector, progress=None, cancelled=None):
    from sqlalchemy import Column, MetaData, Table
    from pandas.io.sql import SQLDatabase, SQLTable
    if connector is None or getattr(connector, "engine", None) is None:
        raise ConnectionError("Connect to the destination database first")
    names = table_parts(params.get("table"), params.get("schema"))
    if any(len(name) > 255 for name in names):
        raise ValueError("Table and schema names may contain at most 255 characters")
    name, schema = names[-1], ".".join(names[:-1]) or None
    dialect = getattr(connector, "db_type", connector.engine.dialect.name)
    temporary = bool(params.get("temporary", False)) or dialect in {"sqlserver", "mssql"} and name.startswith("#")
    if temporary:
        if schema:
            raise ValueError("Temporary tables use a single name without a schema")
        if dialect in {"sqlserver", "mssql"} and not name.startswith("#"):
            name = "#" + name
        if dialect not in {"sqlserver", "mssql"} and name.startswith("#"):
            raise ValueError("The # prefix is reserved for SQL Server temporary tables")
    mode = params.get("if_exists", "fail")
    if mode not in {"fail", "append", "replace"}:
        raise ValueError("if_exists must be fail, append or replace")
    chunksize = params.get("chunksize", 1000)
    if isinstance(chunksize, bool) or not isinstance(chunksize, int) or not 100 <= chunksize <= 100000:
        raise ValueError("chunksize must be between 100 and 100000")
    columns = [str(column) for column in frame.columns]
    if not columns or len(columns) != len(set(columns)):
        raise ValueError("Table export requires distinct column names")
    control = ExportControl(len(frame), progress, cancelled)
    control.check()
    frame, dtype = _typed_frame(frame, dialect, control)
    if temporary:
        pin_connection(connector)
    done = 0
    def insert_batch(sql_table, connection, keys, iterator):
        nonlocal done
        control.check()
        rows = [dict(zip(keys, row)) for row in iterator]
        if rows:
            # SQLAlchemy binds original values with pandas' inferred SQL types.
            # Executemany avoids the SQL Server 2,100 parameter ceiling.
            connection.execute(sql_table.table.insert(), rows)
        done += len(rows)
        control.advance(done)
        return len(rows)
    with connector.engine.begin() as connection:
        if not temporary:
            frame.to_sql(name, connection, schema=schema, if_exists=mode, index=False,
                         chunksize=chunksize, method=insert_batch, dtype=dtype or None)
        else:
            exists = _temporary_exists(connection, name, dialect)
            if exists:
                connector.has_temporary_tables = True
            if exists and mode == "fail":
                raise ValueError(f"Temporary table {name} already exists")
            qualified_schema = "temp" if dialect == "sqlite" else "pg_temp" if dialect in {"postgres", "postgresql"} else None
            sql_table = SQLTable(name, SQLDatabase(connection), frame=frame, index=False, dtype=dtype or None)
            table = Table(name, MetaData(), *(Column(column.name, column.type) for column in sql_table.table.columns),
                          schema=qualified_schema,
                          prefixes=["TEMPORARY"] if dialect not in {"sqlserver", "mssql"} else [])
            if exists and mode == "replace":
                if dialect in {"mysql", "mariadb", "databricks"}:
                    from .sql_export import identifier
                    connection.exec_driver_sql("DROP TEMPORARY TABLE " + identifier(name, dialect))
                else:
                    table.drop(connection, checkfirst=False)
                exists = False
            if not exists:
                # PostgreSQL CREATE TEMP cannot specify pg_temp; target it only
                # when inserting/dropping after creation. SQLite accepts temp.
                if dialect == "databricks":
                    # This dialect adds USING DELTA/TBLPROPERTIES to CreateTable;
                    # Databricks forbids both on session temporary tables.
                    from .sql_export import identifier
                    declarations = ", ".join(identifier(column.name, dialect) + " " + column.type.compile(dialect=connector.engine.dialect) for column in table.columns)
                    connection.exec_driver_sql("CREATE TEMPORARY TABLE " + identifier(name, dialect) + " (" + declarations + ")")
                else:
                    creation = Table(name, MetaData(), *(Column(column.name, column.type) for column in table.columns),
                                     prefixes=table._prefixes)
                    creation.create(connection, checkfirst=False)
                connector.has_temporary_tables = True
            # pandas' insertion conversion correctly maps pd.NA/NaT to None
            # and NumPy/date values without serializing them through JSON.
            sql_table.table = table
            sql_table.insert(chunksize=chunksize, method=insert_batch)
        control.check()
    if temporary:
        registry = getattr(connector, "_datapyn_temporary_tables", {})
        registry[name] = {"schema": "temp" if dialect == "sqlite" else "", "columns": [
            {"name": column.name, "dtype": str(column.type), "type": str(column.type), "nullable": True, "default": None}
            for column in table.columns]}
        connector._datapyn_temporary_tables = registry
    control.complete()
    return {"table": name, "schema": schema, "row_count": len(frame), "if_exists": mode,
            "temporary": temporary}
