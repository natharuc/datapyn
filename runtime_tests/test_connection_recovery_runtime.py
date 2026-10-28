"""Lane recovery contracts without credentials, sockets or application databases."""

from copy import deepcopy
from types import SimpleNamespace
import errno

import pandas as pd
import pytest

from datapyn_runtime import database, kernel
from datapyn_runtime.errors import serialize_runtime_error
from src.database.connection_recovery import ConnectionLostError


class Connector:
    def __init__(self, config):
        self.db_type = config["db_type"]
        self.connection_params = {"database": config.get("database", "db"), "schema": config.get("schema", "dbo")}
        self.automatic_transactions = config.get("automatic_transactions", True)
        self.engine = object()
        self.lost = None
        self.closed = False
        self.statements = []
        self.validations = 0

    def get_connection_recovery_state(self):
        return self.lost

    def has_pending_transaction(self):
        return not self.automatic_transactions and bool(self.lost)

    def validate_connection_for_execution(self):
        self.validations += 1
        if self.lost:
            raise ConnectionLostError(acknowledgement_required=self.lost.get("acknowledgement_required", False))

    def disconnect(self):
        self.closed = True

    def get_transaction_state(self):
        return {"automatic_transactions": self.automatic_transactions, "pending": None if self.lost else False,
                "state": "unknown" if self.lost else "idle"}

    def execute_query(self, code, **kwargs):
        self.statements.append(code)
        if code == "SELECT fail_transport":
            self.lost = {"required": True, "acknowledgement_required": not self.automatic_transactions,
                         "session_state_lost": True, "submitted": True}
            raise ConnectionLostError(acknowledgement_required=not self.automatic_transactions, submitted=True)
        return pd.DataFrame({"answer": [42]})


def factory(monkeypatch):
    opened = []
    def connect(config):
        connector = Connector(config)
        opened.append((deepcopy(config), connector))
        return connector
    monkeypatch.setattr(database, "connect", connect)
    return opened


def params(db_type="sqlserver", block="first", automatic=True):
    return {"connection_id": "saved", "config": {"db_type": db_type, "database": "after_use", "schema": "analysis"},
            "block_id": block, "_execution_scope_id": block, "automatic_transactions": automatic, "scope_inherited": True}


@pytest.mark.parametrize("db_type", ["sqlserver", "postgresql", "mysql", "mariadb", "databricks", "sqlite"])
def test_stale_lane_reconnects_once_before_submission_preserving_affinity_and_focus(db_type, monkeypatch):
    opened = factory(monkeypatch)
    pool = database.ConnectorPool()
    target = params(db_type)
    previous = pool.activate(target, default=True)
    key = pool.active_key
    pool.block_affinity["peer"] = key
    pool.explorers[key] = object()
    previous.lost = {"required": True, "acknowledgement_required": False}
    events = []
    pool.on_recovery = lambda event, scope: events.append((event, scope))
    replacement = pool.activate(target, validate=True)
    assert replacement is not previous and previous.closed and len(opened) == 2
    assert pool.active_key == pool.default_active_key == key
    assert pool.block_affinity == {"first": key, "peer": key}
    assert key not in pool.explorers
    assert opened[-1][0]["database"] == "after_use" and opened[-1][0]["schema"] == "analysis"
    assert [event[0]["phase"] for event in events] == ["recovering", "ready"]
    assert events[-1][0]["affected_block_ids"] == ["first", "peer"]
    assert previous.statements == replacement.statements == []


def test_pending_unknown_manual_lane_requires_ack_and_other_lane_remains_usable(monkeypatch):
    opened = factory(monkeypatch)
    pool = database.ConnectorPool()
    first = pool.activate(params(automatic=False))
    key = pool.active_key
    other = pool.activate(params(block="other"))
    other_key = pool.active_key
    first.lost = {"required": True, "acknowledgement_required": True, "submitted": True}
    with pytest.raises(ConnectionLostError) as failure:
        pool.activate(params(automatic=False), validate=True)
    assert failure.value.details["acknowledgement_required"] and len(opened) == 2 and not first.closed
    assert pool.items[other_key] is other and pool.block_affinity["first"] == key
    blocked = pool.recover(params(automatic=False))
    assert blocked["phase"] == "blocked"
    recovered = pool.recover({**params(automatic=False), "acknowledge_state_loss": True})
    assert recovered["phase"] == "ready" and len(opened) == 3 and first.closed
    assert pool.items[other_key] is other and not other.closed
    assert pool.block_affinity["first"] == key and not pool.items[key].automatic_transactions


