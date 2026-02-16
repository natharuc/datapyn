"""Variables Panel

Displays session variables in memory with name, type, and value.
Includes context menu and double-click to insert into editor.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QHeaderView,
    QLabel, QAbstractItemView, QMenu, QApplication, QMessageBox,
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QAction
import pandas as pd
from typing import Dict, Any, Optional

from .buttons import GhostButton

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class VariablesTableModel(QAbstractTableModel):
    """Model to display variables in table"""

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._variables: list = []  # List of dicts {name, type, value, raw}
        self._update_colors()

    def _update_colors(self):
        """Update theme colors"""
        if self.theme_manager:
            colors = self.theme_manager.get_table_colors()
            self._row_even = QColor(colors["row_even"])
            self._row_odd = QColor(colors["row_odd"])
            self._text_color = QColor(colors["text"])
        else:
            self._row_even = QColor("#1e1e1e")
            self._row_odd = QColor("#252526")
            self._text_color = QColor("#cccccc")

    def set_theme_manager(self, theme_manager):
        """Define theme manager"""
        self.theme_manager = theme_manager
        self._update_colors()
        self.layoutChanged.emit()

    def set_variables(self, namespace: Dict[str, Any]):
        """Set variables from namespace"""
        self.beginResetModel()

        self._variables = []

        # Filter internal variables
        for name, value in namespace.items():
            if name.startswith("_") or name in ("pd", "np", "plt", "sns"):
                continue

            type_name = type(value).__name__

            # Preview of value
            if isinstance(value, pd.DataFrame):
                preview = f"DataFrame ({len(value)} rows × {len(value.columns)} cols)"
            elif isinstance(value, pd.Series):
                preview = f"Series ({len(value)} items)"
            elif isinstance(value, (list, tuple)):
                preview = f"{type_name} [{len(value)} items]"
            elif isinstance(value, dict):
                preview = f"dict {{{len(value)} keys}}"
            elif isinstance(value, str):
                preview = repr(value[:50]) + ("..." if len(value) > 50 else "")
            else:
                preview = repr(value)[:100]

            self._variables.append({"name": name, "type": type_name, "value": preview, "raw": value})

        # Sort by name
        self._variables.sort(key=lambda x: x["name"])

        self.endResetModel()

    def clear(self):
        """Clear variables"""
        self.beginResetModel()
        self._variables = []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._variables)

    def columnCount(self, parent=QModelIndex()):
        return 3  # Nome, Tipo, Valor

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._variables):
            return QVariant()

        var = self._variables[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return var["name"]
            elif col == 1:
                return var["type"]
            elif col == 2:
                return var["value"]

        if role == Qt.ItemDataRole.BackgroundRole:
            return self._row_even if index.row() % 2 == 0 else self._row_odd

        if role == Qt.ItemDataRole.ForegroundRole:
            # Colors by type
            type_colors = {
                "DataFrame": QColor("#4ec9b0"),
                "Series": QColor("#4ec9b0"),
                "int": QColor("#b5cea8"),
                "float": QColor("#b5cea8"),
                "str": QColor("#ce9178"),
                "list": QColor("#dcdcaa"),
                "dict": QColor("#dcdcaa"),
                "bool": QColor("#569cd6"),
            }
            if col == 1:
                return type_colors.get(var["type"], self._text_color)
            return self._text_color

        if role == Qt.ItemDataRole.FontRole:
            if col == 0:
                font = QFont()
                font.setBold(True)
                return font

        if role == Qt.ItemDataRole.UserRole:
            # Return raw value for external use
            return var["raw"]

        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            headers = ["Name", "Type", "Value"]
            return headers[section] if section < len(headers) else ""
        return QVariant()

    def get_variable(self, row: int) -> Optional[Any]:
        """Return raw value of variable"""
        if 0 <= row < len(self._variables):
            return self._variables[row]["raw"]
        return None

    def get_variable_name(self, row: int) -> Optional[str]:
        """Return variable name"""
        if 0 <= row < len(self._variables):
            return self._variables[row]["name"]
        return None


class VariablesPanel(QWidget):
    """Variables visualization panel"""

    # Signals
    variable_selected = pyqtSignal(str, object)  # name, value
    variable_double_clicked = pyqtSignal(str, object)  # name, value (to open in viewer)
    insert_variable_name = pyqtSignal(str)  # name (to insert in focused editor)
    delete_variable = pyqtSignal(str)  # name (to remove from namespace)

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)

        self.theme_manager = theme_manager
        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        """Configure UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 5, 8, 5)
        toolbar_layout.setSpacing(8)

        # Info label
        self.info_label = QLabel("No variables")
        self.info_label.setStyleSheet("color: #808080;")
        toolbar_layout.addWidget(self.info_label)

        toolbar_layout.addStretch()

        # Refresh button
        self.btn_refresh = GhostButton("Refresh")
        if HAS_QTAWESOME:
            self.btn_refresh.setIcon(qta.icon("fa5s.sync", color="#888888"))
        toolbar_layout.addWidget(self.btn_refresh)

        toolbar.setStyleSheet("""
            QWidget {
                background-color: #2d2d30;
                border-bottom: 1px solid #3e3e42;
            }
        """)
        layout.addWidget(toolbar)

        # Tabela
        self.table_view = QTableView()
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.setShowGrid(False)
        self.table_view.doubleClicked.connect(self._on_double_click)
        self.table_view.clicked.connect(self._on_click)

        # Context menu
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._on_context_menu)

        # Model
        self.model = VariablesTableModel(theme_manager=self.theme_manager)
        self.table_view.setModel(self.model)

        # Configure columns
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.table_view)

    def _apply_theme(self):
        """Aplica tema"""
        if self.theme_manager:
            colors = self.theme_manager.get_app_colors()
        else:
            colors = {"background": "#1e1e1e", "foreground": "#cccccc", "border": "#3e3e42"}

        self.table_view.setStyleSheet(f"""
            QTableView {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: none;
                gridline-color: {colors["border"]};
            }}
            QTableView::item:selected {{
                background-color: #094771;
            }}
            QHeaderView::section {{
                background-color: #2d2d30;
                color: #cccccc;
                padding: 6px;
                border: none;
                border-bottom: 1px solid {colors["border"]};
                font-weight: bold;
            }}
        """)

    def set_theme_manager(self, theme_manager):
        """Define theme manager"""
        self.theme_manager = theme_manager
        self.model.set_theme_manager(theme_manager)
        self._apply_theme()

    def set_variables(self, namespace: Dict[str, Any]):
        """Set variables from namespace"""
        self.model.set_variables(namespace)

        count = self.model.rowCount()
        if count == 0:
            self.info_label.setText("No variables")
        elif count == 1:
            self.info_label.setText("1 variable")
        else:
            self.info_label.setText(f"{count} variables")

    def display_dataframe(self, df: Optional[pd.DataFrame], title: str = "Variables"):
        """Compatibility with ResultsViewer - accepts DataFrame of variables"""
        if df is None or df.empty:
            self.clear()
            return

        # Convert DataFrame to namespace
        # DataFrame usually has columns: Name, Type, Value, Shape, Preview
        namespace = {}
        if "Name" in df.columns and "Value" in df.columns:
            for _, row in df.iterrows():
                name = row.get("Name", "")
                value = row.get("Preview", row.get("Valor", ""))
                # Store raw value or string for display
                namespace[name] = value

        self.set_variables(namespace)
        self.info_label.setText(f"{len(df)} variables")

    def set_data(self, df: Optional[pd.DataFrame]):
        """Compatibility with ResultsViewer - accepts DataFrame of variables"""
        self.display_dataframe(df)

    def clear(self):
        """Clear variables"""
        self.model.clear()
        self.info_label.setText("No variables")

    def _on_click(self, index: QModelIndex):
        """When variable is selected"""
        name = self.model.get_variable_name(index.row())
        value = self.model.get_variable(index.row())
        if name:
            self.variable_selected.emit(name, value)

    def _on_double_click(self, index: QModelIndex):
        """When variable is double-clicked - insert name in focused editor"""
        name = self.model.get_variable_name(index.row())
        value = self.model.get_variable(index.row())
        if name:
            self.insert_variable_name.emit(name)
            self.variable_double_clicked.emit(name, value)

    def _on_context_menu(self, pos):
        """Context menu with useful options for the variable"""
        index = self.table_view.indexAt(pos)
        if not index.isValid():
            return

        row = index.row()
        name = self.model.get_variable_name(row)
        value = self.model.get_variable(row)
        if not name:
            return

        menu = QMenu(self)

        # Apply style to menu
        if self.theme_manager:
            colors = self.theme_manager.get_app_colors()
            menu.setStyleSheet(f"""
                QMenu {{
                    background-color: {colors["background"]};
                    color: {colors["foreground"]};
                    border: 1px solid {colors["border"]};
                    padding: 4px;
                }}
                QMenu::item {{
                    padding: 6px 24px 6px 12px;
                }}
                QMenu::item:selected {{
                    background-color: {colors["accent"]};
                    color: white;
                }}
                QMenu::separator {{
                    height: 1px;
                    background-color: {colors["border"]};
                    margin: 4px 8px;
                }}
            """)

        type_name = type(value).__name__

        # Insert name in editor
        act_insert = menu.addAction("Insert in editor")
        act_insert.triggered.connect(lambda: self.insert_variable_name.emit(name))

        menu.addSeparator()

        # Copy name
        act_copy_name = menu.addAction("Copy name")
        act_copy_name.triggered.connect(lambda: QApplication.clipboard().setText(name))

        # Copy value
        act_copy_value = menu.addAction("Copy value")
        act_copy_value.triggered.connect(
            lambda: QApplication.clipboard().setText(self._get_copyable_value(value))
        )

        # Copy type
        act_copy_type = menu.addAction("Copy type")
        act_copy_type.triggered.connect(
            lambda: QApplication.clipboard().setText(type_name)
        )

        menu.addSeparator()

        # Type-specific options
        if isinstance(value, pd.DataFrame):
            act_shape = menu.addAction(f"Shape: {value.shape[0]} x {value.shape[1]}")
            act_shape.setEnabled(False)

            act_cols = menu.addAction("Copy columns")
            act_cols.triggered.connect(
                lambda: QApplication.clipboard().setText(", ".join(value.columns.tolist()))
            )

            act_dtypes = menu.addAction("Copy dtypes")
            act_dtypes.triggered.connect(
                lambda: QApplication.clipboard().setText(str(value.dtypes))
            )

            act_head = menu.addAction("Copy head(5)")
            act_head.triggered.connect(
                lambda: QApplication.clipboard().setText(value.head(5).to_string())
            )

            act_csv = menu.addAction("Copy as CSV")
            act_csv.triggered.connect(
                lambda: QApplication.clipboard().setText(value.to_csv(index=False))
            )

        elif isinstance(value, (list, dict, tuple)):
            act_len = menu.addAction(f"Size: {len(value)}")
            act_len.setEnabled(False)

        elif isinstance(value, str):
            act_len = menu.addAction(f"Size: {len(value)} chars")
            act_len.setEnabled(False)

        menu.addSeparator()

        # Delete variable
        act_delete = menu.addAction("Remove variable")
        act_delete.triggered.connect(lambda: self.delete_variable.emit(name))

        menu.exec(self.table_view.viewport().mapToGlobal(pos))

    @staticmethod
    def _get_copyable_value(value) -> str:
        """Return copyable representation of value"""
        if isinstance(value, pd.DataFrame):
            return value.to_string()
        elif isinstance(value, pd.Series):
            return value.to_string()
        return repr(value)
