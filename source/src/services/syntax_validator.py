"""Syntax validation for Monaco editors (Python + SQL)."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import List, Optional

# T-SQL batch separator (validated per batch).
_RE_GO_BATCH = re.compile(r"(?im)^[ \t]*GO(?:[ \t]+--[^\n]*)?[ \t]*$")

_SQL_DIALECT_MAP = {
    "mssql": "tsql",
    "sqlserver": "tsql",
    "tsql": "tsql",
    "mysql": "mysql",
    "mariadb": "mysql",
    "postgresql": "postgres",
    "postgres": "postgres",
    "redshift": "redshift",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "databricks": "databricks",
    "spark": "spark",
    "sqlite": "sqlite",
    "oracle": "oracle",
}


@dataclass(frozen=True)
class SyntaxMarker:
    """Monaco marker (1-based line/column)."""

    start_line: int
    start_column: int
    end_line: int
    end_column: int
    message: str
    severity: str = "error"  # error | warning

    def to_dict(self) -> dict:
        return {
            "startLineNumber": self.start_line,
            "startColumn": self.start_column,
            "endLineNumber": self.end_line,
            "endColumn": self.end_column,
            "message": self.message,
            "severity": self.severity,
        }


import builtins as _builtins_mod

_PYTHON_BUILTINS = {
    name for name in dir(_builtins_mod) if not name.startswith("_")
}

_PYTHON_EXTRA_GLOBALS = {
    "pd",
    "np",
    "plt",
    "sns",
    "datetime",
    "json",
    "re",
    "os",
    "sys",
    "math",
    "random",
}


def _collect_python_scoped_names(tree: ast.AST) -> set[str]:
    """Names assigned or imported in the snippet (module-level scope)."""
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    defined.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                defined.update(_names_from_assign_target(target))
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            defined.update(_names_from_assign_target(node.target))
        elif isinstance(node, ast.For):
            defined.update(_names_from_assign_target(node.target))
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    defined.update(_names_from_assign_target(item.optional_vars))
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
    return defined


def _names_from_assign_target(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for elt in target.elts:
            names.update(_names_from_assign_target(elt))
        return names
    if isinstance(target, ast.Starred):
        return _names_from_assign_target(target.value)
    return set()


def _undefined_python_names(
    tree: ast.AST,
    namespace: Optional[dict],
) -> List[SyntaxMarker]:
    known = set(namespace or {}) | _PYTHON_BUILTINS | _PYTHON_EXTRA_GLOBALS
    known.update(_collect_python_scoped_names(tree))

    markers: List[SyntaxMarker] = []
    seen: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        name = node.id
        if name in known or name.startswith("_"):
            continue
        key = (node.lineno, name)
        if key in seen:
            continue
        seen.add(key)
        col = getattr(node, "col_offset", 0) + 1
        markers.append(
            SyntaxMarker(
                start_line=int(node.lineno or 1),
                start_column=max(1, col),
                end_line=int(node.lineno or 1),
                end_column=max(1, col + len(name)),
                message=f"Undefined name: {name}",
                severity="error",
            )
        )
    return markers


def validate_python(
    code: str,
    *,
    namespace: Optional[dict] = None,
) -> List[SyntaxMarker]:
    """Parse Python source; return syntax and undefined-name markers."""
    text = code or ""
    if not text.strip():
        return []

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [_marker_from_syntax_error(exc)]

    if namespace is None:
        return []
    return _undefined_python_names(tree, namespace)


def _marker_from_syntax_error(exc: SyntaxError) -> SyntaxMarker:
    line = int(exc.lineno or 1)
    col = int(exc.offset or 1)
    end_line = int(getattr(exc, "end_lineno", None) or line)
    end_col = int(getattr(exc, "end_offset", None) or (col + 1))
    if end_line == line and end_col <= col:
        end_col = col + 1
    msg = exc.msg or str(exc)
    return SyntaxMarker(
        start_line=line,
        start_column=max(1, col),
        end_line=end_line,
        end_column=max(1, end_col),
        message=f"SyntaxError: {msg}",
    )


def _sql_dialect(db_type: Optional[str]) -> str:
    if not db_type:
        return "tsql"
    return _SQL_DIALECT_MAP.get(str(db_type).lower().strip(), "tsql")


def _split_sql_batches(code: str) -> List[tuple[str, int]]:
    """Return (batch_text, 1-based start line of batch)."""
    lines = code.splitlines(keepends=True)
    batches: List[tuple[str, int]] = []
    start_line = 1
    chunk: List[str] = []

    for idx, line in enumerate(lines):
        if _RE_GO_BATCH.match(line.rstrip("\r\n")):
            if chunk:
                batches.append(("".join(chunk), start_line))
                chunk = []
            start_line = idx + 2
            continue
        if not chunk:
            start_line = idx + 1
        chunk.append(line)

    if chunk:
        batches.append(("".join(chunk), start_line))
    return batches if batches else [(code, 1)]


def _offset_marker(marker: SyntaxMarker, line_offset: int) -> SyntaxMarker:
    return SyntaxMarker(
        start_line=marker.start_line + line_offset,
        start_column=marker.start_column,
        end_line=marker.end_line + line_offset,
        end_column=marker.end_column,
        message=marker.message,
        severity=marker.severity,
    )


def _validate_sql_batch(batch: str, dialect: str, line_offset: int) -> List[SyntaxMarker]:
    batch = batch.strip()
    if not batch:
        return []

    try:
        import sqlglot
        from sqlglot.errors import ParseError
    except ImportError:
        return []

    try:
        sqlglot.parse(batch, dialect=dialect)
        return []
    except ParseError as exc:
        markers: List[SyntaxMarker] = []
        errors = getattr(exc, "errors", None) or []
        if errors:
            for err in errors:
                markers.extend(_markers_from_sqlglot_error(err, line_offset))
        if markers:
            return markers
        return [_marker_from_sqlglot_exception(exc, line_offset)]
    except Exception as exc:
        return [
            SyntaxMarker(
                start_line=1 + line_offset,
                start_column=1,
                end_line=1 + line_offset,
                end_column=2,
                message=str(exc),
            )
        ]


def _markers_from_sqlglot_error(err, line_offset: int) -> List[SyntaxMarker]:
    if isinstance(err, dict):
        line = int(err.get("line") or err.get("lineno") or 1)
        col = int(err.get("col") or err.get("start") or 1)
        msg = err.get("description") or err.get("message") or "SQL syntax error"
    else:
        line = int(getattr(err, "line", None) or getattr(err, "lineno", None) or 1)
        col = int(getattr(err, "col", None) or getattr(err, "start", None) or 1)
        msg = str(getattr(err, "description", None) or err)

    return [
        SyntaxMarker(
            start_line=line + line_offset,
            start_column=max(1, col),
            end_line=line + line_offset,
            end_column=max(1, col + 1),
            message=f"SQL: {msg}",
        )
    ]


def _marker_from_sqlglot_exception(exc: Exception, line_offset: int) -> SyntaxMarker:
    line = int(getattr(exc, "line", None) or 1)
    col = int(getattr(exc, "col", None) or 1)
    return SyntaxMarker(
        start_line=line + line_offset,
        start_column=max(1, col),
        end_line=line + line_offset,
        end_column=max(1, col + 1),
        message=f"SQL: {exc}",
    )


def _iter_sql_statements_in_batch(batch: str) -> List[tuple[str, int]]:
    """Split a batch into statements with 1-based start lines (T-SQL ``;`` / ``GO``)."""
    try:
        from src.services.sql_autocomplete_service import SqlAutoCompleteService

        service = SqlAutoCompleteService()
        from src.services.sql_schema_validator import _statement_slices

        return _statement_slices(batch, service)
    except Exception:
        stripped = batch.strip()
        return [(stripped, 1)] if stripped else []


def validate_sql(
    code: str,
    db_type: Optional[str] = None,
    *,
    schema: Optional[dict] = None,
) -> List[SyntaxMarker]:
    """Parse SQL with sqlglot; return syntax and optional schema error markers."""
    text = code or ""
    if not text.strip():
        return []

    dialect = _sql_dialect(db_type)
    if schema and not db_type:
        dialect = _sql_dialect(schema.get("db_type"))

    markers: List[SyntaxMarker] = []
    for batch, start_line in _split_sql_batches(text):
        batch_base = start_line - 1
        for statement, stmt_line in _iter_sql_statements_in_batch(batch):
            stmt = statement.strip()
            if not stmt:
                continue
            line_offset = batch_base + stmt_line - 1
            markers.extend(_validate_sql_batch(stmt, dialect, line_offset))

    if schema:
        try:
            from src.services.sql_schema_validator import validate_sql_schema

            schema_markers = validate_sql_schema(text, schema)
            markers.extend(schema_markers)
        except Exception:
            pass

    return markers


def validate_code(
    language: str,
    code: str,
    *,
    db_type: Optional[str] = None,
    schema: Optional[dict] = None,
    namespace: Optional[dict] = None,
) -> List[SyntaxMarker]:
    """Validate by block language id (python, sql)."""
    lang = (language or "").lower()
    if lang == "python":
        return validate_python(code, namespace=namespace)
    if lang == "sql":
        return validate_sql(code, db_type=db_type, schema=schema)
    return []
