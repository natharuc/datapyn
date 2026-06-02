"""
UISetupMixin - Menus, toolbar, shortcuts, statusbar, settings, about, auto-update.
"""

from __future__ import annotations

import os
import sys
import logging

from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, QSettings
from PyQt6.QtGui import QAction, QKeySequence, QFont, QIcon
from PyQt6.QtWidgets import (
    QMessageBox, QWidget, QVBoxLayout, QHBoxLayout, QApplication,
    QDockWidget, QStackedWidget, QLabel,
)

from src.ui.components.session_tabs import SessionTabs
from src.ui.components.connection_panel import ConnectionPanel
from src.ui.components.toolbar import MainToolbar
from src.ui.components.statusbar import MainStatusBar
from src.ui.components.object_explorer_panel import ObjectExplorerPanel
from src.ui.dialogs.settings_dialog import SettingsDialog
from src.ui.dialogs.package_manager_dialog import PackageManagerDialog
from src.ui.dialogs.update_dialog import UpdateDialog, UpdateDownloadDialog, UpdateCheckingDialog
from src.design_system.tokens import get_colors, DARK_COLORS, RADIUS
from src.design_system.stylesheet import (
    get_main_window_stylesheet,
    get_dock_widget_stylesheet,
    get_bottom_dock_stylesheet,
    get_execution_label_stylesheet,
    get_connection_status_stylesheet,
    get_empty_state_stylesheet,
    get_start_button_stylesheet,
)
from src.language import S

DEFAULT_VERSION = "1.1.6"

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

logger = logging.getLogger(__name__)


