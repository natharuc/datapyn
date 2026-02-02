"""
Testes automatizados de UI para DataPyn

Usa pytest-qt para simular interações do usuário:
- Abrir janela
- Criar/fechar abas
- Clicar em conexões
- Executar queries
- Verificar status bar
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest
import tempfile
import os

# Fixtures


@pytest.fixture(scope='session')
def qapp():
    """Cria QApplication uma vez para toda a sessão de testes"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def mock_all_dialogs():
    """Mock automático de TODOS os diálogos do QMessageBox para evitar interação manual"""
    with patch.object(QMessageBox, 'warning', return_value=QMessageBox.StandardButton.Ok), \
         patch.object(QMessageBox, 'information', return_value=QMessageBox.StandardButton.Ok), \
         patch.object(QMessageBox, 'critical', return_value=QMessageBox.StandardButton.Ok), \
         patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
         patch.object(QMessageBox, 'about', return_value=None):
        yield


@pytest.fixture
def main_window(qapp, qtbot, tmp_path):
    """Cria MainWindow para testes - agora usa apenas QScintilla"""
    from src.ui.main_window import MainWindow
    
    # Mock do ConnectionManager para não depender de banco real
    with patch('src.ui.main_window.ConnectionManager') as MockConnManager, \
         patch('src.core.session_manager.Path.home', return_value=tmp_path):
        mock_conn_manager = MockConnManager.return_value
        mock_conn_manager.get_saved_connections.return_value = ['Test Connection']
        mock_conn_manager.get_connection_config.return_value = {
            'db_type': 'mysql',
            'host': 'localhost',
            'port': 3306,
            'database': 'test',
            'username': 'user',
            'use_windows_auth': False
        }
        mock_conn_manager.get_connections_by_group.return_value = {
            'Test Connection': {'db_type': 'mysql', 'group': 'Desenvolvimento'}
        }
        mock_conn_manager.get_groups.return_value = {'Desenvolvimento': {'color': '#007acc'}}
        mock_conn_manager.active_connection = None
        mock_conn_manager.get_active_connection.return_value = None
        mock_conn_manager.get_connection.return_value = None
        mock_conn_manager.mark_connection_used = Mock()
        mock_conn_manager.create_connection = Mock()
        
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        
        # Garantir que há pelo menos uma sessão para os testes
        if not window._get_current_session_widget():
            window._new_session()
            qtbot.wait(100)  # Esperar UI atualizar
        
        yield window
        
        window.close()


# === TESTES DE INICIALIZAÇÃO ===


class TestMainWindowInit:
    """Testes de inicialização da janela principal"""
    
    def test_window_opens(self, main_window):
        """Janela deve abrir sem erros"""
        assert main_window.isVisible()
    
    def test_window_has_title(self, main_window):
        """Janela deve ter título"""
        assert "DataPyn" in main_window.windowTitle()
    
    def test_session_tabs_exist(self, main_window):
        """Deve ter widget de abas de sessão"""
        assert hasattr(main_window, 'session_tabs')
        assert main_window.session_tabs is not None
    
    def test_at_least_one_session(self, main_window):
        """Deve ter pelo menos uma sessão criada"""
        # Conta SessionWidgets (exclui aba +)
        from src.ui.components.session_widget import SessionWidget
        session_count = sum(
            1 for i in range(main_window.session_tabs.count())
            if isinstance(main_window.session_tabs.widget(i), SessionWidget)
        )
        assert session_count >= 1
    
    def test_statusbar_exists(self, main_window):
        """Deve ter status bar"""
        assert hasattr(main_window, 'statusbar')
        assert main_window.statusbar is not None
    
    def test_connection_dock_exists(self, main_window):
        """Deve ter dock de conexões"""
        assert hasattr(main_window, 'connections_dock')
        assert main_window.connections_dock is not None


# === TESTES DE SESSÕES ===


