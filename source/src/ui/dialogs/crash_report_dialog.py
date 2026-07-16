"""Crash report dialog — surfaces an unhandled exception without closing the app.

Frameless, design-system styled. Shows the formatted traceback and offers:
- "Reportar no GitHub" — creates/comments a GitHub issue (gh CLI, browser fallback).
- "Copiar" — copies the traceback to the clipboard.
- "Continuar" — dismisses the dialog; the app keeps running.

There is intentionally no "Close/Quit" button — dismissing never terminates
the process.
"""

from __future__ import annotations

import platform
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.design_system.button import GhostButton, PrimaryButton, SecondaryButton
from src.design_system.frameless_dialog import (
    frameless_body_stylesheet,
    install_frameless_shell,
)
from src.design_system.tokens import RADIUS, SCROLLBAR_STYLE, TYPOGRAPHY, get_colors
from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class CrashReportDialog(QDialog):
    """Modal (but non-fatal) dialog that shows an unhandled exception."""

    reported = pyqtSignal(str)  # issue URL

    def __init__(
        self,
        *,
        traceback_text: str,
        signature: str,
        version: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._traceback = traceback_text or ""
        self._signature = signature or ""
        self._version = version or ""
        self._result_url = ""
        self._setup_ui()

    # ------------------------------------------------------------------ UI

    def _setup_ui(self) -> None:
        colors = get_colors()

        self.setWindowTitle(S.crash.title)
        self.resize(720, 520)

        layout = install_frameless_shell(
            self,
            S.crash.title,
            min_width=520,
            min_height=360,
            content_margins=(22, 16, 22, 18),
            content_spacing=14,
            resizable=True,
            show_close=False,
        )
        self.setStyleSheet(self.styleSheet() + frameless_body_stylesheet())

        # Header: icon + title + short message
        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        if HAS_QTAWESOME:
            icon_label.setPixmap(qta.icon("mdi.alert-circle-outline", color=colors.danger).pixmap(30, 30))
        header_text = QVBoxLayout()
        header_text.setSpacing(4)
        title = QLabel(S.crash.title)
        title.setStyleSheet(f"color: {colors.text_primary}; font-size: 16px; font-weight: 600;")
        message = QLabel(S.crash.message)
        message.setWordWrap(True)
        message.setStyleSheet(f"color: {colors.text_secondary}; font-size: 12px;")
        header_text.addWidget(title)
        header_text.addWidget(message)
        header_row.addWidget(icon_label)
        header_row.addLayout(header_text, 1)
        layout.addLayout(header_row)

        # Meta footer (version / OS / signature / timestamp)
        meta = QLabel(self._meta_text())
        meta.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px;")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        # Traceback area
        tb_label = QLabel(S.crash.traceback_label)
        tb_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 12px; font-weight: 600;")
        layout.addWidget(tb_label)

        self._traceback_view = QPlainTextEdit(self._traceback)
        self._traceback_view.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self._traceback_view.setFont(mono)
        self._traceback_view.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_sm}px;
                padding: 8px;
                font-size: 11px;
            }}
            {SCROLLBAR_STYLE}
            """
        )
        layout.addWidget(self._traceback_view, 1)

        # Progress (hidden until reporting)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        # Status label for report result / errors
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px;")
        self._status.hide()
        layout.addWidget(self._status)

        layout.addLayout(self._build_buttons(colors))

    def _meta_text(self) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"DataPyn {self._version or '?'}  •  {platform.system()} {platform.release()}  "
            f"•  {S.crash.signature}: {self._signature}  •  {ts}"
        )

    def _build_buttons(self, colors) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)

        self._copy_btn = GhostButton(S.crash.copy)
        self._copy_btn.clicked.connect(self._on_copy)

        self._continue_btn = SecondaryButton(S.crash.continue_btn)
        self._continue_btn.clicked.connect(self.accept)

        self._report_btn = PrimaryButton(S.crash.report_btn)
        self._report_btn.clicked.connect(self._on_report)
        self._report_btn.setDefault(True)

        row.addWidget(self._copy_btn)
        row.addWidget(self._continue_btn)
        row.addWidget(self._report_btn)
        return row

    # -------------------------------------------------------------- Actions

    def _on_copy(self) -> None:
        clip = QGuiApplication.clipboard()
        if clip is not None:
            clip.setText(self._full_report_text())
        self._flash_status(S.crash.copied, ok=True)

    def _on_report(self) -> None:
        self._progress.show()
        self._status.hide()
        self._report_btn.setEnabled(False)
        self._copy_btn.setEnabled(False)

        from PyQt6.QtCore import QThread

        from src.services.crash_reporter_service import CrashReporterWorker

        self._worker = CrashReporterWorker(
            traceback_text=self._full_report_text(),
            signature=self._signature,
            summary=self._short_summary(),
        )
        self._worker_thread = QThread(self)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_report_finished)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_report_finished(self, url: str, error: str) -> None:
        self._progress.hide()
        self._report_btn.setEnabled(True)
        self._copy_btn.setEnabled(True)
        if error:
            self._flash_status(S.crash.report_failed.format(error=error), ok=False)
            return
        if url:
            self._result_url = url
            self.reported.emit(url)
            self._flash_status(S.crash.report_success.format(url=url), ok=True)
            # Open the issue in the browser so the user can follow up
            try:
                import webbrowser

                webbrowser.open(url)
            except Exception:
                pass
        else:
            self._flash_status(S.crash.report_failed.format(error="no URL"), ok=False)

    def _flash_status(self, text: str, *, ok: bool) -> None:
        colors = get_colors()
        color = colors.success if ok else colors.danger
        self._status.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._status.setText(text)
        self._status.show()

    # ----------------------------------------------------------- Helpers

    def _short_summary(self) -> str:
        """One-line summary derived from the last frame of the traceback."""
        lines = [ln.strip() for ln in self._traceback.splitlines() if ln.strip()]
        exc_line = ""
        for ln in reversed(lines):
            if ln and not ln.startswith((" ", "File ", "Traceback")):
                exc_line = ln
                break
        exc_line = (exc_line or "Unhandled exception")[:120]
        return f"Crash: {exc_line}"

    def _full_report_text(self) -> str:
        return (
            f"DataPyn crash report\n"
            f"version: {self._version or '?'}\n"
            f"os: {platform.system()} {platform.release()}\n"
            f"python: {platform.python_version()}\n"
            f"signature: datapyn-crash:{self._signature}\n"
            f"timestamp: {datetime.now().isoformat()}\n"
            f"\n---- traceback ----\n{self._traceback}\n"
        )
