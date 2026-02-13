"""
Object Explorer Panel

Exibe a estrutura do banco de dados em arvore hierarquica:
banco > tabelas > colunas (com tipos).

Suporta:
- Context menu com "Selecionar 1000 linhas" em tabelas
- Duplo clique para inserir nome no editor focado
- Refresh manual do schema
- Indicacao de carregamento
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QLabel,
    QMenu,
    QApplication,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QAction

from .buttons import GhostButton

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

import logging

logger = logging.getLogger(__name__)


class ObjectExplorerPanel(QWidget):
    """Painel de Object Explorer - exibe estrutura do banco em arvore"""

    # Sinais
    insert_text_requested = pyqtSignal(str)  # texto para inserir no editor focado
    select_top_requested = pyqtSignal(str, str)  # schema, table_name -> SELECT TOP 1000
    query_requested = pyqtSignal(str)  # query SQL para executar

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._current_schema = None  # schema dict do SchemaService
        self._current_connection = ""
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
        self.info_label = QLabel("Nenhuma conexao")
        self.info_label.setStyleSheet("color: #808080;")
        toolbar_layout.addWidget(self.info_label)

        toolbar_layout.addStretch()

        # Botao refresh
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

        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setAnimated(True)
        self.tree.setExpandsOnDoubleClick(False)

        # Context menu
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)

        # Double click
        self.tree.itemDoubleClicked.connect(self._on_double_click)

        layout.addWidget(self.tree)

    def _apply_theme(self):
        """Aplica tema ao tree widget"""
        if self.theme_manager:
            colors = self.theme_manager.get_app_colors()
        else:
            colors = {
                "background": "#1e1e1e",
                "foreground": "#cccccc",
                "border": "#3e3e42",
            }

        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: none;
                font-size: 12px;
            }}
            QTreeWidget::item {{
                padding: 3px 4px;
            }}
            QTreeWidget::item:selected {{
                background-color: #094771;
            }}
            QTreeWidget::item:hover {{
                background-color: #2a2d2e;
            }}
        """)

    def set_theme_manager(self, theme_manager):
        """Define theme manager"""
        self.theme_manager = theme_manager
        self._apply_theme()

    def set_schema(self, schema: dict, connection_name: str = ""):
        """Define o schema a ser exibido na arvore.

        Args:
            schema: dict com keys 'database', 'tables', 'columns'
                    (formato do SchemaService)
            connection_name: nome da conexao
        """
        self._current_schema = schema
        self._current_connection = connection_name
        self._build_tree(schema)

    def clear(self):
        """Limpa a arvore"""
        self.tree.clear()
        self._current_schema = None
        self._current_connection = ""
        self.info_label.setText("Nenhuma conexao")

    def _build_tree(self, schema: dict):
        """Constroi a arvore a partir do schema"""
        self.tree.clear()

        if not schema:
            self.info_label.setText("Nenhuma conexao")
            return

        tables = schema.get("tables", [])
        columns = schema.get("columns", {})
        db_name = schema.get("database", "")

        # No raiz: banco de dados
        db_display = db_name or self._current_connection or "Banco"
        db_item = QTreeWidgetItem(self.tree, [db_display])
        db_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "database", "name": db_name})

        if HAS_QTAWESOME:
            db_item.setIcon(0, qta.icon("mdi.database", color="#569cd6"))

        font = db_item.font(0)
        font.setBold(True)
        db_item.setFont(0, font)

        # Agrupar tabelas por schema
        schema_groups = {}
        for table in tables:
            table_schema = table.get("schema", "")
            if table_schema not in schema_groups:
                schema_groups[table_schema] = []
            schema_groups[table_schema].append(table)

        # Se ha apenas um schema (ou nenhum), nao criar no intermediario
        use_schema_nodes = len(schema_groups) > 1

        for schema_name, schema_tables in sorted(schema_groups.items()):
            if use_schema_nodes and schema_name:
                parent = QTreeWidgetItem(db_item, [schema_name])
                parent.setData(
                    0, Qt.ItemDataRole.UserRole,
                    {"type": "schema", "name": schema_name},
                )
                if HAS_QTAWESOME:
                    parent.setIcon(0, qta.icon("mdi.folder", color="#dcdc8b"))
            else:
                parent = db_item

            for table in sorted(schema_tables, key=lambda t: t.get("name", "")):
                table_name = table.get("name", "")
                table_type = table.get("type", "TABLE")
                table_schema = table.get("schema", "")

                # Icone diferente para view
                is_view = "VIEW" in table_type.upper()
                label = table_name
                if is_view:
                    label = f"{table_name} (view)"

                table_item = QTreeWidgetItem(parent, [label])
                table_item.setData(
                    0, Qt.ItemDataRole.UserRole,
                    {
                        "type": "table",
                        "name": table_name,
                        "schema": table_schema,
                        "table_type": table_type,
                    },
                )

                if HAS_QTAWESOME:
                    if is_view:
                        table_item.setIcon(0, qta.icon("mdi.table-eye", color="#4ec9b0"))
                    else:
                        table_item.setIcon(0, qta.icon("mdi.table", color="#4ec9b0"))

                # Colunas da tabela
                table_columns = columns.get(table_name, [])
                for col in table_columns:
                    col_name = col.get("name", "")
                    col_type = col.get("type", "")
                    nullable = col.get("nullable", "YES")

                    display = f"{col_name}  ({col_type})"
                    if nullable.upper() == "NO":
                        display += "  NOT NULL"

                    col_item = QTreeWidgetItem(table_item, [display])
                    col_item.setData(
                        0, Qt.ItemDataRole.UserRole,
                        {
                            "type": "column",
                            "name": col_name,
                            "data_type": col_type,
                            "nullable": nullable,
                            "table": table_name,
                            "schema": table_schema,
                        },
                    )

                    if HAS_QTAWESOME:
                        col_item.setIcon(0, qta.icon("mdi.table-column", color="#888888"))

                    # Cor sutil para tipo
                    col_item.setForeground(0, QColor("#b0b0b0"))

        # Atualizar info
        table_count = len(tables)
        col_count = sum(len(v) for v in columns.values())
        self.info_label.setText(f"{table_count} tabelas, {col_count} colunas")

        # Expandir banco por padrao
        db_item.setExpanded(True)

    def _on_double_click(self, item: QTreeWidgetItem, column: int):
        """Duplo clique insere nome no editor focado"""
        if item is None:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        item_type = data.get("type", "")
        name = data.get("name", "")

        if item_type in ("table", "column") and name:
            self.insert_text_requested.emit(name)

    def _on_context_menu(self, pos):
        """Menu de contexto"""
        item = self.tree.itemAt(pos)
        if item is None:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        item_type = data.get("type", "")
        name = data.get("name", "")
        schema_name = data.get("schema", "")

        menu = QMenu(self)

        # Estilo do menu
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

        if item_type == "table":
            # Selecionar 1000 linhas
            qualified = f"{schema_name}.{name}" if schema_name else name
            act_select = menu.addAction("Selecionar 1000 linhas")
            act_select.triggered.connect(
                lambda: self.query_requested.emit(f"SELECT TOP 1000 * FROM {qualified}")
            )

            menu.addSeparator()

            # Inserir nome no editor
            act_insert = menu.addAction("Inserir nome no editor")
            act_insert.triggered.connect(lambda: self.insert_text_requested.emit(name))

            # Copiar nome
            act_copy = menu.addAction("Copiar nome")
            act_copy.triggered.connect(lambda: QApplication.clipboard().setText(name))

            # Copiar nome qualificado
            if schema_name:
                act_copy_qual = menu.addAction("Copiar nome qualificado")
                act_copy_qual.triggered.connect(
                    lambda: QApplication.clipboard().setText(f"{schema_name}.{name}")
                )

        elif item_type == "column":
            table_name = data.get("table", "")
            col_type = data.get("data_type", "")

            # Inserir nome no editor
            act_insert = menu.addAction("Inserir nome no editor")
            act_insert.triggered.connect(lambda: self.insert_text_requested.emit(name))

            # Copiar nome
            act_copy = menu.addAction("Copiar nome")
            act_copy.triggered.connect(lambda: QApplication.clipboard().setText(name))

            # Copiar como table.column
            if table_name:
                act_copy_full = menu.addAction(f"Copiar como {table_name}.{name}")
                act_copy_full.triggered.connect(
                    lambda: QApplication.clipboard().setText(f"{table_name}.{name}")
                )

            menu.addSeparator()

            # Info do tipo (desabilitado)
            act_type_info = menu.addAction(f"Tipo: {col_type}")
            act_type_info.setEnabled(False)

        elif item_type == "database":
            # Copiar nome do banco
            act_copy = menu.addAction("Copiar nome")
            act_copy.triggered.connect(lambda: QApplication.clipboard().setText(name))

        else:
            return

        menu.exec(self.tree.viewport().mapToGlobal(pos))
