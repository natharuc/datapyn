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
