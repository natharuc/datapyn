"""
SessionManager - Central session manager

Responsibilities:
- Create/destroy sessions
- Maintain focused session
- Serialize/deserialize all sessions
- Notify focus changes
"""

from PyQt6.QtCore import QObject, pyqtSignal
from typing import Optional, Dict, List, Any
from pathlib import Path
import json
import uuid
import logging

from .session import Session

logger = logging.getLogger(__name__)


class SessionManager(QObject):
    """
    Central manager for all sessions.

    Maintains control of which session is focused and
    manages the session lifecycle.
    """

    # Sinais
    session_created = pyqtSignal(Session)
    session_closed = pyqtSignal(str)  # session_id
    session_focused = pyqtSignal(Session)  # New focused session
    sessions_restored = pyqtSignal()  # When sessions are restored from disk

    def __init__(self, workspace_path: Optional[Path] = None):
        super().__init__()

        self._sessions: Dict[str, Session] = {}
        self._focused_session: Optional[Session] = None
        self._session_order: List[str] = []  # Session order (for tabs)

        # Path to save sessions
        if workspace_path:
            self._sessions_file = workspace_path / "sessions.json"
        else:
            # Use WorkspaceService for default path (supports workspace switching)
            from src.core.workspace_service import get_workspace_service
            self._sessions_file = get_workspace_service().get_config_path("sessions.json")

        self._sessions_file.parent.mkdir(parents=True, exist_ok=True)

    # === PROPRIEDADES ===

    @property
    def focused_session(self) -> Optional[Session]:
        """Returns the currently focused session"""
        return self._focused_session

    @property
    def sessions(self) -> List[Session]:
        """Returns all sessions in order"""
        return [self._sessions[sid] for sid in self._session_order if sid in self._sessions]

    @property
    def session_count(self) -> int:
        """Number of sessions"""
        return len(self._sessions)

    # === CREATE/CLOSE SESSIONS ===

    def create_session(self, title: str = None) -> Session:
        """Creates a new session"""
        session_id = str(uuid.uuid4())[:8]

        if title is None:
            title = f"Script {len(self._sessions) + 1}"

        session = Session(session_id=session_id, title=title)

        self._sessions[session_id] = session
        self._session_order.append(session_id)

        self.session_created.emit(session)

        # Focus on new session
        self.focus_session(session_id)

        return session

    def close_session(self, session_id: str) -> bool:
        """Closes a session"""
        if session_id not in self._sessions:
            return False

        session = self._sessions[session_id]

        # Cleanup the session
        session.cleanup()

        # Remove from list
        del self._sessions[session_id]
        self._session_order.remove(session_id)

        # If it was the focused session, focus another
        if self._focused_session and self._focused_session.session_id == session_id:
            self._focused_session = None
            if self._session_order:
                self.focus_session(self._session_order[-1])

        self.session_closed.emit(session_id)

        return True

    def get_session(self, session_id: str) -> Optional[Session]:
        """Gets a session by ID"""
        return self._sessions.get(session_id)

    def get_session_by_index(self, index: int) -> Optional[Session]:
        """Gets a session by index"""
        if 0 <= index < len(self._session_order):
            return self._sessions.get(self._session_order[index])
        return None

    def get_session_index(self, session_id: str) -> int:
        """Gets the index of a session"""
        try:
            return self._session_order.index(session_id)
        except ValueError:
            return -1

    # === FOCO ===

    def focus_session(self, session_id: str) -> bool:
        """Sets the focused session"""
        if session_id not in self._sessions:
            return False

        session = self._sessions[session_id]

        if self._focused_session != session:
            self._focused_session = session
            self.session_focused.emit(session)

        return True

    def focus_session_by_index(self, index: int) -> bool:
        """Focuses session by index"""
        if 0 <= index < len(self._session_order):
            return self.focus_session(self._session_order[index])
        return False

    # === RENOMEAR ===

    def rename_session(self, session_id: str, new_title: str) -> bool:
        """Renames a session"""
        session = self._sessions.get(session_id)
        if session:
            session.title = new_title
            return True
        return False

    # === SERIALIZATION ===

    def save_sessions(self) -> bool:
        """Saves all sessions to disk"""
        try:
            data = {
                "version": 1,
                "focused_session": self._focused_session.session_id if self._focused_session else None,
                "session_order": self._session_order,
                "sessions": {sid: session.serialize() for sid, session in self._sessions.items()},
            }

            with open(self._sessions_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            return True
        except Exception as e:
            logger.error(f"Error saving sessions: {e}")
            return False

    def load_sessions(self, connection_manager=None, reconnect: bool = False) -> bool:
        """Loads sessions from disk.

        By default, saved sessions preserve their connection metadata without
        blocking the UI on synchronous reconnect attempts during startup.
        """
        try:
            if not self._sessions_file.exists():
                # Don't create default session - let UI show empty state
                return True

            with open(self._sessions_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Load sessions
            self._session_order = data.get("session_order", [])

            for session_data in data.get("sessions", {}).values():
                session = Session.deserialize(session_data)
                self._sessions[session.session_id] = session

                # Initialize (reconnect if necessary)
                session.initialize(connection_manager, reconnect=reconnect)

            # Clean up sessions that no longer exist in order
            self._session_order = [sid for sid in self._session_order if sid in self._sessions]

            # Focus on saved session
            focused_id = data.get("focused_session")
            if focused_id and focused_id in self._sessions:
                self.focus_session(focused_id)
            elif self._session_order:
                self.focus_session(self._session_order[0])

            # Don't create default session if none exist - let UI show empty state

            self.sessions_restored.emit()

            return True
        except Exception as e:
            logger.error(f"Error loading sessions: {e}")
            # Don't create default session on error - let UI handle it
            return False

    # === CONNECTION ===

    def set_connection_for_focused(self, connection_name: str, connector):
        """Sets connection for the focused session"""
        if self._focused_session:
            self._focused_session.set_connection(connection_name, connector)

    def clear_connection_for_focused(self):
        """Removes connection from the focused session"""
        if self._focused_session:
            self._focused_session.clear_connection()

    # === CLEANUP ===

    def cleanup_all(self):
        """Cleans up all sessions"""
        for session in self._sessions.values():
            session.cleanup()
        self._sessions.clear()
        self._session_order.clear()
        self._focused_session = None
