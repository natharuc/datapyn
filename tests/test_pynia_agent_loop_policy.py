"""Tests for Pynia agent tool-loop guards."""

from src.services.pynia.agent_loop_policy import (
    MAX_SDK_MUTATING_TOOLS_PER_TURN,
    MAX_SDK_READ_TOOLS_PER_TURN,
    evaluate_sdk_budget,
    evaluate_tool_call,
    invalidate_block_reads,
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


def test_prepare_caps_unanchored_inspects_per_block():
    """Unanchored re-reads (structure / whole code) are capped at 2 per block."""
    seen: set[str] = set()
    block_counts: dict[str, int] = {}
    calls = [
        ("datapyn_inspect", {"kind": "block", "block_name": "block4", "detail": "structure"}, "a"),
        ("datapyn_inspect", {"kind": "block", "block_name": "block4", "detail": "code"}, "b"),
        ("datapyn_inspect", {"kind": "block", "block_name": "block4", "detail": "result"}, "c"),
    ]
    prepared = prepare_tool_calls(calls, seen_keys=seen, block_inspect_counts=block_counts)
    assert sum(1 for p in prepared if p[3]) == 2
    assert prepared[2][3] is False
    msg = skipped_tool_message(prepared[2][0], prepared[2][1], seen, block_counts)
    assert "block4" in msg


def test_prepare_allows_distinct_section_reads():
    """Anchored section reads (around=/line range) of a big block are not capped."""
    seen: set[str] = set()
    block_counts: dict[str, int] = {}
    calls = [
        ("datapyn_inspect", {"kind": "block", "block_name": "block3", "detail": "structure"}, "a"),
        ("datapyn_inspect", {"kind": "block", "block_name": "block3", "around": "renderGroupTable"}, "b"),
        ("datapyn_inspect", {"kind": "block", "block_name": "block3", "around": "renderSidePanel"}, "c"),
        ("datapyn_inspect", {"kind": "block", "block_name": "block3", "start_line": 400, "end_line": 480}, "d"),
    ]
    prepared = prepare_tool_calls(calls, seen_keys=seen, block_inspect_counts=block_counts)
    # structure (1 unanchored, under cap) + 3 distinct section reads all run.
    assert sum(1 for p in prepared if p[3]) == 4
    # An identical anchored read is still deduped.
    dup = prepare_tool_calls(
        [("datapyn_inspect", {"kind": "block", "block_name": "block3", "around": "renderGroupTable"}, "e")],
        seen_keys=seen,
        block_inspect_counts=block_counts,
    )
    assert dup[0][3] is False


def test_evaluate_tool_call_guard():
    seen: set[str] = set()
    block_counts: dict[str, int] = {}
    args = {"kind": "block", "block_name": "b1", "detail": "code"}
    ok, _ = evaluate_tool_call("datapyn_inspect", args, seen_keys=seen, block_inspect_counts=block_counts)
    assert ok is True
    ok2, skip = evaluate_tool_call("datapyn_inspect", args, seen_keys=seen, block_inspect_counts=block_counts)
    assert ok2 is False
    assert "DUPLICATE" in skip


def test_invalidate_block_reads_allows_reinspect_after_edit():
    """Editing a block must clear the read-dedupe so the model can verify."""
    seen: set[str] = set()
    block_counts: dict[str, int] = {}
    inspect_args = {"kind": "block", "block_name": "vendas", "detail": "code"}

    ok, _ = evaluate_tool_call(
        "datapyn_inspect", inspect_args, seen_keys=seen, block_inspect_counts=block_counts
    )
    assert ok is True

    invalidate_block_reads(
        "datapyn_edit",
        {"operation": "replace", "block_name": "vendas", "content": "SELECT 2"},
        seen_keys=seen,
        block_inspect_counts=block_counts,
    )

    ok2, _ = evaluate_tool_call(
        "datapyn_inspect", inspect_args, seen_keys=seen, block_inspect_counts=block_counts
    )
    assert ok2 is True


def test_invalidate_block_reads_keeps_other_blocks_deduped():
    seen: set[str] = set()
    block_counts: dict[str, int] = {}
    other_args = {"kind": "block", "block_name": "outro", "detail": "code"}
    evaluate_tool_call(
        "datapyn_inspect", other_args, seen_keys=seen, block_inspect_counts=block_counts
    )

    invalidate_block_reads(
        "datapyn_edit",
        {"operation": "replace", "block_name": "vendas", "content": "x"},
        seen_keys=seen,
        block_inspect_counts=block_counts,
    )

    ok, msg = evaluate_tool_call(
        "datapyn_inspect", other_args, seen_keys=seen, block_inspect_counts=block_counts
    )
    assert ok is False
    assert "DUPLICATE" in msg


def test_invalidate_block_reads_ignores_non_mutating_tools():
    seen: set[str] = set()
    args = {"kind": "block", "block_name": "vendas"}
    evaluate_tool_call("datapyn_inspect", args, seen_keys=seen, block_inspect_counts={})
    invalidate_block_reads("datapyn_snapshot", {"action": "blocks"}, seen_keys=seen)
    ok, _ = evaluate_tool_call("datapyn_inspect", args, seen_keys=seen, block_inspect_counts={})
    assert ok is False


def test_sdk_budget_reads_exhausted_still_allows_edits():
    """The incident: mapping a 2412-line block burned the whole shared budget
    on reads and the user's edits were silently skipped. Reads exhausting
    their lane must NOT block mutations."""
    reads = MAX_SDK_READ_TOOLS_PER_TURN

    ok_read, msg_read = evaluate_sdk_budget(
        "datapyn_inspect", read_executions=reads, mutating_executions=0
    )
    assert ok_read is False
    assert "EDIT" in msg_read or "edit" in msg_read

    ok_edit, _ = evaluate_sdk_budget(
        "datapyn_edit", read_executions=reads, mutating_executions=0
    )
    assert ok_edit is True

    ok_run, _ = evaluate_sdk_budget(
        "datapyn_run", read_executions=reads, mutating_executions=0
    )
    assert ok_run is True


def test_sdk_budget_blocked_mutation_is_unmistakable():
    """A refused edit must scream NOT APPLIED so the model can't narrate it
    as done."""
    ok, msg = evaluate_sdk_budget(
        "datapyn_edit",
        read_executions=0,
        mutating_executions=MAX_SDK_MUTATING_TOOLS_PER_TURN,
    )
    assert ok is False
    assert "NOT APPLIED" in msg
    assert "NOT modified" in msg


def test_sdk_budget_within_limits_allows_everything():
    for name in ("datapyn_inspect", "datapyn_snapshot", "datapyn_edit", "datapyn_run"):
        ok, msg = evaluate_sdk_budget(name, read_executions=0, mutating_executions=0)
        assert ok is True
        assert msg == ""


def test_truncate_tool_result():
    long = "x" * 10_000
    out = truncate_tool_result(long, max_chars=500)
    assert len(out) <= 500
    assert "Truncated" in out
