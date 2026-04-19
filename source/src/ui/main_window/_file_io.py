"""
FileIOMixin - File open/save/export, context detection, modification tracking.
"""

from __future__ import annotations

import os
import re
import hashlib
import logging
import traceback
from datetime import datetime

import pandas as pd
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from src.ui.main_window._workers import _read_file_with_encoding_fallback
from src.language import S

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

logger = logging.getLogger(__name__)


class FileIOMixin:
    """Handles file I/O: open, save, export, recent files, context detection."""

    def _new_file(self):
        """Clears current tab editor"""
        editor = self._get_current_editor()
        if editor:
            editor.clear()

    def _open_file(self):
        """Opens workspace or code file"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            S.dialogs.open_file_title,
            "",
            S.dialogs.open_file_filter,
        )
        if filename:
            # All files (including .dpw) open as single tab
            self._open_code_file(filename)

    def _update_recent_menu(self):
        """Refresh the Open Recent submenu with current entries."""
        self._recent_menu.clear()
        recent = self.recent_files_manager.get_recent()

        if not recent:
            empty_action = QAction(S.menu.open_recent_empty, self)
            empty_action.setEnabled(False)
            self._recent_menu.addAction(empty_action)
            return

        for entry in recent:
            path = entry.get("path", "")
            label = entry.get("name", path)
            action = QAction(label, self)
            action.setToolTip(path)
            action.triggered.connect(
                lambda _checked, p=path: self._open_recent_file(p)
            )
            self._recent_menu.addAction(action)

        self._recent_menu.addSeparator()
        clear_action = QAction(S.menu.open_recent_clear, self)
        if HAS_QTAWESOME:
            clear_action.setIcon(qta.icon("mdi.delete-sweep", color="#b0b0b0"))
        clear_action.triggered.connect(self._clear_recent_files)
        self._recent_menu.addAction(clear_action)

    def _open_recent_file(self, filepath: str):
        """Open a file from the recent files list."""
        import os
        if not os.path.exists(filepath):
            QMessageBox.warning(
                self,
                S.dialogs.error,
                S.dialogs.error_opening_file.format(error=f"File not found: {filepath}"),
            )
            return
        self._open_code_file(filepath)

    def _clear_recent_files(self):
        """Clear the recent files history."""
        self.recent_files_manager.clear()
        self._update_recent_menu()

    def _open_code_file(self, filename: str):
        """Opens code file in new tab with complete panels"""
        try:
            # Capture connection from current tab BEFORE creating new one
            previous_connection = None
            previous_color = None
            current_widget = self._get_current_session_widget()
            if current_widget and hasattr(current_widget, "session"):
                previous_connection = current_widget.session.connection_name
                if previous_connection:
                    config = self.connection_manager.get_connection_config(previous_connection)
                    if config:
                        previous_color = config.get("color", "#007ACC") or "#007ACC"

            # 1. Read file content (or cells if notebook)
            is_notebook = filename.endswith(".ipynb")
            cells = None
            content = ""

            if is_notebook:
                # Import service to parse notebook
                from src.services.file_import_service import FileImportService

                try:
                    cells = FileImportService.parse_ipynb_file(filename)
                    # Keep original content as JSON
                    content = _read_file_with_encoding_fallback(filename)
                except ValueError as e:
                    from PyQt6.QtWidgets import QMessageBox

                    QMessageBox.critical(self, S.dialogs.error, S.dialogs.error_opening_notebook.format(error=e))
                    return
            else:
                content = _read_file_with_encoding_fallback(filename)

            # 2. Detect language and configure context
            if filename.endswith(".py"):
                language = "python"
                self._original_file_type = "python"
            elif filename.endswith(".ipynb"):
                language = "python"
                self._original_file_type = "notebook"
            elif filename.endswith(".dpw"):
                language = "sql"
                self._original_file_type = "workspace"
            else:
                language = "sql"
                self._original_file_type = "sql"

            # 3. Se estava no estado vazio, remover placeholder e mostrar paineis
            self._hide_empty_state()

            # 4. Criar nova sessao
            import os

            tab_title = os.path.basename(filename)
            session = self.session_manager.create_session(title=tab_title)

            # 5. Criar widget da sessao usando _create_session_widget (centralizado)
            widget = self._create_session_widget(session)

            # Definir file_path e tipo ANTES de qualquer setCurrentIndex
            # para que _on_session_tab_changed restaure corretamente
            widget.file_path = filename
            widget._original_file_type = self._original_file_type

            # Armazenar caminho do arquivo original (apos widget estar configurado)
            self._original_file_path = filename

            # 6. Configurar conteudo
            is_dpw = filename.endswith(".dpw")

            if is_dpw:
                # .dpw file: multi-block JSON format
                import json
                try:
                    dpw_data = json.loads(content)
                    blocks_data = dpw_data.get("blocks", [])
                    if blocks_data:
                        widget.editor.from_list(blocks_data)
                except json.JSONDecodeError:
                    # Fallback: treat as single SQL block
                    blocks = widget.editor.get_blocks()
                    if blocks:
                        blocks[0].set_language("sql")
                        blocks[0].set_code(content)
            elif is_notebook and cells:
                # Notebook: criar um bloco por celula
                blocks = widget.editor.get_blocks()
                for i, cell in enumerate(cells):
                    if i == 0 and blocks:
                        # Usar primeiro bloco existente
                        blocks[0].set_language(cell["language"])
                        blocks[0].set_code(cell["code"])
                    else:
                        # Criar novos blocos para celulas subsequentes
                        new_block = widget.editor.add_block(language=cell["language"])
                        if new_block:
                            new_block.set_code(cell["code"])
            else:
                # File tradicional: um bloco unico
                blocks = widget.editor.get_blocks()
                if blocks:
                    blocks[0].set_language(language)
                    blocks[0].set_code(content)

            # 7. Calcular hash apos carregar conteudo (content_changed ja esta conectado)
            widget._content_hash = self._compute_widget_content_hash(widget)
            widget._is_modified = False

            # Remover asterisco que pode ter sido adicionado durante set_code
            index = self.session_tabs.indexOf(widget)
            if index >= 0:
                tab_text = self.session_tabs.tabText(index)
                if tab_text.endswith(" *"):
                    self.session_tabs.setTabText(index, tab_text[:-2])

            # 8. Focar na aba criada
            index = self.session_tabs.indexOf(widget)
            if index >= 0:
                self.session_tabs.setCurrentIndex(index)

            # Ensure file context survives tab change events
            self._original_file_path = filename
            self._original_file_type = widget._original_file_type

            self.main_statusbar.show_save_feedback(S.status.file_opened.format(filename=filename))
            self.main_statusbar.set_file_info(filename)

            # Track recently opened file
            self.recent_files_manager.add(filename)
            self._update_recent_menu()

            # 9. Update window title with context
            self._update_window_title()

            # 10. Switch panels to new session
            self._switch_session_panels(session.session_id)

            # 11. Inherit connection from previous tab (deferred for UI responsiveness)
            if previous_connection:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(150, lambda: self._connect_session_background(
                    widget, session, previous_connection, previous_color
                ))

        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(self, S.dialogs.error, S.dialogs.error_opening_file.format(error=e))

    def _save_file(self):
        """Intelligent saving system"""
        self._save_intelligently()

    def _save_file_as(self):
        """Save As - detects context to offer appropriate filter"""
        context = self._detect_file_context()

        if context == "sql":
            filter_text = "SQL Files (*.sql);;DataPyn Workspace (*.dpw);;All Files (*.*)"
        elif context == "python":
            filter_text = "Python Files (*.py);;DataPyn Workspace (*.dpw);;All Files (*.*)"
        else:
            filter_text = "DataPyn Workspace (*.dpw);;SQL Files (*.sql);;Python Files (*.py);;All Files (*.*)"

        filename, selected_filter = QFileDialog.getSaveFileName(
            self, S.dialogs.save_as_title, "", filter_text
        )
        if filename:
            if filename.endswith(".dpw"):
                self._save_tab_as_dpw(filename)
            elif filename.endswith(".sql"):
                self._save_single_file(filename, "sql")
            elif filename.endswith(".py"):
                self._save_single_file(filename, "python")
            else:
                # Infer from context or add default extension
                if context == "sql":
                    filename += ".sql"
                    self._save_single_file(filename, "sql")
                elif context == "python":
                    filename += ".py"
                    self._save_single_file(filename, "python")
                else:
                    filename += ".dpw"
                    self._save_tab_as_dpw(filename)

            # Sync global from widget (widget was updated by _save_single_file/_save_tab_as_dpw)
            self._sync_file_context_from_widget()

            self._update_window_title()

    def _open_workspace(self, filename: str):
        """Opens a workspace from a specific file"""
        try:
            # Load workspace from file
            workspace = self.workspace_manager.load_workspace(filename)

            # Close all current sessions
            self._close_all_sessions()

            # Reload sessions from workspace
            self._restore_sessions()

            self.main_statusbar.show_save_feedback(S.status.workspace_opened.format(filename=filename))
            self.main_statusbar.set_file_info(filename)
            self._update_window_title()

        except Exception as e:
            import traceback

            traceback.print_exc()
            QMessageBox.critical(self, S.dialogs.error_opening_workspace_title, S.dialogs.error_opening_workspace_msg.format(error=str(e)))

    def _save_workspace_to_file(self, filename: str):
        """Saves workspace to a specific file"""
        # Synchronize current session
        widget = self._get_current_session_widget()
        if widget:
            widget.sync_to_session()

        # Salvar via SessionManager
        self.session_manager.save_sessions()

        # Salvar geometria da janela
        window_geometry = {
            "x": self.geometry().x(),
            "y": self.geometry().y(),
            "width": self.geometry().width(),
            "height": self.geometry().height(),
            "maximized": self.isMaximized(),
        }

        dock_visible = self.connections_dock.isVisible() if hasattr(self, "connections_dock") else True

        # Save in workspace manager with specific path
        self.workspace_manager.save_workspace(
            tabs=[],
            active_tab=0,
            active_connection=None,
            window_geometry=window_geometry,
            splitter_sizes=[],
            dock_visible=dock_visible,
            file_path=filename,  # Passa o caminho do arquivo
        )

        # Clear tab modification markers
        self._clear_modification_markers()

    def _clear_modification_markers(self):
        """Removes asterisks from tabs, resets flags and updates hashes"""
        for i in range(self.session_tabs.count()):
            widget = self.session_tabs.widget(i)
            if hasattr(widget, "_is_modified"):
                widget._is_modified = False
            if hasattr(widget, "editor"):
                widget._content_hash = self._compute_widget_content_hash(widget)

            # Remover asterisco do titulo da aba se existir
            current_text = self.session_tabs.tabText(i)
            if current_text.endswith(" *"):
                self.session_tabs.setTabText(i, current_text[:-2])

    def _update_status(self):
        """Updates status periodically (no I/O on main thread)."""
        # Check rapido sem I/O - apenas verifica estado do pool
        session = self.session_manager.focused_session
        if session and session.connector and not session.connector.is_connected():
            session.clear_connection()
            self._update_connection_status()

    # _change_theme removido - tema fixo em 'dark'

    def _compute_widget_content_hash(self, widget):
        """Calcula hash do conteudo atual do editor do widget"""
        if not hasattr(widget, "editor") or not widget.editor:
            return ""

        blocks = widget.editor.get_blocks()
        parts = []
        for block in blocks:
            parts.append(block.get_language())
            parts.append(block.get_code())

        content = "\n".join(parts)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _on_editor_modified(self, widget):
        """Callback quando o conteudo do editor e modificado - usa hash para comparacao"""
        current_hash = self._compute_widget_content_hash(widget)
        original_hash = getattr(widget, "_content_hash", "")

        is_modified = current_hash != original_hash
        was_modified = getattr(widget, "_is_modified", False)
        widget._is_modified = is_modified

        # Atualizar titulo da aba conforme estado de modificacao
        if is_modified != was_modified:
            for i in range(self.session_tabs.count()):
                if self.session_tabs.widget(i) == widget:
                    current_text = self.session_tabs.tabText(i)
                    if is_modified and not current_text.endswith(" *"):
                        self.session_tabs.setTabText(i, current_text + " *")
                    elif not is_modified and current_text.endswith(" *"):
                        self.session_tabs.setTabText(i, current_text[:-2])
                    break

            self._update_window_title()

    def _sync_file_context_from_widget(self):
        """Sync global _original_file_path/_original_file_type from the current widget.
        This ensures the global always matches the active tab."""
        current_widget = self._get_current_session_widget()
        if current_widget and hasattr(current_widget, "file_path") and current_widget.file_path:
            self._original_file_path = current_widget.file_path
            self._original_file_type = getattr(current_widget, "_original_file_type", None)
        else:
            self._original_file_path = None
            self._original_file_type = None

    def _detect_file_context(self) -> str:
        """
        Detects the current context based on the number of blocks and types

        Returns:
            'sql'       - um bloco SQL apenas
            'python'    - um bloco Python apenas
            'workspace' - multiple blocks or .dpw file origin
        """
        current_widget = self._get_current_session_widget()
        if not current_widget:
            # No current widget - use original type or fallback
            if self._original_file_type in ["sql", "python"]:
                return self._original_file_type
            return "workspace"

        blocks = current_widget.editor.get_blocks()

        # Se tem mais de 1 bloco = workspace (.dpw)
        if len(blocks) > 1:
            return "workspace"

        # Se originalmente era workspace (aberto de .dpw), manter como workspace
        widget_file_type = getattr(current_widget, "_original_file_type", None)
        if widget_file_type == "workspace":
            return "workspace"

        # Se tem 1 bloco apenas, usar linguagem do bloco
        if len(blocks) == 1:
            block_language = blocks[0].get_language()
            if block_language in ["sql", "python"]:
                return block_language

        # Fallback
        return "workspace"

    def _update_window_title(self):
        """Updates window title with context indicator and file path"""
        from src.core.workspace_service import get_workspace_service
        
        ws_service = get_workspace_service()
        
        # Workspace prefix (empty for Default workspace)
        workspace_prefix = ""
        if not ws_service.is_default_workspace:
            workspace_prefix = f"{ws_service.current_workspace_name} - "
        
        base_title = "DataPyn"

        # Detectar contexto atual
        context = self._detect_file_context()
        self._current_context = context

        # Adicionar indicador
        if context == "sql":
            indicator = "[SQL]"
        elif context == "python":
            indicator = "[Python]"
        else:
            indicator = "[Workspace]"

        # Adicionar caminho do arquivo se disponivel
        file_info = ""
        file_path_for_statusbar = ""
        if self._original_file_path:
            import os

            file_info = f" - {self._original_file_path}"
            file_path_for_statusbar = self._original_file_path
        elif self.workspace_manager.current_file_path:
            import os

            file_info = f" - {self.workspace_manager.current_file_path}"
            file_path_for_statusbar = str(self.workspace_manager.current_file_path)

        self.setWindowTitle(f"{workspace_prefix}{indicator} {base_title}{file_info}")

        # Atualizar informacao do arquivo na statusbar
        if hasattr(self, "main_statusbar"):
            self.main_statusbar.set_file_info(file_path_for_statusbar)

    def _save_intelligently(self):
        """Intelligent save system based on context.
        Reads file_path from the CURRENT WIDGET (per-tab), not from global."""
        context = self._detect_file_context()

        # Per-tab source of truth for file path
        current_widget = self._get_current_session_widget()
        widget_file_path = getattr(current_widget, "file_path", None) if current_widget else None

        if context in ["sql", "python"]:
            # Contexto de arquivo unico
            expected_ext = ".sql" if context == "sql" else ".py"

            # Check if original file matches the expected extension
            if widget_file_path:
                import os
                current_ext = os.path.splitext(widget_file_path)[1].lower()

                if current_ext == expected_ext:
                    # File type matches block type - save directly
                    self._save_single_file(widget_file_path, context)
                else:
                    # Block type changed - ask for new file location
                    self._save_single_file_as(context)
            else:
                # Pedir caminho para arquivo unico
                self._save_single_file_as(context)
        else:
            # Contexto workspace (multiple blocks) - save as .dpw
            if widget_file_path and widget_file_path.endswith(".dpw"):
                self._save_tab_as_dpw(widget_file_path)
            else:
                # Pedir caminho para .dpw
                self._save_tab_as_dpw_dialog()

    def _save_tab_as_dpw(self, file_path: str):
        """Saves current tab's blocks to a .dpw file"""
        import json

        try:
            current_widget = self._get_current_session_widget()
            if not current_widget:
                return

            blocks_data = current_widget.editor.to_list()

            dpw_content = {
                "version": "1.0",
                "blocks": blocks_data
            }

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(dpw_content, f, indent=2, ensure_ascii=False)

            # Update file_path on widget and session
            current_widget.file_path = file_path
            current_widget._original_file_type = "workspace"
            current_widget.session.file_path = file_path
            current_widget.session.original_file_type = "workspace"

            # Update global file context
            self._original_file_path = file_path
            self._original_file_type = "workspace"

            # Update content hash
            current_widget._content_hash = self._compute_widget_content_hash(current_widget)
            current_widget._is_modified = False

            # Update tab name
            import os
            filename = os.path.basename(file_path)
            index = self.session_tabs.indexOf(current_widget)
            if index >= 0:
                self.session_tabs.setTabText(index, filename)
                current_widget.session.title = filename

            self.main_statusbar.show_save_feedback(S.status.file_saved.format(path=file_path))
            self.main_statusbar.set_file_info(file_path)
            self._update_window_title()

        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, S.dialogs.error, S.dialogs.error_saving_file.format(error=e))

    def _save_tab_as_dpw_dialog(self):
        """Asks for path to save tab as .dpw"""
        from PyQt6.QtWidgets import QFileDialog

        filename, _ = QFileDialog.getSaveFileName(
            self,
            S.dialogs.save_as_title,
            "",
            "DataPyn Workspace (*.dpw);;All Files (*.*)"
        )

        if filename:
            if not filename.endswith(".dpw"):
                filename += ".dpw"
            self._save_tab_as_dpw(filename)

            # Feedback visual para o usuario
            save_path = str(self.workspace_manager.current_file_path or self.workspace_manager.config_path)
            self.main_statusbar.show_save_feedback(S.status.workspace_saved.format(path=save_path))
            self.main_statusbar.set_file_info(save_path)

            self._clear_modification_markers()

    def _save_single_file(self, file_path: str, file_type: str):
        """Saves content to single file (sql/py)"""
        try:
            current_widget = self._get_current_session_widget()
            if not current_widget:
                return

            blocks = current_widget.editor.get_blocks()
            if not blocks:
                return

            # Pegar conteudo do primeiro bloco
            content = blocks[0].get_code()

            # Salvar arquivo
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            # Atualizar file_path no widget e sessao
            current_widget.file_path = file_path
            current_widget._original_file_type = file_type
            current_widget.session.file_path = file_path
            current_widget.session.original_file_type = file_type

            # Sync global from widget
            self._sync_file_context_from_widget()

            # Update content hash after saving (now it's the new "original")
            current_widget._content_hash = self._compute_widget_content_hash(current_widget)
            current_widget._is_modified = False

            # Atualizar nome da aba com o nome do arquivo (sem asterisco)
            import os

            filename = os.path.basename(file_path)
            index = self.session_tabs.indexOf(current_widget)
            if index >= 0:
                self.session_tabs.setTabText(index, filename)
                current_widget.session.title = filename

            self.main_statusbar.show_save_feedback(S.status.file_saved.format(path=file_path))
            self.main_statusbar.set_file_info(file_path)

            self._update_window_title()

        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(self, S.dialogs.error, S.dialogs.error_saving_file.format(error=e))

    def _save_single_file_as(self, file_type: str):
        """Asks for path to save single file"""
        from PyQt6.QtWidgets import QFileDialog

        if file_type == "sql":
            filter_text = "SQL Files (*.sql);;All Files (*.*)"
            default_ext = ".sql"
        else:
            filter_text = "Python Files (*.py);;All Files (*.*)"
            default_ext = ".py"

        filename, _ = QFileDialog.getSaveFileName(self, S.dialogs.save_python_file_title.format(type=file_type.upper()), "", filter_text)

        if filename:
            # Ensure correct extension
            if not filename.endswith(default_ext):
                filename += default_ext

            self._original_file_path = filename
            self._original_file_type = file_type
            self._save_single_file(filename, file_type)

    def _export_as_script(self):
        """Exports the current analysis as a complete Python script"""
        from PyQt6.QtWidgets import QFileDialog

        current_widget = self._get_current_session_widget()
        if not current_widget:
            QMessageBox.warning(self, S.dialogs.warning, S.dialogs.export_no_session)
            return

        blocks = current_widget.editor.get_blocks()
        if not blocks:
            QMessageBox.warning(self, S.dialogs.warning, S.dialogs.export_no_blocks)
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            S.dialogs.export_script_title,
            "",
            "Python Files (*.py);;All Files (*.*)"
        )

        if not filename:
            return

        if not filename.endswith('.py'):
            filename += '.py'

        try:
            script_content = self._generate_script_from_blocks(blocks, current_widget)

            with open(filename, 'w', encoding='utf-8') as f:
                f.write(script_content)

            self.action_label.setText(S.status.script_exported.format(filename=filename))
            QMessageBox.information(
                self,
                S.dialogs.export_complete_title,
                S.dialogs.export_complete_msg.format(filename=filename)
            )

        except Exception as e:
            QMessageBox.critical(self, S.dialogs.error, S.dialogs.error_exporting_script.format(error=e))

    def _generate_script_from_blocks(self, blocks, session_widget) -> str:
        """Generates complete Python code from the blocks"""
        lines = []

        lines.append('"""')
        lines.append('Python Script Exported from DataPyn')
        lines.append('')
        lines.append(f'Generated at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        if session_widget.session.connection_name:
            lines.append(f'Connection: {session_widget.session.connection_name}')
        lines.append('"""')
        lines.append('')

        imports_needed = set()
        has_sql = False

        for block in blocks:
            lang = block.get_language()
            if lang == 'sql':
                has_sql = True

        imports_needed.add('import pandas as pd')
        
        if has_sql:
            imports_needed.add('from sqlalchemy import create_engine')
            # Note: pyodbc is only added for SQL Server connections below

        lines.extend(sorted(imports_needed))
        lines.append('')
        
        if has_sql:
            lines.append('# Database Connection Configuration')
            lines.append('# IMPORTANT: Adjust the credentials below according to your configuration')

            if session_widget.session.connection_name:
                conn_name = session_widget.session.connection_name
                config = self.connection_manager.get_connection_config(conn_name)
                if config:
                    db_type = config.get('db_type', 'mysql')
                    host = config.get('host', 'localhost')
                    port = config.get('port', 3306)
                    database = config.get('database', 'database')
                    username = config.get('username', 'user')

                    lines.append(f"# Database type: {db_type}")
                    lines.append(f"DB_HOST = '{host}'")
                    lines.append(f"DB_PORT = {port}")
                    lines.append(f"DB_NAME = '{database}'")
                    lines.append(f"DB_USER = '{username}'")
                    lines.append("DB_PASSWORD = ''  # Enter password here")
                    lines.append('')

                    if db_type == 'mysql':
                        lines.append("# MySQL connection string")
                        lines.append("connection_string = f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'")
                    elif db_type == 'postgresql':
                        lines.append("# PostgreSQL connection string")
                        lines.append("connection_string = f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'")
                    elif db_type == 'sqlserver':
                        lines.append("# SQL Server connection string")
                        lines.append("# Requer: pip install pyodbc")
                        lines.append("connection_string = f'mssql+pyodbc://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?driver=ODBC+Driver+17+for+SQL+Server'")
                    elif db_type == 'databricks':
                        http_path = config.get('http_path', '')
                        lines.append("# Databricks SQL Warehouse connection string")
                        lines.append("# Requer: pip install databricks-sql-connector")
                        lines.append(f"DB_HTTP_PATH = '{http_path}'")
                        lines.append("connection_string = f'databricks://token:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}?http_path={DB_HTTP_PATH}&catalog={DB_NAME}&schema=default'")
                    else:
                        lines.append(f"# {db_type} connection string")
                        lines.append("connection_string = ''  # Configure the appropriate connection string")

                    lines.append('')
                    lines.append('# Create connection engine')
                    lines.append('engine = create_engine(connection_string)')
                    lines.append('')
            else:
                lines.append("connection_string = ''  # Configure your connection string")
                lines.append('engine = create_engine(connection_string)')
                lines.append('')

        lines.append('# ========================================')
        lines.append('# Code Blocks')
        lines.append('# ========================================')
        lines.append('')

        for i, block in enumerate(blocks, 1):
            lang = block.get_language()
            code = block.get_code().strip()
            block_name = block.get_block_name()

            if not code:
                continue

            lines.append(f'# --- Block {i}: {lang.upper()}' + (f' ({block_name})' if block_name else '') + ' ---')

            if lang == 'sql':
                lines.append('# SQL Query executed via pandas')
                var_name = block_name if block_name else f'df_block_{i}'
                lines.append(f'{var_name} = pd.read_sql("""')
                lines.append(code)
                lines.append('""", engine)')
                lines.append(f'print(f"Query executed: {{len({var_name})}} rows returned")')

            elif lang == 'python':
                lines.append('# Python code')
                lines.append(code)

            lines.append('')

        lines.append('# ========================================')
        lines.append('# End of Script')
        lines.append('# ========================================')

        return '\n'.join(lines)