def test_two_transport_attempts_and_cooldown_do_not_turn_metadata_into_retry_storm(monkeypatch):
    opened = factory(monkeypatch)
    pool = database.ConnectorPool()
    previous = pool.activate(params())
    previous.lost = {"required": True, "acknowledgement_required": False}
    attempts = []
    monkeypatch.setattr(database.time, "sleep", lambda delay: None)
    def offline(config):
        attempts.append(config)
        raise OSError(errno.ECONNREFUSED, "network unavailable")
    monkeypatch.setattr(database, "connect", offline)
    for _ in range(5):
        with pytest.raises(ConnectionLostError):
            pool.activate(params(), validate=True)
    assert len(attempts) == 2 and len(opened) == 1 and not previous.closed
    assert pool.last_recovery["phase"] == "error"


def test_authentication_errors_are_not_retried_and_explicit_retry_keeps_the_target(monkeypatch):
    factory(monkeypatch)
    pool = database.ConnectorPool()
    previous = pool.activate(params())
    previous.lost = {"required": True, "acknowledgement_required": False}
    attempts = []
    def rejected(config):
        attempts.append(config)
        raise RuntimeError("Login failed")
    monkeypatch.setattr(database, "connect", rejected)
    assert pool.recover(params())["phase"] == "error"
    assert len(attempts) == 1 and pool.active is previous and not previous.closed
    assert pool.recover(params())["phase"] == "error" and len(attempts) == 2


def test_initial_connection_retries_only_transport_errors_then_exposes_retryable_envelope(monkeypatch):
    from datapyn_runtime.database import ConnectionUnavailableError
    attempts = []
    monkeypatch.setattr(database.time, "sleep", lambda delay: None)
    def offline(config):
        attempts.append(config)
        raise OSError(errno.ECONNREFUSED, "network unavailable")
    monkeypatch.setattr(database, "connect", offline)
    pool = database.ConnectorPool()
    with pytest.raises(ConnectionUnavailableError) as failure:
        pool.activate(params())
    assert len(attempts) == 2 and not pool.items
    assert serialize_runtime_error(failure.value)["details"] == {"retryable": True}
    attempts.clear()
    def auth(config):
        attempts.append(config)
        raise RuntimeError("authentication rejected")
    monkeypatch.setattr(database, "connect", auth)
    with pytest.raises(RuntimeError, match="authentication rejected"):
        pool.activate(params())
    assert len(attempts) == 1


def test_explicit_ack_uses_rotated_saved_credentials_without_losing_block_affinity(monkeypatch):
    opened = factory(monkeypatch)
    pool = database.ConnectorPool()
    target = params(automatic=False)
    target["config"]["password"] = "old-private-password"
    previous = pool.activate(target, default=True)
    previous.lost = {"required": True, "acknowledgement_required": True}
    old_key = pool.active_key
    fresh = deepcopy(target)
    fresh["config"]["password"] = "rotated-private-password"
    result = pool.recover({**fresh, "acknowledge_state_loss": True})
    assert result["phase"] == "ready" and previous.closed
    assert opened[-1][0]["password"] == "rotated-private-password"
    assert old_key not in pool.items and pool.active_key == pool.default_active_key == pool.block_affinity["first"]
    assert pool.activate(fresh) is opened[-1][1] and len(opened) == 2


def test_explicit_recover_does_not_discard_a_healthy_pending_transaction(monkeypatch):
    opened = factory(monkeypatch)
    pool = database.ConnectorPool()
    previous = pool.activate(params(automatic=False))
    previous.has_pending_transaction = lambda: True
    assert pool.recover(params(automatic=False))["phase"] == "ready"
    assert pool.active is previous and not previous.closed and len(opened) == 1


@pytest.mark.parametrize("changed", [{"database": "other_database"}, {"schema": "other_schema"}, {"connection_id": "other_id"}, {"automatic_transactions": True}])
def test_late_acknowledgement_never_replaces_a_different_scope_or_transaction_mode(changed, monkeypatch):
    opened = factory(monkeypatch)
    pool = database.ConnectorPool()
    target = params(automatic=False)
    previous = pool.activate(target)
    previous.lost = {"required": True, "acknowledgement_required": True}
    outcome = pool.recover({**target, **changed, "acknowledge_state_loss": True})
    assert outcome["phase"] == "error" and not previous.closed and len(opened) == 1


