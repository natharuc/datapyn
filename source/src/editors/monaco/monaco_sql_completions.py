"""Build Monaco static completion payloads off the UI thread."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QThread, pyqtSignal

SQL_KEYWORDS = [
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "BETWEEN",
    "LIKE", "IS", "NULL", "JOIN", "INNER", "LEFT", "RIGHT", "OUTER",
    "ON", "AS", "ORDER BY", "GROUP BY", "HAVING", "LIMIT", "DISTINCT",
    "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE", "CREATE",
    "TABLE", "DROP", "ALTER", "COUNT", "SUM", "AVG", "MIN", "MAX",
    "CAST", "CASE", "WHEN", "THEN", "ELSE", "END",
]


def build_sql_completions(schema: Optional[dict]) -> List[Dict[str, Any]]:
    """Build Monaco completion items from a schema dict (CPU-only, thread-safe)."""
    if not schema:
        return []

    completions: List[Dict[str, Any]] = []

    for table in schema.get("tables", []) or []:
        if isinstance(table, dict):
            table_name = table.get("name", "")
            table_schema = table.get("schema", "")
            table_type = table.get("type", "TABLE")
            detail = f"{table_schema}.{table_name}" if table_schema else table_name
            detail = f"view: {detail}" if table_type == "VIEW" else f"table: {detail}"
        else:
            table_name = str(table)
            detail = "table"

        if table_name:
            completions.append({
                "label": table_name,
                "kind": "property",
                "insertText": table_name,
                "detail": detail,
                "category": "table",
            })

    for table_name, column_list in (schema.get("columns") or {}).items():
        for column in column_list or []:
            if isinstance(column, dict):
                column_name = column.get("name", "")
                column_type = column.get("type", "")
                detail = (
                    f"{table_name}.{column_name} ({column_type})"
                    if column_type
                    else f"{table_name}.{column_name}"
                )
            else:
                column_name = str(column)
                detail = f"{table_name}.{column_name}"

            if column_name:
                completions.append({
                    "label": column_name,
                    "kind": "field",
                    "insertText": column_name,
                    "detail": detail,
                    "category": "column",
                    "table": table_name,
                })

    for kw in SQL_KEYWORDS:
        completions.append({
            "label": kw,
            "kind": "keyword",
            "insertText": kw,
            "detail": "SQL keyword",
        })

    return completions


class SqlCompletionBuildWorker(QThread):
    """Build SQL completion payloads without blocking the UI thread."""

    completions_ready = pyqtSignal(int, list)

    def __init__(self, generation: int, schema: dict, parent=None):
        super().__init__(parent)
        self._generation = generation
        self._schema = schema or {}

    def run(self):
        if self.isInterruptionRequested():
            return
        completions = build_sql_completions(self._schema)
        if not self.isInterruptionRequested():
            self.completions_ready.emit(self._generation, completions)


PYTHON_KEYWORDS = [
    "def", "class", "if", "elif", "else", "for", "while", "break",
    "continue", "return", "import", "from", "as", "try", "except",
    "finally", "with", "lambda", "yield", "assert", "pass", "raise",
    "True", "False", "None", "and", "or", "not", "in", "is",
]

PYTHON_PACKAGES = [
    "pandas", "pd", "numpy", "np", "datetime", "json", "re", "os",
    "sys", "math", "random", "collections", "itertools",
]


def build_python_completions(variables: Optional[dict]) -> List[Dict[str, Any]]:
    completions: List[Dict[str, Any]] = []
    for var_name, var_info in (variables or {}).items():
        if str(var_name).startswith("_"):
            continue
        var_type = type(var_info).__name__ if not isinstance(var_info, str) else var_info
        completions.append({
            "label": var_name,
            "kind": "variable",
            "insertText": var_name,
            "detail": var_type,
        })

    for kw in PYTHON_KEYWORDS:
        completions.append({
            "label": kw,
            "kind": "keyword",
            "insertText": kw,
            "detail": "Python keyword",
        })

    for pkg in PYTHON_PACKAGES:
        completions.append({
            "label": pkg,
            "kind": "module",
            "insertText": pkg,
            "detail": "module",
        })

    return completions


class PythonCompletionBuildWorker(QThread):
    """Build Python completion payloads without blocking the UI thread."""

    completions_ready = pyqtSignal(int, list)

    def __init__(self, generation: int, variables: dict, parent=None):
        super().__init__(parent)
        self._generation = generation
        self._variables = variables or {}

    def run(self):
        if self.isInterruptionRequested():
            return
        completions = build_python_completions(self._variables)
        if not self.isInterruptionRequested():
            self.completions_ready.emit(self._generation, completions)
