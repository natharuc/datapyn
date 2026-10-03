"""Bounded editor jobs, independent from busy execution kernels."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import sys
import threading
import time

from .process_group import initialize_kernel_group, own_process_group
from .stdio import isolate_kernel_output


def _task_main(method, params, context, pipe):
    initialize_kernel_group()
    isolate_kernel_output()
    try:
        if method == "connection.test":
            from .database import test_connection
            result = test_connection(params)
        elif method in {"notifications.deliver_prepared", "notifications.test"}:
            from .notifications import deliver_prepared, dispatch
            result = deliver_prepared(params) if method == "notifications.deliver_prepared" else dispatch(method, params)
        else:
            from .language import dispatch
            result = dispatch(method, params, context)
        pipe.send({"result": result})
    except BaseException as exc:
        pipe.send({"error": {"code": "operation_failed", "message": f"{type(exc).__name__}: {exc}"}})
    finally:
        pipe.close()


class BackgroundJobs:
    """Persistent language threads; native DB test runs in a killable process."""

    def __init__(self, emit, *, completion_process=None):
        self.emit = emit
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="editor-service")
        self.delivery_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="notification-delivery")
        self.slots = threading.BoundedSemaphore(16)
        self.closed = threading.Event()
        from .editor_process import CompletionProcess
        use_process = getattr(sys, "frozen", False) if completion_process is None else completion_process
        self.completion_worker = CompletionProcess(self.closed) if use_process else None
        self.tests = set()
        self.lock = threading.Lock()
        self.latest = {}
        self.sequence = 0
        self.active_count = 0
        self.test_jobs = {}

    def submit(self, request_id, method, params, context):
        if not self.slots.acquire(blocking=False):
            raise ValueError("Too many editor requests; retry after the previous request finishes")
        key = None
        with self.lock:
            test_id = params.get("test_id") if method == "connection.test" else None
            if test_id in self.test_jobs:
                self.slots.release()
                raise ValueError("This connection test is already running")
            cancelled = threading.Event()
            if test_id:
                self.test_jobs[test_id] = {"cancelled": cancelled, "group": None}
            self.sequence += 1
            self.active_count += 1
            sequence = self.sequence
            if method in {"language.complete", "language.diagnostics", "parameters.scan"} and params.get("block_id"):
                key = (params.get("session_id"), params["block_id"], method)
                self.latest[key] = sequence
        executor = self.delivery_executor if method in {"notifications.deliver_prepared", "notifications.test"} else self.executor
        try:
            future = executor.submit(self._run, method, dict(params), context, key, sequence, cancelled)
        except BaseException:
            with self.lock:
                self.active_count -= 1
                if test_id:
                    self.test_jobs.pop(test_id, None)
            self.slots.release()
            raise
        def done(future):
            try:
                message = future.result()
            except BaseException as exc:
                message = {"error": {"code": "operation_failed", "message": f"{type(exc).__name__}: {exc}"}}
            finally:
                with self.lock:
                    self.active_count -= 1
                    if test_id:
                        self.test_jobs.pop(test_id, None)
                self.slots.release()
            if not self.closed.is_set():
                self.emit({"id": request_id, **message})
        future.add_done_callback(done)

    def cancel_test(self, test_id):
        with self.lock:
            state = self.test_jobs.get(test_id)
            if state is None:
                return {"test_id": test_id, "status": "already_finished"}
            state["cancelled"].set()
            if state["group"]:
                state["group"].close()
        return {"test_id": test_id, "status": "cancelling"}

    def _run(self, method, params, context, key, sequence, cancelled):
        if self.closed.is_set():
            raise RuntimeError("Runtime is closing")
        if cancelled.is_set():
            return {"error": {"code": "cancelled", "message": "Connection test cancelled"}}
        with self.lock:
            if key is not None and self.latest.get(key) != sequence:
                return {"result": {"items": [], "markers": [], "superseded": True}}
        if method not in {"connection.test", "notifications.deliver_prepared", "notifications.test"}:
            if method == "language.complete" and params.get("language") == "python" and self.completion_worker is not None:
                def superseded():
                    with self.lock:
                        return key is not None and self.latest.get(key) != sequence
                return self.completion_worker.request(params, context, superseded=superseded)
            if method.startswith("diagnostics."):
                from .diagnostics import dispatch
                return {"result": dispatch(method, params)}
            if method.startswith("notifications."):
                from .notifications import dispatch
                return {"result": dispatch(method, params)}
            if method.startswith("snapshot."):
                from .variable_snapshot import dispatch
                return {"result": dispatch(method, params)}
            from .language import dispatch
            return {"result": dispatch(method, params, context)}
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_task_main, args=(method, params, {}, sender), name="datapyn-background-operation")
        group = None
        try:
            process.start()
            sender.close()
            group = own_process_group(process.pid)
        except BaseException:
            sender.close()
            receiver.close()
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=1)
                if not process.is_alive():
                    process.close()
            raise
        with self.lock:
            self.tests.add(group)
            state = self.test_jobs.get(params.get("test_id")) if method == "connection.test" else None
            if state is not None:
                state["group"] = group
        try:
            deadline = time.monotonic() + 45
            while not self.closed.is_set() and not cancelled.is_set() and time.monotonic() < deadline:
                if receiver.poll(0.05):
                    try:
                        return receiver.recv()
                    except EOFError:
                        if cancelled.is_set():
                            return {"error": {"code": "cancelled", "message": "Connection test cancelled"}}
                        raise
                if not process.is_alive():
                    raise ConnectionError("Background operation worker exited unexpectedly")
            if cancelled.is_set():
                return {"error": {"code": "cancelled", "message": "Connection test cancelled"}}
            raise TimeoutError("Background operation exceeded 45 seconds")
        finally:
            if method == "notifications.deliver_prepared":
                (params.get("_secrets") or {}).clear()
                params.pop("_secrets", None)
            with self.lock:
                self.tests.discard(group)
            group.close()
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            if not process.is_alive():
                process.close()
            receiver.close()

    def close(self):
        self.closed.set()
        if self.completion_worker is not None:
            self.completion_worker.close()
        with self.lock:
            for group in list(self.tests):
                group.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.delivery_executor.shutdown(wait=False, cancel_futures=True)
