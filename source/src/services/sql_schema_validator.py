"""Validate SQL column/table references against a loaded database schema."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.services.syntax_validator import SyntaxMarker

try:
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import traverse_scope

    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False

_RE_GO_BATCH = re.compile(r"(?im)^[ \t]*GO(?:[ \t]+--[^\n]*)?[ \t]*$")


def _split_sql_batches(code: str) -> List[tuple[str, int]]:
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


def _marker_at(
    line: int,
    col: int,
    message: str,
    *,
    end_col: Optional[int] = None,
    severity: str = "error",
) -> SyntaxMarker:
    end = end_col if end_col is not None else col + max(1, len(message) // 4)
    return SyntaxMarker(
        start_line=max(1, line),
        start_column=max(1, col),
        end_line=max(1, line),
        end_column=max(1, end),
        message=message,
        severity=severity,
    )


def _expression_span(node) -> Tuple[int, int, int]:
    line = int(getattr(node, "line", None) or 1)
    col = int(getattr(node, "col", None) or 1)
    end_col = int(getattr(node, "end_col", None) or (col + len(str(getattr(node, "name", "") or ""))))
    return line, col, end_col


def _schema_has_objects(schema: dict) -> bool:
    if not schema:
        return False
    if schema.get("tables"):
        return True
    return bool(schema.get("columns"))


def _statement_slices(text: str, service: Any) -> List[tuple[str, int]]:
    """Return (statement_sql, 1-based start line within *text*)."""
    stripped = text.strip()
    if not stripped:
        return []

    normalized = service._normalize_batches(text)
    statements = service._split_sql_statements(normalized)
    if not statements:
        return []

    results: List[tuple[str, int]] = []
    search_from = 0
    for statement in statements:
        needle = statement.strip()
        if not needle:
            continue
        idx = text.find(needle, search_from)
        search_base = text
        if idx < 0:
            idx = normalized.find(needle, search_from)
            search_base = normalized
        if idx < 0:
            start_line = 1
        else:
            start_line = 1 + search_base[:idx].count("\n")
            search_from = idx + len(needle)
        results.append((statement, start_line))
    return results


def _validation_scope_analysis(
    statement: str,
    service: Any,
    *,
    previous_sql: str = "",
) -> dict[str, Any]:
    """Build alias/table scope for validation without cursor placeholder injection.

    Autocomplete injects a cursor token at the end of the statement, which can
    replace the trailing table alias (e.g. ``FROM Premio p`` → ``FROM Premio __cursor__``).
    Validation must parse the statement as written.
    """
    statement = statement.strip()
    script_state = service._collect_script_state(previous_sql)
    output_cache: dict[int, List[dict[str, Any]]] = {}

    parsed = service._parse_statement(statement)
    if parsed is None or not HAS_SQLGLOT:
        scope_sources, scope_lookup = service._fallback_scope_relations(statement, script_state)
        return {
            "parsed": None,
            "scope_sources": scope_sources,
            "scope_lookup": scope_lookup,
            "cte_lookup": {},
            "script_state": script_state,
        }

    scope_sources: List[dict[str, Any]] = []
    scope_lookup: dict[str, dict[str, Any]] = {}
    scopes = list(traverse_scope(parsed))
    cte_sources, cte_lookup = service._collect_cte_sources(scopes, script_state, output_cache)

    for scope in scopes:
        sources, lookup = service._resolve_scope_sources(scope, script_state, output_cache)
        for relation in sources:
            service._append_relation(scope_sources, scope_lookup, relation)
        for name, relation in lookup.items():
            scope_lookup[name] = relation

    update_relation = service._resolve_update_target(parsed, script_state)
    if update_relation is not None:
        service._append_relation(scope_sources, scope_lookup, update_relation)

    return {
        "parsed": parsed,
        "scope_sources": scope_sources,
        "scope_lookup": scope_lookup,
        "cte_lookup": cte_lookup,
        "cte_sources": cte_sources,
        "script_state": script_state,
    }


def validate_sql_schema(code: str, schema: Optional[dict] = None) -> List[SyntaxMarker]:
    """Flag unknown tables/columns using the same scope logic as SQL autocomplete."""
    text = code or ""
    if not text.strip() or not _schema_has_objects(schema or {}):
        return []

    if not HAS_SQLGLOT:
        return []

    from src.services.sql_autocomplete_service import (
        CURSOR_PLACEHOLDER,
        SqlAutoCompleteService,
    )

    service = SqlAutoCompleteService()
    service.set_schema(schema)

    markers: List[SyntaxMarker] = []
    seen: Set[Tuple[str, int, int]] = set()

    for batch, batch_start_line in _split_sql_batches(text):
        batch = batch.strip()
        if not batch:
            continue
        batch_base_offset = batch_start_line - 1
        previous_sql = ""

        for statement, stmt_start_line in _statement_slices(batch, service):
            statement = statement.strip()
            if not statement:
                continue
            line_offset = batch_base_offset + stmt_start_line - 1
            markers.extend(
                _validate_statement(
                    statement,
                    service,
                    line_offset,
                    seen,
                    previous_sql=previous_sql,
                )
            )
            previous_sql = f"{previous_sql};{statement}" if previous_sql else statement

    return markers


def _validate_statement(
    statement: str,
    service: Any,
    line_offset: int,
    seen: Set[Tuple[str, int, int]],
    *,
    previous_sql: str = "",
) -> List[SyntaxMarker]:
    from src.services.sql_autocomplete_service import CURSOR_PLACEHOLDER

    analysis = _validation_scope_analysis(statement, service, previous_sql=previous_sql)
    parsed = analysis.get("parsed")
    if parsed is None:
        return []

    scope_sources = analysis.get("scope_sources", [])
    scope_lookup = analysis.get("scope_lookup", {})
    cte_lookup = analysis.get("cte_lookup", {})
    script_lookup = analysis.get("script_state", {}).get("relation_lookup", {})

    markers: List[SyntaxMarker] = []

    for table in parsed.find_all(exp.Table):
        if isinstance(getattr(table, "this", None), exp.Parameter):
            continue
        table_name = service._table_identifier_from_expression(table)
        if not table_name:
            continue
        lookup_names = service._relation_lookup_names(table_name)
        if service._find_schema_entry(
            table.name or "",
            table.db or "",
            table.catalog or "",
        ) is not None:
            continue
        if any(script_lookup.get(name) for name in lookup_names):
            continue
        if any(scope_lookup.get(name) for name in lookup_names):
            continue
        line, col, end_col = _expression_span(table)
        key = ("table", line + line_offset, col)
        if key in seen:
            continue
        seen.add(key)
        markers.append(
            _marker_at(
                line + line_offset,
                col,
                f"Unknown table '{table_name}'",
                end_col=end_col,
            )
        )

    for column in parsed.find_all(exp.Column):
        name = str(getattr(column, "name", "") or "")
        if not name or name == "*":
            continue
        qualifier = str(getattr(column, "table", "") or "")
        if service._normalize_name(name) == service._normalize_name(CURSOR_PLACEHOLDER):
            continue

        if qualifier:
            normalized_qualifier = service._normalize_relation_key(qualifier)
            relation = (
                scope_lookup.get(normalized_qualifier)
                or cte_lookup.get(normalized_qualifier)
                or script_lookup.get(normalized_qualifier)
            )
            if relation is None:
                entry = service._find_schema_entry(qualifier)
                if entry is not None:
                    relation = service._make_relation(
                        entry["detail"],
                        entry.get("columns", []),
                        "table",
                        entry.get("detail", ""),
                        preferred_qualifier=qualifier,
                        lookup_names=set(entry.get("lookup_names", set())),
                    )
            if relation is None:
                line, col, end_col = _expression_span(column)
                key = ("qualifier", line + line_offset, col)
                if key not in seen:
                    seen.add(key)
                    markers.append(
                        _marker_at(
                            line + line_offset,
                            col,
                            f"Unknown table or alias '{qualifier}'",
                            end_col=end_col,
                        )
                    )
                continue

            if service._find_column_definition([relation], qualifier, name) is None:
                line, col, end_col = _expression_span(column)
                key = ("column", line + line_offset, col)
                if key not in seen:
                    seen.add(key)
                    markers.append(
                        _marker_at(
                            line + line_offset,
                            col,
                            f"Unknown column '{qualifier}.{name}'",
                            end_col=end_col,
                        )
                    )
            continue

        if scope_sources:
            if service._find_column_definition(scope_sources, "", name) is not None:
                continue
            line, col, end_col = _expression_span(column)
            key = ("column", line + line_offset, col)
            if key not in seen:
                seen.add(key)
                markers.append(
                    _marker_at(
                        line + line_offset,
                        col,
                        f"Unknown column '{name}'",
                        end_col=end_col,
                    )
                )
            continue

        if service._find_column_definition(
            [
                service._make_relation(
                    entry["detail"],
                    entry.get("columns", []),
                    "table",
                    entry.get("detail", ""),
                    preferred_qualifier=entry["name"],
                    lookup_names=set(entry.get("lookup_names", set())),
                )
                for entry in service._table_entries
            ],
            "",
            name,
        ) is None:
            line, col, end_col = _expression_span(column)
            key = ("column", line + line_offset, col)
            if key not in seen:
                seen.add(key)
                markers.append(
                    _marker_at(
                        line + line_offset,
                        col,
                        f"Unknown column '{name}'",
                        end_col=end_col,
                        severity="warning",
                    )
                )

    return markers
