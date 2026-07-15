"""Tests for QueryDownloadWorker."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QThread

from src.database.query_stream_exporter import StreamExportResult
from src.workers import QueryDownloadWorker


@pytest.fixture
def qtbot(qtbot):
    return qtbot


class TestQueryDownloadWorker:
    def test_emits_finished_with_result(self, qtbot):
        connector = MagicMock()
        expected = StreamExportResult(
            files=[Path("out.csv")],
            row_counts=[10],
            columns_per_file=[["id"]],
        )
        connector.stream_query_to_files.return_value = expected

        worker = QueryDownloadWorker(connector, "SELECT 1", "out.csv", "csv")
        results: list[tuple] = []
        worker.download_finished.connect(lambda r, e: results.append((r, e)))

        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        qtbot.waitUntil(lambda: len(results) == 1, timeout=5000)

        result, error = results[0]
        assert error == ""
        assert result.total_rows == 10
        connector.stream_query_to_files.assert_called_once()

    def test_cancel_sets_flag_and_requests_connector_cancel(self):
        connector = MagicMock()
        worker = QueryDownloadWorker(connector, "SELECT 1", "out.csv", "csv")
        worker.cancel()
        assert worker._cancel_requested is True
        connector.request_cancel.assert_called_once()

    def test_cancelled_result_emits_sentinel(self, qtbot):
        connector = MagicMock()
        connector.stream_query_to_files.return_value = StreamExportResult(cancelled=True)

        worker = QueryDownloadWorker(connector, "SELECT 1", "out.csv", "csv")
        results: list[tuple] = []
        worker.download_finished.connect(lambda r, e: results.append((r, e)))

        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        qtbot.waitUntil(lambda: len(results) == 1, timeout=5000)

        _, error = results[0]
        assert error == "__CANCELLED__"

    def test_error_message_containing_cancel_substring_is_not_swallowed(self, qtbot):
        """A real error whose text contains 'cancel' (e.g. column 'Cancelad') must
        surface as the real error, not be misclassified as a user cancellation."""
        connector = MagicMock()
        connector._cancelled = False
        connector.db_type = "mysql"
        connector.stream_query_to_files.side_effect = Exception(
            "(pymysql.err.OperationalError) (1054, \"Unknown column 'Cancelad' in 'WHERE'\")"
        )

        worker = QueryDownloadWorker(connector, "select * from atendimento where Cancelad = 1", "out.csv", "csv")
        results: list[tuple] = []
        worker.download_finished.connect(lambda r, e: results.append((r, e)))

        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        qtbot.waitUntil(lambda: len(results) == 1, timeout=5000)

        _, error = results[0]
        assert error != "__CANCELLED__"
        assert "Cancelad" in error


    def test_progress_emits_tuple(self, qtbot):
        connector = MagicMock()

        def stream_side_effect(*args, **kwargs):
            on_progress = kwargs.get("on_progress")
            if on_progress:
                on_progress(1, 50, 1024)
                on_progress(1, 100, 2048)
            return StreamExportResult(files=[Path("out.csv")], row_counts=[100])

        connector.stream_query_to_files.side_effect = stream_side_effect

        worker = QueryDownloadWorker(connector, "SELECT 1", "out.csv", "csv")
        progress = []
        worker.progress.connect(lambda fi, rows, nbytes: progress.append((fi, rows, nbytes)))

        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        qtbot.waitUntil(lambda: len(progress) >= 1, timeout=5000)
        assert progress[0][:2] == (1, 50)

    def test_total_ready_emitted_when_connector_reports_total(self, qtbot):
        connector = MagicMock()

        def stream_side_effect(*args, **kwargs):
            on_total = kwargs.get("on_total")
            if on_total:
                on_total(1, 42)
            return StreamExportResult(files=[Path("out.csv")], row_counts=[42])

        connector.stream_query_to_files.side_effect = stream_side_effect

        worker = QueryDownloadWorker(connector, "SELECT 1", "out.csv", "csv")
        totals = []
        worker.total_ready.connect(lambda fi, total: totals.append((fi, total)))

        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        qtbot.waitUntil(lambda: len(totals) >= 1, timeout=5000)
        assert totals == [(1, 42)]

    def test_total_ready_not_emitted_when_connector_omits_it(self, qtbot):
        connector = MagicMock()
        connector.stream_query_to_files.return_value = StreamExportResult(
            files=[Path("out.csv")], row_counts=[10]
        )

        worker = QueryDownloadWorker(connector, "SELECT 1", "out.csv", "csv")
        totals = []
        worker.total_ready.connect(lambda fi, total: totals.append((fi, total)))
        finished = []
        worker.download_finished.connect(lambda r, e: finished.append(True))

        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        qtbot.waitUntil(lambda: len(finished) >= 1, timeout=5000)
        assert totals == []

    def test_passes_csv_options_to_connector(self, qtbot):
        connector = MagicMock()
        connector.stream_query_to_files.return_value = StreamExportResult(
            files=[Path("out.csv")],
            row_counts=[1],
        )
        csv_options = {"delimiter": ";", "decimal": ",", "encoding": "utf-8", "header": True}

        worker = QueryDownloadWorker(
            connector,
            "SELECT 1",
            "out.csv",
            "csv",
            csv_options=csv_options,
        )
        results: list[tuple] = []
        worker.download_finished.connect(lambda r, e: results.append((r, e)))

        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        qtbot.waitUntil(lambda: len(results) == 1, timeout=5000)

        _, kwargs = connector.stream_query_to_files.call_args
        assert kwargs["csv_options"] == csv_options

    def test_passes_csv_options_to_connector(self, qtbot):
        connector = MagicMock()
        connector.stream_query_to_files.return_value = StreamExportResult(
            files=[Path("out.csv")],
            row_counts=[1],
        )
        csv_options = {"delimiter": ";", "decimal": ",", "encoding": "utf-8", "header": True}

        worker = QueryDownloadWorker(
            connector,
            "SELECT 1",
            "out.csv",
            "csv",
            csv_options=csv_options,
        )
        results: list[tuple] = []
        worker.download_finished.connect(lambda r, e: results.append((r, e)))

        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        qtbot.waitUntil(lambda: len(results) == 1, timeout=5000)

        _, kwargs = connector.stream_query_to_files.call_args
        assert kwargs["csv_options"] == csv_options
