"""Copilot SDK custom tools must emit tool_result for the chat UI."""

from src.services.copilot.copilot_client_sdk import CopilotWorker


def test_emit_tool_result_once_dedupes():
    worker = CopilotWorker(tool_executor=None)
    worker._finished_tool_keys = set()
    emitted = []

    def capture(name, text, cid):
        emitted.append((name, text, cid))

    worker.tool_result.connect(capture)
    worker._emit_tool_result_once("datapyn_inspect", "ok", "call-1")
    worker._emit_tool_result_once("datapyn_inspect", "ok", "call-1")
    assert len(emitted) == 1


def test_pop_pending_call_id_matches_name():
    worker = CopilotWorker(tool_executor=None)
    worker._pending_tool_ids = [("id-a", "datapyn_snapshot"), ("id-b", "datapyn_inspect")]
    assert worker._pop_pending_call_id("datapyn_snapshot", "") == "id-a"
    assert worker._pop_pending_call_id("datapyn_inspect", "") == "id-b"
