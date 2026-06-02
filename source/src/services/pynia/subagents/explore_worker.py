"""Background explore subagent — mini LLM loop with read-only tools only."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from src.services.pynia.agent_loop_policy import truncate_tool_result
from src.services.pynia.subagents.classifier import EXPLORE_SUBAGENT_TOOLS, filter_openai_tools
from src.services.pynia.subagents.types import ExploreTask, ExploreTaskResult

if TYPE_CHECKING:
    from src.services.copilot.copilot_client_sdk import ThreadSafeToolExecutor

logger = logging.getLogger(__name__)

EXPLORE_SYSTEM = """\
You are a **Pynia explore subagent** inside DataPyn. Your job is ONE focused read-only task.
Use only datapyn_snapshot, datapyn_inspect, datapyn_database, datapyn_query.
Do not edit, run visible blocks, or create artifacts.
Be fast: at most **1–2** tool calls total, then return a concise factual summary for the main agent.
Never call datapyn_inspect on a block already described in the task context.
Respond in the same language as the task.
"""


class ExploreSubagentWorker(QObject):
    """Runs one explore task on a dedicated QThread (LLM + read-only tools)."""

    finished = pyqtSignal(object)  # ExploreTaskResult

    def __init__(
        self,
        task: ExploreTask,
        *,
        provider_id: str,
        model: str,
        openai_tools: List[Dict[str, Any]],
        tool_executor: Optional["ThreadSafeToolExecutor"],
        parent=None,
    ):
        super().__init__(parent)
        self._task = task
        self._provider_id = provider_id
        self._model = model
        self._tools = filter_openai_tools(openai_tools, EXPLORE_SUBAGENT_TOOLS)
        self._tool_executor = tool_executor
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _execute_tool(self, name: str, arguments: dict) -> str:
        if not self._tool_executor:
            return f"Error: Tools not available for {name}"
        return truncate_tool_result(self._tool_executor.execute(name, arguments))

    @pyqtSlot()
    def run(self) -> None:
        task = self._task
        try:
            if not self._tool_executor:
                self.finished.emit(
                    ExploreTaskResult(
                        task_id=task.task_id,
                        summary="Error: tool executor not configured.",
                        ok=False,
                    )
                )
                return

            user_body = task.instruction.strip()
            if task.context.strip():
                user_body = f"{task.context.strip()}\n\n## Task\n{user_body}"

            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": EXPLORE_SYSTEM},
                {"role": "user", "content": user_body},
            ]
            is_cancelled = lambda: self._cancelled
            tool_trace: List[Dict[str, Any]] = []

            def on_tool_call(name: str, args: dict, tc_id: str) -> None:
                tool_trace.append({"tool": name, "args": args, "id": tc_id})

            def on_tool_result(name: str, result: str, tc_id: str) -> None:
                for entry in tool_trace:
                    if entry.get("id") == tc_id:
                        entry["result_preview"] = (result or "")[:400]
                        break

            if self._provider_id == "anthropic":
                from src.services.pynia.anthropic_agent_loop import run_anthropic_agent_turn

                summary = run_anthropic_agent_turn(
                    api_key=self._api_key(),
                    model=self._model,
                    messages=messages,
                    tools=self._tools,
                    attachments=None,
                    execute_tool=self._execute_tool,
                    tool_executor=self._tool_executor,
                    on_chunk=lambda _c: None,
                    on_tool_call=on_tool_call,
                    on_tool_result=on_tool_result,
                    is_cancelled=is_cancelled,
                    max_tool_rounds=task.max_tool_rounds,
                )
            else:
                from src.services.pynia.openai_agent_loop import run_openai_agent_turn
                from src.services.pynia.providers.token_worker import OPENROUTER_HEADERS
                from src.services.pynia.settings import get_pynia_settings

                settings = get_pynia_settings()
                extra = OPENROUTER_HEADERS if self._provider_id == "openrouter" else None
                summary = run_openai_agent_turn(
                    base_url=settings.base_url(self._provider_id),
                    api_key=self._api_key(),
                    model=self._model,
                    messages=messages,
                    tools=self._tools,
                    attachments=None,
                    execute_tool=self._execute_tool,
                    tool_executor=self._tool_executor,
                    on_chunk=lambda _c: None,
                    on_tool_call=on_tool_call,
                    on_tool_result=on_tool_result,
                    is_cancelled=is_cancelled,
                    max_tool_rounds=task.max_tool_rounds,
                    extra_headers=extra,
                )

            self.finished.emit(
                ExploreTaskResult(
                    task_id=task.task_id,
                    summary=(summary or "").strip() or "(no summary)",
                    ok=True,
                    tool_trace=tool_trace,
                )
            )
        except Exception as exc:
            logger.exception("Explore subagent %s failed", task.task_id)
            self.finished.emit(
                ExploreTaskResult(
                    task_id=task.task_id,
                    summary=f"Explore subagent error: {exc}",
                    ok=False,
                )
            )

    def _api_key(self) -> str:
        from src.services.pynia.settings import get_provider_secret

        token = get_provider_secret(self._provider_id)
        if not token:
            raise RuntimeError("API token not configured.")
        return token


def run_tool_only_explore(
    tool_name: str,
    arguments: dict,
    tool_executor: "ThreadSafeToolExecutor",
) -> str:
    """Fast path: run a single read-only tool without an LLM hop."""
    return truncate_tool_result(tool_executor.execute(tool_name, arguments or {}))
