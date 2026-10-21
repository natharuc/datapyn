"""Default-on SQL review gates the shipped runtime before database mutation.

All databases and settings in these tests live in private temporary directories.
Client.execute explicitly simulates the user's review/OK; raw responses do not.
"""

from copy import deepcopy
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from datapyn_runtime.sql_safety_guard import (
    ConfirmationRequiredError, MAX_TICKETS, SqlSafetyGuard, TICKET_TTL,
    kernel_policy, request_risks,
)
from datapyn_runtime.sql_safety_settings import settings_set
from datapyn_runtime.supervisor import Supervisor
from test_runtime import client  # noqa: F401 -- shared isolated stdio fixture


def command(code="DELETE FROM sample", **options):
    return {"session_id": "a", "execution_id": "destructive", "language": "sql", "code": code, **options}


def seed(client):
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite"}})
    finished = client.execute("CREATE TABLE sample (value INTEGER); INSERT INTO sample VALUES (1),(2)", "seed", language="sql")
    assert finished["status"] == "succeeded", finished


def assert_rows(client, expected, execution_id="check"):
    assert client.page(client.execute("SELECT value FROM sample ORDER BY value", execution_id, language="sql"))["rows"] == expected


@pytest.mark.parametrize("code", ["DELETE FROM sample", "DELETE FROM sample WHERE value=1", "UPDATE sample SET value=99", "DROP TABLE sample"])
def test_destructive_sql_requires_confirmation_before_enqueue_and_keeps_rows(client, code):
    seed(client)
    response = client.response("execution.run", command(code, _sql_safety_authorized=True, _sql_safety_enabled=False))
    assert response["error"]["code"] == "destructive_sql_confirmation_required"
    assert not any(item.get("event") == "execution.started" and item["payload"]["execution_id"] == "destructive" for item in client.all_messages)
    assert_rows(client, [[1], [2]])


def test_review_is_nonmutating_and_token_is_single_use(client):
    seed(client)
    params = command("DELETE FROM sample WHERE value=1")
    reviewed = client.request("execution.review", params)
    assert reviewed["confirmation_required"] and reviewed["risks"][0]["has_where"]
    # No intervening run is needed to prove review did not execute SQL.
    assert not any(item.get("event") == "execution.started" and item["payload"]["execution_id"] == "destructive" for item in client.all_messages)
    approved = {**params, "confirmation_token": reviewed["confirmation_token"]}
    client.request("execution.run", approved)
    assert client.event("execution.finished", "destructive")["status"] == "succeeded"
    assert client.response("execution.run", approved)["error"]["code"] == "destructive_sql_confirmation_required"
    assert_rows(client, [[2]])


@pytest.mark.parametrize("changed", [
    {"code": "DELETE FROM sample"}, {"database": "other"}, {"schema": "other"},
    {"block_id": "other"}, {"parameters": {"value": 2}}, {"execution_id": "other"},
])
def test_changed_reviewed_payload_needs_new_confirmation(client, changed):
    seed(client)
    params = command("DELETE FROM sample WHERE value=:value", parameters={"value": 1})
    reviewed = client.request("execution.review", params)
    result = client.response("execution.run", {**params, **changed, "confirmation_token": reviewed["confirmation_token"]})
    assert result["error"]["code"] == "destructive_sql_confirmation_required"
    assert_rows(client, [[1], [2]])


def test_intervening_session_execution_invalidates_review(client):
    seed(client)
    params = command()
    reviewed = client.request("execution.review", params)
    assert_rows(client, [[1], [2]], "intervening")
    assert client.response("execution.run", {**params, "confirmation_token": reviewed["confirmation_token"]})["error"]["code"] == "destructive_sql_confirmation_required"
    assert_rows(client, [[1], [2]])


def test_explicit_setting_disables_confirmation_and_can_be_reenabled(client):
    seed(client)
    assert client.request("sql.safety.settings.get") == {"confirm_destructive_sql": True}
    assert client.request("sql.safety.settings.set", {"confirm_destructive_sql": False}) == {"confirm_destructive_sql": False}
    params = command("DELETE FROM sample WHERE value=1")
    assert client.request("execution.review", params) == {"confirmation_required": False, "risks": []}
    client.request("execution.run", params)
    assert client.event("execution.finished", "destructive")["status"] == "succeeded"
    client.request("sql.safety.settings.set", {"confirm_destructive_sql": True})
    assert client.response("execution.run", command(execution_id="blocked"))["error"]["code"] == "destructive_sql_confirmation_required"
    assert_rows(client, [[2]])


