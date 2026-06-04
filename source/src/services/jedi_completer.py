"""
Jedi-based Python autocompletion service.

Uses jedi library to provide intelligent completions based on:
- Installed modules and their classes/methods/attributes
- Current code context (imports, variables, etc.)
- Python namespace from previous executions (variables, DataFrames, etc.)
"""

import logging
from typing import List, Tuple, Dict, Any, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)

try:
    import jedi
    HAS_JEDI = True
except ImportError:
    HAS_JEDI = False
    logger.warning("jedi not installed - intelligent Python autocomplete disabled")


def _build_namespace_header(namespace: Dict[str, Any]) -> str:
    """
    Build Python code that declares namespace variables with their types.
    This helps Jedi understand the types of variables from previous executions.
    """
    if not namespace:
        return ""

    lines = ["# Namespace variables from previous executions"]
    has_pandas = False
    has_numpy = False

    for name, value in namespace.items():
        # Skip private/dunder and non-identifier names
        if name.startswith("_") or not name.isidentifier():
            continue

        try:
            # Type-hint strings from session namespace metadata (no live object).
            if isinstance(value, str):
                type_name = value
                if type_name == "DataFrame":
                    has_pandas = True
                    lines.append(f"{name}: pd.DataFrame = pd.DataFrame()")
                elif type_name == "Series":
                    has_pandas = True
                    lines.append(f"{name}: pd.Series = pd.Series()")
                elif type_name == "ndarray":
                    has_numpy = True
                    lines.append(f"{name}: np.ndarray = np.array([])")
                elif type_name == "list":
                    lines.append(f"{name}: list = []")
                elif type_name == "dict":
                    lines.append(f"{name}: dict = {{}}")
                elif type_name == "str":
                    lines.append(f'{name}: str = ""')
                elif type_name in ("int", "float"):
                    lines.append(f"{name}: {type_name} = 0")
                elif type_name == "bool":
                    lines.append(f"{name}: bool = False")
                elif type_name in ("module", "function", "class"):
                    lines.append(f"# {name}: {type_name}")
                    lines.append(f"{name} = None")
                else:
                    lines.append(f"# {name}: {type_name}")
                    lines.append(f"{name} = None")
                continue

            type_name = type(value).__name__
            module = type(value).__module__

            # Handle pandas DataFrames specially
            if type_name == "DataFrame" and module == "pandas.core.frame":
                has_pandas = True
                # Get column info if available
                try:
                    cols = list(value.columns)[:20]  # Limit columns
                    cols_str = ", ".join(f'"{c}"' for c in cols)
                    lines.append(f"{name}: pd.DataFrame = pd.DataFrame(columns=[{cols_str}])")
                except Exception:
                    lines.append(f"{name}: pd.DataFrame = pd.DataFrame()")

            # Handle pandas Series
            elif type_name == "Series" and "pandas" in module:
                has_pandas = True
                lines.append(f"{name}: pd.Series = pd.Series()")

            # Handle numpy arrays
            elif type_name == "ndarray" and "numpy" in module:
                has_numpy = True
                lines.append(f"{name}: np.ndarray = np.array([])")

            # Handle lists
            elif type_name == "list":
                lines.append(f"{name}: list = []")

            # Handle dicts
            elif type_name == "dict":
                lines.append(f"{name}: dict = {{}}")

            # Handle strings
            elif type_name == "str":
                lines.append(f'{name}: str = ""')

            # Handle ints/floats
            elif type_name in ("int", "float"):
                lines.append(f"{name}: {type_name} = 0")

            # Handle other types - just declare as Any
            else:
                full_type = f"{module}.{type_name}" if module != "builtins" else type_name
                lines.append(f"# {name}: {full_type}")
                lines.append(f"{name} = None")

        except Exception as e:
            logger.debug(f"Error processing namespace variable {name}: {e}")
            continue

    # Build imports at the top
    imports = []
    if has_pandas:
        imports.append("import pandas as pd")
    if has_numpy:
        imports.append("import numpy as np")

    result_lines = imports + lines + [""]  # Empty line separator
    return "\n".join(result_lines) + "\n"


