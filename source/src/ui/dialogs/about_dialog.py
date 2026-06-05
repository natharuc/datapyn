"""
About dialog — frameless, matching installer chrome.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.design_system.frameless_dialog import install_frameless_shell
from src.design_system.tokens import get_colors, TYPOGRAPHY
from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


def _logo_pixmap(size: int = 72) -> QPixmap:
    assets = Path(__file__).resolve().parents[2] / "assets"
    for name in ("datapyn_logo.svg", "datapyn-logo.svg"):
        path = assets / name
        if path.is_file():
            renderer = QSvgRenderer(str(path))
            if renderer.isValid():
                pixmap = QPixmap(size, size)
                pixmap.fill(Qt.GlobalColor.transparent)
                from PyQt6.QtGui import QPainter

                painter = QPainter(pixmap)
                renderer.render(painter)
                painter.end()
                return pixmap
    if HAS_QTAWESOME:
        return qta.icon("mdi.database", color="#3369ff").pixmap(size, size)
    return QPixmap()


class AboutDialog(QDialog):
    """About DataPyn — frameless modal."""

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self._version = version
        self.setWindowTitle(S.about.title)
        self.resize(520, 480)
        self._build_ui()

    def _build_ui(self):
        colors = get_colors()
        layout = install_frameless_shell(
            self,
            S.about.title,
            min_width=480,
            min_height=420,
            content_margins=(24, 18, 24, 20),
            content_spacing=14,
        )

        top = QHBoxLayout()
        top.setSpacing(20)

        logo = QLabel()
        logo.setPixmap(_logo_pixmap(72))
        logo.setFixedSize(72, 72)
        top.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        name = QLabel(S.about.ide_name)
        name_font = QFont()
        name_font.setPointSize(16)
        name_font.setBold(True)
        name.setFont(name_font)
        name.setStyleSheet(f"color: {colors.text_primary};")
        title_col.addWidget(name)

        ver = QLabel(S.about.version.format(version=self._version))
        ver_font = QFont()
        ver_font.setPointSize(12)
        ver_font.setBold(True)
        ver.setFont(ver_font)
        ver.setStyleSheet(f"color: {colors.text_primary};")
        title_col.addWidget(ver)

        desc = QLabel(S.about.description)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: {TYPOGRAPHY.text_sm}px;"
        )
        title_col.addWidget(desc)
        title_col.addStretch()
        top.addLayout(title_col, 1)
        layout.addLayout(top)

        def section_heading(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {colors.text_primary}; font-weight: 600; "
                f"font-size: {TYPOGRAPHY.text_sm}px; margin-top: 4px;"
            )
            return lbl

        def bullet_list(items: list[str]) -> QWidget:
            w = QWidget()
            col = QVBoxLayout(w)
            col.setContentsMargins(12, 0, 0, 0)
            col.setSpacing(2)
            for item in items:
                line = QLabel(f"• {item}")
                line.setStyleSheet(
                    f"color: {colors.text_secondary}; font-size: {TYPOGRAPHY.text_sm}px;"
                )
                col.addWidget(line)
            return w

        columns = QHBoxLayout()
        columns.setSpacing(24)

        tech_col = QVBoxLayout()
        tech_col.addWidget(section_heading(S.about.technologies))
        tech_col.addWidget(
            bullet_list(
                [
                    "Python 3.12+",
                    "PyQt6",
                    "Monaco Editor",
                    "Pandas & Polars",
                    "SQLAlchemy",
                    "Matplotlib",
                    "GitHub Copilot SDK",
                ]
            )
        )
        columns.addLayout(tech_col, 1)

        db_col = QVBoxLayout()
        db_col.addWidget(section_heading(S.about.databases))
        db_col.addWidget(
            bullet_list(
                [
                    "Microsoft SQL Server",
                    "MySQL / MariaDB",
                    "PostgreSQL",
                    "SQLite",
                    "Databricks",
                ]
            )
        )
        columns.addLayout(db_col, 1)
        layout.addLayout(columns)

        license_lbl = QLabel(S.about.license)
        license_lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: {TYPOGRAPHY.text_sm}px;")
        layout.addWidget(license_lbl)

        links = QVBoxLayout()
        links.setSpacing(4)
        for text, url in (
            ("Website: datapyn.com", "http://datapyn.com"),
            ("Repository: github.com/natharuc/datapyn", "https://github.com/natharuc/datapyn"),
        ):
            link = QLabel(f'<a href="{url}" style="color: #3369ff;">{text}</a>')
            link.setOpenExternalLinks(True)
            link.setStyleSheet(f"font-size: {TYPOGRAPHY.text_sm}px;")
            links.addWidget(link)
        layout.addLayout(links)

        footer = QLabel(S.about.built_with)
        footer.setStyleSheet(f"color: {colors.text_tertiary}; font-size: {TYPOGRAPHY.text_xs}px;")
        layout.addWidget(footer)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok = QPushButton("OK")
        ok.setMinimumWidth(100)
        ok.clicked.connect(self.accept)
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)
