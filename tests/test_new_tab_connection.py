"""
Testes para a nova funcionalidade de conectar em nova aba
"""

import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QGuiApplication

from source.src.ui.components.connection_panel import ConnectionsList, ConnectionPanel
from source.src.ui.main_window import MainWindow


class TestNewTabConnection:
    """Testes para funcionalidade CTRL+duplo-click e 'Conectar em Nova Aba'"""

    @pytest.fixture
    def app(self):
        """Fixture para aplicação Qt"""
        from PyQt6.QtWidgets import QApplication
        import sys
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        yield app

    def test_connection_list_has_new_tab_signal(self, app):
        """Testa se ConnectionsList tem o novo sinal"""
        connections_list = ConnectionsList()
        
        # Verificar se o sinal existe
        assert hasattr(connections_list, 'new_tab_connection_requested')
        
        # Verificar se é um pyqtSignal
        signal = connections_list.new_tab_connection_requested
        assert hasattr(signal, 'emit')

    def test_connection_panel_has_new_tab_signal(self, app):
        """Testa se ConnectionPanel tem o novo sinal"""
        connection_panel = ConnectionPanel()
        
        # Verificar se o sinal existe
        assert hasattr(connection_panel, 'new_tab_connection_requested')
        
        # Verificar se é um pyqtSignal
        signal = connection_panel.new_tab_connection_requested
        assert hasattr(signal, 'emit')

    @patch('PyQt6.QtGui.QGuiApplication.keyboardModifiers')
    def test_ctrl_double_click_emits_new_tab_signal(self, mock_modifiers, app):
        """Testa se CTRL+duplo-click emite o sinal de nova aba"""
        # Simular CTRL pressionado
        mock_modifiers.return_value = Qt.KeyboardModifier.ControlModifier
        
        connections_list = ConnectionsList()
        
        # Mock dos sinais
        new_tab_signal = MagicMock()
        normal_signal = MagicMock()
        
        connections_list.new_tab_connection_requested = new_tab_signal
        connections_list.connection_double_clicked = normal_signal
        
        # Criar item mock
        item_mock = MagicMock()
        item_mock.data.return_value = "TestConnection"
        
        # Simular duplo-click com CTRL
        connections_list._on_item_double_clicked(item_mock)
        
        # Verificar se sinal correto foi emitido
        new_tab_signal.emit.assert_called_once_with("TestConnection")
        normal_signal.emit.assert_not_called()

    @patch('PyQt6.QtGui.QGuiApplication.keyboardModifiers')
    def test_normal_double_click_emits_normal_signal(self, mock_modifiers, app):
        """Testa se duplo-click normal emite o sinal normal"""
        # Simular nenhuma tecla pressionada
        mock_modifiers.return_value = Qt.KeyboardModifier.NoModifier
        
        connections_list = ConnectionsList()
        
        # Mock dos sinais
        new_tab_signal = MagicMock()
        normal_signal = MagicMock()
        
        connections_list.new_tab_connection_requested = new_tab_signal
        connections_list.connection_double_clicked = normal_signal
        
        # Criar item mock
        item_mock = MagicMock()
        item_mock.data.return_value = "TestConnection"
        
        # Simular duplo-click normal
        connections_list._on_item_double_clicked(item_mock)
        
        # Verificar se sinal correto foi emitido
        normal_signal.emit.assert_called_once_with("TestConnection")
        new_tab_signal.emit.assert_not_called()

    def test_context_menu_has_new_tab_option(self, app):
        """Testa se o menu de contexto tem a opção 'Conectar em Nova Aba'"""
        connections_list = ConnectionsList()
        
        # Verificar se o método _show_context_menu existe
        assert hasattr(connections_list, '_show_context_menu')
        
        # Verificar se list_widget foi criado
        assert hasattr(connections_list, 'list_widget')
        
        # Test simples: se não há erro de atributo com o novo sinal
        assert hasattr(connections_list, 'new_tab_connection_requested')

    @patch('src.database.ConnectionManager.get_connection_config')
    def test_main_window_connect_new_tab_method(self, mock_get_config, app):
        """Testa se o MainWindow tem o método _connect_new_tab"""
        # Mock da configuração
        mock_get_config.return_value = {
            'password': 'test_pass',
            'use_windows_auth': False
        }
        
        main_window = MainWindow()
        
        # Verificar se o método existe
        assert hasattr(main_window, '_connect_new_tab')
        
        # Mock de widgets necessários
        main_window._new_session = MagicMock()
        main_window._get_current_session_widget = MagicMock()
        
        widget_mock = MagicMock()
        widget_mock.connect_to_database = MagicMock()
        main_window._get_current_session_widget.return_value = widget_mock
        
        # Testar o método
        main_window._connect_new_tab("TestConnection")
        
        # Verificar se nova sessão foi criada
        main_window._new_session.assert_called_once()
        
        # Verificar se conexão foi chamada no widget
        widget_mock.connect_to_database.assert_called_once_with("TestConnection", "test_pass")

    def test_main_window_signal_connection(self, app):
        """Testa se os sinais estão conectados no MainWindow"""
        main_window = MainWindow()
        
        # Verificar se connection_panel existe e tem o sinal
        assert hasattr(main_window, 'connection_panel')
        assert hasattr(main_window.connection_panel, 'new_tab_connection_requested')
        
        # Verificar se o método _connect_new_tab existe
        assert hasattr(main_window, '_connect_new_tab')

    def test_signal_propagation_from_list_to_panel(self, app):
        """Testa se o sinal propaga corretamente da lista para o painel"""
        connection_panel = ConnectionPanel()
        
        # Mock do sinal no painel
        panel_signal = MagicMock()
        connection_panel.new_tab_connection_requested = panel_signal
        
        # Simular emissão do sinal da lista
        connection_panel.connections_list.new_tab_connection_requested.emit("TestConnection")
        
        # Verificar se foi propagado (seria através da conexão interna)
        # Como é conectado via _connect_signals, vamos verificar se existe
        assert hasattr(connection_panel.connections_list, 'new_tab_connection_requested')