class _JediThread(QThread):
    """Thread subclass that runs jedi completions."""

    results_ready = pyqtSignal(list)

    def __init__(self, source: str, line: int, column: int, namespace: Dict[str, Any] = None, parent=None):
        super().__init__(parent)
        self.source = source
        self.line = line
        self.column = column
        self.namespace = namespace or {}

    def run(self):
        """Execute jedi completion."""
        if not HAS_JEDI:
            self.results_ready.emit([])
            return

        try:
            # Build namespace header and prepend to source
            ns_header = _build_namespace_header(self.namespace)
            ns_line_count = ns_header.count("\n")

            full_source = ns_header + self.source
            adjusted_line = self.line + ns_line_count

            script = jedi.Script(full_source)
            completions = script.complete(adjusted_line, self.column)

            results = []
            seen = set()
            for c in completions[:200]:  # Increased limit
                name = c.name

                # Filter out dunder methods unless user is typing __
                if name.startswith("__") and name.endswith("__"):
                    continue

                if name in seen:
                    continue
                seen.add(name)

                comp_type = c.type or ""
                description = ""

                try:
                    # Get signature for functions/methods
                    sigs = c.get_signatures()
                    if sigs:
                        description = str(sigs[0])
                    else:
                        # Try to get module/class info
                        description = c.description or ""
                except Exception:
                    pass

                results.append((name, comp_type, description))

            self.results_ready.emit(results)

        except Exception as e:
            logger.debug(f"Jedi completion error: {e}")
            self.results_ready.emit([])


class JediCompleter(QObject):
    """
    Manages jedi-based autocompletion with namespace support.

    Usage:
        completer = JediCompleter(parent)
        completer.completions_ready.connect(on_completions)
        completer.set_namespace({"df": pd.DataFrame(), ...})
        completer.request_completions(source, line, col)
    """

    completions_ready = pyqtSignal(list)  # List of (name, type, description)
    _shared_instance: Optional["JediCompleter"] = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: Optional[_JediThread] = None
        self._namespace: Dict[str, Any] = {}

    @classmethod
    def instance(cls, parent=None) -> "JediCompleter":
        """Return a process-wide Jedi completer instance."""
        if cls._shared_instance is None:
            cls._shared_instance = JediCompleter(parent)
        return cls._shared_instance

    def is_available(self) -> bool:
        """Check if jedi is installed."""
        return HAS_JEDI

    def set_namespace(self, namespace: Dict[str, Any]) -> None:
        """
        Update the Python namespace for context-aware completions.

        Args:
            namespace: Dict of variable name -> value from previous executions
        """
        self._namespace = namespace or {}

    def request_completions(self, source: str, line: int, column: int, namespace: Dict[str, Any] = None):
        """
        Request completions asynchronously.

        Args:
            source: Python source code
            line: 1-based line number
            column: 0-based column number
            namespace: Optional namespace override (uses stored namespace if not provided)
        """
        if not HAS_JEDI:
            self.completions_ready.emit([])
            return

        self._cleanup()

        ns = namespace if namespace is not None else self._namespace

        self._thread = _JediThread(source, line, column, namespace=ns, parent=self)
        self._thread.results_ready.connect(self._on_finished)
        self._thread.finished.connect(self._on_thread_done)
        self._thread.start()

    def complete_sync(self, source: str, line: int, column: int, namespace: Dict[str, Any] = None) -> List[Tuple[str, str, str]]:
        """
        Get completions synchronously (blocking).
        Use for quick completions when async is not needed.

        Args:
            source: Python source code
            line: 1-based line number
            column: 0-based column number
            namespace: Optional namespace override

        Returns:
            List of (name, type, description) tuples
        """
        if not HAS_JEDI:
            return []

        ns = namespace if namespace is not None else self._namespace

        try:
            ns_header = _build_namespace_header(ns)
            ns_line_count = ns_header.count("\n")

            full_source = ns_header + source
            adjusted_line = line + ns_line_count

            script = jedi.Script(full_source)
            completions = script.complete(adjusted_line, column)

            results = []
            seen = set()
            for c in completions[:200]:
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
                    else:
                        description = c.description or ""
                except Exception:
                    pass

                results.append((name, comp_type, description))

            return results

        except Exception as e:
            logger.debug(f"Jedi sync completion error: {e}")
            return []

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
