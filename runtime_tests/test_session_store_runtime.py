"""Persisted private drafts survive a killed broker without executing their code."""

from pathlib import Path

from test_runtime import Client


def test_rpc_patch_ack_survives_broker_kill_and_restore_never_runs_code(tmp_path, monkeypatch):
    root = tmp_path / "preview"
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(root))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(root))
    marker = tmp_path / "must-not-execute.txt"
    code = f"from pathlib import Path\nPath({str(marker)!r}).write_text('execution is forbidden on restore')"
    first = Client()
    try:
        record = {"sessionId": "stable-analysis", "title": "Initial", "document": {"version": "1.0", "blocks": [{"language": "python", "code": code, "block_key": "block-1"}]}}
        saved = first.request("workspace.profiles.save", {"profile_id": "default", "state": {"documents": [record], "activeIndex": 0}})
        patched = first.request("workspace.profiles.patch", {"profile_id": "default", "upserts": [{"sessionId": "stable-analysis", "title": "Acknowledged", "editorViewState": {"block-1": {"cursor": 9}}}], "metadata": {"layout": {"rightPanel": "variables"}}})
        assert patched["revision"] > saved["revision"] and patched["changed_payloads"] == 0
        first.process.kill()
        first.process.wait(timeout=10)
    finally:
        first.close()
    reopened = Client()
    try:
        restored = reopened.request("workspace.profiles.state")
        document = restored["state"]["documents"][0]
        assert restored["revision"] == patched["revision"] and restored["storage"] == "sqlite"
        assert document["sessionId"] == "stable-analysis" and document["title"] == "Acknowledged"
        assert document["document"]["blocks"][0]["code"] == code
        assert document["editorViewState"] == {"block-1": {"cursor": 9}}
        assert restored["state"]["layout"] == {"rightPanel": "variables"}
        activity = reopened.request("system.activity")
        assert not activity["busy"] and activity["executions"] == 0
        assert not marker.exists()
        assert not any(message.get("event") in {"execution.started", "execution.finished", "session.ready"} for message in reopened.all_messages)
    finally:
        reopened.close()
