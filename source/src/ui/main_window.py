"""
Janela principal da IDE DataPyn
"""
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QSplitter, QTabWidget, QMenuBar, QMenu, QToolBar,
                             QStatusBar, QMessageBox, QTextEdit, QDockWidget,
                             QLabel, QPushButton, QFileDialog, QLineEdit, QTabBar,
                             QGroupBox, QListWidget, QListWidgetItem, QFrame,
                             QApplication)
from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, QThread, pyqtSignal, QObject, QSettings
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QFont, QColor
import sys
import re
import logging
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
from src.ui.components.output_panel import OutputPanel
from src.ui.components.variables_panel import VariablesPanel
from src.ui.docking import DockingMainWindow
from src.design_system.tokens import get_colors, DARK_COLORS


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


# ConnectionWorker REMOVIDO - cada aba gerencia sua própria conexão via SessionWidget


class PythonWorker(QObject):
    """Worker centralizado para execução Python em background"""
    finished = pyqtSignal(object, str, str, dict)  # (result, output, error, namespace)
    
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
            
            result_value = self._execute_centralized()
            
            sys.stdout = old_stdout
            output = captured_output.getvalue()
            
            # Retornar namespace atualizado
            self.finished.emit(result_value, output, '', self.namespace)
        except Exception as e:
            sys.stdout = old_stdout
            self.finished.emit(None, '', traceback.format_exc(), self.namespace)
    
    def _execute_centralized(self):
        """Execução centralizada - todas as execuções Python passam aqui"""
        code = self.code.strip()
        if not code:
            return None
        
        # Limpar linhas vazias e comentários
        lines = [line for line in code.split('\n') if line.strip() and not line.strip().startswith('#')]
        
        if not lines:
            return None
        
        # CASO 1: Uma linha só
        if len(lines) == 1:
            try:
                # Tenta avaliar como expressão primeiro
                return eval(lines[0], self.namespace)
            except:
                # Se falhar, executa como statement
                exec(lines[0], self.namespace)
                return None
        
        # CASO 2: Múltiplas linhas
        # Executa todas exceto a última
        exec_code = '\n'.join(lines[:-1])
        exec(exec_code, self.namespace)
        
        # Tenta a última linha como expressão
        last_line = lines[-1]
        try:
            return eval(last_line, self.namespace)
        except:
            # Se falhar, executa como statement
            exec(last_line, self.namespace)
            return None


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


