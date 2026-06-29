"""
Inline (ghost-text) completion for Monaco editors — Pynia.

ONE clean path: take the focused block's prefix/suffix (the code the user is
editing) plus the context Monaco already has (SQL schema / Python namespace),
and ask the configured Pynia API connector (OpenAI / OpenRouter / Claude) for a
multiline completion over HTTP.

Deliberately removed: the GitHub Copilot LSP path, the chat-session detour, and
the local keyword heuristics — all proved unreliable and produced nothing. The
HTTP connector path is simple, fast, and debuggable.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, QTimer

from src.services.ai_autocomplete_circuit_breaker import get_ai_autocomplete_circuit_breaker
from src.services.pynia.settings import get_pynia_settings, get_provider_secret
from src.utils.qt_threading import detach_qthread

logger = logging.getLogger(__name__)

# API connectors that can serve autocomplete over HTTP. Copilot is intentionally
# excluded — its completion endpoint never worked reliably in this integration.
COMPLETION_PROVIDERS = ("openai", "openrouter", "anthropic")

_DEBOUNCE_MS = 400
_WATCHDOG_MS = 4500
_MIN_PREFIX = 3


class InlineCompletionService(QObject):
    """Debounced, single-flight inline completion via a Pynia API connector."""

    completion_ready = pyqtSignal(str)        # ghost-text to insert
    log_message = pyqtSignal(str, str)        # (message, level) -> output panel
    lsp_download_needed = pyqtSignal()        # kept for signal compatibility

    def __init__(self, parent=None):
        super().__init__(parent)

        # Context Monaco already has (focused block only, by design).
        self._language = "python"
        self._database_context = ""               # SQL schema text
        self._python_namespace: Dict[str, str] = {}  # var -> type (prompt summary)
        self._python_namespace_objects: Dict[str, Any] = {}  # live session objects
        self._blocks_code_context = ""            # other blocks / SQL outputs
        self._lsp_preamble = ""                   # session context sent to Copilot LSP
        self._lsp_line_offset = 0                 # 0-based line of block body in LSP doc

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._fire)

        # Never let one slow/hung request wedge the pipeline.
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
        self._no_provider_logged = False
        self._circuit_open_logged = False
        self._provider_cache: Optional[Tuple[Optional[str], Optional[str]]] = None

        self._thread: Optional[QThread] = None
        self._worker: Optional[QObject] = None
        self._orphaned_threads: list[tuple[QObject, QThread]] = []

        # Native Copilot LSP (preferred when authenticated). The Pynia API
        # connector is the fallback when no Copilot LSP is available.
        self._lsp_client = None
        self._pynia_client = None  # stored for compat; not used for completion
        self._document_uri = ""
        self._document_version = 0

    # ------------------------------------------------------------------ logging
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

    # -------------------------------------------------------------- context API
    def set_database_context(self, context: str) -> None:
        """SQL schema text (tables/columns) for the focused block's connection."""
        self._database_context = context or ""

    def set_python_namespace(self, namespace: Dict[str, Any]) -> None:
        """Python variables in scope (live DataFrames + other objects)."""
        raw = namespace or {}
        self._python_namespace_objects = dict(raw)
        self._python_namespace = self._namespace_type_map(raw)

    @staticmethod
    def _namespace_type_map(namespace: Dict) -> Dict[str, str]:
        """Build name -> type label for the AI prompt."""
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
        """Other blocks in the tab (SQL DataFrames, Python sources)."""
        self._blocks_code_context = code_context or ""

    def set_lsp_preamble(self, preamble: str, line_offset: int) -> None:
        """Session preamble prepended for Copilot LSP (Monaco still edits block only)."""
        self._lsp_preamble = preamble or ""
        self._lsp_line_offset = max(0, int(line_offset))

    def _lsp_document_text(self, block_text: str) -> str:
        if not self._lsp_preamble:
            return block_text
        return self._lsp_preamble + block_text

    def _lsp_line_index(self, monaco_line_1based: int) -> int:
        return max(0, monaco_line_1based - 1) + self._lsp_line_offset

    def set_document_info(self, uri: str, language: str) -> None:
        self._document_uri = uri or ""
        self._language = language or "python"
        self._document_version = 1

    def open_document(self, uri: str, language: str, text: str, version: int = 1) -> None:
        self._document_uri = uri or self._document_uri
        self._language = language or self._language
        self._document_version = version
        if self._lsp_client is not None:
            self._lsp_client.open_document(
                uri, language, self._lsp_document_text(text), version
            )

    def notify_document_changed(self, text: str, *args, **kwargs) -> None:
        if self._lsp_client is not None and self._document_uri:
            self._document_version += 1
            self._lsp_client.change_document(
                self._document_uri,
                self._document_version,
                self._lsp_document_text(text),
            )

    def close_document(self, *args, **kwargs) -> None:
        if self._lsp_client is not None and self._document_uri:
            self._lsp_client.close_document(self._document_uri)

    def set_pynia_client(self, client=None) -> None:
        self._pynia_client = client  # stored for compat; not used for completion

    def set_copilot_client(self, client=None) -> None:
        self.set_pynia_client(client)

    def set_lsp_client(self, client=None) -> None:
        """Wire the native Copilot LSP client (preferred completion source)."""
        if self._lsp_client is not None:
            try:
                self._lsp_client.completion_ready.disconnect(self._on_lsp_result)
            except (TypeError, RuntimeError):
                pass
        self._lsp_client = client
        if client is not None and hasattr(client, "completion_ready"):
            client.completion_ready.connect(self._on_lsp_result)

    @property
    def has_lsp(self) -> bool:
        client = self._lsp_client
        if client is None:
            return False
        if hasattr(client, "completions_enabled"):
            return bool(client.completions_enabled)
        return bool(getattr(client, "is_authenticated", False))

    @property
    def has_pynia(self) -> bool:
        provider, _ = self._resolve_provider()
        return provider is not None

    def invalidate_provider_cache(self) -> None:
        """Clear cached provider resolution (e.g. after settings change)."""
        self._provider_cache = None

    # ----------------------------------------------------------- provider pick
    def _resolve_provider(self):
        """Return (provider_id, model) for an API connector that has a token.

        Prefers the active connector when it's an API provider; otherwise the
        first configured one. Returns (None, None) when autocomplete is off or
        no API token is set.
        """
        if self._provider_cache is not None:
            return self._provider_cache
        settings = get_pynia_settings()
        if not settings.autocomplete_enabled:
            self._provider_cache = (None, None)
            return self._provider_cache
        order = []
        active = settings.active_provider
        if active in COMPLETION_PROVIDERS:
            order.append(active)
        order += [p for p in COMPLETION_PROVIDERS if p not in order]
        for pid in order:
            if get_provider_secret(pid):
                self._provider_cache = (pid, settings.completion_model(pid))
                return self._provider_cache
        self._provider_cache = (None, None)
        return self._provider_cache

    # ---------------------------------------------------------------- requests
    def request_completion(self, prefix: str, suffix: str, language: str, line: int, column: int) -> None:
        """Debounced completion request from the editor (auto-trigger)."""
        if not self._should_request(prefix):
            self.completion_ready.emit("")
            return
        # Only skip exact duplicate while a request is already queued (same cursor).
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
        """Manual trigger (Ctrl+.): bypass debounce and the min-length check."""
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
        """Stop debounced and in-flight work (tab/editor teardown)."""
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
        # Member / call context: complete after `.` `(` `[`
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

    # ------------------------------------------------------------------- engine
    @pyqtSlot()
    def _fire(self) -> None:
        try:
            if not self._pending:
                return
            if self._busy:
                return  # a request is in flight; _maybe_serve_pending re-arms us
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

            lsp_present = self._lsp_client is not None
            lsp_auth = lsp_present and bool(getattr(self._lsp_client, "is_authenticated", False))
            provider_id, model = self._resolve_provider()
            self._log(
                f"state: lsp_client={lsp_present}, lsp_auth={lsp_auth}, "
                f"doc={'yes' if self._document_uri else 'NO'}, pynia={provider_id is not None}",
                "debug",
                panel=False,
            )

            if self.has_lsp and self._document_uri:
                self._busy = True
                self._active_id = req["id"]
                self._watchdog.start()
                self._log(
                    f"Requesting Copilot completion (L{req['line']}:C{req['column']})",
                    "debug",
                    panel=False,
                )
                self._lsp_client.request_completion(
                    self._document_uri,
                    self._document_version,
                    self._lsp_line_index(req["line"]),
                    max(0, req["column"] - 1),
                )
                return

            # LSP exists but paused (network/auth) — don't hammer HTTP on every keystroke.
            if self._lsp_client is not None and not self.has_lsp and not req.get("force"):
                self._log("Copilot paused; skipping auto HTTP inline (use Ctrl+.)", "debug", panel=False)
                try:
                    self.completion_ready.emit("")
                except RuntimeError:
                    pass
                return

            if not provider_id:
                if not self._no_provider_logged:
                    self._log(
                        "Autocomplete needs GitHub Copilot signed in, or an API token "
                        "in Settings → Pynia (OpenAI / OpenRouter / Claude).",
                        "info",
                    )
                    self._no_provider_logged = True
                self.completion_ready.emit("")
                return
            self._no_provider_logged = False

            self._busy = True
            self._active_id = req["id"]
            self._watchdog.start()
            self._log(
                f"Requesting completion ({req['language']}, {provider_id}/{model})",
                "debug",
                panel=False,
            )
            self._start_worker(provider_id, model, req)
        except Exception as exc:
            logger.warning("[Autocomplete] _fire failed (ignored): %s", exc)
            self._release()
            try:
                self.completion_ready.emit("")
            except RuntimeError:
                pass

    def _start_worker(self, provider_id: str, model: str, req: dict) -> None:
        try:
            from src.services.pynia.completion import PyniaInlineCompletionWorker

            self._orphan_worker()

            worker = PyniaInlineCompletionWorker()
            worker.set_request(
                provider_id,
                req["language"],
                req["prefix"],
                req["suffix"],
                model=model,
                database_context=self._database_context,
                python_namespace_objects=self._python_namespace_objects,
                python_namespace=self._python_namespace,
                blocks_code_context=self._blocks_code_context,
            )
            thread = QThread(self)
            thread.setObjectName("PyniaInlineCompletion")
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
            logger.warning("[Autocomplete] worker start failed (ignored): %s", exc)
            self._release()
            try:
                self.completion_ready.emit("")
            except RuntimeError:
                pass

    def _orphan_worker(self) -> None:
        """Detach in-flight HTTP worker without blocking the UI thread."""
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
        """Session context for tests and backward compatibility."""
        from src.services.pynia.completion import build_inline_context

        return build_inline_context(
            language,
            database_context=self._database_context,
            python_namespace_objects=self._python_namespace_objects,
            python_namespace=self._python_namespace,
            blocks_code_context=self._blocks_code_context,
        )

    @pyqtSlot(str, str)
    def _on_lsp_result(self, document_uri: str, text: str) -> None:
        """Copilot LSP completion — only for this block's document URI."""
        try:
            if document_uri and self._document_uri and document_uri != self._document_uri:
                return
            get_ai_autocomplete_circuit_breaker().record_success()
            self._deliver_completion(text)
        except Exception as exc:
            logger.debug("[Autocomplete] LSP result ignored: %s", exc)
            self._release()

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
        get_ai_autocomplete_circuit_breaker().record_failure(message or "HTTP inline completion failed")
        self._deliver_completion("")

    def _deliver_completion(self, text: str) -> None:
        """Forward ghost-text to Monaco; never raises."""
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
            client = self._lsp_client
            if client is not None and hasattr(client, "mark_degraded"):
                client.mark_degraded("inline completion watchdog")
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
