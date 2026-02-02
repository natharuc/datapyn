"""
Tabs de sessão

Gerencia as abas de sessão da IDE.
"""
from PyQt6.QtWidgets import QTabWidget, QTabBar, QWidget, QInputDialog, QMenu, QLineEdit
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QAction
import qtawesome as qta
import subprocess
import os


class SessionTabBar(QTabBar):
    """TabBar customizado para sessões"""
    
    tab_renamed = pyqtSignal(int, str)  # index, new_name
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._setup_style()
        self._setup_context_menu()
    
    def _setup_style(self):
        """Configura estilo"""
        self.setStyleSheet("""
            QTabBar::tab {
                background-color: #2d2d30;
                color: #cccccc;
                padding: 8px 20px;
                padding-right: 28px;
                border: 1px solid #3e3e42;
                border-bottom: none;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QTabBar::tab:hover:!selected {
                background-color: #3e3e42;
            }
            QTabBar::close-button {
                subcontrol-position: right;
                margin-right: 6px;
                padding: 2px;
                width: 14px;
                height: 14px;
            }
            QTabBar::close-button:hover {
                background-color: #f48771;
                border-radius: 2px;
            }
        """)
    
    def _setup_context_menu(self):
        """Configura context menu"""
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
    
    def _show_context_menu(self, pos):
        """Mostra context menu"""
        index = self.tabAt(pos)
        if index < 0:
            return
        
        menu = QMenu(self)
        
        # Obter caminho do arquivo se existir
        tab_widget = self.parent()
        widget = tab_widget.widget(index)
        file_path = getattr(widget, 'file_path', None) if widget else None
        
        # 1. Abrir local do arquivo
        if file_path and os.path.exists(file_path):
            open_location_action = QAction(qta.icon('mdi.folder-open'), "Abrir Local do Arquivo", self)
            open_location_action.triggered.connect(lambda: self._open_file_location(file_path))
            menu.addAction(open_location_action)
            menu.addSeparator()
        
        # 2. Fechar tudo
        close_all_action = QAction(qta.icon('mdi.close-box-multiple'), "Fechar Tudo", self)
        close_all_action.triggered.connect(lambda: self._close_all_tabs())
        menu.addAction(close_all_action)
        
        # 3. Fechar todas as outras
        close_others_action = QAction(qta.icon('mdi.close-box-outline'), "Fechar Todas as Outras", self)
        close_others_action.triggered.connect(lambda: self._close_other_tabs(index))
        menu.addAction(close_others_action)
        
        menu.addSeparator()
        
        # 4. Renomear
        rename_action = QAction(qta.icon('mdi.pencil'), "Renomear", self)
        rename_action.triggered.connect(lambda: self._rename_tab_inline(index))
        menu.addAction(rename_action)
        
        # 5. Duplicar
        duplicate_action = QAction(qta.icon('mdi.content-copy'), "Duplicar", self)
        duplicate_action.triggered.connect(lambda: self._duplicate_tab(index))
        menu.addAction(duplicate_action)
        
        menu.addSeparator()
        
        # 5. Fechar
        close_action = QAction(qta.icon('mdi.close'), "Fechar", self)
        close_action.triggered.connect(lambda: self._close_tab(index))
        menu.addAction(close_action)
        
        menu.exec(self.mapToGlobal(pos))
    
    def _open_file_location(self, file_path):
        """Abre o local do arquivo no explorer"""
        folder = os.path.dirname(file_path)
        if os.path.exists(folder):
            if os.name == 'nt':  # Windows
                subprocess.run(['explorer', '/select,', file_path])
            elif os.name == 'posix':  # Linux/Mac
                subprocess.run(['xdg-open', folder])
    
    def _close_all_tabs(self):
        """Fecha todas as abas"""
        tab_widget = self.parent()
        if tab_widget:
            # Fechar de trás para frente para evitar mudanças de índice
            for i in range(tab_widget.count() - 1, -1, -1):
                tab_widget.session_closed.emit(i)
    
    def _close_other_tabs(self, keep_index):
        """Fecha todas as abas exceto a especificada"""
        tab_widget = self.parent()
        if tab_widget:
            # Fechar de trás para frente
            for i in range(tab_widget.count() - 1, -1, -1):
                if i != keep_index:
                    tab_widget.session_closed.emit(i)
    
    def _rename_tab_inline(self, index):
        """Renomeia a aba usando input inline"""
        if index < 0:
            return
        
        # Criar QLineEdit para edição inline
        line_edit = QLineEdit(self)
        line_edit.setText(self.tabText(index))
        line_edit.selectAll()
        line_edit.setStyleSheet("""
            QLineEdit {
                background-color: #3e3e42;
                color: #ffffff;
                border: 1px solid #007acc;
                padding: 4px 8px;
                font-size: 11px;
            }
        """)
        
        # Função para salvar o novo nome
        def save_name():
            new_name = line_edit.text().strip()
            if new_name:
                self.setTabText(index, new_name)
                self.tab_renamed.emit(index, new_name)
            line_edit.deleteLater()
        
        # Conectar Enter para salvar
        line_edit.returnPressed.connect(save_name)
        line_edit.editingFinished.connect(save_name)
        
        # Posicionar o line_edit sobre a aba
        tab_rect = self.tabRect(index)
        line_edit.setGeometry(tab_rect.adjusted(4, 4, -30, -4))
        line_edit.show()
        line_edit.setFocus()
    
    def _duplicate_tab(self, index):
        """Duplica a aba"""
        tab_widget = self.parent()
        if tab_widget and hasattr(tab_widget, 'duplicate_session'):
            tab_widget.duplicate_session.emit(index)
    
    def _close_tab(self, index):
        """Fecha uma aba"""
        tab_widget = self.parent()
        if tab_widget:
            tab_widget.session_closed.emit(index)
    
    def mouseDoubleClickEvent(self, event):
        """Renomear aba ao dar duplo clique usando input inline"""
        index = self.tabAt(event.pos())
        if index >= 0:
            self._rename_tab_inline(index)
        else:
            super().mouseDoubleClickEvent(event)


