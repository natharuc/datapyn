"""
Map consolidated Pynia tools to legacy MCPToolRegistry handlers.

Keeps battle-tested IDE implementations in mcp_tools.py while exposing
a small, fast tool surface to the LLM.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, TYPE_CHECKING

from src.services.pynia.focus_context import apply_focused_block_defaults

if TYPE_CHECKING:
    from src.services.copilot.mcp_tools import MCPToolRegistry

logger = logging.getLogger(__name__)


def _merge_content(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Combine multiple legacy tool results into one response."""
    parts: List[str] = []
    for result in results:
        if "error" in result:
            return result
        for item in result.get("content", []):
            text = item.get("text", str(item))
            if text:
                parts.append(text)
    return {"content": [{"type": "text", "text": "\n\n".join(parts)}]}


def _pick_block_args(args: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if args.get("block_name"):
        out["block_name"] = args["block_name"]
    if args.get("block_index") is not None:
        out["block_index"] = args["block_index"]
    return out


class PyniaToolDispatcher:
    """Routes datapyn_* tool calls to the legacy registry."""

    def __init__(self, legacy: "MCPToolRegistry"):
        self._legacy = legacy
        self._orchestrator = None
        self._workspace_context: str = ""

    def set_workspace_context(self, context_json: str = "") -> None:
        self._workspace_context = (context_json or "").strip()

    def set_orchestrator(self, orchestrator) -> None:
        self._orchestrator = orchestrator

    def dispatch(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            "datapyn_snapshot": self._snapshot,
            "datapyn_inspect": self._inspect,
            "datapyn_query": self._query,
            "datapyn_run": self._run,
            "datapyn_edit": self._edit,
            "datapyn_blocks": self._blocks,
            "datapyn_database": self._database,
            "datapyn_chart": self._chart,
            "datapyn_notify": self._notify,
            "datapyn_subagent": self._subagent,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown Pynia tool: {tool_name}"}
        args = apply_focused_block_defaults(tool_name, arguments or {}, self._legacy)
        return handler(args)

    def _exec(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._legacy.execute(name, args)

    def _snapshot(self, args: Dict[str, Any]) -> Dict[str, Any]:
        action = (args.get("action") or "context").lower().strip()
        tab_args: Dict[str, Any] = {}
        if args.get("tab_index") is not None:
            tab_args["tab_index"] = args["tab_index"]
        if args.get("tab_name"):
            tab_args["tab_name"] = args["tab_name"]

        if action == "blocks":
            return self._exec("list_blocks", {})
        if action == "schema":
            return self._exec("get_database_schema", {})
        if action == "variables":
            return self._exec("get_variables", {})
        if action == "full":
            return _merge_content([
                self._exec("get_context", {}),
                self._exec("list_blocks", {}),
            ])
        if action in ("tab", "tab_context") and tab_args:
            return self._exec("get_tab_context", tab_args)
        if tab_args:
            return self._exec("get_tab_context", tab_args)
        return self._exec("get_context", {})

    def _inspect(self, args: Dict[str, Any]) -> Dict[str, Any]:
        kind = (args.get("kind") or "block").lower().strip()
        detail = (args.get("detail") or "").lower().strip()
        block_args = _pick_block_args(args)

        if kind == "reference":
            ref = args.get("reference", "")
            if not ref:
                return {"error": "reference is required when kind=reference"}
            return self._exec("resolve_reference", {"reference": ref})

        if kind == "selection":
            return self._exec("get_selection", {})

        if kind == "variable":
            name = args.get("variable_name", "")
            if not name:
                return {"error": "variable_name is required when kind=variable"}
            if detail == "dataframe":
                return self._exec("get_dataframe_info", {"variable_name": name})
            return self._exec("inspect_variable", {"variable_name": name})

        # kind == block (default)
        if not block_args and not args.get("block_name") and args.get("block_index") is None:
            return {"error": "block_name or block_index required for kind=block"}

        if detail == "outline":
            detail = "structure"
        elif detail == "":
            # An anchor or line range implies a code read; otherwise default
            # to the cheap structure outline.
            if args.get("around") or args.get("start_line") is not None:
                detail = "code"
            else:
                detail = "structure"

        if detail == "structure":
            return self._exec("inspect_block", block_args)
        if detail == "result":
            payload = dict(block_args)
            if args.get("max_rows") is not None:
                payload["max_rows"] = args["max_rows"]
            return self._exec("get_block_result", payload)
        if detail == "execution":
            return self._exec("get_execution_results", block_args)

        # detail == code — avoid full-file reads on large blocks without an anchor
        payload = dict(block_args)
        for key in ("around", "start_line", "end_line", "context_lines"):
            if args.get(key) is not None:
                payload[key] = args[key]
        if (
            not payload.get("around")
            and payload.get("start_line") is None
            and payload.get("end_line") is None
        ):
            payload["start_line"] = 1
            payload["end_line"] = 120
        return self._exec("get_block_code", payload)

    def _query(self, args: Dict[str, Any]) -> Dict[str, Any]:
        language = (args.get("language") or "sql").lower().strip()
        code = args.get("code", "")
        if not code:
            return {"error": "code is required"}

        if language in ("python", "py"):
            return self._exec("run_silent_python", {"code": code})
        payload: Dict[str, Any] = {"query": code}
        if args.get("connection_name"):
            payload["connection_name"] = args["connection_name"]
        return self._exec("run_silent_query", payload)

    def _run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        mode = (args.get("mode") or "block").lower().strip()
        block_args = _pick_block_args(args)

        if mode == "all":
            return self._exec("run_all_blocks", {})
        if mode == "write":
            code = args.get("code", "")
            if not code:
                return {"error": "code is required for mode=write"}
            payload: Dict[str, Any] = {"code": code}
            if args.get("language"):
                payload["language"] = args["language"]
            payload.update(block_args)
            return self._exec("write_and_run", payload)
        if not block_args:
            return {"error": "block_name or block_index required for mode=block"}
        return self._exec("execute_block", block_args)

    def _edit(self, args: Dict[str, Any]) -> Dict[str, Any]:
        operation = (args.get("operation") or "replace").lower().strip()
        block_args = _pick_block_args(args)

        if operation == "selection":
            payload: Dict[str, Any] = {}
            if args.get("content") is not None:
                payload["code"] = args["content"]
            return self._exec("replace_selection", payload)

        if operation == "rename":
            if not args.get("new_name"):
                return {"error": "new_name is required for operation=rename"}
            payload = dict(block_args)
            payload["new_name"] = args["new_name"]
            return self._exec("rename_block", payload)

        if operation == "delete":
            return self._exec("delete_block", block_args)

        if operation in ("undo", "restore"):
            return self._exec("undo_block_edit", block_args)

        if operation == "language":
            if not args.get("language"):
                return {"error": "language is required for operation=language"}
            payload = dict(block_args)
            payload["language"] = args["language"]
            return self._exec("set_block_language", payload)

        if operation == "lines":
            payload = dict(block_args)
            if args.get("start_line") is not None:
                payload["start_line"] = args["start_line"]
            if args.get("end_line") is not None:
                payload["end_line"] = args["end_line"]
            if args.get("content") is not None:
                payload["new_code"] = args["content"]
            if args.get("line_operation") is not None:
                payload["mode"] = args["line_operation"]
            return self._exec("edit_block_lines", payload)

        # replace
        if not args.get("content"):
            return {"error": "content is required for operation=replace"}
        # replace + line range means "replace these lines", NOT the whole
        # block — route to the line editor. Sending the snippet to edit_block
        # would wipe everything outside the range.
        if args.get("start_line") is not None or args.get("end_line") is not None:
            payload = dict(block_args)
            payload["start_line"] = args.get("start_line") or 1
            if args.get("end_line") is not None:
                payload["end_line"] = args["end_line"]
            payload["new_code"] = args["content"]
            payload["mode"] = "replace"
            return self._exec("edit_block_lines", payload)
        payload = dict(block_args)
        payload["code"] = args["content"]
        if args.get("force") is not None:
            payload["force"] = args["force"]
        return self._exec("edit_block", payload)

    def _blocks(self, args: Dict[str, Any]) -> Dict[str, Any]:
        operation = (args.get("operation") or "create").lower().strip()

        if operation == "tab":
            return self._exec("create_tab", {"title": args.get("title") or "New Tab"})
        if operation == "focus":
            return self._exec("move_focus", _pick_block_args(args))

        payload = _pick_block_args(args)
        if args.get("code"):
            payload["code"] = args["code"]
        if args.get("language"):
            payload["language"] = args["language"]
        return self._exec("create_block", payload)

    def _database(self, args: Dict[str, Any]) -> Dict[str, Any]:
        operation = (args.get("operation") or "list").lower().strip()

        mapping = {
            "connect": ("connect_database", ["connection_name"]),
            "list": ("list_connections", []),
            "schema": ("get_database_schema", []),
            "read_schema": ("read_schema", ["connection_name"]),
            "tables": ("list_tables", ["connection_name", "schema_name"]),
            "describe": ("describe_table", ["table_name", "connection_name", "schema_name"]),
            "sample": ("sample_data", ["table_name", "connection_name", "schema_name", "limit"]),
            "create": ("create_connection", [
                "connection_name", "host", "port", "database",
                "username", "password", "db_type",
            ]),
            "open": ("open_connection", ["connection_name"]),
        }
        entry = mapping.get(operation)
        if not entry:
            return {"error": f"Unknown database operation: {operation}"}

        legacy_name, keys = entry
        payload = {k: args[k] for k in keys if args.get(k) is not None}
        if operation == "connect" and not payload.get("connection_name"):
            return {"error": "connection_name is required for operation=connect"}
        if operation in ("describe", "sample") and not args.get("table_name"):
            return {"error": "table_name is required for describe/sample"}
        return self._exec(legacy_name, payload)

    def _chart(self, args: Dict[str, Any]) -> Dict[str, Any]:
        operation = (args.get("operation") or "list").lower().strip()

        if operation == "list":
            return self._exec("list_visualizations", {})
        if operation == "create":
            if not args.get("config"):
                return {"error": "config is required for operation=create"}
            return self._exec("create_visualization", {"config": args["config"]})
        if operation == "edit":
            if args.get("chart_index") is None:
                return {"error": "chart_index is required for operation=edit"}
            return self._exec(
                "edit_visualization",
                {"chart_index": args["chart_index"], "config": args.get("config") or {}},
            )
        if operation == "get":
            if args.get("chart_index") is None:
                return {"error": "chart_index is required for operation=get"}
            return self._exec("get_visualization_config", {"chart_index": args["chart_index"]})
        if operation == "delete":
            if args.get("chart_index") is None:
                return {"error": "chart_index is required for operation=delete"}
            return self._exec("delete_visualization", {"chart_index": args["chart_index"]})
        if operation == "export":
            payload: Dict[str, Any] = {}
            if args.get("chart_index") is not None:
                payload["chart_index"] = args["chart_index"]
            if args.get("format"):
                payload["format"] = args["format"]
            if args.get("path"):
                payload["path"] = args["path"]
            return self._exec("export_visualization", payload)
        return {"error": f"Unknown chart operation: {operation}"}

    def _subagent(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self._orchestrator:
            return {"error": "Parallel subagents are not available in this session."}
        payload = dict(args or {})
        if self._workspace_context and not str(payload.get("context") or "").strip():
            payload["context"] = (
                "## Workspace (auto)\n"
                f"{self._workspace_context[:12_000]}"
            )
        return self._orchestrator.run_subagent_tool(payload)

    def _notify(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._exec(
            "notify_user",
            {
                "title": args.get("title", "Pynia"),
                "message": args.get("message", ""),
                "success": args.get("success", True),
            },
        )
