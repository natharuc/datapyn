"""Diagnostics are optional observers, never dependencies of execution delivery."""

import json
import threading
from types import SimpleNamespace

import pytest

from datapyn_runtime import telemetry
from datapyn_runtime.supervisor import Supervisor


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry.TelemetryService, "_start", lambda self: None)
    sent = []
    instance = telemetry.TelemetryService(tmp_path / "consent.json", sender=lambda endpoint, events: sent.append((endpoint, events)))
    instance.configure({"enabled": True, "endpoint": "https://collector.example.com/v1/events"})
    instance.sent = sent
    yield instance
    instance.close()


@pytest.mark.parametrize("value", [10**400, -(10**400)])
def test_arbitrary_json_integer_cannot_break_diagnostic_capture(value):
    event = telemetry.safe_event({"event": "execution_finished", "duration_ms": value, "attempt": value})
    assert 0 <= event["duration_ms"] <= 86_400_000
    assert 0 <= event["attempt"] <= 10
    json.dumps(event, allow_nan=False)


@pytest.mark.parametrize("message", [
    {"event": [], "payload": {}},
    {"event": {}, "payload": {}},
    {"event": "execution.finished", "payload": {"duration_ms": 10**400, "status": "succeeded"}},
    {"event": "connection.recovery", "payload": {"duration_ms": 10**400, "attempt": 10**400}},
])
def test_malformed_optional_observations_never_propagate_to_execution(message, service):
    service.observe(message)
    service.flush_once()


def test_observer_implementation_failure_never_prevents_supervisor_delivery():
    sent = []
    supervisor = Supervisor.__new__(Supervisor)
    supervisor._internal_lock = threading.RLock()
    supervisor._notification_deliveries = {}
    supervisor._internal = {}
    supervisor._emit = sent.append

    def failure(_message):
        raise RuntimeError("unavailable optional observer")

    supervisor.telemetry = SimpleNamespace(observe=failure)
    message = {"event": "execution.finished", "payload": {"execution_id": "execution", "session_id": "session", "status": "succeeded"}}
    supervisor._deliver(message)
    assert sent == [message]


def test_recording_failure_is_also_isolated_at_the_observer_boundary(service):
    def failure(_params):
        raise RuntimeError("optional queue unavailable")
    service.record = failure
    service.observe({"event": "execution.finished", "payload": {"status": "succeeded"}})


def test_optional_worker_start_failure_cannot_prevent_app_startup(tmp_path, monkeypatch):
    path = tmp_path / "consent.json"
    telemetry.settings_set({"enabled": True}, path)

    def unavailable(_thread):
        raise RuntimeError("cannot start optional thread")

    monkeypatch.setattr(threading.Thread, "start", unavailable)
    instance = telemetry.TelemetryService(path, sender=lambda *_: None)
    instance.close()


def test_optional_worker_start_failure_cannot_break_consent_configuration(tmp_path, monkeypatch):
    instance = telemetry.TelemetryService(tmp_path / "consent.json", sender=lambda *_: None)

    def unavailable(_thread):
        raise RuntimeError("cannot start optional thread")

    monkeypatch.setattr(threading.Thread, "start", unavailable)
    try:
        instance.configure({"enabled": True})
    finally:
        instance.close()


def test_capture_started_before_a_consent_transition_is_not_sent_to_a_new_target(service, monkeypatch):
    started, finish = threading.Event(), threading.Event()
    original = telemetry.safe_event
    failures = []

    def delayed(*args, **kwargs):
        started.set()
        assert finish.wait(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(telemetry, "safe_event", delayed)

    def capture():
        try:
            service.record({"event": "ui_error"})
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=capture)
    thread.start()
    assert started.wait(2)
    service.configure({"enabled": False, "endpoint": "https://collector.example.com/v1/events"})
    service.configure({"enabled": True, "endpoint": "https://another.example.com/v1/events"})
    finish.set()
    thread.join(2)
    assert not thread.is_alive() and failures == []
    service.flush_once()
    assert service.sent == []


def test_result_contents_and_negative_or_boolean_counts_never_escape_aggregate_buckets(service):
    service.observe({"event": "execution.finished", "payload": {"status": "succeeded", "results": [
        {"row_count": -1, "data": {"private": "salary"}}, {"row_count": True, "password": "secret"},
        {"row_count": "private-value", "host": "internal"},
    ]}})
    service.flush_once()
    assert "private" not in json.dumps(service.sent) and "secret" not in json.dumps(service.sent)
    assert service.sent[0][1][0]["rows_bucket"] in telemetry.ROW_BUCKETS
