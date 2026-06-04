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


def validate_python(code: str) -> List[SyntaxMarker]:
    """Parse Python source; return syntax error markers (empty if valid)."""
    text = code or ""
    if not text.strip():
        return []

    try:
        ast.parse(text)
        return []
    except SyntaxError as exc:
        return [_marker_from_syntax_error(exc)]


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


def validate_sql(code: str, db_type: Optional[str] = None) -> List[SyntaxMarker]:
    """Parse SQL with sqlglot; return syntax error markers."""
    text = code or ""
    if not text.strip():
        return []

    dialect = _sql_dialect(db_type)
    markers: List[SyntaxMarker] = []
    for batch, start_line in _split_sql_batches(text):
        batch_markers = _validate_sql_batch(batch, dialect, start_line - 1)
        markers.extend(batch_markers)
    return markers


def validate_code(language: str, code: str, *, db_type: Optional[str] = None) -> List[SyntaxMarker]:
    """Validate by block language id (python, sql)."""
    lang = (language or "").lower()
    if lang == "python":
        return validate_python(code)
    if lang == "sql":
        return validate_sql(code, db_type=db_type)
    return []
