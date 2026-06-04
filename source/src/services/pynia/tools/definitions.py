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
                "Inspect one target. Defaults to the user's focused block if block_name omitted. "
                "kind=block: structure|code|result; kind=variable; kind=reference; kind=selection. "
                "Skip inspect on focused block if code is already in context."
            ),
            "parameters": {
                "kind": {
                    "type": "string",
                    "description": "block | variable | reference | selection.",
                },
                "detail": {
                    "type": "string",
                    "description": (
                        "For block: structure | code | result | execution. "
                        "For variable: value | dataframe."
                    ),
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
                "start_line": {"type": "integer", "optional": True},
                "end_line": {"type": "integer", "optional": True},
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
                "Use for exploration before editing. language=sql|python."
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
                "Execute blocks visibly. mode=block: run existing; "
                "write: create/update block and run; all: run every block in tab."
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
                "Modify blocks. Defaults to focused block if block_name omitted. "
                "operation=replace|lines|selection|rename|delete|language."
            ),
            "parameters": {
                "operation": {
                    "type": "string",
                    "description": "replace | lines | selection | rename | delete | language.",
                },
                **_BLOCK_REF,
                "content": {
                    "type": "string",
                    "description": "New code for replace/selection.",
                    "optional": True,
                },
                "start_line": {"type": "integer", "optional": True},
                "end_line": {"type": "integer", "optional": True},
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
                "Manage tabs/blocks. operation=create (no run), focus, tab (new session)."
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
                "Charts from results. operation=list|create|edit|get|delete|export. "
                "Not for HTML blocks — edit those with datapyn_edit."
            ),
            "parameters": {
                "operation": {
                    "type": "string",
                    "description": "list | create | edit | get | delete | export.",
                },
                "chart_index": {"type": "integer", "optional": True},
                "config": {
                    "type": "object",
                    "description": "Chart config for create/edit.",
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
            "name": "datapyn_subagent",
            "description": (
                "Spawn parallel explore subagents (read-only) for heavy discovery. "
                "Each runs on a background worker with its own mini tool loop. "
                "Use for schema + multiple blocks at once. Max 3 per step. "
                "Provide instruction (required) or tasks[] with task_id + instruction."
            ),
            "parameters": {
                "instruction": {
                    "type": "string",
                    "description": "What this subagent should find out (read-only).",
                    "optional": True,
                },
                "context": {
                    "type": "string",
                    "description": "Optional extra context for the subagent.",
                    "optional": True,
                },
                "task_id": {
                    "type": "string",
                    "description": "Optional id for correlating results.",
                    "optional": True,
                },
                "tasks": {
                    "type": "array",
                    "description": (
                        "Parallel jobs: [{task_id, instruction, context?}, ...]. "
                        "Prefer this when you need 2+ explores at once."
                    ),
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