class UISetupMixin:
    """Handles UI setup: menus, toolbar, statusbar, shortcuts, settings, theme, updates."""

    def _setup_icons(self):
        """Configures QtAwesome icons with uniform color"""
        if not HAS_QTAWESOME:
            return {}

        c = "#b0b0b0"  # Cor padrao uniforme para todos os icones
        return {
            "database": qta.icon("mdi.database", color=c),
            "play": qta.icon("mdi.play", color=c),
            "python": qta.icon("mdi.language-python", color=c),
            "table": qta.icon("mdi.table", color=c),
            "save": qta.icon("mdi.content-save", color=c),
            "folder-open": qta.icon("mdi.folder-open", color=c),
            "trash": qta.icon("mdi.delete-outline", color=c),
            "cog": qta.icon("mdi.cog-outline", color=c),
            "plug": qta.icon("mdi.connection", color=c),
            "code": qta.icon("mdi.code-tags", color=c),
            "chart-bar": qta.icon("mdi.chart-bar", color=c),
            "memory": qta.icon("mdi.memory", color=c),
            "terminal": qta.icon("mdi.console", color=c),
        }

    def _setup_ui(self):
        """Configures the main interface"""
        self.setWindowTitle(S.main_window.window_title)
        self.setGeometry(100, 100, 1400, 900)

        # Apply centralized stylesheet from design system
        self.setStyleSheet(get_main_window_stylesheet())

        # Container for session tabs (will be the central area)
        session_container = QWidget()
        session_layout = QVBoxLayout(session_container)
        session_layout.setContentsMargins(5, 5, 5, 5)

        # TabWidget for sessions (each tab is a complete SessionWidget)
        self.session_tabs = SessionTabs()
        self.session_tabs.session_closed.connect(self._close_session_tab)
        self.session_tabs.session_renamed.connect(self._on_session_renamed)
        self.session_tabs.session_changed.connect(self._on_session_tab_changed)
        self.session_tabs.duplicate_session.connect(self._duplicate_session)

        session_layout.addWidget(self.session_tabs)

        # Configure central area with sessions in the docking system
        self.set_central_content(session_container)

        # Restore sessions
        self._restore_sessions()

        # Dock for connections (left side)
        self._create_connections_dock()

        # Configure dockable panels (Results, Output, Variables)
        self._setup_dockable_panels()

        # Object Explorer (lateral direita, abaixo de Variables)
        self._create_object_explorer_dock()

        # Layout restore deferred to after toolbar creation (see __init__)

    def _create_connections_dock(self):
        """Creates the connections side panel using ConnectionPanel"""
        # Usar o componente ConnectionPanel
        from src.design_system.tokens import get_colors
        colors = get_colors()
        self.connection_panel = ConnectionPanel(
            connection_manager=self.connection_manager, theme_manager=self.theme_manager
        )

        # Connect signals
        self.connection_panel.connection_requested.connect(self._quick_connect)
        self.connection_panel.new_tab_connection_requested.connect(self._connect_new_tab)
        self.connection_panel.new_connection_clicked.connect(self._new_connection)
        self.connection_panel.manage_connections_clicked.connect(self._manage_connections)
        self.connection_panel.edit_connection_clicked.connect(self._edit_connection)
        self.connection_panel.disconnect_clicked.connect(self._disconnect)

        # Create dock widget
        self.connections_dock = QDockWidget(S.dock.connections, self)
        self.connections_dock.setObjectName("ConnectionsDock")  # Para saveState/restoreState
        self.connections_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.connections_dock.setWidget(self.connection_panel)
        self.connections_dock.setStyleSheet(f"""
            QDockWidget {{
                background-color: {colors.bg_secondary};
                color: {colors.text_primary};
                border: none;
            }}
            QDockWidget::title {{
                background-color: {colors.bg_tertiary};
                padding: 8px 10px;
                padding-right: 60px;
                font-weight: 500;
                font-size: 12px;
                border: none;
            }}
            QDockWidget::close-button, QDockWidget::float-button {{
                border: none;
                background: transparent;
                padding: 4px;
                icon-size: 14px;
            }}
            QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
                background: {colors.bg_elevated};
                border-radius: 4px;
            }}
        """)

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.connections_dock)

        # Configure size policy to occupy full side
        self.connections_dock.setMinimumWidth(200)
        self.connections_dock.setMaximumWidth(400)

        # Configure features to allow full repositioning
        features = (
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.connections_dock.setFeatures(features)

        # Create compatibility properties
        self._setup_connection_panel_compat()

    def _setup_connection_panel_compat(self):
        """Creates compatibility properties for legacy code"""
        # Maps old attributes to new component
        self.connections_list = self.connection_panel.connections_list.list_widget
        self.active_conn_name_label = self.connection_panel.active_widget.name_label
        self.active_conn_info_label = self.connection_panel.active_widget.info_label
        self.btn_disconnect = self.connection_panel.active_widget.btn_disconnect

    def _create_object_explorer_dock(self):
        """Creates Object Explorer panel (right side, below Variables).

        Usa QStackedWidget para que cada sessao tenha seu proprio Object Explorer.
        """
        from PyQt6.QtWidgets import QStackedWidget
        from src.design_system.tokens import get_colors
        colors = get_colors()

        self._object_explorer_stack = QStackedWidget()
        # Mapeamento session_id -> ObjectExplorerPanel
        self._session_explorers: dict = {}

        # Criar dock widget
        self.object_explorer_dock = QDockWidget(S.dock.object_explorer, self)
        self.object_explorer_dock.setObjectName("ObjectExplorerDock")
        self.object_explorer_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.object_explorer_dock.setWidget(self._object_explorer_stack)
        self.object_explorer_dock.setStyleSheet(f"""
            QDockWidget {{
                background-color: {colors.bg_secondary};
                color: {colors.text_primary};
                border: none;
            }}
            QDockWidget::title {{
                background-color: {colors.bg_tertiary};
                padding: 8px 10px;
                padding-right: 60px;
                font-weight: 500;
                font-size: 12px;
                border: none;
            }}
            QDockWidget::close-button, QDockWidget::float-button {{
                border: none;
                background: transparent;
                padding: 4px;
                icon-size: 14px;
            }}
            QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
                background: {colors.bg_elevated};
                border-radius: 4px;
            }}
        """)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.object_explorer_dock)

        self.object_explorer_dock.setMinimumWidth(200)
        self.object_explorer_dock.setMinimumHeight(150)

        features = (
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.object_explorer_dock.setFeatures(features)

        # Hide until there is an active connection
        self.object_explorer_dock.hide()

    def _get_session_explorer(self, session_id: str) -> ObjectExplorerPanel:
        """Returns the ObjectExplorerPanel for the session, creating if necessary."""
        if session_id in self._session_explorers:
            return self._session_explorers[session_id]

        panel = ObjectExplorerPanel(theme_manager=self.theme_manager)
        panel.insert_text_requested.connect(self._on_object_explorer_insert_text)
        panel.query_requested.connect(self._on_object_explorer_query)
        panel.database_switch_requested.connect(self._on_object_explorer_database_switch)
        panel.btn_refresh.clicked.connect(self._on_object_explorer_refresh)
        # Lazy loading signals
        panel.schemas_requested.connect(self._on_oe_schemas_requested)
        panel.tables_requested.connect(self._on_oe_tables_requested)
        panel.columns_requested.connect(self._on_oe_columns_requested)
        panel.schema_changed.connect(
            lambda schema, sid=session_id: self._on_object_explorer_schema_changed(sid, schema)
        )

        self._object_explorer_stack.addWidget(panel)
        self._session_explorers[session_id] = panel
        return panel

    def _remove_session_explorer(self, session_id: str):
        """Removes Object Explorer from a session."""
        panel = self._session_explorers.pop(session_id, None)
        if panel:
            self._object_explorer_stack.removeWidget(panel)
            panel.deleteLater()

    def _switch_session_explorer(self, session_id: str):
        """Switches to the Object Explorer of the active session."""
        panel = self._session_explorers.get(session_id)
        if panel:
            self._object_explorer_stack.setCurrentWidget(panel)

    @property
    def _active_object_explorer(self):
        """Returns the ObjectExplorerPanel of the active session."""
        sid = self._get_active_session_id()
        return self._session_explorers.get(sid) if sid else None

    def _create_menus(self):
        """Creates the menus"""
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu(S.menu.file)

        new_action = QAction(S.menu.new_tab, self)
        # Shortcut managed by ShortcutManager (Ctrl+T)
        new_action.triggered.connect(self._new_session)
        file_menu.addAction(new_action)

        open_action = QAction(S.menu.open, self)
        # Shortcut managed by ShortcutManager (Ctrl+O)
        open_action.triggered.connect(self._open_file)
        file_menu.addAction(open_action)

        save_action = QAction(S.menu.save, self)
        # Shortcut managed by ShortcutManager (Ctrl+S)
        save_action.triggered.connect(self._save_file)
        file_menu.addAction(save_action)

        save_as_action = QAction(S.menu.save_as, self)
        # Shortcut managed by ShortcutManager (Ctrl+Shift+S)
        save_as_action.triggered.connect(self._save_file_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        # Open Recent submenu
        self._recent_menu = file_menu.addMenu(S.menu.open_recent)
        if HAS_QTAWESOME:
            self._recent_menu.setIcon(qta.icon("mdi.history", color="#b0b0b0"))
        self._update_recent_menu()

        file_menu.addSeparator()

        export_script_action = QAction(S.menu.export_script, self)
        if HAS_QTAWESOME:
            export_script_action.setIcon(qta.icon("mdi.file-export", color="#b0b0b0"))
        # Shortcut managed by ShortcutManager (Ctrl+Shift+E)
        export_script_action.triggered.connect(self._export_as_script)
        file_menu.addAction(export_script_action)

        file_menu.addSeparator()

        exit_action = QAction(S.menu.exit, self)
        _exit_key = self.shortcut_manager.get_shortcut("exit_app")
        if _exit_key:
            exit_action.setShortcut(QKeySequence(_exit_key))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Connection Menu
        conn_menu = menubar.addMenu(S.menu.connection)

        manage_conn_action = QAction(S.menu.manage_connections, self)
        if HAS_QTAWESOME:
            manage_conn_action.setIcon(self.icons["database"])
        # Shortcut managed by ShortcutManager (Ctrl+Shift+M)
        manage_conn_action.triggered.connect(self._manage_connections)
        conn_menu.addAction(manage_conn_action)

        conn_menu.addSeparator()

        new_conn_action = QAction(S.menu.new_connection, self)
        if HAS_QTAWESOME:
            new_conn_action.setIcon(self.icons["plug"])
        # Shortcut managed by ShortcutManager (Ctrl+Shift+D)
        new_conn_action.triggered.connect(self._new_connection)
        conn_menu.addAction(new_conn_action)

        disconnect_action = QAction(S.menu.disconnect, self)
        if HAS_QTAWESOME:
            disconnect_action.setIcon(self.icons["trash"])
        disconnect_action.triggered.connect(self._disconnect)
        conn_menu.addAction(disconnect_action)

        # Run Menu
        run_menu = menubar.addMenu(S.menu.run)

        run_current_action = QAction(S.menu.run_current_block, self)
        if HAS_QTAWESOME:
            run_current_action.setIcon(self.icons["play"])
        # Shortcut managed by ShortcutManager (F5)
        run_current_action.triggered.connect(self._execute_current_block)
        run_menu.addAction(run_current_action)

        run_all_action = QAction(S.menu.run_all_blocks, self)
        if HAS_QTAWESOME:
            run_all_action.setIcon(qta.icon("mdi.fast-forward", color="#b0b0b0"))
        # Shortcut managed by ShortcutManager (Ctrl+F5)
        run_all_action.triggered.connect(self._execute_all_blocks)
        run_menu.addAction(run_all_action)

        run_menu.addSeparator()

        clear_results_action = QAction(S.menu.clear_results, self)
        if HAS_QTAWESOME:
            clear_results_action.setIcon(self.icons["trash"])
        # Shortcut managed by ShortcutManager (Ctrl+Shift+C)
        clear_results_action.triggered.connect(self._clear_results)
        run_menu.addAction(clear_results_action)

        # View Menu
        view_menu = menubar.addMenu(S.menu.view)

        # Panels Submenu
        panels_menu = view_menu.addMenu(S.menu.panels)

        # Results panel toggle
        results_action = QAction(S.menu.panel_results, self)
        results_action.setCheckable(True)
        results_action.setChecked(True)
        results_action.triggered.connect(lambda checked: self._toggle_panel_visibility("results", checked))
        panels_menu.addAction(results_action)
        self.results_action = results_action

        # Summarize panel toggle
        summarize_action = QAction(S.menu.panel_summarize, self)
        summarize_action.setCheckable(True)
        summarize_action.setChecked(True)
        summarize_action.triggered.connect(lambda checked: self._toggle_panel_visibility("summarize", checked))
        panels_menu.addAction(summarize_action)
        self.summarize_action = summarize_action

        # Output panel toggle
        output_action = QAction(S.menu.panel_output, self)
        output_action.setCheckable(True)
        output_action.setChecked(True)
        output_action.triggered.connect(lambda checked: self._toggle_output_tab(checked))
        panels_menu.addAction(output_action)
        self.output_action = output_action

        # Variables panel toggle
        variables_action = QAction(S.menu.panel_variables, self)
        variables_action.setCheckable(True)
        variables_action.setChecked(True)
        variables_action.triggered.connect(lambda checked: self._toggle_panel_visibility("variables", checked))
        panels_menu.addAction(variables_action)
        self.variables_action = variables_action

        # Connections panel toggle
        connections_action = QAction(S.menu.panel_connections, self)
        connections_action.setCheckable(True)
        connections_action.setChecked(True)
        connections_action.triggered.connect(lambda checked: self.connections_dock.setVisible(checked))
        panels_menu.addAction(connections_action)
        self.connections_action = connections_action

        # Object Explorer toggle
        object_explorer_action = QAction(S.menu.panel_object_explorer, self)
        object_explorer_action.setCheckable(True)
        object_explorer_action.setChecked(False)
        object_explorer_action.triggered.connect(
            lambda checked: self._toggle_panel_visibility("object_explorer", checked)
        )
        panels_menu.addAction(object_explorer_action)
        self.object_explorer_action = object_explorer_action

        # Copilot Chat toggle
        copilot_action = QAction(S.copilot.dock_title, self)
        copilot_action.setCheckable(True)
        copilot_action.setChecked(False)
        copilot_action.triggered.connect(
            lambda checked: self._toggle_panel_visibility("copilot", checked)
        )
        panels_menu.addAction(copilot_action)
        self.copilot_action = copilot_action

        view_menu.addSeparator()

        # Restore default view
        restore_action = QAction(S.menu.restore_default_view, self)
        _restore_key = self.shortcut_manager.get_shortcut("restore_view")
        if _restore_key:
            restore_action.setShortcut(QKeySequence(_restore_key))
        restore_action.triggered.connect(self._restore_default_layout)
        view_menu.addAction(restore_action)

        # Reset layout completely (clears saved settings)
        reset_layout_action = QAction(S.menu.complete_layout_reset, self)
        _reset_key = self.shortcut_manager.get_shortcut("reset_layout")
        if _reset_key:
            reset_layout_action.setShortcut(QKeySequence(_reset_key))
        reset_layout_action.triggered.connect(self._reset_layout_completely)
        view_menu.addAction(reset_layout_action)

        # Tools Menu
        tools_menu = menubar.addMenu(S.menu.tools)

        packages_action = QAction(S.menu.package_manager, self)
        if HAS_QTAWESOME:
            packages_action.setIcon(qta.icon("mdi.package-variant", color="#b0b0b0"))
        packages_action.triggered.connect(self._show_package_manager)
        tools_menu.addAction(packages_action)

        tools_menu.addSeparator()

        settings_action = QAction(S.menu.shortcut_settings, self)
        if HAS_QTAWESOME:
            settings_action.setIcon(self.icons["cog"])
        # Shortcut managed by ShortcutManager (Ctrl+,)
        settings_action.triggered.connect(self._show_settings)
        tools_menu.addAction(settings_action)

        tools_menu.addSeparator()

        # Auto-update toggle
        auto_update_action = QAction(S.menu.auto_update, self)
        auto_update_action.setCheckable(True)
        auto_update_action.setChecked(self.auto_update_service.is_auto_update_enabled())
        auto_update_action.triggered.connect(self._toggle_auto_update)
        tools_menu.addAction(auto_update_action)
        self._auto_update_action = auto_update_action  # Save reference to update state

        tools_menu.addSeparator()

        # Pynia chat
        pynia_menu = tools_menu.addMenu(
            S.menu.pynia_submenu if hasattr(S.menu, "pynia_submenu") else "Pynia"
        )
        if HAS_QTAWESOME:
            pynia_menu.setIcon(qta.icon("mdi.robot", color="#b0b0b0"))
        open_pynia_action = QAction(
            S.menu.pynia_open_chat if hasattr(S.menu, "pynia_open_chat") else "Open Pynia Chat",
            self,
        )
        open_pynia_action.triggered.connect(self._toggle_copilot_dock)
        pynia_menu.addAction(open_pynia_action)

        # Inline autocomplete (GitHub Copilot language server)
        copilot_menu = tools_menu.addMenu(S.menu.copilot_submenu)
        if HAS_QTAWESOME:
            copilot_menu.setIcon(qta.icon("mdi.robot", color="#b0b0b0"))

        # Download Language Server
        download_lsp_action = QAction(S.menu.copilot_download_lsp, self)
        if HAS_QTAWESOME:
            download_lsp_action.setIcon(qta.icon("mdi.download", color="#b0b0b0"))
        download_lsp_action.triggered.connect(self._show_copilot_download_dialog)
        copilot_menu.addAction(download_lsp_action)

        # Check Status
        check_status_action = QAction(S.menu.copilot_check_status, self)
        if HAS_QTAWESOME:
            check_status_action.setIcon(qta.icon("mdi.information-outline", color="#b0b0b0"))
        check_status_action.triggered.connect(self._show_copilot_status)
        copilot_menu.addAction(check_status_action)

        # Help Menu
        help_menu = menubar.addMenu(S.menu.help)

        check_updates_action = QAction(S.menu.check_updates, self)
        if HAS_QTAWESOME:
            check_updates_action.setIcon(qta.icon("mdi.update", color="#b0b0b0"))
        check_updates_action.triggered.connect(self._check_for_updates)
        help_menu.addAction(check_updates_action)

        help_menu.addSeparator()

        about_action = QAction(S.menu.about, self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_toolbar(self):
        """Creates the toolbar using MainToolbar"""
        self.main_toolbar = MainToolbar(theme_manager=self.theme_manager)
        self.main_toolbar.setObjectName("MainToolbar")  # Para saveState/restoreState
        self.addToolBar(self.main_toolbar)

        # Connect signals
        self.main_toolbar.new_connection_clicked.connect(self._new_connection)
        self.main_toolbar.new_tab_clicked.connect(self._new_session)
        self.main_toolbar.run_clicked.connect(self._execute_from_toolbar)
        self.main_toolbar.run_timer_clicked.connect(self._toggle_run_timer)
        self.main_toolbar.pynia_clicked.connect(self._toggle_copilot_dock)
        self.main_toolbar.copilot_clicked.connect(self._toggle_copilot_dock)
        self.main_toolbar.workspace_switch_requested.connect(self._on_workspace_switch)
        self.main_toolbar.workspace_settings_requested.connect(self._show_workspace_settings)

    def _toggle_copilot_dock(self):
        """Toggle Copilot dock visibility and focus."""
        if hasattr(self, "copilot_dock"):
            if self.copilot_dock.isVisible():
                self.copilot_dock.hide()
            else:
                self.copilot_dock.show()
                self.copilot_dock.raise_()
                # Focus input field
                if hasattr(self, "_copilot_chat_panel"):
                    if hasattr(self._copilot_chat_panel, "focus_input"):
                        self._copilot_chat_panel.focus_input()
                    else:
                        input_field = getattr(self._copilot_chat_panel, "_input", None)
                        if input_field and hasattr(input_field, "setFocus"):
                            input_field.setFocus()

    def _on_workspace_switch(self, path: str):
        """Handle workspace switch request from toolbar."""
        from pathlib import Path
        from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
        from src.core.workspace_service import get_workspace_service
        
        ws_service = get_workspace_service()
        target_path = Path(path)
        
        # Check if already in this workspace
        if target_path == ws_service.current_workspace:
            return
        
        # Save current state before switching
        try:
            self._save_sessions()
        except Exception as e:
            logging.warning(f"Failed to save session before workspace switch: {e}")
        
        # Create custom dialog with two options
        dialog = QDialog(self)
        dialog.setWindowTitle(
            S.settings.workspace_switch_title if hasattr(S.settings, 'workspace_switch_title') 
            else "Switch Workspace"
        )
        dialog.setModal(True)
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Message
        message = QLabel(
            S.settings.workspace_switch_message if hasattr(S.settings, 'workspace_switch_message')
            else "Choose how you want to open the selected workspace:"
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        # Restart current app button
        restart_btn = QPushButton(
            S.settings.workspace_switch_restart if hasattr(S.settings, 'workspace_switch_restart')
            else "Restart Current App"
        )
        restart_btn.setToolTip(
            S.settings.workspace_switch_restart_tooltip if hasattr(S.settings, 'workspace_switch_restart_tooltip')
            else "Closes current DataPyn and reopens with the new workspace"
        )
        restart_btn.setMinimumHeight(35)
        
        # Open new instance button
        new_instance_btn = QPushButton(
            S.settings.workspace_switch_new_instance if hasattr(S.settings, 'workspace_switch_new_instance')
            else "Open New Instance"
        )
        new_instance_btn.setToolTip(
            S.settings.workspace_switch_new_instance_tooltip if hasattr(S.settings, 'workspace_switch_new_instance_tooltip')
            else "Keeps current open and opens another DataPyn with the new workspace"
        )
        new_instance_btn.setMinimumHeight(35)
        
        # Cancel button
        cancel_btn = QPushButton(S.general.cancel if hasattr(S.general, 'cancel') else "Cancel")
        cancel_btn.setMinimumHeight(35)
        
        btn_layout.addWidget(restart_btn)
        btn_layout.addWidget(new_instance_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        # Store result
        result = {"action": None}
        
        def on_restart():
            result["action"] = "restart"
            dialog.accept()
        
        def on_new_instance():
            result["action"] = "new_instance"
            dialog.accept()
        
        restart_btn.clicked.connect(on_restart)
        new_instance_btn.clicked.connect(on_new_instance)
        cancel_btn.clicked.connect(dialog.reject)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if result["action"] == "restart":
                # Set the new workspace and restart
                ws_service.switch_workspace(target_path)
                self._restart_application()
            elif result["action"] == "new_instance":
                # Open new instance with the new workspace
                self._open_new_instance(target_path)
                # Revert combo to current workspace (keep current app unchanged)
                if hasattr(self, 'main_toolbar'):
                    self.main_toolbar._refresh_workspace_combo()
        else:
            # User cancelled - revert combo box
            if hasattr(self, 'main_toolbar'):
                self.main_toolbar._refresh_workspace_combo()

    def _open_new_instance(self, workspace_path):
        """Open a new DataPyn instance with the specified workspace."""
        import sys
        import os
        from PyQt6.QtCore import QProcess
        
        python = sys.executable
        script = os.path.abspath(sys.argv[0])
        working_dir = os.path.dirname(script) or os.getcwd()
        
        # Pass workspace path as argument
        args = [script, "--workspace", str(workspace_path)]
        
        success = QProcess.startDetached(python, args, working_dir)
        logging.info(f"New instance started: workspace={workspace_path}, success={success}")

    def _restart_application(self):
        """Restart the application."""
        import sys
        import os
        
        # Save state
        self._save_sessions()
        self._save_dock_layout()
        
        # Get current script/executable with absolute paths
        python = sys.executable
        script = os.path.abspath(sys.argv[0])
        
        # Build arguments list (use script path directly)
        args = [script] + sys.argv[1:]
        
        # Schedule restart with working directory
        from PyQt6.QtCore import QProcess
        working_dir = os.path.dirname(script) or os.getcwd()
        
        # Start the new process
        success = QProcess.startDetached(python, args, working_dir)
        logging.info(f"Restart initiated: python={python}, args={args}, cwd={working_dir}, success={success}")
        
        # Close this instance
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _create_statusbar(self):
        """Creates the status bar using MainStatusBar"""
        self.main_statusbar = MainStatusBar(theme_manager=self.theme_manager)
        self.setStatusBar(self.main_statusbar)

        # Create compatibility properties
        self.statusbar = self.main_statusbar
        self.connection_status_bar = self.main_statusbar.connection_label
        self.action_label = self.main_statusbar.action_label
        self.execution_label = self.main_statusbar.timer_label

        # Timers - usar os do componente
        self._is_executing = False
        self._execution_timer = QElapsedTimer()
        self._execution_update_timer = QTimer()
        self._execution_update_timer.timeout.connect(self._update_execution_time)

    def _setup_shortcuts(self):
        """Configures global application shortcuts"""
        from PyQt6.QtGui import QShortcut, QKeySequence
        from PyQt6.QtCore import Qt

        # Guardar shortcuts como atributos para evitar garbage collection
        self._shortcuts = []

        # Map actions to callbacks
        shortcuts_map = {
            # Execution
            "execute_sql": self._execute_current_block,
            "execute_all": self._execute_all_blocks,
            "execute_block_advance": self._execute_and_advance,
            "clear_results": self._clear_results,
            # File
            "open_file": self._open_file,
            "save_file": self._save_file,
            "save_as": self._save_file_as,
            "export_script": self._export_as_script,
            # Sessions
            "new_tab": self._new_session,
            "new_session": self._new_session,
            "close_tab": self._close_current_session,
            "add_block": self._add_block_to_current_session,
            # Edicao
            "find": self._find_in_editor,
            "replace": self._replace_in_editor,
            "format_code": self._format_current_block,
            "show_entity_info": self._show_selected_entity_info,
            # Autocompletar
            "force_autocomplete": self._force_autocomplete,
            # Conexoes
            "manage_connections": self._manage_connections,
            "new_connection": self._new_connection,
            # Schema
            "reload_schema": self._reload_schema,
            # Tools
            "settings": self._show_settings,
        }

        # Create shortcuts from ShortcutManager
        app_keys = set()
        for action, callback in shortcuts_map.items():
            key_sequence = self.shortcut_manager.get_shortcut(action)
            if key_sequence:
                shortcut = QShortcut(QKeySequence(key_sequence), self)
                shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
                shortcut.activated.connect(callback)
                self._shortcuts.append(shortcut)
                app_keys.add(key_sequence)

    def _reload_shortcuts(self):
        """Re-registers all shortcuts (called when user changes settings)"""
        from PyQt6.QtGui import QShortcut, QKeySequence
        from PyQt6.QtCore import Qt

        # Limpar atalhos antigos
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._shortcuts.clear()

        # Map actions to callbacks
        shortcuts_map = {
            # Execution
            "execute_sql": self._execute_current_block,
            "execute_all": self._execute_all_blocks,
            "execute_block_advance": self._execute_and_advance,
            "clear_results": self._clear_results,
            # File
            "open_file": self._open_file,
            "save_file": self._save_file,
            "save_as": self._save_file_as,
            "export_script": self._export_as_script,
            # Sessions
            "new_tab": self._new_session,
            "new_session": self._new_session,
            "close_tab": self._close_current_session,
            "add_block": self._add_block_to_current_session,
            # Edicao
            "find": self._find_in_editor,
            "replace": self._replace_in_editor,
            "format_code": self._format_current_block,
            "show_entity_info": self._show_selected_entity_info,
            # Autocompletar
            "force_autocomplete": self._force_autocomplete,
            # Conexoes
            "manage_connections": self._manage_connections,
            "new_connection": self._new_connection,
            # Schema
            "reload_schema": self._reload_schema,
            # Tools
            "settings": self._show_settings,
        }

        # Create new shortcuts
        app_keys = set()
        for action, callback in shortcuts_map.items():
            key_sequence = self.shortcut_manager.get_shortcut(action)
            if key_sequence:
                shortcut = QShortcut(QKeySequence(key_sequence), self)
                shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
                shortcut.activated.connect(callback)
                self._shortcuts.append(shortcut)
                app_keys.add(key_sequence)

    # NOTA: _new_session() definido mais abaixo (linha ~2745) com guard contra duplicacao

    def _apply_app_theme(self):
        """Applies theme to the application (not to editors)"""
        colors = self.theme_manager.get_app_colors()

        # Apply general style to window
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {colors["background"]};
            }}
            QMenuBar {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border-bottom: 1px solid {colors["border"]};
            }}
            QMenuBar::item {{
                background-color: transparent;
                padding: 6px 12px;
            }}
            QMenuBar::item:selected {{
                background-color: {colors["accent"]};
            }}
            QMenu {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: 1px solid {colors["border"]};
                padding: 4px 0px;
            }}
            QMenu::item {{
                padding: 8px 40px 8px 36px;
                min-width: 180px;
            }}
            QMenu::icon {{
                padding-left: 12px;
            }}
            QMenu::item:selected {{
                background-color: {colors["accent"]};
            }}
            QToolBar {{
                background-color: {colors["background"]};
                border-bottom: 1px solid {colors["border"]};
                spacing: 5px;
                padding: 3px;
            }}
            QPushButton {{
                background-color: {colors["border"]};
                color: {colors["foreground"]};
                border: none;
                padding: 6px 12px;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {colors["accent"]};
            }}
            QTabWidget::pane {{
                border: 1px solid {colors["border"]};
                background-color: {colors["background"]};
            }}
            QTabBar::tab {{
                background-color: {colors["border"]};
                color: {colors["foreground"]};
                padding: 8px 15px;
                padding-right: 25px;
                margin-right: 2px;
                min-width: 80px;
            }}
            QTabBar::tab:selected {{
                background-color: {colors["background"]};
                color: {colors["accent"]};
            }}
            QTabBar::tab:hover {{
                background-color: {colors["accent"]};
            }}
            QTabBar::tab:last {{
                min-width: 30px;
                padding: 8px 10px;
                padding-right: 10px;
            }}
            QTabBar::close-button {{
                subcontrol-position: right;
                width: 12px;
                height: 12px;
            }}
            QTabBar::close-button:hover {{
                background-color: #ff6b6b;
                border-radius: 4px;
            }}
            QTextEdit {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: 1px solid {colors["border"]};
            }}
            QLabel {{
                color: {colors["foreground"]};
            }}
            QGroupBox {{
                color: {colors["accent"]};
                font-weight: bold;
                border: 1px solid {colors["border"]};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
            QListWidget {{
                background-color: {colors["background"]};
                border: 1px solid {colors["border"]};
                color: {colors["foreground"]};
            }}
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {colors["border"]};
            }}
            QListWidget::item:hover {{
                background-color: {colors["border"]};
            }}
            QListWidget::item:selected {{
                background-color: {colors["accent"]};
                color: white;
            }}
            QDockWidget {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
            }}
            QDockWidget::title {{
                background-color: {colors["border"]};
                padding: 8px;
                font-weight: bold;
            }}
            QPushButton#btnPrimary {{
                background-color: {colors["accent"]};
                color: white;
            }}
            QPushButton#btnPrimary:hover {{
                background-color: {colors["accent"]};
            }}
            QPushButton#btnDisconnect:hover {{
                background-color: #f48771;
                color: white;
            }}
            QPushButton:disabled {{
                background-color: {colors["border"]};
                color: #666666;
            }}
        """)

        # Atualizar paineis de todas as sessoes
        if hasattr(self, "_session_panel_indices"):
            for info in self._session_panel_indices.values():
                info["results"].set_theme_manager(self.theme_manager)
                if hasattr(info["output"], "set_theme_manager"):
                    info["output"].set_theme_manager(self.theme_manager)
                if hasattr(info["variables"], "set_theme_manager"):
                    info["variables"].set_theme_manager(self.theme_manager)

        # Atualizar SessionWidgets
        if hasattr(self, "_session_widgets"):
            for widget in self._session_widgets.values():
                if hasattr(widget, "apply_theme"):
                    widget.apply_theme()

    def _show_about(self):
        """Shows the about dialog"""
        QMessageBox.about(
            self,
            S.about.title,
            f"""<h2>{S.about.ide_name}</h2>
            <p><b>{S.about.version.format(version=self._current_version)}</b></p>
            <p>{S.about.description}</p>
            
            <p><b>{S.about.technologies}</b></p>
            <ul>
                <li>Python 3.12+</li>
                <li>PyQt6 - Interface</li>
                <li>Monaco Editor - Code editor (VS Code)</li>
                <li>Pandas & Polars - Data analysis</li>
                <li>SQLAlchemy - Database ORM</li>
                <li>Matplotlib - Visualization</li>
                <li>GitHub Copilot SDK - AI completions</li>
            </ul>
            
            <p><b>{S.about.databases}</b></p>
            <ul>
                <li>Microsoft SQL Server</li>
                <li>MySQL / MariaDB</li>
                <li>PostgreSQL</li>
                <li>SQLite</li>
                <li>Databricks</li>
            </ul>
            
            <p><b>{S.about.license}</b></p>
            <p><b>Website:</b> <a href="http://datapyn.com">datapyn.com</a></p>
            <p><b>Repository:</b> <a href="https://github.com/natharuc/datapyn">github.com/natharuc/datapyn</a></p>
            
            <p style="margin-top: 15px; color: #888;">{S.about.built_with}</p>
            """,
        )

    def _show_package_manager(self):
        """Shows package manager dialog"""
        dialog = PackageManagerDialog(theme_manager=self.theme_manager, parent=self)
        dialog.exec()

    def show_settings_dialog(self, initial_tab: str = None):
        """Shows the settings dialog, optionally selecting a tab."""
        dialog = SettingsDialog(
            self.shortcut_manager,
            theme_manager=self.theme_manager,
            initial_tab=initial_tab,
        )
        dialog.shortcuts_changed.connect(self._reload_shortcuts)
        dialog.copilot_chat_login_requested.connect(self._on_settings_chat_login)
        dialog.copilot_chat_logout_requested.connect(self._on_settings_chat_logout)
        dialog.copilot_lsp_login_requested.connect(self._on_settings_lsp_login)
        dialog.copilot_lsp_logout_requested.connect(self._on_settings_lsp_logout)
        dialog.exec()

    def _show_settings(self):
        """Shows the settings dialog"""
        self.show_settings_dialog()

    def _show_workspace_settings(self):
        """Shows the settings dialog on the Workspace tab."""
        dialog = SettingsDialog(self.shortcut_manager, theme_manager=self.theme_manager, initial_tab="workspace")
        dialog.shortcuts_changed.connect(self._reload_shortcuts)
        
        # Connect Copilot auth signals
        dialog.copilot_chat_login_requested.connect(self._on_settings_chat_login)
        dialog.copilot_chat_logout_requested.connect(self._on_settings_chat_logout)
        dialog.copilot_lsp_login_requested.connect(self._on_settings_lsp_login)
        dialog.copilot_lsp_logout_requested.connect(self._on_settings_lsp_logout)
        
        dialog.exec()

    def _toggle_auto_update(self, checked: bool):
        """Enables or disables auto-update"""
        self.auto_update_service.set_auto_update_enabled(checked)
        if checked:
            self.statusbar.showMessage(S.status.auto_update_enabled, 3000)
        else:
            self.statusbar.showMessage(S.status.auto_update_disabled, 3000)

    def _get_current_version(self) -> str:
        """Gets current version from pyproject.toml"""
        try:
            import tomllib
            import os

            # Path to pyproject.toml
            if getattr(sys, "frozen", False):
                # If running as executable, use embedded version
                base_path = sys._MEIPASS
            else:
                # In development, go to project root
                # __file__ is source/src/ui/main_window/_ui_setup.py
                # Need 5 levels up: _ui_setup.py -> main_window/ -> ui/ -> src/ -> source/ -> project root
                base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

            pyproject_path = os.path.join(base_path, "pyproject.toml")

            if os.path.exists(pyproject_path):
                with open(pyproject_path, "rb") as f:
                    data = tomllib.load(f)
                    return data.get("project", {}).get("version", DEFAULT_VERSION)
            else:
                return DEFAULT_VERSION
        except Exception as e:
            logger.warning(f"Error reading version from pyproject.toml: {e}")
            return DEFAULT_VERSION

    def _check_for_updates(self):
        """Manually checks for updates"""
        if not self.auto_update_service.is_auto_update_enabled():
            reply = QMessageBox.question(
                self,
                S.dialogs.auto_update_disabled_title,
                S.dialogs.auto_update_disabled_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.auto_update_service.set_auto_update_enabled(True)
            else:
                return

        # Show loading dialog
        self._update_checking_dialog = UpdateCheckingDialog(self)
        
        # Start verificacao
        self.auto_update_service.check_for_updates(
            on_available=lambda v, url, notes: self._on_update_check_complete(v, url, notes),
            on_no_update=lambda: self._on_update_check_complete(None, None, None),
            on_error=lambda msg: self._on_update_check_error(msg),
        )
        
        # Show dialog (modal)
        self._update_checking_dialog.exec()

    def _on_update_check_complete(self, version: str, download_url: str, release_notes: str):
        """Callback when update check is complete"""
        # Close loading dialog
        if hasattr(self, "_update_checking_dialog") and self._update_checking_dialog:
            self._update_checking_dialog.close()
        
        if version:
            # Update available
            self._on_update_available(version, download_url, release_notes)
        else:
            # No update available
            self._on_no_update_available()

    def _check_for_updates_silent(self):
        """Silently checks for updates on startup"""
        if getattr(self, "_is_closing", False):
            return

        if not self.auto_update_service.is_auto_update_enabled():
            return

        self.auto_update_service.check_for_updates(
            on_available=self._on_update_available,
            on_no_update=lambda: None,  # Silencioso se nao houver atualizacao
            on_error=lambda msg: logger.info(f"Update check failed: {msg}"),
        )

    def _on_update_available(self, version: str, download_url: str, release_notes: str):
        """Callback when an update is available"""
        self.statusbar.showMessage(S.status.new_version_available.format(version=version), 5000)

        dialog = UpdateDialog(self._current_version, version, release_notes, self)
        if dialog.exec() == UpdateDialog.DialogCode.Accepted and dialog.should_download:
            self._download_update(version, download_url)

    def _on_no_update_available(self):
        """Callback when no updates are available"""
        self.statusbar.showMessage(S.status.latest_version, 5000)
        QMessageBox.information(
            self,
            S.dialogs.no_updates_title,
            S.dialogs.no_updates_msg.format(version=self._current_version),
        )

    def _on_update_check_error(self, error_message: str):
        """Callback when an error occurs while checking for updates"""
        # Close loading dialog
        if hasattr(self, "_update_checking_dialog") and self._update_checking_dialog:
            self._update_checking_dialog.close()
        
        self.statusbar.showMessage(S.status.error_checking_updates, 5000)
        QMessageBox.warning(
            self, S.dialogs.verification_error_title, S.dialogs.verification_error_msg.format(error=error_message)
        )

    def _download_update(self, version: str, download_url: str):
        """Starts the update download"""
        download_dialog = UpdateDownloadDialog(version, self)

        self.auto_update_service.download_update(
            download_url,
            version,
            on_progress=download_dialog.update_progress,
            on_complete=lambda path: self._on_download_complete(path, download_dialog),
            on_error=download_dialog.download_failed,
        )

        download_dialog.exec()

    def _on_download_complete(self, installer_path: str, download_dialog):
        """Callback when the download is complete"""
        download_dialog.download_complete(installer_path)

        reply = QMessageBox.question(
            self,
            S.dialogs.download_complete_title,
            S.dialogs.download_complete_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.auto_update_service.install_update(installer_path):
                QApplication.quit()
            else:
                QMessageBox.critical(
                    self, S.dialogs.installation_error_title, S.dialogs.installation_error_msg
                )
