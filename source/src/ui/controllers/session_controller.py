"""
SessionController - Manages session/tab lifecycle

Extracted from MainWindow to follow Single Responsibility Principle.
Handles:
- Creating new sessions
- Closing sessions
- Duplicating sessions
- Session persistence (save/restore)
- Tab navigation
"""

from typing import TYPE_CHECKING, Dict, Optional, Callable
from PyQt6.QtCore import QObject, QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from src.ui.components.session_widget import SessionWidget
from src.language import S

import logging

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.ui.main_window import MainWindow


class SessionController(QObject):
    """Controller for session/tab management"""
    
    # Signals
    session_created = pyqtSignal(object)  # SessionWidget
    session_closed = pyqtSignal(str)  # session_id
    session_focused = pyqtSignal(object)  # Session
    
    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._main = main_window
        
        # State flags
        self._creating_session = False
        self._closing_session = False
        self._restoring_sessions = False
        
        # Sessions to load queue (for incremental restore)
        self._sessions_to_load = []
        
        # Connection threads (prevent GC)
        self._connection_threads = []
        
    @property
    def session_widgets(self) -> Dict[str, SessionWidget]:
        """Access to session widgets dictionary"""
        return self._main._session_widgets
    
    @property
    def session_manager(self):
        """Access to SessionManager"""
        return self._main.session_manager
    
    @property
    def session_tabs(self):
        """Access to SessionTabs widget"""
        return self._main.session_tabs
    
    @property
    def connection_manager(self):
        """Access to ConnectionManager"""
        return self._main.connection_manager
    
    @property
    def theme_manager(self):
        """Access to ThemeManager"""
        return self._main.theme_manager
    
    # =========================================================================
    # SESSION CREATION
    # =========================================================================
    
    def new_session(self, inherit_connection: bool = True) -> Optional[SessionWidget]:
        """Creates a new session, optionally inheriting connection from current tab"""
        if self._creating_session:
            return None
        
        self._creating_session = True
        try:
            # Capture active session connection BEFORE creating new one
            previous_connection = None
            previous_color = None
            
            if inherit_connection:
                current_widget = self.get_current_session_widget()
                if current_widget and hasattr(current_widget, "session"):
                    previous_connection = current_widget.session.connection_name
                    if previous_connection:
                        config = self.connection_manager.get_connection_config(previous_connection)
                        if config:
                            previous_color = config.get("color", "#007ACC") or "#007ACC"
            
            # Hide empty state if showing
            self._main._hide_empty_state()
            
            # Create session
            session = self.session_manager.create_session()
            widget = self.create_session_widget(session)
            
            # Update window title
            self._main._update_window_title()
            
            # Defer connection to background with delay
            if previous_connection:
                QTimer.singleShot(150, lambda: self._connect_session_background(
                    widget, session, previous_connection, previous_color
                ))
            
            self.session_created.emit(widget)
            return widget
            
        finally:
            self._creating_session = False
    
    def create_session_widget(self, session) -> SessionWidget:
        """Creates widget for a session and adds it to a tab"""
        widget = SessionWidget(session, theme_manager=self.theme_manager)
        
        if hasattr(self._main, "_pynia_agent") and self._main._pynia_agent:
            widget.editor.set_pynia_client(self._main._pynia_agent)
        elif hasattr(self._main, "_copilot_client") and self._main._copilot_client:
            widget.editor.set_pynia_client(self._main._copilot_client)

        # Native Copilot LSP completion (preferred over the prompt path).
        lsp_client = getattr(self._main, "_lsp_client", None)
        if lsp_client and hasattr(widget.editor, "set_lsp_client"):
            widget.editor.set_lsp_client(lsp_client)

        # Create panels for session
        self._main._create_session_panels(session.session_id)
        
        # Set file_path on widget if available
        if hasattr(session, "file_path") and session.file_path:
            widget.file_path = session.file_path
            widget._original_file_type = getattr(session, "original_file_type", None)
        else:
            widget.file_path = None
            widget._original_file_type = None
        
        # Initialize content hash for modification tracking
        widget._content_hash = self._main._compute_widget_content_hash(widget)
        widget._is_modified = False
        
        # Connect widget signals
        self._connect_widget_signals(widget, session)
        
        # Store reference
        self.session_widgets[session.session_id] = widget
        
        # Add tab using SessionTabs method
        index = self.session_tabs.add_session(widget, session.title)
        
        # Apply tab color based on session connection
        if hasattr(session, "_connection_name") and session._connection_name:
            config = self.connection_manager.get_connection_config(session._connection_name)
            if config:
                color = config.get("color", "#007ACC") or "#007ACC"
                self.session_tabs.set_tab_connection_color(index, color)
        
        # Switch panels to new session
        self._main._switch_session_panels(session.session_id)
        
        # Focus on first block with delay for rendering
        if widget.editor and hasattr(widget.editor, "focus_first_block"):
            QTimer.singleShot(50, widget.editor.focus_first_block)
        
        return widget
    
    def _connect_widget_signals(self, widget: SessionWidget, session):
        """Connect all signals from a SessionWidget"""
        # Status changes
        widget.status_changed.connect(
            lambda msg: self._main._on_session_status_changed(session, msg)
        )
        
        # Connection changes
        widget.connection_changed.connect(
            lambda conn_name, db: self._main._on_session_connection_changed(session, conn_name, db)
        )
        widget.block_connection_changed.connect(
            lambda block, conn_name: self._main._on_block_connection_changed(block, conn_name)
        )
        widget.connection_drop_requested.connect(
            lambda conn_name: self._main._quick_connect(conn_name)
        )
        widget.block_database_changed.connect(
            lambda block, db_name: self._main._on_block_database_changed(block, db_name)
        )
        
        # Execution signals
        widget.execution_started.connect(
            lambda w=widget: self._main._on_execution_started(w)
        )
        widget.execution_finished.connect(
            lambda title, msg, success, w=widget: self._main._on_execution_finished_notification(
                title, msg, success, w
            )
        )
        widget.execution_finished.connect(
            lambda title, msg, success, w=widget: self._main._on_execution_finished_cleanup(w)
        )
        widget.execution_cancelled.connect(
            lambda w=widget: self._main._on_execution_cancelled(w)
        )
        
        # Completion logging (for Copilot output panel)
        widget.completion_log.connect(self._main._on_completion_log)
        
        # Editor modification tracking
        widget.editor.content_changed.connect(
            lambda w=widget: self._main._on_editor_modified(w)
        )
        
        # Namespace changes (for autocomplete)
        session.variables_changed.connect(
            lambda ns: self._main._push_python_namespace(ns)
        )
    
    def _connect_session_background(self, widget, session, connection_name, color):
        """Connect session in background thread to avoid UI freeze"""
        
        class ConnectionWorker(QObject):
            finished = pyqtSignal(bool)
            
            def __init__(self, session, connection_name):
                super().__init__()
                self._session = session
                self._connection_name = connection_name
            
            def run(self):
                try:
                    result = self._session.connect(self._connection_name)
                    self.finished.emit(result)
                except Exception as e:
                    logger.warning(f"Background connection failed: {e}")
                    self.finished.emit(False)
        
        def on_connected(success):
            if success and color:
                idx = self.session_tabs.indexOf(widget)
                if idx >= 0:
                    self.session_tabs.set_tab_connection_color(idx, color)
            # Cleanup
            thread.quit()
            thread.wait()
            thread.deleteLater()
            worker.deleteLater()
        
        thread = QThread()
        worker = ConnectionWorker(session, connection_name)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_connected)
        thread.start()
        
        self._connection_threads.append(thread)
    
    # =========================================================================
    # SESSION CLOSING
    # =========================================================================
    
    def close_session(self, index: int) -> bool:
        """Closes session tab at index. Returns True if closed."""
        widget = self.session_tabs.widget(index)
        if not isinstance(widget, SessionWidget):
            return False
        
        # Check if execution is running
        if getattr(widget, "_is_executing", False):
            reply = QMessageBox.question(
                self._main,
                "Cancel Execution?",
                "A script is running in this tab. Do you want to cancel it and close the tab?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False
            widget._on_cancel_execution()
        
        self._closing_session = True
        try:
            # Clear file path tracking if needed
            closed_file_path = getattr(widget, "file_path", None)
            if closed_file_path and closed_file_path == self._main._original_file_path:
                self._main._original_file_path = None
                self._main._original_file_type = None
            
            # Cleanup
            session_id = widget.session.session_id
            widget.cleanup()
            self.session_manager.close_session(session_id)
            
            # Remove session panels
            self._main._remove_session_panels(session_id)
            
            # Remove from dictionary
            if session_id in self.session_widgets:
                del self.session_widgets[session_id]
            
            self.session_tabs.removeTab(index)
            self.save_sessions()
            
            # Check if no more sessions
            session_count = sum(
                1 for i in range(self.session_tabs.count())
                if isinstance(self.session_tabs.widget(i), SessionWidget)
            )
            if session_count == 0:
                self._main._original_file_path = None
                self._main._original_file_type = None
                self._main._show_empty_state()
            
            self._main._update_window_title()
            self.session_closed.emit(session_id)
            return True
            
        finally:
            self._closing_session = False
    
    def close_current_session(self) -> bool:
        """Closes the currently active session"""
        current_index = self.session_tabs.currentIndex()
        widget = self.session_tabs.widget(current_index)
        
        if not isinstance(widget, SessionWidget):
            return False
        
        # Don't close if it's the only session
        session_count = sum(
            1 for i in range(self.session_tabs.count())
            if isinstance(self.session_tabs.widget(i), SessionWidget)
        )
        if session_count <= 1:
            return False
        
        return self.close_session(current_index)
    
    # =========================================================================
    # SESSION DUPLICATION
    # =========================================================================
    
    def duplicate_session(self, index: int) -> Optional[SessionWidget]:
        """Duplicates a session at index"""
        widget = self.session_tabs.widget(index)
        if not widget or not hasattr(widget, "editor"):
            return None
        
        self._creating_session = True
        try:
            # Create new session
            session = self.session_manager.create_session()
            new_widget = SessionWidget(session, theme_manager=self.theme_manager)
            
            # Create panels
            self._main._create_session_panels(session.session_id)
            
            # Copy editor content
            source_blocks = widget.editor.get_blocks()
            new_blocks = new_widget.editor.get_blocks()
            
            # Remove existing blocks except last
            for b in new_blocks[:-1]:
                new_widget.editor.remove_block(b)
            
            # Copy blocks
            if source_blocks:
                first_new_block = new_widget.editor.get_blocks()[0]
                first_new_block.set_language(source_blocks[0].get_language())
                first_new_block.set_code(source_blocks[0].get_code())
                
                for block in source_blocks[1:]:
                    new_block = new_widget.editor.add_block(language=block.get_language())
                    new_block.set_code(block.get_code())
            
            # Copy file_path
            if hasattr(widget, "file_path"):
                new_widget.file_path = widget.file_path
            
            # Inherit connection
            if hasattr(widget, "session") and widget.session.connection_name:
                try:
                    session.connect(widget.session.connection_name)
                except Exception:
                    pass
            
            # Connect signals
            self._connect_widget_signals(new_widget, session)
            
            # Register widget
            self.session_widgets[session.session_id] = new_widget
            
            # Tab name
            original_name = self.session_tabs.tabText(index)
            new_name = f"{original_name} (copia)"
            
            # Insert tab
            insert_position = self.session_tabs.count() - 1 if self.session_tabs.count() > 0 else 0
            tab_index = self.session_tabs.insertTab(insert_position, new_widget, new_name)
            
            self.session_tabs._setup_close_button(tab_index)
            
            # Apply tab color
            if session.connection_name:
                config = self.connection_manager.get_connection_config(session.connection_name)
                if config:
                    color = config.get("color", "#007ACC") or "#007ACC"
                    self.session_tabs.set_tab_connection_color(tab_index, color)
            
            self.session_tabs.setCurrentIndex(tab_index)
            self._main._switch_session_panels(session.session_id)
            
            self.session_created.emit(new_widget)
            return new_widget
            
        finally:
            self._creating_session = False
    
    # =========================================================================
    # SESSION PERSISTENCE
    # =========================================================================
    
    def save_sessions(self):
        """Saves all sessions"""
        # Sync code from widgets to sessions
        for session_id, widget in self.session_widgets.items():
            widget.sync_to_session()
        
        # Save via SessionManager
        self.session_manager.save_sessions()
        
        # Save window geometry
        window_geometry = {
            "x": self._main.geometry().x(),
            "y": self._main.geometry().y(),
            "width": self._main.geometry().width(),
            "height": self._main.geometry().height(),
            "maximized": self._main.isMaximized(),
        }
        
        dock_visible = (
            self._main.connections_dock.isVisible()
            if hasattr(self._main, "connections_dock")
            else True
        )
        
        self._main.workspace_manager.save_workspace(
            tabs=[],
            active_tab=0,
            active_connection=None,
            window_geometry=window_geometry,
            splitter_sizes=[],
            dock_visible=dock_visible,
        )
    
    def restore_sessions(self):
        """Restores saved sessions - loads incrementally"""
        self._restoring_sessions = True
        
        # Load sessions from disk
        self.session_manager.load_sessions(self.connection_manager)
        
        # Save workspace for geometry restore
        workspace = self._main.workspace_manager.load_workspace()
        self._main._pending_workspace_restore = workspace
        
        # Queue sessions for incremental loading
        self._sessions_to_load = list(self.session_manager.sessions)
        
        self._restoring_sessions = False
        
        # Start loading
        if self._sessions_to_load:
            QTimer.singleShot(50, self._load_next_session)
        else:
            self._main._show_empty_state()
    
    def _load_next_session(self):
        """Loads next session from queue"""
        if not self._sessions_to_load:
            # Focus on active session
            focused = self.session_manager.focused_session
            if focused:
                index = self.session_manager.get_session_index(focused.session_id)
                if index >= 0:
                    self.session_tabs.setCurrentIndex(index)
                
                if focused.is_connected and hasattr(self._main, "connection_panel"):
                    self._main.connection_panel.set_active_connection(
                        focused.connection_name,
                        focused.connection_name,
                    )
            return
        
        session = self._sessions_to_load.pop(0)
        self.create_session_widget(session)
        
        QApplication.processEvents()
        QTimer.singleShot(10, self._load_next_session)
    
    # =========================================================================
    # UTILITIES
    # =========================================================================
    
    def get_current_session_widget(self) -> Optional[SessionWidget]:
        """Returns the currently active SessionWidget"""
        index = self.session_tabs.currentIndex()
        widget = self.session_tabs.widget(index)
        if isinstance(widget, SessionWidget):
            return widget
        return None
    
    def on_tab_changed(self, index: int):
        """Handle tab changed event"""
        if self._restoring_sessions or self._creating_session or self._closing_session:
            return
        
        # "+" tab creates new session
        if self.session_tabs.tabText(index).strip() == "+":
            self.new_session()
            return
        
        widget = self.session_tabs.widget(index)
        if isinstance(widget, SessionWidget):
            self.session_manager.focus_session(widget.session.session_id)
            self._main._switch_session_panels(widget.session.session_id)
            
            # Restore file context
            if hasattr(widget, "file_path") and widget.file_path:
                self._main._original_file_path = widget.file_path
                self._main._original_file_type = getattr(widget, "_original_file_type", None)
            else:
                self._main._original_file_path = None
                self._main._original_file_type = None
        
        self._main._update_window_title()
    
    def on_session_renamed(self, index: int, new_name: str):
        """Handle session rename"""
        widget = self.session_tabs.widget(index)
        if not isinstance(widget, SessionWidget):
            return
        
        widget.session.title = new_name.strip()
        self.save_sessions()
    
    @property
    def is_creating(self) -> bool:
        """True if currently creating a session"""
        return self._creating_session
    
    @property
    def is_closing(self) -> bool:
        """True if currently closing a session"""
        return self._closing_session
    
    @property
    def is_restoring(self) -> bool:
        """True if currently restoring sessions"""
        return self._restoring_sessions
