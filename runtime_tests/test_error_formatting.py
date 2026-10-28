"""User diagnostics stay short, actionable and separate from library logging."""

import io
import json
import logging
import pytest

from datapyn_runtime.errors import format_error, serialize_runtime_error, suppress_internal_console_logs
from datapyn_runtime.kernel import connection_loss_error
from src.database.connection_recovery import ConnectionLostError


def odbc_error(state, message):
    return type("ProgrammingError", (Exception,), {"__module__": "pyodbc"})(state, message)


def test_exact_sqlserver_missing_table_is_one_clean_message_without_driver_wrappers():
    from sqlalchemy.exc import DBAPIError
    provider = odbc_error("42S02", "[42S02] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]Invalid object name 'missing_table'. (208) (SQLExecDirectW); [42S02] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]Invalid object name 'missing_table'. (208) (SQLExecDirectW)")
    wrapped = DBAPIError("SELECT * FROM missing_table WHERE secret=:password", {"password": "private-parameter"}, provider)
    info = format_error(wrapped, language="sql")
    assert info["category"] == "not_found" and info["title"] == "Objeto não encontrado"
    assert info["message"] == "Invalid object name 'missing_table'."
    assert "private-parameter" not in json.dumps(info)
    assert "SELECT" not in json.dumps(info) and "ODBC Driver" not in info["message"]


def test_multi_batch_wrapper_uses_native_error_and_keeps_additional_errors_in_details_only():
    first = odbc_error("42S02", "[42S02] [Microsoft][SQL Server]Invalid object name 'first'. (208)")
    second = odbc_error("42000", "[42000] [Microsoft][SQL Server]Incorrect syntax near 'WHERE'. (156)")
    aggregate = Exception("Batch 1/2: SQL wrapper containing private-query")
    aggregate.orig = first
    aggregate._datapyn_provider_errors = (first, second, first)
    info = format_error(aggregate, language="sql")
    assert info["message"] == "Invalid object name 'first'."
    assert info["category"] == "not_found"
    assert "Incorrect syntax near 'WHERE'." in info["technical_details"]
    assert info["technical_details"].count("Invalid object name 'first'.") == 1
    assert "private-query" not in json.dumps(info)


@pytest.mark.parametrize("state,message,category", [
    ("08004", '[08004] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]Cannot open database "restricted" requested by the login. The login failed. (4060) (SQLDriverConnect)', "permission"),
    ("42000", "[42000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]The SELECT permission was denied on the object 'items'. (229) (SQLExecDirectW)", "permission"),
    ("28000", "[28000] Login failed for user 'example'. (18456)", "authentication"),
    ("42P01", 'relation "missing" does not exist', "not_found"),
    ("42601", 'syntax error at or near "FROM"', "syntax"),
    ("23000", "Cannot insert duplicate key row. (2627)", "constraint"),
    ("22003", "numeric value out of range", "data"),
    ("HYT00", "Query timeout expired", "timeout"),
    ("57014", "canceling statement due to statement timeout", "timeout"),
    ("57014", "canceling statement due to user request", "cancelled"),
    ("08S01", "Communication link failure", "network"),
])
def test_provider_categories_keep_permission_and_statement_errors_distinct_from_transport(state, message, category):
    info = format_error(odbc_error(state, message), language="sql")
    assert info["category"] == category, info
    assert "Traceback" not in info["message"] and state not in info["message"]


def test_handled_old_transport_error_is_not_the_new_python_failure():
    try:
        raise ConnectionLostError()
    except ConnectionLostError:
        try:
            raise ValueError("a different invalid value")
        except ValueError as error:
            assert connection_loss_error(error) is None
            info = format_error(error, language="python")
    assert info["category"] == "python"
    assert info["message"] == "ValueError: a different invalid value"
    assert "ConnectionLostError" not in info["technical_details"]


def test_explicit_managed_connection_loss_remains_owned():
    from sqlalchemy.exc import DBAPIError
    original = ConnectionLostError(submitted=True)
    wrapped = DBAPIError(None, None, original, connection_invalidated=True)
    assert connection_loss_error(wrapped) is original
    assert format_error(wrapped)["category"] == "network"


def test_python_message_names_type_and_user_line_without_copying_source_or_locals():
    try:
        exec(compile("private_value='hardcoded-private-value'\nraise ValueError('expected value')", "<datapyn:block-first>", "exec"), {})
    except ValueError as error:
        info = format_error(error, language="python")
    assert info["category"] == "python"
    assert info["message"] == "ValueError: expected value (linha 2)"
    assert '<datapyn:block-first>' in info["technical_details"]
    assert 'line 2' in info["technical_details"]
    assert 'hardcoded-private-value' not in json.dumps(info) and "raise ValueError" not in json.dumps(info)


