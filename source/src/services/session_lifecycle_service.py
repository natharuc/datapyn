"""
SessionLifecycleService - Servico centralizado para ciclo de vida de sessoes

Responsavel por:
- Criar sessoes (nova, a partir de arquivo, duplicata)
- Fechar sessoes (individual, todas, outras)
- Garantir que paineis e widgets sejam criados/removidos consistentemente
- Gerenciar transicao entre estado vazio e estado com sessoes

Principio: Toda criacao/destruicao de sessao DEVE passar por este servico.
Isso evita bugs onde paineis, widgets ou estado ficam inconsistentes.
"""
from typing import Optional, Callable, Dict, List, Any, Protocol, runtime_checkable
from PyQt6.QtCore import QObject, pyqtSignal


@runtime_checkable
class ISessionHost(Protocol):
    """Interface que o host (MainWindow) deve implementar para o servico funcionar."""
    
    def create_session_panels(self, session_id: str) -> None:
        """Cria paineis (Results, Output, Variables) para a sessao."""
        ...
    
    def remove_session_panels(self, session_id: str) -> None:
        """Remove paineis de uma sessao."""
        ...
    
    def switch_session_panels(self, session_id: str) -> None:
        """Troca os stacks para exibir os paineis da sessao ativa."""
        ...
    
    def hide_all_panels(self) -> None:
        """Esconde todos os paineis inferiores (estado vazio)."""
        ...
    
    def show_all_panels(self) -> None:
        """Mostra todos os paineis inferiores."""
        ...


class SessionLifecycleService(QObject):
    """
    Servico centralizado para ciclo de vida de sessoes.
    
    Centraliza criacao, destruicao e troca de sessoes para garantir
    consistencia entre SessionManager, SessionTabs, paineis e widgets.
    """
    
    # Sinais emitidos pelo servico
    session_created = pyqtSignal(str)       # session_id
    session_closed = pyqtSignal(str)        # session_id
    session_switched = pyqtSignal(str)      # session_id
    all_sessions_closed = pyqtSignal()      # quando nenhuma sessao resta
    first_session_created = pyqtSignal()    # quando sai do estado vazio
    
    def __init__(self, session_manager, parent=None):
        super().__init__(parent)
        self._session_manager = session_manager
        self._host: Optional[ISessionHost] = None
        self._is_creating = False
        self._is_closing = False
        self._session_widgets: Dict[str, Any] = {}
    
    def set_host(self, host: ISessionHost):
        """Define o host (MainWindow) que implementa ISessionHost."""
        self._host = host
    
    @property
    def is_creating(self) -> bool:
        return self._is_creating
    
    @property
    def is_closing(self) -> bool:
        return self._is_closing
    
    @property
    def has_sessions(self) -> bool:
        """Retorna True se existe pelo menos uma sessao ativa."""
        return len(self._session_widgets) > 0
    
    @property
    def session_count(self) -> int:
        return len(self._session_widgets)
    
    def get_widget(self, session_id: str):
        """Retorna o widget associado a uma sessao."""
        return self._session_widgets.get(session_id)
    
    @property
    def all_widgets(self) -> Dict[str, Any]:
        return dict(self._session_widgets)
    
    def register_widget(self, session_id: str, widget):
        """Registra um widget criado externamente (usado durante restauracao)."""
        self._session_widgets[session_id] = widget
    
    def create_session(self, title: str = None, 
                       widget_factory: Callable = None) -> tuple:
        """
        Cria uma nova sessao com todos os componentes necessarios.
        
        Args:
            title: Titulo da sessao (opcional)
            widget_factory: Funcao que recebe Session e retorna widget
            
        Returns:
            Tupla (session, widget) ou (session, None) se nao tem factory
        """
        if self._is_creating:
            return None, None
        
        self._is_creating = True
        was_empty = not self.has_sessions
        
        try:
            # Criar sessao no manager
            session = self._session_manager.create_session(title=title)
            
            # Criar paineis para a sessao
            if self._host:
                self._host.create_session_panels(session.session_id)
            
            widget = None
            if widget_factory:
                widget = widget_factory(session)
                self._session_widgets[session.session_id] = widget
            
            # Sinalizar
            if was_empty:
                self.first_session_created.emit()
            
            self.session_created.emit(session.session_id)
            return session, widget
            
        finally:
            self._is_creating = False
    
    def close_session(self, session_id: str, 
                      cleanup_callback: Callable = None) -> bool:
        """
        Fecha uma sessao e remove todos os componentes.
        
        Args:
            session_id: ID da sessao
            cleanup_callback: Funcao chamada antes de remover (para cleanup de widget)
            
        Returns:
            True se fechou com sucesso
        """
        if self._is_closing:
            return False
        
        self._is_closing = True
        
        try:
            # Cleanup do widget
            widget = self._session_widgets.get(session_id)
            if widget and cleanup_callback:
                cleanup_callback(widget)
            
            # Fechar sessao no manager
            self._session_manager.close_session(session_id)
            
            # Remover paineis
            if self._host:
                self._host.remove_session_panels(session_id)
            
            # Remover widget do registro
            self._session_widgets.pop(session_id, None)
            
            # Sinalizar
            self.session_closed.emit(session_id)
            
            if not self.has_sessions:
                # Esconder paineis quando nao ha sessoes
                if self._host:
                    self._host.hide_all_panels()
                self.all_sessions_closed.emit()
            
            return True
            
        finally:
            self._is_closing = False
    
    def close_all_sessions(self, cleanup_callback: Callable = None):
        """Fecha todas as sessoes."""
        session_ids = list(self._session_widgets.keys())
        for sid in session_ids:
            self.close_session(sid, cleanup_callback)
    
    def switch_to_session(self, session_id: str):
        """Troca para uma sessao ativa."""
        if session_id not in self._session_widgets:
            return
        
        self._session_manager.focus_session(session_id)
        
        if self._host:
            self._host.switch_session_panels(session_id)
        
        self.session_switched.emit(session_id)