class TestSessionManagement:
    """Testes de gerenciamento de sessões"""
    
    def test_session_manager_exists(self, main_window):
        """Deve ter SessionManager"""
        assert hasattr(main_window, 'session_manager')
        assert main_window.session_manager is not None
    
    def test_create_new_session(self, main_window, qtbot):
        """Deve criar nova sessão ao chamar _new_session"""
        from src.ui.components.session_widget import SessionWidget
        
        initial_count = sum(
            1 for i in range(main_window.session_tabs.count())
            if isinstance(main_window.session_tabs.widget(i), SessionWidget)
        )
        
        main_window._new_session()
        
        new_count = sum(
            1 for i in range(main_window.session_tabs.count())
            if isinstance(main_window.session_tabs.widget(i), SessionWidget)
        )
        
        assert new_count == initial_count + 1
    
    def test_session_has_editor(self, main_window):
        """Cada sessão deve ter um editor"""
        widget = main_window._get_current_session_widget()
        assert widget is not None
        assert hasattr(widget, 'editor')
        assert widget.editor is not None
    
    def test_session_has_results_viewer(self, main_window):
        """Cada sessão deve ter visualizador de resultados"""
        widget = main_window._get_current_session_widget()
        assert widget is not None
        assert hasattr(widget, 'results_viewer')
    
    def test_session_has_output(self, main_window):
        """Cada sessão deve ter output/logs"""
        widget = main_window._get_current_session_widget()
        assert widget is not None
        assert hasattr(widget, 'output_text')
    
    def test_session_has_variables_viewer(self, main_window):
        """Cada sessão deve ter visualizador de variáveis"""
        widget = main_window._get_current_session_widget()
        assert widget is not None
        assert hasattr(widget, 'variables_viewer')


# === TESTES DE CONEXÃO ===


class TestConnectionManagement:
    """Testes de gerenciamento de conexões"""
    
    def test_connection_manager_exists(self, main_window):
        """Deve ter ConnectionManager para configurações"""
        assert hasattr(main_window, 'connection_manager')
    
    def test_session_widget_has_own_connection_manager(self, main_window, qtbot):
        """Cada SessionWidget deve ter seu próprio ConnectionManager"""
        widget = main_window.session_tabs.currentWidget()
        assert hasattr(widget, 'connection_manager')
        assert widget.connection_manager is not None
        # Deve ser instância diferente do MainWindow
        assert widget.connection_manager is not main_window.connection_manager
    
    def test_session_widget_can_connect(self, main_window, qtbot):
        """SessionWidget deve poder conectar independentemente (teste simplificado)"""
        widget = main_window.session_tabs.currentWidget()
        
        # Verificar que tem ConnectionManager isolado
        assert hasattr(widget, 'connection_manager')
        assert widget.connection_manager is not main_window.connection_manager
        
        # Verificar que método connect_to_database existe
        assert hasattr(widget, 'connect_to_database')
        assert callable(widget.connect_to_database)
        
        # Testar conexão simulada diretamente no Session
        mock_connector = Mock()
        mock_connector.is_connected = True
        
        widget.session.set_connection('Test Connection', mock_connector)
        
        # Verificar que sessão tem a conexão
        assert widget.session.is_connected
        assert widget.session.connection_name == 'Test Connection'
    
    def test_session_widget_connection_error_isolated(self, main_window, qtbot):
        """Erro de conexão em uma aba não deve afetar outras"""
        widget1 = main_window.session_tabs.currentWidget()
        
        # Criar segunda aba
        main_window._new_session()
        widget2 = main_window.session_tabs.currentWidget()
        
        # Mock falha na conexão do widget1
        widget1.connection_manager.get_connection_config = Mock(side_effect=Exception("Erro de teste"))
        
        # Tentar conectar widget1 - deve falhar silenciosamente (erro no output da aba)
        widget1.connect_to_database('Bad Connection')
        
        # widget2 não deve ser afetado
        assert not widget2.session.is_connected
        assert widget2.connection_manager is not widget1.connection_manager
    
    def test_session_widget_disconnect_isolated(self, main_window, qtbot):
        """Desconectar uma aba não afeta outras"""
        widget1 = main_window.session_tabs.currentWidget()
        
        # Criar e conectar segunda aba
        main_window._new_session()
        widget2 = main_window.session_tabs.currentWidget()
        
        # Mock conexões
        mock_conn1 = Mock()
        mock_conn1.is_connected = True
        mock_conn1.disconnect = Mock()
        
        mock_conn2 = Mock()
        mock_conn2.is_connected = True
        mock_conn2.disconnect = Mock()
        
        widget1.session._connector = mock_conn1
        widget1.session._connection_name = 'Conn1'
        
        widget2.session._connector = mock_conn2
        widget2.session._connection_name = 'Conn2'
        
        # Mock close_all para não afetar os mocks
        widget1.connection_manager.close_all = Mock()
        
        # Desconectar apenas widget1
        widget1.disconnect_database()
        
        # widget1 desconectado, widget2 continua conectado
        assert not widget1.session.is_connected
        assert widget2.session.is_connected


