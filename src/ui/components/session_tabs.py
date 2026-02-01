"""
Tabs de sessão

Gerencia as abas de sessão da IDE.
"""
from PyQt6.QtWidgets import QTabWidget, QTabBar, QWidget, QInputDialog
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor


class SessionTabBar(QTabBar):
    """TabBar customizado para sessões"""
    
    tab_renamed = pyqtSignal(int, str)  # index, new_name
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._setup_style()
    
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
                image: url(close.png);
                subcontrol-position: right;
                margin-right: 6px;
                padding: 2px;
            }
            QTabBar::close-button:hover {
                background-color: #f48771;
                border-radius: 2px;
            }
        """)
    
    def mouseDoubleClickEvent(self, event):
        """Renomear aba ao dar duplo clique"""
        index = self.tabAt(event.pos())
        if index >= 0:
            current_name = self.tabText(index)
            new_name, ok = QInputDialog.getText(
                self, "Renomear Sessão",
                "Novo nome:",
                text=current_name
            )
            if ok and new_name:
                self.setTabText(index, new_name)
                self.tab_renamed.emit(index, new_name)
        
        super().mouseDoubleClickEvent(event)


class SessionTabs(QTabWidget):
    """Widget de abas de sessão"""
    
    # Sinais
    session_changed = pyqtSignal(int)  # index
    session_closed = pyqtSignal(int)   # index
    session_renamed = pyqtSignal(int, str)  # index, new_name
    new_session_requested = pyqtSignal()
    
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
