"""Tests for DatabaseConnector.stream_query_to_files."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.database.database_connector import DatabaseConnector
from src.database.query_stream_exporter import StreamExportResult


class TestStreamQueryToFiles:
    def test_delegates_to_stream_generic_for_postgresql(self, tmp_path):
        connector = DatabaseConnector()
        connector.engine = MagicMock()
        connector.db_type = "postgresql"
        expected = StreamExportResult(
            files=[tmp_path / "out.csv"],
            row_counts=[5],
            columns_per_file=[["id"]],
        )
        with patch.object(connector, "_stream_query_unlocked", return_value=expected) as mock_stream:
            result = connector.stream_query_to_files(
                "SELECT 1",
                base_path=tmp_path / "out.csv",
                export_format="csv",
            )

        assert result is expected
        mock_stream.assert_called_once()

    def test_raises_when_not_connected(self):
        connector = DatabaseConnector()
        connector.engine = None
        with pytest.raises(ConnectionError):
            connector.stream_query_to_files(
                "SELECT 1",
                base_path=Path("out.csv"),
                export_format="csv",
            )

    def test_estimate_count_single_select(self):
        connector = DatabaseConnector()
        connector.db_type = "databricks"
        cur = MagicMock()
        cur.fetchone.return_value = (12345,)
        raw = MagicMock()
        raw.cursor.return_value = cur
        engine = MagicMock()
        engine.raw_connection.return_value = raw
        connector.engine = engine

        total = connector._estimate_databricks_row_count("SELECT * FROM t", None)
        assert total == 12345
        cur.execute.assert_called_once()
        assert "COUNT(*)" in cur.execute.call_args[0][0]

    def test_estimate_count_multi_statement_returns_none(self):
        connector = DatabaseConnector()
        connector.db_type = "databricks"
        engine = MagicMock()
        connector.engine = engine

        assert connector._estimate_databricks_row_count("SELECT 1; SELECT 2;", None) is None
        engine.raw_connection.assert_not_called()

    def test_estimate_count_ddl_returns_none(self):
        connector = DatabaseConnector()
        connector.db_type = "databricks"
        engine = MagicMock()
        connector.engine = engine

        assert connector._estimate_databricks_row_count("CREATE TABLE t (id INT)", None) is None
        engine.raw_connection.assert_not_called()

    def test_estimate_count_show_returns_none(self):
        connector = DatabaseConnector()
        connector.db_type = "databricks"
        engine = MagicMock()
        connector.engine = engine

        assert connector._estimate_databricks_row_count("SHOW TABLES", None) is None
        engine.raw_connection.assert_not_called()

    def test_estimate_count_error_returns_none(self):
        connector = DatabaseConnector()
        connector.db_type = "databricks"
        cur = MagicMock()
        cur.execute.side_effect = RuntimeError("boom")
        raw = MagicMock()
        raw.cursor.return_value = cur
        engine = MagicMock()
        engine.raw_connection.return_value = raw
        connector.engine = engine

        assert connector._estimate_databricks_row_count("SELECT * FROM t", None) is None