# === TESTES DE EDITOR ===


class TestEditorFunctionality:
    """Testes de funcionalidade do editor"""
    
    def test_get_current_editor(self, main_window):
        """Deve retornar editor da sessão atual"""
        editor = main_window._get_current_editor()
        assert editor is not None
    
    def test_editor_accepts_text(self, main_window, qtbot):
        """Editor deve aceitar texto"""
        editor = main_window._get_current_editor()
        if editor:
            editor.setText("SELECT * FROM test")
            assert "SELECT" in editor.text()
    
    def test_session_widget_sync_to_session(self, main_window, qtbot):
        """SessionWidget deve sincronizar blocos para Session"""
        widget = main_window._get_current_session_widget()
        if widget:
            # Pega o primeiro bloco e define código
            blocks = widget.editor.get_blocks()
            if blocks:
                blocks[0].set_language('sql')
                blocks[0].set_code('SELECT 1')
            widget.sync_to_session()
            # Verifica se os blocos foram salvos
            assert len(widget.session.blocks) >= 1
            assert widget.session.blocks[0]['code'] == 'SELECT 1'
            assert widget.session.blocks[0]['language'] == 'sql'


# === TESTES DE TEMA ===


class TestThemeManagement:
    """Testes de gerenciamento de tema - tema fixo em 'dark'"""
    
    def test_theme_manager_exists(self, main_window):
        """Deve ter ThemeManager"""
        assert hasattr(main_window, 'theme_manager')
    
    def test_current_theme_is_dark(self, main_window):
        """Tema atual deve ser sempre 'dark'"""
        assert main_window.theme_manager.get_theme_name() == 'dark'


# === TESTES DE SALVAR/CARREGAR ===


class TestPersistence:
    """Testes de persistência (salvar/carregar)"""
    
    def test_save_sessions_no_error(self, main_window):
        """Salvar sessões não deve dar erro"""
        # Não deve lançar exceção
        main_window._save_sessions()
    
    def test_session_serialization(self, main_window):
        """Sessões devem ser serializáveis"""
        focused = main_window.session_manager.focused_session
        if focused:
            data = focused.serialize()
            assert 'session_id' in data
            assert 'title' in data
            assert 'code' in data


# === TESTES DE FECHAR ABA ===


class TestCloseTab:
    """Testes de fechar abas"""
    
    def test_can_close_all_sessions_shows_empty_state(self, main_window, qtbot):
        """Ao fechar todas as sessões, deve mostrar tela de estado vazio"""
        from src.ui.components.session_widget import SessionWidget
        
        # Contar sessões iniciais
        initial_count = sum(
            1 for i in range(main_window.session_tabs.count())
            if isinstance(main_window.session_tabs.widget(i), SessionWidget)
        )
        
        # Se só tem uma, fechar deve mostrar estado vazio
        if initial_count == 1:
            main_window._close_session_tab(0)
            
            # Não deve ter mais sessões
            new_count = sum(
                1 for i in range(main_window.session_tabs.count())
                if isinstance(main_window.session_tabs.widget(i), SessionWidget)
            )
            assert new_count == 0
            
            # Deve ter o widget de estado vazio
            assert hasattr(main_window, '_empty_state_widget')
            assert main_window._empty_state_widget is not None
    
    def test_new_session_removes_empty_state(self, main_window, qtbot):
        """Criar nova sessão deve remover estado vazio"""
        from src.ui.components.session_widget import SessionWidget
        
        # Primeiro, garantir estado vazio fechando tudo
        session_count = sum(
            1 for i in range(main_window.session_tabs.count())
            if isinstance(main_window.session_tabs.widget(i), SessionWidget)
        )
        for _ in range(session_count):
            main_window._close_session_tab(0)
        
        # Verificar estado vazio
        assert hasattr(main_window, '_empty_state_widget')
        assert main_window._empty_state_widget is not None
        
        # Criar nova sessão
        main_window._new_session()
        qtbot.wait(100)
        
        # Verificar que estado vazio foi removido
        assert main_window._empty_state_widget is None
        
        # E que há uma sessão
        new_count = sum(
            1 for i in range(main_window.session_tabs.count())
            if isinstance(main_window.session_tabs.widget(i), SessionWidget)
        )
        assert new_count == 1


