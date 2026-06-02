"""Tests for Pynia parallel explore subagents."""

from unittest.mock import MagicMock

import pytest

from src.services.pynia.agent_loop_policy import (
    MAX_READ_ONLY_PER_ROUND,
    MAX_SUBAGENTS_PER_ROUND,
    prepare_tool_calls,
    was_duplicate_skip,
)
from src.services.pynia.subagents.classifier import (
    EXPLORE_SUBAGENT_TOOLS,
    READ_ONLY_TOOLS,
    filter_openai_tools,
    is_read_only_tool,
)
from src.services.pynia.subagents.orchestrator import SubagentOrchestrator
from src.services.pynia.subagents.types import ExploreTask
from src.services.pynia.tool_round_executor import process_tool_round


def test_read_only_includes_query():
    assert "datapyn_query" in READ_ONLY_TOOLS
    assert is_read_only_tool("datapyn_query")


def test_filter_openai_tools_explore_subset():
    tools = [
        {"type": "function", "function": {"name": "datapyn_edit", "parameters": {}}},
        {"type": "function", "function": {"name": "datapyn_inspect", "parameters": {}}},
    ]
    filtered = filter_openai_tools(tools, EXPLORE_SUBAGENT_TOOLS)
    assert len(filtered) == 1
    assert filtered[0]["function"]["name"] == "datapyn_inspect"


def test_prepare_separate_subagent_limit():
    seen: set[str] = set()
    calls = [
        ("datapyn_subagent", {"instruction": "a"}, "s1"),
        ("datapyn_subagent", {"instruction": "b"}, "s2"),
        ("datapyn_subagent", {"instruction": "c"}, "s3"),
        ("datapyn_subagent", {"instruction": "d"}, "s4"),
    ]
    prepared = prepare_tool_calls(calls, seen_keys=seen, max_subagents=MAX_SUBAGENTS_PER_ROUND)
    assert sum(1 for p in prepared if p[3]) == MAX_SUBAGENTS_PER_ROUND


def test_prepare_read_only_higher_than_mutating():
    seen: set[str] = set()
    calls = [
        *((
            "datapyn_inspect",
            {"kind": "block", "block_name": str(i)},
            f"i{i}",
        )
        for i in range(MAX_READ_ONLY_PER_ROUND + 2)),
        ("datapyn_edit", {"operation": "replace", "content": "x"}, "d"),
        ("datapyn_edit", {"operation": "replace", "content": "y"}, "e"),
        ("datapyn_edit", {"operation": "replace", "content": "z"}, "f"),
    ]
    prepared = prepare_tool_calls(calls, seen_keys=seen)
    ro_run = sum(1 for n, _, _, run in prepared if run and is_read_only_tool(n))
    mut_run = sum(1 for n, _, _, run in prepared if run and n == "datapyn_edit")
    assert ro_run == MAX_READ_ONLY_PER_ROUND
    assert mut_run == 2


def test_was_duplicate_skip():
    from src.services.pynia.agent_loop_policy import tool_call_key

    seen = {tool_call_key("datapyn_snapshot", {"action": "context"})}
    assert was_duplicate_skip("datapyn_snapshot", {"action": "context"}, seen)
    assert not was_duplicate_skip("datapyn_snapshot", {"action": "blocks"}, seen)


def test_process_tool_round_overflow_executes_readonly():
    executor = MagicMock()
    executor.execute_batch = None
    executor.execute.side_effect = lambda name, args: f"ok:{name}"

    orchestrator = MagicMock()
    orchestrator.execute_readonly_overflow.return_value = [
        ("datapyn_inspect", "overflow-result", "tc-overflow"),
    ]

    from src.services.pynia.agent_loop_policy import tool_call_key

    seen = {tool_call_key("datapyn_inspect", {"kind": "block", "block_name": "1"})}
    prepared = [
        ("datapyn_inspect", {"kind": "block", "block_name": "1"}, "tc1", True),
        ("datapyn_inspect", {"kind": "block", "block_name": "2"}, "tc2", False),
    ]

    outcomes = process_tool_round(
        prepared,
        seen_keys=seen,
        execute_tool=executor.execute,
        tool_executor=executor,
        subagent_orchestrator=orchestrator,
        on_tool_call=lambda *a: None,
        on_tool_result=lambda *a: None,
        is_cancelled=lambda: False,
    )
    orchestrator.execute_readonly_overflow.assert_called_once()
    ids = {tc_id for tc_id, _, _ in outcomes}
    assert "tc1" in ids
    assert "tc-overflow" in ids


def test_orchestrator_format_subagent_results():
    from src.services.pynia.subagents.types import ExploreTaskResult

    orch = SubagentOrchestrator(
        provider_id="openai",
        model="gpt-4o",
        openai_tools=[],
        tool_executor=None,
    )
    text = orch.format_subagent_results(
        [ExploreTaskResult(task_id="t1", summary="found schema", ok=True)]
    )
    assert "t1" in text
    assert "found schema" in text
