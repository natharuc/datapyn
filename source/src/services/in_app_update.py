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
    QProgressBar,
    QVBoxLayout,
)

from src.design_system.app_dialogs import show_danger
from src.design_system.frameless_dialog import install_frameless_shell
from src.design_system.tokens import get_colors
from src.services.windows_installer import (
    _append_update_log,
    _datapyn_process_pids,
    _install_locked_message,
    launch_application,
    install_from_zip,
    normalize_version,
    wait_for_datapyn_exit,
    wait_for_process_exit,
)

logger = logging.getLogger(__name__)


class ZipUpdateWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        zip_path: Path,
        install_dir: Path,
        version: str,
        parent_pid: int | None = None,
    ):
        super().__init__()
        self.zip_path = zip_path
        self.install_dir = install_dir
        self.version = version
        self.parent_pid = parent_pid

    def run(self) -> None:
        try:

            def on_progress(pct: int, msg: str) -> None:
                self.progress.emit(pct, msg)

            if self.parent_pid:
                on_progress(2, "Aguardando o DataPyn encerrar…")
                if not wait_for_process_exit(self.parent_pid, timeout_sec=180):
                    raise RuntimeError(
                        _install_locked_message(
                            [],
                            extra="O processo principal não encerrou a tempo.",
                        )
                    )

            on_progress(5, "Aguardando instâncias do DataPyn encerrarem…")
            exclude = os.getpid()
            if not wait_for_datapyn_exit(timeout_sec=180, exclude_pid=exclude):
                raise RuntimeError(_install_locked_message(_datapyn_process_pids(exclude_pid=exclude)))

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

    def __init__(
        self,
        zip_path: Path,
        version: str,
        install_dir: Path,
        parent_pid: int | None = None,
    ):
        super().__init__()
        self._zip_path = zip_path
        self._version = normalize_version(version)
        self._install_dir = install_dir
        self._parent_pid = parent_pid
        self._worker: ZipUpdateWorker | None = None

        self.setWindowTitle("DataPyn — Atualizando")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        colors = get_colors()
        layout = install_frameless_shell(
            self,
            "DataPyn — Atualizando",
            min_width=440,
            min_height=160,
            content_margins=(24, 20, 24, 20),
            content_spacing=12,
            resizable=False,
        )

        title = QLabel(f"Atualizando para v{self._version}")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {colors.text_primary};")
        layout.addWidget(title)

        self._status = QLabel("Preparando…")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {colors.text_secondary};")
        layout.addWidget(self._status)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: none;
                border-radius: 4px;
                background: {colors.bg_tertiary};
            }}
            QProgressBar::chunk {{
                border-radius: 4px;
                background: {colors.interactive_primary};
            }}
            """
        )
        layout.addWidget(self._bar)

    def start(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._worker = ZipUpdateWorker(
            self._zip_path, self._install_dir, self._version, self._parent_pid
        )
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
        show_danger(self, "Falha na atualização", message)
        self.reject()


def parse_apply_update_argv(argv: list[str]) -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--apply-update", dest="zip_path", default=None)
    parser.add_argument("--version", default="")
    parser.add_argument("--dir", default="")
    parser.add_argument("--parent-pid", type=int, default=None)
    args, _unknown = parser.parse_known_args(argv[1:] if argv else [])
    if not args.zip_path:
        return None
    return args


def run_apply_update(
    zip_path: Path,
    version: str,
    install_dir: Path,
    parent_pid: int | None = None,
) -> int:
    zip_path = Path(zip_path)
    install_dir = Path(install_dir)
    if not zip_path.is_file():
        msg = f"Update ZIP not found: {zip_path}"
        _append_update_log(f"ERROR: {msg}")
        print(msg, file=sys.stderr)
        return 1
    if not install_dir.is_dir():
        msg = f"Install dir not found: {install_dir}"
        _append_update_log(f"ERROR: {msg}")
        print(msg, file=sys.stderr)
        return 1

    try:
        logging.basicConfig(level=logging.INFO)
        app = QApplication(sys.argv)
        app.setApplicationName("DataPyn")
        app.setStyle("Fusion")
        app.setFont(QFont("Segoe UI", 10))

        dialog = InAppUpdateDialog(zip_path, version, install_dir, parent_pid)
        dialog.start()
        return 0 if dialog.exec() == QDialog.DialogCode.Accepted else 1
    except Exception as exc:
        _append_update_log(f"ERROR: {exc}")
        logger.exception("In-app update failed to start")
        return 1


def try_run_apply_update_from_argv(argv: list[str] | None = None) -> bool:
    """If argv requests ``--apply-update``, run the updater and exit the process."""
    argv = argv if argv is not None else sys.argv
    try:
        parsed = parse_apply_update_argv(argv)
        if parsed is None:
            return False
        install_dir = Path(parsed.dir) if parsed.dir else Path.cwd()
        code = run_apply_update(
            Path(parsed.zip_path),
            parsed.version,
            install_dir,
            parent_pid=parsed.parent_pid,
        )
        raise SystemExit(code)
    except SystemExit:
        raise
    except Exception as exc:
        _append_update_log(f"ERROR: {exc}")
        logger.exception("In-app update argv handler failed")
        raise SystemExit(1) from exc
