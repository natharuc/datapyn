"""Tests for Pynia agent tool-loop guards."""

from src.services.pynia.agent_loop_policy import (
    prepare_tool_calls,
    skipped_tool_message,
    tool_call_key,
    truncate_tool_result,
)


def test_tool_call_key_stable():
    k1 = tool_call_key("datapyn_inspect", {"kind": "block", "block_name": "a"})
    k2 = tool_call_key("datapyn_inspect", {"block_name": "a", "kind": "block"})
    assert k1 == k2


def test_prepare_dedupes_same_call():
    seen: set[str] = set()
    calls = [
        ("datapyn_inspect", {"kind": "block", "block_name": "b3", "detail": "code"}, "id1"),
        ("datapyn_inspect", {"kind": "block", "block_name": "b3", "detail": "code"}, "id2"),
    ]
    prepared = prepare_tool_calls(calls, seen_keys=seen)
    assert prepared[0][3] is True
    assert prepared[1][3] is False


def test_prepare_limits_read_only_per_round():
    seen: set[str] = set()
    calls = [
        ("datapyn_snapshot", {"action": "context"}, "a"),
        ("datapyn_inspect", {"kind": "block", "block_name": "1"}, "b"),
        ("datapyn_inspect", {"kind": "block", "block_name": "2"}, "c"),
        ("datapyn_inspect", {"kind": "block", "block_name": "3"}, "d"),
        ("datapyn_inspect", {"kind": "block", "block_name": "4"}, "e"),
        ("datapyn_inspect", {"kind": "block", "block_name": "5"}, "f"),
        ("datapyn_inspect", {"kind": "block", "block_name": "6"}, "g"),
    ]
    prepared = prepare_tool_calls(calls, seen_keys=seen, max_read_only=5)
    assert sum(1 for p in prepared if p[3]) == 5
    assert prepared[5][3] is False
    msg = skipped_tool_message(prepared[5][0], prepared[5][1], seen)
    assert "read-only" in msg.lower() or "skipped" in msg.lower()


def test_truncate_tool_result():
    long = "x" * 10_000
    out = truncate_tool_result(long, max_chars=500)
    assert len(out) <= 500
    assert "Truncated" in out
