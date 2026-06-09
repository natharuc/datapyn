"""Variables Panel — session variables with type filter and Parquet storage status."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QHeaderView,
    QLabel, QAbstractItemView, QMenu, QApplication, QComboBox,
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, pyqtSignal
from PyQt6.QtGui import QColor, QFont
import pandas as pd
from typing import Dict, Any, Optional

from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class VariablesTableModel(QAbstractTableModel):
    """Model to display variables: name, type, storage."""

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._all_variables: list = []
        self._variables: list = []
        self._type_filter = "all"
        self._storage_map: Dict[str, int] = {}
        self._update_colors()

    def _update_colors(self):
        from src.design_system.tokens import get_colors
        tokens = get_colors()

        if self.theme_manager:
            colors = self.theme_manager.get_table_colors()
            self._row_even = QColor(colors["row_even"])
            self._row_odd = QColor(colors["row_odd"])
            self._text_color = QColor(colors["text"])
        else:
            self._row_even = QColor(tokens.bg_primary)
            self._row_odd = QColor(tokens.bg_secondary)
            self._text_color = QColor(tokens.text_secondary)

    def set_theme_manager(self, theme_manager):
        self.theme_manager = theme_manager
        self._update_colors()
        self.layoutChanged.emit()

    def set_type_filter(self, filter_key: str) -> None:
        self._type_filter = filter_key or "all"
        self.beginResetModel()
        self._rebuild_filtered_list()
        self.endResetModel()

    def update_storage_map(self, storage_map: Dict[str, int]) -> None:
        self._storage_map = dict(storage_map or {})
        if self._variables:
            top_left = self.index(0, 2)
            bottom_right = self.index(len(self._variables) - 1, 2)
            self.dataChanged.emit(top_left, bottom_right)

    def _matches_type_filter(self, type_name: str) -> bool:
        if self._type_filter == "all":
            return True
        if self._type_filter == "numeric":
            return type_name in ("int", "float")
        if self._type_filter == "other":
            known = {
                "DataFrame", "Series", "str", "bool", "int", "float",
                "list", "dict", "tuple",
            }
            return type_name not in known
        return type_name == self._type_filter

    def _rebuild_filtered_list(self) -> None:
        self._variables = [
            var for var in self._all_variables if self._matches_type_filter(var["type"])
        ]

    def _storage_label(self, name: str, type_name: str) -> str:
        from src.core.session_result_storage import format_storage_size

        size_bytes = self._storage_map.get(name)
        if size_bytes and size_bytes > 0:
            return S.variables_panel.storage_saved.format(
                size=format_storage_size(size_bytes),
            )
        if type_name == "DataFrame":
            return S.variables_panel.storage_not_saved
        return S.variables_panel.storage_not_applicable

    def set_variables(self, namespace: Dict[str, Any], storage_map: Optional[Dict[str, int]] = None):
        self.beginResetModel()
        self._storage_map = dict(storage_map or {})
        self._all_variables = []

        for name, value in namespace.items():
            if name.startswith("_") or name in ("pd", "np", "plt", "sns"):
                continue

            type_name = type(value).__name__
            self._all_variables.append(
                {"name": name, "type": type_name, "raw": value}
            )

        self._all_variables.sort(key=lambda x: x["name"])
        self._rebuild_filtered_list()
        self.endResetModel()

    def clear(self):
        self.beginResetModel()
        self._all_variables = []
        self._variables = []
        self._storage_map = {}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._variables)

    def columnCount(self, parent=QModelIndex()):
        return 3

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._variables):
            return QVariant()

        var = self._variables[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return var["name"]
            if col == 1:
                return var["type"]
            if col == 2:
                return self._storage_label(var["name"], var["type"])

        if role == Qt.ItemDataRole.BackgroundRole:
            return self._row_even if index.row() % 2 == 0 else self._row_odd

        if role == Qt.ItemDataRole.ForegroundRole:
            from src.design_system.tokens import get_colors
            tokens = get_colors()
            type_colors = {
                "DataFrame": QColor(tokens.success),
                "Series": QColor(tokens.success),
                "int": QColor("#b5cea8"),
                "float": QColor("#b5cea8"),
                "str": QColor("#ce9178"),
                "list": QColor(tokens.warning),
                "dict": QColor(tokens.warning),
                "bool": QColor(tokens.info),
            }
            if col == 1:
                return type_colors.get(var["type"], self._text_color)
            if col == 2:
                size_bytes = self._storage_map.get(var["name"], 0)
                if size_bytes > 0:
                    return QColor(tokens.success)
            return self._text_color

        if role == Qt.ItemDataRole.FontRole:
            if col == 0:
                font = QFont()
                font.setBold(True)
                return font

        if role == Qt.ItemDataRole.UserRole:
            return var["raw"]

        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            headers = [
                S.variables_panel.header_name,
                S.variables_panel.header_type,
                S.variables_panel.header_storage,
            ]
            return headers[section] if section < len(headers) else ""
        return QVariant()

    def get_variable(self, row: int) -> Optional[Any]:
        if 0 <= row < len(self._variables):
            return self._variables[row]["raw"]
        return None

    def get_variable_name(self, row: int) -> Optional[str]:
        if 0 <= row < len(self._variables):
            return self._variables[row]["name"]
        return None

    def get_variable_storage_bytes(self, row: int) -> Optional[int]:
        if 0 <= row < len(self._variables):
            name = self._variables[row]["name"]
            size = self._storage_map.get(name)
            return size if size and size > 0 else None
        return None


class VariablesPanel(QWidget):
    """Variables visualization panel."""

    variable_selected = pyqtSignal(str, object)
    variable_double_clicked = pyqtSignal(str, object)
    insert_variable_name = pyqtSignal(str)
    delete_variable = pyqtSignal(str)
    show_in_results = pyqtSignal(str, object)

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)

        self.theme_manager = theme_manager
        self._session_widget = None
        self._session_id: Optional[str] = None
        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 5, 8, 5)
        toolbar_layout.setSpacing(8)

        from src.design_system.tokens import get_colors
        colors_tk = get_colors()

        self.info_label = QLabel(S.variables_panel.no_variables)
        self.info_label.setStyleSheet(f"color: {colors_tk.text_tertiary};")
        toolbar_layout.addWidget(self.info_label)

        self.type_filter = QComboBox()
        self.type_filter.setMinimumWidth(120)
        self.type_filter.addItem(S.variables_panel.filter_all, "all")
        self.type_filter.addItem(S.variables_panel.filter_dataframe, "DataFrame")
        self.type_filter.addItem(S.variables_panel.filter_series, "Series")
        self.type_filter.addItem(S.variables_panel.filter_numeric, "numeric")
        self.type_filter.addItem(S.variables_panel.filter_str, "str")
        self.type_filter.addItem(S.variables_panel.filter_bool, "bool")
        self.type_filter.addItem(S.variables_panel.filter_list, "list")
        self.type_filter.addItem(S.variables_panel.filter_dict, "dict")
        self.type_filter.addItem(S.variables_panel.filter_other, "other")
        self.type_filter.currentIndexChanged.connect(self._on_type_filter_changed)
        toolbar_layout.addWidget(self.type_filter)
        toolbar_layout.addStretch()

        toolbar.setStyleSheet(f"""
            QWidget {{
                background-color: {colors_tk.bg_secondary};
                border-bottom: 1px solid {colors_tk.border_default};
            }}
        """)
        layout.addWidget(toolbar)

        self.table_view = QTableView()
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.setShowGrid(False)
        self.table_view.doubleClicked.connect(self._on_double_click)
        self.table_view.clicked.connect(self._on_click)
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._on_context_menu)

        self.model = VariablesTableModel(theme_manager=self.theme_manager)
        self.table_view.setModel(self.model)

        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.table_view)

    def bind_session_widget(self, session_widget) -> None:
        self._session_widget = session_widget
        self._session_id = session_widget.session.session_id
        session_widget.session.variables_changed.connect(self._on_bound_namespace_changed)

    def _on_bound_namespace_changed(self, _namespace: dict) -> None:
        self.refresh_storage_column()

    def _on_type_filter_changed(self, _index: int) -> None:
        filter_key = self.type_filter.currentData()
        self.model.set_type_filter(str(filter_key or "all"))
        self._update_count_label()

    def get_selected_variable(self) -> Optional[tuple]:
        index = self.table_view.currentIndex()
        if not index.isValid():
            return None
        name = self.model.get_variable_name(index.row())
        if not name:
            return None
        return name, self.model.get_variable(index.row())

    def refresh_storage_column(self) -> None:
        if not self._session_id:
            return
        from src.core.session_result_storage import get_snapshot_variable_sizes

        self.model.update_storage_map(get_snapshot_variable_sizes(self._session_id))

    def _update_count_label(self) -> None:
        count = self.model.rowCount()
        if count == 0:
            self.info_label.setText(S.variables_panel.no_variables)
        elif count == 1:
            self.info_label.setText(S.variables_panel.one_variable)
        else:
            self.info_label.setText(S.variables_panel.n_variables.format(n=count))

    def _apply_theme(self):
        from src.design_system.tokens import get_colors, SCROLLBAR_STYLE
        colors_tk = get_colors()

        self.table_view.setStyleSheet(f"""
            QTableView {{
                background-color: {colors_tk.bg_primary};
                color: {colors_tk.text_primary};
                border: none;
                gridline-color: transparent;
                selection-background-color: {colors_tk.interactive_primary};
                alternate-background-color: {colors_tk.bg_secondary};
                font-size: 12px;
            }}
            QTableView::item {{
                padding: 6px 10px;
                border: none;
            }}
            QTableView::item:selected {{
                background-color: {colors_tk.interactive_primary};
                color: {colors_tk.text_inverse};
            }}
            QTableView::item:hover:!selected {{
                background-color: {colors_tk.bg_tertiary};
            }}
            QHeaderView::section {{
                background-color: {colors_tk.bg_secondary};
                color: {colors_tk.text_secondary};
                padding: 8px 10px;
                border: none;
                border-bottom: 1px solid {colors_tk.border_default};
                font-weight: 600;
                font-size: 11px;
            }}
            {SCROLLBAR_STYLE}
        """)
        self.table_view.setAlternatingRowColors(True)

    def set_theme_manager(self, theme_manager):
        self.theme_manager = theme_manager
        self.model.set_theme_manager(theme_manager)
        self._apply_theme()

    def set_variables(self, namespace: Dict[str, Any]):
        from src.core.session_result_storage import get_snapshot_variable_sizes

        storage_map = get_snapshot_variable_sizes(self._session_id) if self._session_id else {}
        self.model.set_variables(namespace, storage_map)
        self._update_count_label()

    def display_dataframe(self, df: Optional[pd.DataFrame], title: str = "Variables"):
        if df is None or df.empty:
            self.clear()
            return

        namespace = {}
        if "Name" in df.columns and "Value" in df.columns:
            for _, row in df.iterrows():
                name = row.get("Name", "")
                value = row.get("Preview", row.get("Valor", ""))
                namespace[name] = value

        self.set_variables(namespace)
        self.info_label.setText(S.variables_panel.n_variables.format(n=len(df)))

    def set_data(self, df: Optional[pd.DataFrame]):
        self.display_dataframe(df)

    def clear(self):
        self.model.clear()
        self.info_label.setText(S.variables_panel.no_variables)

    def _on_click(self, index: QModelIndex):
        name = self.model.get_variable_name(index.row())
        value = self.model.get_variable(index.row())
        if name:
            self.variable_selected.emit(name, value)

    def _insert_name(self, name: str) -> None:
        if name:
            self.insert_variable_name.emit(name)

    def _on_double_click(self, index: QModelIndex):
        name = self.model.get_variable_name(index.row())
        value = self.model.get_variable(index.row())
        if not name:
            return

        storage_bytes = self.model.get_variable_storage_bytes(index.row())
        from src.ui.dialogs.variable_detail_dialog import VariableDetailDialog

        dlg = VariableDetailDialog(name, value, storage_bytes, parent=self)
        dlg.exec()
        self.variable_double_clicked.emit(name, value)

    def _on_context_menu(self, pos):
        index = self.table_view.indexAt(pos)
        if not index.isValid():
            return

        row = index.row()
        name = self.model.get_variable_name(row)
        value = self.model.get_variable(row)
        if not name:
            return

        menu = QMenu(self)

        from src.design_system.tokens import get_colors, RADIUS
        colors_tk = get_colors()
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {colors_tk.bg_elevated};
                color: {colors_tk.text_primary};
                border: 1px solid {colors_tk.border_default};
                border-radius: {RADIUS.radius_md}px;
                padding: 6px;
            }}
            QMenu::item {{
                padding: 8px 24px 8px 12px;
                border-radius: {RADIUS.radius_sm}px;
            }}
            QMenu::item:selected {{
                background-color: {colors_tk.interactive_primary};
                color: white;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {colors_tk.border_default};
                margin: 6px 8px;
            }}
        """)

        type_name = type(value).__name__

        act_details = menu.addAction(S.variables_panel.ctx_view_details)
        act_details.triggered.connect(lambda: self._on_double_click(index))

        if HAS_QTAWESOME:
            act_insert = menu.addAction(
                qta.icon("mdi.code-braces", color=colors_tk.interactive_primary),
                S.variables_panel.ctx_insert_in_editor,
            )
        else:
            act_insert = menu.addAction(S.variables_panel.ctx_insert_in_editor)
        act_insert.triggered.connect(lambda _checked=False, n=name: self._insert_name(n))

        menu.addSeparator()

        act_copy_name = menu.addAction(S.variables_panel.ctx_copy_name)
        act_copy_name.triggered.connect(lambda: QApplication.clipboard().setText(name))

        act_copy_value = menu.addAction(S.variables_panel.ctx_copy_value)
        act_copy_value.triggered.connect(
            lambda: QApplication.clipboard().setText(self._get_copyable_value(value))
        )

        act_copy_type = menu.addAction(S.variables_panel.ctx_copy_type)
        act_copy_type.triggered.connect(lambda: QApplication.clipboard().setText(type_name))

        menu.addSeparator()

        if isinstance(value, pd.DataFrame):
            act_show = menu.addAction(S.variables_panel.ctx_show_in_results)
            act_show.triggered.connect(lambda: self.show_in_results.emit(name, value))
        elif isinstance(value, pd.Series):
            act_show = menu.addAction(S.variables_panel.ctx_show_in_results)
            act_show.triggered.connect(lambda: self.show_in_results.emit(name, value))

        menu.addSeparator()
        act_delete = menu.addAction(S.variables_panel.ctx_remove_variable)
        act_delete.triggered.connect(lambda: self.delete_variable.emit(name))

        menu.exec(self.table_view.viewport().mapToGlobal(pos))

    @staticmethod
    def _get_copyable_value(value) -> str:
        if isinstance(value, pd.DataFrame):
            return value.to_string()
        if isinstance(value, pd.Series):
            return value.to_string()
        return repr(value)
