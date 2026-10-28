"""Bounded, provider-neutral transport classification with no network I/O.

An execution may have reached the server even when the client received no
response. These errors describe recovery of a connection, never permission to
repeat a submitted statement.
"""

from __future__ import annotations

import errno
import re
import socket
import ssl


class ConnectionLostError(ConnectionError):
    code = "connection_lost"

    def __init__(self, message=None, *, acknowledgement_required=False, submitted=False,
                 session_state_lost=True):
        if message is None:
            message = ("A conexão foi interrompida durante a execução. O comando não foi repetido; "
                       "confira seu resultado antes de executá-lo novamente." if submitted else
                       "A conexão com o banco foi interrompida. Reconecte para continuar.")
        super().__init__(message)
        self.details = {"acknowledgement_required": bool(acknowledgement_required),
                        "submitted": bool(submitted), "session_state_lost": bool(session_state_lost)}


_NETWORK_ERRNOS = {errno.EPIPE, errno.ECONNRESET, errno.ECONNABORTED, errno.ENOTCONN,
                   errno.ESHUTDOWN, errno.ETIMEDOUT, errno.ECONNREFUSED, errno.EHOSTUNREACH,
                   errno.ENETUNREACH, errno.ENETDOWN, 10050, 10051, 10052, 10053, 10054,
                   10057, 10058, 10060, 10061, 10064, 10065}
_SQLSTATE = re.compile(r"^(?:\[)?([A-Z0-9]{5})(?:\]|$)|\bSQLSTATE\s*[:=]?\s*\[?([A-Z0-9]{5})", re.I)
_CANCEL_STATES = {"HY008", "57014"}
_POSTGRES_SHUTDOWN = {"57P01", "57P02", "57P03"}


def _message(error):
    try:
        return str(error).lower()[:2048]
    except Exception:
        return ""


def _error_chain(error):
    seen, pending = set(), [error]
    while pending and len(seen) < 12:
        current = pending.pop(0)
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        # __context__ may be a handled failure from an earlier fallback. Only
        # an explicit cause (or a provider's documented wrapper) belongs to the
        # current failure: a syntax/timeout error must not inherit an old reset.
        pending.extend((getattr(current, "orig", None), current.__cause__))
        # Databricks RequestError retains the original network exception as a
        # positional argument, while its JSON context only contains str(error).
        pending.extend(value for value in current.args[:4] if isinstance(value, BaseException))
        context = getattr(current, "context", None)
        if isinstance(context, dict):
            pending.append(context.get("original-exception"))


def is_read_only_query(query, db_type=""):
    """Conservatively recognize a single ordinary read, never authorize replay.

    This only decides whether losing an *idle* manual session needs a
    transaction-loss confirmation. Unknown functions, session mutations,
    locking reads, procedural SQL and multi-command scripts stay conservative.
    """
    if not isinstance(query, str) or not query.strip() or len(query) > 128 * 1024:
        return False
    from datapyn_runtime.sql_context import lexical_spans, sql_code_mask
    if any(not closed for _start, _end, _kind, closed in lexical_spans(query, db_type)):
        return False
    code = sql_code_mask(query, db_type, identifiers=True)
    if re.search(r"\b(?:INTO|OUTFILE|DUMPFILE|UPDLOCK|XLOCK|HOLDLOCK|TABLOCKX|NEXT\s+VALUE|GO)\b", code, re.I):
        return False
    try:
        from sqlglot import parse, exp
        from src.services.syntax_validator import _silence_sqlglot_warnings
        dialect = {"sqlserver": "tsql", "postgresql": "postgres", "mariadb": "mysql"}.get(db_type, db_type or "tsql")
        with _silence_sqlglot_warnings():
            statements = [node for node in parse(query, read=dialect) if node is not None]
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.SetOperation)):
            return False
        allowed_functions = {"ABS", "AVG", "COUNT", "MIN", "MAX", "SUM", "COALESCE", "NULLIF",
                             "CAST", "TRY_CAST", "LOWER", "UPPER", "LENGTH", "ROUND", "CONCAT",
                             "SUBSTRING", "TRIM", "REPLACE", "FLOOR", "CEIL", "ROW_NUMBER", "RANK",
                             "DENSE_RANK", "CURRENT_DATE", "CURRENT_TIMESTAMP", "DATE", "DATE_TRUNC",
                             "DATE_ADD", "DATE_DIFF", "IF", "CASE"}
        for node in statements[0].walk():
            if isinstance(node, (exp.DML, exp.DDL, exp.Into, exp.Lock, exp.Command, exp.Parameter)):
                return False
            if isinstance(node, exp.Func) and (isinstance(node, exp.Anonymous) or node.sql_name() not in allowed_functions):
                return False
        return True
    except Exception:
        return False


