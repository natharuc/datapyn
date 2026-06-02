"""Execute one agent tool round with batching, overflow, and parallel subagents."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from src.services.pynia.agent_loop_policy import (
    is_read_only_tool,
    is_subagent_tool,
    skipped_tool_message,
    truncate_tool_result,
    was_duplicate_skip,
)

if TYPE_CHECKING:
    from src.services.pynia.subagents.orchestrator import SubagentOrchestrator

logger = logging.getLogger(__name__)


def process_tool_round(
    prepared: List[Tuple[str, Dict[str, Any], str, bool]],
    *,
    seen_keys: set[str],
    execute_tool: Callable[[str, Dict[str, Any]], str],
    tool_executor: Any = None,
    subagent_orchestrator: Optional["SubagentOrchestrator"] = None,
    on_tool_call: Callable[[str, dict, str], None],
    on_tool_result: Callable[[str, str, str], None],
    is_cancelled: Callable[[], bool],
) -> List[Tuple[str, str, str]]:
    """
    Run prepared tool calls; return (tool_call_id, name, result_text) for conversation.
    """
    outcomes: List[Tuple[str, str, str]] = []

    to_run_ro: List[Tuple[str, Dict[str, Any], str]] = []
    overflow_ro: List[Tuple[str, Dict[str, Any], str]] = []
    subagent_calls: List[Tuple[str, Dict[str, Any], str]] = []
    sequential: List[Tuple[str, Dict[str, Any], str, bool]] = []

    for name, args, tc_id, should_execute in prepared:
        if is_cancelled():
            return outcomes
        if is_subagent_tool(name):
            if should_execute:
                subagent_calls.append((name, args, tc_id))
            else:
                sequential.append((name, args, tc_id, should_execute))
        elif is_read_only_tool(name) and should_execute:
            to_run_ro.append((name, args, tc_id))
        elif is_read_only_tool(name) and not should_execute:
            if was_duplicate_skip(name, args, seen_keys):
                sequential.append((name, args, tc_id, False))
            else:
                overflow_ro.append((name, args, tc_id))
        else:
            sequential.append((name, args, tc_id, should_execute))

    # Parallel explore subagents (LLM workers on background QThreads)
    if subagent_calls:
        if subagent_orchestrator:
            from src.services.pynia.subagents.types import ExploreTask

            if len(subagent_calls) == 1:
                name, args, tc_id = subagent_calls[0]
                on_tool_call(name, args, tc_id)
                result = truncate_tool_result(
                    _format_orchestrator_result(subagent_orchestrator.run_subagent_tool(args))
                )
                on_tool_result(name, result, tc_id)
                outcomes.append((tc_id, name, result))
            else:
                tasks = []
                for _, args, tc_id in subagent_calls:
                    instr = str(args.get("instruction") or args.get("task") or "").strip()
                    tasks.append(
                        ExploreTask(
                            task_id=tc_id,
                            instruction=instr,
                            context=str(args.get("context") or ""),
                        )
                    )
                for name, args, tc_id in subagent_calls:
                    on_tool_call(name, args, tc_id)
                parallel_results = subagent_orchestrator.run_explore_parallel_blocking(tasks)
                by_id = {r.task_id: r.summary for r in parallel_results}
                for name, args, tc_id in subagent_calls:
                    result = truncate_tool_result(by_id.get(tc_id, "Error: subagent returned no result."))
                    on_tool_result(name, result, tc_id)
                    outcomes.append((tc_id, name, result))
        else:
            for name, args, tc_id in subagent_calls:
                on_tool_call(name, args, tc_id)
                err = "Error: parallel subagents unavailable."
                on_tool_result(name, err, tc_id)
                outcomes.append((tc_id, name, err))

    # Batch read-only tools (single main-thread hop when possible)
    use_batch = (
        len(to_run_ro) > 1
        and tool_executor is not None
        and hasattr(tool_executor, "execute_batch")
    )
    if use_batch:
        for name, args, tc_id in to_run_ro:
            on_tool_call(name, args, tc_id)
        results = tool_executor.execute_batch([(n, a) for n, a, _ in to_run_ro])
        for (name, args, tc_id), result in zip(to_run_ro, results):
            result = truncate_tool_result(result)
            on_tool_result(name, result, tc_id)
            outcomes.append((tc_id, name, result))
    else:
        for name, args, tc_id in to_run_ro:
            if is_cancelled():
                return outcomes
            on_tool_call(name, args, tc_id)
            result = truncate_tool_result(execute_tool(name, args))
            on_tool_result(name, result, tc_id)
            outcomes.append((tc_id, name, result))

    # Overflow read-only (limit skipped) — still execute, tool-only
    if overflow_ro:
        if subagent_orchestrator:
            for name, args, tc_id in overflow_ro:
                on_tool_call(name, args, tc_id)
            overflow_results = subagent_orchestrator.execute_readonly_overflow(overflow_ro)
            for name, result, tc_id in overflow_results:
                result = truncate_tool_result(result)
                on_tool_result(name, result, tc_id)
                outcomes.append((tc_id, name, result))
        else:
            for name, args, tc_id in overflow_ro:
                if is_cancelled():
                    return outcomes
                on_tool_call(name, args, tc_id)
                result = truncate_tool_result(execute_tool(name, args))
                on_tool_result(name, result, tc_id)
                outcomes.append((tc_id, name, result))

    for name, args, tc_id, should_execute in sequential:
        if is_cancelled():
            return outcomes
        on_tool_call(name, args, tc_id)
        if should_execute:
            result = truncate_tool_result(execute_tool(name, args))
        else:
            result = skipped_tool_message(name, args, seen_keys)
        on_tool_result(name, result, tc_id)
        outcomes.append((tc_id, name, result))

    return outcomes


def _format_orchestrator_result(result: Dict[str, Any]) -> str:
    if "error" in result:
        return f"Error: {result['error']}"
    parts = []
    for item in result.get("content", []):
        parts.append(item.get("text", str(item)))
    return "\n".join(parts)
