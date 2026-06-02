"""Run explore subagents in parallel on background QThreads."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread, QEventLoop

from src.services.pynia.subagents.explore_worker import ExploreSubagentWorker
from src.services.pynia.subagents.types import ExploreTask, ExploreTaskResult

if TYPE_CHECKING:
    from src.services.copilot.copilot_client_sdk import ThreadSafeToolExecutor

logger = logging.getLogger(__name__)

MAX_PARALLEL_EXPLORE = 4


class SubagentOrchestrator(QObject):
    """
    Spawns explore subagents on dedicated QThreads.

    LLM calls run in parallel; each subagent marshals IDE tools to the Qt main thread.
    """

    def __init__(
        self,
        *,
        provider_id: str,
        model: str,
        openai_tools: List[Dict[str, Any]],
        tool_executor: Optional["ThreadSafeToolExecutor"] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._provider_id = provider_id
        self._model = model
        self._openai_tools = openai_tools
        self._tool_executor = tool_executor

    def set_model(self, model: str) -> None:
        self._model = model

    def set_provider(self, provider_id: str) -> None:
        self._provider_id = provider_id

    def set_openai_tools(self, tools: List[Dict[str, Any]]) -> None:
        self._openai_tools = tools

    def set_tool_executor(self, tool_executor: "ThreadSafeToolExecutor") -> None:
        self._tool_executor = tool_executor

    def run_explore_parallel_blocking(
        self,
        tasks: List[ExploreTask],
    ) -> List[ExploreTaskResult]:
        """Run up to MAX_PARALLEL_EXPLORE explore jobs; blocks until all finish."""
        if not tasks:
            return []
        if not self._tool_executor:
            return [
                ExploreTaskResult(
                    task_id=t.task_id,
                    summary="Error: subagents unavailable (no tool executor).",
                    ok=False,
                )
                for t in tasks
            ]

        capped = tasks[:MAX_PARALLEL_EXPLORE]
        if len(tasks) > MAX_PARALLEL_EXPLORE:
            logger.warning(
                "Capping parallel explore subagents from %s to %s",
                len(tasks),
                MAX_PARALLEL_EXPLORE,
            )

        results: Dict[str, ExploreTaskResult] = {}
        pending = len(capped)
        loop = QEventLoop()

        def on_one_done(result: ExploreTaskResult) -> None:
            nonlocal pending
            results[result.task_id] = result
            pending -= 1
            if pending <= 0:
                loop.quit()

        threads: List[QThread] = []
        for task in capped:
            thread = QThread(self)
            worker = ExploreSubagentWorker(
                task,
                provider_id=self._provider_id,
                model=self._model,
                openai_tools=self._openai_tools,
                tool_executor=self._tool_executor,
            )
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.finished.connect(on_one_done)
            worker.finished.connect(thread.quit)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            threads.append(thread)
            thread.start()

        loop.exec()
        return [results.get(t.task_id, ExploreTaskResult(t.task_id, "Error: no result.", False)) for t in capped]

    def format_subagent_results(self, results: List[ExploreTaskResult]) -> str:
        parts: List[str] = []
        for r in results:
            status = "ok" if r.ok else "failed"
            parts.append(f"### Subagent `{r.task_id}` ({status})\n{r.summary}")
        return "\n\n".join(parts)

    def run_subagent_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle datapyn_subagent from the tool dispatcher (may run on main thread).

        Supports one or more tasks in a single call.
        """
        raw_tasks = arguments.get("tasks")
        if raw_tasks and isinstance(raw_tasks, list):
            explore_tasks = []
            for i, item in enumerate(raw_tasks[:MAX_PARALLEL_EXPLORE]):
                if not isinstance(item, dict):
                    continue
                tid = str(item.get("task_id") or f"explore-{i + 1}")
                instr = str(item.get("instruction") or item.get("task") or "").strip()
                if not instr:
                    continue
                explore_tasks.append(
                    ExploreTask(
                        task_id=tid,
                        instruction=instr,
                        context=str(item.get("context") or ""),
                    )
                )
        else:
            instr = str(arguments.get("instruction") or arguments.get("task") or "").strip()
            if not instr:
                return {"error": "instruction or tasks[] is required for datapyn_subagent"}
            explore_tasks = [
                ExploreTask(
                    task_id=str(arguments.get("task_id") or f"explore-{uuid.uuid4().hex[:8]}"),
                    instruction=instr,
                    context=str(arguments.get("context") or ""),
                )
            ]

        if not explore_tasks:
            return {"error": "No valid subagent tasks."}

        results = self.run_explore_parallel_blocking(explore_tasks)
        text = self.format_subagent_results(results)
        return {"content": [{"type": "text", "text": text}]}

    def execute_readonly_overflow(
        self,
        calls: List[Tuple[str, Dict[str, Any], str]],
    ) -> List[Tuple[str, str, str]]:
        """
        Execute read-only tools that exceeded the per-round limit (tool-only, no LLM).

        Returns (name, result_text, tool_call_id) in the same order as *calls*.
        """
        if not calls or not self._tool_executor:
            return []
        out: List[Tuple[str, str, str]] = []
        for name, args, tc_id in calls:
            try:
                text = self._tool_executor.execute(name, args or {})
            except Exception as exc:
                text = f"Error: {exc}"
            out.append((name, text, tc_id))
        return out
