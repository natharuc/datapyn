"""Opt-in cache writes and restart restore through the shipped stdio broker."""

import pytest

from test_runtime import Client


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "preview"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "preview"))
    monkeypatch.setenv("DATAPYN_SNAPSHOT_ROOT", str(tmp_path / "cache"))
    value = Client()
    try:
        yield value, tmp_path
    finally:
        value.close()


def enable(value):
    value.request("snapshot.settings.set", {"settings": {"enabled": True, "restore_on_startup": True, "max_size_mb": 50}})


def test_successful_execution_autosaves_real_parquet_and_recreates_stable_session(client):
    value, tmp_path = client
    enable(value)
    value.session("stable-analysis")
    value.event("namespace.changed", session_id="stable-analysis")
    finished = value.execute("df = pd.DataFrame({'value': [2**60 + 3, 7]})\ndf", session_id="stable-analysis")
    assert finished["status"] == "succeeded"
    saved = value.event("snapshot.saved", session_id="stable-analysis")
    assert saved["saved"] is True
    assert [item["name"] for item in saved["variables"]] == ["df"]
    assert list((tmp_path / "cache").rglob("*.parquet"))
    value.request("session.close", {"session_id": "stable-analysis"})
    value.session("stable-analysis")
    restored = value.event("namespace.changed", session_id="stable-analysis")
    assert restored["restored"] is True
    page = value.request("result.page", {"session_id": "stable-analysis", "result_id": restored["results"][0]["result_id"], "offset": 0, "limit": 10})
    assert page["rows"] == [[str(2**60 + 3)], [7]]


def test_immediate_close_flushes_latest_frame_before_idle_autosave(client):
    value, _ = client
    enable(value)
    value.session("close-flush")
    value.event("namespace.changed", session_id="close-flush")
    value.execute("df = pd.DataFrame({'value': [42]})", session_id="close-flush")
    # Do not wait for snapshot.saved: close must save the latest namespace itself.
    value.request("session.close", {"session_id": "close-flush"})
    value.session("close-flush")
    restored = value.event("namespace.changed", session_id="close-flush")
    assert restored["restored"] is True
    page = value.request("result.page", {"session_id": "close-flush", "result_id": restored["results"][0]["result_id"], "offset": 0, "limit": 10})
    assert page["rows"] == [[42]]


def test_explicit_workspace_flush_saves_each_existing_idle_kernel(client):
    value, _ = client
    enable(value)
    for session_id, amount in (("first", 37), ("second", 42)):
        value.session(session_id)
        value.event("namespace.changed", session_id=session_id)
        value.execute(f"df = pd.DataFrame({{'value': [{amount}]}})", execution_id=session_id, session_id=session_id)
    flushed = value.request("system.flush_workspace")
    assert flushed["flushed"] == 2
    assert {item["session_id"] for item in flushed["sessions"]} == {"first", "second"}
    assert all(item["saved"] for item in flushed["sessions"])
    assert not value.request("system.activity")["busy"]
    for session_id in ("first", "second"):
        snapshot = value.request("snapshot.list", {"session_id": session_id})
        assert [item["name"] for item in snapshot["snapshots"][0]["variables"]] == ["df"]


def test_disabled_snapshots_do_not_write_cache_during_execution_or_close(client):
    value, tmp_path = client
    assert value.request("snapshot.settings.get")["enabled"] is False
    value.session("no-cache")
    value.execute("df = pd.DataFrame({'value': [42]})", session_id="no-cache")
    value.request("session.close", {"session_id": "no-cache"})
    assert not list((tmp_path / "cache").rglob("*.parquet"))
    assert not list((tmp_path / "cache").rglob("current.json"))


def test_import_and_delete_refresh_automatic_cache(client, tmp_path):
    value, _ = client
    enable(value)
    value.session("mutation-cache")
    value.event("namespace.changed", session_id="mutation-cache")
    path = tmp_path / "import.csv"
    path.write_text("amount\n12\n", encoding="utf-8")
    value.request("data.import", {"session_id": "mutation-cache", "path": str(path), "variable_name": "imported"})
    saved = value.event("snapshot.saved", session_id="mutation-cache")
    assert [item["name"] for item in saved["variables"]] == ["imported"]
    value.request("variable.delete", {"session_id": "mutation-cache", "name": "imported"})
    saved = value.event("snapshot.saved", session_id="mutation-cache")
    assert saved["variables"] == []
    assert value.request("snapshot.list", {"session_id": "mutation-cache"})["snapshots"] == []
