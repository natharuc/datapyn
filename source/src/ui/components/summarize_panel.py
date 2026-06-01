"""Summarize panel — selection stats and aggregates for the results grid."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QThread, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from src.design_system.tokens import SCROLLBAR_STYLE, get_colors
from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


ZOOM_LEVELS = (85, 100, 115, 130)
DEFAULT_ZOOM_INDEX = 1


class _SummarizeBuildWorker(QObject):
    """Compute summarize stats off the UI thread."""

    finished = pyqtSignal(int, object)
    error = pyqtSignal(int, str)

    def __init__(
        self,
        generation: int,
        df,
        scope: dict,
        result_label: str,
        column_formats: dict,
        numeric_column_indices,
    ):
        super().__init__()
        self._generation = generation
        self._df = df
        self._scope = dict(scope or {})
        self._result_label = result_label
        self._column_formats = dict(column_formats or {})
        self._numeric_column_indices = numeric_column_indices

    def run(self):
        try:
            from src.ui.components.summarize_stats import build_selection_summary

            payload = build_selection_summary(
                self._df,
                self._scope.get("cells") or [],
                row_ranges=self._scope.get("row_ranges"),
                bound_cols=self._scope.get("bound_cols"),
                result_label=self._result_label,
                column_formats=self._column_formats,
                numeric_column_indices=self._numeric_column_indices,
            )
            self.finished.emit(self._generation, payload)
        except Exception as exc:
            self.error.emit(self._generation, str(exc))


class _StatChip(QFrame):
    """Compact stat label + value."""

    def __init__(self, label: str, value: str, *, accent: bool = False, parent=None, zoom: float = 1.0):
        super().__init__(parent)
        self.setObjectName("summarizeStatChip")
        self._zoom = zoom
        layout = QVBoxLayout(self)
        self._apply_layout_metrics(layout)

        self.label = QLabel(label)
        self.label.setObjectName("summarizeStatLabel")
        self.value = QLabel(value or "—")
        self.value.setObjectName("summarizeStatValue")
        self.value.setWordWrap(True)
        self._accent = accent

        layout.addWidget(self.label)
        layout.addWidget(self.value)
        self._apply_fonts()

    def _apply_layout_metrics(self, layout: QVBoxLayout):
        pad = max(2, int(4 * self._zoom))
        layout.setContentsMargins(pad + 2, pad, pad + 2, pad)
        layout.setSpacing(0)

    def set_zoom(self, zoom: float):
        self._zoom = zoom
        self._apply_layout_metrics(self.layout())
        self._apply_fonts()

    def _apply_fonts(self):
        label_font = QFont(self.label.font())
        label_font.setPointSizeF(max(7.0, 7.5 * self._zoom))
        self.label.setFont(label_font)

        value_font = QFont(self.value.font())
        value_font.setPointSizeF(max(8.0, 8.5 * self._zoom))
        value_font.setWeight(QFont.Weight.DemiBold)
        self.value.setFont(value_font)

    def set_value(self, value: str):
        self.value.setText(value or "—")

    def apply_theme(self, tokens, accent_color: str):
        bg = tokens.bg_tertiary if self._accent else tokens.bg_secondary
        value_color = accent_color if self._accent else tokens.text_primary
        self.setStyleSheet(f"""
            QFrame#summarizeStatChip {{
                background-color: {bg};
                border: 1px solid {tokens.border_muted};
                border-radius: 6px;
            }}
            QLabel#summarizeStatLabel {{
                color: {tokens.text_tertiary};
                background: transparent;
            }}
            QLabel#summarizeStatValue {{
                color: {value_color};
                background: transparent;
            }}
        """)


class _ColumnSummaryCard(QFrame):
    """Per-column summary card with optional format menu."""

    format_requested = pyqtSignal(str, object)

    def __init__(self, column: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._column = dict(column or {})
        self.setObjectName("summarizeColumnCard")
        self._chips: List[_StatChip] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)

        self.title = QLabel(self._column.get("name", ""))
        title_font = QFont(self.title.font())
        title_font.setPointSize(10)
        title_font.setWeight(QFont.Weight.DemiBold)
        self.title.setFont(title_font)

        kind = self._column.get("kind", "text")
        self.badge = QLabel(kind.upper())
        self.badge.setObjectName("summarizeKindBadge")

        self.format_btn = QToolButton()
        self.format_btn.setObjectName("summarizeFormatBtn")
        self.format_btn.setToolTip(S.summarize_panel.format_column)
        self.format_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if HAS_QTAWESOME:
            self.format_btn.setIcon(qta.icon("mdi.tune-variant", color="#9aa0a6"))
        self.format_btn.clicked.connect(self._on_format_clicked)

        header.addWidget(self.title, 1)
        header.addWidget(self.badge, 0)
        header.addWidget(self.format_btn, 0)
        root.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)

        labels = S.summarize_panel.headers
        if kind == "numeric":
            specs = [
                ("sum", self._column.get("sum", "—"), True),
                ("avg", self._column.get("avg", "—"), False),
                ("min", self._column.get("min", "—"), False),
                ("max", self._column.get("max", "—"), False),
                ("count", self._column.get("count", "—"), False),
                ("distinct", self._column.get("distinct", "—"), False),
            ]
        else:
            specs = [
                ("count", self._column.get("count", "—"), False),
                ("distinct", self._column.get("distinct", "—"), False),
                ("top", self._column.get("top", "—"), True),
            ]

        for index, (key, value, accent) in enumerate(specs):
            chip = _StatChip(getattr(labels, key, key), str(value), accent=accent, parent=self)
            self._chips.append(chip)
            grid.addWidget(chip, index // 2, index % 2)

        root.addLayout(grid)

    def _on_format_clicked(self):
        self.format_requested.emit(self._column.get("name", ""), self.format_btn)

    def update_column(self, column: Dict[str, Any]):
        self._column = dict(column or {})
        kind = self._column.get("kind", "text")
        self.title.setText(self._column.get("name", ""))
        self.badge.setText(kind.upper())

        if kind == "numeric":
            values = [
                self._column.get("sum", "—"),
                self._column.get("avg", "—"),
                self._column.get("min", "—"),
                self._column.get("max", "—"),
                self._column.get("count", "—"),
                self._column.get("distinct", "—"),
            ]
        else:
            values = [
                self._column.get("count", "—"),
                self._column.get("distinct", "—"),
                self._column.get("top", "—"),
            ]
        for chip, value in zip(self._chips, values):
            chip.set_value(str(value))

    def apply_theme(self, tokens, accent_color: str):
        kind = self._column.get("kind", "text")
        badge_bg = getattr(tokens, "info", "#3b82f6") if kind == "numeric" else getattr(tokens, "warning", "#f59e0b")
        self.setStyleSheet(f"""
            QFrame#summarizeColumnCard {{
                background-color: {tokens.bg_primary};
                border: 1px solid {tokens.border_default};
                border-radius: 8px;
            }}
            QLabel#summarizeKindBadge {{
                color: {tokens.text_primary};
                background-color: {badge_bg};
                border-radius: 4px;
                padding: 1px 6px;
                font-size: 9px;
                font-weight: 600;
            }}
            QToolButton#summarizeFormatBtn {{
                border: 1px solid {tokens.border_muted};
                border-radius: 4px;
                padding: 2px;
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
                background: {tokens.bg_secondary};
            }}
            QToolButton#summarizeFormatBtn:hover {{
                background: {tokens.bg_elevated};
            }}
        """)
        self.title.setStyleSheet(f"color: {tokens.text_primary}; background: transparent;")
        for chip in self._chips:
            chip.apply_theme(tokens, accent_color)


class _AggregateRow(QFrame):
    def __init__(self, label: str, value: str, parent=None, *, zoom: float = 1.0, show_divider: bool = True):
        super().__init__(parent)
        self.setObjectName("summarizeAggregateRow")
        self._zoom = zoom
        self._show_divider = show_divider

        layout = QHBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.label = QLabel(label)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.value = QLabel(value or "—")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self.label, 1)
        layout.addWidget(self.value, 1)

        self._apply_layout_metrics(layout)
        self._apply_fonts()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def _apply_layout_metrics(self, layout: QHBoxLayout):
        pad_x = max(14, int(18 * self._zoom))
        pad_y = max(2, int(3 * self._zoom))
        layout.setContentsMargins(pad_x, pad_y, pad_x, pad_y)
        layout.setSpacing(max(10, int(14 * self._zoom)))
        height = max(20, int(22 * self._zoom))
        self.setFixedHeight(height)

    def set_zoom(self, zoom: float):
        self._zoom = zoom
        self._apply_layout_metrics(self.layout())
        self._apply_fonts()

    def _apply_fonts(self):
        label_font = QFont(self.label.font())
        label_font.setPointSizeF(max(7.0, 7.5 * self._zoom))
        label_font.setWeight(QFont.Weight.Medium)
        label_font.setCapitalization(QFont.Capitalization.AllUppercase)
        self.label.setFont(label_font)

        value_font = QFont(self.value.font())
        value_font.setPointSizeF(max(7.5, 8.5 * self._zoom))
        value_font.setWeight(QFont.Weight.DemiBold)
        self.value.setFont(value_font)

    def set_value(self, value: str):
        self.value.setText(value or "—")

    def apply_theme(self, tokens, accent_color: str):
        border = f"border-bottom: 1px solid {tokens.border_muted};" if self._show_divider else "border: none;"
        self.setStyleSheet(f"""
            QFrame#summarizeAggregateRow {{
                background: transparent;
                {border}
            }}
        """)
        self.label.setStyleSheet(
            f"color: {tokens.text_tertiary}; background: transparent; margin: 0; padding: 0;"
        )
        self.value.setStyleSheet(
            f"color: {accent_color}; background: transparent; margin: 0; padding: 0;"
        )


class SummarizePanel(QWidget):
    """Dock panel that summarizes the focused grid selection."""

    cleared = pyqtSignal()

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._results_viewer = None
        self._payload: Dict[str, Any] = {}
        self._column_cards: List[_ColumnSummaryCard] = []
        self._aggregate_rows: List[_AggregateRow] = []
        self._zoom_index = DEFAULT_ZOOM_INDEX
        self._summarize_dirty = False
        self._summarize_generation = 0
        self._summarize_thread: Optional[QThread] = None
        self._summarize_worker: Optional[_SummarizeBuildWorker] = None
        self._summarize_update_timer: Optional[QTimer] = None
        self._setup_ui()
        self.clear()

    def _zoom_scale(self) -> float:
        return ZOOM_LEVELS[self._zoom_index] / 100.0

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QWidget()
        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(10, 5, 10, 3)
        header_layout.setSpacing(2)

        self.title_label = QLabel()
        title_font = QFont(self.title_label.font())
        title_font.setPointSize(10)
        title_font.setWeight(QFont.Weight.DemiBold)
        self.title_label.setFont(title_font)

        self.subtitle_label = QLabel()
        self.subtitle_label.setWordWrap(True)

        self.zoom_out_btn = QToolButton()
        self.zoom_out_btn.setObjectName("summarizeZoomBtn")
        self.zoom_out_btn.setToolTip(S.summarize_panel.zoom_out)
        self.zoom_out_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if HAS_QTAWESOME:
            self.zoom_out_btn.setIcon(qta.icon("mdi.magnify-minus-outline", color="#9aa0a6"))

        self.zoom_label = QLabel()
        self.zoom_label.setObjectName("summarizeZoomLabel")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setMinimumWidth(34)

        self.zoom_in_btn = QToolButton()
        self.zoom_in_btn.setObjectName("summarizeZoomBtn")
        self.zoom_in_btn.setToolTip(S.summarize_panel.zoom_in)
        self.zoom_in_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if HAS_QTAWESOME:
            self.zoom_in_btn.setIcon(qta.icon("mdi.magnify-plus-outline", color="#9aa0a6"))

        self.zoom_out_btn.clicked.connect(self._zoom_out)
        self.zoom_in_btn.clicked.connect(self._zoom_in)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        title_row.addWidget(self.title_label, 1)
        title_row.addWidget(self.zoom_out_btn, 0)
        title_row.addWidget(self.zoom_label, 0)
        title_row.addWidget(self.zoom_in_btn, 0)

        self.grand_total_frame = QFrame()
        self.grand_total_frame.setObjectName("summarizeGrandTotal")
        grand_layout = QHBoxLayout(self.grand_total_frame)
        grand_layout.setContentsMargins(10, 6, 10, 6)
        self.grand_total_caption = QLabel(S.summarize_panel.grand_total)
        self.grand_total_value = QLabel("—")
        grand_value_font = QFont(self.grand_total_value.font())
        grand_value_font.setPointSize(14)
        grand_value_font.setWeight(QFont.Weight.Bold)
        self.grand_total_value.setFont(grand_value_font)
        self.grand_total_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grand_layout.addWidget(self.grand_total_caption, 0)
        grand_layout.addWidget(self.grand_total_value, 1)

        header_layout.addLayout(title_row)
        header_layout.addWidget(self.subtitle_label)

        layout.addWidget(self.header)
        layout.addWidget(self.grand_total_frame)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setObjectName("summarizeTabs")

        self.summarize_page = QWidget()
        summarize_layout = QVBoxLayout(self.summarize_page)
        summarize_layout.setContentsMargins(0, 0, 0, 0)
        summarize_layout.setSpacing(0)

        self.empty_label = QLabel()
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)

        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_host = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.setContentsMargins(8, 6, 8, 6)
        self.cards_layout.setSpacing(6)
        self.cards_layout.addStretch(1)
        self.cards_scroll.setWidget(self.cards_host)

        summarize_layout.addWidget(self.empty_label)
        summarize_layout.addWidget(self.cards_scroll, 1)

        self.aggregate_page = QWidget()
        aggregate_layout = QVBoxLayout(self.aggregate_page)
        aggregate_layout.setContentsMargins(0, 0, 0, 0)
        aggregate_layout.setSpacing(0)

        self.aggregate_empty = QLabel()
        self.aggregate_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.aggregate_empty.setWordWrap(True)

        self.aggregate_scroll = QScrollArea()
        self.aggregate_scroll.setWidgetResizable(True)
        self.aggregate_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.aggregate_host = QWidget()
        self.aggregate_layout = QVBoxLayout(self.aggregate_host)
        self.aggregate_layout.setContentsMargins(8, 6, 8, 6)
        self.aggregate_layout.setSpacing(0)
        self.aggregate_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.aggregate_inner = QFrame()
        self.aggregate_inner.setObjectName("summarizeAggregateCard")
        self.aggregate_inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.aggregate_inner_layout = QVBoxLayout(self.aggregate_inner)
        self.aggregate_inner_layout.setContentsMargins(0, 0, 0, 0)
        self.aggregate_inner_layout.setSpacing(0)
        self.aggregate_layout.addWidget(self.aggregate_inner)
        self.aggregate_scroll.setWidget(self.aggregate_host)

        aggregate_layout.addWidget(self.aggregate_empty)
        aggregate_layout.addWidget(self.aggregate_scroll, 1)

        self.tabs.addTab(self.summarize_page, S.summarize_panel.tab_summarize)
        self.tabs.addTab(self.aggregate_page, S.summarize_panel.tab_aggregate)
        layout.addWidget(self.tabs, 1)

        self._apply_theme()
        self._update_zoom_controls()

    def _zoom_out(self):
        if self._zoom_index > 0:
            self._zoom_index -= 1
            self._apply_zoom()

    def _zoom_in(self):
        if self._zoom_index < len(ZOOM_LEVELS) - 1:
            self._zoom_index += 1
            self._apply_zoom()

    def _update_zoom_controls(self):
        percent = ZOOM_LEVELS[self._zoom_index]
        self.zoom_label.setText(f"{percent}%")
        self.zoom_out_btn.setEnabled(self._zoom_index > 0)
        self.zoom_in_btn.setEnabled(self._zoom_index < len(ZOOM_LEVELS) - 1)

    def _apply_zoom(self):
        self._update_zoom_controls()
        scale = self._zoom_scale()
        for card in self._column_cards:
            title_font = QFont(card.title.font())
            title_font.setPointSizeF(max(9.0, 10.0 * scale))
            title_font.setWeight(QFont.Weight.DemiBold)
            card.title.setFont(title_font)
            for chip in card._chips:
                chip.set_zoom(scale)
        for row in self._aggregate_rows:
            row.set_zoom(scale)

        grand_value_font = QFont(self.grand_total_value.font())
        grand_value_font.setPointSizeF(max(12.0, 14.0 * scale))
        grand_value_font.setWeight(QFont.Weight.Bold)
        self.grand_total_value.setFont(grand_value_font)
        self._apply_theme()

    def set_theme_manager(self, theme_manager):
        self.theme_manager = theme_manager
        self._apply_theme()

    def _accent_color(self, tokens) -> str:
        return getattr(tokens, "info", "#7ec8ff")

    def _apply_theme(self):
        tokens = get_colors()
        if self.theme_manager:
            app_colors = self.theme_manager.get_app_colors()
            fg = app_colors.get("foreground", tokens.text_primary)
            bg = app_colors.get("background", tokens.bg_primary)
        else:
            fg = tokens.text_primary
            bg = tokens.bg_primary

        accent = self._accent_color(tokens)
        self.title_label.setStyleSheet(f"color: {fg};")
        self.subtitle_label.setStyleSheet(f"color: {tokens.text_secondary}; font-size: 10px;")
        self.empty_label.setStyleSheet(
            f"color: {tokens.text_tertiary}; font-size: 11px; padding: 16px;"
        )
        self.aggregate_empty.setStyleSheet(
            f"color: {tokens.text_tertiary}; font-size: 11px; padding: 16px;"
        )
        self.grand_total_frame.setStyleSheet(f"""
            QFrame#summarizeGrandTotal {{
                background-color: {tokens.bg_tertiary};
                border-top: 1px solid {tokens.border_default};
                border-bottom: 1px solid {tokens.border_default};
            }}
        """)
        self.grand_total_caption.setStyleSheet(f"color: {tokens.text_secondary}; font-size: 10px;")
        self.grand_total_value.setStyleSheet(f"color: {accent};")
        self.zoom_label.setStyleSheet(f"color: {tokens.text_tertiary}; font-size: 9px; padding: 0 2px;")
        zoom_btn_style = f"""
            QToolButton#summarizeZoomBtn {{
                border: 1px solid {tokens.border_muted};
                border-radius: 3px;
                padding: 0;
                min-width: 18px;
                max-width: 18px;
                min-height: 18px;
                max-height: 18px;
                background: {tokens.bg_secondary};
            }}
            QToolButton#summarizeZoomBtn:hover {{
                background: {tokens.bg_elevated};
            }}
            QToolButton#summarizeZoomBtn:disabled {{
                color: {tokens.text_tertiary};
            }}
        """
        self.zoom_out_btn.setStyleSheet(zoom_btn_style)
        self.zoom_in_btn.setStyleSheet(zoom_btn_style)
        self.tabs.setStyleSheet(f"""
            QTabWidget#summarizeTabs::pane {{
                border: none;
                background: {bg};
            }}
            QTabBar::tab {{
                background: {tokens.bg_secondary};
                color: {tokens.text_secondary};
                padding: 5px 10px;
                margin-right: 2px;
                font-size: 10px;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
            }}
            QTabBar::tab:selected {{
                background: {tokens.bg_primary};
                color: {fg};
                font-weight: 600;
            }}
            {SCROLLBAR_STYLE}
        """)
        self.cards_scroll.setStyleSheet(f"background: {bg}; border: none; {SCROLLBAR_STYLE}")
        self.aggregate_scroll.setStyleSheet(f"background: {bg}; border: none; {SCROLLBAR_STYLE}")
        self.aggregate_host.setStyleSheet(f"background: {bg};")
        self.aggregate_inner.setStyleSheet(f"""
            QFrame#summarizeAggregateCard {{
                background: {tokens.bg_secondary};
                border: 1px solid {tokens.border_default};
                border-radius: 8px;
            }}
        """)

        for card in self._column_cards:
            card.apply_theme(tokens, accent)
        for row in self._aggregate_rows:
            row.apply_theme(tokens, accent)

    def clear(self):
        self._payload = {}
        self.title_label.setText(S.summarize_panel.title)
        self.subtitle_label.setText("")
        self.grand_total_frame.setVisible(False)
        self.empty_label.setText(S.summarize_panel.empty_hint)
        self.aggregate_empty.setText(S.summarize_panel.empty_hint)
        self._set_content_visible(False)
        self._clear_cards()
        self._clear_aggregate_rows()
        self.cleared.emit()

    def _set_content_visible(self, visible: bool):
        self.empty_label.setVisible(not visible)
        self.cards_scroll.setVisible(visible)
        self.aggregate_empty.setVisible(not visible)
        self.aggregate_scroll.setVisible(visible)

    def _clear_cards(self):
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._column_cards.clear()

    def _clear_aggregate_rows(self):
        while self.aggregate_inner_layout.count():
            item = self.aggregate_inner_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._aggregate_rows.clear()

    def _rebuild_cards(self, columns: List[Dict[str, Any]]):
        self._clear_cards()
        tokens = get_colors()
        accent = self._accent_color(tokens)
        scale = self._zoom_scale()
        for column in columns:
            card = _ColumnSummaryCard(column, parent=self.cards_host)
            card.format_requested.connect(self._on_format_requested)
            for chip in card._chips:
                chip.set_zoom(scale)
            title_font = QFont(card.title.font())
            title_font.setPointSizeF(max(9.0, 10.0 * scale))
            title_font.setWeight(QFont.Weight.DemiBold)
            card.title.setFont(title_font)
            card.apply_theme(tokens, accent)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
            self._column_cards.append(card)

    def _rebuild_aggregates(self, aggregates: List[Dict[str, str]]):
        self._clear_aggregate_rows()
        labels = S.summarize_panel.aggregates
        tokens = get_colors()
        accent = self._accent_color(tokens)
        scale = self._zoom_scale()
        last_index = len(aggregates) - 1
        for index, item in enumerate(aggregates):
            key = item.get("key", "")
            label = getattr(labels, key, key.upper())
            row = _AggregateRow(
                label,
                item.get("value", "—"),
                parent=self.aggregate_inner,
                zoom=scale,
                show_divider=index < last_index,
            )
            row.apply_theme(tokens, accent)
            self.aggregate_inner_layout.addWidget(row)
            self._aggregate_rows.append(row)

    def _on_format_requested(self, column_name: str, button):
        viewer = self._results_viewer
        if viewer is None or not column_name:
            return
        global_pos = button.mapToGlobal(button.rect().bottomLeft())
        if hasattr(viewer, "show_column_format_menu"):
            viewer.show_column_format_menu(column_name, global_pos)

    def set_summary(self, payload: Optional[Dict[str, Any]]):
        payload = payload or {}
        self._payload = payload
        columns = payload.get("columns") or []
        aggregates = payload.get("aggregates") or []

        if not columns:
            self.clear()
            if payload.get("subtitle") == "no_data":
                self.empty_label.setText(S.summarize_panel.no_data)
                self.aggregate_empty.setText(S.summarize_panel.no_data)
            return

        title = payload.get("title") or S.summarize_panel.title
        self.title_label.setText(title)

        scope = payload.get("scope", "all")
        rows_count = int(payload.get("rows_selected") or 0)
        cols_count = int(payload.get("cols_selected") or 0)
        cells_count = int(payload.get("cells_selected") or 0)
        if scope == "selection":
            self.subtitle_label.setText(
                S.summarize_panel.selection_subtitle.format(
                    rows=rows_count,
                    cols=cols_count,
                    cells=cells_count,
                )
            )
        else:
            self.subtitle_label.setText(
                S.summarize_panel.all_rows_subtitle.format(
                    rows=rows_count,
                    cols=cols_count,
                )
            )

        grand_total = payload.get("grand_total_display")
        numeric_cols = [col for col in columns if col.get("kind") == "numeric"]
        show_grand_total = grand_total is not None and (
            len(numeric_cols) > 1 or int(payload.get("cells_selected") or 0) > 1
        )
        self.grand_total_frame.setVisible(show_grand_total)
        if show_grand_total:
            self.grand_total_value.setText(grand_total)

        self._rebuild_cards(columns)
        self._rebuild_aggregates(aggregates)
        self._set_content_visible(True)
        self._apply_theme()

    def update_from_results_viewer(self, results_viewer) -> None:
        self._results_viewer = results_viewer
        if results_viewer is None or not hasattr(results_viewer, "build_summarize_payload"):
            self.clear()
            return
        if not results_viewer.is_grid_active():
            self.clear()
            return
        if not self.isVisible():
            self._summarize_dirty = True
            return
        self._schedule_summarize_update()

    def schedule_update_from_results_viewer(self, results_viewer) -> None:
        """Deferred entry point for session/result tab switches."""
        self._results_viewer = results_viewer
        if not self.isVisible():
            self._summarize_dirty = True
            return
        self._schedule_summarize_update()

    def _schedule_summarize_update(self):
        timer = self._summarize_update_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(48)
            timer.timeout.connect(self._start_summarize_update)
            self._summarize_update_timer = timer
        timer.start()

    def _start_summarize_update(self):
        viewer = self._results_viewer
        if viewer is None or not viewer.is_grid_active() or not self.isVisible():
            return

        scope = viewer.get_summarize_selection_scope()
        from src.ui.components.summarize_stats import has_summarize_selection

        if not has_summarize_selection(scope):
            self._cancel_summarize_worker()
            self.clear()
            return

        self._summarize_generation += 1
        generation = self._summarize_generation
        prepared = getattr(viewer.model, "_prepared", None)
        numeric_indices = None
        if prepared is not None and getattr(prepared, "numeric_column_indices", None):
            numeric_indices = set(prepared.numeric_column_indices)

        self._cancel_summarize_worker()
        worker = _SummarizeBuildWorker(
            generation,
            viewer.current_df,
            scope,
            viewer.get_current_result_label(),
            getattr(viewer, "_column_formats", {}),
            numeric_indices,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_summarize_payload_ready)
        worker.error.connect(self._on_summarize_payload_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._clear_summarize_worker(thread))
        self._summarize_thread = thread
        self._summarize_worker = worker
        thread.start()

    def _clear_summarize_worker(self, thread: QThread):
        if self._summarize_thread is thread:
            self._summarize_thread = None
            self._summarize_worker = None

    def _cancel_summarize_worker(self):
        thread = self._summarize_thread
        if thread is not None and thread.isRunning():
            thread.quit()
        self._summarize_thread = None
        self._summarize_worker = None

    def _on_summarize_payload_ready(self, generation: int, payload: dict):
        if generation != self._summarize_generation:
            return
        self._summarize_dirty = False
        self.set_summary(payload)

    def _on_summarize_payload_error(self, generation: int, message: str):
        if generation != self._summarize_generation:
            return
        self.clear()

    def showEvent(self, event):
        super().showEvent(event)
        if self._summarize_dirty and self._results_viewer is not None:
            self._summarize_dirty = False
            self._schedule_summarize_update()
