"""
DataPyn Setup — lightweight Windows installer (downloads latest release ZIP).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.services import windows_installer as wi


class InstallWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str, str)  # exe path, version
    failed = pyqtSignal(str)

    def __init__(self, install_dir: Path, mode: str, zip_path: Path | None, version: str):
        super().__init__()
        self.install_dir = install_dir
        self.mode = mode
        self.zip_path = zip_path
        self.version = version

    def run(self):
        try:
            def on_progress(pct: int, msg: str):
                self.progress.emit(pct, msg)

            if self.mode == "update" and self.zip_path:
                exe = wi.install_from_zip(
                    self.zip_path, self.install_dir, self.version, on_progress=on_progress
                )
                self.finished_ok.emit(str(exe), self.version)
                return

            exe, release = wi.install_latest_release(self.install_dir, on_progress=on_progress)
            self.finished_ok.emit(str(exe), release.version)
        except Exception as exc:
            self.failed.emit(str(exc))


class SetupWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DataPyn Setup")
        self.setFixedSize(520, 420)
        self._install_dir = wi.DEFAULT_INSTALL_DIR
        self._worker: InstallWorker | None = None
        self._exe_path: str | None = None

        logo_path = ROOT / "source" / "src" / "assets" / "datapyn_logo.svg"
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)
        self._stack.addWidget(self._page_welcome())
        self._stack.addWidget(self._page_progress())
        self._stack.addWidget(self._page_done())
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(
            """
            QMainWindow { background: #0c111b; }
            QLabel { color: #eef2f7; }
            QLabel#muted { color: #8b9cb3; font-size: 12px; }
            QLabel#title { font-size: 22px; font-weight: 600; }
            QPushButton {
                background: #3369ff;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: 600;
            }
            QPushButton:hover { background: #4f80ff; }
            QPushButton#ghost {
                background: transparent;
                color: #8b9cb3;
                border: 1px solid rgba(148,163,184,0.25);
            }
            QPushButton#ghost:hover { color: #eef2f7; border-color: #3369ff; }
            QProgressBar {
                border: none;
                border-radius: 6px;
                background: #161f30;
                height: 10px;
                text-align: center;
                color: #8b9cb3;
            }
            QProgressBar::chunk {
                border-radius: 6px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3369ff, stop:1 #33c2ff);
            }
            """
        )

    def _page_welcome(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        title = QLabel("Install DataPyn")
        title.setObjectName("title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Downloads the latest release from GitHub, installs for your user "
            f"({self._install_dir}) and creates shortcuts."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)

        existing = wi.read_installed_version()
        if existing:
            hint = QLabel(f"Installed version: {existing}. Setup will upgrade to the latest release.")
            hint.setWordWrap(True)
            hint.setObjectName("muted")
            layout.addWidget(hint)

        layout.addStretch()

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.close)
        row.addWidget(cancel)
        install = QPushButton("Install")
        install.clicked.connect(self._start_install)
        row.addWidget(install)
        layout.addLayout(row)
        return page

    def _page_progress(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)

        self._progress_title = QLabel("Downloading…")
        self._progress_title.setObjectName("title")
        layout.addWidget(self._progress_title)

        self._progress_status = QLabel("Connecting to GitHub…")
        self._progress_status.setObjectName("muted")
        self._progress_status.setWordWrap(True)
        layout.addWidget(self._progress_status)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        layout.addWidget(self._progress_bar)
        layout.addStretch()
        return page

    def _page_done(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        done_title = QLabel("DataPyn is ready")
        done_title.setObjectName("title")
        layout.addWidget(done_title)

        self._done_label = QLabel("")
        self._done_label.setWordWrap(True)
        self._done_label.setObjectName("muted")
        layout.addWidget(self._done_label)
        layout.addStretch()

        row = QHBoxLayout()
        row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("ghost")
        close_btn.clicked.connect(self.close)
        row.addWidget(close_btn)
        self._launch_btn = QPushButton("Open DataPyn")
        self._launch_btn.clicked.connect(self._launch_app)
        row.addWidget(self._launch_btn)
        layout.addLayout(row)
        return page

    def _start_install(self):
        self._stack.setCurrentIndex(1)
        self._worker = InstallWorker(self._install_dir, "install", None, "")
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, pct: int, msg: str):
        self._progress_bar.setValue(pct)
        self._progress_status.setText(msg)
        if pct < 30:
            self._progress_title.setText("Downloading…")
        elif pct < 70:
            self._progress_title.setText("Installing…")
        else:
            self._progress_title.setText("Finishing…")

    def _on_success(self, exe_path: str, version: str):
        self._exe_path = exe_path
        self._done_label.setText(f"Version {version} installed at:\n{Path(exe_path).parent}")
        self._stack.setCurrentIndex(2)

    def _on_failed(self, message: str):
        QMessageBox.critical(self, "Setup failed", message)
        self._stack.setCurrentIndex(0)

    def _launch_app(self):
        if self._exe_path:
            wi.launch_application(Path(self._exe_path))
        self.close()


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    flags = wi.parse_cli_args(argv)

    if "--uninstall" in flags:
        ok = wi.uninstall(Path(flags["--dir"]) if "--dir" in flags else None)
        return 0 if ok else 1

    if "--update" in flags:
        zip_path = Path(flags["--update"])
        version = flags.get("--version", "0.0.0")
        install_dir = Path(flags.get("--dir", wi.DEFAULT_INSTALL_DIR))
        try:
            wi.install_from_zip(zip_path, install_dir, version)
            return 0
        except Exception as exc:
            print(exc, file=sys.stderr)
            return 1

    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    window = SetupWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
