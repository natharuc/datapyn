"""
PyniaToolRegistry — consolidated DataPyn tools for the native agent.

Exposes ~9 high-level tools to LLMs while delegating execution to the
legacy MCPToolRegistry (full IDE integration in mcp_tools.py).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject

from src.services.copilot.mcp_tools import MCPToolRegistry
from src.services.pynia.tools.definitions import pynia_tool_definitions
from src.services.pynia.tools.dispatch import PyniaToolDispatcher
from src.services.pynia.tools.types import PyniaTool

logger = logging.getLogger(__name__)


class PyniaToolRegistry(QObject):
    """
    Native Pynia tool surface for chat agents and MCP.

    Same threading contract as MCPToolRegistry: execute() is safe from
    worker threads when dispatched via ThreadSafeToolExecutor.
    """

    def __init__(self, parent=None, legacy_registry: Optional[MCPToolRegistry] = None):
        super().__init__(parent)
        self._legacy = legacy_registry or MCPToolRegistry(parent=self)
        self._dispatcher = PyniaToolDispatcher(self._legacy)
        self._tools: Dict[str, PyniaTool] = {}
        self._recent_tool_cache: Dict[tuple, tuple] = {}
        self._register_tools()

    @property
    def legacy_registry(self) -> MCPToolRegistry:
        """Underlying implementation registry (handlers, session pin)."""
        return self._legacy

    def set_main_window(self, main_window) -> None:
        self._legacy.set_main_window(main_window)

    def pin_session(self, session_id: str) -> None:
        self._legacy.pin_session(session_id)

    def unpin_session(self) -> None:
        self._legacy.unpin_session()

    def _register_tools(self) -> None:
        for spec in pynia_tool_definitions():
            name = spec["name"]

            def _make_handler(tool_name: str):
                def handler(args: Dict[str, Any]) -> Dict[str, Any]:
                    return self._dispatcher.dispatch(tool_name, args)

                return handler

            self._tools[name] = PyniaTool(
                name=name,
                description=spec["description"],
                parameters=spec["parameters"],
                handler=_make_handler(name),
            )

    def list_tools(self) -> List[Dict[str, Any]]:
        return [tool.to_mcp_schema() for tool in self._tools.values()]

    def list_tools_openai(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def tool_names(self) -> List[str]:
        return list(self._tools.keys())

    def execute(self, tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        tool = self._tools.get(tool_name)
        if not tool:
            return {"error": f"Unknown tool: {tool_name}"}

        if not self._legacy._main_window:
            return {"error": "Main window not available. Cannot execute tools."}

        return self._execute_directly(tool_name, arguments or {})

    def _execute_directly(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        tool = self._tools.get(tool_name)
        if not tool:
            return {"error": f"Unknown tool: {tool_name}"}

        cache_key = (tool_name, json.dumps(arguments, sort_keys=True, default=str))
        now = time.time()
        cached = self._recent_tool_cache.get(cache_key)
        if cached and now - cached[0] < 20:
            logger.info("Pynia tool '%s' deduplicated (20s cache)", tool_name)
            return cached[1]

        try:
            start = time.perf_counter()
            logger.info("Pynia executing '%s'", tool_name)
            result = tool.handler(arguments)
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("Pynia tool '%s' finished in %.0fms", tool_name, elapsed_ms)
            self._recent_tool_cache[cache_key] = (now, result)
            if len(self._recent_tool_cache) > 48:
                cutoff = now - 20
                self._recent_tool_cache = {
                    k: v for k, v in self._recent_tool_cache.items() if v[0] >= cutoff
                }
            return result
        except Exception as e:
            logger.error("Pynia tool '%s' failed: %s", tool_name, e)
            return {"error": str(e)}
