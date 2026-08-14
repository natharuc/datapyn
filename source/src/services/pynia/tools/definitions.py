"""Consolidated Pynia tool schemas (~9 tools instead of 40+)."""

from __future__ import annotations

from typing import Any, Dict, List

# Shared parameter fragments
_BLOCK_REF = {
    "block_name": {
        "type": "string",
        "description": "Block name (preferred).",
        "optional": True,
    },
    "block_index": {
        "type": "integer",
        "description": "Block index in the active tab (0-based).",
        "optional": True,
    },
}


def pynia_tool_definitions() -> List[Dict[str, Any]]:
    """Return name, description, parameters for each public Pynia tool."""
    return [
        {
            "name": "datapyn_snapshot",
            "description": (
                "Read workspace state in one call. "
                "action=context: tab + blocks summary; blocks: block list; "
                "schema: DB schema; variables: namespace; full: context+blocks. "
                "Skip if turn context already has blocks/schema."
            ),
            "parameters": {
                "action": {
                    "type": "string",
                    "description": "One of: context, blocks, schema, variables, full.",
                },
                "tab_index": {
                    "type": "integer",
                    "description": "Optional tab index for schema/blocks on another tab.",
                    "optional": True,
                },
                "tab_name": {
                    "type": "string",
                    "description": "Optional tab title.",
                    "optional": True,
                },
            },
        },
        {
            "name": "datapyn_inspect",
            "description": (
                "Inspect one target inside this DataPyn tab (in-process, not HTTP). "
                "Defaults to the focused block. kind=block detail defaults to result "
                "(the Results grid) when omitted; use structure|code for the editor. "
                "kind=variable; kind=reference; kind=selection. "
                "Skip inspect on focused block if code is already in context. "
                "For grid questions, prefer execution_state.active_result already in the prompt."
            ),
            "parameters": {
                "kind": {
                    "type": "string",
                    "description": "block | variable | reference | selection.",
                },
                "detail": {
                    "type": "string",
                    "description": "For block: structure | code | result | execution. Default for kind=block is result (the Results grid).",
                    "optional": True,
                },
                **_BLOCK_REF,
                "variable_name": {
                    "type": "string",
                    "description": "Python variable name when kind=variable.",
                    "optional": True,
                },
                "reference": {
                    "type": "string",
                    "description": "DataPyn reference when kind=reference (e.g. #block:sales).",
                    "optional": True,
                },
                "around": {
                    "type": "string",
                    "description": "Anchor for partial code (id, class, symbol).",
                    "optional": True,
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to read (1-based).",
                    "optional": True,
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to read (1-based, inclusive).",
                    "optional": True,
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Max preview rows for result/dataframe.",
                    "optional": True,
                },
            },
        },
        {
            "name": "datapyn_query",
            "description": (
                "Run SQL or Python silently (no new visible block). "
                "Prefer this over bash/curl when exploring data. language=sql|python."
            ),
            "parameters": {
                "language": {
                    "type": "string",
                    "description": "sql or python.",
                },
                "code": {
                    "type": "string",
                    "description": "SQL or Python source to execute.",
                },
                "connection_name": {
                    "type": "string",
                    "description": "Saved connection for SQL (optional if tab already connected).",
                    "optional": True,
                },
            },
        },
        {
            "name": "datapyn_run",
            "description": (
                "Execute blocks in the IDE. Call this instead of telling the user to press F5. "
                "mode=block: run existing (defaults to focused); "
                "write: with block_name updates that block (or names a new one), "
                "without block_name creates a new block — then runs it; "
                "all: run every block in tab."
            ),
            "parameters": {
                "mode": {
                    "type": "string",
                    "description": "block | write | all.",
                },
                "code": {
                    "type": "string",
                    "description": "Required for mode=write.",
                    "optional": True,
                },
                "language": {
                    "type": "string",
                    "description": "sql | python | html for mode=write.",
                    "optional": True,
                },
                **_BLOCK_REF,
            },
        },
        {
            "name": "datapyn_edit",
            "description": (
                "Modify blocks in the editor. Call this instead of pasting code in chat. "
                "Defaults to focused block if block_name omitted. "
                "operation=lines: edit ONLY start_line..end_line (use for partial changes); "
                "replace: swap the ENTIRE block code; undo: restore the block to before "
                "the last Pynia edit; also selection|rename|delete|language."
            ),
            "parameters": {
                "operation": {
                    "type": "string",
                    "description": (
                        "lines (partial edit) | replace (whole block) | undo | "
                        "selection | rename | delete | language."
                    ),
                },
                **_BLOCK_REF,
                "content": {
                    "type": "string",
                    "description": "New code for replace/lines/selection.",
                    "optional": True,
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to edit (1-based).",
                    "optional": True,
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to edit (1-based, inclusive).",
                    "optional": True,
                },
                "force": {
                    "type": "boolean",
                    "description": (
                        "Confirm a whole-block replace that shrinks a large block "
                        "(safety guard refuses it otherwise)."
                    ),
                    "optional": True,
                },
                "new_name": {
                    "type": "string",
                    "description": "New block name for rename.",
                    "optional": True,
                },
                "language": {
                    "type": "string",
                    "description": "sql | python | html for operation=language.",
                    "optional": True,
                },
                "line_operation": {
                    "type": "string",
                    "description": "replace | insert | delete for operation=lines.",
                    "optional": True,
                },
            },
        },
        {
            "name": "datapyn_blocks",
            "description": (
                "Create or focus tabs and blocks. Call this instead of asking the user "
                "to add a block by hand. operation=create (no run), focus, tab (new session)."
            ),
            "parameters": {
                "operation": {
                    "type": "string",
                    "description": "create | focus | tab.",
                },
                "title": {
                    "type": "string",
                    "description": "Tab title when operation=tab.",
                    "optional": True,
                },
                **_BLOCK_REF,
                "code": {"type": "string", "optional": True},
                "language": {"type": "string", "optional": True},
            },
        },
        {
            "name": "datapyn_database",
            "description": (
                "Database connections and metadata. "
                "operation=connect|list|schema|tables|describe|sample|create|open."
            ),
            "parameters": {
                "operation": {
                    "type": "string",
                    "description": (
                        "connect | list | schema | tables | describe | sample | create | open."
                    ),
                },
                "connection_name": {"type": "string", "optional": True},
                "table_name": {"type": "string", "optional": True},
                "schema_name": {"type": "string", "optional": True},
                "limit": {"type": "integer", "optional": True},
                "host": {"type": "string", "optional": True},
                "port": {"type": "integer", "optional": True},
                "database": {"type": "string", "optional": True},
                "username": {"type": "string", "optional": True},
                "password": {"type": "string", "optional": True},
                "db_type": {"type": "string", "optional": True},
            },
        },
        {
            "name": "datapyn_chart",
            "description": (
                "Create or edit a chart from the Results grid NOW. "
                "Call this as soon as the user asks for a graph/chart/gráfico. "
                "Use execution_state.active_result and chart_sources from context; "
                "do not ask graph vs block vs visualization. "
                "operation=list|create|edit|get|delete|export. "
                "Not for HTML blocks — those use datapyn_edit. "
                "Never use curl or localhost HTTP to make charts."
            ),
            "parameters": {
                "operation": {
                    "type": "string",
                    "description": "list | create | edit | get | delete | export.",
                },
                "chart_index": {"type": "integer", "optional": True},
                "config": {
                    "type": "object",
                    "description": (
                        "Chart config for create/edit. Main keys: "
                        "type (bar|line|scatter|area|pie), x_column, "
                        "y_columns (list of numeric columns), "
                        "aggregation (sum|mean|count|min|max), group_by, "
                        "stacking (none|stacked|percent), title, "
                        "source_label (result tab label from chart_sources)."
                    ),
                    "optional": True,
                },
                "format": {
                    "type": "string",
                    "description": "png or jpg for export.",
                    "optional": True,
                },
                "path": {
                    "type": "string",
                    "description": "Export file path.",
                    "optional": True,
                },
            },
        },
        {
            "name": "datapyn_notify",
            "description": "Show a toast when the task is done or needs attention.",
            "parameters": {
                "title": {"type": "string", "description": "Short title."},
                "message": {"type": "string", "description": "Message body."},
                "success": {
                    "type": "boolean",
                    "description": "True=success styling, False=error.",
                    "optional": True,
                },
            },
        },
    ]