def classify_connection_error(error, db_type=""):
    """Only classify evidence of a lost/unavailable physical transport.

    Authentication, SQL errors, cancellation, a statement timeout and a locked
    SQLite file do not on their own justify replacing a live session.
    """
    dialect = str(db_type or "").lower()
    chain = list(_error_chain(error))
    for item in chain:
        if isinstance(item, ssl.SSLCertVerificationError) or any(token in _message(item) for token in (
                "certificate verify failed", "certificate verification failed", "hostname mismatch", "self signed certificate")):
            return False
        code = getattr(item, "code", "")
        if isinstance(code, str) and code.startswith(("transaction_", "destructive_sql_")):
            return False
        if code in {"ssh_auth_failed", "ssh_cancelled", "ssh_config_invalid", "ssh_key_invalid",
                    "ssh_host_key_changed", "ssh_host_key_unknown", "ssh_trust_invalid"}:
            return False
        states = [getattr(item, "sqlstate", None), getattr(item, "pgcode", None)]
        first = item.args[0] if item.args else None
        if isinstance(first, str):
            match = _SQLSTATE.search(first[:1024])
            if match:
                states.append(match.group(1) or match.group(2))
        if any(str(state or "").upper() in _CANCEL_STATES for state in states):
            return False
        if any(str(state or "").upper().startswith("28") for state in states):
            return False
        if any(str(state or "").upper() == "08004" or
               str(state or "").upper().startswith(("22", "23", "25", "2D", "3D", "3F", "40", "42"))
               for state in states):
            # Server rejection, permissions, missing objects, syntax and
            # transaction failures are SQL outcomes, not broken transports.
            return False
        context = getattr(item, "context", None)
        if isinstance(context, dict) and str(context.get("http-code", "")) in {"401", "403"}:
            return False
    for item in chain:
        if isinstance(item, ConnectionLostError):
            return True
        code = getattr(item, "code", "")
        if code == "ssh_connection_lost":
            return True
        if isinstance(item, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return True
        if isinstance(item, socket.gaierror) and item.errno == socket.EAI_AGAIN:
            return True
        if isinstance(item, OSError) and (item.errno in _NETWORK_ERRNOS or getattr(item, "winerror", None) in _NETWORK_ERRNOS):
            return True
        states = [getattr(item, "sqlstate", None), getattr(item, "pgcode", None)]
        first = item.args[0] if item.args else None
        if isinstance(first, str):
            match = _SQLSTATE.search(first[:1024])
            if match:
                states.append(match.group(1) or match.group(2))
        if any(str(state or "").upper().startswith("08") or str(state or "").upper() in _POSTGRES_SHUTDOWN for state in states):
            return True
        if dialect in {"mysql", "mariadb"} and isinstance(first, int) and first in {2002, 2003, 2006, 2013, 2055}:
            return True
        message = _message(item)
        if dialect == "sqlite" and "cannot operate on a closed database" in message:
            return True
        if dialect == "sqlserver" and any(token in message for token in (
                "attempt to use a closed connection", "the cursor's connection has been closed")):
            return True
        if dialect == "sqlserver" and type(item).__module__.startswith("pytds") and (
                type(item).__name__ == "ClosedConnectionError" or message in {"server closed connection", "stream closed"}
                or "unexpected eof while reading smp header" in message):
            return True
        if dialect == "postgresql" and any(token in message for token in (
                "server closed the connection unexpectedly", "connection already closed",
                "connection not open", "ssl connection has been closed unexpectedly",
                "ssl syscall error: eof detected", "could not receive data from server",
                "could not send data to server", "terminating connection due to administrator command")):
            return True
        if dialect in {"mysql", "mariadb"} and any(token in message for token in (
                "server has gone away", "lost connection to mysql server", "connection was killed")):
            return True
        if dialect == "databricks" and any(token in message for token in (
                "invalid sessionhandle", "invalid session handle", "session has been closed",
                "session is closed", "invalid_handle.session_closed", "invalid_handle.session_changed",
                "invalid_session_id", "session not found", "cannot create cursor from closed connection")):
            return True
    return False
