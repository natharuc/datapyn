"""Tests for consolidated Pynia tools (dispatch + registry)."""

from unittest.mock import MagicMock

import pytest

from src.services.pynia.tools.definitions import pynia_tool_definitions
from src.services.pynia.tools.dispatch import PyniaToolDispatcher
from src.services.pynia.tools.registry import PyniaToolRegistry


class TestPyniaToolDefinitions:
    def test_ten_consolidated_tools(self):
        names = [t["name"] for t in pynia_tool_definitions()]
        assert len(names) == 10
        assert "datapyn_subagent" in names
        assert names == [
            "datapyn_snapshot",
            "datapyn_inspect",
            "datapyn_query",
            "datapyn_run",
            "datapyn_edit",
            "datapyn_blocks",
            "datapyn_database",
            "datapyn_chart",
            "datapyn_subagent",
            "datapyn_notify",
        ]


class TestPyniaToolDispatcher:
    def _legacy(self):
        legacy = MagicMock()
        legacy.execute = MagicMock(
            return_value={"content": [{"type": "text", "text": "ok"}]}
        )
        legacy._get_block_editor.return_value = None
        return legacy

    def test_snapshot_full_merges_two_calls(self):
        legacy = self._legacy()
        dispatcher = PyniaToolDispatcher(legacy)
        result = dispatcher.dispatch("datapyn_snapshot", {"action": "full"})
        assert "content" in result
        assert legacy.execute.call_count == 2
        legacy.execute.assert_any_call("get_context", {})
        legacy.execute.assert_any_call("list_blocks", {})

    def test_query_sql(self):
        legacy = self._legacy()
        dispatcher = PyniaToolDispatcher(legacy)
        dispatcher.dispatch(
            "datapyn_query",
            {"language": "sql", "code": "SELECT 1"},
        )
        legacy.execute.assert_called_with("run_silent_query", {"query": "SELECT 1"})

    def test_query_python(self):
        legacy = self._legacy()
        dispatcher = PyniaToolDispatcher(legacy)
        dispatcher.dispatch(
            "datapyn_query",
            {"language": "python", "code": "print(1)"},
        )
        legacy.execute.assert_called_with(
            "run_silent_python", {"code": "print(1)"}
        )

    def test_run_write(self):
        legacy = self._legacy()
        dispatcher = PyniaToolDispatcher(legacy)
        dispatcher.dispatch(
            "datapyn_run",
            {"mode": "write", "code": "SELECT 1", "language": "sql"},
        )
        legacy.execute.assert_called_with(
            "write_and_run", {"code": "SELECT 1", "language": "sql"}
        )

    def test_edit_replace_maps_content_to_code(self):
        legacy = self._legacy()
        dispatcher = PyniaToolDispatcher(legacy)
        sql = "SELECT 1 AS x"
        dispatcher.dispatch(
            "datapyn_edit",
            {
                "operation": "replace",
                "block_name": "block1",
                "content": sql,
            },
        )
        legacy.execute.assert_called_with(
            "edit_block",
            {"block_name": "block1", "code": sql},
        )

    def test_edit_lines(self):
        legacy = self._legacy()
        dispatcher = PyniaToolDispatcher(legacy)
        dispatcher.dispatch(
            "datapyn_edit",
            {
                "operation": "lines",
                "block_name": "a",
                "start_line": 1,
                "end_line": 2,
                "content": "x",
                "line_operation": "replace",
            },
        )
        legacy.execute.assert_called_with(
            "edit_block_lines",
            {
                "block_name": "a",
                "start_line": 1,
                "end_line": 2,
                "new_code": "x",
                "mode": "replace",
            },
        )

    def test_inspect_reference(self):
        legacy = self._legacy()
        dispatcher = PyniaToolDispatcher(legacy)
        dispatcher.dispatch(
            "datapyn_inspect",
            {"kind": "reference", "reference": "#block:sales"},
        )
        legacy.execute.assert_called_with(
            "resolve_reference", {"reference": "#block:sales"}
        )

    def test_notify(self):
        legacy = self._legacy()
        dispatcher = PyniaToolDispatcher(legacy)
        dispatcher.dispatch(
            "datapyn_notify",
            {"title": "Done", "message": "All good"},
        )
        legacy.execute.assert_called_with(
            "notify_user",
            {"title": "Done", "message": "All good", "success": True},
        )


class TestPyniaToolRegistry:
    def test_list_openai_format(self):
        registry = PyniaToolRegistry(parent=None, legacy_registry=MagicMock())
        tools = registry.list_tools_openai()
        assert len(tools) == 10
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"].startswith("datapyn_")

    def test_execute_without_main_window(self):
        legacy = MagicMock()
        legacy._main_window = None
        registry = PyniaToolRegistry(parent=None, legacy_registry=legacy)
        result = registry.execute("datapyn_notify", {"title": "t", "message": "m"})
        assert "error" in result
        assert "Main window" in result["error"]
