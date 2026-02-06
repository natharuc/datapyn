"""
Tabs de sessão

Gerencia as abas de sessão da IDE.
"""
from PyQt6.QtWidgets import QTabWidget, QTabBar, QWidget, QInputDialog, QMenu, QLineEdit
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QAction, QPainter, QPen
import qtawesome as qta
from typing import Dict
import subprocess
import os


class SessionTabBar(QTabBar):
    """TabBar customizado para sessões"""
    
    tab_renamed = pyqtSignal(int, str)  # index, new_name
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tab_colors: Dict[int, str] = {}  # Armazena cor por índice da aba
        
        self._setup_style()
        self._setup_context_menu()
    
    def _setup_style(self):
        """Configura estilo"""
        self.setStyleSheet("""
            QTabBar {
                background-color: #252526;
            }
            QTabBar::tab {
                background-color: #2d2d30;
                color: #999999;
                padding: 6px 16px;
                padding-right: 28px;
                border: none;
                border-bottom: 2px solid transparent;
                margin-right: 1px;
                min-width: 80px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #ffffff;
                border-bottom: 2px solid #3369FF;
            }
            QTabBar::tab:hover:!selected {
                background-color: #37373d;
                color: #cccccc;
            }
            QTabBar::close-button {
                subcontrol-position: right;
                margin-right: 4px;
                padding: 0px;
            }
            QTabBar::close-button:hover {
                background-color: rgba(231, 76, 60, 0.9);
                border-radius: 3px;
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
        import os.path
        if os.path.exists(file_path):
            if os.name == 'nt':  # Windows
                # Comando correto: explorer.exe /select,"caminho"
                subprocess.run(['explorer.exe', f'/select,"{file_path}"'])
            elif os.name == 'posix':  # Linux/Mac
                folder = os.path.dirname(file_path)
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
        
        # Posicionar o line_edit sobre a aba (deixar 60px à direita para o close button)
        tab_rect = self.tabRect(index)
        line_edit.setGeometry(tab_rect.adjusted(8, 6, -60, -6))
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
    
    def set_tab_connection_color(self, index: int, color: str):
        """Define cor da conexão para uma aba específica"""
        self._tab_colors[index] = color
        self.update()  # Força repaint
    
    def clear_tab_connection_color(self, index: int):
        """Remove cor da conexão de uma aba"""
        if index in self._tab_colors:
            del self._tab_colors[index]
            self.update()
    
    def paintEvent(self, event):
        """Override para pintar bordas coloridas nas abas"""
        # Pintar normalmente primeiro
        super().paintEvent(event)
        
        # Pintar bordas coloridas
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        for index, color in self._tab_colors.items():
            if index < self.count():  # Verifica se índice ainda é válido
                rect = self.tabRect(index)
                if rect.isValid():
                    # Pintar linha colorida na parte inferior da aba
                    pen = QPen(QColor(color))
                    pen.setWidth(3)
                    painter.setPen(pen)
                    painter.drawLine(
                        rect.left() + 2, rect.bottom() - 1,
                        rect.right() - 2, rect.bottom() - 1
                    )


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
        """Configura ícone X no botão de fechar da aba - elegante e compacto"""
        from PyQt6.QtWidgets import QToolButton
        from PyQt6.QtCore import Qt
        
        # Criar botão customizado compacto e elegante com ícone X
        close_btn = QToolButton()
        close_btn.setIcon(qta.icon('mdi.close', color='#999999', scale_factor=0.7))
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                margin-right: 0px;
                border-radius: 0px;
            }
            QToolButton:hover {
                background-color: rgba(231, 76, 60, 0.8);
            }
        """)
        
        # Atualizar icone no hover para branco
        def on_hover_enter(event):
            close_btn.setIcon(qta.icon('mdi.close', color='#ffffff', scale_factor=0.7))
            QToolButton.enterEvent(close_btn, event)
        
        def on_hover_leave(event):
            close_btn.setIcon(qta.icon('mdi.close', color='#999999', scale_factor=0.7))
            QToolButton.leaveEvent(close_btn, event)
        
        close_btn.enterEvent = on_hover_enter
        close_btn.leaveEvent = on_hover_leave
        
        # IMPORTANTE: Buscar índice dinamicamente no momento do click
        # porque os índices mudam quando abas são removidas
        def request_close():
            # Encontrar o índice atual desta aba pelo botão
            for i in range(self.count()):
                btn = self.tabBar().tabButton(i, QTabBar.ButtonPosition.RightSide)
                if btn == close_btn:
                    self.tabCloseRequested.emit(i)
                    return
        
        close_btn.clicked.connect(request_close)
        
        # Substituir botão padrão
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, close_btn)
    
    def _setup_style(self):
        """Configura estilo"""
        self.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                border-top: 1px solid #3e3e42;
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
        # Adicionar aba normalmente
        index = self.addTab(widget, name)
        
        # Configurar botão de fechar customizado
        self._setup_close_button(index)
        
        if make_current:
            self.setCurrentIndex(index)
        
        return index
    
    def remove_session(self, index: int):
        """Remove sessão (permite fechar última aba)"""
        # Limpar cor da aba antes de remover
        self.tab_bar.clear_tab_connection_color(index)
        self.removeTab(index)
    
    def rename_session(self, index: int, name: str):
        """Renomeia sessão"""
        self.setTabText(index, name)
    
    def set_tab_color(self, index: int, color: str):
        """Define cor do tab (para indicar status)"""
        self.tabBar().setTabTextColor(index, QColor(color))
    
    def set_tab_connection_color(self, index: int, color: str):
        """Define faixa colorida no tab para indicar conexão ativa"""
        self.tab_bar.set_tab_connection_color(index, color)
    
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

    def refresh_close_buttons(self):
        """Reaplica o botão de fechar customizado em todas as abas (exceto a última 'nova aba').

        Use isto quando o estilo foi alterado em runtime para forçar atualização dos botões.
        """
        total = self.count()
        # Não tocar na última aba que é o botão de nova aba (index = total-1)
        for i in range(total - 1):
            # Reaplica o botão customizado
            try:
                self._setup_close_button(i)
            except Exception:
                # Não falhar se uma aba estiver em processo de remoção
                continue
