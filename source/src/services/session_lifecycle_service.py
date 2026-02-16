"""
SessionLifecycleService - Centralized service for session lifecycle

Responsible for:
- Creating sessions (new, from file, duplicate)
- Closing sessions (individual, all, others)
- Ensuring panels and widgets are created/removed consistently
- Managing transition between empty and with-sessions state

Principle: All session creation/destruction MUST go through this service.
This prevents bugs where panels, widgets or state become inconsistent.
"""

from typing import Optional, Callable, Dict, List, Any, Protocol, runtime_checkable
from PyQt6.QtCore import QObject, pyqtSignal


@runtime_checkable
class ISessionHost(Protocol):
    """Interface that the host (MainWindow) must implement for the service to work."""

    def create_session_panels(self, session_id: str) -> None:
        """Create panels (Results, Output, Variables) for the session."""
        ...

    def remove_session_panels(self, session_id: str) -> None:
        """Remove panels from a session."""
        ...

    def switch_session_panels(self, session_id: str) -> None:
        """Switch stacks to display active session panels."""
        ...

    def hide_all_panels(self) -> None:
        """Hide all bottom panels (empty state)."""
        ...

    def show_all_panels(self) -> None:
        """Show all bottom panels."""
        ...


class SessionLifecycleService(QObject):
    """
    Centralized service for session lifecycle.

    Centralizes session creation, destruction and switching to ensure
    consistency between SessionManager, SessionTabs, panels and widgets.
    """

    # Signals emitted by the service
    session_created = pyqtSignal(str)  # session_id
    session_closed = pyqtSignal(str)  # session_id
    session_switched = pyqtSignal(str)  # session_id
    all_sessions_closed = pyqtSignal()  # when no session remains
    first_session_created = pyqtSignal()  # when leaving empty state

    def __init__(self, session_manager, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self._host: Optional[ISessionHost] = None
        self._is_creating = False
        self._is_closing = False
        self._session_widgets: Dict[str, Any] = {}

    def set_host(self, host: ISessionHost):
        """Set the host (MainWindow) that implements ISessionHost."""
        self._host = host

    @property
    def is_creating(self) -> bool:
        return self._is_creating

    @property
    def is_closing(self) -> bool:
        return self._is_closing

    @property
    def has_sessions(self) -> bool:
        """Return True if at least one active session exists."""
        return len(self._session_widgets) > 0

    @property
    def session_count(self) -> int:
        return len(self._session_widgets)

    def get_widget(self, session_id: str):
        """Return widget associated with a session."""
        return self._session_widgets.get(session_id)

    @property
    def all_widgets(self) -> Dict[str, Any]:
        return dict(self._session_widgets)

    def register_widget(self, session_id: str, widget):
        """Register an externally created widget (used during restore)."""
        self._session_widgets[session_id] = widget

    def create_session(self, title: str = None, widget_factory: Callable = None) -> tuple:
        """
        Create a new session with all necessary components.

        Args:
            title: Session title (optional)
            widget_factory: Function that receives Session and returns widget

        Returns:
            Tuple (session, widget) or (session, None) if no factory
        """
        if self._is_creating:
            return None, None

        self._is_creating = True
        was_empty = not self.has_sessions

        try:
            # Create session in manager
            session = self._session_manager.create_session(title=title)

            # Create panels for session
            if self._host:
                self._host.create_session_panels(session.session_id)

            widget = None
            if widget_factory:
                widget = widget_factory(session)
                self._session_widgets[session.session_id] = widget

            # Signal
            if was_empty:
                self.first_session_created.emit()

            self.session_created.emit(session.session_id)
            return session, widget

        finally:
            self._is_creating = False

    def close_session(self, session_id: str, cleanup_callback: Callable = None) -> bool:
        """
        Close a session and remove all components.

        Args:
            session_id: Session ID
            cleanup_callback: Function called before removing (for widget cleanup)

        Returns:
            True if closed successfully
        """
        if self._is_closing:
            return False

        self._is_closing = True

        try:
            # Cleanup widget
            widget = self._session_widgets.get(session_id)
            if widget and cleanup_callback:
                cleanup_callback(widget)

            # Close session in manager
            self._session_manager.close_session(session_id)

            # Remove panels
            if self._host:
                self._host.remove_session_panels(session_id)

            # Remove widget from registry
            self._session_widgets.pop(session_id, None)

            # Signal
            self.session_closed.emit(session_id)

            if not self.has_sessions:
                # Hide panels when no sessions
                if self._host:
                    self._host.hide_all_panels()
                self.all_sessions_closed.emit()

            return True

        finally:
            self._is_closing = False

    def close_all_sessions(self, cleanup_callback: Callable = None):
        """Close all sessions."""
        session_ids = list(self._session_widgets.keys())
        for sid in session_ids:
            self.close_session(sid, cleanup_callback)

    def switch_to_session(self, session_id: str):
        """Switch to an active session."""
        if session_id not in self._session_widgets:
            return

        self._session_manager.focus_session(session_id)

        if self._host:
            self._host.switch_session_panels(session_id)

        self.session_switched.emit(session_id)
