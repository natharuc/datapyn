"""Tests for block download progress UI."""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from src.editors.code_block import CodeBlock
from src.ui.components.download_progress_bar import DownloadProgressBar


@pytest.fixture
def qtbot(qtbot):
    return qtbot


class TestDownloadProgressBar:
    def test_update_stats(self, qtbot):
        bar = DownloadProgressBar(1, "out.parquet")
        qtbot.addWidget(bar)
        bar.update_stats(12345, 4_400_000, 8.1)
        assert "12,345" in bar.stats_label.text()
        assert "4.2" in bar.stats_label.text()

    def test_cancel_emits(self, qtbot):
        bar = DownloadProgressBar(2, "data.csv")
        qtbot.addWidget(bar)
        seen = []
        bar.cancel_clicked.connect(lambda i: seen.append(i))
        bar.cancel_btn.click()
        assert seen == [2]

    def test_set_total_determinate(self, qtbot):
        bar = DownloadProgressBar(1, "out.parquet")
        qtbot.addWidget(bar)
        bar.set_total(1000)
        assert bar.progress_bar.minimum() == 0
        assert bar.progress_bar.maximum() == 1000
        bar.update_stats(500, 1_000_000, 5.0)
        assert "50" in bar.stats_label.text()
        assert "1,000" in bar.stats_label.text()
        assert bar.progress_bar.value() == 500

    def test_set_total_none_is_indeterminate(self, qtbot):
        bar = DownloadProgressBar(1, "out.parquet")
        qtbot.addWidget(bar)
        bar.set_total(1000)
        bar.set_total(None)
        assert bar.progress_bar.minimum() == 0
        assert bar.progress_bar.maximum() == 0


class TestCodeBlockDownloadProgress:
    def test_start_and_clear(self, qtbot):
        block = CodeBlock()
        qtbot.addWidget(block)
        block.show()
        qtbot.waitExposed(block)
        block.start_download(1, "a.parquet")
        assert not block.download_progress_container.isHidden()
        assert 1 in block._download_bars
        block.start_download(2, "b.parquet")
        assert 2 in block._download_bars
        block.clear_downloads()
        assert not block._download_bars
        assert not block.download_progress_container.isVisible()

    def test_finish_keeps_bar_with_reveal_button(self, qtbot, tmp_path):
        block = CodeBlock()
        qtbot.addWidget(block)
        block.show()
        qtbot.waitExposed(block)
        block.start_download(1, "a.parquet")
        bar = block._download_bars[1]
        assert bar.reveal_btn.isHidden()
        assert not bar.cancel_btn.isHidden()
        path = tmp_path / "a.parquet"
        path.write_bytes(b"")
        block.finish_download(1, str(path), 42)
        # Bar stays in the container, marked done.
        assert 1 in block._download_bars
        assert bar.cancel_btn.isHidden()
        assert not bar.reveal_btn.isHidden()
        assert "42" in bar.stats_label.text()

    def test_reveal_signal(self, qtbot, tmp_path):
        block = CodeBlock()
        qtbot.addWidget(block)
        block.show()
        qtbot.waitExposed(block)
        seen = []
        block.reveal_file_requested.connect(lambda p: seen.append(p))
        block.start_download(1, "x.csv")
        path = tmp_path / "x.csv"
        path.write_bytes(b"")
        block.finish_download(1, str(path), 5)
        bar = block._download_bars[1]
        bar.reveal_btn.click()
        assert seen == [str(path)]

    def test_cancel_signal(self, qtbot):
        block = CodeBlock()
        qtbot.addWidget(block)
        seen = []
        block.cancel_download_requested.connect(lambda b: seen.append(b))
        block.start_download(1, "x.csv")
        block._download_bars[1].cancel_btn.click()
        assert seen == [block]


class TestSessionDownloadCancel:
    """Cancel must clear bars even when download_finished is token-skipped."""

    def test_download_cancel_clears_bars_immediately(self, qtbot):
        from unittest.mock import MagicMock, patch
        from src.core.session import Session
        from src.ui.components.session_widget import SessionWidget

        session = Session("dl-cancel", title="dl-cancel")
        widget = SessionWidget(session)
        qtbot.addWidget(widget)
        block = widget.editor.get_blocks()[0]
        block.start_download(1, "out.csv")
        assert block._download_bars

        widget._sql_is_download = True
        widget._sql_worker = MagicMock()
        widget._sql_worker.connector = MagicMock()
        widget._sql_thread = MagicMock()
        widget._sql_thread.isRunning.return_value = True

        with (
            patch.object(widget, "_stop_sql_execution"),
            patch.object(widget, "_release_sql_slot"),
            patch.object(widget, "_stop_python_execution"),
            patch.object(widget, "_arm_sql_stop_watch"),
            patch.object(widget, "_schedule_sql_stop_finalize"),
        ):
            widget._on_download_cancel_requested(block)

        assert not block._download_bars
        assert widget._download_cancel_pending is True

    def test_complete_user_cancel_quiet_when_closing(self, qtbot):
        from unittest.mock import MagicMock
        from src.core.session import Session
        from src.ui.components.session_widget import SessionWidget

        session = Session("dl-close", title="dl-close")
        widget = SessionWidget(session)
        qtbot.addWidget(widget)
        widget._is_closing = True
        widget._download_cancel_pending = True
        widget.append_output = MagicMock()

        widget._complete_user_cancel()

        widget.append_output.assert_not_called()

    def test_complete_user_cancel_download_uses_download_message(self, qtbot):
        from unittest.mock import MagicMock
        from src.core.session import Session
        from src.language import S
        from src.ui.components.session_widget import SessionWidget

        session = Session("dl-msg", title="dl-msg")
        widget = SessionWidget(session)
        qtbot.addWidget(widget)
        widget._download_cancel_pending = True
        widget._is_closing = False
        logged = []
        statuses = []
        widget.append_output = MagicMock(side_effect=lambda *a, **k: logged.append(a))
        widget.status_changed.connect(lambda s: statuses.append(s))

        widget._complete_user_cancel()

        assert logged
        joined = " ".join(str(x) for x in logged[0])
        assert S.block.download_cancelled in joined or "Download cancelled" in joined
        assert "Execution cancelled by user" not in joined
        assert statuses
        assert S.block.download_cancelled in statuses[0] or "Download cancelled" in statuses[0]
