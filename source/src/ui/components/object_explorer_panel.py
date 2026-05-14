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
    QStyledItemDelegate,
    QStyleOptionViewItem,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QMimeData, QRect, QModelIndex, QPoint
from PyQt6.QtGui import QFont, QColor, QAction, QDrag, QPainter, QPen, QMouseEvent

from .buttons import GhostButton

from src.language import S

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

import logging

logger = logging.getLogger(__name__)


class InsertButtonDelegate(QStyledItemDelegate):
    """Delegate that paints a >> button on the right side of tree items.
    
    The button appears on hover and emits insert_clicked when clicked.
    Only shows for items that have meaningful content to insert
    (tables, columns, schemas, catalogs, databases).
    """
    
    insert_clicked = pyqtSignal(QTreeWidgetItem)
    
    BUTTON_WIDTH = 24
    BUTTON_MARGIN = 4
    
    def __init__(self, tree: QTreeWidget, parent=None):
        super().__init__(parent)
        self._tree = tree
        self._hovered_index: QModelIndex | None = None
        # Enable mouse tracking on the viewport for hover detection
        self._tree.viewport().setMouseTracking(True)
        self._tree.viewport().installEventFilter(self)
    
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        """Paint the item normally, then overlay >> button on hover."""
        super().paint(painter, option, index)
        
        # Only paint >> on hovered row
        if self._hovered_index is not None and index.row() == self._hovered_index.row() and index.parent() == self._hovered_index.parent():
            item = self._tree.itemFromIndex(index)
            if item:
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data and data.get("type") != self._tree.parent().PLACEHOLDER_TYPE:
                    btn_rect = self._get_button_rect(option.rect)
                    
                    painter.save()
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    
                    # Draw >> text
                    painter.setPen(QPen(QColor("#569cd6")))
                    font = painter.font()
                    font.setPointSize(9)
                    font.setBold(True)
                    painter.setFont(font)
                    painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, ">>")
                    
                    painter.restore()
    
    def _get_button_rect(self, item_rect: QRect) -> QRect:
        """Get the rectangle for the >> button at the right edge of item."""
        return QRect(
            item_rect.right() - self.BUTTON_WIDTH - self.BUTTON_MARGIN,
            item_rect.top(),
            self.BUTTON_WIDTH,
            item_rect.height()
        )
    
    def eventFilter(self, obj, event):
        """Track mouse for hover and click on >> button."""
        if obj is self._tree.viewport():
            if event.type() == event.Type.MouseMove:
                pos = event.pos()
                index = self._tree.indexAt(pos)
                if index.isValid():
                    if self._hovered_index != index:
                        self._hovered_index = index
                        self._tree.viewport().update()
                else:
                    if self._hovered_index is not None:
                        self._hovered_index = None
                        self._tree.viewport().update()
            elif event.type() == event.Type.Leave:
                if self._hovered_index is not None:
                    self._hovered_index = None
                    self._tree.viewport().update()
            elif event.type() == event.Type.MouseButtonPress:
                pos = event.pos()
                index = self._tree.indexAt(pos)
                if index.isValid():
                    item = self._tree.itemFromIndex(index)
                    if item:
                        vis_rect = self._tree.visualItemRect(item)
                        btn_rect = self._get_button_rect(vis_rect)
                        if btn_rect.contains(pos):
                            self.insert_clicked.emit(item)
                            return True  # consume the event
        return super().eventFilter(obj, event)


