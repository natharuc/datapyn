"""Explore subagent routing heuristics."""

from src.services.pynia.agent_loop_policy import (
    FORCE_ANSWER_AFTER_ROUND,
    should_offer_tools,
)
from src.services.pynia.subagents.classifier import (
    suggest_explore_tasks,
    try_parse_single_tool_call,
)


def test_try_parse_single_tool_snapshot_schema():
    name, args = try_parse_single_tool_call("datapyn_snapshot action=schema")
    assert name == "datapyn_snapshot"
    assert args.get("action") == "schema"


def test_try_parse_inspect_block():
    parsed = try_parse_single_tool_call("inspect block block4 structure")
    assert parsed is not None
    name, args = parsed
    assert name == "datapyn_inspect"
    assert args["block_name"] == "block4"


def test_suggest_explore_tasks():
    tasks = suggest_explore_tasks("show schema and all blocks", connection_name="db")
    assert len(tasks) >= 2
    assert any(t["task_id"] == "schema" for t in tasks)


def test_should_offer_tools_stops_after_force_round():
    # Tools are offered up to (but not including) the force-answer round, so
    # the model gets read → act → verify before being made to answer.
    assert should_offer_tools(FORCE_ANSWER_AFTER_ROUND - 1) is True
    assert should_offer_tools(FORCE_ANSWER_AFTER_ROUND) is False
    assert should_offer_tools(0) is True
