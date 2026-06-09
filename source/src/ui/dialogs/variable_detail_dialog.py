"""Dialog showing full details for a session variable."""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout

from src.core.session_result_storage import format_storage_size, _to_pandas_dataframe
from src.design_system.button import SecondaryButton
from src.design_system.frameless_dialog import frameless_body_stylesheet, install_frameless_shell
from src.design_system.tokens import SCROLLBAR_STYLE, get_colors
from src.language import S


def _build_variable_detail_text(name: str, value: Any, storage_bytes: Optional[int]) -> str:
    lines = [
        f"{S.variables_panel.detail_name}: {name}",
        f"{S.variables_panel.detail_type}: {type(value).__name__}",
    ]

    if storage_bytes is not None and storage_bytes > 0:
        lines.append(
            f"{S.variables_panel.detail_storage}: "
            f"{S.variables_panel.storage_saved.format(size=format_storage_size(storage_bytes))}"
        )
    elif _to_pandas_dataframe(value) is not None:
        lines.append(
            f"{S.variables_panel.detail_storage}: {S.variables_panel.storage_not_saved}"
        )
    else:
        lines.append(f"{S.variables_panel.detail_storage}: {S.variables_panel.storage_not_applicable}")

    lines.append("")

    if isinstance(value, pd.DataFrame):
        lines.append(f"{S.variables_panel.detail_shape}: {value.shape[0]:,} rows × {value.shape[1]} cols")
        lines.append(f"{S.variables_panel.detail_columns}: {', '.join(map(str, value.columns.tolist()))}")
        lines.append("")
        lines.append(S.variables_panel.detail_dtypes)
        lines.append(str(value.dtypes))
        lines.append("")
        lines.append(S.variables_panel.detail_preview)
        lines.append(value.head(20).to_string())
    elif isinstance(value, pd.Series):
        lines.append(f"{S.variables_panel.detail_size}: {len(value):,}")
        lines.append(f"{S.variables_panel.detail_dtype}: {value.dtype}")
        lines.append("")
        lines.append(S.variables_panel.detail_preview)
        lines.append(value.head(20).to_string())
    elif isinstance(value, (list, tuple, dict)):
        lines.append(f"{S.variables_panel.detail_size}: {len(value):,}")
        lines.append("")
        lines.append(S.variables_panel.detail_preview)
        text = repr(value)
        lines.append(text[:8000] + ("..." if len(text) > 8000 else ""))
    elif isinstance(value, str):
        lines.append(f"{S.variables_panel.detail_size}: {len(value):,} chars")
        lines.append("")
        lines.append(S.variables_panel.detail_preview)
        lines.append(value[:8000] + ("..." if len(value) > 8000 else ""))
    else:
        lines.append(S.variables_panel.detail_preview)
        text = repr(value)
        lines.append(text[:8000] + ("..." if len(text) > 8000 else ""))

    return "\n".join(lines)


class VariableDetailDialog(QDialog):
    """Read-only detail view for a single session variable."""

    def __init__(
        self,
        name: str,
        value: Any,
        storage_bytes: Optional[int] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._name = name
        self._value = value
        self._storage_bytes = storage_bytes
        self._setup_ui()

    def _setup_ui(self) -> None:
        colors = get_colors()
        title = S.variables_panel.detail_dialog_title.format(name=self._name)

        self.setWindowTitle(title)
        self.resize(640, 480)

        layout = install_frameless_shell(
            self,
            title,
            min_width=420,
            min_height=280,
            content_margins=(20, 14, 20, 16),
            content_spacing=12,
            resizable=True,
        )
        self.setStyleSheet(self.styleSheet() + frameless_body_stylesheet())

        subtitle = QLabel(type(self._value).__name__)
        subtitle.setStyleSheet(
            f"color: {colors.text_tertiary}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(subtitle)

        body = QTextEdit()
        body.setReadOnly(True)
        body.setFont(QFont("Consolas", 10))
        body.setPlainText(
            _build_variable_detail_text(self._name, self._value, self._storage_bytes)
        )
        body.setStyleSheet(
            f"""
            QTextEdit {{
                background-color: {colors.bg_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 6px;
                padding: 8px;
            }}
            {SCROLLBAR_STYLE}
            """
        )
        layout.addWidget(body, 1)

        actions = QHBoxLayout()
        actions.addStretch()
        btn_close = SecondaryButton(S.variables_panel.detail_btn_close, size="sm")
        btn_close.clicked.connect(self.accept)
        actions.addWidget(btn_close)
        layout.addLayout(actions)
