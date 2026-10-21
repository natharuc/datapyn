"""One-use SQL review tickets and runtime checks for managed database execution."""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import json
import secrets
import threading
import time

from .sql_safety_settings import settings_get, settings_path

MAX_TICKETS = 256
TICKET_TTL = 300
MAX_CODE_BYTES = 1024 * 1024
CONTEXT_MUTATIONS = {"execution.run", "connection.connect", "connection.disconnect", "explorer.use_database",
                     "result.export_table", "data.import", "variable.delete", "variable.archive.import", "snapshot.restore"}
CONTEXT_ACTIVATIONS = {"execution.run", "connection.connect", "connection.disconnect", "explorer.use_database",
                       "schema.get", "language.context", "explorer.list", "explorer.details", "explorer.query",
                       "explorer.snapshot", "result.export_table"}


class ConfirmationRequiredError(Exception):
    code = "destructive_sql_confirmation_required"

    def __init__(self):
        super().__init__("Confirme os comandos SQL destrutivos antes de executar. A confirmação é válida somente para o código e destino revisados.")


def request_risks(method, params, db_type=""):
    """Render only parameters; never evaluate Python or open a database."""
    from .sql_safety import analyze_python, analyze_sql
    if method == "result.export_table":
        if params.get("if_exists", "fail") != "replace":
            return []
        target = ".".join(str(params.get(key) or "") for key in ("schema", "table")).strip(".")
        return [{"statement": 1, "operation": "REPLACE TABLE", "target": target, "has_where": False,
                 "unfiltered": True, "preview": ("REPLACE TABLE " + target)[:500]}]
    if method != "execution.run":
        raise ValueError("SQL review supports execution.run or result.export_table")
    code, language = params.get("code"), params.get("language")
    if language not in {"sql", "python"} or not isinstance(code, str) or len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise ValueError("language must be sql/python and code at most 1 MiB")
    from src.core.parameter_settings import use_shared_parameter_delimiter
    with use_shared_parameter_delimiter(params.get("shared_delimiter", "{{name}}")):
        if language == "python":
            if params.get("shared_parameters"):
                from src.utils.sql_parameter_service import prepare_python_code_with_shared_parameters, SqlParameterError
                try:
                    code = prepare_python_code_with_shared_parameters(code, params["shared_parameters"])
                except SqlParameterError:
                    pass  # The execution reports the existing parameter error before running code.
            return analyze_python(code, db_type)
        parameters = params.get("parameters")
        if parameters is None:
            parameters = (params.get("sql_parameters") or []) + (params.get("shared_parameters") or [])
        if isinstance(parameters, list) and parameters:
            from src.utils.sql_parameter_service import prepare_generic_sql, SqlParameterError
            try:
                code = prepare_generic_sql(code, parameters).query
            except SqlParameterError:
                pass
        return analyze_sql(code, db_type)


def _fingerprint(method, params, binding):
    from .connection_catalog import without_secrets
    public = {key: value for key, value in params.items() if not key.startswith("_") and key not in {"confirmation_token", "method"}}
    if isinstance(public.get("config"), dict):
        public["config"] = without_secrets(public["config"])
    # SQL bind names such as "token" or "password" are still part of the
    # reviewed query. Only connection credentials are excluded, not SQL values.
    material = {"method": method, "params": public, "binding": without_secrets(binding)}
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).digest()


class SqlSafetyGuard:
    def __init__(self, path=None, clock=None):
        self.path = path
        self.clock = clock or time.monotonic
        self.tickets = OrderedDict()
        self.lock = threading.RLock()

    def _enabled(self):
        return settings_get(self.path)["confirm_destructive_sql"]

    def _expire(self, now):
        while self.tickets and next(iter(self.tickets.values()))[0] <= now:
            self.tickets.popitem(last=False)

    def review(self, method, params, binding):
        enabled = self._enabled()
        risks = request_risks(method, params, binding.get("db_type", "")) if enabled else []
        result = {"confirmation_required": bool(risks), "risks": risks}
        if risks:
            token, now = secrets.token_urlsafe(32), self.clock()
            digest = _fingerprint(method, params, binding)
            with self.lock:
                self._expire(now)
                self.tickets[token] = (now + TICKET_TTL, digest)
                while len(self.tickets) > MAX_TICKETS:
                    self.tickets.popitem(last=False)
            result["confirmation_token"] = token
        return result

    def authorize(self, method, params, binding, *, allow_ticket=True):
        enabled = self._enabled()
        risks = request_risks(method, params, binding.get("db_type", "")) if enabled else []
        authorized = False
        if risks:
            token = params.get("confirmation_token") if allow_ticket else None
            with self.lock:
                self._expire(self.clock())
                issued = self.tickets.pop(token, None) if isinstance(token, str) else None
            if issued is None or not secrets.compare_digest(issued[1], _fingerprint(method, params, binding)):
                raise ConfirmationRequiredError()
            authorized = True
        return {"_sql_safety_enabled": enabled, "_sql_safety_authorized": authorized,
                "_sql_safety_settings_path": str(self.path or settings_path())}


def kernel_policy(params):
    """Enabling protection also covers work queued before the setting changed."""
    current = settings_get(params.get("_sql_safety_settings_path"))["confirm_destructive_sql"]
    return current or params.get("_sql_safety_enabled") is True, params.get("_sql_safety_authorized") is True


def require_kernel_review(method, params, db_type=""):
    enabled, authorized = kernel_policy(params)
    if enabled and not authorized and request_risks(method, params, db_type):
        raise ConfirmationRequiredError()
    return enabled, authorized


def require_query_review(query, enabled, authorized, db_type=""):
    if enabled and not authorized:
        from .sql_safety import analyze_sql
        if not isinstance(query, str) or analyze_sql(query, db_type):
            raise ConfirmationRequiredError()


@contextmanager
def guard_python_engines(enabled, authorized):
    """Guard SQLAlchemy engines during this isolated kernel's Python block.

    Python is not a sandbox. This covers DataPyn's SQLAlchemy execution paths,
    including cached engines/connections and pandas to_sql replacement SQL.
    """
    if not enabled or authorized:
        yield
        return
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    def before_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        dialect = connection.engine.dialect.name
        require_query_review(statement, True, False, "sqlserver" if dialect == "mssql" else dialect)

    event.listen(Engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield
    finally:
        event.remove(Engine, "before_cursor_execute", before_cursor_execute)
