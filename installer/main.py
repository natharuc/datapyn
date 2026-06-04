"""
DataPyn Setup — lightweight Windows installer (downloads latest release ZIP).
"""

from __future__ import annotations

import sys
from pathlib import Path

_INSTALLER_DIR = Path(__file__).resolve().parent
if str(_INSTALLER_DIR) not in sys.path:
    sys.path.insert(0, str(_INSTALLER_DIR))

import _bundle_deps  # noqa: F401 — PyInstaller: stdlib for windows_installer (datas/exec)

from _bootstrap import load_windows_installer

wi = load_windows_installer()

from PyQt6.QtCore import Qt, QPoint, QThread, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
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

C_BG_DEEP = "#070b12"
C_BG_BASE = "#0c111b"
C_BG_CARD = "#161f30"
C_BORDER = "rgba(148, 163, 184, 0.18)"
C_TEXT = "#eef2f7"
C_MUTED = "#8b9cb3"
C_DIM = "#5c6d85"
C_ACCENT = "#3369ff"
C_CYAN = "#33c2ff"
C_SUCCESS = "#4ade80"
LOGO_SIZE = 56


def _assets_dir() -> Path:
    """Dev: repo source/src/assets. Frozen: PyInstaller datas folder."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets"
    return _INSTALLER_DIR.parent / "source" / "src" / "assets"


def _asset_path(*names: str) -> Path | None:
    folder = _assets_dir()
    for name in names:
        path = folder / name
        if path.is_file():
            return path
    return None


def _load_logo_pixmap(size: int = 40) -> QPixmap:
    svg_path = _asset_path("datapyn_logo.svg", "datapyn-logo.svg")
    if svg_path is not None:
        renderer = QSvgRenderer(str(svg_path))
        if renderer.isValid():
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            if not pixmap.isNull():
                return pixmap

    ico_path = _asset_path("datapyn-logo.ico")
    if ico_path is not None:
        icon = QIcon(str(ico_path))
        pixmap = icon.pixmap(size, size)
        if not pixmap.isNull():
            return pixmap
    return QPixmap()


class SuccessBadge(QWidget):
    """Rounded success indicator (vector check, no text glyphs)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(48, 48)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        fill = QColor(C_SUCCESS)
        fill.setAlpha(38)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(2, 2, 44, 44)

        pen = QPen(QColor(C_SUCCESS))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(4, 4, 40, 40)

        pen.setWidthF(2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        check = QPainterPath()
        check.moveTo(14, 24)
        check.lineTo(21, 31)
        check.lineTo(34, 16)
        painter.drawPath(check)
        painter.end()


class TitleBar(QWidget):
    """Draggable header for frameless window."""

    def __init__(self, parent_window: QMainWindow):
        super().__init__(parent_window)
        self._window = parent_window
        self._drag_pos: QPoint | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 8, 8)
        row.setSpacing(0)

        row.addStretch()

        close_btn = QPushButton("×")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(parent_window.close)
        row.addWidget(close_btn)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None


class InstallWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str, str)
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

            if self.mode == "repair":
                exe, version = wi.repair_installation(self.install_dir, on_progress=on_progress)
                self.finished_ok.emit(str(exe), version)
                return

            exe, release = wi.install_latest_release(self.install_dir, on_progress=on_progress)
            self.finished_ok.emit(str(exe), release.version)
        except Exception as exc:
            self.failed.emit(str(exc))


class SetupWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DataPyn Setup")
        self.setFixedSize(440, 380)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        installed, install_dir, installed_version = wi.detect_existing_installation()
        self._is_installed = installed
        self._install_dir = install_dir
        self._installed_version = installed_version
        self._worker: InstallWorker | None = None
        self._exe_path: str | None = None

        for name in ("datapyn-logo.ico", "datapyn_logo.svg"):
            p = _asset_path(name)
            if p is not None:
                self.setWindowIcon(QIcon(str(p)))
                break

        shell = QFrame()
        shell.setObjectName("shell")
        shadow = QGraphicsDropShadowEffect(shell)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(Qt.GlobalColor.black)
        shell.setGraphicsEffect(shadow)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._title_bar = TitleBar(self)
        root.addWidget(self._title_bar)

        accent = QFrame()
        accent.setObjectName("accentLine")
        accent.setFixedHeight(2)
        root.addWidget(accent)

        body = QWidget()
        body.setObjectName("body")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(36, 8, 36, 36)
        body_layout.setSpacing(8)

        brand = QWidget()
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(0, 4, 0, 0)
        brand_layout.setSpacing(6)
        brand_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._logo_label = QLabel()
        self._logo_label.setPixmap(_load_logo_pixmap(LOGO_SIZE))
        self._logo_label.setFixedSize(LOGO_SIZE, LOGO_SIZE)
        self._logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_layout.addWidget(self._logo_label, 0, Qt.AlignmentFlag.AlignHCenter)

        brand_title = QLabel("DataPyn")
        brand_title.setObjectName("title")
        brand_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_layout.addWidget(brand_title)

        body_layout.addWidget(brand)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._page_welcome())
        self._stack.addWidget(self._page_progress())
        self._stack.addWidget(self._page_done())
        body_layout.addWidget(self._stack)
        root.addWidget(body, 1)

        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(16, 16, 16, 16)
        outer_layout.addWidget(shell)
        self.setCentralWidget(outer)
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(
            f"""
            QFrame#shell {{
                background: {C_BG_BASE};
                border: 1px solid {C_BORDER};
                border-radius: 14px;
            }}
            QFrame#accentLine {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {C_ACCENT}, stop:0.5 {C_CYAN}, stop:1 {C_ACCENT});
                border: none;
            }}
            QWidget#body {{
                background: transparent;
            }}
            QLabel {{
                color: {C_TEXT};
                background: transparent;
            }}
            QLabel#title {{
                font-size: 18px;
                font-weight: 600;
            }}
            QLabel#muted {{
                color: {C_DIM};
                font-size: 11px;
            }}
            QLabel#path {{
                color: {C_MUTED};
                font-size: 10px;
                font-family: "Cascadia Mono", Consolas, monospace;
            }}
            QPushButton {{
                background: {C_ACCENT};
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 10px 24px;
                font-weight: 600;
                font-size: 13px;
                min-width: 108px;
            }}
            QPushButton:hover {{
                background: #4f80ff;
            }}
            QPushButton:pressed {{
                background: #2858e0;
            }}
            QPushButton#ghost {{
                background: transparent;
                color: {C_MUTED};
                border: 1px solid {C_BORDER};
            }}
            QPushButton#ghost:hover {{
                color: {C_TEXT};
                border-color: rgba(51, 105, 255, 0.45);
            }}
            QPushButton#closeBtn {{
                background: transparent;
                color: {C_MUTED};
                border: none;
                border-radius: 8px;
                font-size: 18px;
                min-width: 32px;
                padding: 0;
            }}
            QPushButton#closeBtn:hover {{
                background: rgba(239, 68, 68, 0.12);
                color: #f87171;
            }}
            QProgressBar {{
                border: none;
                border-radius: 4px;
                background: {C_BG_CARD};
                height: 6px;
            }}
            QProgressBar::chunk {{
                border-radius: 4px;
                background: {C_ACCENT};
            }}
            """
        )

    def _centered_page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        return page, layout

    def _button_row(self, primary_text: str, primary_slot, ghost_text: str, ghost_slot) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ghost = QPushButton(ghost_text)
        ghost.setObjectName("ghost")
        ghost.setCursor(Qt.CursorShape.PointingHandCursor)
        ghost.clicked.connect(ghost_slot)
        primary = QPushButton(primary_text)
        primary.setCursor(Qt.CursorShape.PointingHandCursor)
        primary.clicked.connect(primary_slot)
        h.addWidget(ghost)
        h.addWidget(primary)
        return row

    def _page_welcome(self) -> QWidget:
        page, layout = self._centered_page()
        layout.setSpacing(12)

        if self._is_installed:
            ver = self._installed_version or "?"
            sub = QLabel(f"Instalação detectada · v{ver}")
            hint = QLabel("Reparar baixa a versão mais recente e substitui os arquivos.")
            primary_label, primary_slot = "Reparar", self._start_repair
        else:
            sub = QLabel("Instalar")
            hint = QLabel("Baixa a versão mais recente do GitHub.")
            primary_label, primary_slot = "Instalar", self._start_install

        sub.setObjectName("muted")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        path = QLabel(str(self._install_dir))
        path.setObjectName("path")
        path.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(path)

        layout.addStretch()
        layout.addWidget(self._button_row(primary_label, primary_slot, "Cancelar", self.close))
        return page

    def _page_progress(self) -> QWidget:
        page, layout = self._centered_page()
        layout.setSpacing(12)

        layout.addStretch()

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedWidth(280)
        layout.addWidget(self._progress_bar, 0, Qt.AlignmentFlag.AlignHCenter)

        self._progress_status = QLabel("…")
        self._progress_status.setObjectName("muted")
        self._progress_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._progress_status)

        layout.addStretch()
        return page

    def _page_done(self) -> QWidget:
        page, layout = self._centered_page()
        layout.setSpacing(12)

        layout.addStretch()

        layout.addWidget(SuccessBadge(), 0, Qt.AlignmentFlag.AlignHCenter)

        self._done_label = QLabel("")
        self._done_label.setObjectName("title")
        self._done_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._done_label)

        layout.addStretch()
        layout.addWidget(
            self._button_row("Abrir", self._launch_app, "Fechar", self.close)
        )
        return page

    def _begin_worker(self, mode: str):
        self._stack.setCurrentIndex(1)
        self._worker = InstallWorker(self._install_dir, mode, None, "")
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _start_install(self):
        self._begin_worker("install")

    def _start_repair(self):
        self._begin_worker("repair")

    def _on_progress(self, pct: int, msg: str):
        self._progress_bar.setValue(pct)
        self._progress_status.setText(msg)

    def _on_success(self, exe_path: str, version: str):
        self._exe_path = exe_path
        self._done_label.setText(f"v{version}")
        self._stack.setCurrentIndex(2)

    def _on_failed(self, message: str):
        QMessageBox.critical(self, "Falha na instalação", message)
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

    if "--repair" in flags:
        install_dir = Path(flags.get("--dir", wi.DEFAULT_INSTALL_DIR))
        try:
            exe, version = wi.repair_installation(install_dir)
            wi.launch_application(exe)
            return 0
        except Exception as exc:
            print(exc, file=sys.stderr)
            return 1

    if "--update" in flags:
        zip_path = Path(flags["--update"])
        version = flags.get("--version", "0.0.0")
        install_dir = Path(flags.get("--dir", wi.DEFAULT_INSTALL_DIR))
        try:
            wi.wait_for_datapyn_exit()
            exe = wi.install_from_zip(zip_path, install_dir, version)
            wi.launch_application(exe)
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