class SessionTabs(QTabWidget):
    """Widget de abas de sessão"""
    
    # Sinais
    session_changed = pyqtSignal(int)  # index
    session_closed = pyqtSignal(int)   # index
    session_renamed = pyqtSignal(int, str)  # index, new_name
    new_session_requested = pyqtSignal()
    duplicate_session = pyqtSignal(int)  # index - duplicar sessão
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._setup_ui()
        self._setup_style()
        self._connect_signals()
    
    def _setup_ui(self):
        """Configura UI"""
        # TabBar customizado
        self.tab_bar = SessionTabBar()
        self.setTabBar(self.tab_bar)
        
        # Configurações
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
    
    def _setup_close_button(self, index):
        """Configura ícone X no botão de fechar da aba"""
        from PyQt6.QtWidgets import QToolButton
        
        # Criar botão customizado
        close_btn = QToolButton()
        close_btn.setIcon(qta.icon('mdi.close', color='#cccccc', scale_factor=1.4))
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 2px;
                margin-right: 10px;
            }
            QToolButton:hover {
                background-color: #3e3e42;
            }
        """)
        close_btn.clicked.connect(lambda: self.tabCloseRequested.emit(index))
        
        # Substituir botão padrão
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, close_btn)
    
    def _setup_style(self):
        """Configura estilo"""
        self.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #3e3e42;
                background-color: #1e1e1e;
            }
            QTabWidget::tab-bar {
                alignment: left;
            }
        """)
    
    def _connect_signals(self):
        """Conecta sinais"""
        self.currentChanged.connect(self.session_changed.emit)
        self.tabCloseRequested.connect(self._on_close_requested)
        self.tab_bar.tab_renamed.connect(self.session_renamed.emit)
    
    def _on_close_requested(self, index: int):
        """Trata pedido de fechar aba"""
        # Emite sinal para o main_window tratar (pode fechar todas as abas)
        self.session_closed.emit(index)
    
    def add_session(self, widget: QWidget, name: str, make_current: bool = True) -> int:
        """Adiciona nova sessão
        
        Returns:
            Índice da nova aba
        """
        index = self.addTab(widget, name)
        
        # Configurar botão de fechar customizado
        self._setup_close_button(index)
        
        if make_current:
            self.setCurrentIndex(index)
        
        return index
    
    def remove_session(self, index: int):
        """Remove sessão"""
        if self.count() > 1:
            self.removeTab(index)
    
    def rename_session(self, index: int, name: str):
        """Renomeia sessão"""
        self.setTabText(index, name)
    
    def set_tab_color(self, index: int, color: str):
        """Define cor do tab (para indicar status)"""
        self.tabBar().setTabTextColor(index, QColor(color))
    
    def set_tab_running(self, index: int, is_running: bool):
        """Indica se sessão está executando"""
        current_text = self.tabText(index)
        
        if is_running and not current_text.startswith("⏳ "):
            self.setTabText(index, f"⏳ {current_text}")
        elif not is_running and current_text.startswith("⏳ "):
            self.setTabText(index, current_text[3:])
    
    def get_session_name(self, index: int) -> str:
        """Retorna nome da sessão"""
        name = self.tabText(index)
        # Remove indicador de execução se presente
        if name.startswith("⏳ "):
            return name[3:]
        return name
