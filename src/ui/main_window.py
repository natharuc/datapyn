"""
Janela principal da IDE DataPyn
"""
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QSplitter, QTabWidget, QMenuBar, QMenu, QToolBar,
                             QStatusBar, QMessageBox, QTextEdit, QDockWidget,
                             QLabel, QPushButton, QFileDialog, QLineEdit, QTabBar,
                             QGroupBox, QListWidget, QListWidgetItem, QFrame,
                             QApplication)
from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QFont, QColor
import sys
import re
import traceback
from io import StringIO
from datetime import datetime
import pandas as pd

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

try:
    from windows_toasts import Toast, WindowsToaster
    HAS_WINDOWS_TOASTS = True
except ImportError:
    HAS_WINDOWS_TOASTS = False

from src.editors import UnifiedEditor
from src.database import ConnectionManager
from src.core import ResultsManager, ShortcutManager, WorkspaceManager, ThemeManager, SessionManager
from src.core.mixed_executor import MixedLanguageExecutor
from src.ui.dialogs.connection_edit_dialog import ConnectionEditDialog
from src.ui.dialogs.connections_manager_dialog import ConnectionsManagerDialog
from src.ui.dialogs.settings_dialog import SettingsDialog

# Componentes da UI
from src.ui.components.results_viewer import ResultsViewer
from src.ui.components.session_widget import SessionWidget
from src.ui.components.session_tabs import SessionTabs
from src.ui.components.connection_panel import ConnectionPanel
from src.ui.components.toolbar import MainToolbar
from src.ui.components.statusbar import MainStatusBar


class SqlWorker(QObject):
    """Worker para executar SQL em background"""
    finished = pyqtSignal(object, str)  # (result_df ou None, error_msg ou '')
    
    def __init__(self, connector, query):
        super().__init__()
        self.connector = connector
        self.query = query
    
    def run(self):
        try:
            df = self.connector.execute_query(self.query)
            self.finished.emit(df, '')
        except Exception as e:
            self.finished.emit(None, str(e))


class ConnectionWorker(QObject):
    """Worker para conectar ao banco em background"""
    finished = pyqtSignal(bool, str)  # (success, error_msg)
    
    def __init__(self, connection_manager, conn_name, config, password):
        super().__init__()
        self.connection_manager = connection_manager
        self.conn_name = conn_name
        self.config = config
        self.password = password
    
    def run(self):
        try:
            self.connection_manager.create_connection(
                self.conn_name,
                self.config['db_type'],
                self.config['host'],
                self.config['port'],
                self.config['database'],
                self.config.get('username', ''),
                self.password,
                use_windows_auth=self.config.get('use_windows_auth', False)
            )
            self.finished.emit(True, '')
        except Exception as e:
            self.finished.emit(False, str(e))


class PythonWorker(QObject):
    """Worker para executar Python em background"""
    finished = pyqtSignal(object, str, str)  # (result, output, error)
    
    def __init__(self, code, namespace, is_expression):
        super().__init__()
        self.code = code
        self.namespace = namespace
        self.is_expression = is_expression
    
    def run(self):
        try:
            # Captura stdout
            old_stdout = sys.stdout
            sys.stdout = captured_output = StringIO()
            
            result_value = None
            
            if self.is_expression:
                result_value = eval(self.code, self.namespace)
            else:
                exec(self.code, self.namespace)
            
            sys.stdout = old_stdout
            output = captured_output.getvalue()
            
            self.finished.emit(result_value, output, '')
        except Exception as e:
            sys.stdout = old_stdout
            self.finished.emit(None, '', traceback.format_exc())


class CrossSyntaxWorker(QObject):
    """Worker para executar Cross-Syntax em background"""
    finished = pyqtSignal(dict, str)  # (result_dict, error)
    
    def __init__(self, executor, code, namespace):
        super().__init__()
        self.executor = executor
        self.code = code
        self.namespace = namespace
    
    def run(self):
        try:
            result = self.executor.parse_and_execute(self.code, self.namespace)
            self.finished.emit(result, '')
        except Exception as e:
            self.finished.emit({}, traceback.format_exc())


