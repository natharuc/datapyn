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


class _JediThread(QThread):
    """Thread subclass that runs jedi completions."""

    results_ready = pyqtSignal(list)

    def __init__(self, source: str, line: int, column: int, parent=None):
        super().__init__(parent)
        self.source = source
        self.line = line
        self.column = column

    def run(self):
        """Execute jedi completion."""
        if not HAS_JEDI:
            self.results_ready.emit([])
            return

        try:
            script = jedi.Script(self.source)
            completions = script.complete(self.line, self.column)

            results = []
            seen = set()
            for c in completions[:150]:
                name = c.name
                if name.startswith("__") and name.endswith("__"):
                    continue
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

            self.results_ready.emit(results)

        except Exception as e:
            logger.debug(f"Jedi completion error: {e}")
            self.results_ready.emit([])


class JediCompleter(QObject):
    """
    Manages jedi-based autocompletion.

    Usage:
        completer = JediCompleter(parent)
        completer.completions_ready.connect(on_completions)
        completer.request_completions(source, line, col)
    """

    completions_ready = pyqtSignal(list)  # List of (name, type, description)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None

    def is_available(self) -> bool:
        """Check if jedi is installed."""
        return HAS_JEDI

    def request_completions(self, source: str, line: int, column: int, namespace: dict = None):
        """Request completions asynchronously."""
        if not HAS_JEDI:
            return

        self._cleanup()

        # QThread subclass with self as parent - Qt handles lifecycle
        self._thread = _JediThread(source, line, column, parent=self)
        self._thread.results_ready.connect(self._on_finished)
        self._thread.finished.connect(self._on_thread_done)
        self._thread.start()

    def _on_finished(self, results: list):
        """Forward results."""
        self.completions_ready.emit(results)

    def _on_thread_done(self):
        """Clean up after thread finishes naturally."""
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    def _cleanup(self):
        """Cancel any running completion request."""
        thread = self._thread
        if thread is not None:
            self._thread = None
            try:
                thread.finished.disconnect(self._on_thread_done)
            except (TypeError, RuntimeError):
                pass
            if thread.isRunning():
                thread.quit()
                if not thread.wait(500):
                    thread.terminate()
                    thread.wait(500)
            thread.deleteLater()

    def shutdown(self):
        """Explicit shutdown - call before destroying parent widget."""
        self._cleanup()