def test_python_syntax_error_does_not_expose_the_source_line():
    try:
        compile("private='hardcoded-private-value'\nif True print(private)", "<datapyn:block-first>", "exec")
    except SyntaxError as error:
        info = format_error(error, language="python")
    assert info["category"] == "syntax" and "linha 2" in info["message"]
    assert "print(private)" not in json.dumps(info) and "hardcoded-private-value" not in json.dumps(info)


@pytest.mark.parametrize("message,secret", [
    ("failure: password=private-password", "private-password"),
    ("failure: {'access_token': 'private-token'}", "private-token"),
    ("Authorization: Bearer private-auth-token", "private-auth-token"),
    ("postgresql://private-user:private-password@private-host/db", "private-password"),
    ("DRIVER={ODBC};SERVER=private-host;UID=private-user;PWD={private password}", "private password"),
    ("failure [SQL: SELECT 'private-query'] [parameters: {'id': 'private-parameter'}]", "private-query"),
])
def test_even_local_technical_details_omit_credentials_connection_strings_and_statement_annotations(message, secret):
    info = format_error(RuntimeError(message))
    assert secret not in json.dumps(info), info
    assert "private-parameter" not in json.dumps(info)


def test_diagnostics_are_bounded_and_a_broken_exception_string_cannot_hide_the_error():
    info = format_error(ValueError("x" * 100_000), language="python")
    assert len(info["message"]) <= 8192 and len(info["technical_details"]) <= 32768
    class Broken(Exception):
        def __str__(self): raise ValueError("broken formatter")
    info = format_error(Broken())
    assert info["message"] == "Broken"


def test_malformed_exception_properties_cannot_break_diagnostic_serialization():
    class Broken(Exception):
        @property
        def orig(self): raise ValueError("broken orig")
        @property
        def code(self): raise ValueError("broken code")
        @property
        def args(self): return {"unexpected": object()}
        def __str__(self): raise ValueError("broken string")
    error = Broken()
    assert connection_loss_error(error) is None
    for result in (format_error(error), serialize_runtime_error(error)):
        assert isinstance(result, dict)
        json.dumps(result, allow_nan=False)
    assert len(serialize_runtime_error(error)["error_info"]["message"]) <= 8192


def test_formatter_and_challenge_failure_use_a_fixed_bounded_fallback(monkeypatch):
    from datapyn_runtime import errors
    monkeypatch.setattr(errors, "_format_error", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("internal formatting failure")))
    assert errors.format_error(ValueError())["category"] == "internal"
    class BrokenDictionary(dict):
        def items(self): raise ValueError("broken details")
    error = RuntimeError("original error")
    error.code = "ssh_host_key_unknown"
    error.details = BrokenDictionary(host="example.invalid")
    result = errors.serialize_runtime_error(error)
    assert result["code"] == "internal_error" and result["error_info"]["category"] == "internal"
    assert "internal formatting failure" not in json.dumps(result) and "broken details" not in json.dumps(result)


def test_error_envelope_retains_safe_ssh_challenge_and_adds_user_diagnostics():
    error = RuntimeError("Check the host identity")
    error.code = "ssh_host_key_unknown"
    error.details = {"host": "example.invalid", "port": 22, "fingerprint": "SHA256:public", "password": "private-password"}
    result = serialize_runtime_error(error)
    assert result["code"] == "ssh_host_key_unknown"
    assert result["details"] == {"host": "example.invalid", "port": 22, "fingerprint": "SHA256:public"}
    assert result["error_info"]["message"] == "Check the host identity"
    assert "private-password" not in json.dumps(result)


def test_internal_logs_do_not_duplicate_output_but_user_output_and_monitoring_survive(monkeypatch, tmp_path):
    console = io.StringIO()
    monkeypatch.setattr("sys.stderr", console)
    stream_handler = logging.StreamHandler(console)
    file_handler = logging.FileHandler(tmp_path / "monitor.log", encoding="utf-8")
    internal = logging.getLogger("src.database.diagnostic_test")
    user = logging.getLogger("user.analysis.diagnostic_test")
    previous = [(logger, logger.handlers[:], logger.level, logger.propagate) for logger in (internal, user)]
    for logger in (internal, user):
        logger.handlers = [stream_handler, file_handler]
        logger.setLevel(logging.WARNING)
        logger.propagate = False
    try:
        with suppress_internal_console_logs():
            internal.error("internal duplicate")
            user.warning("user diagnostic")
            print("user print", file=console)
            import sys
            sys.stderr.write("user stderr\n")
        internal.error("outside capture")
        file_handler.flush()
        output = console.getvalue()
        assert "internal duplicate" not in output
        assert "user diagnostic" in output and "user print" in output and "user stderr" in output
        assert "outside capture" in output
        assert "internal duplicate" in (tmp_path / "monitor.log").read_text(encoding="utf-8")
    finally:
        for logger, handlers, level, propagate in previous:
            logger.handlers, logger.level, logger.propagate = handlers, level, propagate
        stream_handler.close()
        file_handler.close()


