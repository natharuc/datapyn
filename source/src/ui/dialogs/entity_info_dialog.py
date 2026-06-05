"""
Entity information dialog.

Shows relation metadata gathered in the background from the active database.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.design_system.button import SecondaryButton
from src.design_system.tokens import get_colors, RADIUS
from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class EntityInfoDialog(QDialog):
    """Displays database metadata for a table, view, procedure, function, or trigger."""

    def __init__(self, entity_name: str, parent=None):
        super().__init__(parent)
        self._entity_name = entity_name
        self._summary_cards: dict[str, QLabel] = {}
        self._setup_ui()

    def _setup_ui(self):
        colors = get_colors()
        from src.design_system.frameless_dialog import install_frameless_shell

        self.setWindowTitle(S.entity_info.dialog_title)
        self.resize(860, 720)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: transparent;
                color: {colors.text_primary};
            }}
            """
        )

        layout = install_frameless_shell(
            self,
            S.entity_info.dialog_title,
            min_width=680,
            min_height=600,
            content_margins=(20, 16, 20, 18),
            content_spacing=16,
        )

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)

        if HAS_QTAWESOME:
            icon_label = QLabel()
            icon_label.setPixmap(
                qta.icon("mdi.database-search", color=colors.interactive_primary).pixmap(22, 22)
            )
            title_row.addWidget(icon_label)

        self._title_label = QLabel(self._entity_name)
        self._title_label.setStyleSheet(
            f"color: {colors.text_primary}; font-size: 20px; font-weight: 700;"
        )
        title_row.addWidget(self._title_label, 1)
        header_layout.addLayout(title_row)

        self._path_label = QLabel()
        self._path_label.setStyleSheet(
            f"color: {colors.text_tertiary}; font-size: 11px; font-family: monospace;"
        )
        self._path_label.hide()
        header_layout.addWidget(self._path_label)

        self._subtitle_label = QLabel(S.entity_info.loading)
        self._subtitle_label.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 12px;"
        )
        header_layout.addWidget(self._subtitle_label)
        layout.addWidget(header)

        self._message_banner = QLabel()
        self._message_banner.setWordWrap(True)
        self._message_banner.hide()
        layout.addWidget(self._message_banner)

        summary_panel = QFrame()
        summary_panel.setObjectName("entitySummaryPanel")
        summary_panel.setStyleSheet(
            f"""
            QFrame#entitySummaryPanel {{
                background-color: {colors.bg_secondary};
                border-radius: {RADIUS.radius_md}px;
                border: none;
            }}
            """
        )
        self._summary_layout = QGridLayout(summary_panel)
        self._summary_layout.setContentsMargins(16, 14, 16, 14)
        self._summary_layout.setHorizontalSpacing(20)
        self._summary_layout.setVerticalSpacing(14)

        summary_fields = [
            ("entity_type", S.entity_info.field_type),
            ("database", S.entity_info.field_database),
            ("catalog", S.entity_info.field_catalog),
            ("schema", S.entity_info.field_schema),
            ("row_count", S.entity_info.field_rows),
            ("size", S.entity_info.field_size),
        ]
        for index, (field_key, label_text) in enumerate(summary_fields):
            card = self._create_summary_card(label_text)
            self._summary_layout.addWidget(card, index // 3, index % 3)
            self._summary_cards[field_key] = card.findChild(QLabel, "value")
        layout.addWidget(summary_panel)

        self._columns_header = QLabel(S.entity_info.section_columns)
        self._columns_header.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 11px; font-weight: 600;"
            f" letter-spacing: 0.4px; padding-top: 4px;"
        )
        layout.addWidget(self._columns_header)

        self._columns_table = self._create_table(
            [
                S.entity_info.columns_name,
                S.entity_info.columns_type,
                S.entity_info.columns_nullable,
                S.entity_info.columns_default,
            ]
        )
        layout.addWidget(self._columns_table, 1)

        self._indexes_header = QLabel(S.entity_info.section_indexes)
        self._indexes_header.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 11px; font-weight: 600;"
            f" letter-spacing: 0.4px; padding-top: 4px;"
        )
        layout.addWidget(self._indexes_header)

        self._indexes_table = self._create_table(
            [
                S.entity_info.indexes_name,
                S.entity_info.indexes_type,
                S.entity_info.indexes_columns,
            ]
        )
        layout.addWidget(self._indexes_table, 1)

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_button = SecondaryButton(S.entity_info.button_close, size="sm")
        close_button.clicked.connect(self.close)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.set_loading()

    def _create_summary_card(self, label_text: str) -> QWidget:
        colors = get_colors()
        card = QWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(2)

        label = QLabel(label_text.upper())
        label.setStyleSheet(
            f"color: {colors.text_tertiary}; font-size: 10px; font-weight: 600;"
            f" letter-spacing: 0.5px;"
        )
        card_layout.addWidget(label)

        value = QLabel(S.entity_info.not_available)
        value.setObjectName("value")
        value.setWordWrap(True)
        value.setStyleSheet(
            f"color: {colors.text_primary}; font-size: 14px; font-weight: 600;"
        )
        card_layout.addWidget(value)
        return card

    def _create_table(self, headers: list[str]) -> QTableWidget:
        colors = get_colors()
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: {colors.bg_secondary};
                color: {colors.text_primary};
                border: none;
                border-radius: {RADIUS.radius_md}px;
                font-size: 11px;
                outline: none;
            }}
            QHeaderView::section {{
                background-color: transparent;
                color: {colors.text_tertiary};
                border: none;
                border-bottom: 1px solid {colors.border_muted};
                padding: 8px 10px;
                font-weight: 600;
                font-size: 10px;
                text-transform: uppercase;
            }}
            QTableWidget::item {{
                padding: 8px 10px;
                border-bottom: 1px solid {colors.border_muted};
            }}
            QTableWidget::item:alternate {{
                background-color: {colors.bg_tertiary};
            }}
            """
        )
        return table

    def set_loading(self):
        self._subtitle_label.setText(S.entity_info.loading)
        self._show_banner(S.entity_info.loading, "info")
        self._set_empty_table(self._columns_table, S.entity_info.loading)
        self._indexes_header.show()
        self._indexes_table.show()
        self._set_empty_table(self._indexes_table, S.entity_info.loading)

    def set_error(self, message: str):
        self._subtitle_label.setText(S.entity_info.error_subtitle)
        self._show_banner(message, "error")
        self._set_empty_table(self._columns_table, message)
        self._indexes_header.show()
        self._indexes_table.show()
        self._set_empty_table(self._indexes_table, message)

    def populate(self, metadata: dict, connection_name: str):
        entity_label = metadata.get("entity_name") or self._entity_name
        self._title_label.setText(entity_label)
        self._subtitle_label.setText(
            S.entity_info.subtitle_ready.format(connection=connection_name, db_type=metadata.get("db_type", ""))
        )
        self._show_banner(
            S.entity_info.header_connection.format(connection=connection_name),
            "success",
        )

        qualified = metadata.get("qualified_name") or ""
        if qualified:
            self._path_label.setText(qualified)
            self._path_label.show()
        else:
            self._path_label.hide()

        summary_values = {
            "entity_type": metadata.get("entity_type") or S.entity_info.not_available,
            "database": metadata.get("database") or S.entity_info.not_available,
            "catalog": metadata.get("catalog") or S.entity_info.not_available,
            "schema": metadata.get("schema") or S.entity_info.not_available,
            "row_count": self._format_row_count(metadata.get("row_count")),
            "size": metadata.get("size_pretty") or S.entity_info.not_available,
        }
        for field_key, label in self._summary_cards.items():
            label.setText(str(summary_values.get(field_key, S.entity_info.not_available)))

        section_type = metadata.get("section_type", "table")

        if section_type == "routine":
            self._columns_header.setText(S.entity_info.section_parameters)
            self._columns_table.setHorizontalHeaderLabels([
                S.entity_info.columns_name,
                S.entity_info.columns_type,
                S.entity_info.columns_direction,
                S.entity_info.columns_default,
            ])
            params = metadata.get("parameters", [])
            self._populate_parameters(params)
            self._indexes_header.hide()
            self._indexes_table.hide()
        elif section_type == "trigger":
            self._columns_header.setText(S.entity_info.section_trigger_info)
            self._columns_table.setHorizontalHeaderLabels([
                S.entity_info.columns_name,
                S.entity_info.columns_type,
                S.entity_info.columns_default,
                S.entity_info.columns_nullable,
            ])
            trigger_cols = metadata.get("parameters", [])
            self._populate_trigger_info(trigger_cols)
            self._indexes_header.hide()
            self._indexes_table.hide()
        else:
            self._columns_header.setText(S.entity_info.section_columns)
            self._columns_table.setHorizontalHeaderLabels([
                S.entity_info.columns_name,
                S.entity_info.columns_type,
                S.entity_info.columns_nullable,
                S.entity_info.columns_default,
            ])
            self._indexes_header.show()
            self._indexes_table.show()
            self._populate_columns(metadata.get("columns", []))
            self._populate_indexes(metadata.get("indexes", []), metadata.get("indexes_supported", True))

    def _populate_parameters(self, parameters: list[dict]):
        if not parameters:
            self._set_empty_table(self._columns_table, S.entity_info.no_parameters)
            return
        self._columns_table.setRowCount(len(parameters))
        for row_index, param in enumerate(sorted(parameters, key=lambda p: p.get("ordinal_position", 0))):
            values = [
                str(param.get("name", "")),
                str(param.get("display_type", "")),
                str(param.get("direction", "IN")),
                str(param.get("default", "")),
            ]
            for col_index, value in enumerate(values):
                self._columns_table.setItem(row_index, col_index, QTableWidgetItem(value))
        self._columns_table.resizeRowsToContents()

    def _populate_trigger_info(self, trigger_cols: list[dict]):
        if not trigger_cols:
            self._set_empty_table(self._columns_table, S.entity_info.not_available)
            return
        self._columns_table.setRowCount(len(trigger_cols))
        for row_index, item in enumerate(sorted(trigger_cols, key=lambda p: p.get("ordinal_position", 0))):
            values = [
                str(item.get("name", "")),
                str(item.get("display_type", "")),
                "",
                "",
            ]
            for col_index, value in enumerate(values):
                self._columns_table.setItem(row_index, col_index, QTableWidgetItem(value))
        self._columns_table.resizeRowsToContents()

    def _populate_columns(self, columns: list[dict]):
        if not columns:
            self._set_empty_table(self._columns_table, S.entity_info.no_columns)
            return

        self._columns_table.setRowCount(len(columns))
        for row_index, column in enumerate(columns):
            values = [
                str(column.get("name", "")),
                str(column.get("display_type", "")),
                self._format_nullable(column.get("nullable")),
                str(column.get("default", "")),
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self._columns_table.setItem(row_index, column_index, item)
        self._columns_table.resizeRowsToContents()

    def _populate_indexes(self, indexes: list[dict], indexes_supported: bool):
        if not indexes_supported:
            self._set_empty_table(self._indexes_table, S.entity_info.indexes_not_supported)
            return
        if not indexes:
            self._set_empty_table(self._indexes_table, S.entity_info.no_indexes)
            return

        self._indexes_table.setRowCount(len(indexes))
        for row_index, index_info in enumerate(indexes):
            values = [
                str(index_info.get("name", "")),
                str(index_info.get("type", "")),
                str(index_info.get("columns", "")),
            ]
            for column_index, value in enumerate(values):
                self._indexes_table.setItem(row_index, column_index, QTableWidgetItem(value))
        self._indexes_table.resizeRowsToContents()

    def _set_empty_table(self, table: QTableWidget, message: str):
        table.clearContents()
        table.setRowCount(1)
        table.setItem(0, 0, QTableWidgetItem(message))
        for column_index in range(1, table.columnCount()):
            table.setItem(0, column_index, QTableWidgetItem(""))
        table.resizeRowsToContents()

    def _show_banner(self, message: str, variant: str):
        colors = get_colors()
        palette = {
            "info": (colors.text_secondary, colors.bg_tertiary),
            "success": (colors.success, f"{colors.success}18"),
            "error": (colors.danger, f"{colors.danger}18"),
        }
        text_color, background_color = palette.get(variant, palette["info"])
        self._message_banner.setText(message)
        self._message_banner.setStyleSheet(
            f"""
            QLabel {{
                background-color: {background_color};
                color: {text_color};
                border: none;
                border-radius: {RADIUS.radius_sm}px;
                padding: 8px 12px;
                font-size: 11px;
            }}
            """
        )
        self._message_banner.show()

    def _format_row_count(self, row_count) -> str:
        if row_count is None:
            return S.entity_info.not_available
        try:
            return f"{int(row_count):,}"
        except (TypeError, ValueError):
            return str(row_count)

    def _format_nullable(self, value) -> str:
        if str(value).strip().upper() == "NO":
            return S.entity_info.nullable_no
        return S.entity_info.nullable_yes
