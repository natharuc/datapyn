"""Opt-in diagnostics cannot observe content, block execution or grow unbounded."""
from __future__ import annotations

import json
import threading

import pytest

from datapyn_runtime.telemetry import (BATCH_SIZE, MAX_AGE, MAX_QUEUE, TelemetryService,
                                      endpoint_url, safe_event, settings_get, settings_set)


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(TelemetryService, "_start", lambda self: None)
    values = []
    instance = TelemetryService(tmp_path / "telemetry.json", sender=lambda endpoint, events: values.append((endpoint, events)))
    instance.sent_batches = values
    yield instance
    instance.close()


def enable(service):
    return service.configure({"enabled": True, "endpoint": "https://telemetry.example.com/v1/events"})


def test_new_installation_never_starts_a_thread_or_sends_without_opt_in(service):
    assert service.status()["enabled"] is False
    assert service._thread is None
    assert service.record({"event": "ui_error"}) == {"accepted": False}
    service.client_info({"version": "1.0.13"})
    service.flush_once()
    assert service.sent_batches == []
    assert service.status()["queued"] == 0


def test_opt_in_round_trip_and_revocation_clear_queue(service):
    enable(service)
    service.record({"event": "ui_error"})
    assert service.status()["queued"] == 1
    service.configure({"enabled": False, "endpoint": "https://telemetry.example.com/v1/events"})
    assert service.status()["queued"] == 0
    assert settings_get(service.path)["enabled"] is False
    service.flush_once()
    assert service.sent_batches == []


@pytest.mark.parametrize("endpoint", ["http://example.com", "https://user:password@example.com", "https://example.com/?token=secret",
                                      "https://example.com/#fragment", "https://localhost/x", "https://127.0.0.1/x",
                                      "https://[::1]/x", "https://192.168.1.2/x", "https://host.local/x", "https://example.com:22/x",
                                      "https://example.com:bad/x", "https://example.com/\nsecret", "file:///etc/passwd", None])
def test_endpoint_accepts_only_public_https_without_embedded_secrets(endpoint):
    with pytest.raises(ValueError):
        endpoint_url(endpoint)


@pytest.mark.parametrize("host", ["localhost.", "localhost。", "127.0.0.1.", "127.1", "2130706433", "0x7f000001", "0177.0.0.1", "0x7f.1"])
def test_alternative_loopback_host_spellings_are_not_public_endpoints(host):
    with pytest.raises(ValueError):
        endpoint_url(f"https://{host}/v1/events")


def test_corrupt_consent_fails_closed_and_does_not_create_thread(tmp_path):
    path = tmp_path / "telemetry.json"
    path.write_text('{"enabled":"true"}', encoding="utf-8")
    instance = TelemetryService(path)
    assert instance.status()["enabled"] is False
    assert instance._thread is None
    instance.close()


def test_nonboolean_consent_is_rejected_without_replacing_previous_consent(tmp_path):
    path = tmp_path / "telemetry.json"
    before = settings_set({"enabled": False}, path)
    with pytest.raises(ValueError):
        settings_set({"enabled": "yes"}, path)
    assert settings_get(path) == before


def test_diagnostic_builder_discards_content_and_personal_identifiers():
    event = safe_event({"event": "connection_recovery", "status": "ready", "db_type": "postgresql", "attempt": 2,
                        "sql": "DELETE FROM private_table", "password": "private-password", "host": "private.internal",
                        "username": "private-user", "file": "C:/private/report.xlsx", "error": "private-stack",
                        "rows": [{"salary": 999}], "duration_ms": 123.4567}, version="1.0.13", platform="windows")
    assert event == {"event": "connection_recovery", "version": "1.0.13", "platform": "windows", "db_type": "postgresql",
                     "status": "ready", "error_code": "unknown", "duration_ms": 123.457, "attempt": 2, "rows_bucket": "none"}
    assert "private" not in json.dumps(event)


@pytest.mark.parametrize("payload", [None, [], {"event": []}, {"event": "private-user"}])
def test_unrecognized_event_never_enters_queue(service, payload):
    enable(service)
    assert service.record(payload)["accepted"] is False
    assert service.status()["queued"] == 0