def test_internal_diagnostic_filter_is_removed_even_when_user_code_fails(monkeypatch):
    console = io.StringIO()
    monkeypatch.setattr("sys.stderr", console)
    handler = logging.StreamHandler(console)
    logger = logging.getLogger("src.database.diagnostic_failure")
    previous = (logger.handlers[:], logger.level, logger.propagate)
    logger.handlers, logger.level, logger.propagate = [handler], logging.ERROR, False
    try:
        with pytest.raises(ValueError):
            with suppress_internal_console_logs():
                raise ValueError("expected")
        logger.error("still available outside capture")
        assert "still available" in console.getvalue()
    finally:
        logger.handlers, logger.level, logger.propagate = previous
        handler.close()


def test_postgres_and_databricks_messages_do_not_copy_query_context():
    primary = type("UndefinedTable", (Exception,), {"pgcode": "42P01"})(
        'relation "missing" does not exist\nLINE 1: SELECT secret FROM private_table\n               ^')
    info = format_error(primary, language="sql")
    assert info["category"] == "not_found" and info["message"] == 'relation "missing" does not exist'
    assert "private_table" not in json.dumps(info)
    primary = RuntimeError("[PERMISSION_DENIED] User cannot read this table.\n== SQL ==\nSELECT 'private-query'")
    info = format_error(primary, language="sql")
    assert info["category"] == "permission" and "private-query" not in json.dumps(info)


def test_real_stdio_errors_have_one_summary_and_keep_user_stderr_and_python_line(tmp_path):
    from test_runtime import Client
    client = Client()
    try:
        client.session()
        client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite", "database": ":memory:"}})
        setup = client.execute(
            "import logging\n"
            "from datapyn_runtime.database import SQLiteConnector\n"
            "_original_read = SQLiteConnector.execute_query\n"
            "def _diagnostic_read(self, code, **kwargs):\n"
            "    logging.getLogger('src.database.synthetic_driver').error('internal duplicate before provider error')\n"
            "    return _original_read(self, code, **kwargs)\n"
            "SQLiteConnector.execute_query = _diagnostic_read\n", "setup")
        assert setup["status"] == "succeeded", setup
        for execution_id in ("missing-first", "missing-second"):
            failed = client.execute("SELECT * FROM missing_table", execution_id, language="sql")
            assert failed["status"] == "failed" and failed["error_info"]["category"] == "not_found"
            assert failed["error_info"]["message"] == "no such table: missing_table"
            assert "Traceback" not in failed["error"] and "internal duplicate" not in failed["error"]
            assert client.output(execution_id, "stderr") == ""
            assert not failed.get("connection_lost") and not failed.get("connection_recovery")
        failed = client.execute("import sys, warnings\nprint('user stdout')\nsys.stderr.write('user stderr\\n')\nwarnings.warn('user warning')\nraise ValueError('invalid value')", "python-failure")
        assert failed["status"] == "failed" and failed["error_info"]["category"] == "python"
        assert failed["error_info"]["message"] == "ValueError: invalid value (linha 5)"
        assert "user stdout" in client.output("python-failure")
        assert "user stderr" in client.output("python-failure", "stderr")
        assert "user warning" in client.output("python-failure", "stderr")
        assert "Traceback" not in client.output("python-failure", "stderr")
        failed = client.execute("class Broken(Exception):\n    @property\n    def code(self): raise ValueError('broken code')\n    @property\n    def orig(self): raise ValueError('broken orig')\n    @property\n    def args(self): return {'unexpected': object()}\n    def __str__(self): raise ValueError('broken formatter')\nraise Broken()", "broken-error")
        assert failed["status"] == "failed" and isinstance(failed["error_info"]["message"], str)
        assert client.execute("1 + 1", "after-broken-error")["status"] == "succeeded"
        rpc = client.response("document.read", {"session_id": "a", "path": str(tmp_path / "missing.sql")})
        assert rpc["error"]["error_info"]["category"] == "file"
        assert "Traceback" not in rpc["error"]["message"]
    finally:
        client.close()