class MainWindow(DockingMainWindow):
    """Janela principal da IDE"""
    
    def __init__(self):
        # Inicializar atributos ANTES de chamar super().__init__()
        # para evitar que DockingMainWindow._setup_ui() acesse atributos não inicializados
        
        # Managers (ConnectionManager agora é APENAS para configurações, não conexões ativas)
        self.connection_manager = ConnectionManager()  # Só para gerenciar configs salvas
        self.results_manager = ResultsManager()
        self.shortcut_manager = ShortcutManager()
        self.workspace_manager = WorkspaceManager()
        self.theme_manager = ThemeManager()
        self.theme_manager.set_editor_theme('monokai')  # Tema específico para editores de código
        self.session_manager = SessionManager()  # Novo: Gerenciador de sessões
        self.mixed_executor = MixedLanguageExecutor(None, self.results_manager)
        
        # Mapeia session_id -> SessionWidget
        self._session_widgets: dict = {}
        
        # Widget de estado vazio (quando não há sessões)
        self._empty_state_widget = None
        
        # Threads para execução em background
        self._worker_threads = []  # Mantém referência para não ser coletado pelo GC
        
        # Sistema de gerenciamento inteligente de arquivos
        self._original_file_path = None      # Caminho do arquivo original aberto (sql/py/dpw)
        self._original_file_type = None      # Tipo: 'sql', 'python', 'workspace'
        self._current_context = 'workspace'   # Contexto atual: 'sql', 'python', 'workspace'
        
        # Ícones
        self.icons = self._setup_icons()
        
        # Agora chama super().__init__() que vai inicializar o docking system
        super().__init__()
        
        # Habilita aninhamento avançado e configurações especiais de dock
        self.setDockNestingEnabled(True)
        self.setCorner(Qt.Corner.TopLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea) 
        self.setCorner(Qt.Corner.TopRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        
        # Finalizar configuração do docking system
        self.finish_docking_setup()
        
        # Aplicar tema após configurar tema dos editores
        self._apply_app_theme()
        
        # Configurar UI específica da MainWindow
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
        
        # Atualizar título inicial da janela
        self._update_window_title()
    
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
        """Retorna um objeto compatível com BottomTabs usando os painéis globais"""
        # Retorna um mock object que redireciona para os painéis dockable
        class DockableBottomTabsCompat:
            def __init__(self, main_window):
                self.main_window = main_window
                
            def setCurrentIndex(self, index):
                """Simula mudança de aba ativa"""
                if index == 0:  # Results
                    self.main_window.show_panel('results')
                    results_panel = self.main_window.get_panel('results')
                    if results_panel and results_panel.tab_widget.count() > 0:
                        results_panel.tab_widget.setCurrentIndex(0)
                elif index == 1:  # Output  
                    self.main_window.show_panel('output')
                elif index == 2:  # Variables
                    self.main_window.show_panel('variables')
            
            @property  
            def results_viewer(self):
                return self.main_window.global_results_viewer
                
            @property
            def output_panel(self):
                return self.main_window.global_output_panel
                
            @property 
            def variables_panel(self):
                return self.main_window.global_variables_panel
            
            def log(self, message, prefix="INFO"):
                """Compatibilidade: log para output global"""
                if self.main_window.global_output_panel:
                    self.main_window.global_output_panel.log(message, prefix)
            
            def log_error(self, message):
                """Compatibilidade: log de erro para output global"""
                if self.main_window.global_output_panel:
                    self.main_window.global_output_panel.error(message)
                    
            def error(self, message):
                """Compatibilidade: alias para log_error"""
                self.log_error(message)
                
            def log_success(self, message):
                """Compatibilidade: log de sucesso para output global"""
                if self.main_window.global_output_panel:
                    self.main_window.global_output_panel.success(message)
                    
            def log_warning(self, message):
                """Compatibilidade: log de warning para output global"""
                if self.main_window.global_output_panel:
                    self.main_window.global_output_panel.warning(message)
                    
            def set_results(self, df, title="Resultado", query_info=None):
                """Compatibilidade: define resultados no painel global"""
                if self.main_window.global_results_viewer:
                    self.main_window.global_results_viewer.display_dataframe(df, title)
                    
            def set_variables(self, variables_dict):
                """Compatibilidade: define variáveis no painel global"""
                if self.main_window.global_variables_panel:
                    self.main_window.global_variables_panel.set_variables(variables_dict)
                    
            def show_output(self):
                """Compatibilidade: mostra painel de output"""
                self.main_window.show_panel('output')
                
            def clear_output(self):
                """Compatibilidade: limpa output global"""
                if self.main_window.global_output_panel:
                    self.main_window.global_output_panel.clear()
                    
            @property
            def output_text(self):
                """Compatibilidade: acesso ao texto do output global"""
                if self.main_window.global_output_panel:
                    return self.main_window.global_output_panel
                return None
        
        return DockableBottomTabsCompat(self)
        
    def _get_bottom_tabs_instance(self):
        """Retorna uma instancia unica do BottomTabs para compatibilidade"""
        if not hasattr(self, '_bottom_tabs_cache'):
            # Criar instância única da classe de compatibilidade
            class DockableBottomTabsCompat:
                def __init__(self, main_window):
                    self.main_window = main_window
                    
                def setCurrentIndex(self, index):
                    """Simula mudança de aba ativa"""
                    if index == 0:  # Results
                        self.main_window.show_panel('results')
                        results_panel = self.main_window.get_panel('results')
                        if results_panel and results_panel.tab_widget.count() > 0:
                            results_panel.tab_widget.setCurrentIndex(0)
                    elif index == 1:  # Output  
                        self.main_window.show_panel('output')
                    elif index == 2:  # Variables
                        self.main_window.show_panel('variables')
                
                @property  
                def results_viewer(self):
                    return self.main_window.global_results_viewer
                    
                @property
                def output_panel(self):
                    return self.main_window.global_output_panel
                    
                @property 
                def variables_panel(self):
                    return self.main_window.global_variables_panel
                
                def log(self, message, prefix="INFO"):
                    """Compatibilidade: log para output global"""
                    if self.main_window.global_output_panel:
                        self.main_window.global_output_panel.log(message, prefix)
                
                def log_error(self, message):
                    """Compatibilidade: log de erro para output global"""
                    if self.main_window.global_output_panel:
                        self.main_window.global_output_panel.error(message)
                        
                def error(self, message):
                    """Compatibilidade: alias para log_error"""
                    self.log_error(message)
                    
                def log_success(self, message):
                    """Compatibilidade: log de sucesso para output global"""
                    if self.main_window.global_output_panel:
                        self.main_window.global_output_panel.success(message)
                        
                def log_warning(self, message):
                    """Compatibilidade: log de warning para output global"""
                    if self.main_window.global_output_panel:
                        self.main_window.global_output_panel.warning(message)
                        
                def set_results(self, df, title="Resultado", query_info=None):
                    """Compatibilidade: define resultados no painel global"""
                    if self.main_window.global_results_viewer:
                        self.main_window.global_results_viewer.display_dataframe(df, title)
                        
                def set_variables(self, variables_dict):
                    """Compatibilidade: define variaveis no painel global"""
                    if self.main_window.global_variables_panel:
                        self.main_window.global_variables_panel.set_variables(variables_dict)
                        
                def show_output(self):
                    """Compatibilidade: mostra painel de output"""
                    self.main_window.show_panel('output')
                    
                def clear_output(self):
                    """Compatibilidade: limpa output global"""
                    if self.main_window.global_output_panel:
                        self.main_window.global_output_panel.clear()
                        
                @property
                def output_text(self):
                    """Compatibilidade: acesso ao texto do output global"""
                    if self.main_window.global_output_panel:
                        return self.main_window.global_output_panel
                    return None
            
            self._bottom_tabs_cache = DockableBottomTabsCompat(self)
        return self._bottom_tabs_cache

    @property
    def bottom_tabs(self):
        """Retorna instancia compartilhada do BottomTabs"""
        return self._get_bottom_tabs_instance()
        
    def _create_bottom_tabs_compat(self):
        """Cria o objeto de compatibilidade com BottomTabs"""
        # Retorna um mock object que redireciona para os painéis dockable
        class DockableBottomTabsCompat:
            pass
        
        return DockableBottomTabsCompat()

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
        
        # Carregar cores do design system
        colors = get_colors()
        
        # Tema escuro
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {colors.bg_primary};
            }}
            QMenuBar {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border-bottom: 1px solid {colors.border_default};
            }}
            QMenuBar::item:selected {{
                background-color: {colors.bg_elevated};
            }}
            QMenu {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                padding: 5px 0px;
            }}
            QMenu::item {{
                padding: 6px 40px 6px 30px;
                min-width: 180px;
            }}
            QMenu::item:selected {{
                background-color: {colors.interactive_primary_active};
            }}
            QMenu::icon {{
                padding-left: 10px;
            }}
            QToolBar {{
                background-color: {colors.bg_tertiary};
                border-bottom: 1px solid {colors.border_default};
                spacing: 5px;
            }}
            QStatusBar {{
                background-color: {colors.interactive_primary};
                color: {colors.text_inverse};
            }}
            QTabWidget::pane {{
                border: 1px solid {colors.border_default};
                background-color: {colors.bg_primary};
            }}
            QTabBar::tab {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                padding: 8px 20px;
                border: 1px solid {colors.border_default};
                border-bottom: none;
            }}
            QTabBar::tab:selected {{
                background-color: {colors.bg_primary};
                color: {colors.text_inverse};
            }}
            QTabBar::tab:hover {{
                background-color: {colors.bg_elevated};
            }}
            QSplitter::handle {{
                background-color: {colors.border_default};
            }}
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: {colors.text_inverse};
                border: none;
                padding: 5px 15px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary_hover};
            }}
            QTextEdit {{
                background-color: {colors.bg_primary};
                color: {colors.editor_fg};
                border: 1px solid {colors.border_default};
            }}
        """)
        
        # Container para as abas de sessões (será a área central)
        session_container = QWidget()
        session_layout = QVBoxLayout(session_container)
        session_layout.setContentsMargins(5, 5, 5, 5)
        
        # TabWidget para sessões (cada aba é um SessionWidget completo)
        self.session_tabs = SessionTabs()
        self.session_tabs.session_closed.connect(self._close_session_tab)
        self.session_tabs.session_renamed.connect(self._on_session_renamed)
        self.session_tabs.session_changed.connect(self._on_session_tab_changed)
        self.session_tabs.duplicate_session.connect(self._duplicate_session)
        
        session_layout.addWidget(self.session_tabs)
        
        # Configurar área central com sessões no sistema de docking
        self.set_central_content(session_container)
        
        # Restaurar sessões
        self._restore_sessions()
        
        # Dock para conexões (lateral esquerda) 
        self._create_connections_dock()
        
        # Configurar painéis dockable (Results, Output, Variables)
        self._setup_dockable_panels()
        
        # Restaurar layout de dock widgets após criar todos os docks
        # DESABILITADO: self._restore_dock_layout()
        # SEMPRE USA LAYOUT PADRÃO por enquanto
        print("DEBUG: [MODO SUPER SEGURO] Sempre aplicando layout padrão - save/restore completamente desabilitado")
        self._setup_default_layout()
        
        # Configurar auto-save de layout quando dock widgets mudarem  
        # DESABILITADO: self._setup_auto_save_layout()
        print("DEBUG: Auto-save desabilitado por segurança")
    
    def _create_connections_dock(self):
        """Cria painel lateral de conexões usando ConnectionPanel"""
        # Usar o componente ConnectionPanel
        self.connection_panel = ConnectionPanel(
            connection_manager=self.connection_manager,
            theme_manager=self.theme_manager
        )
        
        # Conectar sinais
        self.connection_panel.connection_requested.connect(self._quick_connect)
        self.connection_panel.new_tab_connection_requested.connect(self._connect_new_tab)
        self.connection_panel.new_connection_clicked.connect(self._new_connection)
        self.connection_panel.manage_connections_clicked.connect(self._manage_connections)
        self.connection_panel.edit_connection_clicked.connect(self._edit_connection)
        self.connection_panel.disconnect_clicked.connect(self._disconnect)
        
        # Criar dock widget
        self.connections_dock = QDockWidget("Conexões", self)
        self.connections_dock.setObjectName("ConnectionsDock")  # Para saveState/restoreState
        self.connections_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
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
        
        # Configurar política de tamanho para ocupar lateral completa
        self.connections_dock.setMinimumWidth(200)
        self.connections_dock.setMaximumWidth(400)
        
        # Configurar features para permitir reposicionamento total
        features = (QDockWidget.DockWidgetFeature.DockWidgetMovable | 
                   QDockWidget.DockWidgetFeature.DockWidgetFloatable |
                   QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.connections_dock.setFeatures(features)
        
        # Criar propriedades de compatibilidade
        self._setup_connection_panel_compat()
    
    def _setup_connection_panel_compat(self):
        """Cria propriedades de compatibilidade para código legado"""
        # Mapeia atributos antigos para o novo componente
        self.connections_list = self.connection_panel.connections_list.list_widget
        self.active_conn_name_label = self.connection_panel.active_widget.name_label
        self.active_conn_info_label = self.connection_panel.active_widget.info_label
        self.btn_disconnect = self.connection_panel.active_widget.btn_disconnect
    
    def _setup_dockable_panels(self):
        """Configura paineis dockable (Results, Output, Variables) usando QDockWidget.
        
        Cada dock contem um QStackedWidget. Cada sessao adiciona seus proprios
        paineis (ResultsViewer, OutputPanel, VariablesPanel) ao stack.
        Ao trocar de aba, troca-se a pagina visivel no stack.
        """
        from PyQt6.QtWidgets import QStackedWidget
        
        # Stacks - cada sessao terá sua pagina
        self._results_stack = QStackedWidget()
        self._output_stack = QStackedWidget()
        self._variables_stack = QStackedWidget()
        
        # Mapeamento session_id -> indice no stack
        self._session_panel_indices: dict = {}
        
        # Dock styling compartilhado
        dock_style_bottom = """
            QDockWidget {
                background-color: #252526;
                color: #cccccc;
            }
            QDockWidget::title {
                background-color: #2d2d30;
                padding: 8px;
                font-weight: bold;
            }
        """
        
        # Results Panel
        self.results_dock = QDockWidget("Results", self)
        self.results_dock.setObjectName("ResultsDock")
        self.results_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.results_dock.setWidget(self._results_stack)
        self.results_dock.setStyleSheet(dock_style_bottom)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.results_dock)
        
        # Output Panel
        self.output_dock = QDockWidget("Output", self)
        self.output_dock.setObjectName("OutputDock")
        self.output_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.output_dock.setWidget(self._output_stack)
        self.output_dock.setStyleSheet(dock_style_bottom)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)
        
        # Variables Panel
        self.variables_dock = QDockWidget("Variables", self)
        self.variables_dock.setObjectName("VariablesDock")
        self.variables_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.variables_dock.setWidget(self._variables_stack)
        self.variables_dock.setStyleSheet(dock_style_bottom)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.variables_dock)
        
        # Configurar tamanhos minimos para garantir visibilidade
        self.results_dock.setMinimumHeight(180)
        self.output_dock.setMinimumHeight(180)
        self.variables_dock.setMinimumWidth(200)
        self.variables_dock.setMinimumHeight(180)
        
        # Tabifica Results e Output por padrao (fica em abas)
        self.tabifyDockWidget(self.results_dock, self.output_dock)
        
        # Results fica como aba ativa
        self.results_dock.raise_()
    
    def _create_session_panels(self, session_id: str):
        """Cria paineis (Results, Output, Variables) para uma sessao e adiciona aos stacks."""
        results = ResultsViewer(theme_manager=self.theme_manager)
        output = OutputPanel(theme_manager=self.theme_manager)
        variables = VariablesPanel(theme_manager=self.theme_manager)
        
        r_idx = self._results_stack.addWidget(results)
        o_idx = self._output_stack.addWidget(output)
        v_idx = self._variables_stack.addWidget(variables)
        
        self._session_panel_indices[session_id] = {
            'results_idx': r_idx,
            'output_idx': o_idx,
            'variables_idx': v_idx,
            'results': results,
            'output': output,
            'variables': variables,
        }
        return results, output, variables
    
    def _remove_session_panels(self, session_id: str):
        """Remove paineis de uma sessao dos stacks."""
        info = self._session_panel_indices.pop(session_id, None)
        if not info:
            return
        self._results_stack.removeWidget(info['results'])
        self._output_stack.removeWidget(info['output'])
        self._variables_stack.removeWidget(info['variables'])
        info['results'].deleteLater()
        info['output'].deleteLater()
        info['variables'].deleteLater()
    
    def _switch_session_panels(self, session_id: str):
        """Troca os stacks para exibir os paineis da sessao ativa.
        
        Usa setCurrentWidget() em vez de setCurrentIndex() para evitar
        bugs com indices invalidos apos remocao de widgets do stack.
        """
        info = self._session_panel_indices.get(session_id)
        if not info:
            return
        if info['results']:
            self._results_stack.setCurrentWidget(info['results'])
        if info['output']:
            self._output_stack.setCurrentWidget(info['output'])
        if info['variables']:
            self._variables_stack.setCurrentWidget(info['variables'])
    
    @property
    def global_results_viewer(self):
        """Retorna o ResultsViewer da sessao ativa."""
        sid = self._get_active_session_id()
        info = self._session_panel_indices.get(sid) if sid else None
        return info['results'] if info else None
    
    @property
    def global_output_panel(self):
        """Retorna o OutputPanel da sessao ativa."""
        sid = self._get_active_session_id()
        info = self._session_panel_indices.get(sid) if sid else None
        return info['output'] if info else None
    
    @property
    def global_variables_panel(self):
        """Retorna o VariablesPanel da sessao ativa."""
        sid = self._get_active_session_id()
        info = self._session_panel_indices.get(sid) if sid else None
        return info['variables'] if info else None
    
    def _get_active_session_id(self) -> str:
        """Retorna o session_id da aba ativa."""
        widget = self._get_current_session_widget()
        if widget and hasattr(widget, 'session'):
            return widget.session.session_id
        return None
    
    def _on_namespace_updated(self, namespace: dict):
        """Callback quando o namespace e atualizado"""
        panel = self.global_variables_panel
        if panel:
            panel.refresh_variables(namespace)
    
    def show_output(self, text: str):
        """Mostra output no painel da sessao ativa"""
        panel = self.global_output_panel
        if panel:
            panel.append_output(text)
        
        # Mostra o painel de output
        self.show_panel('output')
    
    def show_panel(self, name: str):
        """Mostra painel especifico usando QDockWidget.
        
        Para docks tabificados (results/output), raise_() sozinho nao
        funciona. Precisamos buscar o QTabBar do grupo e trocar a aba ativa.
        """
        dock_map = {
            'results': self.results_dock,
            'output': self.output_dock,
            'variables': self.variables_dock,
        }
        dock = dock_map.get(name)
        if dock is None:
            return
        
        dock.show()
        dock.raise_()
        
        # Para docks tabificados, raise_() nao troca a aba visivel.
        # Precisamos encontrar o QTabBar que controla o grupo e selecionar
        # a aba correspondente manualmente.
        if name in ('results', 'output'):
            self._activate_tabified_dock(dock)
    
    def _activate_tabified_dock(self, dock: QDockWidget):
        """Ativa a aba correta em um grupo de docks tabificados.
        
        Quando docks sao tabificados via tabifyDockWidget(), eles compartilham
        um QTabBar interno do QMainWindow. raise_() sozinho nao troca a aba.
        Este metodo encontra o QTabBar correto e seleciona a aba do dock.
        """
        from PyQt6.QtWidgets import QTabBar
        target_title = dock.windowTitle()
        for tab_bar in self.findChildren(QTabBar):
            for i in range(tab_bar.count()):
                if tab_bar.tabText(i) == target_title:
                    tab_bar.setCurrentIndex(i)
                    return

    def hide_panel(self, name: str):
        """Esconde painel específico usando QDockWidget"""
        if name == 'results':
            self.results_dock.hide()
        elif name == 'output':
            self.output_dock.hide()
        elif name == 'variables':
            self.variables_dock.hide()
    
    def _refresh_connections_list(self):
        """Atualiza lista de conexões salvas"""
        self.connection_panel.refresh_connections()
    
    def _on_connection_double_click(self, item: QListWidgetItem):
        """Conecta ao dar duplo clique na conexão"""
        conn_name = item.data(Qt.ItemDataRole.UserRole)
        if conn_name:
            self._quick_connect(conn_name)
    
    def _toggle_panel_visibility(self, panel_name: str, visible: bool):
        """Controla visibilidade de um painel"""
        if visible:
            self.show_panel(panel_name)
        else:
            self.hide_panel(panel_name)
    
    def _toggle_output_tab(self, visible: bool):
        """Controla visibilidade do painel Output"""
        if visible:
            self.show_panel('output')
        else:
            self.hide_panel('output')
    
    def _restore_default_layout(self):
        """Restaura o layout padrão dos painéis"""
        # Mostra todos os docks na posição padrão
        self.results_dock.show()
        self.output_dock.show() 
        self.variables_dock.show()
        self.connections_dock.show()
        
        # Redefine posições
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.results_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.variables_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.connections_dock)
        
        # Tabifica Results e Output
        self.tabifyDockWidget(self.results_dock, self.output_dock)
        self.results_dock.raise_()
        
        # Atualiza ações do menu
        if hasattr(self, 'results_action'):
            self.results_action.setChecked(True)
        if hasattr(self, 'output_action'):
            self.output_action.setChecked(True)
        if hasattr(self, 'variables_action'):
            self.variables_action.setChecked(True)
        if hasattr(self, 'connections_action'):
            self.connections_action.setChecked(True)
    
    def _save_dock_layout(self):
        """DESABILITADO - Não salva layout automaticamente por segurança"""
        print("DEBUG: [SUPER SEGURO] Save automático desabilitado por segurança")
        return
    
    def _restore_dock_layout(self):
        """Restaura layout dos dock widgets com validação robusta"""
        try:
            settings = QSettings('DataPyn', 'MainWindow')
            
            # Verifica se deve resetar (se segurar Shift ao abrir)
            modifiers = QApplication.keyboardModifiers()
            if modifiers == Qt.KeyboardModifier.ShiftModifier:
                print("DEBUG: Shift pressionado - resetando layout para padrão")
                self._clear_saved_layout()
                self._setup_default_layout()
                return
            
            # Restaura geometria da janela
            geometry = settings.value('geometry')
            geometry_restored = False
            if geometry and len(geometry) > 20:
                success = self.restoreGeometry(geometry)
                geometry_restored = success
                print(f"DEBUG: Geometria restaurada - Sucesso: {success}, Dados: {len(geometry)} bytes")
                if not success:
                    print("DEBUG: Falha ao restaurar geometria")
            else:
                print("DEBUG: Geometria inválida ou inexistente - usando padrão")
            
            # Restaura estado dos docks
            window_state = settings.value('windowState')
            state_restored = False
            if window_state and len(window_state) > 50:
                success = self.restoreState(window_state)
                state_restored = success
                print(f"DEBUG: Estado dos docks restaurado - Sucesso: {success}, Dados: {len(window_state)} bytes")
                
                if success:
                    # Força atualização da interface após restaurar
                    QApplication.processEvents()
                    # Verifica se o layout ficou válido após restaurar
                    QTimer.singleShot(500, self._validate_restored_layout)
                else:
                    print("DEBUG: Falha ao restaurar estado dos docks")
                    state_restored = False
            else:
                print("DEBUG: Estado dos docks inválido ou inexistente - usando padrão")
            
            # Se não conseguiu restaurar nada OU falhou, usa padrão
            if not geometry_restored and not state_restored:
                print("DEBUG: Nada foi restaurado ou houve falhas - aplicando layout padrão")
                self._setup_default_layout()
                
        except Exception as e:
            print(f"DEBUG: Erro ao restaurar layout: {e} - usando layout padrão")
            self._setup_default_layout()
    
    def _setup_auto_save_layout(self):
        """DESABILITADO - Auto-save desabilitado por segurança"""
        print("DEBUG: [SUPER SEGURO] Auto-save permanentemente desabilitado")
        return
    
    def _on_dock_changed(self):
        """DESABILITADO - Não reage a mudanças de dock por segurança"""
        print("DEBUG: [SUPER SEGURO] Mudança de dock ignorada - save desabilitado")
    
    def _clear_saved_layout(self):
        """Limpa layout salvo (para reset)"""
        try:
            settings = QSettings('DataPyn', 'MainWindow')
            settings.remove('geometry')
            settings.remove('windowState')
            settings.sync()
            print("DEBUG: Layout salvo removido com sucesso")
        except Exception as e:
            print(f"DEBUG: Erro ao limpar layout salvo: {e}")
    
    def _setup_default_layout(self):
        """Configura layout padrão simples e confiável"""
        print("DEBUG: [SUPER SEGURO] Configurando layout padrão SIMPLIFICADO")
        
        try:
            # Força todos visíveis e não-flutuantes
            all_docks = [self.connections_dock, self.results_dock, self.output_dock, self.variables_dock]
            for dock in all_docks:
                if dock:
                    dock.setVisible(True)
                    dock.setFloating(False)
            
            # Posições simples - sem remoção/readição complexa
            print("DEBUG: Aplicando layout super simples...")
            
            # Janela no tamanho padrão
            self.setGeometry(100, 100, 1400, 900) 
            
            # Força show de todos
            self.connections_dock.show()
            self.results_dock.show() 
            self.output_dock.show()
            self.variables_dock.show()
            
            print("DEBUG: Layout padrão SIMPLIFICADO aplicado")
            
        except Exception as e:
            print(f"DEBUG: ERRO no layout simplificado: {e}")
            # Fallback absoluto
            try:
                self.connections_dock.show()
                self.results_dock.show()
                self.output_dock.show() 
                self.variables_dock.show()
            except:
                pass
    
    def _is_layout_valid(self):
        """Verifica se o layout atual está sano"""
        try:
            # Verifica se todos os docks existem e estão visíveis
            required_docks = [self.connections_dock, self.results_dock, self.output_dock, self.variables_dock]
            
            for dock in required_docks:
                if dock is None:
                    print(f"DEBUG: Dock None encontrado")
                    return False
            
            # Verifica geometria da janela
            geom = self.geometry()
            if geom.width() < 400 or geom.height() < 300:
                print(f"DEBUG: Janela muito pequena: {geom.width()}x{geom.height()}")
                return False
            
            return True
            
        except Exception as e:
            print(f"DEBUG: Erro ao validar layout: {e}")
            return False
    
    def _validate_restored_layout(self):
        """Valida layout após restaurar e corrige se necessário"""
        if not self._is_layout_valid():
            print("DEBUG: Layout restaurado está inválido - aplicando padrão")
            self._clear_saved_layout()  # Remove o layout corrompido
            self._setup_default_layout()
    
    def _reset_layout_completely(self):
        """Reseta layout completamente (limpa configurações e aplica padrão)"""
        reply = QMessageBox.question(
            self, 
            "Confirmar Reset",
            "Isso irá resetar completamente o layout dos painéis.\nTodas as configurações de layout serão perdidas.\n\nContinuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            print("DEBUG: Resetando layout completamente por solicitação do usuário")
            self._clear_saved_layout()
            self._setup_default_layout()
            QMessageBox.information(
                self,
                "Layout Resetado",
                "Layout dos painéis foi resetado para o padrão."
            )
    
    def closeEvent(self, event):
        """DESABILITADO - Não salva layout ao fechar por segurança"""
        print("DEBUG: [SUPER SEGURO] Fechando sem salvar layout (modo seguro ativo)")
        super().closeEvent(event)
    
    def _quick_connect(self, connection_name: str):
        """
        Conecta a um banco de dados.
        - Se não há aba: cria nova aba
        - Se há aba atual conectando: cria nova aba
        - Se há aba atual disponível: troca a conexão dessa aba
        A conexão acontece em background (não trava a aplicação).
        """
        # Obter aba atual
        current_widget = self._get_current_session_widget()
        
        # Se não há aba ou a aba atual está conectando, criar uma nova
        if not current_widget or current_widget.is_connecting():
            self._new_session()
            current_widget = self._get_current_session_widget()
        
        if not current_widget:
            self._show_warning("Erro", "Não foi possível criar nova aba")
            return
        
        # Obter config (apenas metadados, não conexão)
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            self._show_warning("Erro", f"Conexão '{connection_name}' não encontrada")
            return
        
        # Pegar senha se necessário
        password = ''
        if not config.get('use_windows_auth', False):
            password = config.get('password', '')
        
        # DELEGAR para a aba - ela gerencia conexão em background
        # Retorna True imediatamente (assíncrono)
        current_widget.connect_to_database(connection_name, password)
        
        # Atualizar status (a aba mostrará o loading internamente)
        self.action_label.setText(f"Conectando a {connection_name}...")
    
    def _connect_new_tab(self, connection_name: str):
        """
        Conecta a um banco de dados SEMPRE criando uma nova aba.
        Usado quando CTRL+duplo-click ou 'Conectar em Nova Aba' no menu.
        """
        # Sempre criar nova aba
        self._new_session()
        current_widget = self._get_current_session_widget()
        
        if not current_widget:
            self._show_warning("Erro", "Não foi possível criar nova aba")
            return
        
        # Obter config (apenas metadados, não conexão)
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            self._show_warning("Erro", f"Conexão '{connection_name}' não encontrada")
            return
        
        # Pegar senha se necessário
        password = ''
        if not config.get('use_windows_auth', False):
            password = config.get('password', '')
        
        # DELEGAR para a aba - ela gerencia conexão em background
        current_widget.connect_to_database(connection_name, password)
        
        # Atualizar status
        self.action_label.setText(f"Conectando a {connection_name} (nova aba)...")
    
    def _create_menus(self):
        """Cria os menus"""
        menubar = self.menuBar()
        
        # Menu Arquivo
        file_menu = menubar.addMenu("&Arquivo")
        
        new_action = QAction("&Nova Aba", self)
        # Atalho gerenciado por ShortcutManager (Ctrl+T)
        new_action.triggered.connect(self._new_session)
        file_menu.addAction(new_action)
        
        open_action = QAction("&Abrir...", self)
        # Atalho gerenciado por ShortcutManager (Ctrl+O)
        open_action.triggered.connect(self._open_file)
        file_menu.addAction(open_action)
        
        save_action = QAction("&Salvar", self)
        # Atalho gerenciado por ShortcutManager (Ctrl+S)
        save_action.triggered.connect(self._save_file)
        file_menu.addAction(save_action)
        
        save_as_action = QAction("Salvar &Como...", self)
        # Atalho gerenciado por ShortcutManager (Ctrl+Shift+S)
        save_as_action.triggered.connect(self._save_file_as)
        file_menu.addAction(save_as_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Sai&r", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)  # Manter Quit padrão do sistema
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Menu Conexão
        conn_menu = menubar.addMenu("&Conexão")
        
        manage_conn_action = QAction("&Gerenciar Conexões...", self)
        if HAS_QTAWESOME:
            manage_conn_action.setIcon(self.icons['database'])
        # Atalho gerenciado por ShortcutManager (Ctrl+Shift+M)
        manage_conn_action.triggered.connect(self._manage_connections)
        conn_menu.addAction(manage_conn_action)
        
        conn_menu.addSeparator()
        
        new_conn_action = QAction("&Nova Conexão...", self)
        if HAS_QTAWESOME:
            new_conn_action.setIcon(self.icons['plug'])
        # Atalho gerenciado por ShortcutManager (Ctrl+Shift+D)
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
        # Atalho gerenciado por ShortcutManager (F5)
        run_current_action.triggered.connect(self._execute_current_block)
        run_menu.addAction(run_current_action)
        
        run_all_action = QAction("Executar &Todos os Blocos", self)
        if HAS_QTAWESOME:
            run_all_action.setIcon(qta.icon('fa5s.forward'))
        # Atalho gerenciado por ShortcutManager (Ctrl+F5)
        run_all_action.triggered.connect(self._execute_all_blocks)
        run_menu.addAction(run_all_action)
        
        run_menu.addSeparator()
        
        clear_results_action = QAction("&Limpar Resultados", self)
        if HAS_QTAWESOME:
            clear_results_action.setIcon(self.icons['trash'])
        # Atalho gerenciado por ShortcutManager (Ctrl+Shift+C)
        clear_results_action.triggered.connect(self._clear_results)
        run_menu.addAction(clear_results_action)
        
        # Menu Exibir
        view_menu = menubar.addMenu("E&xibir")
        
        # Submenu Painéis
        panels_menu = view_menu.addMenu("&Painéis")
        
        # Toggle do painel de resultados
        results_action = QAction("&Resultados", self)
        results_action.setCheckable(True)
        results_action.setChecked(True)
        results_action.triggered.connect(lambda checked: self._toggle_panel_visibility('results', checked))
        panels_menu.addAction(results_action)
        self.results_action = results_action
        
        # Toggle do painel de output
        output_action = QAction("&Output", self)
        output_action.setCheckable(True)
        output_action.setChecked(True)
        output_action.triggered.connect(lambda checked: self._toggle_output_tab(checked))
        panels_menu.addAction(output_action)
        self.output_action = output_action
        
        # Toggle do painel de variáveis
        variables_action = QAction("&Variáveis", self)
        variables_action.setCheckable(True)
        variables_action.setChecked(True)
        variables_action.triggered.connect(lambda checked: self._toggle_panel_visibility('variables', checked))
        panels_menu.addAction(variables_action)
        self.variables_action = variables_action
        
        # Toggle do painel de conexões
        connections_action = QAction("&Conexões", self)
        connections_action.setCheckable(True)
        connections_action.setChecked(True)
        connections_action.triggered.connect(lambda checked: self.connections_dock.setVisible(checked))
        panels_menu.addAction(connections_action)
        self.connections_action = connections_action
        
        view_menu.addSeparator()
        
        # Restaurar visão padrão
        restore_action = QAction("&Restaurar Visão Padrão", self)
        restore_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        restore_action.triggered.connect(self._restore_default_layout)
        view_menu.addAction(restore_action)
        
        # Resetar layout completamente (limpa configurações salvas)
        reset_layout_action = QAction("Reset &Completo de Layout", self)
        reset_layout_action.setShortcut(QKeySequence("Ctrl+Shift+Alt+R"))
        reset_layout_action.triggered.connect(self._reset_layout_completely)
        view_menu.addAction(reset_layout_action)
        
        # Menu Ferramentas
        tools_menu = menubar.addMenu("&Ferramentas")
        
        settings_action = QAction("&Configurações de Atalhos...", self)
        if HAS_QTAWESOME:
            settings_action.setIcon(self.icons['cog'])
        # Atalho gerenciado por ShortcutManager (Ctrl+,)
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
        self.main_toolbar.setObjectName("MainToolbar")  # Para saveState/restoreState
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
            mode = f"{self._execution_mode}" if self._execution_mode else "Código"
            # Ícone animado + texto mais visível
            icon = qta.icon('fa5s.spinner', color='#FFD700', animation=qta.Spin(self.execution_label))
            self.execution_label.setPixmap(icon.pixmap(16, 16))
            self.execution_label.setText(f"  Executando {mode} {elapsed:.1f}s")
            self.execution_label.setStyleSheet("""
                QLabel {
                    color: #FFD700;
                    font-weight: bold;
                    padding: 4px 12px;
                    background: rgba(255, 215, 0, 0.15);
                    border-left: 3px solid #FFD700;
                    border-radius: 2px;
                }
            """)
    
    def _clear_execution_label(self):
        """Limpa o label de execução"""
        if not self._is_executing:
            self.execution_label.setText("")
    
    def _setup_shortcuts(self):
        """Configura atalhos globais da aplicação"""
        from PyQt6.QtGui import QShortcut, QKeySequence
        from PyQt6.QtCore import Qt
        
        # Guardar shortcuts como atributos para evitar garbage collection
        self._shortcuts = []
        
        # Mapear ações para callbacks
        shortcuts_map = {
            # Execução
            'execute_sql': self._execute_current_block,
            'execute_all': self._execute_all_blocks,
            'clear_results': self._clear_results,
            
            # Arquivo
            'open_file': self._open_file,
            'save_file': self._save_file,
            'save_as': self._save_file_as,
            
            # Sessões
            'new_tab': self._new_session,
            'close_tab': self._close_current_session,
            'add_block': self._add_block_to_current_session,
            
            # Edição - REMOVIDOS find/replace para não conflitar com editores
            # Monaco e QScintilla têm seus próprios Ctrl+F e Ctrl+H nativos
            # 'find': self._show_find_dialog,
            # 'replace': self._show_replace_dialog,
            
            # Conexões
            'manage_connections': self._manage_connections,
            'new_connection': self._new_connection,
            
            # Ferramentas
            'settings': self._show_settings,
        }
        
        # Criar atalhos a partir do ShortcutManager
        for action, callback in shortcuts_map.items():
            key_sequence = self.shortcut_manager.get_shortcut(action)
            if key_sequence:
                shortcut = QShortcut(QKeySequence(key_sequence), self)
                shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
                shortcut.activated.connect(callback)
                self._shortcuts.append(shortcut)
    
    def _reload_shortcuts(self):
        """Re-registra todos os atalhos (chamado quando usuário altera configurações)"""
        from PyQt6.QtGui import QShortcut, QKeySequence
        from PyQt6.QtCore import Qt
        
        # Limpar atalhos antigos
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._shortcuts.clear()
        
        # Mapear ações para callbacks
        shortcuts_map = {
            # Execução
            'execute_sql': self._execute_current_block,
            'execute_all': self._execute_all_blocks,
            'clear_results': self._clear_results,
            
            # Arquivo
            'open_file': self._open_file,
            'save_file': self._save_file,
            'save_as': self._save_file_as,
            
            # Sessões
            'new_tab': self._new_session,
            'close_tab': self._close_current_session,
            'add_block': self._add_block_to_current_session,
            
            # Conexões
            'manage_connections': self._manage_connections,
            'new_connection': self._new_connection,
            
            # Ferramentas
            'settings': self._show_settings,
        }
        
        # Criar novos atalhos
        for action, callback in shortcuts_map.items():
            key_sequence = self.shortcut_manager.get_shortcut(action)
            if key_sequence:
                shortcut = QShortcut(QKeySequence(key_sequence), self)
                shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
                shortcut.activated.connect(callback)
                self._shortcuts.append(shortcut)
    
    # NOTA: _new_session() definido mais abaixo (linha ~2745) com guard contra duplicacao
    
    def _close_current_session(self):
        """Fecha a sessao/aba atual - delega para _close_session_tab"""
        current_index = self.session_tabs.currentIndex()
        if current_index >= 0:
            widget = self.session_tabs.widget(current_index)
            if isinstance(widget, SessionWidget):
                # Confirmar fechamento se houver codigo nao salvo
                has_code = any(block.get_code().strip() for block in widget.editor.get_blocks())
                if has_code:
                    reply = QMessageBox.question(
                        self,
                        "Fechar Sessao",
                        "Tem certeza que deseja fechar esta sessao?\n\nO codigo nao salvo sera perdido.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.No:
                        return
                
                # Delegar para _close_session_tab que faz cleanup completo
                self._close_session_tab(current_index)
    
    def _duplicate_session(self, index: int):
        """Duplica uma sessao - cria nova sessao com paineis e copia conteudo"""
        widget = self.session_tabs.widget(index)
        if not widget or not hasattr(widget, 'editor'):
            return
        
        # Guard para evitar que _on_session_tab_changed dispare _new_session
        self._creating_session = True
        try:
            # Criar nova sessao com paineis
            session = self.session_manager.create_session()
            new_widget = SessionWidget(session, theme_manager=self.theme_manager)
            
            # Criar paineis para a nova sessao
            self._create_session_panels(session.session_id)
            
            # Copiar todo o conteudo do editor
            source_blocks = widget.editor.get_blocks()
            
            # Remover blocos existentes na nova sessao (exceto o ultimo)
            new_blocks = new_widget.editor.get_blocks()
            for b in new_blocks[:-1]:
                new_widget.editor.remove_block(b)
            
            # Se fonte tem blocos, usa o primeiro bloco vazio da nova sessao
            if source_blocks:
                first_new_block = new_widget.editor.get_blocks()[0]
                first_new_block.set_language(source_blocks[0].get_language())
                first_new_block.set_code(source_blocks[0].get_code())
                
                # Adicionar os demais blocos
                for block in source_blocks[1:]:
                    new_block = new_widget.editor.add_block(language=block.get_language())
                    new_block.set_code(block.get_code())
            
            # Copiar file_path se existir
            if hasattr(widget, 'file_path'):
                new_widget.file_path = widget.file_path
            
            # Herdar conexao da sessao original
            if hasattr(widget, 'session') and widget.session.connection_name:
                try:
                    connected = session.connect(widget.session.connection_name)
                    if not connected:
                        pass  # Conexao falhou, sessao fica sem conexao
                except Exception:
                    pass
            
            # Conectar sinais do widget
            new_widget.execute_cross_syntax.connect(lambda code: self._execute_cross_syntax_for_session(session, code))
            new_widget.status_changed.connect(lambda msg: self._on_session_status_changed(session, msg))
            new_widget.connection_changed.connect(lambda conn_name, db: self._on_session_connection_changed(session, conn_name, db))
            
            # Registrar widget
            self._session_widgets[session.session_id] = new_widget
            
            # Nome da nova aba
            original_name = self.session_tabs.tabText(index)
            new_name = f"{original_name} (copia)"
            
            # Inserir antes do ultimo tab (botao nova aba)
            insert_position = self.session_tabs.count() - 1 if self.session_tabs.count() > 0 else 0
            tab_index = self.session_tabs.insertTab(insert_position, new_widget, new_name)
            
            # Configurar botao de fechar customizado
            self.session_tabs._setup_close_button(tab_index)
            
            # Aplicar cor da aba se sessao original tinha conexao
            if session.connection_name:
                config = self.connection_manager.get_connection_config(session.connection_name)
                if config:
                    color = config.get('color', '#007ACC') or '#007ACC'
                    self.session_tabs.set_tab_connection_color(tab_index, color)
            
            self.session_tabs.setCurrentIndex(tab_index)
            
            # Trocar paineis para a nova sessao
            self._switch_session_panels(session.session_id)
        finally:
            self._creating_session = False
    
    def _show_find_dialog(self):
        """Mostra diálogo de busca no editor atual"""
        widget = self._get_current_session_widget()
        if widget and widget.editor:
            # Implementação simples de busca com QInputDialog
            from PyQt6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(self, "Buscar", "Texto a buscar:")
            if ok and text:
                # Buscar no editor
                editor = widget.editor
                if hasattr(editor, 'findFirst'):
                    editor.findFirst(text, False, False, False, True)
    
    def _show_replace_dialog(self):
        """Mostra diálogo de substituir no editor atual"""
        widget = self._get_current_session_widget()
        if widget and widget.editor:
            # Implementação simples de substituição
            from PyQt6.QtWidgets import QInputDialog
            find_text, ok1 = QInputDialog.getText(self, "Substituir", "Buscar:")
            if ok1 and find_text:
                replace_text, ok2 = QInputDialog.getText(self, "Substituir", "Substituir por:")
                if ok2:
                    # Substituir no editor
                    editor = widget.editor
                    if hasattr(editor, 'findFirst') and hasattr(editor, 'replace'):
                        while editor.findFirst(find_text, False, False, False, True):
                            editor.replace(replace_text)
    
    def _add_block_to_current_session(self):
        """Adiciona novo bloco de código na sessão atual"""
        widget = self._get_current_session_widget()
        if widget and widget.editor:
            widget.editor.add_block()
    
    def _manage_connections(self):
        """Abre diálogo de gerenciamento de conexões"""
        dialog = ConnectionsManagerDialog(self.connection_manager, theme_manager=self.theme_manager, parent=self)
        dialog.connection_selected.connect(self._connect_from_manager)
        dialog.exec()
        # Atualizar lista após fechar o diálogo
        self._refresh_connections_list()
    
    def _connect_from_manager(self, name: str, config: dict):
        """Conecta a partir do gerenciador de conexoes - mesmo comportamento do painel lateral"""
        self._quick_connect(name)
    
    def _new_connection(self):
        """Abre dialogo para nova conexao"""
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
            self._log_info(f"Conexão '{name}' criada com sucesso")
            self.action_label.setText(f"Conexão '{name}' criada")
    
    def _edit_connection(self, connection_name: str):
        """Abre dialogo para editar uma conexao especifica"""
        # Obter config da conexão
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            self._show_warning("Erro", f"Conexão '{connection_name}' não encontrada")
            return
        
        dialog = ConnectionEditDialog(
            connection_name=connection_name,
            config=config,
            groups=self.connection_manager.get_groups(),
            theme_manager=self.theme_manager,
            parent=self
        )
        
        if dialog.exec():
            name, new_config = dialog.get_result()
            
            # Se mudou o nome, deletar antiga
            if name != connection_name:
                self.connection_manager.delete_connection_config(connection_name)
            
            # Salva a conexão
            self.connection_manager.save_connection_config(
                name,
                new_config['db_type'],
                new_config['host'],
                new_config['port'],
                new_config['database'],
                new_config.get('username', ''),
                new_config.get('save_password', False),
                new_config.get('password', ''),
                new_config.get('group', ''),
                new_config.get('use_windows_auth', False),
                new_config.get('color', '')
            )
            
            self._update_connection_status()
            self._refresh_connections_list()
            self._log_info(f"Conexão '{name}' atualizada com sucesso")
            self.action_label.setText(f"Conexão '{name}' atualizada")
    
    # === Métodos auxiliares para diálogos com ícones ===
    
    def _show_warning(self, title: str, message: str):
        """Mostra warning com ícone"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    
    def _show_error(self, title: str, message: str):
        """Mostra erro com ícone"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    
    def _show_info(self, title: str, message: str):
        """Mostra informação com ícone"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    
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
        
        # Se é um BlockEditor, usa a execução inteligente (mesma lógica do botão)
        from src.editors.block_editor import BlockEditor
        if isinstance(editor, BlockEditor):
            editor._execute_smart()
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
            self._show_warning("Atenção", "Nenhuma conexão ativa nesta sessão. Conecte-se a um banco de dados primeiro.")
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
                
                self._log_info(f"[SQL] Banco alterado para: {database_name}")
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
    
    def _handle_execution_result(self, result=None, error=None, execution_type="Unknown", additional_info=""):
        """
        Método centralizado para tratar resultados de execução
        
        Args:
            result: Resultado da execução (DataFrame, string, etc) ou None
            error: Mensagem de erro ou None
            execution_type: Tipo da execução ("SQL", "Python", "Cross-Syntax")
            additional_info: Informação adicional para logs
        """
        if error:
            # ERRO → OUTPUT (console)
            self._show_error_output(f"[{execution_type}] {error}")
            self.action_label.setText(f"[{execution_type}] Erro ao executar")
            return False  # Indica erro
        
        if result is None:
            # SEM RESULTADO → OUTPUT (console)
            self.show_panel('output')
            return True
        
        # SUCESSO -> Decidir painel baseado no tipo do resultado
        import pandas as pd
        
        results_panel = self.global_results_viewer
        
        if isinstance(result, pd.DataFrame):
            # DATAFRAME -> GRID (results)
            if results_panel:
                results_panel.display_dataframe(result, f'Resultado {execution_type}')
            self.show_panel('results')
            rows = len(result)
            self._log_info(f"[{execution_type}] {additional_info or f'DataFrame exibido ({rows:,} linhas)'}")
            return True
        
        elif isinstance(result, (list, tuple)) and len(result) > 0:
            # LISTA/TUPLA → Tentar converter para DataFrame
            try:
                df = pd.DataFrame(result)
                if len(df) > 0:
                    if results_panel:
                        results_panel.display_dataframe(df, f'Resultado {execution_type}')
                    self.show_panel('results')
                    self._log_info(f"[{execution_type}] Lista convertida para DataFrame ({len(df)} linhas)")
                    return True
            except:
                pass
            
            # Se não conseguiu converter, vai para output
            self._log(f"[{execution_type}] {repr(result)}")
            return True
        
        elif isinstance(result, dict):
            # DICT → Tentar converter para DataFrame
            try:
                df = pd.DataFrame([result]) if not isinstance(list(result.values())[0], (list, tuple)) else pd.DataFrame(result)
                if results_panel:
                    results_panel.display_dataframe(df, f'Resultado {execution_type}')
                self.show_panel('results')  
                self._log_info(f"[{execution_type}] Dicionário convertido para DataFrame")
                return True
            except:
                pass
            
            # Se não conseguiu converter, vai para output
            self._log(f"[{execution_type}] {repr(result)}")
            return True
        
        else:
            # OUTROS TIPOS → OUTPUT (console)
            self._log(f"[{execution_type}] {repr(result)}")
            return True

    def _on_sql_finished(self, df, error, thread, tab_index):
        """Callback quando SQL termina"""
        self._stop_execution_timer()
        
        # Remover marcação de rodando
        self._mark_tab_running(False, tab_index)
        
        # Limpar thread da lista
        self._worker_threads = [(t, w) for t, w in self._worker_threads if t != thread]
        thread.quit()
        thread.wait()
        
        # FORÇAR: Se há erro, SEMPRE mostrar output - não importa o que vier no df
        if error:
            self._show_error_output(f"[SQL] Erro: {error}")
            self.action_label.setText("[SQL] Erro ao executar") 
            self._send_notification("Query SQL", f"Erro: {str(error)[:50]}...", success=False)
            return
        
        # SÓ se não há erro, usar método centralizado
        success = self._handle_execution_result(
            result=df,
            error=None,  # Garantir que error é None aqui
            execution_type="SQL",
            additional_info=f"Executado com sucesso ({len(df):,} linhas retornadas)" if df is not None else ""
        )
        
        if success:
            rows = len(df) if df is not None else 0
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
        
        # Sempre usar a lógica centralizada
        is_expression = False
        
        # Criar thread e worker
        thread = QThread()
        worker = PythonWorker(code, namespace, is_expression)
        worker.moveToThread(thread)
        
        # Conectar sinais
        thread.started.connect(worker.run)
        worker.finished.connect(lambda result, output, err, namespace: self._on_python_finished(result, output, err, namespace, thread, running_tab_index))
        
        # Manter referência
        self._worker_threads.append((thread, worker))
        
        # Iniciar
        thread.start()
    
    def _on_python_finished(self, result_value, output, error, updated_namespace, thread, tab_index):
        """Callback quando Python termina"""
        self._stop_execution_timer()
        
        # Salvar namespace atualizado
        self.results_manager.update_namespace(updated_namespace)
        
        # Remover marcação de rodando
        self._mark_tab_running(False, tab_index)
        
        # Limpar thread da lista
        self._worker_threads = [(t, w) for t, w in self._worker_threads if t != thread]
        thread.quit()
        thread.wait()
        
        logging.info(f"[MAIN_WINDOW] RETORNO DA EXECUÇÃO: \"\"\"{repr(result_value)}\"\"\"")
        logging.info(f"[MAIN_WINDOW] FOI PRO CONSOLE: \"\"\"{output}\"\"\"")
        
        # FORÇAR: Se há erro, SEMPRE mostrar output primeiro
        if error:
            self._show_error_output(f"[Python] Erro: {error}")
            self.action_label.setText("[Python] Erro ao executar")
            return
        
        # Mostra output de print() primeiro (se houver)
        if output:
            self._log(output.strip())
        
        # SÓ se não há erro, usar método centralizado
        success = self._handle_execution_result(
            result=result_value,
            error=None,  # Garantir que error é None aqui
            execution_type="Python"
        )
        
        if success:
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
            self._show_error_output(f"[Cross-Syntax] Erro de sintaxe: {error}")
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
        
        # FORÇAR: Se há erro, SEMPRE mostrar output primeiro
        if error:
            self._show_error_output(f"[Cross-Syntax] Erro: {error}")
            self.action_label.setText("[Cross-Syntax] Erro ao executar")
            self._send_notification("Cross-Syntax", f"Erro: {str(error)[:50]}...", success=False)
            return
        
        # Mostra output primeiro (se houver)
        if result and result.get('output'):
            self._log(result['output'].strip())
        
        # Mostra queries executadas no log
        if result and result.get('queries_executed'):
            # Exibir variáveis criadas
            queries = self.mixed_executor.extract_queries(code)
            for var_name, sql in queries:
                # Buscar no namespace da sessão que executou
                var_value = session.namespace.get(var_name)
                if var_value is not None:
                    if isinstance(var_value, pd.DataFrame):
                        rows = len(var_value)
                        self._log_info(f"[Cross-Syntax] Variável '{var_name}' criada ({rows:,} linhas)")
                    else:
                        self._log_info(f"[Cross-Syntax] Variável '{var_name}' criada")
        
        # SÓ se não há erro, usar método centralizado
        success = self._handle_execution_result(
            result=result.get('result') if result else None,
            error=None,  # Garantir que error é None aqui
            execution_type="Cross-Syntax"
        )
        
        if success:
            # Atualiza variáveis - da sessão que executou, se ainda for a focada
            if session == self.session_manager.focused_session:
                self._update_variables_view()
            
            self.action_label.setText("[Cross-Syntax] Executado com sucesso!")
            
            # Notificação de sucesso
            queries_count = result.get('queries_executed', 0) if result else 0
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
    
    def _log_info(self, message: str):
        """Adiciona mensagem ao log com timestamp (sem mostrar painel)"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        if self.global_output_panel:
            self.global_output_panel.text_edit.append(f"[{timestamp}] {message}")

    def _log(self, message: str):
        """Adiciona mensagem ao log com timestamp e mostra painel output"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        if self.global_output_panel:
            self.global_output_panel.text_edit.append(f"[{timestamp}] {message}")
        
        # Mostrar painel de output
        self.show_panel('output')
    
    def _show_error_output(self, error_msg: str):
        """Mostra erro no Output em vermelho e alterna para o painel de Output"""
        if not self.global_output_panel:
            return
        # Adiciona timestamp e erro em vermelho usando HTML
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        error_html = f'<span style="color: #ff6b6b; font-weight: bold;">[{timestamp}] {error_msg}</span>'
        self.global_output_panel.text_edit.append(error_html)
        
        # Mostrar painel de output
        self.show_panel('output')
        
        # Scroll para o final
        scrollbar = self.global_output_panel.text_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _update_variables_view(self):
        """Atualiza visualizacao de variaveis em memoria"""
        panel = self.global_variables_panel
        if not panel:
            return
        vars_df = self.results_manager.get_variables_info()
        panel.display_dataframe(vars_df, "Variaveis")
    
    def _clear_results(self):
        """Limpa todos os resultados"""
        reply = QMessageBox.question(
            self, "Confirmar", 
            "Deseja limpar todos os resultados em memória?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.results_manager.clear_all()
            results = self.global_results_viewer
            if results:
                results.clear()
            variables = self.global_variables_panel
            if variables:
                variables.clear()
            output = self.global_output_panel
            if output:
                output.text_edit.clear()
            self.action_label.setText("Resultados limpos")
    
    def _new_file(self):
        """Limpa editor da aba atual"""
        editor = self._get_current_editor()
        if editor:
            editor.clear()
    
    def _open_file(self):
        """Abre workspace ou arquivo de código"""
        filename, _ = QFileDialog.getOpenFileName(
            self, 
            "Abrir Arquivo", 
            "", 
            "Arquivos Suportados (*.sql *.py *.dpw);;DataPyn Workspace (*.dpw);;SQL Files (*.sql);;Python Files (*.py);;All Files (*.*)"
        )
        if filename:
            # Verifica se é workspace
            if filename.endswith('.dpw'):
                self._open_workspace(filename)
            else:
                # Criar NOVA aba para o arquivo
                self._open_code_file(filename)
    
    def _open_code_file(self, filename: str):
        """Abre arquivo de codigo em nova aba com paineis completos"""
        try:
            # 1. Ler conteudo do arquivo
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 2. Detectar linguagem e configurar contexto
            if filename.endswith('.py'):
                language = 'python'
                self._original_file_type = 'python'
            elif filename.endswith('.dpw'):
                language = 'sql'
                self._original_file_type = 'workspace'
            else:
                language = 'sql'
                self._original_file_type = 'sql'
            
            # Armazenar caminho do arquivo original
            self._original_file_path = filename
            
            # 3. Se estava no estado vazio, remover placeholder e mostrar paineis
            self._hide_empty_state()
            
            # 4. Criar nova sessao
            import os
            tab_title = os.path.basename(filename)
            session = self.session_manager.create_session(title=tab_title)
            
            # 5. Criar widget da sessao usando _create_session_widget (centralizado)
            widget = self._create_session_widget(session)
            widget.file_path = filename
            widget._original_content = content
            widget._is_modified = False
            
            # 6. Configurar conteudo
            blocks = widget.editor.get_blocks()
            if blocks:
                blocks[0].set_language(language)
                blocks[0].set_code(content)
            
            # 7. Conectar sinal de modificacao do editor
            widget.editor.content_changed.connect(lambda: self._on_editor_modified(widget))
            
            # 8. Focar na aba criada
            index = self.session_tabs.indexOf(widget)
            if index >= 0:
                self.session_tabs.setCurrentIndex(index)
            
            self.action_label.setText(f"Arquivo aberto: {tab_title}")
            
            # 9. Atualizar titulo da janela com contexto
            self._update_window_title()
            
            # 10. Trocar paineis para a nova sessao
            self._switch_session_panels(session.session_id)
            
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Erro", f"Erro ao abrir arquivo: {e}")
    
    def _save_file(self):
        """Sistema inteligente de salvamento"""
        self._save_intelligently()
    
    def _save_file_as(self):
        """Salva workspace em novo arquivo"""
        filename, _ = QFileDialog.getSaveFileName(
            self, 
            "Salvar Workspace Como", 
            "", 
            "DataPyn Workspace (*.dpw);;All Files (*.*)"
        )
        if filename:
            # Garantir extensão .dpw
            if not filename.endswith('.dpw'):
                filename += '.dpw'
            
            self._save_workspace_to_file(filename)
            
            import os
            self.action_label.setText(f"Workspace salvo: {os.path.basename(filename)}")
    
    def _open_workspace(self, filename: str):
        """Abre um workspace de um arquivo específico"""
        try:
            # Carregar workspace do arquivo
            workspace = self.workspace_manager.load_workspace(filename)
            
            # Fechar todas as sessões atuais
            self._close_all_sessions()
            
            # Recarregar sessões do workspace
            self._restore_sessions()
            
            import os
            self.action_label.setText(f"Workspace aberto: {os.path.basename(filename)}")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Erro ao Abrir Workspace",
                f"Erro ao carregar workspace:\n{str(e)}"
            )
    
    def _save_workspace_to_file(self, filename: str):
        """Salva workspace em arquivo específico"""
        # Sincronizar sessão atual
        widget = self._get_current_session_widget()
        if widget:
            widget.sync_to_session()
        
        # Salvar via SessionManager
        self.session_manager.save_sessions()
        
        # Salvar geometria da janela
        window_geometry = {
            'x': self.geometry().x(),
            'y': self.geometry().y(),
            'width': self.geometry().width(),
            'height': self.geometry().height(),
            'maximized': self.isMaximized()
        }
        
        dock_visible = self.connections_dock.isVisible() if hasattr(self, 'connections_dock') else True
        
        # Salvar no workspace manager com caminho específico
        self.workspace_manager.save_workspace(
            tabs=[],
            active_tab=0,
            active_connection=None,
            window_geometry=window_geometry,
            splitter_sizes=[],
            dock_visible=dock_visible,
            file_path=filename  # Passa o caminho do arquivo
        )
        
        # Limpar marcadores de modificação das abas
        self._clear_modification_markers()
    
    def _clear_modification_markers(self):
        """Remove asteriscos das abas e reseta flags de modificação"""
        for i in range(self.session_tabs.count()):
            widget = self.session_tabs.widget(i)
            if hasattr(widget, '_is_modified'):
                widget._is_modified = False
            
            # Remover asterisco do título da aba se existir
            current_text = self.session_tabs.tabText(i)
            if current_text.endswith(' *'):
                self.session_tabs.setTabText(i, current_text[:-2])
    
    def _update_status(self):
        """Atualiza status periodicamente"""
        # Verifica se conexão da sessão atual ainda está ativa
        session = self.session_manager.focused_session
        if session and session.connector and not session.connector.is_connected():
            session.clear_connection()
            self._update_connection_status()
    
    # _change_theme removido - tema fixo em 'dark'
    
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
        
        # Atualizar paineis de todas as sessoes
        if hasattr(self, '_session_panel_indices'):
            for info in self._session_panel_indices.values():
                info['results'].set_theme_manager(self.theme_manager)
                if hasattr(info['output'], 'set_theme_manager'):
                    info['output'].set_theme_manager(self.theme_manager)
                if hasattr(info['variables'], 'set_theme_manager'):
                    info['variables'].set_theme_manager(self.theme_manager)
        
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
        dialog.shortcuts_changed.connect(self._reload_shortcuts)
        dialog.exec()
    
    def _new_session(self):
        """Cria nova sessão, herdando a conexão da aba atual (se houver)"""
        # Guard para evitar criação duplicada
        if hasattr(self, '_creating_session') and self._creating_session:
            return
        self._creating_session = True
        
        try:
            # Capturar conexão da sessão ativa ANTES de criar a nova
            previous_connection = None
            current_widget = self._get_current_session_widget()
            if current_widget and hasattr(current_widget, 'session'):
                previous_connection = current_widget.session.connection_name
            
            # Se está no estado vazio, remover o placeholder
            self._hide_empty_state()
            
            session = self.session_manager.create_session()
            widget = self._create_session_widget(session)
            
            # Herdar conexão da aba anterior
            if previous_connection:
                try:
                    connected = session.connect(previous_connection)
                    if connected:
                        # Aplicar cor da aba
                        config = self.connection_manager.get_connection_config(previous_connection)
                        if config:
                            color = config.get('color', '#007ACC') or '#007ACC'
                            idx = self.session_tabs.indexOf(widget)
                            if idx >= 0:
                                self.session_tabs.set_tab_connection_color(idx, color)
                except Exception as e:
                    print(f"[AVISO] Nao foi possivel herdar conexao: {e}")
            
            # Atualizar título da janela (contexto pode ter mudado)
            self._update_window_title()
        finally:
            self._creating_session = False
    
    def _handle_empty_state_drop(self, file_paths):
        """Trata drop de arquivos na tela de estado vazio"""
        import os
        
        data_files = []
        code_files = []
        
        for file_path in file_paths:
            ext = os.path.splitext(file_path.lower())[1]
            if ext in ('.csv', '.json', '.xlsx', '.xls'):
                data_files.append(file_path)
            elif ext in ('.sql', '.py', '.dpw'):
                code_files.append(file_path)
        
        # Abrir arquivos de codigo/workspace normalmente
        for file_path in code_files:
            if file_path.lower().endswith('.dpw'):
                self._open_workspace(file_path)
            else:
                self._open_code_file(file_path)
        
        # Abrir arquivos de dados (csv, json, xlsx) com bloco de importacao
        if data_files:
            self._new_session()
            current_index = self.session_tabs.currentIndex()
            widget = self.session_tabs.widget(current_index)
            
            if widget and hasattr(widget, 'editor'):
                editor = widget.editor
                for file_path in data_files:
                    import_code = editor._generate_import_code(file_path)
                    if import_code:
                        editor.add_block(language='python', code=import_code)
                        editor.content_changed.emit()

    def _show_empty_state(self):
        """Mostra estado vazio quando nao ha sessoes, escondendo paineis"""
        if hasattr(self, '_empty_state_widget') and self._empty_state_widget:
            return  # Ja esta mostrando
        
        # Esconder paineis inferiores (sem sessao, nao faz sentido mostralos)
        if hasattr(self, 'results_dock'):
            self.results_dock.hide()
        if hasattr(self, 'output_dock'):
            self.output_dock.hide()
        if hasattr(self, 'variables_dock'):
            self.variables_dock.hide()
        
        # Criar widget de estado vazio com suporte a drag-and-drop
        from PyQt6.QtWidgets import QLabel, QPushButton
        from PyQt6.QtGui import QDragEnterEvent, QDropEvent
        
        main_window_ref = self
        
        class DropEmptyStateWidget(QWidget):
            """Widget de estado vazio com suporte a drag-and-drop de arquivos"""
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setAcceptDrops(True)
            
            def dragEnterEvent(self, event: QDragEnterEvent):
                mime_data = event.mimeData()
                if mime_data.hasUrls():
                    for url in mime_data.urls():
                        file_path = url.toLocalFile()
                        if file_path.lower().endswith(('.csv', '.json', '.xlsx', '.xls', '.sql', '.py', '.dpw')):
                            event.acceptProposedAction()
                            return
            
            def dragMoveEvent(self, event):
                event.acceptProposedAction()
            
            def dropEvent(self, event: QDropEvent):
                mime_data = event.mimeData()
                if mime_data.hasUrls():
                    file_paths = []
                    for url in mime_data.urls():
                        file_path = url.toLocalFile()
                        if file_path.lower().endswith(('.csv', '.json', '.xlsx', '.xls', '.sql', '.py', '.dpw')):
                            file_paths.append(file_path)
                    if file_paths:
                        main_window_ref._handle_empty_state_drop(file_paths)
                        event.acceptProposedAction()
        
        self._empty_state_widget = DropEmptyStateWidget()
        layout = QVBoxLayout(self._empty_state_widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Icone grande
        icon_label = QLabel()
        if hasattr(qta, 'icon'):
            icon_label.setPixmap(qta.icon('mdi.note-text', color='#64b5f6').pixmap(96, 96))
        icon_label.setStyleSheet("font-size: 96px; background: transparent;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)
        
        # Texto principal
        title_label = QLabel("Nenhum script aberto")
        title_label.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: #cccccc;
            margin-top: 20px;
            background: transparent;
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # Subtitulo com dica de drag-and-drop
        subtitle_label = QLabel("Crie uma nova sessao ou arraste um arquivo para comecar")
        subtitle_label.setStyleSheet("""
            font-size: 14px;
            color: #888888;
            margin-top: 10px;
            background: transparent;
        """)
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle_label)
        
        # Botao iniciar
        colors = get_colors()
        start_button = QPushButton("  Iniciar  ")
        start_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: white;
                border: none;
                padding: 12px 40px;
                font-size: 16px;
                font-weight: bold;
                border-radius: 4px;
                margin-top: 30px;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary_hover};
            }}
            QPushButton:pressed {{
                background-color: {colors.interactive_primary_active};
            }}
        """)
        start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        start_button.clicked.connect(self._new_session)
        layout.addWidget(start_button, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Adicionar como "aba" invisivel ou substituir conteudo
        self._empty_state_widget.setStyleSheet("background-color: #1e1e1e;")
        
        # Adicionar aba do empty state
        index = self.session_tabs.addTab(self._empty_state_widget, "")
        
        # Esconder o tab do estado vazio
        self.session_tabs.tabBar().setTabVisible(index, False)
        self.session_tabs.setCurrentIndex(index)
    
    def _hide_empty_state(self):
        """Remove estado vazio e restaura paineis"""
        if hasattr(self, '_empty_state_widget') and self._empty_state_widget:
            index = self.session_tabs.indexOf(self._empty_state_widget)
            if index >= 0:
                self.session_tabs.removeTab(index)
            self._empty_state_widget = None
        
        # Restaurar paineis inferiores ao sair do estado vazio
        if hasattr(self, 'results_dock'):
            self.results_dock.show()
        if hasattr(self, 'output_dock'):
            self.output_dock.show()
        if hasattr(self, 'variables_dock'):
            self.variables_dock.show()
    
    def _create_session_widget(self, session):
        """Cria widget para uma sessao e adiciona a aba"""
        widget = SessionWidget(session, theme_manager=self.theme_manager)
        
        # Criar paineis por sessao (Results, Output, Variables)
        self._create_session_panels(session.session_id)
        
        # Definir file_path no widget se disponivel na sessao
        if hasattr(session, 'file_path') and session.file_path:
            widget.file_path = session.file_path
            
        # Conectar sinais do widget
        widget.execute_cross_syntax.connect(lambda code: self._execute_cross_syntax_for_session(session, code))
        widget.status_changed.connect(lambda msg: self._on_session_status_changed(session, msg))
        widget.connection_changed.connect(lambda conn_name, db: self._on_session_connection_changed(session, conn_name, db))
        
        # Guardar referência
        self._session_widgets[session.session_id] = widget
        
        # Adicionar aba usando método do SessionTabs (já lida com botão +)
        index = self.session_tabs.add_session(widget, session.title)
        
        # Durante restauração, aplicar cor da aba baseada na conexão da sessão
        if hasattr(session, '_connection_name') and session._connection_name:
            config = self.connection_manager.get_connection_config(session._connection_name)
            if config:
                color = config.get('color', '#007ACC') or '#007ACC'
                self.session_tabs.set_tab_connection_color(index, color)
        
        # Trocar paineis para a nova sessao (garante que paineis vazios aparecam)
        self._switch_session_panels(session.session_id)
        
        # Focar automaticamente no primeiro bloco (com delay para garantir renderizacao)
        if widget.editor and hasattr(widget.editor, 'focus_first_block'):
            QTimer.singleShot(50, widget.editor.focus_first_block)
        
        return widget
    
    def _on_session_renamed(self, index: int, new_name: str):
        """Callback quando sessão é renomeada pelo componente SessionTabs"""
        widget = self.session_tabs.widget(index)
        if not isinstance(widget, SessionWidget):
            return
        
        widget.session.title = new_name.strip()
        self._save_sessions()
    
    def _close_session_tab(self, index: int):
        """Fecha aba de sessão"""
        widget = self.session_tabs.widget(index)
        if not isinstance(widget, SessionWidget):
            return  # Ignorar se não é uma SessionWidget (ex: aba do botão +)
        
        # Guard para evitar criar sessão ao fechar
        self._closing_session = True
        
        try:
            # Cleanup e remover
            session_id = widget.session.session_id
            widget.cleanup()
            self.session_manager.close_session(session_id)
            
            # Remover paineis da sessao dos stacks
            self._remove_session_panels(session_id)
            
            # Remover do dicionario apenas se existir
            if session_id in self._session_widgets:
                del self._session_widgets[session_id]
            
            self.session_tabs.removeTab(index)
            self._save_sessions()
            
            # Verificar se não há mais sessões REAIS (ignorar aba do botão +)
            session_count = sum(1 for i in range(self.session_tabs.count()) 
                              if isinstance(self.session_tabs.widget(i), SessionWidget))
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
            # Trocar paineis para a sessao ativa
            self._switch_session_panels(widget.session.session_id)
            
        # Atualizar título da janela quando muda de aba
        self._update_window_title()
    
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
            
            # Destacar conexão na lista
            for i in range(self.connections_list.count()):
                item = self.connections_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == session.connection_name:
                    self.connections_list.setCurrentItem(item)
                    break
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
        
        # Atualizar título da janela quando sessão é focada
        self._update_window_title()
    
    def _on_session_status_changed(self, session, message: str):
        """Callback quando status de uma sessão muda"""
        # Só atualiza se for a sessão focada
        if self.session_manager.focused_session == session:
            self.action_label.setText(message)
    
    def _on_session_connection_changed(self, session, connection_name: str, database: str):
        """
        SERVIÇO CENTRALIZADO: Gerencia mudanças de conexão de sessão
        
        Este método centraliza TODAS as atualizações quando uma sessão conecta/troca de banco:
        - Atualiza painel de conexões ativas
        - Destaca conexão na lista
        - Atualiza status bar
        
        Args:
            session: Sessão que mudou a conexão
            connection_name: Nome da conexão
            database: Nome do banco de dados atual
        """
        # Só atualiza se for a sessão focada
        if self.session_manager.focused_session != session:
            return
        
        # Obter config da conexão
        config = self.connection_manager.get_connection_config(connection_name)
        if not config:
            return
        
        host = config.get('host', 'localhost')
        db_type = config.get('db_type', '')
        
        # Usar o banco retornado (pode ter mudado via USE)
        current_db = database if database else config.get('database', '')
        
        # === ATUALIZAR PAINEL DE CONEXÕES ATIVAS ===
        self.connection_panel.set_active_connection(
            connection_name,
            host=host,
            database=current_db,
            db_type=db_type
        )
        
        # === DESTACAR CONEXÃO NA LISTA ===
        for i in range(self.connections_list.count()):
            item = self.connections_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == connection_name:
                self.connections_list.setCurrentItem(item)
                break
        
        # === ATUALIZAR STATUS BAR ===
        self.action_label.setText(f"Conectado: {connection_name} ({current_db})")
        
        # === DEFINIR COR DA ABA ===
        color = config.get('color', '#007ACC') or '#007ACC'
        # Encontrar índice da aba desta sessão
        for i in range(self.session_tabs.count()):
            widget = self.session_tabs.widget(i)
            if isinstance(widget, SessionWidget) and widget.session == session:
                self.session_tabs.set_tab_connection_color(i, color)
                break
    
    def _on_editor_modified(self, widget):
        """Callback quando o conteúdo do editor é modificado"""
        if not hasattr(widget, '_is_modified'):
            widget._is_modified = False
        
        # Marcar widget como modificado
        if not widget._is_modified:
            widget._is_modified = True
            
            # Atualizar título da aba para indicar modificação
            for i in range(self.session_tabs.count()):
                if self.session_tabs.widget(i) == widget:
                    current_text = self.session_tabs.tabText(i)
                    if not current_text.endswith(' *'):
                        self.session_tabs.setTabText(i, current_text + ' *')
                    break
        
        # Atualizar título da janela (contexto pode ter mudado)
        self._update_window_title()
    
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
            # Focar na sessão ativa
            focused = self.session_manager.focused_session
            if focused:
                index = self.session_manager.get_session_index(focused.session_id)
                if index >= 0:
                    self.session_tabs.setCurrentIndex(index)
                
                # Atualizar indicador de conexão (se existir connection_panel)
                if focused.is_connected and hasattr(self, 'connection_panel'):
                    # database_name removido - Session só tem connection_name
                    self.connection_panel.set_active_connection(
                        focused.connection_name,
                        focused.connection_name  # usar connection_name no lugar de database_name
                    )
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
    
    # =========================================================================
    # Sistema de Gerenciamento Inteligente de Arquivos
    # =========================================================================
    
    def _detect_file_context(self) -> str:
        """
        Detecta o contexto atual baseado no número de blocos e tipos
        
        Returns:
            'sql'       - um bloco SQL apenas
            'python'    - um bloco Python apenas  
            'workspace' - múltiplos blocos ou arquivo .dpw
        """
        # Se tem múltiplas sessões = sempre workspace
        if len(self._session_widgets) > 1:
            return 'workspace'
            
        # Se arquivo original já é workspace
        if self._original_file_type == 'workspace':
            return 'workspace'
            
        # Se não há sessões mas há arquivo original sql/py, usa tipo do arquivo
        current_widget = self._get_current_session_widget()
        if not current_widget:
            if self._original_file_type in ['sql', 'python']:
                return self._original_file_type
            return 'workspace'
            
        blocks = current_widget.editor.get_blocks()
        
        # Se tem mais de 1 bloco = workspace
        if len(blocks) > 1:
            return 'workspace'
            
        # Se tem 1 bloco apenas, usar tipo do arquivo original ou tipo do bloco
        if len(blocks) == 1:
            block_language = blocks[0].get_language()
            if self._original_file_type in ['sql', 'python']:
                # Se bloco é compatível com arquivo original
                if (self._original_file_type == 'sql' and block_language == 'sql') or \
                   (self._original_file_type == 'python' and block_language == 'python'):
                    return self._original_file_type
            else:
                # Novo arquivo, usar linguagem do bloco
                if block_language in ['sql', 'python']:
                    return block_language
        
        # Fallback: se tem arquivo original sql/py, usar ele
        if self._original_file_type in ['sql', 'python']:
            return self._original_file_type
            
        return 'workspace'
    
    def _update_window_title(self):
        """Atualiza título da janela com indicador de contexto"""
        base_title = "DataPyn - IDE SQL + Python"
        
        # Detectar contexto atual
        context = self._detect_file_context()
        self._current_context = context
        
        # Adicionar indicador
        if context == 'sql':
            indicator = "[S]"
        elif context == 'python':
            indicator = "[P]"
        else:
            indicator = "[W]"
            
        # Adicionar nome do arquivo se disponível
        file_info = ""
        if self._original_file_path:
            import os
            filename = os.path.basename(self._original_file_path)
            file_info = f" - {filename}"
        elif self.workspace_manager.current_file_path:
            import os
            filename = os.path.basename(self.workspace_manager.current_file_path)
            file_info = f" - {filename}"
            
        self.setWindowTitle(f"{indicator} {base_title}{file_info}")
    
    def _save_intelligently(self):
        """Sistema inteligente de salvamento baseado no contexto"""
        context = self._detect_file_context()
        
        if context in ['sql', 'python']:
            # Contexto de arquivo único - salvar no arquivo original
            if self._original_file_path:
                self._save_single_file(self._original_file_path, context)
            else:
                # Pedir caminho para arquivo único
                self._save_single_file_as(context)
        else:
            # Contexto workspace - usar workspace_manager diretamente
            window_geometry = {
                'x': self.geometry().x(),
                'y': self.geometry().y(),
                'width': self.geometry().width(),
                'height': self.geometry().height(),
                'maximized': self.isMaximized()
            }
            
            dock_visible = self.connections_dock.isVisible() if hasattr(self, 'connections_dock') else True
            
            self.workspace_manager.save_workspace(
                tabs=[],
                active_tab=0,
                active_connection=None,
                window_geometry=window_geometry,
                splitter_sizes=[],
                dock_visible=dock_visible
            )
    
    def _save_single_file(self, file_path: str, file_type: str):
        """Salva conteúdo em arquivo único (sql/py)"""
        try:
            current_widget = self._get_current_session_widget()
            if not current_widget:
                return
                
            blocks = current_widget.editor.get_blocks()
            if not blocks:
                return
                
            # Pegar conteúdo do primeiro bloco
            content = blocks[0].get_code()
            
            # Salvar arquivo
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
            # Limpar marcador de modificação
            current_widget._is_modified = False
            self._clear_modification_markers()
            
            # Atualizar status
            import os
            filename = os.path.basename(file_path)
            self.action_label.setText(f"Arquivo salvo: {filename}")
            
            self._update_window_title()
            
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Erro", f"Erro ao salvar arquivo: {e}")
    
    def _save_single_file_as(self, file_type: str):
        """Pede caminho para salvar arquivo único"""
        from PyQt6.QtWidgets import QFileDialog
        
        if file_type == 'sql':
            filter_text = "Arquivos SQL (*.sql);;Todos os arquivos (*.*)"
            default_ext = '.sql'
        else:
            filter_text = "Arquivos Python (*.py);;Todos os arquivos (*.*)"
            default_ext = '.py'
        
        filename, _ = QFileDialog.getSaveFileName(
            self, 
            f"Salvar Arquivo {file_type.upper()}", 
            "", 
            filter_text
        )
        
        if filename:
            # Garantir extensão correta
            if not filename.endswith(default_ext):
                filename += default_ext
                
            self._original_file_path = filename
            self._original_file_type = file_type
            self._save_single_file(filename, file_type)

    def closeEvent(self, event):
        """Ao fechar a janela"""
        # Verificar se há execução em andamento
        has_running = any(
            widget._is_executing 
            for widget in self._session_widgets.values()
            if hasattr(widget, '_is_executing')
        )
        
        if has_running:
            reply = QMessageBox.question(
                self,
                "Execução em andamento",
                "Há código sendo executado. Deseja cancelar e fechar a aplicação?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            
            # Cancelar todas as execuções
            for widget in self._session_widgets.values():
                if hasattr(widget, '_cancel_requested'):
                    widget._cancel_requested = True
        
        # Salvar sessões antes de fechar
        self._save_sessions()
        
        # Cleanup de todas as sessões
        for widget in self._session_widgets.values():
            widget.cleanup()
        
        self.session_manager.cleanup_all()
        
        # Fechar conexões
        self.connection_manager.close_all()
        event.accept()
