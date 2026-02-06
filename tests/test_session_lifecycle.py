"""
Testes para SessionLifecycleService

Cobre: criacao, fechamento, troca de sessao,
estado vazio, transicoes de estado.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from src.services.session_lifecycle_service import SessionLifecycleService, ISessionHost


class MockHost:
    """Mock que implementa ISessionHost"""
    def __init__(self):
        self.created_panels = []
        self.removed_panels = []
        self.switched_panels = []
        self.panels_hidden = False
        self.panels_shown = False
    
    def create_session_panels(self, session_id):
        self.created_panels.append(session_id)
    
    def remove_session_panels(self, session_id):
        self.removed_panels.append(session_id)
    
    def switch_session_panels(self, session_id):
        self.switched_panels.append(session_id)
    
    def hide_all_panels(self):
        self.panels_hidden = True
    
    def show_all_panels(self):
        self.panels_shown = True


class MockSessionManager:
    """Mock do SessionManager"""
    def __init__(self):
        self._sessions = {}
        self._counter = 0
        self._focused = None
    
    def create_session(self, title=None):
        self._counter += 1
        session = MagicMock()
        session.session_id = f"session_{self._counter}"
        session.title = title or f"Session {self._counter}"
        self._sessions[session.session_id] = session
        return session
    
    def close_session(self, session_id):
        self._sessions.pop(session_id, None)
    
    def focus_session(self, session_id):
        self._focused = session_id


class TestSessionLifecycleServiceCreation:
    """Testes de criacao de sessao"""
    
    def test_create_session_basic(self):
        """Criar sessao basica sem widget factory"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        session, widget = service.create_session()
        
        assert session is not None
        assert session.session_id == "session_1"
        assert widget is None
        assert "session_1" in host.created_panels
    
    def test_create_session_with_factory(self):
        """Criar sessao com widget factory"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        mock_widget = MagicMock()
        factory = MagicMock(return_value=mock_widget)
        
        session, widget = service.create_session(widget_factory=factory)
        
        assert session is not None
        assert widget is mock_widget
        factory.assert_called_once_with(session)
        assert service.get_widget(session.session_id) is mock_widget
    
    def test_create_session_with_title(self):
        """Criar sessao com titulo customizado"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        session, _ = service.create_session(title="Minha Query")
        assert session.title == "Minha Query"
    
    def test_create_session_guard_against_duplicate(self):
        """Guard contra criacao duplicada"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        
        # Forcar flag de criacao
        service._is_creating = True
        session, widget = service.create_session()
        
        assert session is None
        assert widget is None
    
    def test_create_session_emits_first_session_signal(self, qtbot):
        """Sinal first_session_created emitido na primeira sessao"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        with qtbot.waitSignal(service.first_session_created, timeout=1000):
            service.create_session()
    
    def test_create_session_does_not_emit_first_on_second(self, qtbot):
        """Sinal first_session_created NAO emitido na segunda sessao"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        # Primeira sessao
        service.create_session(widget_factory=lambda s: MagicMock())
        
        # Segunda sessao - nao deve emitir first_session_created
        signals_received = []
        service.first_session_created.connect(lambda: signals_received.append(True))
        service.create_session(widget_factory=lambda s: MagicMock())
        
        assert len(signals_received) == 0
    
    def test_create_session_panels_created(self):
        """Paineis criados pelo host ao criar sessao"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        service.create_session()
        assert len(host.created_panels) == 1
        
        service.create_session()
        assert len(host.created_panels) == 2


class TestSessionLifecycleServiceClosing:
    """Testes de fechamento de sessao"""
    
    def test_close_session_basic(self):
        """Fechar sessao remove paineis e widget"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        session, _ = service.create_session(widget_factory=lambda s: MagicMock())
        sid = session.session_id
        
        result = service.close_session(sid)
        
        assert result is True
        assert sid in host.removed_panels
        assert service.get_widget(sid) is None
    
    def test_close_session_calls_cleanup(self):
        """Cleanup callback chamado ao fechar"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        mock_widget = MagicMock()
        session, _ = service.create_session(widget_factory=lambda s: mock_widget)
        
        cleanup = MagicMock()
        service.close_session(session.session_id, cleanup_callback=cleanup)
        
        cleanup.assert_called_once_with(mock_widget)
    
    def test_close_all_hides_panels(self):
        """Fechar todas as sessoes esconde paineis"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        service.create_session(widget_factory=lambda s: MagicMock())
        service.create_session(widget_factory=lambda s: MagicMock())
        
        assert service.session_count == 2
        service.close_all_sessions()
        
        assert service.session_count == 0
        assert host.panels_hidden is True
    
    def test_close_last_session_emits_all_closed(self, qtbot):
        """Sinal all_sessions_closed emitido ao fechar ultima sessao"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        session, _ = service.create_session(widget_factory=lambda s: MagicMock())
        
        with qtbot.waitSignal(service.all_sessions_closed, timeout=1000):
            service.close_session(session.session_id)
    
    def test_close_session_guard(self):
        """Guard contra fechamento duplicado"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        
        service._is_closing = True
        result = service.close_session("fake_id")
        assert result is False


class TestSessionLifecycleServiceSwitching:
    """Testes de troca de sessao"""
    
    def test_switch_to_session(self):
        """Trocar para sessao existente"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        s1, _ = service.create_session(widget_factory=lambda s: MagicMock())
        s2, _ = service.create_session(widget_factory=lambda s: MagicMock())
        
        service.switch_to_session(s1.session_id)
        
        assert s1.session_id in host.switched_panels
        assert manager._focused == s1.session_id
    
    def test_switch_to_nonexistent_session(self):
        """Trocar para sessao inexistente nao faz nada"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        service.switch_to_session("fake_id")
        assert len(host.switched_panels) == 0


class TestSessionLifecycleServiceState:
    """Testes de estado do servico"""
    
    def test_has_sessions(self):
        """Verifica propriedade has_sessions"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        assert service.has_sessions is False
        
        service.create_session(widget_factory=lambda s: MagicMock())
        assert service.has_sessions is True
    
    def test_session_count(self):
        """Verifica contagem de sessoes"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        assert service.session_count == 0
        
        s1, _ = service.create_session(widget_factory=lambda s: MagicMock())
        assert service.session_count == 1
        
        s2, _ = service.create_session(widget_factory=lambda s: MagicMock())
        assert service.session_count == 2
        
        service.close_session(s1.session_id)
        assert service.session_count == 1
    
    def test_all_widgets(self):
        """Verifica all_widgets retorna copia"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        host = MockHost()
        service.set_host(host)
        
        w1 = MagicMock()
        w2 = MagicMock()
        service.create_session(widget_factory=lambda s: w1)
        service.create_session(widget_factory=lambda s: w2)
        
        widgets = service.all_widgets
        assert len(widgets) == 2
        
        # Deve ser copia, nao referencia
        widgets.clear()
        assert service.session_count == 2
    
    def test_register_widget(self):
        """Registrar widget externamente (restauracao)"""
        manager = MockSessionManager()
        service = SessionLifecycleService(manager)
        
        widget = MagicMock()
        service.register_widget("ext_session", widget)
        
        assert service.get_widget("ext_session") is widget
        assert service.session_count == 1
