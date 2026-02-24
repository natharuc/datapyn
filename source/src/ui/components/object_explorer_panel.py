"""
Object Explorer Panel

Exibe a estrutura do banco de dados em arvore hierarquica:
bancos > tabelas > colunas (com tipos).

Suporta:
- Exibir todos os bancos do servidor da conexao ativa
- Campo de busca para filtrar tabelas/colunas
- Context menu com "Selecionar 1000 linhas" em tabelas
- Duplo clique em qualquer item faz append no editor e refoca
- Duplo clique em banco troca o banco da conexao ativa
- Refresh manual do schema
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QLabel,
    QLineEdit,
    QMenu,
    QApplication,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QMimeData
from PyQt6.QtGui import QFont, QColor, QAction, QDrag

from .buttons import GhostButton

from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

import logging

logger = logging.getLogger(__name__)


class ObjectExplorerPanel(QWidget):
    """Object Explorer Panel - displays database structure in tree"""

    # Signals
    insert_text_requested = pyqtSignal(str)  # text to insert (append) in focused editor
    select_top_requested = pyqtSignal(str, str)  # schema, table_name -> SELECT TOP 1000
    query_requested = pyqtSignal(str)  # SQL query to execute
    database_switch_requested = pyqtSignal(str)  # database name to switch to

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._current_schema = None  # schema dict from SchemaService
        self._current_connection = ""
        self._db_type = ""  # Database type (mssql, postgresql, mysql, etc.)
        self._all_databases = []  # list of all databases from server
        self._filter_timer = None
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
        self.info_label = QLabel(S.object_explorer.no_connection)
        self.info_label.setStyleSheet("color: #808080;")
        toolbar_layout.addWidget(self.info_label)

        toolbar_layout.addStretch()

        # Refresh button - icon-only, compact
        self.btn_refresh = QPushButton()
        self.btn_refresh.setFixedSize(24, 24)
        self.btn_refresh.setToolTip(S.object_explorer.btn_refresh)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        if HAS_QTAWESOME:
            self.btn_refresh.setIcon(qta.icon("mdi.refresh", color="#9d9d9d"))
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.1);
            }
        """)
        toolbar_layout.addWidget(self.btn_refresh)

        from src.design_system.tokens import get_colors
        colors_tk = get_colors()
        toolbar.setStyleSheet(f"""
            QWidget {{
                background-color: {colors_tk.bg_secondary};
                border-bottom: 1px solid {colors_tk.border_default};
            }}
        """)
        layout.addWidget(toolbar)

        # Search field
        from src.design_system.tokens import RADIUS
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(S.object_explorer.placeholder_search)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {colors_tk.bg_tertiary};
                color: {colors_tk.text_primary};
                border: 1px solid {colors_tk.border_default};
                border-radius: {RADIUS.radius_sm}px;
                padding: 6px 10px;
                margin: 4px 8px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {colors_tk.interactive_primary};
            }}
            QLineEdit::placeholder {{
                color: {colors_tk.text_tertiary};
            }}
        """)
        self.search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_input)

        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setAnimated(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setDragEnabled(True)
        self.tree.setDefaultDropAction(Qt.DropAction.CopyAction)

        # Context menu
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)

        # Double click
        self.tree.itemDoubleClicked.connect(self._on_double_click)

        # Override startDrag to provide database mime data
        self.tree.startDrag = self._start_drag

        layout.addWidget(self.tree, 1)  # stretch=1 so tree fills available space
        
        # Loading container (fills space when tree is hidden)
        self._loading_container = QWidget()
        loading_layout = QVBoxLayout(self._loading_container)
        loading_layout.setContentsMargins(0, 0, 0, 0)
        loading_layout.addStretch(1)
        
        # Spinner + Text row
        spinner_row = QHBoxLayout()
        spinner_row.addStretch(1)
        
        # Spinner widget (animated)
        if HAS_QTAWESOME:
            self._spinner_widget = qta.IconWidget()
            self._spinner_widget.setFixedSize(24, 24)
            spinner_row.addWidget(self._spinner_widget)
        else:
            self._spinner_widget = None
        
        self._loading_label = QLabel()
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._loading_label.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 12px;
                padding-left: 8px;
                background: transparent;
            }
        """)
        spinner_row.addWidget(self._loading_label)
        spinner_row.addStretch(1)
        
        loading_layout.addLayout(spinner_row)
        loading_layout.addStretch(1)
        
        self._loading_container.hide()
        layout.addWidget(self._loading_container, 1)  # stretch=1 to fill space

    def _apply_theme(self):
        """Apply theme to tree widget"""
        from src.design_system.tokens import get_colors, RADIUS
        colors_tk = get_colors()
        
        if self.theme_manager:
            colors = self.theme_manager.get_app_colors()
        else:
            colors = {
                "background": colors_tk.bg_primary,
                "foreground": colors_tk.text_primary,
                "border": colors_tk.border_default,
            }

        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: none;
                font-size: 12px;
            }}
            QTreeWidget::item {{
                padding: 5px 6px;
                border-radius: 4px;
                margin: 1px 4px;
            }}
            QTreeWidget::item:selected {{
                background-color: {colors_tk.interactive_primary};
                color: {colors_tk.text_inverse};
            }}
            QTreeWidget::item:hover {{
                background-color: {colors_tk.bg_elevated};
            }}
            QTreeWidget::branch {{
                background: transparent;
            }}
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {{
                image: url(none);
                border-image: none;
            }}
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {{
                image: url(none);
                border-image: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(128, 128, 128, 0.3);
                border-radius: 4px;
                min-height: 40px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(128, 128, 128, 0.5);
            }}
            QScrollBar::handle:vertical:pressed {{
                background: rgba(128, 128, 128, 0.7);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: rgba(128, 128, 128, 0.3);
                border-radius: 4px;
                min-width: 40px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: rgba(128, 128, 128, 0.5);
            }}
            QScrollBar::handle:horizontal:pressed {{
                background: rgba(128, 128, 128, 0.7);
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
            QScrollBar::corner {{
                background: transparent;
            }}
        """)

    def set_theme_manager(self, theme_manager):
        """Set theme manager"""
        self.theme_manager = theme_manager
        self._apply_theme()

    def set_loading(self, loading: bool, message: str = ""):
        """Show or hide loading state.
        
        Args:
            loading: True to show loading, False to hide
            message: Optional message to display (default: "Loading...")
        """
        if loading:
            if HAS_QTAWESOME and self._spinner_widget:
                # Create animated spinner icon and set it
                spin_icon = qta.icon("fa5s.spinner", animation=qta.Spin(self._spinner_widget), color="#888")
                self._spinner_widget.setIcon(spin_icon)
                self._spinner_widget.show()
            self._loading_label.setText(message or "Loading...")
            self._loading_container.show()
            self.tree.hide()
        else:
            self._loading_container.hide()
            if self._spinner_widget:
                self._spinner_widget.hide()
            self.tree.show()

    def set_schema(self, schema: dict, connection_name: str = "", db_type: str = ""):
        """Set the schema to be displayed in the tree.

        Args:
            schema: dict with keys 'database', 'tables', 'columns',
                    optionally 'databases' (list of all databases)
                    (format from SchemaService)
            connection_name: connection name
            db_type: database type (mssql, postgresql, mysql, etc.)
        """
        self.set_loading(False)  # Hide loading when schema arrives
        self._current_schema = schema
        self._current_connection = connection_name
        self._db_type = db_type.lower() if db_type else ""
        if schema:
            self._all_databases = schema.get("databases", [])
        self._build_tree(schema)

    def clear(self):
        """Clear tree"""
        self.tree.clear()
        self._current_schema = None
        self._current_connection = ""
        self._db_type = ""
        self._all_databases = []
        self.info_label.setText(S.object_explorer.no_connection)
        self.search_input.clear()

    def _quote_identifier(self, identifier: str) -> str:
        """Quote SQL identifier based on current db_type.
        
        Args:
            identifier: Table or column name (may include schema: schema.table)
        
        Returns:
            Properly quoted identifier for safe SQL use
        """
        parts = identifier.split(".", 1)
        db_type = self._db_type
        
        if db_type in ("sqlserver", "mssql", ""):
            # SQL Server uses [brackets] - default for SELECT TOP queries
            quoted_parts = [f"[{p}]" for p in parts]
        elif db_type in ("postgres", "postgresql"):
            quoted_parts = [f'"{p}"' for p in parts]
        elif db_type in ("mysql", "mariadb"):
            quoted_parts = [f"`{p}`" for p in parts]
        else:
            # ANSI SQL double quotes
            quoted_parts = [f'"{p}"' for p in parts]
        
        return ".".join(quoted_parts)

    def _build_tree(self, schema: dict):
        """Build tree from schema"""
        self.tree.clear()

        if not schema:
            self.info_label.setText(S.object_explorer.no_connection)
            return

        tables = schema.get("tables", [])
        columns = schema.get("columns", {})
        db_name = schema.get("database", "")
        all_databases = schema.get("databases", [])

        filter_text = self.search_input.text().strip().lower()

        # Criar nos raiz para cada banco do servidor
        if all_databases:
            for db in sorted(all_databases):
                is_current = (db.lower() == db_name.lower()) if db_name else False

                # So o banco atual tem tabelas/colunas carregados
                if is_current:
                    # Quando filtro ativo, verificar se banco tem conteudo relevante
                    if filter_text:
                        has_match = any(
                            filter_text in t.get("name", "").lower()
                            or any(filter_text in c.get("name", "").lower() for c in columns.get(t.get("name", ""), []))
                            for t in tables
                        )
                        # Verificar tambem se o nome do banco corresponde
                        if not has_match and filter_text not in db.lower():
                            continue

                    display = f"{db} {S.object_explorer.db_connected.format(db='')}" if not filter_text else db
                    db_item = QTreeWidgetItem(self.tree, [display])
                    db_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "database", "name": db})

                    if HAS_QTAWESOME:
                        db_item.setIcon(0, qta.icon("mdi.database", color="#569cd6"))

                    font = db_item.font(0)
                    font.setBold(True)
                    db_item.setFont(0, font)

                    self._add_tables_to_node(db_item, tables, columns, filter_text)
                    db_item.setExpanded(True)
                else:
                    # Bancos nao-atuais: esconder quando filtro ativo (nao tem tabelas carregadas)
                    if filter_text:
                        # Mostrar apenas se nome do banco corresponde ao filtro
                        if filter_text not in db.lower():
                            continue

                    display = db
                    db_item = QTreeWidgetItem(self.tree, [display])
                    db_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "database", "name": db})

                    if HAS_QTAWESOME:
                        db_item.setIcon(0, qta.icon("mdi.database", color="#888888"))
        else:
            # Fallback: apenas o banco conectado (sem lista de bancos)
            db_display = db_name or self._current_connection or "Database"
            db_item = QTreeWidgetItem(self.tree, [db_display])
            db_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "database", "name": db_name})

            if HAS_QTAWESOME:
                db_item.setIcon(0, qta.icon("mdi.database", color="#569cd6"))

            font = db_item.font(0)
            font.setBold(True)
            db_item.setFont(0, font)

            self._add_tables_to_node(db_item, tables, columns, filter_text)
            db_item.setExpanded(True)

        # Atualizar info
        table_count = len(tables)
        col_count = sum(len(v) for v in columns.values())
        db_count = len(all_databases)
        if db_count > 0:
            self.info_label.setText(S.object_explorer.info_dbs_tables.format(dbs=db_count, tables=table_count))
        else:
            self.info_label.setText(S.object_explorer.info_tables_cols.format(tables=table_count, cols=col_count))

    def _add_tables_to_node(self, parent_item, tables, columns, filter_text=""):
        """Adiciona tabelas e colunas a um no da arvore.

        Args:
            parent_item: QTreeWidgetItem pai (banco)
            tables: lista de tabelas
            columns: dict de colunas por tabela
            filter_text: filtro de busca (lowercase)
        """
        # Agrupar tabelas por schema
        schema_groups = {}
        for table in tables:
            table_schema = table.get("schema", "")
            if table_schema not in schema_groups:
                schema_groups[table_schema] = []
            schema_groups[table_schema].append(table)

        use_schema_nodes = len(schema_groups) > 1

        for schema_name, schema_tables in sorted(schema_groups.items()):
            schema_item = None
            if use_schema_nodes and schema_name:
                schema_item = QTreeWidgetItem(parent_item, [schema_name])
                schema_item.setData(
                    0, Qt.ItemDataRole.UserRole,
                    {"type": "schema", "name": schema_name},
                )
                if HAS_QTAWESOME:
                    schema_item.setIcon(0, qta.icon("mdi.folder", color="#dcdc8b"))
                parent = schema_item
            else:
                parent = parent_item

            for table in sorted(schema_tables, key=lambda t: t.get("name", "")):
                table_name = table.get("name", "")
                table_type = table.get("type", "TABLE")
                table_schema = table.get("schema", "")

                # Colunas da tabela
                table_columns = columns.get(table_name, [])

                # Filtro de busca: verificar se tabela ou alguma coluna corresponde
                if filter_text:
                    table_match = filter_text in table_name.lower()
                    col_match = any(filter_text in c.get("name", "").lower() for c in table_columns)
                    if not table_match and not col_match:
                        continue

                is_view = "VIEW" in table_type.upper()
                label = table_name
                if is_view:
                    label = f"{table_name} {S.object_explorer.view_suffix}"

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

                # Determinar se a tabela em si corresponde ao filtro
                table_matches_filter = filter_text in table_name.lower() if filter_text else True

                for col in table_columns:
                    col_name = col.get("name", "")
                    col_type = col.get("type", "")
                    nullable = col.get("nullable", "YES")

                    # Quando filtro ativo, sempre filtrar colunas individualmente
                    if filter_text and filter_text not in col_name.lower() and filter_text not in col_type.lower():
                        continue

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

                    col_item.setForeground(0, QColor("#b0b0b0"))

                # Expandir tabela se filtro ativo e ha match
                if filter_text:
                    table_item.setExpanded(True)

            # Remover schema node vazio apos filtro
            if schema_item is not None and schema_item.childCount() == 0:
                parent_item.removeChild(schema_item)

    def _on_search_changed(self, text: str):
        """Chamado quando texto de busca muda - debounce para reconstruir arvore"""
        if self._filter_timer is None:
            self._filter_timer = QTimer(self)
            self._filter_timer.setSingleShot(True)
            self._filter_timer.timeout.connect(self._apply_filter)
        self._filter_timer.start(200)  # 200ms debounce

    def _apply_filter(self):
        """Aplica filtro de busca reconstruindo a arvore"""
        if self._current_schema:
            self._build_tree(self._current_schema)

    def _on_double_click(self, item: QTreeWidgetItem, column: int):
        """Duplo clique: append no editor para qualquer objeto, troca banco para database"""
        if item is None:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        item_type = data.get("type", "")
        name = data.get("name", "")

        if item_type == "database" and name:
            # Trocar banco ativo da conexao da aba
            self.database_switch_requested.emit(name)
        elif item_type in ("table", "column", "schema") and name:
            self.insert_text_requested.emit(name)

    def _start_drag(self, supported_actions):
        """Start drag for database items from Object Explorer"""
        item = self.tree.currentItem()
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        item_type = data.get("type", "")
        name = data.get("name", "")

        if item_type != "database" or not name:
            return

        mime_data = QMimeData()
        mime_data.setData("application/x-database-name", name.encode("utf-8"))

        # Include connection name so drop target knows which connection to use
        if self._current_connection:
            mime_data.setData(
                "application/x-connection-name",
                self._current_connection.encode("utf-8"),
            )

        drag = QDrag(self.tree)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)

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
            # Selecionar 1000 linhas with proper quoting
            qualified = f"{schema_name}.{name}" if schema_name else name
            quoted = self._quote_identifier(qualified)
            
            # Build query based on database type
            if self._db_type in ("mysql", "mariadb", "postgres", "postgresql", "sqlite"):
                select_query = f"SELECT * FROM {quoted} LIMIT 1000"
            else:
                # SQL Server / default
                select_query = f"SELECT TOP 1000 * FROM {quoted}"
            
            act_select = menu.addAction(S.object_explorer.ctx_select_top)
            act_select.triggered.connect(
                lambda _, q=select_query: self.query_requested.emit(q)
            )

            menu.addSeparator()

            # Inserir nome no editor
            act_insert = menu.addAction(S.object_explorer.ctx_insert_name)
            act_insert.triggered.connect(lambda: self.insert_text_requested.emit(name))

            # Copiar nome
            act_copy = menu.addAction(S.object_explorer.ctx_copy_name)
            act_copy.triggered.connect(lambda: QApplication.clipboard().setText(name))

            # Copiar nome qualificado
            if schema_name:
                act_copy_qual = menu.addAction(S.object_explorer.ctx_copy_qualified)
                act_copy_qual.triggered.connect(
                    lambda: QApplication.clipboard().setText(f"{schema_name}.{name}")
                )

        elif item_type == "column":
            table_name = data.get("table", "")
            col_type = data.get("data_type", "")

            # Inserir nome no editor
            act_insert = menu.addAction(S.object_explorer.ctx_insert_name)
            act_insert.triggered.connect(lambda: self.insert_text_requested.emit(name))

            # Copiar nome
            act_copy = menu.addAction(S.object_explorer.ctx_copy_name)
            act_copy.triggered.connect(lambda: QApplication.clipboard().setText(name))

            # Copiar como table.column
            if table_name:
                act_copy_full = menu.addAction(S.object_explorer.ctx_copy_as_qualified.format(table=table_name, name=name))
                act_copy_full.triggered.connect(
                    lambda: QApplication.clipboard().setText(f"{table_name}.{name}")
                )

            menu.addSeparator()

            # Info do tipo (desabilitado)
            act_type_info = menu.addAction(S.object_explorer.ctx_type_info.format(type=col_type))
            act_type_info.setEnabled(False)

        elif item_type == "database":
            # Switch to this database
            act_switch = menu.addAction(S.object_explorer.ctx_use_database.format(name=name))
            act_switch.triggered.connect(lambda: self.database_switch_requested.emit(name))

            menu.addSeparator()

            # Copy database name
            act_copy = menu.addAction(S.object_explorer.ctx_copy_db_name)
            act_copy.triggered.connect(lambda: QApplication.clipboard().setText(name))

        else:
            return

        menu.exec(self.tree.viewport().mapToGlobal(pos))