def test_recover_selects_same_id_database_and_mode_without_borrowing_a_manual_peer(monkeypatch):
    opened = factory(monkeypatch)
    pool = database.ConnectorPool()
    first = pool.activate(params(automatic=False))
    first.lost = {"required": True, "acknowledgement_required": True}
    first_key = pool.active_key
    second_target = params(block="second", automatic=False)
    second_target["config"]["database"] = "other_database"
    second_target["database"] = "other_database"
    second = pool.activate(second_target)
    second_key = pool.active_key
    second.lost = {"required": True, "acknowledgement_required": True}
    third_target = params(block="third", automatic=False)
    third_target["database"] = "other_database"
    third_target["config"]["database"] = "other_database"
    result = pool.recover({**third_target, "acknowledge_state_loss": True})
    assert result["phase"] == "ready" and len(opened) == 3
    assert pool.items[first_key] is first and pool.items[second_key] is second
    assert not first.closed and not second.closed and pool.active is opened[-1][1]
    assert pool.active.connection_params["database"] == "other_database"
    assert pool.block_affinity["third"] not in {first_key, second_key}


def test_lost_temporary_namespace_requires_ack_before_replacing_it(monkeypatch):
    opened = factory(monkeypatch)
    pool = database.ConnectorPool()
    previous = pool.activate(params())
    previous.has_temporary_tables = True
    previous.lost = {"required": True, "acknowledgement_required": False}
    with pytest.raises(ConnectionLostError) as failure:
        pool.activate(params(), validate=True)
    assert failure.value.details["acknowledgement_required"] and len(opened) == 1
    assert pool.recover({**params(), "acknowledge_state_loss": True})["phase"] == "ready"


def test_closed_sqlite_memory_requires_acknowledgement_of_data_loss():
    pool = database.ConnectorPool()
    target = {"config": {"db_type": "sqlite", "database": ":memory:"}, "block_id": "first"}
    previous = pool.activate(target)
    previous.execute_query("CREATE TABLE private_memory(value INTEGER)")
    previous.connection.close()
    with pytest.raises(ConnectionLostError) as failure:
        pool.activate(target, validate=True)
    assert failure.value.details["acknowledgement_required"]
    result = pool.recover({**target, "acknowledge_state_loss": True})
    assert result["phase"] == "ready" and pool.active is not previous
    pool.disconnect()


def test_error_envelope_carries_only_safe_recovery_flags():
    error = ConnectionLostError(acknowledgement_required=True, submitted=True)
    error.details["password"] = "do-not-send"
    result = serialize_runtime_error(error)
    assert result["code"] == "connection_lost"
    assert result["details"] == {"acknowledgement_required": True, "submitted": True, "session_state_lost": True}


