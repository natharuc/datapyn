"""Transaction state and non-owning access to a block's retained DBAPI socket.

The execution connection never enters a SQLAlchemy checkout/checkin cycle.
Metadata and Python engines keep their ordinary ownership and transaction rules.
"""

from sqlalchemy.engine import Connection


class BorrowedConnection:
    """Pool-proxy facade for internal SQLAlchemy exports, without ownership.

SQL text still reaches the driver. SQLAlchemy's automatic close/commit/rollback
hooks cannot finish a transaction explicitly opened by a SQL block.
"""

    def __init__(self, raw):
        self.dbapi_connection = raw
        self.driver_connection = raw
        self.info = {}
        self.is_valid = True

    def __getattr__(self, name):
        return getattr(self.dbapi_connection, name)

    def cursor(self, *args, **kwargs):
        cursor = self.dbapi_connection.cursor(*args, **kwargs)
        # NonMarsCursor.close() only detaches its references; it does not consume
        # a scalar result's trailing DONE. This facade is used exclusively for
        # internal export/metadata operations, whose results belong to its scope.
        return _BorrowedTdsCursor(cursor) if hasattr(cursor, "_session") else cursor

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def _close_special(self, transaction_reset=False):
        pass

    def invalidate(self, exception=None):
        # Do not close a user-owned transaction because SQLAlchemy classified
        # an export exception as a disconnect. The owner observes its state.
        self.is_valid = False


def borrowed_sqlalchemy_connection(engine, raw):
    """Reuse the initialized dialect without factory, pool reset or checkout."""
    return Connection(engine, connection=BorrowedConnection(raw))


def drain_cursor_results(cursor):
    """Consume a small internal probe and its DONE tokens before releasing it."""
    while True:
        if getattr(cursor, "description", None):
            # Most probes leave only DONE, but exports may encounter metadata
            # or trigger-produced rows. Consume those without a large allocation.
            while cursor.fetchmany(5000):
                pass
        if not cursor.nextset():
            return


class _BorrowedTdsCursor:
    def __init__(self, cursor):
        object.__setattr__(self, "_cursor", cursor)
        object.__setattr__(self, "_closed", False)

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __setattr__(self, name, value):
        setattr(self._cursor, name, value)

    def close(self):
        if self._closed:
            return
        try:
            drain_cursor_results(self._cursor)
        finally:
            object.__setattr__(self, "_closed", True)
            self._cursor.close()


def transaction_state(raw, dialect):
    """Observe driver/server state without finishing or changing a transaction."""
    unknown = {"pending": None, "state": "unknown"}
    if raw is None:
        return {"pending": False, "state": "idle"}
    try:
        if dialect == "sqlserver":
            cursor = raw.cursor()
            try:
                cursor.execute("SELECT @@TRANCOUNT, XACT_STATE()")
                row = cursor.fetchone()
                drain_cursor_results(cursor)
                if not row:
                    return unknown
                count, state = int(row[0]), int(row[1])
                return {"pending": count > 0 or state != 0,
                        "state": "failed" if state == -1 else "active" if count or state else "idle",
                        "transaction_count": count, "xact_state": state}
            finally:
                cursor.close()
        if dialect == "postgresql":
            status = raw.get_transaction_status()
            # libpq PQTRANS_IDLE/ACTIVE/INTRANS/INERROR/UNKNOWN.
            return {0: {"pending": False, "state": "idle"},
                    1: {"pending": True, "state": "active"},
                    2: {"pending": True, "state": "active"},
                    3: {"pending": True, "state": "failed"}}.get(status, unknown)
        if dialect in {"mysql", "mariadb"}:
            status = raw.server_status
            if not isinstance(status, int):
                return unknown
            pending = bool(status & 1)  # SERVER_STATUS_IN_TRANS, observed in OK/EOF.
            return {"pending": pending, "state": "active" if pending else "idle"}
        if dialect == "sqlite":
            pending = raw.in_transaction
            return {"pending": pending, "state": "active" if pending else "idle"}
    except Exception:
        # Do not expose connection strings in provider errors or infer that a
        # transaction finished just because its connection could not be read.
        return unknown
    return unknown
