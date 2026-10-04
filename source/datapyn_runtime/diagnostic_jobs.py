"""Coalesced syntax checks that cannot fill the completion or execution queues."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import threading

MAX_PENDING_BLOCKS = 64
MAX_PENDING_BYTES = 8 * 1024 * 1024


@dataclass
class _DiagnosticJob:
    request_id: int
    params: dict
    context: dict
    key: tuple
    sequence: int
    code_bytes: int


class DiagnosticJobs:
    """One running check and at most one waiting revision for each block.

    A dedicated thread keeps diagnostics off the autocomplete pool. Pending
    replacements are removed immediately instead of leaving cancelled work and
    complete document snapshots in an executor's unbounded queue.
    """

    def __init__(self, emit, closed, *, dispatch=None):
        self.emit = emit
        self.closed = closed
        self.dispatch = dispatch
        self.condition = threading.Condition()
        self.pending = OrderedDict()
        self.latest = {}
        self.pending_bytes = 0
        self.sequence = 0
        self.active = None
        self.thread = threading.Thread(target=self._loop, name="syntax-diagnostics", daemon=True)
        self.thread.start()

    @property
    def active_count(self):
        with self.condition:
            return len(self.pending) + int(self.active is not None)

    @staticmethod
    def _superseded():
        return {"result": {"markers": [], "superseded": True}}

    def _emit(self, job, message):
        if not self.closed.is_set():
            self.emit({"id": job.request_id, **message})

    def submit(self, request_id, params, context):
        key = (params.get("session_id"), params.get("block_id") or ("request", request_id))
        code_bytes = len(params.get("code", "").encode("utf-8"))
        with self.condition:
            if self.closed.is_set():
                raise RuntimeError("Runtime is closing")
            previous = self.pending.get(key)
            pending_bytes = self.pending_bytes - (previous.code_bytes if previous else 0) + code_bytes
            if (previous is None and len(self.pending) >= MAX_PENDING_BLOCKS) or pending_bytes > MAX_PENDING_BYTES:
                raise ValueError("Too many pending syntax checks; retry after the previous check finishes")
            self.sequence += 1
            job = _DiagnosticJob(request_id, dict(params), context, key, self.sequence, code_bytes)
            self.pending[key] = job
            self.latest[key] = job
            self.pending_bytes = pending_bytes
            self.condition.notify()
        if previous is not None:
            self._emit(previous, self._superseded())

    def cancel(self, session_id, block_id, diagnostic_id):
        return self._cancel((session_id, block_id), diagnostic_id, exact=True)

    def cancel_block(self, session_id, block_id):
        return self._cancel((session_id, block_id))

    def _cancel(self, key, diagnostic_id=None, *, exact=False):
        with self.condition:
            current = self.latest.get(key)
            if current is None or (exact and current.params.get("diagnostic_id") != diagnostic_id):
                return {"status": "already_finished"}
            self.latest.pop(key, None)
            pending = self.pending.pop(key, None)
            if pending is not None:
                self.pending_bytes -= pending.code_bytes
        if pending is not None:
            self._emit(pending, self._superseded())
        return {"status": "cancelling"}

    def cancel_session(self, session_id):
        with self.condition:
            pending = [job for key, job in self.pending.items() if key[0] == session_id]
            for job in pending:
                self.pending.pop(job.key, None)
                self.pending_bytes -= job.code_bytes
            for key in list(self.latest):
                if key[0] == session_id:
                    self.latest.pop(key, None)
        for job in pending:
            self._emit(job, self._superseded())

    def _stale(self, job):
        with self.condition:
            return self.closed.is_set() or self.latest.get(job.key) is not job

    def _loop(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed.is_set() or bool(self.pending))
                if self.closed.is_set():
                    return
                _, job = self.pending.popitem(last=False)
                self.pending_bytes -= job.code_bytes
                self.active = job
            try:
                if self._stale(job):
                    message = self._superseded()
                else:
                    dispatch = self.dispatch
                    if dispatch is None:
                        from .language import dispatch
                    result = dispatch("language.diagnostics", job.params, job.context,
                                      should_abort=lambda: self._stale(job))
                    message = {"result": result}
            except BaseException as exc:
                message = {"error": {"code": "operation_failed", "message": f"{type(exc).__name__}: {exc}"}}
            with self.condition:
                if self._stale(job):
                    message = self._superseded()
                if self.latest.get(job.key) is job:
                    self.latest.pop(job.key, None)
                self.active = None
            self._emit(job, message)

    def close(self):
        self.closed.set()
        with self.condition:
            self.pending.clear()
            self.latest.clear()
            self.pending_bytes = 0
            self.condition.notify_all()
