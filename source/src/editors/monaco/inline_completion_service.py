"""
Inline (ghost-text) completion for Monaco editors — Pynia ACP.

Debounced, single-flight, cancellable. Asks the tab's ACP agent on a
dedicated completion session (never the chat session). Failures are silent.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, QTimer

from src.services.ai_autocomplete_circuit_breaker import get_ai_autocomplete_circuit_breaker
from src.services.pynia.settings import get_pynia_settings
from src.utils.qt_threading import detach_qthread

logger = logging.getLogger(__name__)

_DEBOUNCE_MS = 400
_WATCHDOG_MS = 4000
_MIN_PREFIX = 3


class _AcpCompletionWorker(QObject):
    """Runs one ACP inline completion off the UI thread."""

    inline_complete = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._host = None
        self._tab_id = ""
        self._prefix = ""
        self._suffix = ""
        self._language = "python"
        self._database_context = ""
        self._python_namespace: Dict[str, str] = {}
        self._cancelled = False

    def set_request(self, host, tab_id: str, req: dict, database_context: str, python_namespace: dict) -> None:
        self._host = host
        self._tab_id = tab_id or ""
        self._prefix = req.get("prefix") or ""
        self._suffix = req.get("suffix") or ""
        self._language = req.get("language") or "python"
        self._database_context = database_context or ""
        self._python_namespace = dict(python_namespace or {})
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        try:
            if self._cancelled or self._host is None:
                self.inline_complete.emit("")
                return
            from src.services.pynia.completion import build_inline_context, build_inline_prompt

            context = build_inline_context(
                self._language,
                database_context=self._database_context,
                python_namespace=self._python_namespace,
            )
            body = build_inline_prompt(
                language=self._language,
                prefix=self._prefix,
                suffix=self._suffix,
                context=context,
            )
            if self._cancelled:
                self.inline_complete.emit("")
                return
            text = self._host.complete_inline(self._tab_id, body, timeout=3.5)
            if self._cancelled:
                self.inline_complete.emit("")
                return
            self.inline_complete.emit(text or "")
        except Exception as exc:
            logger.debug("[Autocomplete] ACP completion failed: %s", exc)
            try:
                self.error.emit(str(exc))
            except RuntimeError:
                pass
            try:
                self.inline_complete.emit("")
            except RuntimeError:
                pass
        finally:
            try:
                self.finished.emit()
            except RuntimeError:
                pass


class InlineCompletionService(QObject):
    """Debounced, single-flight inline completion via the Pynia ACP host."""

    completion_ready = pyqtSignal(str)
    log_message = pyqtSignal(str, str)
    lsp_download_needed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._language = "python"
        self._database_context = ""
        self._python_namespace: Dict[str, str] = {}
        self._python_namespace_objects: Dict[str, Any] = {}
        self._blocks_code_context = ""
        self._lsp_preamble = ""
        self._lsp_line_offset = 0

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._fire)

        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.setInterval(_WATCHDOG_MS)
        self._watchdog.timeout.connect(self._on_watchdog)

        self._pending: Optional[dict] = None
        self._active_req: Optional[dict] = None
        self._busy = False
        self._active_id = 0
        self._req_id = 0
        self._last_key = ""
        self._circuit_open_logged = False

        self._thread: Optional[QThread] = None
        self._worker: Optional[QObject] = None
        self._orphaned_threads: list[tuple[QObject, QThread]] = []

        self._pynia_client = None
        self._tab_id = ""
        self._document_uri = ""
        self._document_version = 0

    def _log(self, message: str, level: str = "info", *, panel: bool = True) -> None:
        logger.log(
            {"error": logging.ERROR, "warning": logging.WARNING, "debug": logging.DEBUG}.get(
                level, logging.INFO
            ),
            "[Autocomplete] %s",
            message,
        )
        if panel:
            self.log_message.emit(f"[Autocomplete] {message}", level)

    def set_database_context(self, context: str) -> None:
        self._database_context = context or ""

    def set_python_namespace(self, namespace: Dict[str, Any]) -> None:
        raw = namespace or {}
        self._python_namespace_objects = dict(raw)
        self._python_namespace = self._namespace_type_map(raw)

    @staticmethod
    def _namespace_type_map(namespace: Dict) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for key, value in namespace.items():
            if not key or str(key).startswith("_"):
                continue
            if isinstance(value, str):
                out[str(key)] = value
            else:
                try:
                    out[str(key)] = type(value).__name__
                except Exception:
                    out[str(key)] = "object"
        return out

    def set_blocks_code_context(self, code_context: str) -> None:
        self._blocks_code_context = code_context or ""

    def set_lsp_preamble(self, preamble: str, line_offset: int) -> None:
        self._lsp_preamble = preamble or ""
        self._lsp_line_offset = max(0, int(line_offset))

    def set_document_info(self, uri: str, language: str) -> None:
        self._document_uri = uri or ""
        self._language = language or "python"
        self._document_version = 1

    def open_document(self, uri: str, language: str, text: str, version: int = 1) -> None:
        self._document_uri = uri or self._document_uri
        self._language = language or self._language
        self._document_version = version

    def notify_document_changed(self, text: str, *args, **kwargs) -> None:
        self._document_version += 1

    def close_document(self, *args, **kwargs) -> None:
        return

    def set_pynia_client(self, client=None) -> None:
        self._pynia_client = client

    def set_tab_id(self, tab_id: str) -> None:
        self._tab_id = tab_id or ""

    def set_copilot_client(self, client=None) -> None:
        self.set_pynia_client(client)

    def set_lsp_client(self, client=None) -> None:
        """Kept as a no-op for leftover editor wiring."""
        return

    @property
    def has_lsp(self) -> bool:
        return False

    @property
    def has_pynia(self) -> bool:
        if not get_pynia_settings().autocomplete_enabled:
            return False
        return self._pynia_client is not None and hasattr(self._pynia_client, "complete_inline")

    def invalidate_provider_cache(self) -> None:
        return

    def request_completion(self, prefix: str, suffix: str, language: str, line: int, column: int) -> None:
        if not self._should_request(prefix):
            self.completion_ready.emit("")
            return
        key = f"{line}:{column}:{len(prefix)}:{prefix[-40:]}"
        if key == self._last_key and (self._busy or self._debounce.isActive()):
            return
        self._last_key = key
        self._req_id += 1
        self._pending = {
            "id": self._req_id, "prefix": prefix, "suffix": suffix,
            "language": language or self._language, "line": line, "column": column,
        }
        self._debounce.start()

    def force_completion(self, prefix: str, suffix: str, language: str, line: int, column: int) -> None:
        self._req_id += 1
        self._pending = {
            "id": self._req_id, "prefix": prefix, "suffix": suffix,
            "language": language or self._language, "line": line, "column": column,
            "force": True,
        }
        self._busy = False
        self._debounce.stop()
        self._fire()

    def cancel_request(self) -> None:
        self._debounce.stop()
        self._pending = None
        self._req_id += 1
        self._active_req = None
        self._active_id = 0
        if self._worker is not None:
            try:
                self._worker.cancel()
            except Exception:
                pass
        self._release()

    def cancel(self) -> None:
        self.cancel_request()
        self._orphan_worker()
        try:
            self.close_document()
        except Exception:
            pass

    def _should_request(self, prefix: str) -> bool:
        lines = prefix.split("\n")
        last = lines[-1] if lines else prefix
        stripped = last.rstrip()
        if stripped.endswith((".", "(", "[")):
            return True
        if len(stripped) < _MIN_PREFIX:
            return False
        if stripped == "":
            return any(line.strip() for line in lines[:-1])
        return True

    def _ai_circuit_allows(self) -> bool:
        breaker = get_ai_autocomplete_circuit_breaker()
        if breaker.allows_requests():
            self._circuit_open_logged = False
            return True
        if not self._circuit_open_logged:
            self._circuit_open_logged = True
            self._log(
                "AI inline completion paused after repeated failures. "
                "Restart the app or reconfigure Pynia in Settings to retry.",
                "info",
            )
        return False

    @pyqtSlot()
    def _fire(self) -> None:
        try:
            if not self._pending:
                return
            if self._busy:
                return
            if not self._ai_circuit_allows():
                self._active_req = None
                try:
                    self.completion_ready.emit("")
                except RuntimeError:
                    pass
                return

            req = self._pending
            self._pending = None
            self._active_req = dict(req)

            if not get_pynia_settings().autocomplete_enabled:
                self.completion_ready.emit("")
                return
            host = self._pynia_client
            if host is None or not hasattr(host, "complete_inline"):
                self.completion_ready.emit("")
                return

            self._busy = True
            self._active_id = req["id"]
            self._watchdog.start()
            self._start_worker(host, req)
        except Exception as exc:
            logger.warning("[Autocomplete] _fire failed (ignored): %s", exc)
            self._release()
            try:
                self.completion_ready.emit("")
            except RuntimeError:
                pass

    def _start_worker(self, host, req: dict) -> None:
        try:
            self._orphan_worker()
            worker = _AcpCompletionWorker()
            worker.set_request(
                host,
                self._tab_id,
                req,
                self._database_context,
                self._python_namespace,
            )
            thread = QThread(self)
            thread.setObjectName("PyniaAcpInlineCompletion")
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.inline_complete.connect(
                lambda text, w=worker: self._on_worker_complete(w, text)
            )
            worker.error.connect(
                lambda msg, w=worker: self._on_worker_error(w, msg)
            )
            worker.finished.connect(thread.quit)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            self._worker = worker
            self._thread = thread
            thread.start()
        except Exception as exc:
            logger.warning("[Autocomplete] worker start failed: %s", exc)
            self._release()
            self.completion_ready.emit("")

    def _orphan_worker(self) -> None:
        worker, thread = self._worker, self._thread
        self._worker = None
        self._thread = None
        if worker is None and thread is None:
            return
        try:
            if worker is not None:
                worker.setParent(None)
            if thread is not None:
                thread.setParent(None)
        except RuntimeError:
            pass
        if thread is not None:
            self._orphaned_threads.append((worker, thread))
            thread.finished.connect(
                lambda t=thread, w=worker: self._drop_orphaned(t, w)
            )
        detach_qthread(thread, worker)

    def _drop_orphaned(self, thread: QThread, worker: QObject) -> None:
        try:
            self._orphaned_threads = [
                pair for pair in self._orphaned_threads if pair[1] is not thread
            ]
        except Exception:
            pass
        try:
            if worker is not None:
                worker.deleteLater()
        except RuntimeError:
            pass
        try:
            thread.deleteLater()
        except RuntimeError:
            pass

    def _context_for(self, language: str) -> str:
        from src.services.pynia.completion import build_inline_context

        return build_inline_context(
            language,
            database_context=self._database_context,
            python_namespace_objects=self._python_namespace_objects,
            python_namespace=self._python_namespace,
            blocks_code_context=self._blocks_code_context,
        )

    def _on_worker_complete(self, worker: QObject, text: str) -> None:
        if worker is not self._worker:
            return
        get_ai_autocomplete_circuit_breaker().record_success()
        self._deliver_completion(text)

    def _on_worker_error(self, worker: QObject, message: str) -> None:
        if worker is not self._worker:
            return
        if message:
            self._log(f"Completion failed: {message}", "debug", panel=False)
        get_ai_autocomplete_circuit_breaker().record_failure(message or "ACP inline completion failed")
        self._deliver_completion("")

    def _deliver_completion(self, text: str) -> None:
        try:
            req = self._active_req
            if req is None or req.get("id", 0) != self._active_id:
                return
            self._active_req = None
            self._release()
            cleaned = text or ""
            if cleaned and req:
                try:
                    from src.services.pynia.completion import clean_completion_text

                    cleaned = clean_completion_text(
                        cleaned,
                        req.get("prefix", "") or "",
                        req.get("suffix", "") or "",
                    )
                except Exception:
                    pass
            if cleaned:
                preview = cleaned[:60].replace("\n", " ")
                self._log(f"Completion: {preview}…", "debug", panel=False)
            self.completion_ready.emit(cleaned)
            self._maybe_serve_pending()
        except Exception as exc:
            logger.debug("[Autocomplete] deliver ignored: %s", exc)
            self._release()

    @pyqtSlot()
    def _on_watchdog(self) -> None:
        if not self._busy:
            return
        try:
            self._log("Watchdog: releasing slow inline completion", "debug", panel=False)
            self._active_req = None
            self._active_id = 0
            self._orphan_worker()
            self._release()
            self.completion_ready.emit("")
            self._maybe_serve_pending()
        except Exception as exc:
            logger.debug("[Autocomplete] watchdog ignored: %s", exc)
            self._release()

    def _release(self) -> None:
        self._busy = False
        self._watchdog.stop()

    def _maybe_serve_pending(self) -> None:
        if self._pending and not self._debounce.isActive():
            self._debounce.start()