class ObjectExplorerPanel(QWidget):
    """Object Explorer Panel - displays database structure in tree"""

    # Signals
    insert_text_requested = pyqtSignal(str)  # text to insert (append) in focused editor
    query_requested = pyqtSignal(str)  # SQL query to execute
    database_switch_requested = pyqtSignal(str)  # database name to switch to
    # Lazy loading signals
    schemas_requested = pyqtSignal(str)  # catalog_name -> request schemas for this catalog
    tables_requested = pyqtSignal(str, str)  # catalog, schema -> request tables
    columns_requested = pyqtSignal(str, str, str)  # catalog, schema, table -> request columns

    # Placeholder marker for lazy loading
    PLACEHOLDER_TYPE = "__placeholder__"

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

        # Connection header (shows connection name + database)
        self._conn_label = QLabel(S.object_explorer.no_connection)
        self._conn_label.setStyleSheet("color: #cccccc; font-weight: bold; font-size: 12px;")
        toolbar_layout.addWidget(self._conn_label)

        toolbar_layout.addStretch()

        # Info label (stats: tables, columns count)
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: #808080; font-size: 11px;")
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

        # Double click - only expand/collapse
        self.tree.itemDoubleClicked.connect(self._on_double_click)

        # >> insert button delegate
        self._insert_delegate = InsertButtonDelegate(self.tree, self)
        self.tree.setItemDelegate(self._insert_delegate)
        self._insert_delegate.insert_clicked.connect(self._on_insert_clicked)

        # Lazy loading on expand
        self.tree.itemExpanded.connect(self._on_item_expanded)

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

    def set_error(self, message: str):
        """Show error state in the OE panel (replaces loading spinner)."""
        self.set_loading(False)
        self.info_label.setText(message)
        self.info_label.setStyleSheet("color: #f44747; font-size: 11px;")

    def _save_expansion_state(self) -> set:
        """Save the set of expanded node paths (type:name) before tree rebuild."""
        expanded = set()

        def _walk(item, path_prefix=""):
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data:
                node_type = data.get("type", "")
                node_name = data.get("name", "")
                path = f"{path_prefix}/{node_type}:{node_name}"
            else:
                path = f"{path_prefix}/{item.text(0)}"

            if item.isExpanded():
                expanded.add(path)

            for i in range(item.childCount()):
                _walk(item.child(i), path)

        for i in range(self.tree.topLevelItemCount()):
            _walk(self.tree.topLevelItem(i))

        return expanded

    def _restore_expansion_state(self, expanded_paths: set):
        """Restore expansion state for nodes that still exist."""
        if not expanded_paths:
            return

        def _walk(item, path_prefix=""):
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data:
                node_type = data.get("type", "")
                node_name = data.get("name", "")
                path = f"{path_prefix}/{node_type}:{node_name}"
            else:
                path = f"{path_prefix}/{item.text(0)}"

            if path in expanded_paths:
                item.setExpanded(True)

            for i in range(item.childCount()):
                _walk(item.child(i), path)

        for i in range(self.tree.topLevelItemCount()):
            _walk(self.tree.topLevelItem(i))

    def set_schema(self, schema: dict, connection_name: str = "", db_type: str = ""):
        """Set the schema to be displayed in the tree.

        Args:
            schema: dict with keys 'database', 'tables', 'columns',
                    optionally 'databases' (list of all databases)
                    (format from SchemaService)
            connection_name: connection name
            db_type: database type (mssql, postgresql, mysql, etc.)
        """
        # Guard against invalid data (e.g., Mock objects from async tests)
        if not isinstance(schema, dict) or not isinstance(connection_name, str):
            return
        
        self.set_loading(False)  # Hide loading when schema arrives
        self.info_label.setStyleSheet("color: #808080; font-size: 11px;")  # Reset error style
        self._current_schema = schema
        self._current_connection = connection_name
        self._db_type = db_type.lower() if db_type else ""
        if schema:
            self._all_databases = schema.get("databases", [])
        
        # Update connection header
        db_name = schema.get("database", "") if schema else ""
        if connection_name and db_name:
            self._conn_label.setText(S.object_explorer.header_connection.format(
                connection=connection_name, database=db_name
            ))
        elif connection_name:
            self._conn_label.setText(S.object_explorer.header_no_database.format(
                connection=connection_name
            ))
        else:
            self._conn_label.setText(S.object_explorer.no_connection)
        
        self._build_tree(schema)

    def clear(self):
        """Clear tree"""
        self.tree.clear()
        self._current_schema = None
        self._current_connection = ""
        self._db_type = ""
        self._all_databases = []
        self._conn_label.setText(S.object_explorer.no_connection)
        self.info_label.setText("")
        self.search_input.clear()

    def _quote_identifier(self, identifier: str) -> str:
        """Quote SQL identifier based on current db_type.
        
        Args:
            identifier: Table or column name (may include schema: schema.table
                        or catalog.schema.table for Databricks)
        
        Returns:
            Properly quoted identifier for safe SQL use
        """
        parts = identifier.split(".")
        db_type = self._db_type
        
        if db_type in ("sqlserver", "mssql", ""):
            # SQL Server uses [brackets] - default for SELECT TOP queries
            quoted_parts = [f"[{p}]" for p in parts]
        elif db_type in ("postgres", "postgresql"):
            quoted_parts = [f'"{p}"' for p in parts]
        elif db_type in ("mysql", "mariadb", "databricks"):
            quoted_parts = [f"`{p}`" for p in parts]
        else:
            # ANSI SQL double quotes
            quoted_parts = [f'"{p}"' for p in parts]
        
        return ".".join(quoted_parts)

    def _get_column_display_type(self, column_info: dict) -> str:
        return str(
            column_info.get("display_type")
            or column_info.get("data_type")
            or column_info.get("type")
            or ""
        )

    def _format_column_label(self, column_info: dict) -> str:
        col_name = column_info.get("name", "")
        col_type = self._get_column_display_type(column_info)
        nullable = str(column_info.get("nullable", "YES"))

        display = f"{col_name}  ({col_type})" if col_type else str(col_name)
        if nullable.upper() == "NO":
            display += f"  {S.object_explorer.not_null}"
        return display

    def _get_item_qualified_name(self, data: dict) -> str:
        catalog = data.get("catalog", "")
        schema_name = data.get("schema", "")
        name = data.get("name", "")

        if catalog and schema_name:
            return f"{catalog}.{schema_name}.{name}"
        if schema_name:
            return f"{schema_name}.{name}"
        return str(name)

    def _get_cached_columns_for_table(self, table_data: dict) -> list:
        if not self._current_schema:
            return []

        columns = self._current_schema.get("columns", {})
        table_key = table_data.get("key", "")
        schema_name = table_data.get("schema", "")
        table_name = table_data.get("name", "")

        lookup_keys = [key for key in (
            table_key,
            f"{schema_name}.{table_name}" if schema_name else "",
            table_name,
        ) if key]

        for lookup_key in lookup_keys:
            if lookup_key in columns:
                return columns.get(lookup_key, [])
        return []

    def _get_column_metadata_for_table(self, table_item: QTreeWidgetItem) -> list:
        table_data = table_item.data(0, Qt.ItemDataRole.UserRole) or {}
        cached_columns = self._get_cached_columns_for_table(table_data)
        if cached_columns:
            return cached_columns

        columns = []
        for index in range(table_item.childCount()):
            child = table_item.child(index)
            child_data = child.data(0, Qt.ItemDataRole.UserRole)
            if child_data and child_data.get("type") == "column":
                columns.append(
                    {
                        "name": child_data.get("name", ""),
                        "display_type": child_data.get("display_type", ""),
                        "type": child_data.get("data_type", ""),
                        "nullable": child_data.get("nullable", "YES"),
                    }
                )
        return columns

    def _build_create_table_script(self, table_item: QTreeWidgetItem) -> str:
        table_data = table_item.data(0, Qt.ItemDataRole.UserRole) or {}
        qualified_name = self._get_item_qualified_name(table_data)
        quoted_name = self._quote_identifier(qualified_name)
        columns = self._get_column_metadata_for_table(table_item)

        if columns:
            column_lines = []
            for column in columns:
                col_name = column.get("name", "")
                col_type = self._get_column_display_type(column)
                nullable = "NOT NULL" if str(column.get("nullable", "YES")).upper() == "NO" else "NULL"
                column_lines.append(
                    f"    {self._quote_identifier(col_name)} {col_type} {nullable}".rstrip()
                )
            body = ",\n".join(column_lines)
        else:
            body = "    -- Expand the table to load column metadata and regenerate this script."

        return f"CREATE TABLE {quoted_name} (\n{body}\n);"

    def _build_drop_and_create_script(self, table_item: QTreeWidgetItem) -> str:
        table_data = table_item.data(0, Qt.ItemDataRole.UserRole) or {}
        qualified_name = self._get_item_qualified_name(table_data)
        quoted_name = self._quote_identifier(qualified_name)

        if self._db_type in ("mssql", "sqlserver", ""):
            drop_statement = (
                f"IF OBJECT_ID(N'{qualified_name}', N'U') IS NOT NULL\n"
                f"    DROP TABLE {quoted_name};"
            )
        else:
            drop_statement = f"DROP TABLE IF EXISTS {quoted_name};"

        return f"{drop_statement}\n\n{self._build_create_table_script(table_item)}"

    def _build_tree(self, schema: dict):
        """Build tree from schema.

        For Databricks: Catalog > Schema > Table > Columns (3-level namespace)
        For SQL Server/MySQL: Database > Schema > Table > Columns
        For PostgreSQL: Database > Schema > Table > Columns (single DB only)
        """
        # Disable updates during bulk tree building to prevent UI freezes
        self.tree.setUpdatesEnabled(False)
        try:
            self._do_build_tree(schema)
        finally:
            self.tree.setUpdatesEnabled(True)

    def _do_build_tree(self, schema: dict):
        """Internal tree building implementation."""
        # Save expansion state before clearing
        expanded_paths = self._save_expansion_state()
        
        self.tree.clear()

        if not schema:
            self._conn_label.setText(S.object_explorer.no_connection)
            self.info_label.setText("")
            return

        tables = schema.get("tables", [])
        columns = schema.get("columns", {})
        db_name = schema.get("database", "")
        all_databases = schema.get("databases", [])
        
        # Guard: ensure db_name is a string (protect against Mock objects from async tests)
        if not isinstance(db_name, str):
            db_name = ""

        filter_text = self.search_input.text().strip().lower()

        is_databricks = self._db_type == "databricks"

        if is_databricks:
            self._build_tree_databricks(tables, columns, db_name, all_databases, filter_text)
        elif all_databases and len(all_databases) > 1:
            self._build_tree_multi_db(tables, columns, db_name, all_databases, filter_text)
        else:
            # Single database (PostgreSQL, or single MySQL/MariaDB)
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

        # Update info label
        table_count = len(tables)
        col_count = sum(len(v) for v in columns.values())
        db_count = len(all_databases)
        if is_databricks and db_count > 0:
            self.info_label.setText(S.object_explorer.info_catalogs_tables.format(
                catalogs=db_count, tables=table_count
            ))
        elif db_count > 0:
            self.info_label.setText(S.object_explorer.info_dbs_tables.format(dbs=db_count, tables=table_count))
        else:
            self.info_label.setText(S.object_explorer.info_tables_cols.format(tables=table_count, cols=col_count))

        # Restore expansion state
        self._restore_expansion_state(expanded_paths)

    def _build_tree_databricks(self, tables, columns, current_catalog, all_catalogs, filter_text):
        """Build tree for Databricks 3-level namespace: Catalog > Schema > Table > Columns
        
        Uses lazy loading: only catalogs shown initially, schemas/tables/columns loaded on expand.
        Exception: when filter is active, loads matching items fully.
        """
        logger.info(f"[OE Databricks] Building tree: {len(tables)} tables, {len(all_catalogs)} catalogs, current={current_catalog}")
        
        # If filter is active, use full loading (old behavior)
        if filter_text:
            self._build_tree_databricks_full(tables, columns, current_catalog, all_catalogs, filter_text)
            return

        # Lazy loading mode: show catalogs with placeholder children
        for catalog in sorted(all_catalogs):
            is_current = (catalog.lower() == current_catalog.lower()) if current_catalog else False

            if is_current:
                display = f"{catalog} {S.object_explorer.db_connected.format(db='')}"
            else:
                display = catalog

            cat_item = QTreeWidgetItem(self.tree, [display])
            cat_item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "catalog", "name": catalog
            })

            icon_color = "#569cd6" if is_current else "#888888"
            if HAS_QTAWESOME:
                cat_item.setIcon(0, qta.icon("mdi.database", color=icon_color))

            if is_current:
                font = cat_item.font(0)
                font.setBold(True)
                cat_item.setFont(0, font)
                
                # For current catalog, show schemas if we have table data
                if tables:
                    # Extract unique schemas from tables
                    schemas = sorted(set(t.get("schema", "") for t in tables if t.get("schema")))
                    for schema_name in schemas:
                        schema_item = QTreeWidgetItem(cat_item, [schema_name])
                        schema_item.setData(0, Qt.ItemDataRole.UserRole, {
                            "type": "schema", "name": schema_name, "catalog": catalog
                        })
                        if HAS_QTAWESOME:
                            schema_item.setIcon(0, qta.icon("mdi.folder", color="#dcdc8b"))
                        # Add placeholder for tables (lazy load)
                        self._add_placeholder_child(schema_item)
                else:
                    # No tables loaded yet, add placeholder
                    self._add_placeholder_child(cat_item)
                # Auto-expand current catalog
                cat_item.setExpanded(True)
            else:
                # Non-current catalogs get placeholder for lazy loading
                self._add_placeholder_child(cat_item)

    def _build_tree_databricks_full(self, tables, columns, current_catalog, all_catalogs, filter_text):
        """Build full tree for Databricks with filter active (loads everything)."""
        if tables:
            schemas_in_tables = set(t.get("schema", "") for t in tables)
            logger.info(f"[OE Databricks] Schemas found in tables: {schemas_in_tables}")
        for catalog in sorted(all_catalogs):
            is_current = (catalog.lower() == current_catalog.lower()) if current_catalog else False

            if is_current:
                has_match = any(
                    filter_text in t.get("name", "").lower()
                    or filter_text in t.get("schema", "").lower()
                    or any(filter_text in c.get("name", "").lower()
                           for c in columns.get(t.get("key", t.get("name", "")), []))
                    for t in tables
                )
                if not has_match and filter_text not in catalog.lower():
                    continue

                display = catalog  # No "(connected)" suffix when filtering
                cat_item = QTreeWidgetItem(self.tree, [display])
                cat_item.setData(0, Qt.ItemDataRole.UserRole, {
                    "type": "catalog", "name": catalog
                })

                if HAS_QTAWESOME:
                    cat_item.setIcon(0, qta.icon("mdi.database", color="#569cd6"))

                font = cat_item.font(0)
                font.setBold(True)
                cat_item.setFont(0, font)

                # Load full tree when filtering
                self._add_tables_to_node(cat_item, tables, columns, filter_text, catalog=catalog)
                cat_item.setExpanded(True)
            else:
                if filter_text and filter_text not in catalog.lower():
                    continue

                cat_item = QTreeWidgetItem(self.tree, [catalog])
                cat_item.setData(0, Qt.ItemDataRole.UserRole, {
                    "type": "catalog", "name": catalog
                })
                if HAS_QTAWESOME:
                    cat_item.setIcon(0, qta.icon("mdi.database", color="#888888"))

    def _build_tree_multi_db(self, tables, columns, db_name, all_databases, filter_text):
        """Build tree for multi-database servers (SQL Server, MySQL)
        
        Uses lazy loading: databases shown initially, tables/columns loaded on expand.
        Exception: when filter is active, loads matching items fully.
        """
        # If filter is active, use full loading
        if filter_text:
            self._build_tree_multi_db_full(tables, columns, db_name, all_databases, filter_text)
            return
        
        # Lazy loading mode
        for db in sorted(all_databases):
            is_current = (db.lower() == db_name.lower()) if db_name else False

            if is_current:
                display = f"{db} {S.object_explorer.db_connected.format(db='')}"
            else:
                display = db
                
            db_item = QTreeWidgetItem(self.tree, [display])
            db_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "database", "name": db})

            icon_color = "#569cd6" if is_current else "#888888"
            if HAS_QTAWESOME:
                db_item.setIcon(0, qta.icon("mdi.database", color=icon_color))

            if is_current:
                font = db_item.font(0)
                font.setBold(True)
                db_item.setFont(0, font)
                
                # For current db, show tables with placeholder for columns
                if tables:
                    self._add_table_items(db_item, tables, with_column_placeholder=True)
                else:
                    self._add_placeholder_child(db_item)
                # Auto-expand current db
                db_item.setExpanded(True)
            else:
                # Non-current databases get placeholder for lazy loading
                self._add_placeholder_child(db_item)

    def _build_tree_multi_db_full(self, tables, columns, db_name, all_databases, filter_text):
        """Build full tree for multi-DB with filter active (loads everything)."""
        for db in sorted(all_databases):
            is_current = (db.lower() == db_name.lower()) if db_name else False

            if is_current:
                has_match = any(
                    filter_text in t.get("name", "").lower()
                    or any(filter_text in c.get("name", "").lower()
                           for c in columns.get(t.get("key", t.get("name", "")), []))
                    for t in tables
                )
                if not has_match and filter_text not in db.lower():
                    continue

                display = db  # No "(connected)" suffix when filtering
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
                if filter_text and filter_text not in db.lower():
                    continue

                db_item = QTreeWidgetItem(self.tree, [db])
                db_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "database", "name": db})

                if HAS_QTAWESOME:
                    db_item.setIcon(0, qta.icon("mdi.database", color="#888888"))

    def _add_tables_to_node(self, parent_item, tables, columns, filter_text="", catalog: str = ""):
        """Adiciona tabelas e colunas a um no da arvore.

        Args:
            parent_item: QTreeWidgetItem pai (banco ou catalog)
            tables: lista de tabelas
            columns: dict de colunas por table_key (schema.table_name)
            filter_text: filtro de busca (lowercase)
            catalog: Databricks catalog name (for full namespace references)
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
                    {"type": "schema", "name": schema_name, "catalog": catalog},
                )
                if HAS_QTAWESOME:
                    schema_item.setIcon(0, qta.icon("mdi.folder", color="#dcdc8b"))
                parent = schema_item
                # Expand schema nodes by default so tables are visible
                schema_item.setExpanded(True)
            else:
                parent = parent_item

            for table in sorted(schema_tables, key=lambda t: t.get("name", "")):
                table_name = table.get("name", "")
                table_key = table.get("key", table_name)
                table_type = table.get("type", "TABLE")
                table_schema = table.get("schema", "")

                # Columns use the composite key (schema.table) for lookup
                table_columns = columns.get(table_key, [])

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
                        "key": table_key,
                        "schema": table_schema,
                        "catalog": catalog,
                        "table_type": table_type,
                    },
                )

                if HAS_QTAWESOME:
                    if is_view:
                        table_item.setIcon(0, qta.icon("mdi.table-eye", color="#4ec9b0"))
                    else:
                        table_item.setIcon(0, qta.icon("mdi.table", color="#4ec9b0"))

                for col in table_columns:
                    col_name = col.get("name", "")
                    col_type = self._get_column_display_type(col)

                    # Quando filtro ativo, filtrar colunas individualmente
                    if filter_text and filter_text not in col_name.lower() and filter_text not in col_type.lower():
                        continue

                    self._add_column_item(
                        table_item,
                        col,
                        table_name=table_name,
                        table_key=table_key,
                        table_schema=table_schema,
                        catalog=catalog,
                    )

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

    def _add_placeholder_child(self, parent_item: QTreeWidgetItem):
        """Add a placeholder child to make item expandable. Will be replaced on expand."""
        placeholder = QTreeWidgetItem(parent_item, [S.object_explorer.loading if hasattr(S.object_explorer, 'loading') else "Loading..."])
        placeholder.setData(0, Qt.ItemDataRole.UserRole, {"type": self.PLACEHOLDER_TYPE})
        placeholder.setForeground(0, QColor("#808080"))
        if HAS_QTAWESOME:
            placeholder.setIcon(0, qta.icon("mdi.loading", color="#808080"))

    def _add_column_item(
        self,
        table_item: QTreeWidgetItem,
        column_info: dict,
        table_name: str,
        table_key: str = "",
        table_schema: str = "",
        catalog: str = "",
    ):
        col_name = column_info.get("name", "")
        col_type = column_info.get("type", "")
        display_type = self._get_column_display_type(column_info)
        nullable = column_info.get("nullable", "YES")

        col_item = QTreeWidgetItem(table_item, [self._format_column_label(column_info)])
        col_item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "type": "column",
                "name": col_name,
                "data_type": col_type,
                "display_type": display_type,
                "nullable": nullable,
                "table": table_name,
                "table_key": table_key,
                "schema": table_schema,
                "catalog": catalog,
            },
        )

        if HAS_QTAWESOME:
            col_item.setIcon(0, qta.icon("mdi.table-column", color="#888888"))

        col_item.setForeground(0, QColor("#b0b0b0"))

    def _has_placeholder_child(self, item: QTreeWidgetItem) -> bool:
        """Check if item has a placeholder child (needs lazy loading)."""
        if item.childCount() == 0:
            return False
        first_child = item.child(0)
        data = first_child.data(0, Qt.ItemDataRole.UserRole)
        return data and data.get("type") == self.PLACEHOLDER_TYPE

    def _remove_placeholder_children(self, item: QTreeWidgetItem):
        """Remove placeholder children from item."""
        to_remove = []
        for i in range(item.childCount()):
            child = item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == self.PLACEHOLDER_TYPE:
                to_remove.append(child)
        for child in to_remove:
            item.removeChild(child)

    def _on_item_expanded(self, item: QTreeWidgetItem):
        """Handle item expansion for lazy loading."""
        if item is None:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        # Check if this item needs lazy loading (has placeholder child)
        if not self._has_placeholder_child(item):
            return

        item_type = data.get("type", "")
        name = data.get("name", "")
        catalog = data.get("catalog", "")

        if item_type == "catalog" and name:
            # Request schemas/tables for this catalog
            self.schemas_requested.emit(name)
        elif item_type == "schema" and name:
            # Request tables for this schema
            cat = catalog or self._current_schema.get("database", "") if self._current_schema else ""
            self.tables_requested.emit(cat, name)
        elif item_type == "table" and name:
            # Request columns for this table
            schema_name = data.get("schema", "")
            cat = catalog or self._current_schema.get("database", "") if self._current_schema else ""
            self.columns_requested.emit(cat, schema_name, name)
        elif item_type == "database" and name:
            # For non-Databricks, request tables for this database
            self.tables_requested.emit(name, "")

    def add_schemas_to_catalog(self, catalog_name: str, schemas: list):
        """Add schemas to a catalog item (lazy loading callback)."""
        # Find the catalog item
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "catalog" and data.get("name") == catalog_name:
                self._remove_placeholder_children(item)
                for schema_name in sorted(schemas):
                    schema_item = QTreeWidgetItem(item, [schema_name])
                    schema_item.setData(0, Qt.ItemDataRole.UserRole, {
                        "type": "schema", "name": schema_name, "catalog": catalog_name
                    })
                    if HAS_QTAWESOME:
                        schema_item.setIcon(0, qta.icon("mdi.folder", color="#dcdc8b"))
                    # Add placeholder for tables
                    self._add_placeholder_child(schema_item)
                return

    def add_tables_to_schema(self, catalog_name: str, schema_name: str, tables: list):
        """Add tables to a schema item (lazy loading callback)."""
        # Find the schema item
        for i in range(self.tree.topLevelItemCount()):
            cat_item = self.tree.topLevelItem(i)
            cat_data = cat_item.data(0, Qt.ItemDataRole.UserRole)
            if not cat_data:
                continue
            cat_type = cat_data.get("type", "")
            cat_name = cat_data.get("name", "")
            
            # For catalog items, search children
            if cat_type == "catalog" and cat_name == catalog_name:
                for j in range(cat_item.childCount()):
                    schema_item = cat_item.child(j)
                    schema_data = schema_item.data(0, Qt.ItemDataRole.UserRole)
                    if schema_data and schema_data.get("type") == "schema" and schema_data.get("name") == schema_name:
                        self._remove_placeholder_children(schema_item)
                        self._add_table_items(schema_item, tables, catalog_name, schema_name)
                        return
            # For database items (non-Databricks)
            elif cat_type == "database" and cat_name == catalog_name:
                self._remove_placeholder_children(cat_item)
                self._add_table_items(cat_item, tables, "", "")
                return

    def _add_table_items(
        self, parent_item: QTreeWidgetItem, tables: list,
        catalog: str = "", schema: str = "", with_column_placeholder: bool = True
    ):
        """Add table items to a parent node.
        
        Args:
            parent_item: Parent tree item
            tables: List of table dictionaries or strings
            catalog: Databricks catalog name
            schema: Schema name
            with_column_placeholder: If True, add placeholder for lazy column loading
        """
        for table in sorted(tables, key=lambda t: t.get("name", "") if isinstance(t, dict) else t):
            if isinstance(table, dict):
                table_name = table.get("name", "")
                table_type = table.get("type", "TABLE")
                table_schema = table.get("schema", schema)
            else:
                table_name = str(table)
                table_type = "TABLE"
                table_schema = schema

            is_view = "VIEW" in table_type.upper()
            label = f"{table_name} {S.object_explorer.view_suffix}" if is_view else table_name

            table_item = QTreeWidgetItem(parent_item, [label])
            table_item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "table",
                "name": table_name,
                "schema": table_schema,
                "catalog": catalog,
                "table_type": table_type,
            })

            if HAS_QTAWESOME:
                if is_view:
                    table_item.setIcon(0, qta.icon("mdi.table-eye", color="#4ec9b0"))
                else:
                    table_item.setIcon(0, qta.icon("mdi.table", color="#4ec9b0"))

            # Add placeholder for lazy column loading
            if with_column_placeholder:
                self._add_placeholder_child(table_item)

    def add_columns_to_table(self, catalog_name: str, schema_name: str, table_name: str, columns: list):
        """Add columns to a table item (lazy loading callback)."""
        # Find the table item by traversing the tree
        def find_table(parent):
            for i in range(parent.childCount()):
                child = parent.child(i)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                if not data:
                    continue
                if data.get("type") == "table" and data.get("name") == table_name:
                    # Check schema match
                    if schema_name and data.get("schema", "") != schema_name:
                        continue
                    return child
                # Recurse into schema/catalog nodes
                result = find_table(child)
                if result:
                    return result
            return None

        for i in range(self.tree.topLevelItemCount()):
            table_item = find_table(self.tree.topLevelItem(i))
            if table_item:
                self._remove_placeholder_children(table_item)
                for col in columns:
                    self._add_column_item(
                        table_item,
                        col,
                        table_name=table_name,
                        table_key=f"{schema_name}.{table_name}" if schema_name else table_name,
                        table_schema=schema_name,
                        catalog=catalog_name,
                    )
                return

    def _on_double_click(self, item: QTreeWidgetItem, column: int):
        """Double-click only toggles expand/collapse. Insert is via >> button."""
        if item is None:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        # Toggle expand/collapse on double-click for items with children
        if item.childCount() > 0:
            item.setExpanded(not item.isExpanded())

    def _on_insert_clicked(self, item: QTreeWidgetItem):
        """Handle click on the >> insert button - sends path to editor."""
        if item is None:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        item_type = data.get("type", "")
        name = data.get("name", "")
        if not name:
            return

        if item_type == "table":
            catalog = data.get("catalog", "")
            schema = data.get("schema", "")
            if catalog and schema:
                self.insert_text_requested.emit(f"{catalog}.{schema}.{name}")
            elif schema:
                self.insert_text_requested.emit(f"{schema}.{name}")
            else:
                self.insert_text_requested.emit(name)
        elif item_type == "column":
            self.insert_text_requested.emit(name)
        elif item_type == "schema":
            catalog = data.get("catalog", "")
            if catalog:
                self.insert_text_requested.emit(f"{catalog}.{name}")
            else:
                self.insert_text_requested.emit(name)
        elif item_type == "catalog" or item_type == "database":
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

    def _get_column_names_for_table(self, table_item: QTreeWidgetItem) -> list:
        """Get column names from a table tree item's children."""
        names = []
        for i in range(table_item.childCount()):
            child = table_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "column":
                names.append(data.get("name", ""))
        return [n for n in names if n]

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
            catalog_name = data.get("catalog", "")
            qualified = self._get_item_qualified_name(data)
            quoted = self._quote_identifier(qualified)
            is_view = "VIEW" in str(data.get("table_type", "")).upper()
            
            # Build query based on database type
            if self._db_type in ("mysql", "mariadb", "postgres", "postgresql", "sqlite", "databricks"):
                select_query = f"SELECT * FROM {quoted} LIMIT 1000"
            else:
                # SQL Server / default
                select_query = f"SELECT TOP 1000 * FROM {quoted}"
            
            act_select = menu.addAction(S.object_explorer.ctx_select_top)
            act_select.triggered.connect(
                lambda _, q=select_query: self.query_requested.emit(q)
            )

            menu.addSeparator()

            # Insert name in editor (full qualified for Databricks)
            insert_name = qualified if catalog_name else name
            act_insert = menu.addAction(S.object_explorer.ctx_insert_name)
            act_insert.triggered.connect(lambda _, n=insert_name: self.insert_text_requested.emit(n))

            # Copy name (simple table name)
            act_copy = menu.addAction(S.object_explorer.ctx_copy_name)
            act_copy.triggered.connect(lambda _, n=name: QApplication.clipboard().setText(n))

            # Copy qualified name
            act_copy_qual = menu.addAction(S.object_explorer.ctx_copy_qualified)
            act_copy_qual.triggered.connect(
                lambda _, q=qualified: QApplication.clipboard().setText(q)
            )

            menu.addSeparator()

            if not is_view:
                commands_menu = menu.addMenu(S.object_explorer.ctx_commands_menu)

                act_create = commands_menu.addAction(S.object_explorer.ctx_command_create_table)
                act_create.triggered.connect(
                    lambda _, script=self._build_create_table_script(item): self.insert_text_requested.emit(script)
                )

                act_drop_create = commands_menu.addAction(S.object_explorer.ctx_command_drop_create)
                act_drop_create.triggered.connect(
                    lambda _, script=self._build_drop_and_create_script(item): self.insert_text_requested.emit(script)
                )

                menu.addSeparator()

            # COUNT(*)
            count_query = f"SELECT COUNT(*) FROM {quoted}"
            act_count = menu.addAction(S.object_explorer.ctx_count_rows)
            act_count.triggered.connect(
                lambda _, q=count_query: self.query_requested.emit(q)
            )

            # SELECT with all columns (from table's children)
            col_names = self._get_column_names_for_table(item)
            if col_names:
                cols_quoted = ", ".join(self._quote_identifier(c) for c in col_names)
                if self._db_type in ("mysql", "mariadb", "postgres", "postgresql", "sqlite", "databricks"):
                    select_all_cols = f"SELECT {cols_quoted}\nFROM {quoted}\nLIMIT 1000"
                else:
                    select_all_cols = f"SELECT TOP 1000 {cols_quoted}\nFROM {quoted}"
                act_all_cols = menu.addAction(S.object_explorer.ctx_select_all_columns)
                act_all_cols.triggered.connect(
                    lambda _, q=select_all_cols: self.query_requested.emit(q)
                )

        elif item_type == "column":
            table_name = data.get("table", "")
            col_type = data.get("display_type") or data.get("data_type", "")

            # Insert name in editor
            act_insert = menu.addAction(S.object_explorer.ctx_insert_name)
            act_insert.triggered.connect(lambda _, n=name: self.insert_text_requested.emit(n))

            # Copy name
            act_copy = menu.addAction(S.object_explorer.ctx_copy_name)
            act_copy.triggered.connect(lambda _, n=name: QApplication.clipboard().setText(n))

            # Copy as table.column
            if table_name:
                act_copy_full = menu.addAction(S.object_explorer.ctx_copy_as_qualified.format(table=table_name, name=name))
                act_copy_full.triggered.connect(
                    lambda _, t=table_name, n=name: QApplication.clipboard().setText(f"{t}.{n}")
                )

            menu.addSeparator()

            # Type info (disabled)
            act_type_info = menu.addAction(S.object_explorer.ctx_type_info.format(type=col_type))
            act_type_info.setEnabled(False)

            menu.addSeparator()

            # WHERE clause
            quoted_col = self._quote_identifier(name)
            where_text = f"WHERE {quoted_col} = "
            act_where = menu.addAction(S.object_explorer.ctx_where_clause)
            act_where.triggered.connect(lambda _, t=where_text: self.insert_text_requested.emit(t))

            # GROUP BY clause
            group_text = f"GROUP BY {quoted_col}"
            act_group = menu.addAction(S.object_explorer.ctx_group_by)
            act_group.triggered.connect(lambda _, t=group_text: self.insert_text_requested.emit(t))

            # ORDER BY clause
            order_text = f"ORDER BY {quoted_col}"
            act_order = menu.addAction(S.object_explorer.ctx_order_by)
            act_order.triggered.connect(lambda _, t=order_text: self.insert_text_requested.emit(t))

        elif item_type == "database":
            # Switch to this database
            act_switch = menu.addAction(S.object_explorer.ctx_use_database.format(name=name))
            act_switch.triggered.connect(lambda _, n=name: self.database_switch_requested.emit(n))

            menu.addSeparator()

            # Copy database name
            act_copy = menu.addAction(S.object_explorer.ctx_copy_db_name)
            act_copy.triggered.connect(lambda _, n=name: QApplication.clipboard().setText(n))

        elif item_type == "catalog":
            # Switch to this Databricks catalog
            act_switch = menu.addAction(S.object_explorer.ctx_use_catalog.format(name=name))
            act_switch.triggered.connect(
                lambda _, n=name: self.database_switch_requested.emit(f"CATALOG:{n}")
            )

            menu.addSeparator()

            # Copy name
            act_copy = menu.addAction(S.object_explorer.ctx_copy_db_name)
            act_copy.triggered.connect(lambda _, n=name: QApplication.clipboard().setText(n))

        elif item_type == "schema" and self._db_type == "databricks":
            # Switch to this Databricks schema
            act_switch = menu.addAction(S.object_explorer.ctx_use_schema.format(name=name))
            act_switch.triggered.connect(
                lambda _, n=name: self.database_switch_requested.emit(f"SCHEMA:{n}")
            )

            menu.addSeparator()

            # Copy name
            act_copy = menu.addAction(S.object_explorer.ctx_copy_db_name)
            act_copy.triggered.connect(lambda _, n=name: QApplication.clipboard().setText(n))

        else:
            return

        menu.exec(self.tree.viewport().mapToGlobal(pos))
