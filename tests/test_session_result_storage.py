"""Tests for optional session DataFrame variable persistence (Parquet)."""

import json

import pandas as pd
import pytest

from src.core.session_result_storage import (
    MANIFEST_NAME,
    SessionResultStorage,
    extract_dataframe_variables,
    set_session_result_max_size_mb,
    set_session_result_restore_enabled,
)


@pytest.fixture
def storage_tmp(monkeypatch, tmp_path):
    root = tmp_path / "session_snapshots"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "src.core.session_result_storage._storage_root",
        lambda: root,
    )
    monkeypatch.setattr(
        "src.core.session_result_storage._current_workspace_path",
        lambda: str(tmp_path / "workspace"),
    )
    return root


@pytest.fixture
def enabled_restore(monkeypatch):
    monkeypatch.setattr(
        "src.core.session_result_storage.is_session_result_restore_enabled",
        lambda: True,
    )
    set_session_result_restore_enabled(True)
    set_session_result_max_size_mb(50)
    yield
    set_session_result_restore_enabled(False)


def test_extract_dataframe_variables_filters_namespace():
    df = pd.DataFrame({"a": [1, 2]})
    other = pd.DataFrame({"b": [3]})
    namespace = {
        "df": df,
        "other": other,
        "_hidden": pd.DataFrame({"x": [1]}),
        "pd": df,
        "name": "text",
        "count": 42,
    }
    items = extract_dataframe_variables(namespace)
    assert [name for name, _ in items] == ["df", "other"]


def test_save_from_namespace_round_trip(storage_tmp, enabled_restore):
    session_id = "abc123"
    df = pd.DataFrame({"id": [1, 2, 3], "name": ["a", "b", "c"]})
    namespace = {"my_df": df, "ignored": 1}

    assert SessionResultStorage.save_from_namespace(session_id, namespace) is True

    session_dir = storage_tmp / session_id
    assert session_dir.is_dir()
    assert (session_dir / MANIFEST_NAME).is_file()
    assert (session_dir / "0.parquet").is_file()

    loaded = SessionResultStorage.load(session_id)
    assert loaded is not None
    assert list(loaded.keys()) == ["my_df"]
    pd.testing.assert_frame_equal(loaded["my_df"], df)


def test_save_skips_when_over_size_limit(storage_tmp, enabled_restore, monkeypatch):
    monkeypatch.setattr(
        "src.core.session_result_storage.get_session_result_max_size_bytes",
        lambda: 64,
    )
    session_id = "big_session"
    namespace = {"big": pd.DataFrame({"value": list(range(500))})}

    assert SessionResultStorage.save_from_namespace(session_id, namespace) is False
    assert not (storage_tmp / session_id).exists()


def test_load_returns_none_when_disabled(storage_tmp, enabled_restore, monkeypatch):
    session_id = "sess1"
    SessionResultStorage.save_from_namespace(session_id, {"df": pd.DataFrame({"a": [1]})})

    monkeypatch.setattr(
        "src.core.session_result_storage.is_session_result_restore_enabled",
        lambda: False,
    )
    assert SessionResultStorage.load(session_id) is None


def test_delete_removes_session_folder(storage_tmp, enabled_restore):
    session_id = "to_delete"
    SessionResultStorage.save_from_namespace(session_id, {"df": pd.DataFrame({"a": [1]})})
    path = storage_tmp / session_id
    assert path.exists()

    SessionResultStorage.delete(session_id)
    assert not path.exists()


def test_manifest_lists_multiple_variables(storage_tmp, enabled_restore):
    session_id = "multi"
    namespace = {
        "df": pd.DataFrame({"a": [1]}),
        "df1": pd.DataFrame({"b": [2, 3]}),
    }
    SessionResultStorage.save_from_namespace(session_id, namespace)

    manifest_path = storage_tmp / session_id / MANIFEST_NAME
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    assert len(manifest["variables"]) == 2
    assert manifest.get("session_id") == session_id
    loaded = SessionResultStorage.load(session_id)
    assert list(loaded.keys()) == ["df", "df1"]


def test_export_import_parquet_file(storage_tmp):
    from pathlib import Path

    from src.core.session_result_storage import export_variables_to_path, import_variables_from_path

    df = pd.DataFrame({"x": [1, 2]})
    file_path = storage_tmp / "export.parquet"
    export_variables_to_path(file_path, {"my_var": df})
    loaded = import_variables_from_path(file_path)
    assert "export" in loaded or "my_var" in loaded
    key = "my_var" if "my_var" in loaded else "export"
    pd.testing.assert_frame_equal(loaded[key], df)


def test_get_snapshot_variable_sizes(storage_tmp, enabled_restore):
    from src.core.session_result_storage import get_snapshot_variable_sizes

    df_a = pd.DataFrame({"a": [1, 2, 3]})
    df_b = pd.DataFrame({"b": list(range(100))})
    SessionResultStorage.save_from_namespace(
        "sizes_session",
        {"alpha": df_a, "beta": df_b},
    )
    sizes = get_snapshot_variable_sizes("sizes_session")
    assert "alpha" in sizes and sizes["alpha"] > 0
    assert "beta" in sizes and sizes["beta"] > sizes["alpha"]


def test_list_session_snapshots(storage_tmp, enabled_restore):
    from src.core.session_result_storage import list_session_snapshots

    SessionResultStorage.save_from_namespace("s1", {"a": pd.DataFrame({"v": [1]})})
    SessionResultStorage.save_from_namespace("s2", {"b": pd.DataFrame({"v": [2]})})
    entries = list_session_snapshots()
    assert len(entries) == 2
    ids = {entry["session_id"] for entry in entries}
    assert ids == {"s1", "s2"}


def test_load_supports_legacy_manifest_items(storage_tmp, enabled_restore):
    session_id = "legacy"
    session_dir = storage_tmp / session_id
    session_dir.mkdir(parents=True)
    df = pd.DataFrame({"x": [9]})
    df.to_parquet(session_dir / "0.parquet", index=False)
    with open(session_dir / MANIFEST_NAME, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "version": 1,
                "items": [{"label": "legacy_df", "file": "0.parquet"}],
                "workspace": str(storage_tmp.parent / "workspace"),
            },
            handle,
        )

    loaded = SessionResultStorage.load(session_id)
    assert loaded is not None
    pd.testing.assert_frame_equal(loaded["legacy_df"], df)
