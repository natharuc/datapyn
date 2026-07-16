"""Tests for idle reaper on BlockConnectorPool."""

import time
from unittest.mock import MagicMock, patch

from src.database.block_connector_pool import BlockConnectorPool


def test_reap_idle_releases_stale_connector():
    pool = BlockConnectorPool()
    connector = MagicMock()
    connector.is_connected.return_value = True
    connector.is_query_busy.return_value = False
    pool._entries["block-a"] = {
        "connector": connector,
        "connection_name": "conn",
        "last_used_at": time.monotonic() - 600,
    }

    released = pool.reap_idle(300)

    assert released == ["block-a"]
    assert "block-a" not in pool._entries
    connector.disconnect.assert_called_once()


def test_reap_idle_skips_active_connector():
    pool = BlockConnectorPool()
    connector = MagicMock()
    connector.is_connected.return_value = True
    connector.is_query_busy.return_value = False
    pool._entries["block-a"] = {
        "connector": connector,
        "connection_name": "conn",
        "last_used_at": time.monotonic(),
    }

    released = pool.reap_idle(300)

    assert released == []
    assert "block-a" in pool._entries
    connector.disconnect.assert_not_called()


def test_reap_idle_skips_busy_query():
    pool = BlockConnectorPool()
    connector = MagicMock()
    connector.is_connected.return_value = True
    connector.is_query_busy.return_value = True
    pool._entries["block-a"] = {
        "connector": connector,
        "connection_name": "conn",
        "last_used_at": time.monotonic() - 600,
    }

    released = pool.reap_idle(300)

    assert released == []
    connector.disconnect.assert_not_called()


def test_reap_idle_disabled_when_timeout_zero():
    pool = BlockConnectorPool()
    connector = MagicMock()
    pool._entries["block-a"] = {
        "connector": connector,
        "connection_name": "conn",
        "last_used_at": 0.0,
    }

    assert pool.reap_idle(0) == []
    connector.disconnect.assert_not_called()
