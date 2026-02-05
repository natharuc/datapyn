"""
CodeBlock - Um bloco de código individual com seletor de linguagem

Similar a uma célula de notebook Jupyter.
Usa editor configurável via editor_config (QScintilla ou Monaco).
"""
import time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, 
    QPushButton, QLabel, QFrame, QSizePolicy
)
from PyQt6.QtCore import pyqtSignal, Qt, QMimeData, QPoint
from PyQt6.QtGui import QDrag, QPixmap, QPainter, QColor

from src.core.theme_manager import ThemeManager
from src.editors.editor_config import get_code_editor_class


class CodeBlock(QFrame):
    """
    Um bloco de código individual.
    
    Contém:
    - Barra de controle (linguagem, executar, remover)
    - Editor Monaco
    """
    
    execute_requested = pyqtSignal(object)  # self
    remove_requested = pyqtSignal(object)  # self
    move_requested = pyqtSignal(object, int)  # self, new_index (-1 = drag started)
    language_changed = pyqtSignal(object, str)  # self, new_language
    focus_changed = pyqtSignal(object, bool)  # self, has_focus
    cancel_requested = pyqtSignal(object)  # self - para cancelar execução
    
    LANGUAGE_COLORS = {
        'python': '#3572A5',
        'sql': '#E38C00',
        'cross': '#6B4C9A'
    }
    
    def __init__(self, theme_manager: ThemeManager = None, parent=None, default_language='sql', default_connection=None):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self._is_focused = False
        self._is_running = False
        self._is_waiting = False
        self._is_resizing = False
        self._resize_start_y = 0
        self._resize_start_height = 0
        self._execution_start_time = 0
        self._last_execution_time = None
        self._default_language = default_language
        self._connection_name = default_connection  # Conexão do bloco
        
        self._setup_ui()
        self._connect_signals()
        # Configurar linguagem inicial explicitamente (setCurrentIndex não dispara signal durante init)
        self.editor.set_language(self._default_language)
        self._update_style()
    
    def _setup_ui(self):
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Plain)
        self.setLineWidth(2)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # === Barra de controle ===
        self.control_bar = QWidget()
        self.control_bar.setFixedHeight(32)
        control_layout = QHBoxLayout(self.control_bar)
        control_layout.setContentsMargins(8, 4, 8, 4)
        control_layout.setSpacing(8)
        
        # Drag handle
        self.drag_handle = QPushButton("≡")
        self.drag_handle.setFixedSize(24, 24)
        self.drag_handle.setToolTip("Arraste para reposicionar")
        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        self.drag_handle.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #888;
                border: none;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #fff;
                background: #444;
                border-radius: 4px;
            }
        """)
        self.drag_handle.pressed.connect(self._start_drag)
        control_layout.addWidget(self.drag_handle)
        
        # Indicador de linguagem
        self.lang_indicator = QFrame()
        self.lang_indicator.setFixedWidth(4)
        self.lang_indicator.setMinimumHeight(20)
        control_layout.addWidget(self.lang_indicator)
        
        # Seletor de linguagem
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Python", "python")
        self.lang_combo.addItem("SQL", "sql")
        self.lang_combo.addItem("Cross-Syntax", "cross")
        # Definir SQL como padrão
        if self._default_language == 'sql':
            self.lang_combo.setCurrentIndex(1)
        elif self._default_language == 'cross':
            self.lang_combo.setCurrentIndex(2)
        else:
            self.lang_combo.setCurrentIndex(0)
        self.lang_combo.setFixedWidth(120)
        control_layout.addWidget(self.lang_combo)
        
        # Seletor de conexão
        self.conn_combo = QComboBox()
        self.conn_combo.setFixedWidth(150)
        self.conn_combo.setToolTip("Conexao de dados para este bloco")
        self.conn_combo.setStyleSheet("""
            QComboBox {
                background: #2d2d30;
                color: #ccc;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 2px 6px;
            }
            QComboBox:hover {
                border-color: #007acc;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
        """)
        control_layout.addWidget(self.conn_combo)
        
        # Status - estilo mais moderno
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 11px;
                padding: 3px 8px;
                background: transparent;
                border-radius: 3px;
            }
        """)
        control_layout.addWidget(self.status_label)
        
        # Botão cancelar (visível apenas durante execução) - estilo moderno flat
        try:
            import qtawesome as qta
            self.cancel_btn = QPushButton()
            self.cancel_btn.setIcon(qta.icon('mdi.stop-circle-outline', color='#e74c3c'))
            self.cancel_btn.setText("Cancelar")
        except:
            self.cancel_btn = QPushButton("Cancelar")
        
        self.cancel_btn.setFixedHeight(24)
        self.cancel_btn.setToolTip("Cancelar execução (Esc)")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #e74c3c;
                border: 1px solid #e74c3c;
                border-radius: 3px;
                padding: 2px 8px;
                font-size: 10px;
            }
            QPushButton:hover {
                background: #e74c3c;
                color: white;
            }
        """)
        self.cancel_btn.hide()  # Escondido por padrão
        control_layout.addWidget(self.cancel_btn)
        
        control_layout.addStretch()
        
        # Botão executar
        self.run_btn = QPushButton("▶")
        self.run_btn.setFixedSize(28, 24)
        self.run_btn.setToolTip("Executar (F5)")
        self.run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        control_layout.addWidget(self.run_btn)
        
        # Botão remover - ícone melhor
        try:
            import qtawesome as qta
            self.remove_btn = QPushButton()
            self.remove_btn.setIcon(qta.icon('mdi.close-circle', color='#999', scale_factor=1.1))
        except:
            self.remove_btn = QPushButton("✖")
        
        self.remove_btn.setFixedSize(28, 28)
        self.remove_btn.setToolTip("Remover bloco")
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #999;
                border: none;
                border-radius: 14px;
            }
            QPushButton:hover {
                background: #e74c3c;
                color: white;
            }
        """)
        control_layout.addWidget(self.remove_btn)
        
        layout.addWidget(self.control_bar)
        
        # === Container do Editor (redimensionável) ===
        self.editor_container = QWidget()
        self.editor_container.setMinimumHeight(80)
        self.editor_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        editor_layout = QVBoxLayout(self.editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)
        
        # Code Editor (configurável via editor_config - implementa ICodeEditor)
        EditorClass = get_code_editor_class()
        self.editor = EditorClass(theme_manager=self.theme_manager)
        
        # Compatibilidade: get_widget() para QScintilla, direto para Monaco
        editor_widget = self.editor.get_widget() if hasattr(self.editor, 'get_widget') else self.editor
        editor_layout.addWidget(editor_widget)
        
        layout.addWidget(self.editor_container, 1)  # stretch=1 para expandir
        
        # === Resize handle ===
        self.resize_handle = QFrame()
        self.resize_handle.setFixedHeight(6)
        self.resize_handle.setCursor(Qt.CursorShape.SizeVerCursor)
        self.resize_handle.setStyleSheet("""
            QFrame { background: transparent; }
            QFrame:hover { background: #555; }
        """)
        self.resize_handle.mousePressEvent = self._resize_start
        self.resize_handle.mouseMoveEvent = self._resize_move
        self.resize_handle.mouseReleaseEvent = self._resize_end
        layout.addWidget(self.resize_handle)
        
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    
    def _connect_signals(self):
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        self.run_btn.clicked.connect(lambda: self.execute_requested.emit(self))
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(self))
        self.editor.execute_requested.connect(lambda: self.execute_requested.emit(self))
        self.editor.SCN_FOCUSIN.connect(self._on_focus_in)
        self.editor.SCN_FOCUSOUT.connect(self._on_focus_out)
    
    def _on_focus_in(self):
        self._is_focused = True
        self._update_style()
        self.focus_changed.emit(self, True)
    
    def _on_focus_out(self):
        self._is_focused = False
        self._update_style()
        self.focus_changed.emit(self, False)
    
    def _on_language_changed(self):
        lang = self.lang_combo.currentData()
        self.editor.set_language(lang)
        self._update_style()
        self.language_changed.emit(self, lang)
    
    def _update_style(self):
        lang = self.get_language()
        color = self.LANGUAGE_COLORS.get(lang, '#888')
        
        self.lang_indicator.setStyleSheet(f"background-color: {color};")
        
        self.run_btn.setStyleSheet(f"""
            QPushButton {{
                background: {color};
                color: white;
                border: none;
                border-radius: 3px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {color}dd; }}
        """)
        
        if self._is_focused:
            self.setStyleSheet(f"CodeBlock {{ border: 2px solid {color}; border-radius: 4px; }}")
        else:
            self.setStyleSheet("CodeBlock { border: 1px solid #444; border-radius: 4px; }")
    
    # === API Pública ===
    
    def get_language(self) -> str:
        return self.lang_combo.currentData()
    
    def set_language(self, lang: str):
        index = self.lang_combo.findData(lang)
        if index >= 0:
            self.lang_combo.setCurrentIndex(index)
            # Garantir que o editor seja atualizado mesmo em mudanças programáticas
            self._on_language_changed()
    
    def get_connection_name(self) -> str:
        """Retorna nome da conexão selecionada ou string vazia"""
        if self.conn_combo.currentIndex() < 0:
            return ''
        return self.conn_combo.currentData() or ''
    
    def set_connection_name(self, conn_name: str):
        """Define conexão selecionada"""
        self._connection_name = conn_name
        # Atualizar combo se já populado
        index = self.conn_combo.findData(conn_name)
        if index >= 0:
            self.conn_combo.setCurrentIndex(index)
    
    def update_available_connections(self, connections: list):
        """
        Atualiza lista de conexões disponíveis
        
        Args:
            connections: Lista de tuplas (name, display_name)
        """
        current = self.get_connection_name()
        self.conn_combo.clear()
        
        # Adicionar opção "Padrão da aba"
        self.conn_combo.addItem("(Padrao da aba)", "")
        
        # Adicionar conexões
        for conn_name, display_name in connections:
            self.conn_combo.addItem(display_name, conn_name)
        
        # Restaurar seleção ou usar padrão
        if current:
            index = self.conn_combo.findData(current)
            if index >= 0:
                self.conn_combo.setCurrentIndex(index)
            else:
                self.conn_combo.setCurrentIndex(0)  # Padrão da aba
        elif self._connection_name:
            index = self.conn_combo.findData(self._connection_name)
            if index >= 0:
                self.conn_combo.setCurrentIndex(index)
            else:
                self.conn_combo.setCurrentIndex(0)
        else:
            self.conn_combo.setCurrentIndex(0)  # Padrão da aba
    
    def get_code(self) -> str:
        return self.editor.get_text()
    
    def set_code(self, code: str):
        self.editor.set_text(code)
    
    def get_selected_text(self) -> str:
        return self.editor.get_selected_text()
    
    def has_selection(self) -> bool:
        return self.editor.has_selection()
    
    def is_focused(self) -> bool:
        return self._is_focused
    
    def set_waiting(self, waiting: bool):
        """Define estado de aguardando na fila"""
        self._is_waiting = waiting
        if waiting:
            self.run_btn.setText("Pausar")
            self.status_label.setText("⏱ Aguardando")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #95a5a6;
                    font-size: 11px;
                    padding: 3px 8px;
                    background: rgba(149, 165, 166, 0.1);
                    border-radius: 3px;
                }
            """)
            self.cancel_btn.hide()
        else:
            if not self._is_running:
                self.run_btn.setText("▶")
    
    def set_running(self, running: bool):
        self._is_running = running
        self._is_waiting = False  # Não está mais aguardando
        if running:
            self._execution_start_time = time.time()
            self.run_btn.setText("◼")
            self.status_label.setText("▶ Executando")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #f39c12;
                    font-size: 11px;
                    padding: 3px 8px;
                    background: rgba(243, 156, 18, 0.1);
                    border-radius: 3px;
                }
            """)
            self.cancel_btn.show()  # Mostra botão de cancelar
        else:
            self.run_btn.setText("▶")
            self.cancel_btn.hide()  # Esconde botão de cancelar
            if self._execution_start_time > 0:
                elapsed = time.time() - self._execution_start_time
                self._last_execution_time = elapsed
                self._execution_start_time = 0
                self.status_label.setText(f"✓ {self._format_execution_time(elapsed)}")
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #2ecc71;
                        font-size: 11px;
                        padding: 3px 8px;
                        background: rgba(46, 204, 113, 0.1);
                        border-radius: 3px;
                    }
                """)
            else:
                self.status_label.setText("")
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #888;
                        font-size: 11px;
                        padding: 3px 8px;
                        background: transparent;
                        border-radius: 3px;
                    }
                """)
    
    def set_cancelled(self):
        """Define estado de cancelado"""
        self._is_running = False
        self._is_waiting = False
        self.run_btn.setText("▶")
        self.cancel_btn.hide()
        self.status_label.setText("✕ Cancelado")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #e74c3c;
                font-size: 11px;
                padding: 3px 8px;
                background: rgba(231, 76, 60, 0.1);
                border-radius: 3px;
            }
        """)
        self._execution_start_time = 0
    
    def set_error(self):
        """Define estado de erro"""
        self._is_running = False
        self._is_waiting = False
        self.run_btn.setText("▶")
        self.cancel_btn.hide()
        self.status_label.setText("⚠ Erro")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #e74c3c;
                font-size: 11px;
                padding: 3px 8px;
                background: rgba(231, 76, 60, 0.15);
                border-radius: 3px;
                font-weight: bold;
            }
        """)
        self._execution_start_time = 0
    
    def _format_execution_time(self, seconds: float) -> str:
        """Formata o tempo de execução para exibição"""
        if seconds < 0.001:
            return f"{seconds*1000000:.0f}µs"
        elif seconds < 1:
            return f"{seconds*1000:.0f}ms"
        elif seconds < 60:
            return f"{seconds:.2f}s"
        else:
            mins = int(seconds // 60)
            secs = seconds % 60
            return f"{mins}m {secs:.1f}s"
    
    def focus_editor(self):
        self.editor.setFocus()
    
    def apply_theme(self):
        self.editor.apply_theme()
        self._update_style()
    
    def to_dict(self) -> dict:
        return {
            'language': self.get_language(), 
            'code': self.get_code(),
            'height': self.editor_container.height(),
            'connection_name': self.get_connection_name()
        }
    
    @classmethod
    def from_dict(cls, data: dict, theme_manager=None, default_connection=None) -> 'CodeBlock':
        block = cls(theme_manager=theme_manager, default_connection=default_connection)
        block.set_language(data.get('language', 'python'))
        block.set_code(data.get('code', ''))
        # Restaurar conexão se salva
        if 'connection_name' in data:
            block.set_connection_name(data['connection_name'])
        # Restaurar altura se salva
        if 'height' in data and data['height']:
            block._set_editor_height(data['height'])
        return block
    
    # === Drag ===
    
    def _start_drag(self):
        self.drag_handle.setCursor(Qt.CursorShape.ClosedHandCursor)
        
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(f"block:{id(self)}")
        drag.setMimeData(mime_data)
        
        pixmap = QPixmap(self.size())
        pixmap.fill(QColor(60, 60, 60, 200))
        painter = QPainter(pixmap)
        painter.setPen(QColor(200, 200, 200))
        painter.drawText(10, 20, f"[{self.get_language().upper()}] Bloco")
        painter.end()
        
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, 10))
        
        self.move_requested.emit(self, -1)
        drag.exec(Qt.DropAction.MoveAction)
        
        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
    
    # === Resize (só o editor_container) ===
    
    def _resize_start(self, event):
        self._is_resizing = True
        self._resize_start_y = event.globalPosition().y()
        self._resize_start_height = self.editor_container.height()
    
    def _resize_move(self, event):
        if not self._is_resizing:
            return
        delta = event.globalPosition().y() - self._resize_start_y
        new_height = max(80, self._resize_start_height + delta)
        self._set_editor_height(int(new_height))
    
    def _resize_end(self, event):
        if self._is_resizing:
            self._is_resizing = False
    
    def _set_editor_height(self, height: int):
        """Define altura fixa do editor container"""
        self.editor_container.setFixedHeight(height)
        # O editor interno expande automaticamente via layout
