from __future__ import annotations

from collections import OrderedDict, deque
import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from datapyn_runtime.background import BackgroundJobs
from datapyn_runtime.diagnostic_jobs import DiagnosticJobs
from datapyn_runtime.supervisor import MAX_CODE_BYTES, SessionRuntime, Supervisor


def params(revision=1, block="a", code="x = 1"):
    return {"session_id": "session", "block_id": block, "diagnostic_id": f"d{revision}",
            "language": "python", "code": code}


def response(messages, request_id):
    deadline = time.monotonic() + 2
    deferred = []
    try:
        while time.monotonic() < deadline:
            message = messages.get(timeout=max(.01, deadline - time.monotonic()))
            if message["id"] == request_id:
                return message
            deferred.append(message)
        raise AssertionError(f"No response for {request_id}")
    finally:
        for message in deferred:
            messages.put(message)


@pytest.fixture
def blocked_jobs():
    messages = queue.Queue()
    entered, release = threading.Event(), threading.Event()
    parsed = []

    def dispatch(method, document, context, *, should_abort):
        parsed.append(document["diagnostic_id"])
        if document["diagnostic_id"] == "d1":
            entered.set()
            assert release.wait(3)
        return {"status": "complete", "markers": [{"message": document["code"]}]}

    jobs = DiagnosticJobs(messages.put, threading.Event(), dispatch=dispatch)
    jobs.submit(1, params(1), {})
    assert entered.wait(2)
    yield jobs, messages, parsed, release
    release.set()
    jobs.close()
    jobs.thread.join(timeout=2)
    assert not jobs.thread.is_alive()


def test_typing_keeps_only_the_last_document_for_each_waiting_block(blocked_jobs):
    jobs, messages, parsed, release = blocked_jobs
    for revision in range(2, 1002):
        jobs.submit(revision, params(revision, code=f"revision_{revision}"), {})
    with jobs.condition:
        assert len(jobs.pending) == 1
        assert len(jobs.latest) == 1
        assert jobs.pending_bytes == len("revision_1001")
    assert jobs.active_count == 2
    assert response(messages, 500)["result"] == {"markers": [], "superseded": True}
    assert parsed == ["d1"]
    release.set()
    assert response(messages, 1)["result"]["superseded"]
    assert response(messages, 1001)["result"] == {"status": "complete", "markers": [{"message": "revision_1001"}]}
    assert parsed == ["d1", "d1001"]


def test_cancel_is_exact_and_never_removes_a_newer_diagnostic(blocked_jobs):
    jobs, messages, _, _release = blocked_jobs
    jobs.submit(2, params(2), {})
    jobs.submit(3, params(3), {})
    assert jobs.cancel("session", "a", "d2") == {"status": "already_finished"}
    assert jobs.pending[("session", "a")].params["diagnostic_id"] == "d3"
    assert jobs.cancel("session", "a", "d3") == {"status": "cancelling"}
    assert not jobs.pending and not jobs.latest and jobs.pending_bytes == 0
    assert response(messages, 3)["result"]["superseded"]


def test_active_diagnostic_cooperatively_observes_cancellation():
    messages = queue.Queue()
    entered = threading.Event()

    def dispatch(method, document, context, *, should_abort):
        entered.set()
        deadline = time.monotonic() + 2
        while not should_abort() and time.monotonic() < deadline:
            time.sleep(.001)
        assert should_abort()
        # Even a parser result returned just after cancellation cannot publish.
        return {"markers": [{"message": "obsolete error"}]}

    jobs = DiagnosticJobs(messages.put, threading.Event(), dispatch=dispatch)
    try:
        jobs.submit(1, params(), {})
        assert entered.wait(2)
        assert jobs.cancel("session", "a", "d1")["status"] == "cancelling"
        assert response(messages, 1)["result"] == {"markers": [], "superseded": True}
        assert jobs.active_count == 0
    finally:
        jobs.close()
        jobs.thread.join(timeout=2)


def test_closing_and_recreating_a_session_cannot_revive_its_old_checks(blocked_jobs):
    jobs, messages, _, release = blocked_jobs
    jobs.submit(2, params(2, "b"), {})
    jobs.cancel_session("session")
    assert response(messages, 2)["result"]["superseded"]
    assert not jobs.latest and jobs.pending_bytes == 0
    jobs.submit(3, params(3), {})
    assert jobs.latest[("session", "a")].params["diagnostic_id"] == "d3"
    assert jobs._stale(jobs.active)
    release.set()
    assert response(messages, 1)["result"]["superseded"]
    assert response(messages, 3)["result"]["status"] == "complete"


