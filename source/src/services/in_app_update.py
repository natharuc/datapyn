"""
In-process update runner — ``DataPyn.exe --apply-update``.

Runs from a temporary copy of the EXE so the install folder can be replaced.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from src.services.windows_installer import (
    EXE_NAME,
    launch_application,
    install_from_zip,
    normalize_version,
    wait_for_datapyn_exit,
)

logger = logging.getLogger(__name__)


class ZipUpdateWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def __init__(self, zip_path: Path, install_dir: Path, version: str):
        super().__init__()
        self.zip_path = zip_path
        self.install_dir = install_dir
        self.version = version

    def run(self) -> None:
        try:

            def on_progress(pct: int, msg: str) -> None:
                self.progress.emit(pct, msg)

            on_progress(2, "Aguardando o DataPyn encerrar…")
            wait_for_datapyn_exit(exclude_pid=os.getpid())
            on_progress(8, "Extraindo atualização…")
            exe = install_from_zip(
                self.zip_path, self.install_dir, self.version, on_progress=on_progress
            )
            self.finished_ok.emit(str(exe), self.version)
        except Exception as exc:
            logger.exception("In-app update failed")
            self.failed.emit(str(exc))


class InAppUpdateDialog(QDialog):
    """Small always-on-top progress window for ``--apply-update``."""

    def __init__(self, zip_path: Path, version: str, install_dir: Path):
        super().__init__()
        self._zip_path = zip_path
        self._version = normalize_version(version)
        self._install_dir = install_dir
        self._worker: ZipUpdateWorker | None = None

        self.setWindowTitle("DataPyn — Atualizando")
        self.setMinimumWidth(440)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel(f"Atualizando para v{self._version}")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        layout.addWidget(title)

        self._status = QLabel("Preparando…")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        layout.addWidget(self._bar)

    def start(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._worker = ZipUpdateWorker(self._zip_path, self._install_dir, self._version)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, pct: int, msg: str) -> None:
        self._bar.setValue(max(0, min(100, pct)))
        self._status.setText(msg)

    def _on_success(self, exe_path: str, version: str) -> None:
        self._status.setText(f"Concluído — abrindo DataPyn v{version}…")
        self._bar.setValue(100)
        launch_application(Path(exe_path))
        self.accept()

    def _on_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Falha na atualização", message)
        self.reject()


def parse_apply_update_argv(argv: list[str]) -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--apply-update", dest="zip_path", default=None)
    parser.add_argument("--version", default="")
    parser.add_argument("--dir", default="")
    args, _unknown = parser.parse_known_args(argv[1:] if argv else [])
    if not args.zip_path:
        return None
    return args


def run_apply_update(zip_path: Path, version: str, install_dir: Path) -> int:
    zip_path = Path(zip_path)
    install_dir = Path(install_dir)
    if not zip_path.is_file():
        print(f"Update ZIP not found: {zip_path}", file=sys.stderr)
        return 1
    if not install_dir.is_dir():
        print(f"Install dir not found: {install_dir}", file=sys.stderr)
        return 1

    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)
    app.setApplicationName("DataPyn")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))

    dialog = InAppUpdateDialog(zip_path, version, install_dir)
    dialog.start()
    return 0 if dialog.exec() == QDialog.DialogCode.Accepted else 1


def try_run_apply_update_from_argv(argv: list[str] | None = None) -> bool:
    """If argv requests ``--apply-update``, run the updater and exit the process."""
    argv = argv if argv is not None else sys.argv
    parsed = parse_apply_update_argv(argv)
    if parsed is None:
        return False
    install_dir = Path(parsed.dir) if parsed.dir else Path.cwd()
    code = run_apply_update(Path(parsed.zip_path), parsed.version, install_dir)
    raise SystemExit(code)
