"""
Jedi-based Python autocompletion service.

Uses jedi library to provide intelligent completions based on:
- Installed modules and their classes/methods/attributes
- Current code context (imports, variables, etc.)
- Python namespace from previous executions
"""

import logging
from typing import List, Tuple

from PyQt6.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)

try:
    import jedi
    HAS_JEDI = True
except ImportError:
    HAS_JEDI = False
    logger.warning("jedi not installed - intelligent Python autocomplete disabled")


class JediCompletionWorker(QObject):
    """Worker that runs jedi completions in a background thread."""

    finished = pyqtSignal(list)  # List of (name, type, description)

    def __init__(self, source: str, line: int, column: int, namespace: dict = None):
        super().__init__()
        self.source = source
        self.line = line
        self.column = column
        self.namespace = namespace or {}

    def run(self):
        """Execute jedi completion."""
        if not HAS_JEDI:
            self.finished.emit([])
            return

        try:
            # Create jedi script
            script = jedi.Script(self.source)
            completions = script.complete(self.line, self.column)

            results = []
            seen = set()
            for c in completions[:150]:  # Limit to 150 for performance
                name = c.name
                if name.startswith("__") and name.endswith("__"):
                    continue  # Skip dunder methods
                if name in seen:
                    continue
                seen.add(name)

                comp_type = c.type or ""
                description = ""
                try:
                    sigs = c.get_signatures()
                    if sigs:
                        description = str(sigs[0])
                except Exception:
                    pass

                results.append((name, comp_type, description))

            self.finished.emit(results)

        except Exception as e:
            logger.debug(f"Jedi completion error: {e}")
            self.finished.emit([])


class JediCompleter(QObject):
    """
    Manages jedi-based autocompletion.

    Usage:
        completer = JediCompleter()
        completer.completions_ready.connect(on_completions)
        completer.request_completions(source, line, col, namespace)
    """

    completions_ready = pyqtSignal(list)  # List of (name, type, description)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None

    def is_available(self) -> bool:
        """Check if jedi is installed."""
        return HAS_JEDI

    def request_completions(self, source: str, line: int, column: int, namespace: dict = None):
        """Request completions asynchronously.

        Args:
            source: Full source code of the editor
            line: 1-based line number
            column: 0-based column offset
            namespace: Optional dict of runtime variables
        """
        if not HAS_JEDI:
            return

        # Cancel previous request
        self._cleanup()

        self._thread = QThread()
        self._worker = JediCompletionWorker(source, line, column, namespace)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _on_finished(self, results: list):
        """Forward results."""
        self.completions_ready.emit(results)
        self._thread = None
        self._worker = None

    def _cleanup(self):
        """Cancel any running completion request."""
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(500)
        self._thread = None
        self._worker = None