@pytest.mark.parametrize("manual", [False, True])
def test_kernel_keeps_namespace_and_never_replays_submitted_sql_while_recovering(monkeypatch, manual, tmp_path):
    opened = factory(monkeypatch)
    for method in ("initialize_kernel_group", "isolate_kernel_output", "_watch_parent", "enable_user_packages"):
        monkeypatch.setattr(kernel, method, lambda: None)
    monkeypatch.setattr("datapyn_runtime.notifications.capture_completion", lambda *args, **kwargs: None)
    monkeypatch.setattr("datapyn_runtime.variable_snapshot.settings_get", lambda: {"enabled": False})
    monkeypatch.setattr("datapyn_runtime.sql_safety_guard.settings_get", lambda *args: {"confirm_destructive_sql": False})
    target = params(automatic=not manual)
    target.pop("_execution_scope_id")
    target["_automatic_transactions_snapshot"] = not manual
    other = {**deepcopy(target), "block_id": "other-block", "scope_inherited": False, "database": "other_database"}
    other["config"]["database"] = "other_database"
    jobs = [
        {"method": "connection.connect", "job_id": "connect", "params": target},
        {"method": "execution.run", "job_id": "seed", "params": {**target, "execution_id": "seed", "language": "python", "code": "frame=pd.DataFrame({'id':[7]})\ndef sql(): return 5"}},
        {"method": "execution.run", "job_id": "failure", "params": {**target, "execution_id": "failure", "language": "sql", "code": "SELECT fail_transport"}},
        {"method": "execution.run", "job_id": "local", "params": {**target, "execution_id": "local", "language": "python", "code": "assert sql()==5\nassert frame['id'].tolist()==[7]\nframe['checked'] = frame.id + 1"}},
        {"method": "execution.run", "job_id": "other", "params": {**other, "execution_id": "other", "language": "sql", "code": "SELECT 9"}},
        {"method": "connection.recover", "job_id": "recover", "params": {**target, "acknowledge_state_loss": True}},
        {"method": "execution.run", "job_id": "final", "params": {**target, "execution_id": "final", "language": "sql", "code": "SELECT 42"}},
        {"method": "shutdown", "job_id": "shutdown", "params": {}},
    ]
    class Commands:
        def poll(self, timeout): return True
        def recv(self): return jobs.pop(0)
        def close(self): pass
    messages = []
    kernel.kernel_main("session", Commands(), SimpleNamespace(send=messages.append, close=lambda: None))
    failure = next(message["payload"] for message in messages if message.get("job_id") == "failure")
    assert failure["status"] == "failed" and failure["connection_lost"] is True
    assert failure["connection_recovery"]["phase"] == ("blocked" if manual else "ready")
    local = next(message["payload"] for message in messages if message.get("job_id") == "local")
    assert local["status"] == "succeeded", local.get("error", local)
    assert any(variable["name"] == "frame" for variable in local["variables"])
    published = [message["language_context"] for message in messages if message.get("language_context", {}).get("variables", {}).get("frame", {}).get("columns") == ["id", "checked"]]
    assert published
    recovered_index = next(index for index, message in enumerate(messages) if message.get("job_id") == "recover")
    recovered_context = [message["language_context"] for message in messages[:recovered_index] if "language_context" in message][-1]
    from datapyn_runtime.transaction_settings import editor_context_key
    assert recovered_context["key"] == editor_context_key(target)
    assert recovered_context["block_id"] == "first" and recovered_context["database"] == "after_use"
    final = next(message["payload"] for message in messages if message.get("job_id") == "final")
    assert final["status"] == "succeeded", final
    assert sum(connector.statements.count("SELECT fail_transport") for _, connector in opened) == 1
    assert sum(connector.statements.count("SELECT 42") for _, connector in opened) == 1
    assert any(message.get("language_context", {}).get("metadata_invalidated") for message in messages)


def test_python_managed_engine_alias_unwraps_loss_and_preserves_data_without_sql_replay(monkeypatch):
    from sqlalchemy.exc import DBAPIError
    opened, reads = [], []
    def connect(config):
        connector = Connector(config)
        class Engine:
            def read(self):
                reads.append(self)
                connector.lost = {"required": True, "acknowledgement_required": False, "submitted": True}
                error = ConnectionLostError(submitted=True)
                error._datapyn_connector = connector
                raise DBAPIError(None, None, error, connection_invalidated=True)
        connector.engine = Engine()
        opened.append(connector)
        return connector
    monkeypatch.setattr(database, "connect", connect)
    for method in ("initialize_kernel_group", "isolate_kernel_output", "_watch_parent", "enable_user_packages"):
        monkeypatch.setattr(kernel, method, lambda: None)
    monkeypatch.setattr("datapyn_runtime.notifications.capture_completion", lambda *args, **kwargs: None)
    monkeypatch.setattr("datapyn_runtime.variable_snapshot.settings_get", lambda: {"enabled": False})
    monkeypatch.setattr("datapyn_runtime.sql_safety_guard.settings_get", lambda *args: {"confirm_destructive_sql": False})
    target = {**params(), "_automatic_transactions_snapshot": True}
    jobs = [
        {"method": "connection.connect", "job_id": "connect", "params": target},
        {"method": "execution.run", "job_id": "seed", "params": {**target, "execution_id": "seed", "language": "python", "code": "frame=pd.DataFrame({'id':[9]})\nengine_alias=db_engine"}},
        {"method": "execution.run", "job_id": "failure", "params": {**target, "execution_id": "failure", "language": "python", "code": "frame['before_loss'] = 1\nengine_alias.read()"}},
        {"method": "execution.run", "job_id": "local", "params": {**target, "execution_id": "local", "language": "python", "code": "assert frame['id'].tolist()==[9]"}},
        {"method": "shutdown", "job_id": "shutdown", "params": {}},
    ]
    class Commands:
        def poll(self, timeout): return True
        def recv(self): return jobs.pop(0)
        def close(self): pass
    messages = []
    kernel.kernel_main("session", Commands(), SimpleNamespace(send=messages.append, close=lambda: None))
    failure = next(message["payload"] for message in messages if message.get("job_id") == "failure")
    assert failure["status"] == "failed" and failure["connection_lost"] is True
    assert failure["error_code"] == "connection_lost" and failure["connection_recovery"]["phase"] == "ready"
    assert len(reads) == 1 and len(opened) == 2
    assert any(message.get("language_context", {}).get("variables", {}).get("frame", {}).get("columns") == ["id", "before_loss"] for message in messages)
    local = next(message["payload"] for message in messages if message.get("job_id") == "local")
    assert local["status"] == "succeeded", local


