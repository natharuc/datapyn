"""Protocol error envelopes shared by isolated runtime workers."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import re
import sys
import traceback

from .connection_catalog import without_secrets


_TITLES = {
    "permission": "Acesso negado", "authentication": "Falha de autenticação",
    "not_found": "Objeto não encontrado", "syntax": "Erro de sintaxe",
    "timeout": "Tempo limite excedido", "network": "Conexão interrompida",
    "cancelled": "Operação cancelada", "python": "Erro no Python",
    "constraint": "Restrição dos dados", "data": "Dados inválidos",
    "file": "Erro de arquivo", "internal": "Não foi possível concluir a operação",
}
_STATE = re.compile(r"(?:^|\[|SQLSTATE\s*[:=]?\s*)([0-9A-Z]{5})(?:\]|$|\s)", re.I)
_WRAPPER = re.compile(r"^(?:Error (?:executing|streaming|changing|connecting)[^:]{0,70}:\s*)+", re.I)
_PROVIDER_PREFIX = re.compile(r"^(?:\[[^\]\r\n]{1,140}\]\s*)+")
_SENSITIVE = re.compile(
    r"\b(?:password|pwd|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|"
    r"authorization|connection[_ -]?string)[\"']?\s*[:=]\s*"
    r"(?:\{[^}]*\}|\"[^\"]*\"|'[^']*'|[^;\s,]+)", re.I)
_INTERNAL_LOGGERS = ("src.", "datapyn_runtime", "sqlalchemy", "databricks", "pyodbc", "pytds",
                     "pymysql", "psycopg", "paramiko", "azure", "urllib3", "requests")


def safe_exception_attribute(error, name, default=None):
    try:
        return getattr(error, name, default)
    except Exception:
        return default


def exception_code(error, default=""):
    code = safe_exception_attribute(error, "code", default)
    return code[:128] if isinstance(code, str) else default


def _arguments(error):
    args = safe_exception_attribute(error, "args", ())
    return args[:8] if isinstance(args, (tuple, list)) else ()


def _text(value):
    try:
        return str(value)[:32_768]
    except Exception:
        return type(value).__name__


def _safe_text(value, limit=8192):
    """Remove transport diagnostics that can contain statements or secrets."""
    text = _text(value)
    # SQLAlchemy appends statement/parameter values to str(DBAPIError). Never
    # include those annotations, even in the opt-in local technical details.
    text = re.split(r"\[\s*(?:SQL|parameters)\s*:", text, maxsplit=1, flags=re.I)[0]
    text = re.split(r"(?:\r?\n)\s*(?:LINE\s+\d+\s*:|QUERY\s*:|STATEMENT\s*:|CONTEXT\s*:|==\s*SQL\s*==)",
                    text, maxsplit=1, flags=re.I)[0]
    text = re.sub(r"\(Background on this error at:.*?\)", "", text, flags=re.I | re.S)
    text = re.sub(r"\b[a-z][a-z0-9+.-]*://[^\s/@]+:[^\s/@]+@[^\s]*",
                  "[connection details omitted]", text, flags=re.I)
    text = re.sub(r"\b(?:DRIVER|SERVER|HOST|Data Source|DSN)\s*=\s*[^\r\n]+",
                  "[connection details omitted]", text, flags=re.I)
    text = re.sub(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [credential omitted]", text, flags=re.I)
    text = _SENSITIVE.sub("[credential omitted]", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()[:limit]


def _primary(error):
    """Unwrap explicit database wrappers, never an unrelated __context__."""
    current, seen = error, set()
    while id(current) not in seen and len(seen) < 12:
        seen.add(id(current))
        inner = safe_exception_attribute(current, "orig")
        if not isinstance(inner, BaseException):
            cause = safe_exception_attribute(current, "__cause__")
            if (isinstance(cause, BaseException) and
                    (type(current).__module__.startswith("sqlalchemy") or _WRAPPER.match(_text(current))
                     or exception_code(current) == "connection_unavailable")):
                inner = cause
        if not isinstance(inner, BaseException):
            break
        current = inner
    return current


def _provider_message(error):
    if isinstance(error, SyntaxError):
        return _safe_text(error.msg)
    pieces = []
    for value in _arguments(error):
        if not isinstance(value, str) or re.fullmatch(r"[0-9A-Z]{5}", value):
            continue
        value = _safe_text(value)
        value = _WRAPPER.sub("", value)
        # ODBC frequently repeats the same text after '; [SQLSTATE] ...'.
        for part in re.split(r";\s*(?=\[[0-9A-Z]{5}\])", value):
            part = _PROVIDER_PREFIX.sub("", part.strip())
            part = re.sub(r"\s*\((?:SQL\w+|\d{2,6})\)\s*$", "", part)
            part = re.sub(r"\s*\((?:SQL\w+|\d{2,6})\)\s*$", "", part)
            part = part.strip()
            if part and part not in pieces:
                pieces.append(part)
    if not pieces:
        pieces.append(_safe_text(error) or type(error).__name__)
    return " ".join(pieces)[:8192]


def _category(error, primary, message, language):
    code = exception_code(error)
    values = [safe_exception_attribute(primary, "sqlstate", ""), safe_exception_attribute(primary, "pgcode", "")]
    values.extend(value for value in _arguments(primary) if isinstance(value, str))
    states = {match.group(1).upper() for value in values for match in _STATE.finditer(str(value)[:8192])}
    numbers = {value for value in _arguments(primary)[:2] if isinstance(value, int)}
    numbers.update(int(value) for value in re.findall(r"\((\d{2,6})\)", _text(primary)))
    text = message.lower()
    provider_code = _text(primary).lower()
    if (code == "cancelled" or type(primary).__name__ in {"OperationCancelled", "ExportCancelled", "KeyboardInterrupt"}
            or "HY008" in states or "57014" in states and "statement timeout" not in text):
        return "cancelled"
    if isinstance(primary, (FileNotFoundError, IsADirectoryError, NotADirectoryError)):
        return "file"
    context = safe_exception_attribute(primary, "context")
    http_status = str(context.get("http-code", "")) if isinstance(context, dict) else str(safe_exception_attribute(primary, "status_code", ""))
    if (numbers & {229, 230, 916, 4060, 4064, 1044, 1142, 1143, 1227} or "42501" in states or http_status == "403"
            or any(value in text for value in ("permission denied", "permission was denied", "access is denied",
                                               "cannot open database", "not authorized", "insufficient privileges"))
            or "[permission_denied]" in provider_code or "[access_denied]" in provider_code):
        return "permission"
    if (any(value.startswith("28") for value in states) or numbers & {18456, 18452, 1045} or http_status == "401"
            or code == "ssh_auth_failed" or any(value in text for value in ("login failed", "authentication failed", "authentication rejected", "password authentication failed"))):
        return "authentication"
    if (states & {"42S02", "42S22", "42P01", "42703", "3D000", "3F000"} or numbers & {207, 208, 1146}
            or any(value in text for value in ("invalid object name", "invalid column name", "table or view not found", "schema_not_found", "table_or_view_not_found", "no such table", "no such column"))
            or any(value in provider_code for value in ("[table_or_view_not_found]", "[schema_not_found]", "[catalog_not_found]"))):
        return "not_found"
    if any(value.startswith("23") for value in states) or numbers & {515, 547, 2601, 2627, 1062}:
        return "constraint"
    if any(value.startswith("22") for value in states) or numbers & {245, 8114, 8115}:
        return "data"
    if isinstance(primary, TimeoutError) or states & {"HYT00", "HYT01"} or any(value in text for value in ("query timeout", "statement timeout", "time limit exceeded")):
        return "timeout"
    if isinstance(primary, SyntaxError) or states & {"42601", "42000"} or "syntax error" in text or "incorrect syntax" in text:
        return "syntax"
    if code in {"connection_lost", "connection_unavailable", "ssh_connection_lost"}:
        return "network"
    from src.database.connection_recovery import classify_connection_error
    if classify_connection_error(primary):
        return "network"
    if isinstance(primary, PermissionError):
        return "file"
    if language == "python":
        return "python"
    if isinstance(primary, (ValueError, TypeError)):
        return "data"
    return "internal"


def _format_error(error, *, language=None):
    """A short user message plus bounded local details, without source/locals."""
    primary = _primary(error)
    message = _provider_message(primary)
    category = _category(error, primary, message, language)
    traceback_ = safe_exception_attribute(error, "__traceback__")
    frames = traceback.extract_tb(traceback_, limit=30) if traceback_ else []
    user_frame = next((frame for frame in reversed(frames) if frame.filename.startswith("<datapyn:")), None)
    if language == "python" and (category == "python" or isinstance(primary, SyntaxError)):
        message = f"{type(primary).__name__}: {message}"
        line = primary.lineno if isinstance(primary, SyntaxError) else user_frame.lineno if user_frame else None
        if isinstance(line, int):
            message += f" (linha {line})"
    details = [message if message.startswith(f"{type(primary).__name__}: ") else f"{type(primary).__name__}: {message}"]
    # Do not format_exception(): its source lines can contain hardcoded SQL,
    # passwords or tokens. File/line/function give enough context for debugging.
    details.extend(f'  File "{_safe_text(frame.filename, 1024)}", line {frame.lineno}, in {_safe_text(frame.name, 256)}'
                   for frame in frames)
    previous_messages = {message}
    provider_errors = safe_exception_attribute(error, "_datapyn_provider_errors", ())
    if isinstance(provider_errors, (list, tuple)):
        for item in provider_errors[:32]:
            if not isinstance(item, BaseException):
                continue
            extra = _provider_message(_primary(item))
            if extra not in previous_messages:
                details.append(f"{type(item).__name__}: {extra}")
                previous_messages.add(extra)
    return {"category": category, "title": _TITLES[category], "message": message[:8192],
            "technical_details": "\n".join(details)[:32_768]}


def format_error(error, *, language=None):
    # User-defined Python exceptions can have broken properties/formatters.
    # Diagnostics must never prevent the terminal execution event.
    try:
        return _format_error(error, language=language)
    except Exception:
        category = "python" if language == "python" else "internal"
        return {"category": category, "title": _TITLES[category],
                "message": "Não foi possível obter os detalhes deste erro.",
                "technical_details": "Error diagnostics were unavailable."}


def error_summary(info):
    return f'{info["title"]}: {info["message"]}' if info["message"] else info["title"]


@contextmanager
def suppress_internal_console_logs():
    """Internal library logs must not become duplicate user execution output.

    Only console handlers pointing at the current capture streams are filtered.
    File/monitoring handlers, user loggers, print(), stderr and warnings remain.
    """
    streams = (sys.stdout, sys.stderr)
    loggers = [logging.getLogger(), *(item for item in list(logging.Logger.manager.loggerDict.values())
                                     if isinstance(item, logging.Logger))]
    handlers = {handler for logger in loggers for handler in logger.handlers}
    if logging.lastResort is not None:
        handlers.add(logging.lastResort)
    installed = []
    for handler in handlers:
        if not isinstance(handler, logging.StreamHandler) or isinstance(handler, logging.FileHandler):
            continue
        class ConsoleFilter(logging.Filter):
            def filter(self, record, target=handler):
                return not (getattr(target, "stream", None) in streams and record.name.startswith(_INTERNAL_LOGGERS))
        filter_ = ConsoleFilter()
        handler.addFilter(filter_)
        installed.append((handler, filter_))
    try:
        yield
    finally:
        for handler, filter_ in installed:
            handler.removeFilter(filter_)


def _serialize_runtime_error(error, *, default_code="operation_failed", language=None):
    """Keep actionable SSH trust challenges across IPC without exposing secrets."""
    code = exception_code(error, default_code)
    if not isinstance(code, str):
        code = default_code
    info = format_error(error, language=language)
    result = {"code": code, "message": error_summary(info), "error_info": info}
    details = safe_exception_attribute(error, "details")
    if code.startswith("ssh_") and isinstance(details, dict):
        # Only the server's public identity belongs in a trust confirmation.
        fields = {"host", "port", "key_type", "public_key", "fingerprint", "expected_fingerprint"}
        result["details"] = without_secrets({key: value for key, value in details.items() if key in fields})
    elif code == "connection_lost" and isinstance(details, dict):
        fields = {"acknowledgement_required", "submitted", "session_state_lost"}
        result["details"] = {key: value for key, value in details.items() if key in fields and isinstance(value, bool)}
    elif code == "connection_unavailable":
        result["details"] = {"retryable": True}
    return result


def serialize_runtime_error(error, *, default_code="operation_failed", language=None):
    try:
        return _serialize_runtime_error(error, default_code=default_code, language=language)
    except Exception:
        info = {"category": "internal", "title": _TITLES["internal"],
                "message": "Não foi possível obter os detalhes deste erro.",
                "technical_details": "Error diagnostics were unavailable."}
        return {"code": "internal_error", "message": error_summary(info), "error_info": info}
