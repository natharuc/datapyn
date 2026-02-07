"""
Painel de Variáveis

Exibe variáveis em memória da sessão com nome, tipo e valor.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableView, QHeaderView, QLabel, QAbstractItemView
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, pyqtSignal
from PyQt6.QtGui import QColor, QFont
import pandas as pd
from typing import Dict, Any, Optional

from .buttons import GhostButton

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


class VariablesTableModel(QAbstractTableModel):
    """Model para exibir variáveis em tabela"""

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._variables: list = []  # Lista de dicts {name, type, value, raw}
        self._update_colors()

    def _update_colors(self):
        """Atualiza cores do tema"""
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
        """Define variáveis a partir do namespace"""
        self.beginResetModel()

        self._variables = []

        # Filtrar variáveis internas
        for name, value in namespace.items():
            if name.startswith("_") or name in ("pd", "np", "plt", "sns"):
                continue

            type_name = type(value).__name__

            # Preview do valor
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

        # Ordenar por nome
        self._variables.sort(key=lambda x: x["name"])

        self.endResetModel()

    def clear(self):
        """Limpa variáveis"""
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
            # Cores por tipo
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
            # Retorna valor raw para uso externo
            return var["raw"]

        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            headers = ["Nome", "Tipo", "Valor"]
            return headers[section] if section < len(headers) else ""
        return QVariant()

    def get_variable(self, row: int) -> Optional[Any]:
        """Retorna valor raw da variável"""
        if 0 <= row < len(self._variables):
            return self._variables[row]["raw"]
        return None

    def get_variable_name(self, row: int) -> Optional[str]:
        """Retorna nome da variável"""
        if 0 <= row < len(self._variables):
            return self._variables[row]["name"]
        return None


class VariablesPanel(QWidget):
    """Painel de visualização de variáveis"""

    # Sinais
    variable_selected = pyqtSignal(str, object)  # name, value
    variable_double_clicked = pyqtSignal(str, object)  # name, value (para abrir em viewer)

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)

        self.theme_manager = theme_manager
        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        """Configura UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 5, 8, 5)
        toolbar_layout.setSpacing(8)

        # Info label
        self.info_label = QLabel("Nenhuma variável")
        self.info_label.setStyleSheet("color: #808080;")
        toolbar_layout.addWidget(self.info_label)

        toolbar_layout.addStretch()

        # Botão refresh
        self.btn_refresh = GhostButton("Atualizar")
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

        # Model
        self.model = VariablesTableModel(theme_manager=self.theme_manager)
        self.table_view.setModel(self.model)

        # Configurar colunas
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
        """Define variáveis do namespace"""
        self.model.set_variables(namespace)

        count = self.model.rowCount()
        if count == 0:
            self.info_label.setText("Nenhuma variável")
        elif count == 1:
            self.info_label.setText("1 variável")
        else:
            self.info_label.setText(f"{count} variáveis")

    def display_dataframe(self, df: Optional[pd.DataFrame], title: str = "Variáveis"):
        """Compatibilidade com ResultsViewer - aceita DataFrame de variáveis"""
        if df is None or df.empty:
            self.clear()
            return

        # Converter DataFrame para namespace
        # O DataFrame geralmente tem colunas: Nome, Tipo, Valor, Shape, Preview
        namespace = {}
        if "Nome" in df.columns and "Valor" in df.columns:
            for _, row in df.iterrows():
                name = row.get("Nome", "")
                value = row.get("Preview", row.get("Valor", ""))
                # Guardar o valor bruto ou string para exibição
                namespace[name] = value

        self.set_variables(namespace)
        self.info_label.setText(f"{len(df)} variáveis")

    def set_data(self, df: Optional[pd.DataFrame]):
        """Compatibilidade com ResultsViewer - aceita DataFrame de variáveis"""
        self.display_dataframe(df)

    def clear(self):
        """Limpa variáveis"""
        self.model.clear()
        self.info_label.setText("Nenhuma variável")

    def _on_click(self, index: QModelIndex):
        """Quando variável é selecionada"""
        name = self.model.get_variable_name(index.row())
        value = self.model.get_variable(index.row())
        if name:
            self.variable_selected.emit(name, value)

    def _on_double_click(self, index: QModelIndex):
        """Quando variável é clicada duas vezes"""
        name = self.model.get_variable_name(index.row())
        value = self.model.get_variable(index.row())
        if name:
            self.variable_double_clicked.emit(name, value)