def test_queued_disabled_command_is_denied_if_policy_is_enabled_before_it_runs(client):
    seed(client)
    client.request("sql.safety.settings.set", {"confirm_destructive_sql": False})
    client.request("execution.run", command("import time; time.sleep(.6)", execution_id="wait", language="python"))
    client.event("execution.started", "wait")
    client.request("execution.run", command())
    client.request("sql.safety.settings.set", {"confirm_destructive_sql": True})
    finished = client.event("execution.finished", "destructive")
    assert finished["status"] == "failed" and finished["error_code"] == "destructive_sql_confirmation_required"
    assert_rows(client, [[1], [2]])


def test_readonly_review_can_queue_while_another_block_is_running(client):
    seed(client)
    client.request("execution.run", command("import time; time.sleep(.3)", execution_id="wait", language="python"))
    client.event("execution.started", "wait")
    params = command("SELECT value FROM sample", execution_id="read")
    assert not client.request("execution.review", params)["confirmation_required"]
    assert client.response("execution.review", command())["error"]["code"] == "session_busy"
    client.request("execution.run", params)
    assert client.page(client.event("execution.finished", "read"))["rows"] == [[1], [2]]


def test_sql_download_authorization_binds_original_options_before_internal_staging(client, tmp_path):
    seed(client)
    path = tmp_path / "rows.csv"
    params = command("DELETE FROM sample WHERE value=1; SELECT value FROM sample", export={"path": str(path), "format": "csv"})
    review = client.request("execution.review", params)
    assert review["confirmation_required"]
    client.request("execution.run", {**params, "confirmation_token": review["confirmation_token"]})
    finished = client.event("execution.finished", "destructive")
    assert finished["status"] == "succeeded", finished
    assert "2" in path.read_text(encoding="utf-8-sig")
    assert_rows(client, [[2]])


@pytest.mark.parametrize("changed_target", [False, True])
def test_metadata_only_invalidates_fallback_approval_when_active_target_changes(client, tmp_path, changed_target):
    first, second = tmp_path / "first.sqlite", tmp_path / "second.sqlite"
    for path in (first, second):
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE sample(value INTEGER)")
            connection.execute("INSERT INTO sample VALUES (1)")
    client.session()
    first_config = {"db_type": "sqlite", "database": str(first)}
    assert client.execute("SELECT value FROM sample", "activate-first", language="sql", config=first_config)["status"] == "succeeded"
    # There is deliberately no tab default: this uses the kernel's active
    # connection fallback, as block-only/legacy callers can do.
    params = command()
    review = client.request("execution.review", params)
    selected = second if changed_target else first
    client.request("schema.get", {"session_id": "a", "config": {"db_type": "sqlite", "database": str(selected)}})
    response = client.response("execution.run", {**params, "confirmation_token": review["confirmation_token"]})
    if changed_target:
        assert response["error"]["code"] == "destructive_sql_confirmation_required"
    else:
        assert "error" not in response, response
        assert client.event("execution.finished", "destructive")["status"] == "succeeded"
    with sqlite3.connect(first) as connection:
        assert connection.execute("SELECT value FROM sample").fetchall() == ([(1,)] if changed_target else [])
    with sqlite3.connect(second) as connection:
        assert connection.execute("SELECT value FROM sample").fetchall() == [(1,)]


def test_pinned_scope_approval_survives_metadata_activating_a_different_target(client, tmp_path):
    first, second = tmp_path / "first.sqlite", tmp_path / "second.sqlite"
    for path in (first, second):
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE sample(value INTEGER)")
            connection.execute("INSERT INTO sample VALUES (1)")
    client.session()
    params = command(config={"db_type": "sqlite", "database": str(first)})
    review = client.request("execution.review", params)
    client.request("schema.get", {"session_id": "a", "config": {"db_type": "sqlite", "database": str(second)}})
    client.request("execution.run", {**params, "confirmation_token": review["confirmation_token"]})
    assert client.event("execution.finished", "destructive")["status"] == "succeeded"
    with sqlite3.connect(first) as connection:
        assert connection.execute("SELECT value FROM sample").fetchall() == []
    with sqlite3.connect(second) as connection:
        assert connection.execute("SELECT value FROM sample").fetchall() == [(1,)]


