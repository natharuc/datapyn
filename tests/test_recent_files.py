"""Tests for RecentFilesManager"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


@pytest.fixture
def tmp_config(tmp_path):
    """Return a temporary path for recent_files.json."""
    return str(tmp_path / "recent_files.json")


@pytest.fixture
def manager(tmp_config):
    """Create a RecentFilesManager backed by a temp file."""
    from src.core.recent_files_manager import RecentFilesManager
    return RecentFilesManager(config_path=tmp_config)


class TestRecentFilesManagerBasic:
    """Basic add / get / clear operations."""

    def test_starts_empty(self, manager):
        assert manager.get_recent() == []

    def test_add_single_file(self, manager):
        manager.add("/tmp/test.sql")
        recent = manager.get_recent()
        assert len(recent) == 1
        assert recent[0]["name"] == "test.sql"
        assert "test.sql" in recent[0]["path"]

    def test_add_moves_duplicate_to_top(self, manager):
        manager.add("/tmp/a.sql")
        manager.add("/tmp/b.sql")
        manager.add("/tmp/a.sql")
        recent = manager.get_recent()
        assert len(recent) == 2
        assert recent[0]["name"] == "a.sql"
        assert recent[1]["name"] == "b.sql"


class TestRecentFilesManagerLimit:
    """Enforces the MAX_RECENT_FILES limit."""

    def test_max_five_entries(self, manager):
        for i in range(8):
            manager.add(f"/tmp/file_{i}.sql")
        recent = manager.get_recent()
        assert len(recent) == 5
        # Most recent should be first
        assert recent[0]["name"] == "file_7.sql"

    def test_oldest_dropped_on_overflow(self, manager):
        for i in range(6):
            manager.add(f"/tmp/f{i}.sql")
        names = [r["name"] for r in manager.get_recent()]
        assert "f0.sql" not in names
        assert "f5.sql" in names


class TestRecentFilesManagerPersistence:
    """Persistence across manager instances."""

    def test_persists_to_disk(self, tmp_config):
        from src.core.recent_files_manager import RecentFilesManager

        mgr1 = RecentFilesManager(config_path=tmp_config)
        mgr1.add("/tmp/persisted.sql")

        mgr2 = RecentFilesManager(config_path=tmp_config)
        assert len(mgr2.get_recent()) == 1
        assert mgr2.get_recent()[0]["name"] == "persisted.sql"

    def test_clear_removes_all_and_persists(self, tmp_config):
        from src.core.recent_files_manager import RecentFilesManager

        mgr = RecentFilesManager(config_path=tmp_config)
        mgr.add("/tmp/a.sql")
        mgr.add("/tmp/b.sql")
        mgr.clear()

        assert mgr.get_recent() == []
        # Reload from disk
        mgr2 = RecentFilesManager(config_path=tmp_config)
        assert mgr2.get_recent() == []

    def test_handles_corrupt_file_gracefully(self, tmp_config):
        from src.core.recent_files_manager import RecentFilesManager

        with open(tmp_config, "w") as f:
            f.write("NOT VALID JSON{{{")

        mgr = RecentFilesManager(config_path=tmp_config)
        assert mgr.get_recent() == []

    def test_handles_missing_file(self, tmp_path):
        from src.core.recent_files_manager import RecentFilesManager

        mgr = RecentFilesManager(config_path=str(tmp_path / "nonexistent.json"))
        assert mgr.get_recent() == []


class TestRecentFilesManagerTimestamp:
    """Entries contain a valid ISO timestamp."""

    def test_entry_has_timestamp(self, manager):
        manager.add("/tmp/ts.sql")
        entry = manager.get_recent()[0]
        assert "timestamp" in entry
        from datetime import datetime
        datetime.fromisoformat(entry["timestamp"])  # should not raise
