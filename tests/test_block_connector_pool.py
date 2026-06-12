"""Per-block isolated SQL connectors."""

from unittest.mock import MagicMock, patch

import pytest

from src.database.block_connector_pool import BlockConnectorPool, connect_connector_from_config


def test_pool_reuses_connector_for_same_block_key():
    pool = BlockConnectorPool()
    config = {
        "db_type": "postgresql",
        "host": "localhost",
        "port": 5432,
        "database": "db1",
        "username": "u",
        "password": "",
    }
    connector = MagicMock()
    connector.is_connected.return_value = True

    with patch(
        "src.database.block_connector_pool.connect_connector_from_config",
        return_value=connector,
    ) as connect_mock:
        first = pool.get("block-a", "conn", config)
        second = pool.get("block-a", "conn", config)

    assert first is second
    connect_mock.assert_called_once()


def test_pool_creates_separate_connectors_per_block_key():
    pool = BlockConnectorPool()
    config = {
        "db_type": "postgresql",
        "host": "localhost",
        "port": 5432,
        "database": "db1",
        "username": "u",
        "password": "",
    }
    connectors = [MagicMock(), MagicMock()]
    for c in connectors:
        c.is_connected.return_value = True

    with patch(
        "src.database.block_connector_pool.connect_connector_from_config",
        side_effect=connectors,
    ):
        a = pool.get("block-a", "conn", config)
        b = pool.get("block-b", "conn", config)

    assert a is connectors[0]
    assert b is connectors[1]
    assert a is not b


def test_connect_connector_from_config_applies_database_context():
    connector = MagicMock()
    connector.is_connected.return_value = True
    config = {
        "db_type": "sqlserver",
        "host": "localhost",
        "port": 1433,
        "database": "master",
        "username": "u",
        "password": "",
    }

    with patch("src.database.block_connector_pool.DatabaseConnector", return_value=connector):
        connect_connector_from_config(config, database_context="other_db")

    connector.connect.assert_called_once()
    connector.change_database.assert_called_once_with("other_db")
