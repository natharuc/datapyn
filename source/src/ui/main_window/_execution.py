"""
ExecutionMixin - SQL/Python execution, timer, notifications, logging.
"""

from __future__ import annotations

import logging
import re
import traceback
from datetime import datetime

import pandas as pd
from PyQt6.QtCore import Qt, QThread, QTimer, QElapsedTimer
from PyQt6.QtWidgets import QMessageBox

from src.database.database_connector import get_connector_database_context
from src.ui.main_window._workers import SqlWorker, PythonWorker
from src.ui.components.toast_notification import ToastManager
from src.language import S
from src.services.notification_delivery_service import get_notification_delivery_service

logger = logging.getLogger(__name__)


class ExecutionMixin:
    """Handles code execution (SQL/Python), timer, tab indicators, logging."""

    def _execute_from_toolbar(self):
        """Executes code from the current editor via toolbar button"""
        editor = self._get_current_editor()
        if not editor:
            return

        # Toolbar run button executes only the focused block
        if hasattr(editor, "execute_focused_block"):
            editor.execute_focused_block()

    def _toggle_run_timer(self):
        """Toggle periodic execution on the CURRENT TAB."""
        widget = self._get_current_session_widget()
        if not widget:
            return

        if widget.is_periodic_active:
            widget.stop_periodic()
            self.main_toolbar.set_timer_running(False)
            self.main_statusbar.action_label.setText("")
            return

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QDialogButtonBox
        dialog = QDialog(self)
        dialog.setWindowTitle(S.toolbar.run_timer_title)
        dialog.setFixedWidth(320)
        dlg_layout = QVBoxLayout(dialog)

        lbl = QLabel(S.toolbar.run_timer_label)
        dlg_layout.addWidget(lbl)

        spin = QSpinBox()
        spin.setRange(1, 86400)
        spin.setValue(widget.periodic_interval if widget.periodic_interval > 0 else 30)
        spin.setSuffix("s")
        dlg_layout.addWidget(spin)

        buttons = QDialogButtonBox()
        start_btn = buttons.addButton(S.toolbar.run_timer_start, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dlg_layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        interval = spin.value()
        widget.start_periodic(interval)
        self.main_toolbar.set_timer_running(True, interval)
        self.main_statusbar.action_label.setText(
            S.toolbar.run_timer_running.format(seconds=interval)
        )

    def _run_timer_fire(self):
        """DEPRECATED: Timer is now per-tab via SessionWidget.periodic_changed."""
        pass

    def _run_timer_schedule_next(self):
        """DEPRECATED: Timer is now per-tab via SessionWidget.schedule_next_periodic."""
        pass

    def _on_periodic_changed(self, widget, active: bool):
        """Handle per-tab periodic timer state change."""
        index = self.session_tabs.indexOf(widget)
        if index >= 0:
            interval = widget.periodic_interval if active else 0
            self.session_tabs.set_tab_timer_icon(index, active, interval)

        # Update toolbar button if this is the active tab
        current = self._get_current_session_widget()
        if current is widget:
            self.main_toolbar.set_timer_running(active, widget.periodic_interval if active else 0)
            if active:
                self.main_statusbar.action_label.setText(
                    S.toolbar.run_timer_running.format(seconds=widget.periodic_interval)
                )
            else:
                self.main_statusbar.action_label.setText("")

    def _start_execution_timer(self, mode: str = ""):
        """Starts the execution timer"""
        self._is_executing = True
        self._execution_mode = mode
        self._execution_timer.start()
        self._execution_update_timer.start(100)
        # Estilizar label UMA vez (nao a cada tick)
        self.execution_label.setStyleSheet("""
            QLabel {
                color: #FFD700;
                font-weight: bold;
                padding: 4px 12px;
                background: rgba(255, 215, 0, 0.15);
                border-left: 3px solid #FFD700;
                border-radius: 8px;
            }
        """)
        self._update_execution_time()
        self.main_statusbar.start_timer()

    def _stop_execution_timer(self):
        """Stops the execution timer and shows final time"""
        self._execution_update_timer.stop()
        if self._is_executing:
            elapsed = self._execution_timer.elapsed() / 1000.0
            self.main_statusbar.stop_timer()
            self.execution_label.setText(f"{elapsed:.2f}s")
            self.execution_label.setStyleSheet("""
                QLabel {
                    color: #00FF00;
                    font-weight: bold;
                    padding: 0 10px;
                }
            """)
        self._is_executing = False

    def _update_execution_time(self):
        """Updates the label with execution time"""
        if self._is_executing:
            elapsed = self._execution_timer.elapsed() / 1000.0
            mode = f"{self._execution_mode}" if self._execution_mode else "Code"
            self.execution_label.setText(S.status.running_mode_elapsed.format(mode=mode, elapsed=f"{elapsed:.1f}"))

    def _clear_execution_label(self):
        """Clears the execution label"""
        if not self._is_executing:
            self.execution_label.setText("")

    def _execute_current_block(self):
        """Executes the currently focused block with its language"""
        editor = self._get_current_editor()
        if not editor:
            return

        # If it's a BlockEditor, executes only the focused block
        from src.editors.block_editor import BlockEditor

        if isinstance(editor, BlockEditor):
            editor.execute_focused_block()
        else:
            # Legacy editor - executes as Python by default
            code = editor.get_selected_or_all_text().strip()
            if code:
                self._execute_python(code)

    def _execute_all_blocks(self):
        """Executes all blocks in sequence"""
        editor = self._get_current_editor()
        if not editor:
            return

        from src.editors.block_editor import BlockEditor

        if isinstance(editor, BlockEditor):
            editor.execute_all_blocks()
        else:
            # Editor antigo - executa tudo como Python
            code = editor.get_selected_or_all_text().strip()
            if code:
                self._execute_python(code)

    def _execute_and_advance(self):
        """Executes focused block and advances to next"""
        editor = self._get_current_editor()
        if not editor:
            return

        from src.editors.block_editor import BlockEditor

        if isinstance(editor, BlockEditor):
            editor._execute_focused_and_advance()

    def _force_execute_sql(self):
        """Forces execution of current block as SQL"""
        editor = self._get_current_editor()
        if not editor:
            return

        from src.editors.block_editor import BlockEditor

        if isinstance(editor, BlockEditor):
            code = editor.get_focused_block_code()
        else:
            code = editor.get_selected_or_all_text()

        if code and code.strip():
            self._execute_sql(code.strip())

    def _force_execute_python(self):
        """Forces execution of current block as Python"""
        editor = self._get_current_editor()
        if not editor:
            return

        from src.editors.block_editor import BlockEditor

        if isinstance(editor, BlockEditor):
            code = editor.get_focused_block_code()
        else:
            code = editor.get_selected_or_all_text()

        if code and code.strip():
            self._execute_python(code.strip())

    def _execute_sql(self, query: str):
        """Executes SQL query in background"""
        query = query.strip()
        if not query:
            # Get from current tab if empty
            editor = self._get_current_editor()
            if editor:
                query = editor.get_selected_or_all_text().strip()
            if not query:
                return

        # Use current session connection
        session = self.session_manager.focused_session
        if not session or not session.is_connected:
            self._show_warning(
                S.dialogs.warning, S.dialogs.cross_no_connection_msg
            )
            return

        connector = session.connector

        # Detect USE database command (runs synchronously since it's fast)
        # Supports: USE db, USE [db], USE `db`, USE db;
        # For Databricks also: USE CATALOG x, USE SCHEMA x
        use_match = re.match(r"^\s*USE\s+(?:CATALOG\s+|SCHEMA\s+)?[\[`]?([^\]`\s;]+)[\]`]?\s*;?\s*$", query, re.IGNORECASE)
        if use_match:
            database_name = use_match.group(1)
            # For Databricks, preserve CATALOG/SCHEMA prefix for proper handling
            if connector.db_type == "databricks":
                catalog_match = re.match(r"^\s*USE\s+CATALOG\s+", query, re.IGNORECASE)
                schema_match = re.match(r"^\s*USE\s+SCHEMA\s+", query, re.IGNORECASE)
                if catalog_match:
                    database_name = f"CATALOG:{database_name}"
                elif schema_match:
                    database_name = f"SCHEMA:{database_name}"
            try:
                self._start_execution_timer("SQL")
                self.action_label.setText(S.status.sql_switching_database.format(name=database_name))

                connector.change_database(database_name)
                database_name = get_connector_database_context(connector) or database_name
                session.database_context = database_name if connector.db_type == "databricks" else ""

                # Update statusbar
                self._update_connection_status()

                # Reload Object Explorer for the new database
                connection_name = getattr(session, "connection_name", "") or ""
                if connection_name:
                    # Invalidate cache since database changed via USE command (per-session)
                    sid = session.session_id
                    self._clear_sql_autocomplete_for_connection(current_widget, connection_name)
                    self._schema_service.invalidate_cache(connection_name, session_id=sid)
                    # Signal triggers _on_session_connection_changed which handles:
                    # - Schema reload
                    # - Connection panel update
                    # - Block database panels update
                    current_widget = self._get_current_session_widget()
                    if current_widget and hasattr(current_widget, "connection_changed"):
                        current_widget.connection_changed.emit(connection_name, database_name)

                self._log_info(S.status.database_changed.format(name=database_name))
                self.action_label.setText(S.status.sql_database.format(name=database_name))
                self._stop_execution_timer()
                return

            except Exception as e:
                self._stop_execution_timer()
                QMessageBox.critical(self, S.dialogs.error, S.dialogs.error_switching_db.format(error=str(e)))
                self.action_label.setText(S.status.sql_error_switching)
                return

        # Background execution
        self._start_execution_timer("SQL")
        self.action_label.setText(S.status.sql_running_query)

        # Mark tab as running
        running_tab_index = self._mark_tab_running(True)

        # Save current database to detect change via USE within batch
        try:
            current_db_before = get_connector_database_context(connector)
        except Exception:
            current_db_before = ""

        # Create thread and worker
        thread = QThread()
        worker = SqlWorker(connector, query)
        worker.moveToThread(thread)

        # Connect signals
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda df, err: self._on_sql_finished(df, err, thread, running_tab_index, current_db_before)
        )

        # Safe cleanup: only delete when thread actually stops
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        # Keep reference
        self._worker_threads.append((thread, worker))

        # Start
        thread.start()

    def _display_figures_in_results(self, figures: list, label: str = "Result"):
        """Displays rich outputs (images/HTML/JSON) in the results panel."""
        results_panel = self.global_results_viewer
        if not results_panel or not figures:
            return
        results_panel.display_rich_output(figures, label)
        self.show_panel("results")

    def _handle_execution_result(self, result=None, error=None, execution_type="Unknown", additional_info=""):
        """
        Centralized method for handling execution results

        Args:
            result: Execution result (DataFrame, string, etc) or None
            error: Mensagem de erro ou None
            execution_type: Execution type ("SQL", "Python", "Cross-Syntax")
            additional_info: Additional information for logs
        """
        if error:
            # ERRO → OUTPUT (console)
            self._show_error_output(f"[{execution_type}] {error}")
            self.action_label.setText(S.status.execution_error_generic.format(type=execution_type))
            return False  # Indica erro

        if result is None:
            # SEM RESULTADO → OUTPUT (console)
            self.show_panel("output")
            return True

        # SUCESSO -> Decidir painel baseado no tipo do resultado
        import pandas as pd

        results_panel = self.global_results_viewer

        if isinstance(result, pd.DataFrame):
            # DATAFRAME -> GRID (results)
            if results_panel:
                results_panel.display_dataframe(result, f"{execution_type} Result")
            self.show_panel("results")
            rows = len(result)
            self._log_info(f"[{execution_type}] {additional_info or S.log.df_displayed.format(type=execution_type, rows=f'{rows:,}')}")
            return True

        elif isinstance(result, pd.Series):
            # SERIES -> Convert to DataFrame and show in GRID
            df = result.to_frame(name=result.name or "value")
            if results_panel:
                results_panel.display_dataframe(df, f"{execution_type} Result")
            self.show_panel("results")
            rows = len(df)
            self._log_info(f"[{execution_type}] Series displayed ({rows:,} rows)")
            return True

        elif isinstance(result, (list, tuple)) and len(result) > 0:
            # LISTA/TUPLA → Tentar converter para DataFrame
            try:
                df = pd.DataFrame(result)
                if len(df) > 0:
                    if results_panel:
                        results_panel.display_dataframe(df, f"{execution_type} Result")
                    self.show_panel("results")
                    self._log_info(S.log.list_converted.format(type=execution_type, rows=len(df)))
                    return True
            except (ValueError, TypeError, KeyError):
                pass

            # If could not convert, goes to output
            self._log(f"[{execution_type}] {repr(result)}")
            return True

        elif isinstance(result, dict):
            # DICT → Tentar converter para DataFrame
            try:
                df = (
                    pd.DataFrame([result])
                    if not isinstance(list(result.values())[0], (list, tuple))
                    else pd.DataFrame(result)
                )
                if results_panel:
                    results_panel.display_dataframe(df, f"{execution_type} Result")
                self.show_panel("results")
                self._log_info(S.log.dict_converted.format(type=execution_type))
                return True
            except (ValueError, TypeError, KeyError, IndexError):
                pass

            # If could not convert, goes to output
            self._log(f"[{execution_type}] {repr(result)}")
            return True

        else:
            # OUTROS TIPOS -> OUTPUT (console)
            self._log(f"[{execution_type}] {repr(result)}")
            return True

    def _remove_worker_thread(self, thread):
        """Removes thread from active workers list (called via thread.finished)."""
        self._worker_threads = [(t, w) for t, w in self._worker_threads if t != thread]

    def _on_sql_finished(self, df, error, thread, tab_index, db_before=""):
        """Callback quando SQL termina"""
        self._stop_execution_timer()

        # Remove running mark
        self._mark_tab_running(False, tab_index)

        # Stop thread (finished signal handles cleanup)
        thread.quit()

        # Detectar mudanca de banco via USE dentro do batch SQL
        self._check_database_changed_after_sql(db_before)

        # FORCAR: Se ha erro, SEMPRE mostrar output
        if error:
            self._show_error_output(f"[SQL] Error: {error}")
            self.action_label.setText(S.status.sql_execution_error)
            self._send_notification(S.notification.sql_query, S.notification.error.format(error=str(error)[:50]), success=False, tab_index=tab_index)
            return

        # ONLY if there is no error, use centralized method
        success = self._handle_execution_result(
            result=df,
            error=None,  # Ensure error is None here
            execution_type="SQL",
            additional_info=f"Executed successfully ({len(df):,} rows returned)" if df is not None else "",
        )

        if success:
            rows = len(df) if df is not None else 0
            self.action_label.setText(S.status.sql_rows_returned.format(rows=f"{rows:,}"))
            self._send_notification(
                S.notification.sql_query, S.notification.complete_rows.format(rows=f"{rows:,}"), success=True, tab_index=tab_index
            )

    def _check_database_changed_after_sql(self, db_before: str):
        """Checks if the database changed after SQL execution (e.g. USE within batch).

        Se mudou, recarrega o Object Explorer com o novo banco.
        Propaga a mudanca para: connection panel, status bar, tab color, todos os blocos.

        NOTE: This only triggers reload if the database actually changed.
        """
        # Skip if no db_before captured
        if not db_before:
            return

        session = self.session_manager.focused_session
        if not session or not session.connector:
            return

        connector = session.connector
        try:
            db_after = get_connector_database_context(connector)
        except Exception:
            return

        # Skip if db_after is empty or if they are the same (case-insensitive)
        if not db_after:
            return
        if db_after.lower() == db_before.lower():
            return

        # Database actually changed - reload schema
        connection_name = getattr(session, "connection_name", "") or ""
        if connection_name:
            # Invalidate cache since database changed (per-session)
            sid = session.session_id
            current_widget = self._get_current_session_widget()
            self._clear_sql_autocomplete_for_connection(current_widget, connection_name)
            self._schema_service.invalidate_cache(connection_name, session_id=sid)
            # Signal triggers _on_session_connection_changed which handles:
            # - Schema reload
            # - Connection panel update
            # - Tab color update
            # - Block database panels update
            # - Status bar update
            if current_widget and hasattr(current_widget, "connection_changed"):
                current_widget.connection_changed.emit(connection_name, db_after)

    def _execute_python(self, code: str):
        """Executes Python code in background"""
        code = code.strip()
        if not code:
            # Get from current tab if empty
            editor = self._get_current_editor()
            if editor:
                code = editor.get_selected_or_all_text().strip()
            if not code:
                return

        self._start_execution_timer("Python")
        self.action_label.setText(S.status.python_running)

        # Mark tab as running
        running_tab_index = self._mark_tab_running(True)

        # Namespace with DataFrames
        namespace = self.results_manager.get_namespace()

        # Always use centralized logic
        is_expression = False

        # Create thread and worker
        thread = QThread()
        worker = PythonWorker(code, namespace, is_expression)
        worker.moveToThread(thread)

        # Connect signals
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda result, output, err, namespace, figures: self._on_python_finished(
                result, output, err, namespace, figures, thread, running_tab_index
            )
        )

        # Safe cleanup: only delete when thread actually stops
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._remove_worker_thread(thread))

        # Keep reference
        self._worker_threads.append((thread, worker))

        # Start
        thread.start()

    def _on_python_finished(self, result_value, output, error, updated_namespace, figures, thread, tab_index):
        """Callback quando Python termina"""
        self._stop_execution_timer()

        # Save updated namespace
        self.results_manager.update_namespace(updated_namespace)

        # Update Python autocomplete with updated namespace
        if updated_namespace:
            self._push_python_namespace(updated_namespace)

        # Remove running mark
        self._mark_tab_running(False, tab_index)

        # Stop thread (finished signal handles cleanup)
        thread.quit()

        # FORCE: If there is an error, ALWAYS show output first
        if error:
            self._show_error_output(f"[Python] Error: {error}")
            self.action_label.setText(S.status.python_execution_error)
            self._send_notification(S.notification.python, S.notification.error.format(error=str(error)[:50]), success=False, tab_index=tab_index)
            return

        # Show output from print()/stderr (if any) -> output panel
        if output:
            self._log(output.strip())

        # Decide what to show in the Results panel:
        # Priority: rich outputs (charts/html/json) > DataFrame > nothing
        has_figures = bool(figures)
        results_panel = self.global_results_viewer

        if has_figures and result_value is not None and isinstance(result_value, pd.DataFrame):
            # Rich outputs + DataFrame: show rich output in results
            if results_panel:
                results_panel.display_rich_output(figures, "Result")
            self.show_panel("results")
            self._update_variables_view()
            self.action_label.setText(S.status.python_chart_data)
            self._send_notification(S.notification.python, S.notification.chart_data, success=True, tab_index=tab_index)
        elif has_figures:
            # Only rich outputs: show in results
            if results_panel:
                results_panel.display_rich_output(figures, "Result")
            self.show_panel("results")
            self._update_variables_view()
            self.action_label.setText(S.status.python_result_displayed)
            self._send_notification(S.notification.python, S.notification.result_displayed, success=True, tab_index=tab_index)
        elif result_value is not None:
            # Result without charts: use centralized handler
            success = self._handle_execution_result(result=result_value, error=None, execution_type="Python")
            if success:
                self._update_variables_view()
                self.action_label.setText(S.status.python_executed)
                self._send_notification(S.notification.python, S.notification.executed, success=True, tab_index=tab_index)
        else:
            # No result, no charts: only output
            if output:
                self.show_panel("output")
            self._update_variables_view()
            self.action_label.setText(S.status.python_executed)
            self._send_notification(S.notification.python, S.notification.executed, success=True, tab_index=tab_index)

    def _mark_tab_running(self, is_running: bool, tab_index: int = None) -> int:
        """
        Marca/desmarca aba como rodando (com spinner animado).

        Args:
            is_running: Se True, mostra spinner. Se False, para.
            tab_index: Indice da aba. Se None, usa a aba atual.

        Returns:
            Indice da aba modificada
        """
        if tab_index is None:
            tab_index = self.session_tabs.currentIndex()

        if tab_index < 0 or tab_index >= self.session_tabs.count():
            return tab_index

        self.session_tabs.set_tab_running(tab_index, is_running)
        return tab_index

    def _on_execution_cancelled(self, widget):
        """
        Handle execution cancellation from a SessionWidget.

        Clears the tab running indicator for the widget that cancelled.
        """
        tab_index = self.session_tabs.indexOf(widget)
        if tab_index >= 0:
            self._mark_tab_running(False, tab_index)
            self._stop_execution_timer()

    def _on_execution_started(self, widget):
        """
        Handle execution start from a SessionWidget.

        Sets the tab running indicator for the widget that started executing.
        """
        tab_index = self.session_tabs.indexOf(widget)
        if tab_index >= 0:
            self._mark_tab_running(True, tab_index)

    def _on_execution_finished_cleanup(self, widget):
        """
        Handle execution finish cleanup from a SessionWidget.

        Clears the tab running indicator for the widget that finished.
        """
        tab_index = self.session_tabs.indexOf(widget)
        if tab_index >= 0:
            self._mark_tab_running(False, tab_index)
            self._stop_execution_timer()

        # Per-tab periodic timer chains via SessionWidget.execution_finished -> schedule_next_periodic

    def _on_execution_finished_notification(self, title: str, message: str, success: bool, widget):
        """
        Envia notificacao apos execucao terminar.
        Suppresses notification if the user is focused on the originating tab.
        """
        tab_index = self.session_tabs.indexOf(widget)
        delivery = getattr(widget, "_last_notification_delivery", None) or {}
        tab_is_focused = (
            self.isActiveWindow()
            and tab_index >= 0
            and tab_index == self.session_tabs.currentIndex()
        )

        if delivery.get("suppressed") or tab_is_focused:
            return

        if delivery.get("send_external"):
            get_notification_delivery_service(self).deliver(
                title=title,
                message=message,
                success=success,
                channels={"telegram": True, "email": True},
            )

        # Check per-tab custom notification color
        color = delivery.get("color")
        if not color:
            tab_config = getattr(widget, '_tab_notification_config', None)
            if tab_config and tab_config.get("enabled") and tab_config.get("color"):
                color = tab_config["color"]
        self._send_notification(title, message, success, tab_index, color=color)

    def _send_notification(self, title: str, message: str, success: bool = True, tab_index: int = None, color: str = None):
        """
        Envia notificacao in-app (toast) no canto inferior direito.

        Args:
            title: Titulo da notificacao
            message: Mensagem
            success: Se True, notificacao de sucesso (verde), senao erro (vermelho)
            tab_index: Indice da aba que originou (foca nela ao clicar)
        """
        try:
            from PyQt6.QtCore import QSettings
            settings = QSettings("DataPyn", "DataPyn")
            if not settings.value("notifications/enabled", True, type=bool):
                return

            sound = settings.value("notifications/sound", True, type=bool)

            on_click = None
            if tab_index is not None:
                on_click = lambda idx=tab_index: self._focus_window_and_tab(idx)

            ToastManager.notify(
                title=title,
                message=message,
                success=success,
                on_click=on_click,
                sound=sound,
                color=color,
            )
        except Exception as e:
            logger.error(f"Error sending toast notification: {e}")

    def _focus_window_and_tab(self, tab_index: int = None):
        """Brings window to front, focuses, and selects the tab that notified"""
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()
        self.show()
        if tab_index is not None and 0 <= tab_index < self.session_tabs.count():
            self.session_tabs.setCurrentIndex(tab_index)

    def _focus_window(self):
        """Brings window to front and focuses"""
        self._focus_window_and_tab(None)

    def _log_info(self, message: str):
        """Adds message to log with timestamp (without showing panel)"""
        if self.global_output_panel:
            self.global_output_panel.log(message)

    def _log(self, message: str):
        """Adds message to log with timestamp and shows output panel"""
        if self.global_output_panel:
            self.global_output_panel.log(message)

        # Mostrar painel de output
        self.show_panel("output")

    def _show_error_output(self, error_msg: str):
        """Shows error in Output in red and switches to the Output panel"""
        if not self.global_output_panel:
            return
        self.global_output_panel.error(error_msg)

        # Mostrar painel de output
        self.show_panel("output")

    def _update_variables_view(self):
        """Updates variable visualization in memory"""
        panel = self.global_variables_panel
        if not panel:
            return
        vars_df = self.results_manager.get_variables_info()
        panel.display_dataframe(vars_df, "Variaveis")

    def _clear_results(self):
        """Clears all results"""
        reply = QMessageBox.question(
            self,
            S.dialogs.confirm_clear_title,
            S.dialogs.confirm_clear_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.results_manager.clear_all()
            results = self.global_results_viewer
            if results:
                results.clear()
            variables = self.global_variables_panel
            if variables:
                variables.clear()
            output = self.global_output_panel
            if output:
                output.clear()
            self.action_label.setText(S.status.results_cleared)
