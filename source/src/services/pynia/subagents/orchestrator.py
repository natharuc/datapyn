"""Run explore subagents in parallel on background QThreads."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread

from src.utils.qt_threading import qthread_is_running

from src.services.pynia.subagents.explore_worker import ExploreSubagentWorker
from src.services.pynia.subagents.types import ExploreTask, ExploreTaskResult

if TYPE_CHECKING:
    from src.services.copilot.copilot_client_sdk import ThreadSafeToolExecutor

logger = logging.getLogger(__name__)

MAX_PARALLEL_EXPLORE = 4
# Safety net for parallel explore. A hung subagent (e.g. a stalled LLM
# stream) must never freeze the whole chat turn — we bail with partial results.
EXPLORE_PARALLEL_TIMEOUT_MS = 120_000
EXPLORE_CANCEL_POLL_MS = 200


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
        self._parallel_lock = threading.Lock()
        self._active_workers: List[ExploreSubagentWorker] = []
        self._active_threads: List[QThread] = []

    def set_model(self, model: str) -> None:
        self._model = model

    def set_provider(self, provider_id: str) -> None:
        self._provider_id = provider_id

    def set_openai_tools(self, tools: List[Dict[str, Any]]) -> None:
        self._openai_tools = tools

    def set_tool_executor(self, tool_executor: "ThreadSafeToolExecutor") -> None:
        self._tool_executor = tool_executor

    def cancel_active_explore(self) -> None:
        """Stop in-flight explore workers (e.g. user cancelled the chat turn)."""
        for worker in self._active_workers:
            try:
                worker.cancel()
            except RuntimeError:
                pass
        for thread in self._active_threads:
            try:
                if qthread_is_running(thread):
                    thread.quit()
                    if not thread.wait(300):
                        logger.warning(
                            "Explore QThread did not stop after quit(); terminating as last resort"
                        )
                        thread.terminate()
                        thread.wait(300)
            except RuntimeError:
                pass
        self._active_workers.clear()
        self._active_threads.clear()

    def _stop_threads(self, threads: List[QThread]) -> None:
        for thread in threads:
            try:
                if thread.isRunning():
                    thread.quit()
                    if not thread.wait(500):
                        logger.warning(
                            "Explore QThread did not stop after quit(); terminating as last resort"
                        )
                        thread.terminate()
                        thread.wait(500)
            except RuntimeError:
                pass
            try:
                thread.deleteLater()
            except RuntimeError:
                pass

    def run_explore_parallel_blocking(
        self,
        tasks: List[ExploreTask],
        is_cancelled: Optional[Callable[[], bool]] = None,
        timeout_ms: int = EXPLORE_PARALLEL_TIMEOUT_MS,
    ) -> List[ExploreTaskResult]:
        """Run up to MAX_PARALLEL_EXPLORE explore jobs; blocks until all finish.

        Uses threading.Event with a safety timeout and (optionally) a
        cancellation poll so a hung subagent can never freeze the chat turn.
        """
        if not tasks:
            return []
        with self._parallel_lock:
            return self._run_explore_parallel_blocking_locked(
                tasks,
                is_cancelled=is_cancelled,
                timeout_ms=timeout_ms,
            )

    def _run_explore_parallel_blocking_locked(
        self,
        tasks: List[ExploreTask],
        is_cancelled: Optional[Callable[[], bool]] = None,
        timeout_ms: int = EXPLORE_PARALLEL_TIMEOUT_MS,
    ) -> List[ExploreTaskResult]:
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
        workers: List[ExploreSubagentWorker] = []
        timed_out = False
        cancelled = False
        done_event = threading.Event()
        done_lock = threading.Lock()
        remaining = len(capped)

        def on_one_done(result: ExploreTaskResult) -> None:
            results[result.task_id] = result
            with done_lock:
                nonlocal remaining
                remaining -= 1
                if remaining <= 0:
                    done_event.set()

        threads: List[QThread] = []
        self.cancel_active_explore()
        for task in capped:
            # Parentless thread — this runs on the token worker thread, not the UI thread.
            thread = QThread()
            thread.setObjectName(f"PyniaExplore-{task.task_id}")
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
            workers.append(worker)
            threads.append(thread)
            thread.start()

        self._active_workers = workers
        self._active_threads = threads

        # Block with threading.Event — no Qt event loop on this worker thread.
        deadline = time.monotonic() + timeout_ms / 1000.0
        poll_s = EXPLORE_CANCEL_POLL_MS / 1000.0

        while not done_event.is_set():
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                timed_out = True
                logger.warning(
                    "Parallel explore timed out after %sms; cancelling workers", timeout_ms
                )
                for w in workers:
                    w.cancel()
                break
            wait_s = min(poll_s, remaining_s)
            if done_event.wait(timeout=wait_s):
                break
            if is_cancelled is not None and is_cancelled():
                cancelled = True
                for w in workers:
                    w.cancel()
                break

        # Wind down any worker that didn't finish on its own (timeout/cancel).
        for w in workers:
            try:
                w.cancel()
            except RuntimeError:
                pass
        self._stop_threads(threads)
        self._active_workers.clear()
        self._active_threads.clear()

        if timed_out:
            fallback = "Error: subagent timed out before returning."
        elif cancelled:
            fallback = "Cancelled by user."
        else:
            fallback = "Error: no result."
        return [results.get(t.task_id, ExploreTaskResult(t.task_id, fallback, False)) for t in capped]

    def format_subagent_results(self, results: List[ExploreTaskResult]) -> str:
        parts: List[str] = []
        for r in results:
            status = "ok" if r.ok else "failed"
            section = f"### Subagent `{r.task_id}` ({status})\n{r.summary}"
            if r.tool_trace:
                tools_used = ", ".join(
                    f"{t.get('tool', '?')}" for t in r.tool_trace[:6]
                )
                section += f"\n\n_Tools used: {tools_used}_"
            parts.append(section)
        return "\n\n".join(parts)

    def run_subagent_tool(
        self,
        arguments: Dict[str, Any],
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Handle datapyn_subagent from the tool dispatcher (may run on main thread).

        Supports one or more tasks in a single call.
        """
        from src.services.pynia.subagents.classifier import try_parse_single_tool_call
        from src.services.pynia.subagents.explore_worker import run_tool_only_explore

        instr = str(arguments.get("instruction") or arguments.get("task") or "").strip()
        if instr and not arguments.get("tasks"):
            single = try_parse_single_tool_call(instr)
            if single and self._tool_executor:
                name, args = single
                text = run_tool_only_explore(name, args, self._tool_executor)
                tid = str(arguments.get("task_id") or "explore-fast")
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": self.format_subagent_results(
                                [
                                    ExploreTaskResult(
                                        task_id=tid,
                                        summary=text,
                                        ok=True,
                                        tool_trace=[{"tool": name, "args": args}],
                                    )
                                ]
                            ),
                        }
                    ]
                }

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

        results = self.run_explore_parallel_blocking(explore_tasks, is_cancelled=is_cancelled)
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