def test_python_sql_helper_cannot_execute_unreviewed_dynamic_sql(client):
    seed(client)
    # The SQL originates in a previous block; analysis cannot see its value.
    client.execute("dangerous_query = 'DELETE FROM sample'\nexecute_saved = sql", "prepare")
    params = command("execute_saved(dangerous_query)", language="python")
    reviewed = client.request("execution.review", params)
    assert not reviewed["confirmation_required"]
    client.request("execution.run", params)
    finished = client.event("execution.finished", "destructive")
    # The old helper is invalidated after its block. A current helper alias
    # also validates the actual query at invocation, independently of parsing.
    assert finished["status"] == "failed"
    current = command("executor = sql\nexecutor(dangerous_query)", execution_id="current", language="python")
    if client.request("execution.review", current)["confirmation_required"]:
        # Dynamic known calls are deliberately reviewed conservatively.
        assert client.response("execution.run", current)["error"]["code"] == "destructive_sql_confirmation_required"
    else:
        client.request("execution.run", current)
        assert client.event("execution.finished", "current")["error_code"] == "destructive_sql_confirmation_required"
    assert_rows(client, [[1], [2]])


def test_python_cached_sqlalchemy_connection_guard_prevents_hidden_mutation(client):
    seed(client)
    client.execute("from sqlalchemy import text\nstatement = text('DELETE FROM sample')", "prepare")
    # A lambda hides the call from static attribute-call analysis, while the
    # SQLAlchemy driver hook still sees the exact SQL before cursor execution.
    params = command("with db_engine.begin() as connection:\n    invoke = connection.execute\n    invoke(statement)", language="python")
    review = client.request("execution.review", params)
    assert not review["confirmation_required"], review
    client.request("execution.run", params)
    finished = client.event("execution.finished", "destructive")
    assert finished["status"] == "failed" and finished["error_code"] == "destructive_sql_confirmation_required", finished
    assert_rows(client, [[1], [2]])
    # The temporary hook is cleaned up; an explicitly reviewed later command
    # can execute through the very same engine.
    approved = client.execute("with db_engine.begin() as connection:\n    connection.execute(text('DELETE FROM sample WHERE value=1'))", "approved")
    assert approved["status"] == "succeeded", approved
    assert_rows(client, [[2]], "final")


def test_replacing_exported_table_requires_same_review_and_preserves_denied_target(client):
    seed(client)
    frame = client.execute("pd.DataFrame({'value': [9]})", "frame")
    params = {"session_id": "a", "result_id": frame["results"][0]["result_id"], "table": "sample", "if_exists": "replace"}
    assert client.response("result.export_table", params)["error"]["code"] == "destructive_sql_confirmation_required"
    assert_rows(client, [[1], [2]])
    reviewed = client.request("execution.review", {**params, "method": "result.export_table"})
    assert reviewed["risks"][0]["operation"] == "REPLACE TABLE"
    result = client.request("result.export_table", {**params, "confirmation_token": reviewed["confirmation_token"]})
    assert result["row_count"] == 1
    assert_rows(client, [[9]], "after-replace")


def test_tickets_expire_are_bounded_and_bind_profile_session_target_and_parameters(tmp_path):
    now = [100.0]
    guard = SqlSafetyGuard(tmp_path / "settings.json", clock=lambda: now[0])
    params = command(parameters={"password": "bind-one"})
    binding = {"profile": "one", "session_epoch": "one", "session_revision": 1, "db_type": "sqlite", "config": {"database": "one"}}
    for changed in [{"profile": "two"}, {"session_epoch": "two"}, {"session_revision": 2}, {"config": {"database": "two"}}]:
        token = guard.review("execution.run", params, binding)["confirmation_token"]
        with pytest.raises(ConfirmationRequiredError):
            guard.authorize("execution.run", {**params, "confirmation_token": token}, {**binding, **changed})
    token = guard.review("execution.run", params, binding)["confirmation_token"]
    with pytest.raises(ConfirmationRequiredError):
        guard.authorize("execution.run", {**params, "parameters": {"password": "bind-two"}, "confirmation_token": token}, binding)
    token = guard.review("execution.run", params, binding)["confirmation_token"]
    now[0] += TICKET_TTL
    with pytest.raises(ConfirmationRequiredError):
        guard.authorize("execution.run", {**params, "confirmation_token": token}, binding)
    first = guard.review("execution.run", params, binding)["confirmation_token"]
    for _ in range(MAX_TICKETS):
        guard.review("execution.run", params, binding)
    assert len(guard.tickets) == MAX_TICKETS and first not in guard.tickets
    # The cache retains hashes, never query text or credentials.
    assert all(isinstance(value[1], bytes) and len(value[1]) == 32 for value in guard.tickets.values())