# === TESTES DE EXECUÇÃO (sem banco real) ===


class TestExecutionWithoutDB:
    """Testes de execução sem banco de dados real"""
    
    def test_sql_execution_without_connection_shows_error(self, main_window, qtbot):
        """Executar SQL sem conexão deve mostrar erro"""
        widget = main_window._get_current_session_widget()
        if widget:
            # Garantir que não há conexão
            widget.session.clear_connection()
            
            # Tentar executar SQL
            widget._on_execute_sql("SELECT 1")
            
            # Deve ter mensagem de erro no output
            output_text = widget.output_text.toPlainText()
            assert 'Erro' in output_text or 'conexão' in output_text.lower()


# === TESTES DE INTEGRAÇÃO ===


class TestIntegration:
    """Testes de integração entre componentes"""
    
    def test_new_session_has_all_components(self, main_window, qtbot):
        """Nova sessão deve ter todos os componentes"""
        main_window._new_session()
        
        widget = main_window._get_current_session_widget()
        assert widget is not None
        
        # Verificar todos os componentes
        assert hasattr(widget, 'editor'), "Falta editor"
        assert hasattr(widget, 'results_viewer'), "Falta results_viewer"
        assert hasattr(widget, 'output_text'), "Falta output_text"
        assert hasattr(widget, 'variables_viewer'), "Falta variables_viewer"
        assert hasattr(widget, 'session'), "Falta session"
        assert hasattr(widget, 'splitter'), "Falta splitter"
        assert hasattr(widget, 'bottom_tabs'), "Falta bottom_tabs"
    
    def test_close_window_saves_sessions(self, main_window, qtbot):
        """Fechar janela deve salvar sessões"""
        # Mock para verificar se save foi chamado
        with patch.object(main_window, '_save_sessions') as mock_save:
            # Simular evento de fechar
            from PyQt6.QtGui import QCloseEvent
            event = QCloseEvent()
            main_window.closeEvent(event)
            
            mock_save.assert_called_once()


# === TESTES DE ATRIBUTOS CRÍTICOS ===


class TestCriticalAttributes:
    """Testes para garantir que atributos críticos existem (evita AttributeError)"""
    
    def test_main_window_has_session_manager(self, main_window):
        """MainWindow deve ter session_manager"""
        assert hasattr(main_window, 'session_manager')
    
    def test_main_window_has_theme_manager(self, main_window):
        """MainWindow deve ter theme_manager"""
        assert hasattr(main_window, 'theme_manager')
    
    def test_main_window_has_connection_manager(self, main_window):
        """MainWindow deve ter connection_manager"""
        assert hasattr(main_window, 'connection_manager')
    
    def test_main_window_has_session_tabs(self, main_window):
        """MainWindow deve ter session_tabs"""
        assert hasattr(main_window, 'session_tabs')
    
    def test_main_window_has_action_label(self, main_window):
        """MainWindow deve ter action_label"""
        assert hasattr(main_window, 'action_label')
    
    def test_main_window_has_statusbar(self, main_window):
        """MainWindow deve ter statusbar"""
        assert hasattr(main_window, 'statusbar')
    
    def test_session_widget_has_session(self, main_window):
        """SessionWidget deve ter session"""
        widget = main_window._get_current_session_widget()
        assert widget is not None
        assert hasattr(widget, 'session')
    
    def test_session_has_required_methods(self, main_window):
        """Session deve ter métodos necessários"""
        session = main_window.session_manager.focused_session
        if session:
            assert hasattr(session, 'serialize')
            assert hasattr(session, 'set_connection')
            assert hasattr(session, 'clear_connection')
            assert hasattr(session, 'initialize')
            assert callable(session.serialize)
    
    def test_connection_manager_has_get_connection(self, main_window):
        """ConnectionManager deve ter get_connection (não get_connector)"""
        cm = main_window.connection_manager
        assert hasattr(cm, 'get_connection')
    
    def test_theme_manager_has_get_app_colors(self, main_window):
        """ThemeManager deve ter get_app_colors (não get_colors)"""
        tm = main_window.theme_manager
        assert hasattr(tm, 'get_app_colors')
        assert callable(tm.get_app_colors)

