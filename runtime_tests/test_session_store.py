"""Private storage migration, incremental writes and crash recovery on real SQLite."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from datapyn_runtime import session_store as storage


def record(identifier="session-1", code="SELECT 1"):
    return {"sessionId": identifier, "title": identifier, "filePath": "C:/analysis.dpw", "modified": True,
            "editorViewState": {"block": "block-1", "cursor": {"line": 8, "column": 3}},
            "extra_header": {"unknown": [1, 2]}, "document": {"version": "1.0", "blocks": [{"language": "sql", "code": code}],
            "notification_config": {"title": "{{rows}}"}, "unknown_public": {"roundtrip": True}}}


def state(*documents):
    return {"documents": list(documents or [record()]), "activeIndex": 0,
            "preferences": {"editorFontSize": 13}, "shortcuts": {"run": "F9"},
            "layout": {"docking": {"panels": ["editor", "results"]}, "unknown": 17}, "unknown": {"private": True}}


@pytest.fixture
def store(tmp_path):
    value = storage.SessionStore(tmp_path)
    yield value
    value.close()


def test_migration_is_idempotent_preserves_original_json_and_assigns_stable_ids(tmp_path):
    original = state(record(), record("session-2"))
    del original["documents"][0]["sessionId"]
    original["saved_at"] = 123
    source = tmp_path / storage.LEGACY_NAME
    raw = json.dumps(original, ensure_ascii=False, indent=2).encode()
    source.write_bytes(raw)
    first = storage.SessionStore(tmp_path)
    migrated = first.load()
    identifier = migrated["documents"][0]["sessionId"]
    assert len(identifier) == 32
    assert migrated["documents"][1]["sessionId"] == "session-2"
    assert migrated["unknown"] == original["unknown"] and migrated["layout"] == original["layout"]
    assert migrated["documents"][0]["document"] == original["documents"][0]["document"]
    assert source.read_bytes() == raw
    first.patch({"upserts": [{"sessionId": identifier, "title": "Newer SQLite title"}]})
    revision = first.info()["revision"]
    first.close()
    source.write_text("broken old JSON after successful migration")
    reopened = storage.SessionStore(tmp_path)
    assert reopened.load()["documents"][0]["title"] == "Newer SQLite title"
    assert reopened.info()["revision"] == revision
    reopened.close()


def test_header_only_changes_do_not_rewrite_document_payload_or_other_records(store):
    store.save(state(record(), record("session-2")))
    rows = dict(store.connection.execute("SELECT session_id,updated_revision FROM documents"))
    result = store.patch({"upserts": [{"sessionId": "session-1", "title": "Renamed", "editorViewState": {"cursor": 23}, "remove_header": ["filePath"]}], "metadata": {"activeIndex": 1}})
    assert result["changed_payloads"] == 0 and result["changed_headers"] == 1 and result["changed_documents"] == 1
    assert dict(store.connection.execute("SELECT session_id,updated_revision FROM documents")) == rows
    first = store.load()["documents"][0]
    assert first["title"] == "Renamed" and first["editorViewState"] == {"cursor": 23} and "filePath" not in first
    assert first["extra_header"] == {"unknown": [1, 2]} and first["document"] == record()["document"]
    assert store.load()["activeIndex"] == 1


def test_migration_retains_desktop_identity_and_existing_private_parquet_snapshot(tmp_path, monkeypatch):
    import pandas as pd
    import polars as pl
    from datapyn_runtime import variable_snapshot as snapshot
    from datapyn_runtime.kernel import ResultStore

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(workspace))
    monkeypatch.setenv("DATAPYN_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    legacy_id = "original-private-session"
    original = state(record(legacy_id, "raise RuntimeError('saved code must never run')"))
    document = original["documents"][0]
    del document["sessionId"]
    document["document"]["desktop"] = {"session_id": legacy_id}
    raw = json.dumps(original).encode()
    source = workspace / storage.LEGACY_NAME
    source.write_bytes(raw)
    snapshot.settings_set({"settings": {"enabled": True}})
    frames = ResultStore(pd, pl)
    expected = pd.DataFrame({"value": [123, 456]})
    assert snapshot.save({"session_id": legacy_id}, {"df": expected}, frames)["saved"]

    migrated = storage.SessionStore(workspace)
    restored_id = migrated.load()["documents"][0]["sessionId"]
    assert restored_id == legacy_id
    namespace = {}
    response = snapshot.restore({"session_id": restored_id}, namespace, frames)
    assert response["restored"] is True
    pd.testing.assert_frame_equal(namespace["df"], expected)
    assert source.read_bytes() == raw
    migrated.close()
    reopened = storage.SessionStore(workspace)
    assert reopened.load()["documents"][0]["sessionId"] == legacy_id
    reopened.close()


def test_identity_precedence_and_collision_fallback_are_stable():
    explicit = record("explicit-session")
    explicit["document"]["desktop"] = {"session_id": "ignored-desktop-id"}
    inherited = record("removed")
    del inherited["sessionId"]
    inherited["document"]["desktop"] = {"session_id": "desktop-session"}
    colliding = record("removed")
    del colliding["sessionId"]
    colliding["document"]["desktop"] = {"session_id": "explicit-session"}
    invalid = record("removed")
    del invalid["sessionId"]
    invalid["document"]["desktop"] = {"session_id": "../invalid"}
    legacy = state(inherited, colliding, explicit, invalid)
    documents, _ = storage.normalize_state(legacy, "stable-seed")
    identifiers = [item["sessionId"] for item in documents]
    assert identifiers[0] == "desktop-session" and identifiers[2] == "explicit-session"
    assert len(set(identifiers)) == 4 and all(storage.IDENTIFIER.fullmatch(item) for item in identifiers)
    repeated, _ = storage.normalize_state(legacy, "stable-seed", identifiers)
    assert [item["sessionId"] for item in repeated] == identifiers


def test_partial_document_edit_preserves_other_payload_rows_and_full_save_is_noop(store):
    original = state(record(), record("session-2"))
    saved = store.save(original)
    rows = dict(store.connection.execute("SELECT session_id,updated_revision FROM documents"))
    unchanged = store.save(original)
    assert unchanged["revision"] == saved["revision"] and unchanged["changed_payloads"] == 0
    changed = record(code="SELECT 2")
    result = store.patch({"upserts": [changed]})
    after = dict(store.connection.execute("SELECT session_id,updated_revision FROM documents"))
    assert result["changed_payloads"] == 1 and result["changed_headers"] == 0
    assert after["session-1"] > rows["session-1"] and after["session-2"] == rows["session-2"]
    assert store.load()["documents"][1] == original["documents"][1]


def test_remove_upsert_order_and_metadata_commit_as_one_state(store):
    store.save(state(record(), record("session-2")))
    result = store.patch({"upserts": [record("session-3")], "removes": ["session-1"], "order": ["session-3", "session-2"],
                          "metadata": {"activeIndex": 1, "preferences": {"editorFontSize": 20}}, "remove_metadata": ["unknown"]})
    restored = store.load()
    assert [document["sessionId"] for document in restored["documents"]] == ["session-3", "session-2"]
    assert restored["preferences"]["editorFontSize"] == 20 and restored["activeIndex"] == 1
    assert "unknown" not in restored and restored["layout"] == state()["layout"]
    assert result["removed_documents"] == 1 and result["order_changed"]


def test_failed_transaction_rolls_back_payload_headers_order_and_metadata(store, monkeypatch):
    store.save(state(record(), record("session-2")))
    previous = store.load()
    revision = store.info()["revision"]
    original = store._put
    def fail_after_write(*args):
        original(*args)
        raise sqlite3.OperationalError("simulated disk full")
    monkeypatch.setattr(store, "_put", fail_after_write)
    with pytest.raises(sqlite3.OperationalError):
        store.patch({"removes": ["session-2"], "upserts": [record(code="SELECT 'should rollback'")], "metadata": {"activeIndex": 0}})
    assert store.load() == previous and store.info()["revision"] == revision


@pytest.mark.parametrize("patch", [
    {"order": ["session-1", "session-1"]}, {"upserts": [{"sessionId": "unknown", "title": "No payload"}]},
    {"upserts": [record(), record()]}, {"upserts": [record()], "removes": ["session-1"]},
    {"upserts": [{"sessionId": "../escape", "document": {}}]}, {"metadata": {"activeIndex": True}},
    {"metadata": {"layout": []}}, {"metadata": {"documents": []}},
    {"remove_metadata": ["activeIndex"]},
    {"metadata": {"unknown": 2}, "remove_metadata": ["unknown"]},
    {"upserts": [{"sessionId": "session-1", "title": "Set", "remove_header": ["title"]}]},
])
def test_invalid_patch_preserves_existing_state(store, patch):
    store.save(state())
    previous = store.load()
    with pytest.raises(ValueError):
        store.patch(patch)
    assert store.load() == previous


def test_total_size_is_validated_transactionally_and_nan_is_rejected(store, monkeypatch):
    store.save(state())
    previous = store.load()
    monkeypatch.setattr(storage, "MAX_STATE_BYTES", 4096)
    with pytest.raises(ValueError, match="exceeds"):
        store.patch({"upserts": [record("a", "x" * 3000), record("b", "y" * 3000)]})
    with pytest.raises(ValueError, match="finite JSON"):
        store.patch({"metadata": {"unknown": float("nan")}})
    assert store.load() == previous


def test_expected_revision_conflicts_preserve_last_acknowledged_state(store):
    saved = store.save(state())
    store.patch({"metadata": {"unknown": "new"}, "expected_revision": saved["revision"]})
    with pytest.raises(ValueError, match="changed since"):
        store.patch({"metadata": {"unknown": "stale"}, "expected_revision": saved["revision"]})
    assert store.load()["unknown"] == "new"


@pytest.mark.parametrize("version,expected", [((3, 44, 5), False), ((3, 44, 6), True), ((3, 45, 1), False),
    ((3, 49, 9), False), ((3, 50, 6), False), ((3, 50, 7), True), ((3, 51, 2), False), ((3, 51, 3), True), ((3, 52, 0), True)])
def test_wal_reset_version_guard(version, expected):
    assert storage.safe_wal_version(version) is expected


def test_journal_fallback_and_durable_synchronous_are_explicit(store):
    mode = store.connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == ("wal" if storage.safe_wal_version() else "delete")
    assert store.connection.execute("PRAGMA synchronous").fetchone()[0] == (2 if mode == "wal" else 3)
    assert store.checkpoint()["busy"] is False


@pytest.mark.parametrize("content", [b"", b"not SQLite", b"SQLite format 3\0" + b"broken" * 50])
def test_corrupt_database_never_replaces_itself_or_uses_older_json(tmp_path, content):
    path = tmp_path / storage.DATABASE_NAME
    path.write_bytes(content)
    source = tmp_path / storage.LEGACY_NAME
    source.write_text(json.dumps(state()))
    with pytest.raises(storage.SessionStoreError):
        storage.SessionStore(tmp_path)
    assert path.read_bytes() == content and json.loads(source.read_text()) == state()


def test_invalid_legacy_json_never_initializes_an_empty_database(tmp_path):
    source = tmp_path / storage.LEGACY_NAME
    source.write_bytes(b'{"documents":broken')
    with pytest.raises(storage.SessionStoreError):
        storage.SessionStore(tmp_path)
    assert not (tmp_path / storage.DATABASE_NAME).exists() and source.read_bytes() == b'{"documents":broken'


def test_checksum_damage_is_reported_instead_of_restoring_empty_state(tmp_path):
    first = storage.SessionStore(tmp_path)
    first.save(state())
    first.connection.execute("UPDATE documents SET payload_json='{}'")
    first.close()
    reopened = storage.SessionStore(tmp_path)
    with pytest.raises(storage.SessionStoreError, match="checksum"):
        reopened.load()
    reopened.close()


def test_process_death_mid_transaction_restores_previous_acknowledged_draft(tmp_path):
    first = storage.SessionStore(tmp_path)
    first.save(state())
    previous = first.load()
    first.close()
    source = Path(__file__).resolve().parents[1] / "source"
    script = """
import os,sys
from datapyn_runtime.session_store import SessionStore
store=SessionStore(sys.argv[1])
original=store._put
def crash(*args):
 original(*args)
 os._exit(17)
store._put=crash
store.patch({'upserts':[{'sessionId':'session-1','title':'uncommitted'}]})
"""
    child = subprocess.run([sys.executable, "-c", script, str(tmp_path)], env={**os.environ, "PYTHONPATH": str(source)}, capture_output=True, timeout=30)
    assert child.returncode == 17, child.stderr.decode(errors="replace")
    reopened = storage.SessionStore(tmp_path)
    assert reopened.load() == previous
    reopened.close()


def test_separate_connections_serialize_header_updates_without_lost_fields(tmp_path):
    first = storage.SessionStore(tmp_path)
    first.save(state())
    second = storage.SessionStore(tmp_path)
    def update(pair):
        store, field = pair
        return store.patch({"upserts": [{"sessionId": "session-1", field: 123}]})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(update, [(first, "first_private"), (second, "second_private")]))
    restored = first.load()["documents"][0]
    assert restored["first_private"] == 123 and restored["second_private"] == 123
    first.close(); second.close()
