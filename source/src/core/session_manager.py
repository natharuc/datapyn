"""
SessionManager - Gerenciador central de sessões

Responsável por:
- Criar/destruir sessões
- Manter a sessão focada
- Serializar/deserializar todas as sessões
- Notificar mudanças de foco
"""

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from .session import Session


class SessionManager(QObject):
    """
    Gerenciador central de todas as sessões.

    Mantém controle de qual sessão está focada e
    gerencia o ciclo de vida das sessões.
    """

    # Sinais
    session_created = pyqtSignal(Session)
    session_closed = pyqtSignal(str)  # session_id
    session_focused = pyqtSignal(Session)  # nova sessão focada
    sessions_restored = pyqtSignal()  # quando sessões são restauradas do disco

    def __init__(self, workspace_path: Optional[Path] = None):
        super().__init__()

        self._sessions: Dict[str, Session] = {}
        self._focused_session: Optional[Session] = None
        self._session_order: List[str] = []  # Ordem das sessões (para tabs)

        # Caminho para salvar sessões
        if workspace_path:
            self._sessions_file = workspace_path / "sessions.json"
        else:
            self._sessions_file = Path.home() / ".datapyn" / "sessions.json"

        self._sessions_file.parent.mkdir(parents=True, exist_ok=True)

    # === PROPRIEDADES ===

    @property
    def focused_session(self) -> Optional[Session]:
        """Retorna a sessão atualmente focada"""
        return self._focused_session

    @property
    def sessions(self) -> List[Session]:
        """Retorna todas as sessões na ordem"""
        return [self._sessions[sid] for sid in self._session_order if sid in self._sessions]

    @property
    def session_count(self) -> int:
        """Número de sessões"""
        return len(self._sessions)

    # === CRIAR/FECHAR SESSÕES ===

    def create_session(self, title: str = None) -> Session:
        """Cria uma nova sessão"""
        session_id = str(uuid.uuid4())[:8]

        if title is None:
            title = f"Script {len(self._sessions) + 1}"

        session = Session(session_id=session_id, title=title)

        self._sessions[session_id] = session
        self._session_order.append(session_id)

        self.session_created.emit(session)

        # Focar na nova sessão
        self.focus_session(session_id)

        return session

    def close_session(self, session_id: str) -> bool:
        """Fecha uma sessão"""
        if session_id not in self._sessions:
            return False

        session = self._sessions[session_id]

        # Cleanup da sessão
        session.cleanup()

        # Remover da lista
        del self._sessions[session_id]
        self._session_order.remove(session_id)

        # Se era a sessão focada, focar em outra
        if self._focused_session and self._focused_session.session_id == session_id:
            self._focused_session = None
            if self._session_order:
                self.focus_session(self._session_order[-1])

        self.session_closed.emit(session_id)

        return True

    def get_session(self, session_id: str) -> Optional[Session]:
        """Obtém uma sessão pelo ID"""
        return self._sessions.get(session_id)

    def get_session_by_index(self, index: int) -> Optional[Session]:
        """Obtém uma sessão pelo índice"""
        if 0 <= index < len(self._session_order):
            return self._sessions.get(self._session_order[index])
        return None

    def get_session_index(self, session_id: str) -> int:
        """Obtém o índice de uma sessão"""
        try:
            return self._session_order.index(session_id)
        except ValueError:
            return -1

    # === FOCO ===

    def focus_session(self, session_id: str) -> bool:
        """Define a sessão focada"""
        if session_id not in self._sessions:
            return False

        session = self._sessions[session_id]

        if self._focused_session != session:
            self._focused_session = session
            self.session_focused.emit(session)

        return True

    def focus_session_by_index(self, index: int) -> bool:
        """Foca sessão pelo índice"""
        if 0 <= index < len(self._session_order):
            return self.focus_session(self._session_order[index])
        return False

    # === RENOMEAR ===

    def rename_session(self, session_id: str, new_title: str) -> bool:
        """Renomeia uma sessão"""
        session = self._sessions.get(session_id)
        if session:
            session.title = new_title
            return True
        return False

    # === SERIALIZAÇÃO ===

    def save_sessions(self) -> bool:
        """Salva todas as sessões no disco"""
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
            print(f"Erro ao salvar sessões: {e}")
            return False

    def load_sessions(self, connection_manager=None) -> bool:
        """Carrega sessões do disco"""
        try:
            if not self._sessions_file.exists():
                # Não criar sessão padrão - deixar UI mostrar estado vazio
                return True

            with open(self._sessions_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Carregar sessões
            self._session_order = data.get("session_order", [])

            for session_data in data.get("sessions", {}).values():
                session = Session.deserialize(session_data)
                self._sessions[session.session_id] = session

                # Inicializar (reconectar se necessário)
                session.initialize(connection_manager)

            # Limpar sessões que não existem mais na ordem
            self._session_order = [sid for sid in self._session_order if sid in self._sessions]

            # Focar na sessão salva
            focused_id = data.get("focused_session")
            if focused_id and focused_id in self._sessions:
                self.focus_session(focused_id)
            elif self._session_order:
                self.focus_session(self._session_order[0])

            # Não criar sessão padrão se não houver - deixar UI mostrar estado vazio

            self.sessions_restored.emit()

            return True
        except Exception as e:
            print(f"Erro ao carregar sessões: {e}")
            # Não criar sessão padrão em caso de erro - deixar UI lidar com isso
            return False

    # === CONEXÃO ===

    def set_connection_for_focused(self, connection_name: str, connector):
        """Define conexão para a sessão focada"""
        if self._focused_session:
            self._focused_session.set_connection(connection_name, connector)

    def clear_connection_for_focused(self):
        """Remove conexão da sessão focada"""
        if self._focused_session:
            self._focused_session.clear_connection()

    # === CLEANUP ===

    def cleanup_all(self):
        """Limpa todas as sessões"""
        for session in self._sessions.values():
            session.cleanup()
        self._sessions.clear()
        self._session_order.clear()
        self._focused_session = None