class TestComponentInterfaces:
    """Testes para garantir que os componentes têm as interfaces esperadas"""
    
    def test_bottom_tabs_has_log_method(self, main_window):
        """BottomTabs deve ter método log()"""
        widget = main_window._get_current_session_widget()
        assert widget is not None
        assert hasattr(widget, 'bottom_tabs')
        bt = widget.bottom_tabs
        assert hasattr(bt, 'log')
        assert callable(bt.log)
    
    def test_bottom_tabs_has_log_error_method(self, main_window):
        """BottomTabs deve ter método log_error()"""
        widget = main_window._get_current_session_widget()
        bt = widget.bottom_tabs
        assert hasattr(bt, 'log_error')
        assert callable(bt.log_error)
    
    def test_bottom_tabs_has_log_success_method(self, main_window):
        """BottomTabs deve ter método log_success()"""
        widget = main_window._get_current_session_widget()
        bt = widget.bottom_tabs
        assert hasattr(bt, 'log_success')
        assert callable(bt.log_success)
    
    def test_bottom_tabs_has_log_warning_method(self, main_window):
        """BottomTabs deve ter método log_warning()"""
        widget = main_window._get_current_session_widget()
        bt = widget.bottom_tabs
        assert hasattr(bt, 'log_warning')
        assert callable(bt.log_warning)
    
    def test_bottom_tabs_has_set_results_method(self, main_window):
        """BottomTabs deve ter método set_results()"""
        widget = main_window._get_current_session_widget()
        bt = widget.bottom_tabs
        assert hasattr(bt, 'set_results')
        assert callable(bt.set_results)
    
    def test_bottom_tabs_has_set_variables_method(self, main_window):
        """BottomTabs deve ter método set_variables()"""
        widget = main_window._get_current_session_widget()
        bt = widget.bottom_tabs
        assert hasattr(bt, 'set_variables')
        assert callable(bt.set_variables)
    
    def test_bottom_tabs_has_show_output_method(self, main_window):
        """BottomTabs deve ter método show_output()"""
        widget = main_window._get_current_session_widget()
        bt = widget.bottom_tabs
        assert hasattr(bt, 'show_output')
        assert callable(bt.show_output)
    
    def test_bottom_tabs_has_clear_output_method(self, main_window):
        """BottomTabs deve ter método clear_output()"""
        widget = main_window._get_current_session_widget()
        bt = widget.bottom_tabs
        assert hasattr(bt, 'clear_output')
        assert callable(bt.clear_output)
    
    def test_bottom_tabs_has_output_text_property(self, main_window):
        """BottomTabs deve ter propriedade output_text para compatibilidade"""
        widget = main_window._get_current_session_widget()
        bt = widget.bottom_tabs
        assert hasattr(bt, 'output_text')
    
    def test_session_widget_has_append_output_method(self, main_window):
        """SessionWidget deve ter método append_output()"""
        widget = main_window._get_current_session_widget()
        assert hasattr(widget, 'append_output')
        assert callable(widget.append_output)
    
    def test_session_widget_has_clear_output_method(self, main_window):
        """SessionWidget deve ter método clear_output()"""
        widget = main_window._get_current_session_widget()
        assert hasattr(widget, 'clear_output')
        assert callable(widget.clear_output)
    
    def test_session_widget_output_text_property(self, main_window):
        """SessionWidget deve ter propriedade output_text"""
        widget = main_window._get_current_session_widget()
        assert hasattr(widget, 'output_text')
    
    def test_session_widget_variables_viewer_property(self, main_window):
        """SessionWidget deve ter propriedade variables_viewer"""
        widget = main_window._get_current_session_widget()
        assert hasattr(widget, 'variables_viewer')
    
    def test_main_window_python_output_property(self, main_window):
        """MainWindow deve ter propriedade python_output"""
        assert hasattr(main_window, 'python_output')
        # Deve retornar o output_text da sessão atual
        output = main_window.python_output
        assert output is not None
    
    def test_main_window_bottom_tabs_property(self, main_window):
        """MainWindow deve ter propriedade bottom_tabs"""
        assert hasattr(main_window, 'bottom_tabs')
        bt = main_window.bottom_tabs
        assert bt is not None