"""Background completion worker for Monaco editor (SQL + Python)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)

CompletionTuple = Tuple[str, str, str]


def _format_sql_completions(raw: List[Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for comp in raw or []:
        name = comp[0] if len(comp) > 0 else ""
        category = comp[1] if len(comp) > 1 else "text"
        detail = comp[2] if len(comp) > 2 else ""

        kind = "text"
        if category == "keyword":
            kind = "keyword"
        elif category in {"function", "routine"}:
            kind = "function"
        elif category == "table":
            kind = "class"
        elif category == "column":
            kind = "field"
        elif category == "variable":
            kind = "variable"
        elif category == "database":
            kind = "module"

        items.append({
            "label": name,
            "kind": kind,
            "insertText": name,
            "detail": detail,
            "category": category,
        })
    return items


def _format_sql_context_completions(raw: List[Any], prefix: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for comp in raw or []:
        name = comp[0] if len(comp) > 0 else ""
        category = comp[1] if len(comp) > 1 else "column"
        detail = comp[2] if len(comp) > 2 else ""
        items.append({
            "label": name,
            "kind": "field" if category != "variable" else "variable",
            "insertText": name,
            "detail": detail,
            "category": category,
            "table": prefix,
        })
    return items


_JEDI_TO_MONACO_KIND = {
    "function": "function",
    "method": "method",
    "class": "class",
    "module": "module",
    "instance": "variable",
    "param": "variable",
    "property": "property",
    "statement": "keyword",
    "keyword": "keyword",
}


def _format_python_completions(raw: List[CompletionTuple]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for comp in raw or []:
        name = comp[0] if len(comp) > 0 else ""
        jedi_kind = (comp[1] if len(comp) > 1 else "text") or "text"
        kind = _JEDI_TO_MONACO_KIND.get(jedi_kind, jedi_kind if jedi_kind in _JEDI_TO_MONACO_KIND.values() else "text")
        detail = comp[2] if len(comp) > 2 else ""
        items.append({
            "label": name,
            "kind": kind,
            "insertText": name,
            "detail": detail,
            "category": "python",
        })
    return items


class _CompletionWorker(QThread):
    """Runs a single completion job off the UI thread."""

    result_ready = pyqtSignal(int, str, list)

    def __init__(
        self,
        request_id: int,
        kind: str,
        *,
        schema: Dict[str, Any],
        namespace: Dict[str, Any],
        global_imports: str,
        full_text: str = "",
        prefix: str = "",
        line: int = 1,
        column: int = 1,
        parent=None,
    ):
        super().__init__(parent)
        self.request_id = request_id
        self.kind = kind
        self.schema = schema
        self.namespace = namespace
        self.global_imports = global_imports
        self.full_text = full_text
        self.prefix = prefix
        self.line = line
        self.column = column

    def run(self):
        try:
            if self.kind == "sql":
                from src.services.sql_autocomplete_service import SqlAutoCompleteService

                service = SqlAutoCompleteService()
                service.set_schema(self.schema)
                raw = service.get_completions(self.full_text, self.line - 1, self.column - 1)
                payload = _format_sql_completions(raw)
            elif self.kind == "sql_context":
                from src.services.sql_autocomplete_service import SqlAutoCompleteService

                service = SqlAutoCompleteService()
                service.set_schema(self.schema)
                raw = service.get_completions(self.full_text, self.line - 1, self.column - 1)
                payload = _format_sql_context_completions(raw, self.prefix)
            elif self.kind == "python":
                from src.services.jedi_completer import JediCompleter

                completer = JediCompleter()
                completer.set_namespace(self.namespace)
                code = self.full_text
                adjusted_line = self.line
                if self.global_imports:
                    code = self.global_imports + "\n" + code
                    adjusted_line = self.line + self.global_imports.count("\n") + 1
                raw = completer.complete_sync(code, adjusted_line, self.column, self.namespace)
                payload = _format_python_completions(raw)
            else:
                payload = []
        except Exception as exc:
            logger.debug("Completion worker error (%s): %s", self.kind, exc)
            payload = []

        if self.isInterruptionRequested():
            return
        self.result_ready.emit(self.request_id, self.kind, payload)


class MonacoCompletionService(QObject):
    """Cancelable async completion orchestrator for MonacoEditor."""

    sql_completions_ready = pyqtSignal(int, list)
    sql_context_completions_ready = pyqtSignal(int, list)
    python_completions_ready = pyqtSignal(int, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._schema: Dict[str, Any] = {}
        self._namespace: Dict[str, Any] = {}
        self._global_imports = ""
        self._worker: Optional[_CompletionWorker] = None

    def set_sql_schema(self, schema: Dict[str, Any]) -> None:
        self._schema = schema or {}

    def set_python_context(self, namespace: Dict[str, Any], global_imports: str = "") -> None:
        self._namespace = namespace or {}
        self._global_imports = global_imports or ""

    def cancel(self) -> None:
        self._stop_worker()

    def request_sql_completions(self, request_id: int, full_text: str, line: int, column: int) -> None:
        self._start_worker(
            request_id,
            "sql",
            full_text=full_text,
            line=line,
            column=column,
        )

    def request_sql_context(self, request_id: int, full_text: str, prefix: str, line: int, column: int) -> None:
        self._start_worker(
            request_id,
            "sql_context",
            full_text=full_text,
            prefix=prefix,
            line=line,
            column=column,
        )

    def request_python_completions(self, request_id: int, full_text: str, line: int, column: int) -> None:
        self._start_worker(
            request_id,
            "python",
            full_text=full_text,
            line=line,
            column=column,
        )

    def _start_worker(self, request_id: int, kind: str, **kwargs) -> None:
        self._stop_worker()
        worker = _CompletionWorker(
            request_id,
            kind,
            schema=self._schema,
            namespace=self._namespace,
            global_imports=self._global_imports,
            parent=self,
            **kwargs,
        )
        worker.result_ready.connect(self._on_worker_result)
        worker.finished.connect(lambda: self._finalize_worker(worker))
        self._worker = worker
        worker.start()

    def _on_worker_result(self, request_id: int, kind: str, payload: list) -> None:
        if kind == "sql":
            self.sql_completions_ready.emit(request_id, payload)
        elif kind == "sql_context":
            self.sql_context_completions_ready.emit(request_id, payload)
        elif kind == "python":
            self.python_completions_ready.emit(request_id, payload)

    def _finalize_worker(self, worker: _CompletionWorker) -> None:
        if self._worker is worker:
            self._worker = None
        worker.deleteLater()

    def _stop_worker(self) -> None:
        worker = self._worker
        if worker is None:
            return
        self._worker = None
        try:
            worker.result_ready.disconnect(self._on_worker_result)
        except (TypeError, RuntimeError):
            pass
        if worker.isRunning():
            worker.requestInterruption()
            return
        worker.deleteLater()
