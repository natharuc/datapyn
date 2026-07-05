"""Download progress bar widget for SQL block streaming exports."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget
import qtawesome as qta

from src.design_system.tokens import get_colors
from src.language import S


class DownloadProgressBar(QWidget):
    """Indeterminate progress bar for one streaming result set."""

    cancel_clicked = pyqtSignal(int)
    reveal_clicked = pyqtSignal(str)

    def __init__(self, file_index: int, label: str, parent=None):
        super().__init__(parent)
        self.file_index = file_index
        self._label_text = label
        self._total: int | None = None
        self._file_path: str | None = None
        self._done = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        colors = get_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.title_label = QLabel(self._label_text)
        self.title_label.setStyleSheet(
            f"color: {colors.text_primary}; font-size: 11px; font-weight: 600;"
        )
        header.addWidget(self.title_label, 1)

        btn_style = (
            f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {colors.bg_elevated};
            }}
            """
        )

        self.cancel_btn = QPushButton()
        self.cancel_btn.setFixedSize(20, 20)
        self.cancel_btn.setIcon(qta.icon("mdi.close", color=colors.text_tertiary))
        self.cancel_btn.setToolTip(getattr(S.block, "download_cancel_btn", "Cancel download"))
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(btn_style)
        self.cancel_btn.clicked.connect(lambda: self.cancel_clicked.emit(self.file_index))
        header.addWidget(self.cancel_btn)
        layout.addLayout(header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setStyleSheet(
            f"""
            QProgressBar {{
                background: {colors.bg_tertiary};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {colors.interactive_primary};
                border-radius: 3px;
            }}
            """
        )
        layout.addWidget(self.progress_bar)

        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(8)

        self.stats_label = QLabel(getattr(S.block, "download_preparing", "Preparing download..."))
        self.stats_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 10px;")
        stats_row.addWidget(self.stats_label, 1)

        self.reveal_btn = QPushButton(getattr(S.block, "download_reveal_btn", "Show file in folder"))
        self.reveal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reveal_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reveal_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                color: {colors.text_secondary};
                font-size: 10px;
                font-weight: 600;
                padding: 1px 8px;
            }}
            QPushButton:hover {{
                background: {colors.interactive_primary};
                color: {colors.bg_elevated};
                border-color: {colors.interactive_primary};
            }}
            QPushButton:pressed {{
                background: {colors.interactive_primary_active};
            }}
            """
        )
        self.reveal_btn.setFixedHeight(20)
        self.reveal_btn.hide()
        self.reveal_btn.clicked.connect(self._emit_reveal)
        stats_row.addWidget(self.reveal_btn)
        layout.addLayout(stats_row)

    def _emit_reveal(self) -> None:
        if self._file_path:
            self.reveal_clicked.emit(self._file_path)

    def set_total(self, total: int | None) -> None:
        if total is None or total <= 0:
            self._total = None
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setValue(0)
        else:
            self._total = int(total)
            self.progress_bar.setRange(0, self._total)
            self.progress_bar.setValue(0)

    def update_stats(self, rows: int, bytes_written: int, rate_mbps: float) -> None:
        mb = bytes_written / (1024 * 1024)
        if self._total and self._total > 0:
            pct = min(round((rows / self._total) * 100, 1), 100.0)
            self.progress_bar.setValue(min(rows, self._total))
            template = getattr(
                S.block,
                "download_rate_determinate",
                "{pct}% - {rows:,}/{total:,} rows - {mb} MB - {rate} MB/s",
            )
            self.stats_label.setText(
                template.format(
                    pct=f"{pct:.1f}",
                    rows=rows,
                    total=self._total,
                    mb=f"{mb:.1f}",
                    rate=f"{rate_mbps:.1f}",
                )
            )
        else:
            template = getattr(S.block, "download_rate", "{rows:,} rows - {mb} MB - {rate} MB/s")
            self.stats_label.setText(template.format(rows=rows, mb=f"{mb:.1f}", rate=f"{rate_mbps:.1f}"))

    def finish(self, file_path: str, total_rows: int) -> None:
        """Mark this result set as done; keep the bar visible with a reveal button."""
        self._done = True
        self._file_path = file_path
        self.cancel_btn.hide()
        self.reveal_btn.show()
        if self._total and self._total > 0:
            self.progress_bar.setRange(0, self._total)
            self.progress_bar.setValue(self._total)
        else:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
        template = getattr(S.block, "download_done", "Done - {rows:,} rows")
        self.stats_label.setText(template.format(rows=total_rows))