def test_enabling_policy_covers_previously_queued_unapproved_work(tmp_path):
    path = tmp_path / "settings.json"
    settings_set({"confirm_destructive_sql": False}, path)
    guard = SqlSafetyGuard(path)
    flags = guard.authorize("execution.run", command(), {})
    assert kernel_policy(flags) == (False, False)
    settings_set({"confirm_destructive_sql": True}, path)
    assert kernel_policy(flags) == (True, False)


def test_review_resolves_public_target_name_without_credentials_or_a_database(tmp_path):
    supervisor = Supervisor.__new__(Supervisor)
    session = SimpleNamespace(session_id="a", _sql_safety_epoch="one", _sql_safety_revision=0, _sql_safety_default={})
    supervisor._session = lambda params: session
    supervisor.profile_path = tmp_path
    saved = {"id": "saved", "name": "Actual destination", "config": {"db_type": "sqlserver", "host": "example", "database": "sample", "password": "never exposed"}}
    def resolve(config, *, resolve_credentials):
        assert resolve_credentials is False
        return deepcopy(config)
    supervisor._catalog = SimpleNamespace(_lock=threading.RLock(), _find=lambda kind, identifier: saved, resolve_ssh=resolve)
    binding = supervisor._sql_safety_binding(command(connection_id="saved", connection_name="Wrong name"))
    assert binding["connection_name"] == "Actual destination"
    assert "password" not in binding["config"] and "password" not in binding["saved_connection"]["config"]


@pytest.mark.parametrize("method", ["internal_query", "internal_rpc"])
def test_agent_internal_calls_cannot_supply_their_own_approval(tmp_path, method):
    supervisor = Supervisor.__new__(Supervisor)
    session = SimpleNamespace(session_id="a", _lock=threading.RLock(), _sql_safety_epoch="epoch", _sql_safety_revision=0, _sql_safety_default={})
    session.enqueue = lambda *args: pytest.fail("A denied destructive query reached the kernel queue")
    supervisor.profile_path = tmp_path
    supervisor._sql_safety_guard = SqlSafetyGuard(tmp_path / "settings.json")
    supervisor._session = lambda params: session
    supervisor._route = lambda params: deepcopy(params)
    supervisor._internal_lock, supervisor._internal = threading.RLock(), {}
    params = command(_sql_safety_authorized=True)
    params["confirmation_token"] = supervisor.sql_safety_guard.review("execution.run", params, supervisor._sql_safety_binding(params))["confirmation_token"]
    with pytest.raises(ConfirmationRequiredError):
        if method == "internal_query":
            supervisor.internal_query("a", params)
        else:
            supervisor.internal_rpc("a", "execution.run", params)
    assert not supervisor._internal


def test_review_shared_python_parameters_before_execution_and_sql_parameters_are_bound():
    # Shared Python parameters are rendered before analysis; ordinary SQL
    # values remain binds and cannot inject commands into the classifier.
    assert not request_risks("execution.run", command("SELECT :value", parameters={"value": "DELETE FROM sample"}))
    risks = request_risks("execution.run", command("DELETE FROM sample WHERE value=:value", parameters={"value": "SELECT 1"}))
    assert len(risks) == 1 and risks[0]["has_where"]
    from src.utils.sql_parameter_service import default_shared_parameter_definition
    shared = {**default_shared_parameter_definition("statement"), "value": "DELETE FROM sample"}
    [risk] = request_risks("execution.run", command("sql({{statement}})", language="python", shared_parameters=[shared]))
    assert risk["operation"] == "DELETE" and risk["target"] == "sample"