class MainWindow(QMainWindow):
    """Janela principal da IDE"""
    
    def __init__(self):
        super().__init__()
        
        # Managers
        self.connection_manager = ConnectionManager()
        self.results_manager = ResultsManager()
        self.shortcut_manager = ShortcutManager()
        self.workspace_manager = WorkspaceManager()
        self.theme_manager = ThemeManager()
        self.session_manager = SessionManager()  # Novo: Gerenciador de sessões
        self.mixed_executor = MixedLanguageExecutor(None, self.results_manager)
        
        # Mapeia session_id -> SessionWidget
        self._session_widgets: dict = {}
        
        # Widget de estado vazio (quando não há sessões)
        self._empty_state_widget = None
        
        # Threads para execução em background
        self._worker_threads = []  # Mantém referência para não ser coletado pelo GC
        
        # Ícones
        self.icons = self._setup_icons()
        
        self._setup_ui()
        self._create_menus()
        self._create_toolbar()
        self._create_statusbar()
        self._setup_shortcuts()
        
        # Conectar sinais do SessionManager
        self.session_manager.session_focused.connect(self._on_session_focused)
        
        # Aplicar tema inicial
        self._apply_app_theme()
        
        # Timer para atualizar status
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)
    
    # === PROPRIEDADES DE DELEGAÇÃO PARA SESSÃO ATUAL ===
    
    @property
    def results_viewer(self):
        """Retorna o results_viewer da sessão atual"""
        widget = self._get_current_session_widget()
        return widget.results_viewer if widget else None
    
    @property
    def variables_viewer(self):
        """Retorna o variables_viewer da sessão atual"""
        widget = self._get_current_session_widget()
        return widget.variables_viewer if widget else None
    
    @property
    def python_output(self):
        """Retorna o output_text da sessão atual"""
        widget = self._get_current_session_widget()
        return widget.output_text if widget else None
    
    @property
    def bottom_tabs(self):
        """Retorna o bottom_tabs da sessão atual"""
        widget = self._get_current_session_widget()
        return widget.bottom_tabs if widget else None
    
    def show(self):
        """Sobrescreve show para restaurar geometria da janela"""
        super().show()
        # Restaurar geometria após a janela ser mostrada
        self._restore_window_state()
    
    def _setup_icons(self):
        """Configura ícones do QtAwesome"""
        if not HAS_QTAWESOME:
            return {}
        
        return {
            'database': qta.icon('fa5s.database', color='#569cd6'),
            'play': qta.icon('fa5s.play', color='#4ec9b0'),
            'python': qta.icon('fa5b.python', color='#4ec9b0'),
            'table': qta.icon('fa5s.table', color='#9cdcfe'),
            'save': qta.icon('fa5s.save', color='#d4d4d4'),
            'folder-open': qta.icon('fa5s.folder-open', color='#d4d4d4'),
            'trash': qta.icon('fa5s.trash', color='#f48771'),
            'cog': qta.icon('fa5s.cog', color='#d4d4d4'),
            'plug': qta.icon('fa5s.plug', color='#569cd6'),
            'code': qta.icon('fa5s.code', color='#9cdcfe'),
            'chart-bar': qta.icon('fa5s.chart-bar', color='#4ec9b0'),
            'memory': qta.icon('fa5s.microchip', color='#c586c0'),
            'terminal': qta.icon('fa5s.terminal', color='#d4d4d4'),
        }
    
    def _setup_ui(self):
        """Configura a interface principal"""
        self.setWindowTitle("DataPyn - IDE SQL + Python")
        self.setGeometry(100, 100, 1400, 900)
        
        # Tema escuro
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QMenuBar {
                background-color: #2d2d30;
                color: #cccccc;
                border-bottom: 1px solid #3e3e42;
            }
            QMenuBar::item:selected {
                background-color: #3e3e42;
            }
            QMenu {
                background-color: #2d2d30;
                color: #cccccc;
                border: 1px solid #3e3e42;
                padding: 5px 0px;
            }
            QMenu::item {
                padding: 6px 40px 6px 30px;
                min-width: 180px;
            }
            QMenu::item:selected {
                background-color: #094771;
            }
            QMenu::icon {
                padding-left: 10px;
            }
            QToolBar {
                background-color: #2d2d30;
                border-bottom: 1px solid #3e3e42;
                spacing: 5px;
            }
            QStatusBar {
                background-color: #007acc;
                color: white;
            }
            QTabWidget::pane {
                border: 1px solid #3e3e42;
                background-color: #1e1e1e;
            }
            QTabBar::tab {
                background-color: #2d2d30;
                color: #cccccc;
                padding: 8px 20px;
                border: 1px solid #3e3e42;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QTabBar::tab:hover {
                background-color: #3e3e42;
            }
            QSplitter::handle {
                background-color: #3e3e42;
            }
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                padding: 5px 15px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3e3e42;
            }
        """)
        
        # Widget central
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Layout principal
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Container para as abas de sessões
        session_container = QWidget()
        session_layout = QVBoxLayout(session_container)
        session_layout.setContentsMargins(5, 5, 5, 5)
        
        # TabWidget para sessões (cada aba é um SessionWidget completo)
        self.session_tabs = SessionTabs()
        self.session_tabs.session_closed.connect(self._close_session_tab)
        self.session_tabs.session_renamed.connect(self._on_session_renamed)
        self.session_tabs.session_changed.connect(self._on_session_tab_changed)
        
        session_layout.addWidget(self.session_tabs)
        
        # Restaurar sessões
        self._restore_sessions()
        
        main_layout.addWidget(session_container)
        
        # Dock para conexões (lateral esquerda)
        self._create_connections_dock()
    
    def _create_connections_dock(self):
        """Cria painel lateral de conexões usando ConnectionPanel"""
        # Usar o componente ConnectionPanel
        self.connection_panel = ConnectionPanel(
            connection_manager=self.connection_manager,
            theme_manager=self.theme_manager
        )
        
        # Conectar sinais
        self.connection_panel.connection_requested.connect(self._quick_connect)
        self.connection_panel.new_connection_clicked.connect(self._new_connection)
        self.connection_panel.manage_connections_clicked.connect(self._manage_connections)
        self.connection_panel.disconnect_clicked.connect(self._disconnect)
        
        # Criar dock widget
        self.connections_dock = QDockWidget("Conexões", self)
        self.connections_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.connections_dock.setWidget(self.connection_panel)
        self.connections_dock.setStyleSheet("""
            QDockWidget {
                background-color: #252526;
                color: #cccccc;
            }
            QDockWidget::title {
                background-color: #2d2d30;
                padding: 8px;
                font-weight: bold;
            }
        """)
        
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.connections_dock)
        
        # Criar propriedades de compatibilidade
        self._setup_connection_panel_compat()
    
    def _setup_connection_panel_compat(self):
        """Cria propriedades de compatibilidade para código legado"""
        # Mapeia atributos antigos para o novo componente
        self.connections_list = self.connection_panel.connections_list.list_widget
        self.active_conn_name_label = self.connection_panel.active_widget.name_label
        self.active_conn_info_label = self.connection_panel.active_widget.info_label
        self.btn_disconnect = self.connection_panel.active_widget.btn_disconnect
    
    def _refresh_connections_list(self):
        """Atualiza lista de conexões salvas"""
        self.connection_panel.refresh_connections()
    
    def _on_connection_double_click(self, item: QListWidgetItem):
        """Conecta ao dar duplo clique na conexão"""
        conn_name = item.data(Qt.ItemDataRole.UserRole)
        if conn_name:
            self._quick_connect(conn_name)
    
    def _quick_connect(self, connection_name: str):
        """Conecta rapidamente a uma conexão salva (em background com loading)"""
        # Verificar se já há uma conexão em andamento
        if hasattr(self, '_conn_thread') and self._conn_thread and self._conn_thread.isRunning():
            QMessageBox.information(
                self, "Aguarde", 
                "Uma conexão já está em andamento. Aguarde ela terminar."
            )
            return
        
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            QMessageBox.warning(self, "Erro", f"Conexão '{connection_name}' não encontrada")
            return
        
        # Pegar senha se necessário
        password = ''
        if not config.get('use_windows_auth', False):
            password = config.get('password', '')
        
        # Criar loading dialog
        from PyQt6.QtWidgets import QProgressDialog
        self.connection_loading = QProgressDialog(self)
        self.connection_loading.setWindowTitle("Conectando")
        self.connection_loading.setLabelText(f"Conectando a {connection_name}...")
        self.connection_loading.setCancelButton(None)
        self.connection_loading.setRange(0, 0)  # Indeterminate
        self.connection_loading.setWindowModality(Qt.WindowModality.WindowModal)
        self.connection_loading.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        self.connection_loading.setMinimumWidth(300)
        self.connection_loading.show()
        
        # Criar thread e worker para conexão em background
        self._conn_thread = QThread()
        self._conn_worker = ConnectionWorker(
            self.connection_manager, connection_name, config, password
        )
        self._conn_worker.moveToThread(self._conn_thread)
        
        # Conectar sinais
        self._conn_thread.started.connect(self._conn_worker.run)
        self._conn_worker.finished.connect(
            lambda success, error: self._on_connection_finished(connection_name, success, error)
        )
        
        # Iniciar
        self._conn_thread.start()
    
    def _on_connection_finished(self, connection_name: str, success: bool, error: str):
        """Callback quando conexão termina (sucesso ou erro)"""
        # Fechar loading dialog
        if hasattr(self, 'connection_loading'):
            self.connection_loading.close()
        
        # Parar thread (se existir - pode não existir em testes)
        if hasattr(self, '_conn_thread') and self._conn_thread:
            self._conn_thread.quit()
            self._conn_thread.wait()
            self._conn_thread = None  # Limpar referência
        
        if success:
            self.connection_manager.mark_connection_used(connection_name)
            
            # Definir conexão na sessão focada
            connector = self.connection_manager.get_connection(connection_name)
            if self.session_manager.focused_session and connector:
                self.session_manager.focused_session.set_connection(connection_name, connector)
            
            self._update_connection_status()
            self.action_label.setText(f"Conectado a {connection_name}")
        else:
            self.action_label.setText("Falha na conexão")
            QMessageBox.critical(self, "Erro de Conexão", f"Não foi possível conectar:\n\n{error}")
    
    def _create_menus(self):
        """Cria os menus"""
        menubar = self.menuBar()
        
        # Menu Arquivo
        file_menu = menubar.addMenu("&Arquivo")
        
        new_action = QAction("&Novo", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self._new_file)
        file_menu.addAction(new_action)
        
        open_action = QAction("&Abrir...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_file)
        file_menu.addAction(open_action)
        
        save_action = QAction("&Salvar", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self._save_file)
        file_menu.addAction(save_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Sai&r", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Menu Conexão
        conn_menu = menubar.addMenu("&Conexão")
        
        manage_conn_action = QAction("&Gerenciar Conexões...", self)
        if HAS_QTAWESOME:
            manage_conn_action.setIcon(self.icons['database'])
        manage_conn_action.setShortcut("Ctrl+Shift+M")
        manage_conn_action.triggered.connect(self._manage_connections)
        conn_menu.addAction(manage_conn_action)
        
        conn_menu.addSeparator()
        
        new_conn_action = QAction("&Nova Conexão...", self)
        if HAS_QTAWESOME:
            new_conn_action.setIcon(self.icons['plug'])
        new_conn_action.setShortcut("Ctrl+Shift+N")
        new_conn_action.triggered.connect(self._new_connection)
        conn_menu.addAction(new_conn_action)
        
        disconnect_action = QAction("&Desconectar", self)
        if HAS_QTAWESOME:
            disconnect_action.setIcon(self.icons['trash'])
        disconnect_action.triggered.connect(self._disconnect)
        conn_menu.addAction(disconnect_action)
        
        # Menu Executar
        run_menu = menubar.addMenu("&Executar")
        
        run_current_action = QAction("Executar &Bloco Atual", self)
        if HAS_QTAWESOME:
            run_current_action.setIcon(self.icons['play'])
        run_current_action.setShortcut("F5")
        run_current_action.triggered.connect(self._execute_current_block)
        run_menu.addAction(run_current_action)
        
        run_all_action = QAction("Executar &Todos os Blocos", self)
        if HAS_QTAWESOME:
            run_all_action.setIcon(qta.icon('fa5s.forward'))
        run_all_action.setShortcut("Ctrl+F5")
        run_all_action.triggered.connect(self._execute_all_blocks)
        run_menu.addAction(run_all_action)
        
        run_menu.addSeparator()
        
        run_sql_action = QAction("Forçar Executar como &SQL", self)
        if HAS_QTAWESOME:
            run_sql_action.setIcon(self.icons['database'])
        run_sql_action.triggered.connect(self._force_execute_sql)
        run_menu.addAction(run_sql_action)
        
        run_python_action = QAction("Forçar Executar como &Python", self)
        if HAS_QTAWESOME:
            run_python_action.setIcon(qta.icon('fa5b.python'))
        run_python_action.setShortcut("Shift+Return")
        run_python_action.triggered.connect(self._force_execute_python)
        run_menu.addAction(run_python_action)
        
        run_cross_action = QAction("Forçar Executar como &Cross", self)
        if HAS_QTAWESOME:
            run_cross_action.setIcon(qta.icon('fa5s.code'))
        run_cross_action.triggered.connect(self._force_execute_cross)
        run_menu.addAction(run_cross_action)
        
        run_menu.addSeparator()
        
        clear_results_action = QAction("&Limpar Resultados", self)
        if HAS_QTAWESOME:
            clear_results_action.setIcon(self.icons['trash'])
        clear_results_action.setShortcut("Ctrl+Shift+C")
        clear_results_action.triggered.connect(self._clear_results)
        run_menu.addAction(clear_results_action)
        
        # Menu Exibir
        view_menu = menubar.addMenu("E&xibir")
        
        # Toggle do dock de conexões
        toggle_dock_action = QAction("Painel de &Conexões", self)
        toggle_dock_action.setCheckable(True)
        toggle_dock_action.setChecked(True)
        toggle_dock_action.triggered.connect(lambda checked: self.connections_dock.setVisible(checked))
        view_menu.addAction(toggle_dock_action)
        
        # Menu Ferramentas
        tools_menu = menubar.addMenu("&Ferramentas")
        
        settings_action = QAction("&Configurações de Atalhos...", self)
        if HAS_QTAWESOME:
            settings_action.setIcon(self.icons['cog'])
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._show_settings)
        tools_menu.addAction(settings_action)
        
        # Menu Ajuda
        help_menu = menubar.addMenu("A&juda")
        
        about_action = QAction("&Sobre", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def _create_toolbar(self):
        """Cria a toolbar usando MainToolbar"""
        self.main_toolbar = MainToolbar(theme_manager=self.theme_manager)
        self.addToolBar(self.main_toolbar)
        
        # Conectar sinais
        self.main_toolbar.new_connection_clicked.connect(self._new_connection)
        self.main_toolbar.new_tab_clicked.connect(self._new_session)
        self.main_toolbar.run_clicked.connect(self._execute_from_toolbar)
    
    def _execute_from_toolbar(self):
        """Executa código do editor atual via botão da toolbar"""
        editor = self._get_current_editor()
        if not editor:
            return
        
        # Usa a mesma lógica do BlockEditor: F5 executa seleção ou todos os blocos
        if hasattr(editor, '_execute_smart'):
            editor._execute_smart()
        elif hasattr(editor, 'get_selected_or_all_text'):
            # Fallback para editor antigo
            code = editor.get_selected_or_all_text()
            if code.strip():
                self._execute_cross_syntax(code)
    
    def _create_statusbar(self):
        """Cria a barra de status usando MainStatusBar"""
        self.main_statusbar = MainStatusBar(theme_manager=self.theme_manager)
        self.setStatusBar(self.main_statusbar)
        
        # Criar propriedades de compatibilidade
        self.statusbar = self.main_statusbar
        self.connection_status_bar = self.main_statusbar.connection_label
        self.action_label = self.main_statusbar.action_label
        self.execution_label = self.main_statusbar.timer_label
        
        # Timers - usar os do componente
        self._is_executing = False
        self._execution_timer = QElapsedTimer()
        self._execution_update_timer = QTimer()
        self._execution_update_timer.timeout.connect(self._update_execution_time)
    
    def _start_execution_timer(self, mode: str = ""):
        """Inicia o timer de execução"""
        self._is_executing = True
        self._execution_mode = mode
        self._execution_timer.start()
        self._execution_update_timer.start(100)
        self._update_execution_time()
        self.main_statusbar.start_timer()
    
    def _stop_execution_timer(self):
        """Para o timer de execução e mostra tempo final"""
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
            # Limpa após 5 segundos
            QTimer.singleShot(5000, self._clear_execution_label)
        self._is_executing = False
    
    def _update_execution_time(self):
        """Atualiza o label com o tempo de execução"""
        if self._is_executing:
            elapsed = self._execution_timer.elapsed() / 1000.0
            mode = f"[{self._execution_mode}] " if self._execution_mode else ""
            self.execution_label.setText(f"{mode}Executando {elapsed:.2f}s")
            self.execution_label.setStyleSheet("""
                QLabel {
                    color: #FFD700;
                    font-weight: bold;
                    padding: 0 10px;
                }
            """)
    
    def _clear_execution_label(self):
        """Limpa o label de execução"""
        if not self._is_executing:
            self.execution_label.setText("")
    
    def _setup_shortcuts(self):
        """Configura atalhos customizados"""
        # Os atalhos principais já estão nos editores
        pass
    
    def _manage_connections(self):
        """Abre diálogo de gerenciamento de conexões"""
        dialog = ConnectionsManagerDialog(self.connection_manager, theme_manager=self.theme_manager, parent=self)
        dialog.connection_selected.connect(self._connect_from_manager)
        dialog.exec()
        # Atualizar lista após fechar o diálogo
        self._refresh_connections_list()
    
    def _connect_from_manager(self, name: str, config: dict):
        """Conecta a partir do gerenciador de conexões"""
        try:
            # Se for autenticação Windows, não precisa de senha
            password = ''
            if not config.get('use_windows_auth', False):
                password = config.get('password', '')
                if not password:
                    from PyQt6.QtWidgets import QInputDialog
                    dialog = QInputDialog(self)
                    dialog.setWindowTitle("Senha Necessária")
                    dialog.setLabelText(f"Digite a senha para a conexão '{name}':")
                    dialog.setTextEchoMode(QLineEdit.EchoMode.Password)
                    dialog.resize(400, 150)
                    if not dialog.exec():
                        return
                    password = dialog.textValue()
            
            connector = self.connection_manager.create_connection(
                name,
                config['db_type'],
                config['host'],
                config['port'],
                config['database'],
                config.get('username', ''),
                password,
                use_windows_auth=config.get('use_windows_auth', False)
            )
            
            # Marcar como usada
            self.connection_manager.mark_connection_used(name)
            
            # Atualizar status
            self._update_connection_status()
            self.action_label.setText(f"Conectado a {name}")
            
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao conectar:\n{str(e)}")
    
    def _new_connection(self):
        """Abre diálogo para nova conexão"""
        dialog = ConnectionEditDialog(
            connection_name=None,
            config=None,
            groups=self.connection_manager.get_groups(),
            theme_manager=self.theme_manager,
            parent=self
        )
        
        if dialog.exec():
            name, config = dialog.get_result()
            
            # Salva a conexão
            self.connection_manager.save_connection_config(
                name,
                config['db_type'],
                config['host'],
                config['port'],
                config['database'],
                config.get('username', ''),
                config.get('save_password', False),
                config.get('password', ''),
                config.get('group', ''),
                config.get('use_windows_auth', False),
                config.get('color', '')
            )
            
            self._update_connection_status()
            self._refresh_connections_list()
            self._log(f"Conexão '{name}' criada com sucesso")
            self.action_label.setText(f"Conexão '{name}' criada")
    
    def _disconnect(self):
        """Desconecta a sessão atual"""
        session = self.session_manager.focused_session
        if session and session.is_connected:
            # Limpar conexão da sessão
            session.clear_connection()
            self._update_connection_status()
            self.action_label.setText("Desconectado")
    
    def _update_connection_status(self):
        """Atualiza status da conexão da sessão atual"""
        session = self.session_manager.focused_session
        
        if session and session.is_connected:
            conn_name = session.connection_name
            connector = session.connector
            
            # Obter config da conexão
            config = self.connection_manager.get_connection_config(conn_name)
            host = config.get('host', 'localhost') if config else 'localhost'
            db = config.get('database', '') if config else ''
            db_type = config.get('db_type', '') if config else ''
            
            # === PAINEL LATERAL ===
            self.connection_panel.set_active_connection(
                conn_name,
                host=host,
                database=db,
                db_type=db_type
            )
            
            # Destacar conexão ativa na lista
            for i in range(self.connections_list.count()):
                item = self.connections_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == conn_name:
                    self.connections_list.setCurrentItem(item)
                    break
            
            # === STATUSBAR ===
            conn_display = f"{conn_name} @ {host}/{db}"
            self.connection_status_bar.setText(conn_display)
            self.connection_status_bar.setStyleSheet("""
                QLabel {
                    color: white;
                    font-weight: bold;
                    padding: 0 15px;
                    border-right: 1px solid rgba(255,255,255,0.3);
                }
            """)
            
            # Usar cor configurada na conexão (ou azul padrão)
            status_color = config.get('color', '#007acc') if config else '#007acc'
            if not status_color:
                status_color = '#007acc'
            self.statusbar.setStyleSheet(f"QStatusBar {{ background-color: {status_color}; color: white; }}")
        else:
            # === PAINEL LATERAL ===
            self.connection_panel.set_disconnected()
            self.connections_list.clearSelection()
            
            # === STATUSBAR ===
            self.connection_status_bar.setText("Desconectado")
            self.connection_status_bar.setStyleSheet("""
                QLabel {
                    color: white;
                    font-weight: bold;
                    padding: 0 15px;
                    border-right: 1px solid rgba(255,255,255,0.3);
                }
            """)
            # Barra de status cinza escuro quando desconectado
            self.statusbar.setStyleSheet("QStatusBar { background-color: #3e3e42; color: white; }}")
    
    def _execute_current_block(self):
        """Executa o bloco atualmente focado com sua linguagem"""
        editor = self._get_current_editor()
        if not editor:
            return
        
        # Se é um BlockEditor, usa o método dele
        from src.editors.block_editor import BlockEditor
        if isinstance(editor, BlockEditor):
            editor.execute_focused_block()
        else:
            # Editor antigo - executa como Python por padrão
            code = editor.get_selected_or_all_text().strip()
            if code:
                self._execute_python(code)
    
    def _execute_all_blocks(self):
        """Executa todos os blocos em sequência"""
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
    
    def _force_execute_sql(self):
        """Força execução do bloco atual como SQL"""
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
        """Força execução do bloco atual como Python"""
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
    
    def _force_execute_cross(self):
        """Força execução do bloco atual como Cross-Syntax"""
        editor = self._get_current_editor()
        if not editor:
            return
        
        from src.editors.block_editor import BlockEditor
        if isinstance(editor, BlockEditor):
            code = editor.get_focused_block_code()
        else:
            code = editor.get_selected_or_all_text()
        
        if code and code.strip():
            self._execute_cross_syntax(code.strip())
    
    def _execute_sql(self, query: str):
        """Executa query SQL em background"""
        query = query.strip()
        if not query:
            # Pegar da aba atual se vazio
            editor = self._get_current_editor()
            if editor:
                query = editor.get_selected_or_all_text().strip()
            if not query:
                return
        
        # Usar conexão da sessão atual
        session = self.session_manager.focused_session
        if not session or not session.is_connected:
            QMessageBox.warning(self, "Atenção", "Não há conexão ativa nesta sessão. Conecte-se a um banco de dados primeiro.")
            return
        
        connector = session.connector
        
        # Detectar comando USE database (executa síncrono pois é rápido)
        use_match = re.match(r'^\s*USE\s+\[?([^\]\s;]+)\]?\s*;?\s*$', query, re.IGNORECASE)
        if use_match:
            database_name = use_match.group(1)
            try:
                self._start_execution_timer("SQL")
                self.action_label.setText(f"[SQL] Alterando para banco {database_name}...")
                
                connector.change_database(database_name)
                
                # Atualiza statusbar
                self._update_connection_status()
                
                self._log(f"[SQL] Banco alterado para: {database_name}")
                self.action_label.setText(f"[SQL] Banco: {database_name}")
                self._stop_execution_timer()
                return
                
            except Exception as e:
                self._stop_execution_timer()
                QMessageBox.critical(self, "Erro", f"Erro ao trocar banco de dados:\n{str(e)}")
                self.action_label.setText("[SQL] Erro ao trocar banco")
                return
        
        # Execução em background
        self._start_execution_timer("SQL")
        self.action_label.setText("[SQL] Executando query...")
        
        # Marcar aba como rodando
        running_tab_index = self._mark_tab_running(True)
        
        # Criar thread e worker
        thread = QThread()
        worker = SqlWorker(connector, query)
        worker.moveToThread(thread)
        
        # Conectar sinais
        thread.started.connect(worker.run)
        worker.finished.connect(lambda df, err: self._on_sql_finished(df, err, thread, running_tab_index))
        
        # Manter referência
        self._worker_threads.append((thread, worker))
        
        # Iniciar
        thread.start()
    
    def _on_sql_finished(self, df, error, thread, tab_index):
        """Callback quando SQL termina"""
        self._stop_execution_timer()
        
        # Remover marcação de rodando
        self._mark_tab_running(False, tab_index)
        
        # Limpar thread da lista
        self._worker_threads = [(t, w) for t, w in self._worker_threads if t != thread]
        thread.quit()
        thread.wait()
        
        if error:
            self._show_error(f"[SQL] Erro: {error}")
            self.action_label.setText("[SQL] Erro ao executar")
            self._send_notification("Query SQL", f"Erro: {error[:50]}...", success=False)
        else:
            # Exibe resultado
            if self.results_viewer:
                self.results_viewer.display_dataframe(df, 'Resultado SQL')
            if self.bottom_tabs:
                self.bottom_tabs.setCurrentIndex(0)
            
            rows = len(df)
            self._log(f"[SQL] Executado com sucesso ({rows:,} linhas retornadas)")
            self.action_label.setText(f"[SQL] {rows:,} linhas retornadas")
            self._send_notification("Query SQL", f"Concluída! {rows:,} linhas retornadas", success=True)
    
    def _execute_python(self, code: str):
        """Executa código Python em background"""
        code = code.strip()
        if not code:
            # Pegar da aba atual se vazio
            editor = self._get_current_editor()
            if editor:
                code = editor.get_selected_or_all_text().strip()
            if not code:
                return
        
        self._start_execution_timer("Python")
        self.action_label.setText("[Python] Executando código...")
        
        # Marcar aba como rodando
        running_tab_index = self._mark_tab_running(True)
        
        # Namespace com os DataFrames
        namespace = self.results_manager.get_namespace()
        
        # Detectar se é expressão (para exibir resultado)
        try:
            compile(code, '<string>', 'eval')
            is_expression = True
        except:
            is_expression = False
        
        # Criar thread e worker
        thread = QThread()
        worker = PythonWorker(code, namespace, is_expression)
        worker.moveToThread(thread)
        
        # Conectar sinais
        thread.started.connect(worker.run)
        worker.finished.connect(lambda result, output, err: self._on_python_finished(result, output, err, thread, running_tab_index))
        
        # Manter referência
        self._worker_threads.append((thread, worker))
        
        # Iniciar
        thread.start()
    
    def _on_python_finished(self, result_value, output, error, thread, tab_index):
        """Callback quando Python termina"""
        self._stop_execution_timer()
        
        # Remover marcação de rodando
        self._mark_tab_running(False, tab_index)
        
        # Limpar thread da lista
        self._worker_threads = [(t, w) for t, w in self._worker_threads if t != thread]
        thread.quit()
        thread.wait()
        
        if error:
            self._show_error(f"[ERRO]\n{error}")
            self.action_label.setText("[Python] Erro ao executar")
            return
        
        # Mostra output de print()
        if output:
            self._log(output.strip())
        
        # Exibir resultado de forma inteligente
        if result_value is not None:
            if isinstance(result_value, pd.DataFrame):
                # DataFrame → TABELA
                if self.results_viewer:
                    self.results_viewer.display_dataframe(result_value, 'result')
                if self.bottom_tabs:
                    self.bottom_tabs.setCurrentIndex(0)
                rows = len(result_value)
                self._log(f"[Python] DataFrame exibido ({rows:,} linhas)")
                
            elif isinstance(result_value, (list, tuple)) and len(result_value) > 0:
                # Lista/tupla → tentar converter para DataFrame
                try:
                    df = pd.DataFrame(result_value)
                    if self.results_viewer:
                        self.results_viewer.display_dataframe(df, 'result')
                    if self.bottom_tabs:
                        self.bottom_tabs.setCurrentIndex(0)
                    self._log(f"[Python] Lista exibida como tabela ({len(result_value)} itens)")
                except:
                    self._log(repr(result_value))
                    
            elif isinstance(result_value, dict):
                # Dict → tentar converter para DataFrame
                try:
                    df = pd.DataFrame([result_value]) if not isinstance(list(result_value.values())[0], (list, tuple)) else pd.DataFrame(result_value)
                    if self.results_viewer:
                        self.results_viewer.display_dataframe(df, 'result')
                    if self.bottom_tabs:
                        self.bottom_tabs.setCurrentIndex(0)
                    self._log(f"[Python] Dicionário exibido como tabela")
                except:
                    self._log(repr(result_value))
            else:
                # Número, string, etc → LOG
                self._log(repr(result_value))
        
        # Atualiza variáveis
        self._update_variables_view()
        self.action_label.setText("[Python] Executado com sucesso!")
    
    def _execute_cross_syntax(self, code: str):
        """Executa código com sintaxe cross {{ SQL }} em background"""
        code = code.strip()
        if not code:
            # Pegar da aba atual se vazio
            editor = self._get_current_editor()
            if editor:
                code = editor.get_selected_or_all_text().strip()
            if not code:
                return
        
        self._start_execution_timer("Cross")
        self.action_label.setText("[Cross-Syntax] Executando...")
        
        # Marcar aba como rodando
        running_tab_index = self._mark_tab_running(True)
        
        # Validar sintaxe primeiro (síncrono, é rápido)
        is_valid, error = self.mixed_executor.validate_syntax(code)
        if not is_valid:
            self._stop_execution_timer()
            self._mark_tab_running(False, running_tab_index)
            self._show_error(f"[Cross-Syntax] Erro de sintaxe: {error}")
            self.action_label.setText("[Cross-Syntax] Erro de sintaxe")
            return
        
        # Usar conexão da sessão atual
        session = self.session_manager.focused_session
        if not session or not session.is_connected:
            self._stop_execution_timer()
            self._mark_tab_running(False, running_tab_index)
            QMessageBox.warning(self, "Atenção", "Nenhuma conexão ativa nesta sessão. Conecte a um banco de dados primeiro.")
            self.action_label.setText("[Cross-Syntax] Sem conexão")
            return
        
        # Guardar referência da sessão que iniciou a execução
        executing_session = session
        
        self.mixed_executor.db_connector = session.connector
        
        # Criar thread e worker - usar namespace da sessão que está executando
        thread = QThread()
        worker = CrossSyntaxWorker(self.mixed_executor, code, session.namespace)
        worker.moveToThread(thread)
        
        # Conectar sinais - passar a sessão que iniciou
        thread.started.connect(worker.run)
        worker.finished.connect(lambda result, err: self._on_cross_finished(result, err, code, thread, running_tab_index, executing_session))
        
        # Manter referência
        self._worker_threads.append((thread, worker))
        
        # Iniciar
        thread.start()
    
    def _on_cross_finished(self, result, error, code, thread, tab_index, session):
        """Callback quando Cross-Syntax termina
        
        Args:
            result: Resultado da execução
            error: Erro se houver
            code: Código executado
            thread: Thread usada
            tab_index: Índice da aba
            session: Sessão que INICIOU a execução (não a focada atual)
        """
        self._stop_execution_timer()
        
        # Remover marcação de rodando
        self._mark_tab_running(False, tab_index)
        
        # Limpar thread da lista
        self._worker_threads = [(t, w) for t, w in self._worker_threads if t != thread]
        thread.quit()
        thread.wait()
        
        # Marcar blocos como não executando
        widget = self._get_current_session_widget()
        if widget and hasattr(widget.editor, 'mark_execution_finished'):
            widget.editor.mark_execution_finished()
        
        if error:
            self._show_error(f"[ERRO Cross-Syntax]\n{error}")
            self.action_label.setText("[Cross-Syntax] Erro ao executar")
            self._send_notification("Cross-Syntax", f"Erro: {error[:50]}...", success=False)
            return
        
        # Mostra output
        if result.get('output'):
            self._log(result['output'].strip())
        
        # Mostra queries executadas no log
        if result.get('queries_executed'):
            # Exibir variáveis criadas
            queries = self.mixed_executor.extract_queries(code)
            for var_name, sql in queries:
                # Buscar no namespace da sessão que executou
                var_value = session.namespace.get(var_name)
                if var_value is not None:
                    if isinstance(var_value, pd.DataFrame):
                        rows = len(var_value)
                        self._log(f"[Cross-Syntax] Variável '{var_name}' criada ({rows:,} linhas)")
                    else:
                        self._log(f"[Cross-Syntax] Variável '{var_name}' criada")
        
        # Atualiza resultados se houver DataFrame retornado
        if result.get('result') is not None:
            if isinstance(result['result'], pd.DataFrame):
                if self.results_viewer:
                    self.results_viewer.display_dataframe(result['result'], 'result')
                if self.bottom_tabs:
                    self.bottom_tabs.setCurrentIndex(0)
        
        # Atualiza variáveis - da sessão que executou, se ainda for a focada
        if session == self.session_manager.focused_session:
            self._update_variables_view()
        
        self.action_label.setText("[Cross-Syntax] Executado com sucesso!")
        
        # Notificação de sucesso
        queries_count = result.get('queries_executed', 0)
        self._send_notification("Cross-Syntax", f"Concluído! {queries_count} queries executadas", success=True)
    
    def _mark_tab_running(self, is_running: bool, tab_index: int = None) -> int:
        """
        Marca/desmarca aba como rodando
        
        Args:
            is_running: Se True, adiciona "(run)" ao título. Se False, remove.
            tab_index: Índice da aba. Se None, usa a aba atual.
            
        Returns:
            Índice da aba modificada
        """
        if tab_index is None:
            tab_index = self.session_tabs.currentIndex()
        
        if tab_index < 0 or tab_index >= self.session_tabs.count():
            return tab_index
        
        current_title = self.session_tabs.tabText(tab_index)
        
        if is_running:
            # Adicionar "(run)" se não existir
            if "(run)" not in current_title:
                self.session_tabs.setTabText(tab_index, f"{current_title} (run)")
        else:
            # Remover "(run)"
            new_title = current_title.replace(" (run)", "")
            self.session_tabs.setTabText(tab_index, new_title)
        
        return tab_index
    
    def _send_notification(self, title: str, message: str, success: bool = True):
        """
        Envia notificação do Windows com callback para focar a janela ao clicar
        
        Args:
            title: Título da notificação
            message: Mensagem
            success: Se True, é uma notificação de sucesso
        """
        if not HAS_WINDOWS_TOASTS:
            return
        
        # Não envia notificação se a janela estiver em foco
        if self.isActiveWindow():
            return
        
        try:
            # Criar toaster com nome do app
            toaster = WindowsToaster('DataPyn')
            
            # Criar toast com título e mensagem
            toast = Toast()
            toast.text_fields = [f"DataPyn - {title}", message]
            
            # Callback para focar a janela quando clicar na notificação
            def on_activated(event_args):
                # Usar QTimer para garantir execução na thread principal
                QTimer.singleShot(0, self._focus_window)
            
            toast.on_activated = on_activated
            
            # Mostrar notificação
            toaster.show_toast(toast)
            
        except Exception as e:
            # Falha silenciosa
            pass
    
    def _focus_window(self):
        """Traz a janela para frente e foca"""
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()
        self.show()
    
    def _log(self, message: str):
        """Adiciona mensagem ao log com timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        if self.python_output:
            self.python_output.append(f"[{timestamp}] {message}")
    
    def _show_error(self, error_msg: str):
        """Mostra erro no Output em vermelho e alterna para a aba de Output"""
        if not self.python_output:
            return
        # Adiciona timestamp e erro em vermelho usando HTML
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        error_html = f'<span style="color: #ff6b6b; font-weight: bold;">[{timestamp}] {error_msg}</span>'
        self.python_output.append(error_html)
        
        # Alterna para a aba de Output (índice 1)
        if self.bottom_tabs:
            self.bottom_tabs.setCurrentIndex(1)
        
        # Scroll para o final
        scrollbar = self.python_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _update_variables_view(self):
        """Atualiza visualização de variáveis em memória"""
        if not self.variables_viewer:
            return
        vars_df = self.results_manager.get_variables_info()
        self.variables_viewer.display_dataframe(vars_df, "Variáveis")
    
    def _clear_results(self):
        """Limpa todos os resultados"""
        reply = QMessageBox.question(
            self, "Confirmar", 
            "Deseja limpar todos os resultados em memória?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.results_manager.clear_all()
            if self.results_viewer:
                self.results_viewer.clear()
            if self.variables_viewer:
                self.variables_viewer.clear()
            if self.python_output:
                self.python_output.clear()
            self.action_label.setText("Resultados limpos")
    
    def _new_file(self):
        """Limpa editor da aba atual"""
        editor = self._get_current_editor()
        if editor:
            editor.clear()
    
    def _open_file(self):
        """Abre arquivo SQL ou Python na aba atual"""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Abrir Arquivo", "", "SQL Files (*.sql);;Python Files (*.py);;All Files (*.*)"
        )
        if filename:
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
                editor = self._get_current_editor()
                if editor:
                    # Limpa blocos existentes e cria um novo com o conteúdo
                    editor.clear()
                    
                    # Detecta tipo de arquivo e ajusta linguagem
                    if filename.endswith('.py'):
                        language = 'python'
                    else:
                        language = 'sql'
                    
                    # Configura o primeiro bloco
                    blocks = editor.get_blocks()
                    if blocks:
                        blocks[0].set_language(language)
                        blocks[0].set_code(content)
                    
                    # Atualizar título da aba
                    import os
                    tab_title = os.path.basename(filename)
                    current_index = self.session_tabs.currentIndex()
                    self.session_tabs.setTabText(current_index, tab_title)
    
    def _save_file(self):
        """Salva arquivo da aba atual"""
        editor = self._get_current_editor()
        if not editor:
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Salvar Arquivo", "", "SQL Files (*.sql);;Python Files (*.py);;All Files (*.*)"
        )
        if filename:
            content = editor.text()
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            self.action_label.setText(f"Arquivo salvo: {filename}")
            
            # Atualizar título da aba
            import os
            tab_title = os.path.basename(filename)
            current_index = self.session_tabs.currentIndex()
            self.session_tabs.setTabText(current_index, tab_title)
            
            # Salvar sessões
            self._save_sessions()
    
    def _update_status(self):
        """Atualiza status periodicamente"""
        # Verifica se conexão da sessão atual ainda está ativa
        session = self.session_manager.focused_session
        if session and session.connector and not session.connector.is_connected():
            session.clear_connection()
            self._update_connection_status()
    
    def _change_theme(self, theme_id: str):
        """Muda o tema da aplicação"""
        self.theme_manager.save_theme(theme_id)
        
        # Atualizar checkmarks do menu
        for tid, action in self.theme_actions.items():
            action.setChecked(tid == theme_id)
        
        # Aplicar tema nos SessionWidgets
        for widget in self._session_widgets.values():
            widget.apply_theme()
        
        # Aplicar tema na aplicação
        self._apply_app_theme()
        
        self.action_label.setText(f"Tema alterado para: {self.theme_manager.get_current_theme()['name']}")
    
    def _apply_app_theme(self):
        """Aplica tema na aplicação (não nos editores)"""
        colors = self.theme_manager.get_app_colors()
        
        # Aplicar estilo geral na janela
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {colors['background']};
            }}
            QMenuBar {{
                background-color: {colors['background']};
                color: {colors['foreground']};
                border-bottom: 1px solid {colors['border']};
            }}
            QMenuBar::item {{
                background-color: transparent;
                padding: 6px 12px;
            }}
            QMenuBar::item:selected {{
                background-color: {colors['accent']};
            }}
            QMenu {{
                background-color: {colors['background']};
                color: {colors['foreground']};
                border: 1px solid {colors['border']};
            }}
            QMenu::item {{
                padding: 6px 40px 6px 30px;
                min-width: 180px;
            }}
            QMenu::item:selected {{
                background-color: {colors['accent']};
            }}
            QToolBar {{
                background-color: {colors['background']};
                border-bottom: 1px solid {colors['border']};
                spacing: 5px;
                padding: 3px;
            }}
            QPushButton {{
                background-color: {colors['border']};
                color: {colors['foreground']};
                border: none;
                padding: 6px 12px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {colors['accent']};
            }}
            QTabWidget::pane {{
                border: 1px solid {colors['border']};
                background-color: {colors['background']};
            }}
            QTabBar::tab {{
                background-color: {colors['border']};
                color: {colors['foreground']};
                padding: 8px 15px;
                padding-right: 25px;
                margin-right: 2px;
                min-width: 80px;
            }}
            QTabBar::tab:selected {{
                background-color: {colors['background']};
                color: {colors['accent']};
            }}
            QTabBar::tab:hover {{
                background-color: {colors['accent']};
            }}
            QTabBar::tab:last {{
                min-width: 30px;
                padding: 8px 10px;
                padding-right: 10px;
            }}
            QTabBar::close-button {{
                subcontrol-position: right;
                width: 12px;
                height: 12px;
            }}
            QTabBar::close-button:hover {{
                background-color: #ff6b6b;
                border-radius: 2px;
            }}
            QTextEdit {{
                background-color: {colors['background']};
                color: {colors['foreground']};
                border: 1px solid {colors['border']};
            }}
            QLabel {{
                color: {colors['foreground']};
            }}
            QGroupBox {{
                color: {colors['accent']};
                font-weight: bold;
                border: 1px solid {colors['border']};
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
            QListWidget {{
                background-color: {colors['background']};
                border: 1px solid {colors['border']};
                color: {colors['foreground']};
            }}
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {colors['border']};
            }}
            QListWidget::item:hover {{
                background-color: {colors['border']};
            }}
            QListWidget::item:selected {{
                background-color: {colors['accent']};
                color: white;
            }}
            QDockWidget {{
                background-color: {colors['background']};
                color: {colors['foreground']};
            }}
            QDockWidget::title {{
                background-color: {colors['border']};
                padding: 8px;
                font-weight: bold;
            }}
            QPushButton#btnPrimary {{
                background-color: {colors['accent']};
                color: white;
            }}
            QPushButton#btnPrimary:hover {{
                background-color: {colors['accent']};
            }}
            QPushButton#btnDisconnect:hover {{
                background-color: #f48771;
                color: white;
            }}
            QPushButton:disabled {{
                background-color: {colors['border']};
                color: #666666;
            }}
        """)
        
        # Atualizar ResultsViewers se existirem (pode ser None se não houver sessão)
        if hasattr(self, 'results_viewer') and self.results_viewer:
            self.results_viewer.set_theme_manager(self.theme_manager)
        if hasattr(self, 'variables_viewer') and self.variables_viewer:
            self.variables_viewer.set_theme_manager(self.theme_manager)
        
        # Atualizar SessionWidgets
        if hasattr(self, '_session_widgets'):
            for widget in self._session_widgets.values():
                if hasattr(widget, 'apply_theme'):
                    widget.apply_theme()
    
    def _show_about(self):
        """Mostra diálogo sobre"""
        QMessageBox.about(
            self,
            "Sobre DataPyn",
            """<h2>DataPyn IDE</h2>
            <p>IDE moderna para consultas SQL com manipulação Python integrada</p>
            <p><b>Recursos:</b></p>
            <ul>
                <li>Suporte para SQL Server, MySQL, MariaDB, PostgreSQL</li>
                <li>Editor SQL com syntax highlighting</li>
                <li>Editor Python para manipular resultados</li>
                <li>Resultados persistem em memória</li>
                <li>Exportação para CSV/Excel</li>
                <li>Sintaxe mista: use query("SELECT...") no editor Python</li>
            </ul>
            <p><b>Atalhos:</b></p>
            <ul>
                <li>F5 - Executar SQL</li>
                <li>Shift+F5 - Executar Python</li>
                <li>Ctrl+/ - Comentar linha</li>
                <li>Ctrl+, - Configurações de Atalhos</li>
            </ul>
            <p>Versão 1.0.0</p>
            """
        )
    
    def _show_settings(self):
        """Mostra diálogo de configurações"""
        dialog = SettingsDialog(self.shortcut_manager, theme_manager=self.theme_manager)
        if dialog.exec():
            QMessageBox.information(
                self,
                "Atalhos Salvos",
                "Os atalhos foram salvos com sucesso!\n\n"
                "Nota: Alguns atalhos podem exigir reinicialização da aplicação."
            )
    
    def _new_session(self):
        """Cria nova sessão"""
        # Guard para evitar criação duplicada
        if hasattr(self, '_creating_session') and self._creating_session:
            return
        self._creating_session = True
        
        try:
            # Se está no estado vazio, remover o placeholder
            self._hide_empty_state()
            
            session = self.session_manager.create_session()
            self._create_session_widget(session)
        finally:
            self._creating_session = False
    
    def _show_empty_state(self):
        """Mostra estado vazio quando não há sessões"""
        if hasattr(self, '_empty_state_widget') and self._empty_state_widget:
            return  # Já está mostrando
        
        # Criar widget de estado vazio
        from PyQt6.QtWidgets import QLabel, QPushButton
        
        self._empty_state_widget = QWidget()
        layout = QVBoxLayout(self._empty_state_widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Ícone/emoji grande
        icon_label = QLabel()
        if hasattr(qta, 'icon'):
            icon_label.setPixmap(qta.icon('mdi.note-text', color='#64b5f6').pixmap(16, 16))
        icon_label.setStyleSheet("font-size: 72px;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)
        
        # Texto principal
        title_label = QLabel("Nenhum script aberto")
        title_label.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: #cccccc;
            margin-top: 20px;
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # Subtítulo
        subtitle_label = QLabel("Crie uma nova sessão para começar a programar")
        subtitle_label.setStyleSheet("""
            font-size: 14px;
            color: #888888;
            margin-top: 10px;
        """)
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle_label)
        
        # Botão iniciar
        start_button = QPushButton("  Iniciar  ")
        start_button.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 12px 40px;
                font-size: 16px;
                font-weight: bold;
                border-radius: 4px;
                margin-top: 30px;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
            QPushButton:pressed {
                background-color: #004578;
            }
        """)
        start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        start_button.clicked.connect(self._new_session)
        layout.addWidget(start_button, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Adicionar como "aba" invisível ou substituir conteúdo
        self._empty_state_widget.setStyleSheet("background-color: #1e1e1e;")
        
        # Inserir antes do + (se existir)
        tab_count = self.session_tabs.count()
        if tab_count > 0 and self.session_tabs.tabText(tab_count - 1).strip() == "+":
            index = self.session_tabs.insertTab(tab_count - 1, self._empty_state_widget, "")
        else:
            index = self.session_tabs.addTab(self._empty_state_widget, "")
        
        # Esconder o tab do estado vazio
        self.session_tabs.tabBar().setTabVisible(index, False)
        self.session_tabs.setCurrentIndex(index)
    
    def _hide_empty_state(self):
        """Remove estado vazio"""
        if hasattr(self, '_empty_state_widget') and self._empty_state_widget:
            index = self.session_tabs.indexOf(self._empty_state_widget)
            if index >= 0:
                self.session_tabs.removeTab(index)
            self._empty_state_widget = None
    
    def _create_session_widget(self, session):
        """Cria widget para uma sessão e adiciona à aba"""
        widget = SessionWidget(session, theme_manager=self.theme_manager)
        
        # Conectar sinais do widget
        widget.execute_cross_syntax.connect(lambda code: self._execute_cross_syntax_for_session(session, code))
        widget.status_changed.connect(lambda msg: self._on_session_status_changed(session, msg))
        
        # Guardar referência
        self._session_widgets[session.session_id] = widget
        
        # Adicionar aba (antes do + se existir)
        tab_count = self.session_tabs.count()
        if tab_count > 0 and self.session_tabs.tabText(tab_count - 1).strip() == "+":
            index = self.session_tabs.insertTab(tab_count - 1, widget, session.title)
        else:
            index = self.session_tabs.addTab(widget, session.title)
        
        self.session_tabs.setCurrentIndex(index)
        
        return widget
    
    def _on_session_renamed(self, index: int, new_name: str):
        """Callback quando sessão é renomeada pelo componente SessionTabs"""
        widget = self.session_tabs.widget(index)
        if not isinstance(widget, SessionWidget):
            return
        
        widget.session.title = new_name.strip()
        self._save_sessions()
    
    def _rename_session_tab(self, index: int):
        """Renomeia aba de sessão ao dar duplo clique (método legado)"""
        widget = self.session_tabs.widget(index)
        if not isinstance(widget, SessionWidget):
            return
        
        current_name = self.session_tabs.tabText(index)
        
        from PyQt6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self,
            "Renomear Sessão",
            "Novo nome:",
            text=current_name
        )
        
        if ok and new_name.strip():
            self.session_tabs.setTabText(index, new_name.strip())
            widget.session.title = new_name.strip()
            self._save_sessions()
    
    def _close_session_tab(self, index: int):
        """Fecha aba de sessão"""
        widget = self.session_tabs.widget(index)
        if not isinstance(widget, SessionWidget):
            return
        
        # Guard para evitar criar sessão ao fechar
        self._closing_session = True
        
        try:
            # Cleanup e remover
            session_id = widget.session.session_id
            widget.cleanup()
            self.session_manager.close_session(session_id)
            del self._session_widgets[session_id]
            
            self.session_tabs.removeTab(index)
            self._save_sessions()
            
            # Verificar se não há mais sessões
            session_count = sum(1 for i in range(self.session_tabs.count()) if isinstance(self.session_tabs.widget(i), SessionWidget))
            if session_count == 0:
                self._show_empty_state()
        finally:
            self._closing_session = False
    
    def _on_session_tab_changed(self, index: int):
        """Evento quando muda de aba de sessão"""
        # Ignorar durante operações que alteram tabs
        if hasattr(self, '_restoring_sessions') and self._restoring_sessions:
            return
        if hasattr(self, '_creating_session') and self._creating_session:
            return
        if hasattr(self, '_closing_session') and self._closing_session:
            return
        
        # Se clicar no + cria nova sessão
        if self.session_tabs.tabText(index).strip() == "+":
            self._new_session()
            return
        
        widget = self.session_tabs.widget(index)
        if isinstance(widget, SessionWidget):
            self.session_manager.focus_session(widget.session.session_id)
    
    def _on_session_focused(self, session):
        """Callback quando uma sessão é focada"""
        # Atualizar status bar e painel de conexão com info da sessão
        if session.is_connected:
            # Atualizar status bar
            self.connection_status_bar.setText(session.connection_name)
            self.connection_status_bar.setStyleSheet("""
                QLabel {
                    color: #4ec9b0;
                    font-weight: bold;
                    padding: 0 15px;
                    border-right: 1px solid #3e3e42;
                }
            """)
            
            # Atualizar painel de conexão ativa
            config = self.connection_manager.get_connection_config(session.connection_name)
            if config:
                self.connection_panel.set_active_connection(
                    session.connection_name,
                    host=config.get('host', ''),
                    database=config.get('database', ''),
                    db_type=config.get('db_type', '')
                )
            else:
                self.connection_panel.set_active_connection(session.connection_name)
        else:
            # Desconectado
            self.connection_status_bar.setText("Desconectado")
            self.connection_status_bar.setStyleSheet("""
                QLabel {
                    color: #f48771;
                    font-weight: bold;
                    padding: 0 15px;
                    border-right: 1px solid #3e3e42;
                }
            """)
            
            # Limpar painel de conexão ativa
            self.connection_panel.set_disconnected()
        
        self.action_label.setText(f"Sessão: {session.title}")
    
    def _on_session_status_changed(self, session, message: str):
        """Callback quando status de uma sessão muda"""
        # Só atualiza se for a sessão focada
        if self.session_manager.focused_session == session:
            self.action_label.setText(message)
    
    def _get_current_session_widget(self) -> SessionWidget:
        """Retorna SessionWidget da aba ativa"""
        widget = self.session_tabs.currentWidget()
        if isinstance(widget, SessionWidget):
            return widget
        return None
    
    def _get_current_editor(self) -> UnifiedEditor:
        """Retorna editor da sessão ativa"""
        widget = self._get_current_session_widget()
        if widget:
            return widget.editor
        return None
    
    def _save_sessions(self):
        """Salva todas as sessões"""
        # Sincronizar código dos widgets para as sessões
        for session_id, widget in self._session_widgets.items():
            widget.sync_to_session()
        
        # Salvar via SessionManager
        self.session_manager.save_sessions()
        
        # Também salvar geometria da janela no workspace
        window_geometry = {
            'x': self.geometry().x(),
            'y': self.geometry().y(),
            'width': self.geometry().width(),
            'height': self.geometry().height(),
            'maximized': self.isMaximized()
        }
        
        dock_visible = self.connections_dock.isVisible() if hasattr(self, 'connections_dock') else True
        
        # Salvar no workspace manager (para geometria)
        # Nota: active_connection agora é por sessão, salvo junto com cada sessão
        self.workspace_manager.save_workspace(
            tabs=[],  # Não mais usado para abas
            active_tab=0,
            active_connection=None,  # Conexão agora é por sessão
            window_geometry=window_geometry,
            splitter_sizes=[],
            dock_visible=dock_visible
        )
    
    def _restore_sessions(self):
        """Restaura sessões salvas - carrega incrementalmente"""
        self._restoring_sessions = True
        
        # Carregar sessões do disco
        self.session_manager.load_sessions(self.connection_manager)
        
        # Salvar workspace para restaurar geometria depois
        workspace = self.workspace_manager.load_workspace()
        self._pending_workspace_restore = workspace
        
        # Fila de sessões para carregar incrementalmente
        self._sessions_to_load = list(self.session_manager.sessions)
        
        # Adicionar botão + como aba
        add_tab_widget = QWidget()
        add_tab_index = self.session_tabs.addTab(add_tab_widget, " + ")
        self.session_tabs.tabBar().setTabButton(add_tab_index, QTabBar.ButtonPosition.RightSide, None)
        self.session_tabs.tabBar().setTabButton(add_tab_index, QTabBar.ButtonPosition.LeftSide, None)
        
        self._restoring_sessions = False
        
        # Iniciar carregamento das sessões incrementalmente
        if self._sessions_to_load:
            QTimer.singleShot(50, self._load_next_session)
        else:
            # Se não há sessões, mostrar estado vazio
            self._show_empty_state()
    
    def _load_next_session(self):
        """Carrega a próxima sessão da fila"""
        if not self._sessions_to_load:
            # Todas as sessões carregadas, focar na sessão ativa
            focused = self.session_manager.focused_session
            if focused:
                index = self.session_manager.get_session_index(focused.session_id)
                if index >= 0:
                    self.session_tabs.setCurrentIndex(index)
            return
        
        session = self._sessions_to_load.pop(0)
        
        # Criar widget para a sessão
        self._create_session_widget(session)
        
        # Processar eventos pendentes da UI
        QApplication.processEvents()
        
        # Agendar próxima sessão
        QTimer.singleShot(10, self._load_next_session)
    
    def _restore_window_state(self):
        """Restaura geometria da janela, splitter e dock após inicialização"""
        if not hasattr(self, '_pending_workspace_restore'):
            return
        
        workspace = self._pending_workspace_restore
        
        # Restaurar geometria da janela
        geometry = workspace.get('window_geometry')
        if geometry:
            if geometry.get('maximized', False):
                self.showMaximized()
            else:
                self.setGeometry(
                    geometry.get('x', 100),
                    geometry.get('y', 100),
                    geometry.get('width', 1400),
                    geometry.get('height', 900)
                )
        
        # Restaurar visibilidade do dock
        dock_visible = workspace.get('dock_visible', True)
        if hasattr(self, 'connections_dock'):
            self.connections_dock.setVisible(dock_visible)
        
        # Restaurar conexão ativa (após UI estar pronta)
        if workspace.get('active_connection'):
            try:
                self._reconnect_saved_connection(workspace['active_connection'])
            except Exception as e:
                print(f"Não foi possível restaurar conexão: {e}")
        
        # Limpar referência
        del self._pending_workspace_restore
    
    def _reconnect_saved_connection(self, connection_name: str):
        """Reconecta à conexão salva automaticamente"""
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            return
        
        # Pegar senha se necessário
        password = ''
        if not config.get('use_windows_auth', False):
            # Tentar conectar sem senha primeiro (pode ter salvo)
            password = config.get('password', '')
        
        try:
            connector = self.connection_manager.create_connection(
                connection_name,
                config['db_type'],
                config['host'],
                config['port'],
                config['database'],
                config.get('username', ''),
                password,
                use_windows_auth=config.get('use_windows_auth', False)
            )
            
            self.connection_manager.mark_connection_used(connection_name)
            self._update_connection_status()
            self.action_label.setText(f"Reconectado a {connection_name}")
            
        except Exception as e:
            print(f"Erro ao reconectar {connection_name}: {e}")
            # Não falha silenciosamente - mostra na statusbar
            self.action_label.setText(f"Falha ao reconectar: {connection_name}")
    
    def _execute_cross_syntax_for_session(self, session, code: str):
        """Executa cross-syntax para uma sessão específica"""
        # TODO: Implementar cross-syntax por sessão
        # Por agora, usa o método global
        self._execute_cross_syntax(code)
    
    def closeEvent(self, event):
        """Ao fechar a janela"""
        # Salvar sessões antes de fechar
        self._save_sessions()
        
        # Cleanup de todas as sessões
        for widget in self._session_widgets.values():
            widget.cleanup()
        
        self.session_manager.cleanup_all()
        
        # Fechar conexões
        self.connection_manager.close_all()
        event.accept()
