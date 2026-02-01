"""
Janela principal da IDE DataPyn
"""
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QSplitter, QTabWidget, QMenuBar, QMenu, QToolBar,
                             QStatusBar, QMessageBox, QTextEdit, QDockWidget,
                             QLabel, QPushButton, QFileDialog, QLineEdit, QTabBar,
                             QGroupBox, QListWidget, QListWidgetItem, QFrame)
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
from src.core import ResultsManager, ShortcutManager, WorkspaceManager, ThemeManager
from src.core.mixed_executor import MixedLanguageExecutor
from .connection_edit_dialog import ConnectionEditDialog
from .connections_manager_dialog import ConnectionsManagerDialog
from .results_viewer import ResultsViewer
from .settings_dialog import SettingsDialog


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
        self.mixed_executor = MixedLanguageExecutor(None, self.results_manager)
        
        # Threads para execução em background
        self._worker_threads = []  # Mantém referência para não ser coletado pelo GC
        
        # Ícones
        self.icons = self._setup_icons()
        
        self._setup_ui()
        self._create_menus()
        self._create_toolbar()
        self._create_statusbar()
        self._setup_shortcuts()
        
        # Aplicar tema inicial
        self._apply_app_theme()
        
        # Timer para atualizar status
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)
    
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
        
        # Splitter principal (vertical)
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # === PARTE SUPERIOR: Abas de Editores ===
        editor_container = QWidget()
        editor_layout = QVBoxLayout(editor_container)
        editor_layout.setContentsMargins(5, 5, 5, 5)
        
        # Header simples
        self.editor_header = QLabel("Editor de Código - F5: SQL | Shift+Enter: Python | Ctrl+Shift+F5: Cross-Syntax")
        self.editor_header.setStyleSheet("color: #569cd6; font-weight: bold; padding: 5px;")
        editor_layout.addWidget(self.editor_header)
        
        # TabWidget para múltiplos editores
        self.editor_tabs = QTabWidget()
        self.editor_tabs.setTabsClosable(True)
        self.editor_tabs.tabCloseRequested.connect(self._close_tab)
        self.editor_tabs.tabBarDoubleClicked.connect(self._rename_tab)
        # Estilos aplicados via _apply_app_theme()
        
        editor_layout.addWidget(self.editor_tabs)
        
        # Criar primeira aba e restaurar workspace
        self._restore_workspace()
        
        self.main_splitter.addWidget(editor_container)
        
        # === PARTE INFERIOR: Resultados e Output ===
        self.bottom_tabs = QTabWidget()
        
        # Tab: Resultados da Query
        self.results_viewer = ResultsViewer(theme_manager=self.theme_manager)
        self.bottom_tabs.addTab(self.results_viewer, "Resultados")
        
        # Tab: Output
        self.python_output = QTextEdit()
        self.python_output.setReadOnly(True)
        self.python_output.setFont(QFont("Consolas", 10))
        self.bottom_tabs.addTab(self.python_output, "Output")
        
        # Tab: Variáveis em Memória
        self.variables_viewer = ResultsViewer(theme_manager=self.theme_manager)
        self.bottom_tabs.addTab(self.variables_viewer, "Variáveis em Memória")
        
        self.main_splitter.addWidget(self.bottom_tabs)
        
        # Tamanho inicial (60% editores, 40% resultados)
        self.main_splitter.setSizes([540, 360])
        
        main_layout.addWidget(self.main_splitter)
        
        # Dock para conexões (lateral esquerda)
        self._create_connections_dock()
    
    def _create_connections_dock(self):
        """Cria painel lateral de conexões"""
        self.connections_dock = QDockWidget("Conexões", self)
        self.connections_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        
        dock_widget = QWidget()
        dock_layout = QVBoxLayout(dock_widget)
        dock_layout.setContentsMargins(5, 5, 5, 5)
        dock_layout.setSpacing(10)
        
        # === GRUPO: CONEXÃO ATIVA ===
        active_group = QGroupBox("Conexão Ativa")
        active_layout = QVBoxLayout(active_group)
        active_layout.setContentsMargins(8, 15, 8, 8)
        
        # Nome da conexão ativa
        self.active_conn_name_label = QLabel("Nenhuma")
        self.active_conn_name_label.setProperty("class", "connection-name")
        active_layout.addWidget(self.active_conn_name_label)
        
        # Info da conexão (servidor/banco)
        self.active_conn_info_label = QLabel("")
        self.active_conn_info_label.setWordWrap(True)
        self.active_conn_info_label.setProperty("class", "connection-info")
        active_layout.addWidget(self.active_conn_info_label)
        
        # Botão desconectar
        self.btn_disconnect = QPushButton("Desconectar")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self._disconnect)
        self.btn_disconnect.setObjectName("btnDisconnect")
        active_layout.addWidget(self.btn_disconnect)
        
        dock_layout.addWidget(active_group)
        
        # === GRUPO: CONEXÕES SALVAS ===
        saved_group = QGroupBox("Conexões Salvas")
        saved_layout = QVBoxLayout(saved_group)
        saved_layout.setContentsMargins(8, 15, 8, 8)
        
        # Lista de conexões
        self.connections_list = QListWidget()
        self.connections_list.setMinimumHeight(150)
        self.connections_list.itemDoubleClicked.connect(self._on_connection_double_click)
        saved_layout.addWidget(self.connections_list)
        
        # Botões de ação
        btn_layout = QHBoxLayout()
        
        btn_new = QPushButton("+ Nova")
        btn_new.clicked.connect(self._new_connection)
        btn_new.setObjectName("btnPrimary")
        btn_layout.addWidget(btn_new)
        
        btn_manage = QPushButton("Gerenciar")
        btn_manage.clicked.connect(self._manage_connections)
        btn_layout.addWidget(btn_manage)
        
        saved_layout.addLayout(btn_layout)
        
        dock_layout.addWidget(saved_group)
        dock_layout.addStretch()
        
        self.connections_dock.setWidget(dock_widget)
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
        
        # Preencher lista de conexões
        self._refresh_connections_list()
    
    def _refresh_connections_list(self):
        """Atualiza lista de conexões salvas"""
        self.connections_list.clear()
        
        connection_names = self.connection_manager.get_saved_connections()
        for conn_name in connection_names:
            config = self.connection_manager.get_connection_config(conn_name)
            if not config:
                continue
                
            item = QListWidgetItem()
            
            # Texto com nome e info
            db_type = config.get('db_type', 'SQL Server')
            host = config.get('host', '')
            database = config.get('database', '')
            
            item.setText(conn_name)
            item.setToolTip(f"{db_type}\n{host}/{database}")
            item.setData(Qt.ItemDataRole.UserRole, conn_name)
            
            # Cor personalizada se tiver
            color = config.get('color', '')
            if color:
                item.setForeground(QColor(color))
            
            self.connections_list.addItem(item)
    
    def _on_connection_double_click(self, item: QListWidgetItem):
        """Conecta ao dar duplo clique na conexão"""
        conn_name = item.data(Qt.ItemDataRole.UserRole)
        if conn_name:
            self._quick_connect(conn_name)
    
    def _quick_connect(self, connection_name: str):
        """Conecta rapidamente a uma conexão salva"""
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            QMessageBox.warning(self, "Erro", f"Conexão '{connection_name}' não encontrada")
            return
        
        # Pegar senha se necessário
        password = ''
        if not config.get('use_windows_auth', False):
            password = config.get('password', '')
        
        try:
            self.connection_manager.create_connection(
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
            self.action_label.setText(f"Conectado a {connection_name}")
            
        except Exception as e:
            QMessageBox.critical(self, "Erro de Conexão", f"Não foi possível conectar:\n{str(e)}")
    
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
        
        run_sql_action = QAction("Executar &SQL", self)
        if HAS_QTAWESOME:
            run_sql_action.setIcon(self.icons['database'])
        run_sql_action.setShortcut("F5")
        run_sql_action.triggered.connect(lambda: self._execute_sql(self._get_current_editor().get_selected_or_all_text() if self._get_current_editor() else ''))
        run_menu.addAction(run_sql_action)
        
        run_python_action = QAction("Executar &Python", self)
        if HAS_QTAWESOME:
            run_python_action.setIcon(qta.icon('fa5b.python'))
        run_python_action.setShortcut("Shift+Return")
        run_python_action.triggered.connect(lambda: self._execute_python(self._get_current_editor().get_selected_or_all_text() if self._get_current_editor() else ''))
        run_menu.addAction(run_python_action)
        
        run_cross_action = QAction("Executar &Cross", self)
        if HAS_QTAWESOME:
            run_cross_action.setIcon(qta.icon('fa5s.code'))
        run_cross_action.setShortcut("Ctrl+Shift+F5")
        run_cross_action.triggered.connect(lambda: self._execute_cross_syntax(self._get_current_editor().get_selected_or_all_text() if self._get_current_editor() else ''))
        run_menu.addAction(run_cross_action)
        
        run_menu.addSeparator()
        
        clear_results_action = QAction("&Limpar Resultados", self)
        if HAS_QTAWESOME:
            clear_results_action.setIcon(self.icons['trash'])
        clear_results_action.setShortcut("Ctrl+Shift+C")
        clear_results_action.triggered.connect(self._clear_results)
        run_menu.addAction(clear_results_action)
        
        # Menu Exibir (Temas)
        view_menu = menubar.addMenu("E&xibir")
        
        # Submenu de Temas
        theme_menu = view_menu.addMenu("&Tema")
        self.theme_actions = {}
        current_theme = self.theme_manager.get_theme_name()
        
        for theme_id, theme_name in self.theme_manager.get_available_themes():
            action = QAction(theme_name, self)
            action.setCheckable(True)
            action.setChecked(theme_id == current_theme)
            action.triggered.connect(lambda checked, t=theme_id: self._change_theme(t))
            theme_menu.addAction(action)
            self.theme_actions[theme_id] = action
        
        view_menu.addSeparator()
        
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
        """Cria a toolbar"""
        toolbar = QToolBar("Principal")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # Botões
        btn_new_conn = QPushButton("Nova Conexão")
        if HAS_QTAWESOME:
            btn_new_conn.setIcon(self.icons['plug'])
        btn_new_conn.clicked.connect(self._new_connection)
        toolbar.addWidget(btn_new_conn)
        
        toolbar.addSeparator()
        
        btn_run_sql = QPushButton("SQL (F5)")
        if HAS_QTAWESOME:
            btn_run_sql.setIcon(self.icons['database'])
        btn_run_sql.clicked.connect(lambda: self._execute_sql(self._get_current_editor().get_selected_or_all_text() if self._get_current_editor() else ''))
        toolbar.addWidget(btn_run_sql)
        
        btn_run_python = QPushButton("Python (Shift+Enter)")
        if HAS_QTAWESOME:
            btn_run_python.setIcon(qta.icon('fa5b.python'))
        btn_run_python.clicked.connect(lambda: self._execute_python(self._get_current_editor().get_selected_or_all_text() if self._get_current_editor() else ''))
        toolbar.addWidget(btn_run_python)
        
        btn_run_cross = QPushButton("Cross (Ctrl+Shift+F5)")
        if HAS_QTAWESOME:
            btn_run_cross.setIcon(qta.icon('fa5s.code'))
        btn_run_cross.clicked.connect(lambda: self._execute_cross_syntax(self._get_current_editor().get_selected_or_all_text() if self._get_current_editor() else ''))
        toolbar.addWidget(btn_run_cross)
        
        toolbar.addSeparator()
        
        btn_clear = QPushButton("Limpar Resultados")
        if HAS_QTAWESOME:
            btn_clear.setIcon(self.icons['trash'])
        btn_clear.clicked.connect(self._clear_results)
        toolbar.addWidget(btn_clear)
    
    def _create_statusbar(self):
        """Cria a barra de status"""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        
        # Label de conexão (sempre visível à esquerda)
        self.connection_status_bar = QLabel("Desconectado")
        self.connection_status_bar.setStyleSheet("""
            QLabel {
                color: #f48771;
                font-weight: bold;
                padding: 0 15px;
                border-right: 1px solid #3e3e42;
            }
        """)
        self.statusbar.addWidget(self.connection_status_bar)
        
        # Label de ação executada (meio)
        self.action_label = QLabel("Pronto")
        self.action_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                padding: 0 15px;
            }
        """)
        self.statusbar.addWidget(self.action_label, 1)  # stretch=1 para ocupar espaço
        
        # Label de execução com tempo (direita)
        self.execution_label = QLabel("")
        self.execution_label.setStyleSheet("""
            QLabel {
                color: #FFD700;
                font-weight: bold;
                padding: 0 10px;
            }
        """)
        self.statusbar.addPermanentWidget(self.execution_label)
        
        # Timer para atualizar tempo de execução
        self._is_executing = False
        self._execution_timer = QElapsedTimer()
        self._execution_update_timer = QTimer()
        self._execution_update_timer.timeout.connect(self._update_execution_time)
    
    def _start_execution_timer(self, mode: str = ""):
        """Inicia o timer de execução"""
        self._is_executing = True
        self._execution_mode = mode
        self._execution_timer.start()
        self._execution_update_timer.start(100)  # Atualiza a cada 100ms
        self._update_execution_time()
    
    def _stop_execution_timer(self):
        """Para o timer de execução e mostra tempo final"""
        self._execution_update_timer.stop()
        if self._is_executing:
            elapsed = self._execution_timer.elapsed() / 1000.0
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
        """Desconecta da base atual"""
        if self.connection_manager.active_connection:
            self.connection_manager.close_connection(self.connection_manager.active_connection)
            self._update_connection_status()
            self.action_label.setText("Desconectado")
    
    def _update_connection_status(self):
        """Atualiza status da conexão"""
        active_conn = self.connection_manager.get_active_connection()
        active_name = self.connection_manager.active_connection
        
        if active_conn and active_conn.is_connected():
            # === DOCK LATERAL ===
            self.active_conn_name_label.setText(active_name)
            self.active_conn_name_label.setStyleSheet("""
                color: #4ec9b0; 
                font-weight: bold; 
                font-size: 13px;
                padding: 5px;
            """)
            
            params = active_conn.connection_params
            host = params.get('host', 'localhost')
            db = params.get('database', '')
            info = f"{host}\n{db}"
            self.active_conn_info_label.setText(info)
            self.btn_disconnect.setEnabled(True)
            
            # Destacar conexão ativa na lista
            for i in range(self.connections_list.count()):
                item = self.connections_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == active_name:
                    self.connections_list.setCurrentItem(item)
                    break
            
            # === STATUSBAR ===
            conn_display = f"{active_name} @ {host}/{db}"
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
            conn_config = self.connection_manager.get_connection_config(active_name)
            status_color = conn_config.get('color', '#007acc') if conn_config else '#007acc'
            if not status_color:
                status_color = '#007acc'  # Cor padrão azul se não configurada
            self.statusbar.setStyleSheet(f"QStatusBar {{ background-color: {status_color}; color: white; }}")
        else:
            # === DOCK LATERAL ===
            self.active_conn_name_label.setText("Nenhuma")
            self.active_conn_name_label.setStyleSheet("""
                color: #f48771; 
                font-weight: bold; 
                font-size: 13px;
                padding: 5px;
            """)
            self.active_conn_info_label.setText("")
            self.btn_disconnect.setEnabled(False)
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
            self.statusbar.setStyleSheet("QStatusBar { background-color: #3e3e42; color: white; }")
    
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
        
        active_conn = self.connection_manager.get_active_connection()
        if not active_conn:
            QMessageBox.warning(self, "Atenção", "Não há conexão ativa. Conecte-se a um banco de dados primeiro.")
            return
        
        # Detectar comando USE database (executa síncrono pois é rápido)
        use_match = re.match(r'^\s*USE\s+\[?([^\]\s;]+)\]?\s*;?\s*$', query, re.IGNORECASE)
        if use_match:
            database_name = use_match.group(1)
            try:
                self._start_execution_timer("SQL")
                self.action_label.setText(f"[SQL] Alterando para banco {database_name}...")
                
                active_conn.change_database(database_name)
                
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
        worker = SqlWorker(active_conn, query)
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
            self.results_viewer.display_dataframe(df, 'Resultado SQL')
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
                self.results_viewer.display_dataframe(result_value, 'result')
                self.bottom_tabs.setCurrentIndex(0)
                rows = len(result_value)
                self._log(f"[Python] DataFrame exibido ({rows:,} linhas)")
                
            elif isinstance(result_value, (list, tuple)) and len(result_value) > 0:
                # Lista/tupla → tentar converter para DataFrame
                try:
                    df = pd.DataFrame(result_value)
                    self.results_viewer.display_dataframe(df, 'result')
                    self.bottom_tabs.setCurrentIndex(0)
                    self._log(f"[Python] Lista exibida como tabela ({len(result_value)} itens)")
                except:
                    self._log(repr(result_value))
                    
            elif isinstance(result_value, dict):
                # Dict → tentar converter para DataFrame
                try:
                    df = pd.DataFrame([result_value]) if not isinstance(list(result_value.values())[0], (list, tuple)) else pd.DataFrame(result_value)
                    self.results_viewer.display_dataframe(df, 'result')
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
        
        # Atualiza o conector no mixed_executor
        active_conn = self.connection_manager.get_active_connection()
        if not active_conn or not active_conn.is_connected():
            self._stop_execution_timer()
            self._mark_tab_running(False, running_tab_index)
            QMessageBox.warning(self, "Atenção", "Nenhuma conexão ativa. Conecte a um banco de dados primeiro.")
            self.action_label.setText("[Cross-Syntax] Sem conexão")
            return
        
        self.mixed_executor.db_connector = active_conn
        
        # Criar thread e worker
        thread = QThread()
        worker = CrossSyntaxWorker(self.mixed_executor, code, self.results_manager.get_namespace())
        worker.moveToThread(thread)
        
        # Conectar sinais
        thread.started.connect(worker.run)
        worker.finished.connect(lambda result, err: self._on_cross_finished(result, err, code, thread, running_tab_index))
        
        # Manter referência
        self._worker_threads.append((thread, worker))
        
        # Iniciar
        thread.start()
    
    def _on_cross_finished(self, result, error, code, thread, tab_index):
        """Callback quando Cross-Syntax termina"""
        self._stop_execution_timer()
        
        # Remover marcação de rodando
        self._mark_tab_running(False, tab_index)
        
        # Limpar thread da lista
        self._worker_threads = [(t, w) for t, w in self._worker_threads if t != thread]
        thread.quit()
        thread.wait()
        
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
                var_value = self.results_manager.get_namespace().get(var_name)
                if var_value is not None:
                    if isinstance(var_value, pd.DataFrame):
                        rows = len(var_value)
                        self._log(f"[Cross-Syntax] Variável '{var_name}' criada ({rows:,} linhas)")
                    else:
                        self._log(f"[Cross-Syntax] Variável '{var_name}' criada")
        
        # Atualiza resultados se houver DataFrame retornado
        if result.get('result') is not None:
            if isinstance(result['result'], pd.DataFrame):
                self.results_viewer.display_dataframe(result['result'], 'result')
                self.bottom_tabs.setCurrentIndex(0)
        
        # Atualiza variáveis
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
            tab_index = self.editor_tabs.currentIndex()
        
        if tab_index < 0 or tab_index >= self.editor_tabs.count():
            return tab_index
        
        current_title = self.editor_tabs.tabText(tab_index)
        
        if is_running:
            # Adicionar "(run)" se não existir
            if "(run)" not in current_title:
                self.editor_tabs.setTabText(tab_index, f"{current_title} (run)")
        else:
            # Remover "(run)"
            new_title = current_title.replace(" (run)", "")
            self.editor_tabs.setTabText(tab_index, new_title)
        
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
        self.python_output.append(f"[{timestamp}] {message}")
    
    def _show_error(self, error_msg: str):
        """Mostra erro no Output em vermelho e alterna para a aba de Output"""
        # Adiciona timestamp e erro em vermelho usando HTML
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        error_html = f'<span style="color: #ff6b6b; font-weight: bold;">[{timestamp}] {error_msg}</span>'
        self.python_output.append(error_html)
        
        # Alterna para a aba de Output (índice 1)
        self.bottom_tabs.setCurrentIndex(1)
        
        # Scroll para o final
        scrollbar = self.python_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _update_variables_view(self):
        """Atualiza visualização de variáveis em memória"""
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
            self.results_viewer.clear()
            self.variables_viewer.clear()
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
                    editor.setText(content)
                    
                    # Detecta tipo de arquivo e ajusta lexer
                    if filename.endswith('.py'):
                        editor.set_lexer_type('python')
                    else:
                        editor.set_lexer_type('sql')
                    
                    # Atualizar título da aba
                    import os
                    tab_title = os.path.basename(filename)
                    current_index = self.editor_tabs.currentIndex()
                    self.editor_tabs.setTabText(current_index, tab_title)
    
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
            current_index = self.editor_tabs.currentIndex()
            self.editor_tabs.setTabText(current_index, tab_title)
            
            # Salvar workspace
            self._save_workspace()
    
    def _update_status(self):
        """Atualiza status periodicamente"""
        # Verifica se conexão ainda está ativa
        active_conn = self.connection_manager.get_active_connection()
        if active_conn and not active_conn.is_connected():
            self._update_connection_status()
    
    def _change_theme(self, theme_id: str):
        """Muda o tema da aplicação"""
        self.theme_manager.save_theme(theme_id)
        
        # Atualizar checkmarks do menu
        for tid, action in self.theme_actions.items():
            action.setChecked(tid == theme_id)
        
        # Aplicar tema nos editores
        for i in range(self.editor_tabs.count()):
            widget = self.editor_tabs.widget(i)
            if isinstance(widget, UnifiedEditor):
                widget.apply_theme(self.theme_manager)
        
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
        
        # Atualizar ResultsViewers se existirem
        if hasattr(self, 'results_viewer'):
            self.results_viewer.set_theme_manager(self.theme_manager)
        if hasattr(self, 'variables_viewer'):
            self.variables_viewer.set_theme_manager(self.theme_manager)
        
        # Atualizar editores
        if hasattr(self, 'editor_tabs'):
            for i in range(self.editor_tabs.count()):
                widget = self.editor_tabs.widget(i)
                if hasattr(widget, 'apply_theme'):
                    widget.apply_theme(self.theme_manager)
    
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
    
    def _new_tab(self):
        """Cria nova aba de editor"""
        # Criar editor
        editor = UnifiedEditor(lexer_type='sql', theme_manager=self.theme_manager)
        editor.execute_sql.connect(self._execute_sql)
        editor.execute_python.connect(self._execute_python)
        editor.execute_cross_syntax.connect(self._execute_cross_syntax)
        
        # Adicionar aba ANTES do botão +
        tab_count = self.editor_tabs.count()
        # Contar apenas editores (excluir botão +)
        editor_count = sum(1 for i in range(tab_count) if isinstance(self.editor_tabs.widget(i), UnifiedEditor))
        tab_name = f"Script {editor_count + 1}"
        
        # Inserir antes da última aba (botão +)
        insert_index = tab_count - 1 if tab_count > 0 else 0
        index = self.editor_tabs.insertTab(insert_index, editor, tab_name)
        self.editor_tabs.setCurrentIndex(index)
        
        # Salvar workspace
        self._save_workspace()
    
    def _rename_tab(self, index: int):
        """Renomeia aba ao dar duplo clique"""
        # Verificar se é editor
        widget = self.editor_tabs.widget(index)
        if not isinstance(widget, UnifiedEditor):
            return
        
        current_name = self.editor_tabs.tabText(index)
        
        from PyQt6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self,
            "Renomear Aba",
            "Novo nome:",
            text=current_name
        )
        
        if ok and new_name.strip():
            self.editor_tabs.setTabText(index, new_name.strip())
            self._save_workspace()
    
    def _close_tab(self, index: int):
        """Fecha aba de editor"""
        # Verificar se é editor
        widget = self.editor_tabs.widget(index)
        if not isinstance(widget, UnifiedEditor):
            return
        
        # Contar apenas editores
        editor_count = sum(1 for i in range(self.editor_tabs.count()) if isinstance(self.editor_tabs.widget(i), UnifiedEditor))
        
        # Não permitir fechar última aba
        if editor_count <= 1:
            QMessageBox.warning(self, "Atenção", "Não é possível fechar a última aba.")
            return
        
        # Remover aba
        self.editor_tabs.removeTab(index)
        
        # Salvar workspace
        self._save_workspace()
    
    def _get_current_editor(self) -> UnifiedEditor:
        """Retorna editor da aba ativa"""
        widget = self.editor_tabs.currentWidget()
        if isinstance(widget, UnifiedEditor):
            return widget
        return None
    
    def _on_tab_changed(self, index: int):
        """Evento quando muda de aba - se clicar no + cria nova aba"""
        if self.editor_tabs.tabText(index).strip() == "+":
            self._new_tab()
    
    def _save_workspace(self):
        """Salva workspace atual (abas, conexões, código, janela)"""
        tabs = []
        
        for i in range(self.editor_tabs.count()):
            widget = self.editor_tabs.widget(i)
            # Pular se for o botão +
            if not isinstance(widget, UnifiedEditor):
                continue
            
            title = self.editor_tabs.tabText(i)
            
            tabs.append({
                'code': widget.text(),
                'connection': None,
                'title': title
            })
        
        active_tab = self.editor_tabs.currentIndex()
        
        # Pegar nome da conexão ativa
        active_conn_name = None
        if self.connection_manager.active_connection:
            active_conn_name = self.connection_manager.active_connection
        
        # Geometria da janela
        window_geometry = {
            'x': self.geometry().x(),
            'y': self.geometry().y(),
            'width': self.geometry().width(),
            'height': self.geometry().height(),
            'maximized': self.isMaximized()
        }
        
        # Tamanhos do splitter
        splitter_sizes = self.main_splitter.sizes()
        
        # Visibilidade do dock de conexões
        dock_visible = self.connections_dock.isVisible() if hasattr(self, 'connections_dock') else True
        
        self.workspace_manager.save_workspace(
            tabs, 
            active_tab, 
            active_conn_name,
            window_geometry=window_geometry,
            splitter_sizes=splitter_sizes,
            dock_visible=dock_visible
        )
    
    def _restore_workspace(self):
        """Restaura workspace salvo (abas, conexões, código)"""
        workspace = self.workspace_manager.load_workspace()
        
        # Salvar workspace para restaurar geometria depois
        self._pending_workspace_restore = workspace
        
        # Criar abas
        for tab_data in workspace['tabs']:
            editor = UnifiedEditor(lexer_type='sql', theme_manager=self.theme_manager)
            editor.execute_sql.connect(self._execute_sql)
            editor.execute_python.connect(self._execute_python)
            editor.execute_cross_syntax.connect(self._execute_cross_syntax)
            
            # Restaurar código
            editor.setText(tab_data.get('code', ''))
            
            # Adicionar aba
            title = tab_data.get('title', f'Script {self.editor_tabs.count() + 1}')
            self.editor_tabs.addTab(editor, title)
        
        # Ativar aba salva
        if 0 <= workspace['active_tab'] < self.editor_tabs.count():
            self.editor_tabs.setCurrentIndex(workspace['active_tab'])
        
        # Adicionar botão + como última aba (sem fechar)
        add_tab_widget = QWidget()
        add_tab_index = self.editor_tabs.addTab(add_tab_widget, " + ")
        # Configura a aba + para ficar menor
        self.editor_tabs.tabBar().setTabButton(add_tab_index, QTabBar.ButtonPosition.RightSide, None)
        self.editor_tabs.tabBar().setTabButton(add_tab_index, QTabBar.ButtonPosition.LeftSide, None)
        
        # Conectar clique na aba + para criar nova aba
        self.editor_tabs.currentChanged.connect(self._on_tab_changed)
    
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
        
        # Restaurar tamanhos do splitter
        splitter_sizes = workspace.get('splitter_sizes')
        if splitter_sizes and len(splitter_sizes) >= 2:
            self.main_splitter.setSizes(splitter_sizes)
        
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
    
    def closeEvent(self, event):
        """Ao fechar a janela"""
        # Salvar workspace antes de fechar
        self._save_workspace()
        
        # Fechar conexões
        self.connection_manager.close_all()
        event.accept()
