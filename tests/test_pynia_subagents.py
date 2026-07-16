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


def test_process_tool_round_overflow_skips_readonly():
    executor = MagicMock()
    executor.execute_batch = None
    executor.execute.side_effect = lambda name, args: f"ok:{name}"

    orchestrator = MagicMock()

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
    orchestrator.execute_readonly_overflow.assert_not_called()
    ids = {tc_id for tc_id, _, _ in outcomes}
    assert "tc1" in ids
    assert "tc2" in ids
    skipped = next(text for tc_id, _, text in outcomes if tc_id == "tc2")
    assert "SKIPPED" in skipped


def _install_hanging_worker(monkeypatch):
    from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
    from src.services.pynia.subagents import orchestrator as orch_mod

    class HangingWorker(QObject):
        finished = pyqtSignal(object)

        def __init__(self, task, *, provider_id, model, openai_tools, tool_executor, parent=None):
            super().__init__(parent)
            self._cancelled = False

        def cancel(self):
            self._cancelled = True

        @pyqtSlot()
        def run(self):
            # Intentionally never emits `finished` — simulates a stalled LLM call.
            return

    monkeypatch.setattr(orch_mod, "ExploreSubagentWorker", HangingWorker)


def test_run_explore_parallel_times_out(qtbot, monkeypatch):
    """A hung subagent must not freeze the turn — the loop bails on timeout."""
    import time

    _install_hanging_worker(monkeypatch)
    orch = SubagentOrchestrator(
        provider_id="openai", model="gpt-4o", openai_tools=[], tool_executor=MagicMock()
    )
    tasks = [ExploreTask(task_id="t1", instruction="x"), ExploreTask(task_id="t2", instruction="y")]

    start = time.monotonic()
    results = orch.run_explore_parallel_blocking(tasks, timeout_ms=300)
    elapsed = time.monotonic() - start

    assert elapsed < 5, "parallel explore should bail quickly, not hang"
    assert len(results) == 2
    assert all(not r.ok for r in results)
    assert all("timed out" in r.summary.lower() for r in results)


def test_run_explore_parallel_cancels(qtbot, monkeypatch):
    """Pressing Stop (is_cancelled) unblocks the wait loop."""
    import time

    _install_hanging_worker(monkeypatch)
    orch = SubagentOrchestrator(
        provider_id="openai", model="gpt-4o", openai_tools=[], tool_executor=MagicMock()
    )
    tasks = [ExploreTask(task_id="t1", instruction="x")]

    start = time.monotonic()
    results = orch.run_explore_parallel_blocking(
        tasks, is_cancelled=lambda: True, timeout_ms=10_000
    )
    elapsed = time.monotonic() - start

    assert elapsed < 5, "cancellation should unblock promptly"
    assert results and results[0].summary == "Cancelled by user."


def test_run_explore_parallel_no_qevent_loop_or_qtimer():
    """Parallel explore must not import or use QEventLoop or QTimer."""
    from pathlib import Path

    src = Path("source/src/services/pynia/subagents/orchestrator.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "QEventLoop" not in line
        assert "QTimer" not in line


def test_should_delegate_matches_portuguese():
    from src.services.pynia.subagents.classifier import should_delegate_to_subagent

    assert should_delegate_to_subagent(
        "me dá uma visão geral de todos os blocos", block_count=10
    )
    assert should_delegate_to_subagent("quais tabelas existem no banco?", block_count=2)


def test_suggest_explore_tasks_portuguese_keywords():
    from src.services.pynia.subagents.classifier import suggest_explore_tasks

    tasks = suggest_explore_tasks("resuma os blocos e as variáveis do banco")
    ids = {t["task_id"] for t in tasks}
    assert "blocks" in ids
    assert "vars" in ids
    assert "schema" in ids


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
