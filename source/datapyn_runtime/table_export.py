"""Transactional batches and session-owned temporary SQL tables."""

from .export_control import ExportControl
from .sql_names import table_parts


# Client batching bounds, not claims about a server's maximum SQL size.
DATABRICKS_BATCH_ROWS = 1000
DATABRICKS_BATCH_PARAMETERS = 10000
DATABRICKS_BATCH_BYTES = 4 * 1024 * 1024


def _databricks_insert_batches(table, connection, keys, iterator, control, advance):
    """Send one parameterized multi-row INSERT per bounded sub-batch.

    Databricks Cursor.executemany sends N sequential requests, not one batch.
    Values stay SQLAlchemy binds; no string interpolation or duplicated frame.
    """
    batch, payload, inserted = [], 0, 0
    max_rows = max(1, min(DATABRICKS_BATCH_ROWS, DATABRICKS_BATCH_PARAMETERS // len(keys)))
    parameter_overhead = sum(len(str(key).encode("utf-8")) + 64 for key in keys)

    def flush():
        nonlocal batch, payload, inserted
        if not batch:
            return
        control.check()
        control.notify(control.current, "writing", force=True)
        connection.execute(table.insert().values(batch))
        inserted += len(batch)
        advance(len(batch))
        batch, payload = [], 0

    for row in iterator:
        control.check()
        # Includes parameter names/types and conservative serialization room.
        size = sum(len(value.encode("utf-8")) if isinstance(value, str) else len(value) if isinstance(value, (bytes, bytearray, memoryview)) else len(str(value)) for value in row) + parameter_overhead
        if batch and (len(batch) >= max_rows or payload + size > DATABRICKS_BATCH_BYTES):
            flush()
        batch.append(dict(zip(keys, row)))
        payload += size
    flush()
    return inserted


def _databricks_temp_unsupported(error):
    message = str(getattr(error, "orig", error)).lower()
    return ("temporary" in message and any(value in message for value in ("not supported", "unsupported", "not implemented"))
            or "parse_syntax_error" in message and any(value in message for value in ("'temporary'", "'temp'")))


def _databricks_cancel_scope(engine, control):
    """Cancel an active SDK cursor from its documented cross-thread API."""
    from contextlib import contextmanager
    import logging
    import threading
    import time
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @contextmanager
    def scope():
        if not isinstance(engine, Engine):
            yield
            return
        stopped = threading.Event()
        lock = threading.Lock()
        active = {"cursor": None}
        def before_cursor_execute(_connection, cursor, _statement, _params, _context, _many):
            control.check()
            with lock:
                active["cursor"] = cursor
        def after_cursor_execute(*_args):
            with lock:
                active["cursor"] = None
        def handle_error(_context):
            after_cursor_execute()
        def monitor():
            tracked_cursor, attempts, retry_at, completed = None, 0, 0.0, False
            backoff = (.1, .3, .9)
            while not stopped.wait(.05):
                if not control.cancelled():
                    continue
                with lock:
                    cursor = active["cursor"]
                if cursor is None:
                    continue
                if cursor is not tracked_cursor:
                    tracked_cursor, attempts, completed = cursor, 0, False
                    retry_at = time.monotonic() + backoff[0]
                if completed or attempts >= len(backoff) or time.monotonic() < retry_at:
                    continue
                # The handle appears once the server accepts the request. A
                # cancel before then is a no-op, so wait for the real handle.
                if hasattr(cursor, "active_command_id") and cursor.active_command_id is None:
                    continue
                cancel = getattr(cursor, "cancel", None)
                if callable(cancel):
                    # Re-check after waiting for the backoff: no cancellation
                    # of a completed cursor or of a later export operation.
                    with lock:
                        if active["cursor"] is not cursor:
                            continue
                    if stopped.is_set() or not control.cancelled():
                        continue
                    attempts += 1
                    try:
                        cancel()
                        completed = True
                    except Exception as exc:
                        logging.getLogger(__name__).warning("Databricks export cancellation failed: %s", type(exc).__name__)
                        if attempts < len(backoff):
                            retry_at = time.monotonic() + backoff[attempts]
        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        event.listen(engine, "after_cursor_execute", after_cursor_execute)
        event.listen(engine, "handle_error", handle_error)
        worker = threading.Thread(target=monitor, name="datapyn-table-export-cancel", daemon=True)
        worker.start()
        try:
            yield
        except Exception:
            if control.cancelled() and control.current:
                from .export_control import ExportCancelled
                control.notify(control.current, "cancelled", force=True)
                raise ExportCancelled(f"Export cancelled. Databricks keeps previously completed batches ({control.current} rows).") from None
            control.check()
            raise
        finally:
            stopped.set()
            after_cursor_execute()
            event.remove(engine, "before_cursor_execute", before_cursor_execute)
            event.remove(engine, "after_cursor_execute", after_cursor_execute)
            event.remove(engine, "handle_error", handle_error)
            worker.join(timeout=.2)
    return scope()


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
        unsigned_sqlite = dialect == "sqlite" and pd.api.types.is_unsigned_integer_dtype(series.dtype) and series.dtype.itemsize == 8
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
        import re
        from .sql_export import value_literal
        # Spark's SHOW matcher expands raw '*' and splits raw '|', even if
        # regex-escaped. Hex escapes keep these valid name characters literal.
        pattern = re.escape(name).replace(r"\*", r"\x2a").replace(r"\|", r"\x7c")
        rows = connection.exec_driver_sql("SHOW TABLES LIKE " + value_literal(pattern, dialect)).mappings()
        return any(str(row.get("tableName", "")).casefold() == name.casefold() and str(row.get("isTemporary", "")).lower() == "true" for row in rows)
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
                existing = {str(row.get("tableName", "")).casefold() for row in connection.exec_driver_sql("SHOW TABLES").mappings()
                            if str(row.get("isTemporary", "")).lower() == "true"}
                removed = [name for name in registry if name.casefold() not in existing]
            else:
                removed = [name for name in registry if not _temporary_exists(connection, name, dialect)]
        for name in removed:
            registry.pop(name, None)
        connector.has_temporary_tables = bool(registry)
    except Exception:
        # Failed metadata access does not prove a temporary table disappeared.
        # Retain the physical session until the next successful DDL refresh.
        return


def _register_temporary_table(connector, name, table, dialect):
    registry = dict(getattr(connector, "_datapyn_temporary_tables", {}))
    if dialect == "databricks":
        registry = {key: value for key, value in registry.items() if key.casefold() != name.casefold()}
    registry[name] = {"schema": "temp" if dialect == "sqlite" else "", "columns": [
        {"name": column.name, "dtype": str(column.type), "type": str(column.type), "nullable": True, "default": None}
        for column in table.columns]}
    connector._datapyn_temporary_tables = registry
    connector.has_temporary_tables = True


def _forget_databricks_temporary_table(connector, name):
    registry = {key: value for key, value in getattr(connector, "_datapyn_temporary_tables", {}).items()
                if key.casefold() != name.casefold()}
    connector._datapyn_temporary_tables = registry
    connector.has_temporary_tables = bool(registry)


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
        if dialect == "databricks":
            def advance(count):
                nonlocal done
                done += count
                # A cancellation arriving after execute returned cannot undo
                # this completed Databricks batch. Preserve its actual count.
                control.current = done
                control.advance(done)
            return _databricks_insert_batches(sql_table.table, connection, keys, iterator, control, advance)
        rows = [dict(zip(keys, row)) for row in iterator]
        if rows:
            # SQLAlchemy binds original values with pandas' inferred SQL types.
            # Executemany avoids the SQL Server 2,100 parameter ceiling.
            connection.execute(sql_table.table.insert(), rows)
        done += len(rows)
        control.advance(done)
        return len(rows)
    from contextlib import nullcontext
    cancel_scope = _databricks_cancel_scope(connector.engine, control) if dialect == "databricks" else nullcontext()
    with cancel_scope, connector.engine.begin() as connection:
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
                    if dialect == "databricks":
                        _forget_databricks_temporary_table(connector, name)
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
                    try:
                        connection.exec_driver_sql("CREATE TEMPORARY TABLE " + identifier(name, dialect) + " (" + declarations + ")")
                    except Exception as exc:
                        if _databricks_temp_unsupported(exc):
                            raise ValueError("This Databricks compute does not support temporary tables. Use a compatible SQL warehouse or Databricks Runtime 18.1+ (not Dedicated/single-user compute), or export to a permanent table. No permanent table was created.") from exc
                        raise
                else:
                    creation = Table(name, MetaData(), *(Column(column.name, column.type) for column in table.columns),
                                     prefixes=table._prefixes)
                    creation.create(connection, checkfirst=False)
                connector.has_temporary_tables = True
            if dialect == "databricks":
                # Databricks autocommits DDL and each INSERT. A table created
                # before a later failure/cancel still exists in this session
                # and must remain explorable with its columns.
                _register_temporary_table(connector, name, table, dialect)
            # pandas' insertion conversion correctly maps pd.NA/NaT to None
            # and NumPy/date values without serializing them through JSON.
            sql_table.table = table
            sql_table.insert(chunksize=chunksize, method=insert_batch)
        control.check()
    if temporary:
        _register_temporary_table(connector, name, table, dialect)
    control.complete()
    return {"table": name, "schema": schema, "row_count": len(frame), "if_exists": mode,
            "temporary": temporary}