def test_pending_document_memory_and_block_count_are_bounded(blocked_jobs, monkeypatch):
    from datapyn_runtime import diagnostic_jobs
    jobs, _, _, _release = blocked_jobs
    monkeypatch.setattr(diagnostic_jobs, "MAX_PENDING_BLOCKS", 2)
    monkeypatch.setattr(diagnostic_jobs, "MAX_PENDING_BYTES", 12)
    jobs.submit(2, params(2, "b", "abcde"), {})
    jobs.submit(3, params(3, "c", "abcde"), {})
    with pytest.raises(ValueError, match="Too many pending"):
        jobs.submit(4, params(4, "d", "a"), {})
    with pytest.raises(ValueError, match="Too many pending"):
        jobs.submit(5, params(5, "b", "abcdefgh"), {})
    jobs.submit(6, params(6, "b", "abcdefg"), {})
    assert jobs.pending_bytes == 12
    assert jobs.pending[("session", "b")].params["diagnostic_id"] == "d6"
    assert jobs.cancel("session", "b", "d6")["status"] == "cancelling"
    assert jobs.pending_bytes == 5


def test_diagnostics_do_not_consume_completion_slots_or_threads(monkeypatch):
    from datapyn_runtime import language
    messages = queue.Queue()
    entered, release = threading.Event(), threading.Event()

    def dispatch(method, document, context, **options):
        if method == "language.diagnostics":
            entered.set()
            assert release.wait(3)
            return {"markers": []}
        return {"items": [{"label": "responsive"}]}

    monkeypatch.setattr(language, "dispatch", dispatch)
    jobs = BackgroundJobs(messages.put, completion_process=False)
    try:
        jobs.submit(1, "language.diagnostics", params(), {})
        assert entered.wait(2)
        acquired = [jobs.slots.acquire(blocking=False) for _ in range(16)]
        assert all(acquired)
        for acquired_slot in acquired:
            if acquired_slot:
                jobs.slots.release()
        jobs.submit(2, "language.complete", params(2), {})
        assert response(messages, 2)["result"]["items"][0]["label"] == "responsive"
        assert jobs.active_count >= 1
    finally:
        release.set()
        jobs.close()
        jobs.diagnostic_jobs.thread.join(timeout=2)


def test_system_activity_counts_diagnostic_queue_completion_and_flush_without_relocking(monkeypatch):
    from datapyn_runtime import language
    diagnostic_entered, completion_entered, release = threading.Event(), threading.Event(), threading.Event()

    def dispatch(method, document, context, **options):
        (diagnostic_entered if method == "language.diagnostics" else completion_entered).set()
        assert release.wait(3)
        return {"markers": []} if method == "language.diagnostics" else {"items": []}

    monkeypatch.setattr(language, "dispatch", dispatch)
    jobs = BackgroundJobs(lambda message: None, completion_process=False)
    runtime = Supervisor.__new__(Supervisor)
    runtime.sessions = {}
    runtime.background = jobs
    runtime.pynia = SimpleNamespace(lock=threading.Lock(), installations={}, conversations={})
    runtime._internal_lock = threading.RLock()
    runtime._flushes = 1
    runtime.desktop_services = SimpleNamespace(busy=False)
    try:
        jobs.submit(1, "language.diagnostics", params(1), {})
        assert diagnostic_entered.wait(2)
        jobs.submit(2, "language.diagnostics", params(2), {})
        jobs.submit(3, "language.complete", params(3), {})
        assert completion_entered.wait(2)
        assert runtime.dispatch("system.activity", {}, 4) == {
            "busy": True, "executions": 0, "packages": 0, "pynia": 0, "background": 4}
    finally:
        release.set()
        jobs.close()
        jobs.diagnostic_jobs.thread.join(timeout=2)
        jobs.executor.shutdown(wait=True)
    runtime._flushes = 0
    assert runtime.dispatch("system.activity", {}, 5) == {
        "busy": False, "executions": 0, "packages": 0, "pynia": 0, "background": 0}