@pytest.mark.parametrize("error_code", ["ssh_host_key_changed", "ssh_auth_failed"])
def test_cached_ssh_preflight_rejection_retains_result_contract_and_original_challenge(error_code, monkeypatch):
    from datapyn_runtime.ssh_tunnel import SshTunnelError
    opened, messages = [], []
    details = {"host": "offline.invalid", "port": 22, "fingerprint": "SHA256:synthetic-public-key",
               "expected_fingerprint": "SHA256:old-public-key", "password": "must-not-escape"}
    def connect(config):
        if opened:
            raise SshTunnelError("Synthetic reconnect rejection", code=error_code, details=details)
        connector = Connector(config)
        connector._ssh_tunnel = SimpleNamespace(alive=True)
        connector._ssh_tunnel.is_alive = lambda: connector._ssh_tunnel.alive
        opened.append(connector)
        return connector
    monkeypatch.setattr(database, "connect", connect)
    for method in ("initialize_kernel_group", "isolate_kernel_output", "_watch_parent", "enable_user_packages"):
        monkeypatch.setattr(kernel, method, lambda: None)
    monkeypatch.setattr("datapyn_runtime.notifications.capture_completion", lambda *args, **kwargs: None)
    monkeypatch.setattr("datapyn_runtime.variable_snapshot.settings_get", lambda: {"enabled": False})
    monkeypatch.setattr("datapyn_runtime.sql_safety_guard.settings_get", lambda *args: {"confirm_destructive_sql": False})
    target = {**params(), "_automatic_transactions_snapshot": True}
    target["config"]["ssh"] = {"enabled": True, "host": "offline.invalid", "port": 22}
    jobs = [
        {"method": "connection.connect", "job_id": "connect", "params": target},
        {"method": "execution.run", "job_id": "seed", "params": {**target, "execution_id": "seed", "language": "python", "code": "frame=pd.DataFrame({'id':[7]})\nframe"}},
        {"method": "execution.run", "job_id": "failure", "params": {**target, "execution_id": "failure", "language": "sql", "code": "SELECT 42"}},
        {"method": "shutdown", "job_id": "shutdown", "params": {}},
    ]
    class Commands:
        def poll(self, timeout): return True
        def recv(self): return jobs.pop(0)
        def close(self): pass
    def send(message):
        messages.append(message)
        if message.get("job_id") == "seed":
            opened[0]._ssh_tunnel.alive = False
    kernel.kernel_main("session", Commands(), SimpleNamespace(send=send, close=lambda: None))
    seed = next(message["payload"] for message in messages if message.get("job_id") == "seed")
    failed = next(message["payload"] for message in messages if message.get("job_id") == "failure")
    assert seed["status"] == "succeeded" and seed["results"]
    assert failed["status"] == "failed" and failed["connection_lost"] is True
    assert failed["connection_recovery"]["phase"] == "error" and failed["connection_recovery"]["session_state_lost"] is True
    assert failed["error_code"] == error_code and failed["error_details"]["host"] == "offline.invalid"
    assert failed["error_details"]["fingerprint"] == "SHA256:synthetic-public-key"
    assert "password" not in failed["error_details"]
    assert any(variable["name"] == "frame" for variable in failed["variables"])
    assert opened[0].statements == []
