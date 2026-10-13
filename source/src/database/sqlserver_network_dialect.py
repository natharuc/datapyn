"""SQLAlchemy's maintained TDS dialect with isolated authentication creation."""

from sqlalchemy_pytds.dialect import MSDialect_pytds
from sqlalchemy.dialects.mssql.base import MSDialect

from .sqlserver_network_auth import connect_network


class DataPynTdsDialect(MSDialect_pytds):
    driver = "datapyn_tds"
    supports_statement_cache = True

    def connect(self, *cargs, **cparams):
        return connect_network(*cargs, **cparams)

    def set_isolation_level(self, connection, level):
        # python-tds exposes autocommit as a property, unlike pymssql.  The
        # upstream dialect currently invokes it as a function.
        connection.autocommit = level == "AUTOCOMMIT"
        if level != "AUTOCOMMIT":
            MSDialect.set_isolation_level(self, connection, level)

    def get_isolation_level_values(self, dbapi_connection):
        return (*super().get_isolation_level_values(dbapi_connection), "AUTOCOMMIT")

    def do_execute(self, cursor, statement, parameters, context=None):
        # Raw text and SQLAlchemy checkout hooks can have no execution
        # context; upstream's condition dereferences context.isupdate then.
        if context is None:
            cursor.execute(statement, parameters)
        else:
            super().do_execute(cursor, statement, parameters, context)