def test_dimensions_are_fixed_categories_and_numbers_are_bounded():
    event = safe_event({"event": "ui_error", "db_type": "private-server", "status": "my-secret", "error_code": "access_token=private",
                        "duration_ms": float("nan"), "attempt": 100, "rows_bucket": "salary"}, version="private-host", platform="private-host")
    assert event["version"] == "dev" and event["platform"] == "other"
    assert event["db_type"] == "none" and event["status"] == "error" and event["error_code"] == "unknown"
    assert event["duration_ms"] == 0 and event["attempt"] == 10 and event["rows_bucket"] == "none"
    assert "private" not in json.dumps(event)


def test_observation_extracts_only_aggregate_execution_fields(service):
    enable(service)
    service.observe({"event": "execution.finished", "payload": {"session_id": "private-id", "status": "failed", "connection_lost": True,
        "db_type": "sqlserver", "duration_ms": 20, "error": "secret-error-text", "results": [{"row_count": 102, "data": "private"}]}})
    service.observe({"event": "connection.recovery", "payload": {"phase": "ready", "db_type": "sqlserver", "attempt": 1, "requested_scope": {"database": "private"}}})
    service.observe({"event": "execution.output", "payload": {"text": "private-stdout"}})
    service.flush_once()
    events = service.sent_batches[0][1]
    assert events[0]["error_code"] == "transport" and events[0]["rows_bucket"] == "101-10000"
    assert events[1]["event"] == "connection_recovery" and len(events) == 2
    assert "private" not in json.dumps(events) and "secret" not in json.dumps(events)


def test_queue_and_batch_sizes_are_bounded(service):
    enable(service)
    for _ in range(MAX_QUEUE + 20):
        service.record({"event": "ui_error"})
    assert service.status()["queued"] == MAX_QUEUE
    assert service.status()["dropped"] == 20
    service.flush_once()
    assert len(service.sent_batches[0][1]) == BATCH_SIZE
    assert service.status()["queued"] == MAX_QUEUE - BATCH_SIZE


def test_offline_sender_retries_only_three_times_and_retains_no_exception_text(service):
    enable(service)
    def offline(*args):
        raise OSError("private-url private-token")
    service._sender = offline
    service.record({"event": "ui_error"})
    for _ in range(3):
        service.flush_once()
    assert service.status()["queued"] == 0 and service.status()["dropped"] == 1
    assert service.status()["last_status"] == "offline"
    assert "private" not in json.dumps(service.status())


def test_expired_events_are_dropped_instead_of_sending_old_usage(service):
    enable(service)
    now = [1.0]
    service._clock = lambda: now[0]
    service.record({"event": "ui_error"})
    now[0] += MAX_AGE + 1
    service.flush_once()
    assert service.sent_batches == [] and service.status()["dropped"] == 1


def test_endpoint_change_drops_old_target_queue(service):
    enable(service)
    service.record({"event": "ui_error"})
    service.configure({"enabled": True, "endpoint": "https://another.example.com/v1/events"})
    service.flush_once()
    assert service.sent_batches == []


def test_slow_collector_does_not_block_recording_revocation_or_shutdown(service):
    enable(service)
    started, finish = threading.Event(), threading.Event()
    def slow(*args):
        started.set()
        assert finish.wait(3)
        raise OSError("offline")
    service._sender = slow
    service.record({"event": "ui_error"})
    thread = threading.Thread(target=service.flush_once)
    thread.start()
    assert started.wait(2)
    service.record({"event": "ui_error"})
    service.configure({"enabled": False})
    service.close()
    finish.set()
    thread.join(2)
    assert not thread.is_alive() and service.status()["queued"] == 0


def test_version_comes_from_packaged_host_without_identifying_the_machine(service, monkeypatch):
    monkeypatch.setenv("DATAPYN_TAURI_VERSION", "1.0.13")
    service._version = "1.0.13"
    enable(service)
    service.client_info({"version": "9.9.9", "installation_id": "private"})
    service.flush_once()
    event = service.sent_batches[0][1][0]
    assert event["version"] == "1.0.13" and event["event"] == "app_start"
    assert "installation_id" not in event
