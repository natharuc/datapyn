"""
LayoutMixin - Dockable panels, dock layout persistence, panel visibility.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer, QSettings
from PyQt6.QtWidgets import QDockWidget, QMessageBox, QStackedWidget, QTabBar

from src.ui.components.results_viewer import ResultsViewer
from src.ui.components.output_panel import OutputPanel
from src.ui.components.variables_panel import VariablesPanel
from src.ui.components.summarize_panel import SummarizePanel
from src.ui.components.copilot_chat_panel import PyniaChatPanel
from src.ui.components.copilot_output_panel import CopilotOutputPanel
from src.design_system.tokens import get_colors
from src.language import S

logger = logging.getLogger(__name__)


class LayoutMixin:
    """Handles dockable panels, dock layout save/restore, panel visibility."""

    def _setup_dockable_panels(self):
        """Configures dockable panels (Results, Output, Variables) using QDockWidget.

        Cada dock contem um QStackedWidget. Cada sessao adiciona seus proprios
        paineis (ResultsViewer, OutputPanel, VariablesPanel) ao stack.
        Ao trocar de aba, troca-se a pagina visivel no stack.
        """
        from PyQt6.QtWidgets import QStackedWidget

        # Stacks - each session will have its page
        self._results_stack = QStackedWidget()
        self._output_stack = QStackedWidget()
        self._variables_stack = QStackedWidget()
        self._summarize_stack = QStackedWidget()

        # Mapeamento session_id -> indice no stack
        self._session_panel_indices: dict = {}

        # Dock styling compartilhado - moderno e limpo
        colors = get_colors()
        dock_style_bottom = f"""
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
        """

        # Results Panel
        self.results_dock = QDockWidget(S.dock.results, self)
        self.results_dock.setObjectName("ResultsDock")
        self.results_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.results_dock.setWidget(self._results_stack)
        self.results_dock.setStyleSheet(dock_style_bottom)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.results_dock)

        # Summarize Panel (grid selection stats)
        self.summarize_dock = QDockWidget(S.dock.summarize, self)
        self.summarize_dock.setObjectName("SummarizeDock")
        self.summarize_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.summarize_dock.setWidget(self._summarize_stack)
        self.summarize_dock.setStyleSheet(dock_style_bottom)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.summarize_dock)

        # Output Panel
        self.output_dock = QDockWidget(S.dock.output, self)
        self.output_dock.setObjectName("OutputDock")
        self.output_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.output_dock.setWidget(self._output_stack)
        self.output_dock.setStyleSheet(dock_style_bottom)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)

        # Variables Panel
        self.variables_dock = QDockWidget(S.dock.variables, self)
        self.variables_dock.setObjectName("VariablesDock")
        self.variables_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.variables_dock.setWidget(self._variables_stack)
        self.variables_dock.setStyleSheet(dock_style_bottom)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.variables_dock)

        # Configure minimum sizes to ensure visibility
        self.results_dock.setMinimumHeight(180)
        self.summarize_dock.setMinimumHeight(140)
        self.output_dock.setMinimumHeight(180)
        self.variables_dock.setMinimumWidth(200)
        self.variables_dock.setMinimumHeight(180)

        # Copilot Chat Panel
        agent_client = getattr(self, "_pynia_agent", None) or self._copilot_client
        self._copilot_chat_panel = PyniaChatPanel(
            copilot_client=agent_client,
            mcp_server=self._mcp_server,
            theme_manager=self.theme_manager,
        )
        self._copilot_chat_panel.set_agent_client(agent_client)
        self._copilot_chat_panel.set_mcp_server(self._mcp_server)
        self._copilot_chat_panel.insert_code_requested.connect(self._on_insert_code_from_chat)

        self.copilot_dock = QDockWidget(S.dock.copilot, self)
        self.copilot_dock.setObjectName("CopilotDock")
        self.copilot_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.copilot_dock.setWidget(self._copilot_chat_panel)
        self.copilot_dock.setStyleSheet(dock_style_bottom)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.copilot_dock)
        self.copilot_dock.setMinimumWidth(280)
        self.copilot_dock.setMinimumHeight(200)

        # Copilot Output Panel (shows tool calls, results, debug info)
        self._copilot_output_panel = CopilotOutputPanel(theme_manager=self.theme_manager)
        self.copilot_output_dock = QDockWidget("Pynia Output", self)
        self.copilot_output_dock.setObjectName("CopilotOutputDock")
        self.copilot_output_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.copilot_output_dock.setWidget(self._copilot_output_panel)
        self.copilot_output_dock.setStyleSheet(dock_style_bottom)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.copilot_output_dock)
        self.copilot_output_dock.setMinimumWidth(200)
        self.copilot_output_dock.setMinimumHeight(150)

        # Connect Copilot signals to output panel
        self._connect_copilot_to_output()

        # Setup LSP client for fast inline completions (if server is available)
        if hasattr(self, "_lsp_server_available") and self._lsp_server_available:
            self._setup_lsp_client()
        
        # Initialize centralized Copilot auth service
        self._setup_copilot_auth_service()

        # Tabifica Results, Summarize e Output por padrao (fica em abas)
        self.tabifyDockWidget(self.results_dock, self.summarize_dock)
        self.tabifyDockWidget(self.results_dock, self.output_dock)
        self.tabifyDockWidget(self.output_dock, self.copilot_output_dock)

        # Results fica como aba ativa
        self.results_dock.raise_()

        # Esconder Results, Summarize e Variables ate a primeira execucao
        self.results_dock.hide()
        self.summarize_dock.hide()
        self.variables_dock.hide()

        if getattr(self, "_empty_state_widget", None):
            self._show_empty_state()

    def _create_session_panels(self, session_id: str):
        """Creates panels (Results, Output, Variables, Summarize) for a session and adds to stacks."""
        results = ResultsViewer(theme_manager=self.theme_manager)
        session = self.session_manager.get_session(session_id) if hasattr(self, "session_manager") else None
        if session is not None and hasattr(results, "set_session"):
            results.set_session(session)
        output = OutputPanel(theme_manager=self.theme_manager)
        variables = VariablesPanel(theme_manager=self.theme_manager)
        summarize = SummarizePanel(theme_manager=self.theme_manager)

        # Connect signals do painel de variaveis
        variables.insert_variable_name.connect(self._on_insert_variable_in_editor)
        variables.delete_variable.connect(self._on_delete_variable)
        variables.show_in_results.connect(self._on_show_variable_in_results)

        results.grid_selection_changed.connect(
            lambda rv=results, panel=summarize: panel.update_from_results_viewer(rv)
        )

        r_idx = self._results_stack.addWidget(results)
        o_idx = self._output_stack.addWidget(output)
        v_idx = self._variables_stack.addWidget(variables)
        s_idx = self._summarize_stack.addWidget(summarize)

        self._session_panel_indices[session_id] = {
            "results_idx": r_idx,
            "output_idx": o_idx,
            "variables_idx": v_idx,
            "summarize_idx": s_idx,
            "results": results,
            "output": output,
            "variables": variables,
            "summarize": summarize,
        }
        return results, output, variables

    def _remove_session_panels(self, session_id: str):
        """Removes panels of a session from stacks."""
        info = self._session_panel_indices.pop(session_id, None)
        if not info:
            return
        self._results_stack.removeWidget(info["results"])
        self._output_stack.removeWidget(info["output"])
        self._variables_stack.removeWidget(info["variables"])
        if info.get("summarize"):
            self._summarize_stack.removeWidget(info["summarize"])
        info["results"].deleteLater()
        info["output"].deleteLater()
        info["variables"].deleteLater()
        if info.get("summarize"):
            info["summarize"].deleteLater()

        # Remove Object Explorer from session
        if hasattr(self, "_session_explorers"):
            self._remove_session_explorer(session_id)

    def _switch_session_panels(self, session_id: str):
        """Switches stacks to display panels of the active session.

        Usa setCurrentWidget() em vez de setCurrentIndex() para evitar
        bugs com indices invalidos apos remocao de widgets do stack.
        """
        info = self._session_panel_indices.get(session_id)
        if not info:
            return
        if info["results"]:
            self._results_stack.setCurrentWidget(info["results"])
        if info["output"]:
            self._output_stack.setCurrentWidget(info["output"])
        if info["variables"]:
            self._variables_stack.setCurrentWidget(info["variables"])
        if info.get("summarize"):
            self._summarize_stack.setCurrentWidget(info["summarize"])
            summarize = info["summarize"]
            results = info.get("results")
            if summarize and results:
                QTimer.singleShot(0, lambda panel=summarize, rv=results: panel.schedule_update_from_results_viewer(rv))

        # Trocar Object Explorer para a sessao ativa (deferido para nao bloquear a UI)
        if hasattr(self, "_session_explorers"):
            QTimer.singleShot(0, lambda sid=session_id: self._switch_session_explorer(sid))

    @property
    def global_results_viewer(self):
        """Returns the ResultsViewer of the active session."""
        sid = self._get_active_session_id()
        info = self._session_panel_indices.get(sid) if sid else None
        return info["results"] if info else None

    @property
    def global_output_panel(self):
        """Returns the OutputPanel of the active session."""
        sid = self._get_active_session_id()
        info = self._session_panel_indices.get(sid) if sid else None
        return info["output"] if info else None

    @property
    def global_variables_panel(self):
        """Returns the VariablesPanel of the active session."""
        sid = self._get_active_session_id()
        info = self._session_panel_indices.get(sid) if sid else None
        return info["variables"] if info else None

    @property
    def global_summarize_panel(self):
        """Returns the SummarizePanel of the active session."""
        sid = self._get_active_session_id()
        info = self._session_panel_indices.get(sid) if sid else None
        return info.get("summarize") if info else None

    def _get_active_session_id(self) -> str:
        """Returns the session_id of the active tab."""
        widget = self._get_current_session_widget()
        if widget and hasattr(widget, "session"):
            return widget.session.session_id
        return None

    def _on_namespace_updated(self, namespace: dict):
        """Callback when namespace is updated"""
        panel = self.global_variables_panel
        if panel:
            panel.refresh_variables(namespace)

            def show_output(self):
                """Compatibility: shows output panel"""
                self.main_window.show_panel("output")

    def show_panel(self, name: str):
        """Shows specific panel using QDockWidget.

        Para docks tabificados (results/output), raise_() sozinho nao
        funciona. Precisamos buscar o QTabBar do grupo e trocar a aba ativa.
        """
        dock_map = {
            "results": self.results_dock,
            "summarize": self.summarize_dock,
            "output": self.output_dock,
            "variables": self.variables_dock,
            "object_explorer": getattr(self, "object_explorer_dock", None),
            "copilot": getattr(self, "copilot_dock", None),
        }
        dock = dock_map.get(name)
        if dock is None:
            return

        dock.show()
        dock.raise_()

        # Se mostrando results pela primeira vez, mostrar variables e summarize tambem
        if name == "results":
            if not self.variables_dock.isVisible():
                self.variables_dock.show()
            if hasattr(self, "summarize_dock") and not self.summarize_dock.isVisible():
                self.summarize_dock.show()
            panel = self.global_summarize_panel
            viewer = self.global_results_viewer
            if panel and viewer:
                panel.update_from_results_viewer(viewer)

        # Para docks tabificados, raise_() nao troca a aba visivel.
        # Precisamos encontrar o QTabBar que controla o grupo e selecionar
        # a aba correspondente manualmente.
        if name in ("results", "output", "summarize"):
            self._activate_tabified_dock(dock)

    def _activate_tabified_dock(self, dock: QDockWidget):
        """Activates the correct tab in a group of tabified docks.

        When docks are tabified via tabifyDockWidget(), they share
        an internal QTabBar of QMainWindow. raise_() alone does not switch the tab.
        This method finds the correct QTabBar and selects the dock tab.
        """
        from PyQt6.QtWidgets import QTabBar

        target_title = dock.windowTitle()
        for tab_bar in self.findChildren(QTabBar):
            for i in range(tab_bar.count()):
                if tab_bar.tabText(i) == target_title:
                    tab_bar.setCurrentIndex(i)
                    return

    def hide_panel(self, name: str):
        """Hides specific panel using QDockWidget"""
        if name == "results":
            self.results_dock.hide()
            if hasattr(self, "summarize_dock"):
                self.summarize_dock.hide()
        elif name == "summarize" and hasattr(self, "summarize_dock"):
            self.summarize_dock.hide()
        elif name == "output":
            self.output_dock.hide()
        elif name == "variables":
            self.variables_dock.hide()
        elif name == "object_explorer" and hasattr(self, "object_explorer_dock"):
            self.object_explorer_dock.hide()
        elif name == "copilot" and hasattr(self, "copilot_dock"):
            self.copilot_dock.hide()

    def _refresh_connections_list(self):
        """Updates the saved connections list"""
        self.connection_panel.refresh_connections()

    def _on_connection_double_click(self, item: QListWidgetItem):
        """Connects on double click on connection"""
        conn_name = item.data(Qt.ItemDataRole.UserRole)
        if conn_name:
            self._quick_connect(conn_name)

    def _toggle_panel_visibility(self, panel_name: str, visible: bool):
        """Controls visibility of a panel"""
        if visible:
            self.show_panel(panel_name)
        else:
            self.hide_panel(panel_name)

    def _toggle_output_tab(self, visible: bool):
        """Controls Output panel visibility"""
        if visible:
            self.show_panel("output")
        else:
            self.hide_panel("output")

    def _restore_default_layout(self):
        """Restores the default panel layout"""
        self._setup_default_layout()
        self._sync_view_menu_checks()

    def _save_dock_layout(self):
        """Save current dock layout to QSettings."""
        try:
            # Ensure toolbar objectName is set (required for saveState)
            if hasattr(self, 'main_toolbar'):
                self.main_toolbar.setObjectName("MainToolbar")
            settings = QSettings("DataPyn", "MainWindow")
            settings.setValue("geometry", self.saveGeometry())
            settings.setValue("windowState", self.saveState(3))  # version=3
            settings.sync()
        except Exception:
            pass

    def _restore_dock_layout(self):
        """Restores dock widget layout from QSettings."""
        self._restoring_layout = True
        try:
            settings = QSettings("DataPyn", "MainWindow")
            geometry = settings.value("geometry")
            window_state = settings.value("windowState")

            restored = False

            if geometry and len(geometry) > 20:
                self.restoreGeometry(geometry)

            if window_state and len(window_state) > 50:
                # Window is NOT visible at this point (show() is called later
                # by the splash screen), so restoreState runs invisibly.
                if self.restoreState(window_state, 3):  # version=3
                    restored = True
                # Re-ensure toolbar settings (restoreState may override them)
                if hasattr(self, 'main_toolbar'):
                    self.main_toolbar.setObjectName("MainToolbar")
                    self.main_toolbar.setMovable(False)
                    self.main_toolbar.setVisible(True)

            if not restored:
                self._setup_default_layout()

            # Ensure all non-hidden docks are properly docked (not floating)
            for dock in [
                self.connections_dock,
                self.results_dock,
                self.summarize_dock,
                self.output_dock,
                self.variables_dock,
            ]:
                if dock.isFloating() and dock.isVisible():
                    dock.setFloating(False)

            if getattr(self, "_empty_state_widget", None):
                self._show_empty_state()

            # Sync view menu after a short delay (docks need to settle)
            QTimer.singleShot(300, self._finish_layout_restore)

        except Exception:
            self._setup_default_layout()
            if getattr(self, "_empty_state_widget", None):
                self._show_empty_state()
            self._restoring_layout = False

    def _finish_layout_restore(self):
        """Called after layout restore settles - sync menu and allow auto-save."""
        self._restoring_layout = False
        self._sync_view_menu_checks()

    def _setup_auto_save_layout(self):
        """Configure auto-save: save layout when dock visibility/position changes."""
        self._layout_save_timer = QTimer()
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.setInterval(1000)
        self._layout_save_timer.timeout.connect(self._save_dock_layout)

        # Connect dock visibility changes to schedule save
        all_docks = [
            self.connections_dock,
            self.results_dock,
            self.summarize_dock,
            self.output_dock,
            self.variables_dock,
        ]
        if hasattr(self, "object_explorer_dock"):
            all_docks.append(self.object_explorer_dock)
        if hasattr(self, "copilot_dock"):
            all_docks.append(self.copilot_dock)
        for dock in all_docks:
            dock.visibilityChanged.connect(self._on_dock_changed)
            dock.dockLocationChanged.connect(self._on_dock_changed)
            dock.topLevelChanged.connect(self._on_dock_changed)

    def _on_dock_changed(self, *args):
        """Schedule layout save after dock state changes."""
        if getattr(self, "_restoring_layout", False):
            return
        if hasattr(self, "_layout_save_timer"):
            self._layout_save_timer.start()

    def _clear_saved_layout(self):
        """Clears saved layout (for reset)."""
        try:
            settings = QSettings("DataPyn", "MainWindow")
            settings.remove("geometry")
            settings.remove("windowState")
            settings.sync()
        except Exception:
            pass

    def _setup_default_layout(self):
        """Configures the default dock layout."""
        try:
            all_docks = [
                self.connections_dock,
                self.results_dock,
                self.summarize_dock,
                self.output_dock,
                self.variables_dock,
            ]
            if hasattr(self, "object_explorer_dock"):
                all_docks.append(self.object_explorer_dock)
            if hasattr(self, "copilot_dock"):
                all_docks.append(self.copilot_dock)

            # Reset: make all non-floating
            for dock in all_docks:
                dock.setFloating(False)

            # Position docks in their default areas
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.connections_dock)
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.results_dock)
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.summarize_dock)
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.variables_dock)

            if hasattr(self, "object_explorer_dock"):
                self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.object_explorer_dock)
                self.object_explorer_dock.hide()

            if hasattr(self, "copilot_dock"):
                self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.copilot_dock)
                self.copilot_dock.hide()

            # Tabify Results, Summarize and Output (bottom tabs)
            self.tabifyDockWidget(self.results_dock, self.summarize_dock)
            self.tabifyDockWidget(self.results_dock, self.output_dock)
            self.results_dock.raise_()

            # Show main panels
            self.connections_dock.show()
            self.results_dock.show()
            self.output_dock.show()
            self.variables_dock.show()

            # Window size
            screen = QApplication.primaryScreen()
            if screen:
                available = screen.availableGeometry()
                w = min(1400, int(available.width() * 0.8))
                h = min(900, int(available.height() * 0.8))
                x = available.x() + (available.width() - w) // 2
                y = available.y() + (available.height() - h) // 2
                self.setGeometry(x, y, w, h)
            else:
                self.setGeometry(100, 100, 1400, 900)

        except Exception:
            # Fallback: just show docks
            try:
                self.connections_dock.show()
                self.results_dock.show()
                self.output_dock.show()
                self.variables_dock.show()
            except Exception:
                pass

    def _is_layout_valid(self):
        """Checks if the current layout is sane."""
        try:
            geom = self.geometry()
            if geom.width() < 400 or geom.height() < 300:
                return False
            return True
        except Exception:
            return False

    def _validate_restored_layout(self):
        """Validates layout after restore and fixes if necessary."""
        if not self._is_layout_valid():
            self._clear_saved_layout()
            self._setup_default_layout()

    def _reset_layout_completely(self):
        """Resets layout completely (clears settings and applies default)."""
        reply = QMessageBox.question(
            self,
            S.dialogs.confirm_reset_title,
            S.dialogs.layout_reset_confirm_msg if hasattr(S.dialogs, 'layout_reset_confirm_msg') else "This will completely reset the panel layout.\nAll layout settings will be lost.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._clear_saved_layout()
            self._setup_default_layout()
            self._sync_view_menu_checks()
            QMessageBox.information(self, S.dialogs.layout_reset_title, S.dialogs.layout_reset_msg)

    def _sync_view_menu_checks(self):
        """Sync View menu check states with actual dock visibility."""
        dock_action_map = [
            ("connections_dock", "connections_action"),
            ("results_dock", "results_action"),
            ("summarize_dock", "summarize_action"),
            ("output_dock", "output_action"),
            ("variables_dock", "variables_action"),
            ("object_explorer_dock", "object_explorer_action"),
            ("copilot_dock", "copilot_action"),
        ]
        for dock_attr, action_attr in dock_action_map:
            dock = getattr(self, dock_attr, None)
            action = getattr(self, action_attr, None)
            if dock and action:
                action.setChecked(dock.isVisible())