def test_context_snapshot_does_not_scan_code_or_queue_sql_metadata(monkeypatch):
    from datapyn_runtime import sql_context
    session = SessionRuntime.__new__(SessionRuntime)
    session._lock = threading.RLock()
    session.language_contexts = OrderedDict({"connection||": {"schema": {"db_type": "sqlite"}}})
    session.language_variables = {"total": {"type": "int"}}
    session.language_version = 7
    session._queue = deque()
    monkeypatch.setattr(sql_context, "metadata_signature", Mock(side_effect=AssertionError("must not scan")))
    result = session.editor_context({"language": "sql", "connection_id": "connection", "code": "SELECT invalid"}, refresh=False)
    assert result == {"schema": {"db_type": "sqlite"}, "variables": session.language_variables, "version": 7}
    assert result["variables"] is not session.language_variables
    assert not session._queue


def supervisor_stub():
    runtime = Supervisor.__new__(Supervisor)
    runtime.background = SimpleNamespace(submit=Mock(), cancel_diagnostics=Mock(return_value={"status": "cancelling"}),
                                         diagnostic_jobs=SimpleNamespace(cancel_block=Mock()))
    runtime.sessions = {"session": SimpleNamespace(editor_context=Mock(return_value={"version": 2}))}
    return runtime


def test_supervisor_accepts_diagnostics_before_any_kernel_has_been_created():
    runtime = supervisor_stub()
    document = {"language": "python", "code": "if :", "block_id": "a", "diagnostic_id": "d1"}
    assert runtime.dispatch("language.diagnostics", document, 1) is None
    runtime.background.submit.assert_called_once_with(1, "language.diagnostics", document, {})


def test_supervisor_routes_diagnostics_using_only_cached_context():
    runtime = supervisor_stub()
    document = params()
    assert runtime.dispatch("language.diagnostics", document, 1) is None
    runtime.sessions["session"].editor_context.assert_called_once_with(document, refresh=False)
    runtime.background.submit.assert_called_once_with(1, "language.diagnostics", document, {"version": 2})


@pytest.mark.parametrize("code", ["a" * (MAX_CODE_BYTES + 1), "é" * (MAX_CODE_BYTES // 2 + 1)], ids=["ascii", "utf8"])
def test_oversized_document_reports_partial_validation_before_allocating_a_job(code):
    runtime = supervisor_stub()
    result = runtime.dispatch("language.diagnostics", {**params(code=code), "locale": "pt-BR"}, 1)
    assert result["status"] == "partial" and result["markers"] == []
    assert "1 MiB" in result["message"]
    runtime.background.submit.assert_not_called()
    runtime.background.diagnostic_jobs.cancel_block.assert_called_once_with("session", "a")
    runtime.sessions["session"].editor_context.assert_not_called()


def test_supervisor_diagnostic_cancel_uses_the_exact_identifier():
    runtime = supervisor_stub()
    assert runtime.dispatch("language.diagnostics.cancel", params(7), 1) == {"status": "cancelling"}
    runtime.background.cancel_diagnostics.assert_called_once_with("session", "a", "d7")


def test_real_protocol_validates_without_a_kernel_and_while_user_code_is_busy(tmp_path, monkeypatch):
    from test_runtime import Client
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "state"))
    client = Client()
    try:
        initial = client.request("language.diagnostics", {
            "language": "sql", "code": "SELECT 1 +", "block_id": "sql", "diagnostic_id": "before-kernel"})
        assert initial["status"] == "complete" and initial["markers"]
        client.session("busy")
        client.request("execution.run", {"session_id": "busy", "execution_id": "sleep",
                                         "language": "python", "code": "import time\ntime.sleep(30)"})
        client.event("execution.started", execution_id="sleep")
        started = time.monotonic()
        result = client.request("language.diagnostics", {
            "session_id": "busy", "language": "python", "code": "def broken(:",
            "block_id": "python", "diagnostic_id": "during-execution", "locale": "pt-BR"})
        assert result["status"] == "complete" and result["markers"]
        assert time.monotonic() - started < 2
        client.request("execution.cancel", {"session_id": "busy", "execution_id": "sleep"})
        assert client.event("execution.finished", execution_id="sleep")["status"] == "cancelled"
    finally:
        client.close()
