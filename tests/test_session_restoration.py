"""
Testes para a restauração de sessão
"""

import pytest
import tempfile
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication

from source.src.core.session import Session
from source.src.ui.main_window import MainWindow


class TestSessionRestoration:
    """Testes para restauração de sessões com file_path e cores"""

    def test_session_serialization_includes_file_path(self):
        """Testa se o file_path é incluído na serialização"""
        # Criar sessão
        session = Session("test_session", "Test Session")
        session.file_path = "C:\\test\\example.sql"
        session.original_file_type = "SQL"
        session._connection_name = "TestDB"
        
        # Serializar
        data = session.serialize()
        
        # Verificar se file_path está na serialização
        assert data['file_path'] == "C:\\test\\example.sql"
        assert data['original_file_type'] == "SQL"
        assert data['connection_name'] == "TestDB"
    
    def test_session_deserialization_restores_file_path(self):
        """Testa se o file_path é restaurado na deserialização"""
        # Dados de sessão com file_path
        data = {
            'session_id': 'test_session',
            'title': 'Test Session',
            'code': 'SELECT * FROM users',
            'blocks': [],
            'connection_name': 'TestDB',
            'file_path': 'C:\\test\\example.sql',
            'original_file_type': 'SQL',
            'created_at': '2024-01-01T00:00:00'
        }
        
        # Deserializar
        session = Session.deserialize(data)
        
        # Verificar se file_path foi restaurado
        assert session.file_path == 'C:\\test\\example.sql'
        assert session.original_file_type == 'SQL'
        assert session._connection_name == 'TestDB'
    
    def test_session_serialization_without_file_path(self):
        """Testa serialização de sessão sem file_path"""
        # Criar sessão sem file_path
        session = Session("test_session", "Test Session")
        
        # Serializar
        data = session.serialize()
        
        # Verificar se file_path é None na serialização 
        assert data.get('file_path') is None
        assert data.get('original_file_type') is None
    
    def test_session_deserialization_handles_missing_file_path(self):
        """Testa deserialização quando file_path não existe nos dados"""
        # Dados de sessão sem file_path
        data = {
            'session_id': 'test_session',
            'title': 'Test Session',
            'code': 'print("Hello")',
            'blocks': []
        }
        
        # Deserializar
        session = Session.deserialize(data)
        
        # Verificar se file_path é None
        assert session.file_path is None
        assert session.original_file_type is None

    @pytest.fixture
    def app(self):
        """Fixture para aplicação Qt"""
        from PyQt6.QtWidgets import QApplication
        import sys
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        yield app

    @patch('src.database.ConnectionManager.get_connection_config')
    def test_create_session_widget_sets_file_path(self, mock_get_config, app):
        """Testa se _create_session_widget define file_path no widget"""
        # Mock da configuração de conexão
        mock_get_config.return_value = {
            'color': '#00FF00',
            'host': 'localhost'
        }
        
        # Criar main window
        main_window = MainWindow()
        
        # Criar sessão com file_path
        session = Session("test_session", "Test Session")
        session.file_path = "C:\\test\\example.sql"
        session.original_file_type = "SQL"
        session._connection_name = "TestDB"
        
        # Criar widget da sessão
        widget = main_window._create_session_widget(session)
        
        # Verificar se file_path foi definido no widget
        assert hasattr(widget, 'file_path')
        assert widget.file_path == "C:\\test\\example.sql"

    @patch('src.database.ConnectionManager.get_connection_config')
    def test_create_session_widget_applies_tab_color(self, mock_get_config, app):
        """Testa se _create_session_widget aplica cor da aba baseada na conexão"""
        # Mock da configuração de conexão com cor
        mock_get_config.return_value = {
            'color': '#FF5733',
            'host': 'localhost'
        }
        
        # Criar main window
        main_window = MainWindow()
        
        # Mock do método set_tab_connection_color
        main_window.session_tabs.set_tab_connection_color = MagicMock()
        
        # Criar sessão com conexão
        session = Session("test_session", "Test Session")
        session._connection_name = "TestDB"
        
        # Criar widget da sessão
        widget = main_window._create_session_widget(session)
        
        # Verificar se get_connection_config foi chamado com a conexão correta
        mock_get_config.assert_called_with("TestDB")
        
        # Verificar se o método de aplicar cor foi chamado
        main_window.session_tabs.set_tab_connection_color.assert_called_with(0, '#FF5733')

    def test_create_session_widget_without_connection_no_color(self, app):
        """Testa se _create_session_widget não aplica cor quando não há conexão"""
        # Criar main window
        main_window = MainWindow()
        
        # Mock do método set_tab_connection_color
        main_window.session_tabs.set_tab_connection_color = MagicMock()
        
        # Criar sessão sem conexão
        session = Session("test_session", "Test Session")
        
        # Criar widget da sessão
        widget = main_window._create_session_widget(session)
        
        # Verificar se o método de aplicar cor NÃO foi chamado
        main_window.session_tabs.set_tab_connection_color.assert_not_called()

    def test_session_complete_workflow(self):
        """Testa fluxo completo de serialização -> deserialização -> criação de widget"""
        # Criar sessão original
        original_session = Session("test_session", "Análise SQL")
        original_session.file_path = "C:\\projetos\\analise.sql"
        original_session.original_file_type = "SQL"
        original_session._connection_name = "ProductionDB"
        original_session._code = "SELECT COUNT(*) FROM users"
        
        # Serializar
        data = original_session.serialize()
        
        # Deserializar
        restored_session = Session.deserialize(data)
        
        # Verificar se todos os dados foram preservados
        assert restored_session.session_id == original_session.session_id
        assert restored_session.title == original_session.title
        assert restored_session.file_path == original_session.file_path
        assert restored_session.original_file_type == original_session.original_file_type
        assert restored_session._connection_name == original_session._connection_name
        assert restored_session._code == original_session._code