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
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

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
        self.resize(860, 790)
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
            min_height=630,
            content_margins=(18, 14, 18, 18),
            content_spacing=14,
        )

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        self._title_label = QLabel(self._entity_name)
        self._title_label.setStyleSheet(
            f"color: {colors.text_primary}; font-size: 22px; font-weight: 700;"
        )
        title_row.addWidget(self._title_label)

        if HAS_QTAWESOME:
            icon_label = QLabel()
            icon_label.setPixmap(qta.icon("mdi.database-search", color=colors.interactive_primary).pixmap(20, 20))
            title_row.insertWidget(0, icon_label)

        title_row.addStretch()
        header_layout.addLayout(title_row)

        self._path_label = QLabel()
        self._path_label.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 12px; font-family: monospace;"
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

        summary_widget = QWidget()
        self._summary_layout = QGridLayout(summary_widget)
        self._summary_layout.setContentsMargins(0, 0, 0, 0)
        self._summary_layout.setHorizontalSpacing(12)
        self._summary_layout.setVerticalSpacing(12)

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
        layout.addWidget(summary_widget)

        self._columns_header = QLabel(S.entity_info.section_columns)
        self._columns_header.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 12px; font-weight: 600;"
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
            f"color: {colors.text_secondary}; font-size: 12px; font-weight: 600;"
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

        close_button = QPushButton(S.entity_info.button_close)
        close_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {colors.bg_elevated};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_sm}px;
                padding: 7px 16px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_secondary};
            }}
            """
        )
        close_button.clicked.connect(self.close)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.set_loading()

    def _create_summary_card(self, label_text: str) -> QFrame:
        colors = get_colors()
        card = QFrame()
        card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_sm}px;
            }}
            """
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(4)

        label = QLabel(label_text)
        label.setStyleSheet(
            f"color: {colors.text_tertiary}; font-size: 11px; font-weight: 600;"
        )
        card_layout.addWidget(label)

        value = QLabel(S.entity_info.not_available)
        value.setObjectName("value")
        value.setWordWrap(True)
        value.setStyleSheet(
            f"color: {colors.text_primary}; font-size: 13px; font-weight: 600;"
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
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: {colors.bg_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_sm}px;
                gridline-color: {colors.border_default};
                font-size: 11px;
            }}
            QHeaderView::section {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_secondary};
                border: none;
                border-bottom: 1px solid {colors.border_default};
                padding: 8px;
                font-weight: 600;
            }}
            QTableWidget::item {{
                padding: 6px 8px;
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
            "info": (colors.info, f"{colors.info}20"),
            "success": (colors.success, f"{colors.success}20"),
            "error": (colors.danger, f"{colors.danger}20"),
        }
        border_color, background_color = palette.get(variant, palette["info"])
        self._message_banner.setText(message)
        self._message_banner.setStyleSheet(
            f"""
            QLabel {{
                background-color: {background_color};
                color: {border_color};
                border: 1px solid {border_color};
                border-radius: {RADIUS.radius_sm}px;
                padding: 8px 10px;
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
