"""Persistent completion interpreter for frozen runtimes, with owned lifetime."""

from __future__ import annotations

import multiprocessing
import threading
import time

from .process_group import initialize_kernel_group, own_process_group
from .stdio import isolate_kernel_output


class _SupersededCompletion(Exception):
    pass


def _editor_main(connection):
    initialize_kernel_group()
    isolate_kernel_output()
    from .kernel import _watch_parent
    threading.Thread(target=_watch_parent, name="editor-parent-watch", daemon=True).start()
    try:
        from .language import initialize_completion_worker, dispatch
        from .desktop_services import enable_user_packages
        initialize_completion_worker()
        connection.send({"ready": True})
        while True:
            request = connection.recv()
            try:
                enable_user_packages()
                result = dispatch("language.complete", request["params"], request["context"])
                connection.send({"result": result})
            except Exception as exc:
                connection.send({"error": {"code": "operation_failed", "message": f"{type(exc).__name__}: {exc}"}})
    except EOFError:
        pass
    except Exception as exc:
        connection.send({"error": {"code": "editor_unavailable", "message": f"{type(exc).__name__}: {exc}"}})
    finally:
        connection.close()


class CompletionProcess:
    """One serial inference process, reused across all tab snapshots."""

    def __init__(self, closed):
        self.closed = closed
        self.lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.process = None
        self.connection = None
        self.group = None
        self.ready = False

    def _start(self):
        with self.state_lock:
            if self.closed.is_set():
                raise RuntimeError("Runtime is closing")
            if self.process is not None and self.process.is_alive():
                return self.process, self.connection
            self._stop()
            context = multiprocessing.get_context("spawn")
            connection, child = context.Pipe(duplex=True)
            process = context.Process(target=_editor_main, args=(child,), name="datapyn-python-completion")
            try:
                process.start()
                group = own_process_group(process.pid)
            except BaseException:
                connection.close()
                if process.pid is not None:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout=1)
                    if not process.is_alive():
                        process.close()
                raise
            finally:
                child.close()
            self.process, self.connection, self.group = process, connection, group
            return process, connection

    def request(self, params, context, *, timeout=12, superseded=None):
        with self.lock:
            if superseded is not None and superseded():
                return {"result": {"items": [], "superseded": True}}
            process, connection = self._start()
            try:
                deadline = time.monotonic() + timeout
                if not self.ready:
                    initialized = self._receive(process, connection, deadline, superseded)
                    if not initialized.get("ready"):
                        self._stop()
                        return initialized
                    self.ready = True
                # Readiness is confirmed before sending a potentially large
                # document, so a stuck initializer cannot block a pipe write.
                connection.send({"params": params, "context": context})
                return self._receive(process, connection, deadline, superseded)
            except _SupersededCompletion:
                self._stop()
                return {"result": {"items": [], "superseded": True}}
            except BaseException:
                self._stop()
                raise

    def warmup(self, timeout=12):
        with self.lock:
            process, connection = self._start()
            if self.ready:
                return
            try:
                initialized = self._receive(process, connection, time.monotonic() + timeout)
                if not initialized.get("ready"):
                    self._stop()
                    raise RuntimeError("Python completion initializer is unavailable")
                self.ready = True
            except BaseException:
                self._stop()
                raise

    def _receive(self, process, connection, deadline, superseded=None):
        while not self.closed.is_set() and time.monotonic() < deadline:
            if superseded is not None and superseded():
                raise _SupersededCompletion()
            if connection.poll(min(0.05, max(0, deadline - time.monotonic()))):
                return connection.recv()
            if not process.is_alive():
                raise ConnectionError("Python completion worker exited unexpectedly")
        if self.closed.is_set():
            raise RuntimeError("Runtime is closing")
        raise TimeoutError("Python completion exceeded its 12-second limit")

    def _stop(self):
        with self.state_lock:
            process, connection, group = self.process, self.connection, self.group
            self.process = self.connection = self.group = None
            self.ready = False
            if group is not None:
                group.close()
            if process is not None:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
                if not process.is_alive():
                    process.close()
            if connection is not None:
                connection.close()

    def reset(self):
        with self.lock:
            self._stop()

    def close(self):
        self._stop()
