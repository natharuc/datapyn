"""
BlockEditor - Container que gerencia múltiplos blocos de código

Similar a um notebook Jupyter, mas com foco em execução de SQL/Python
"""

import os
from typing import List, Optional

import qtawesome as qta
from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from src.core.theme_manager import ThemeManager
from src.editors.code_block import CodeBlock


class BlockEditor(QWidget):
    """
    Editor baseado em blocos.

    Cada bloco tem sua própria linguagem (Python, SQL, Cross-Syntax).

    Atalhos:
    - F5: Executa bloco focado ou todos se nada selecionado
    - Shift+Enter: Executa bloco focado e avança para próximo
    - Ctrl+Enter: Executa todos os blocos

    Signals:
        execute_block: (language, code, block) - Executa um bloco
        execute_all: () - Executa todos os blocos
    """

    # Sinais de execução
    execute_sql = pyqtSignal(str)  # query
    execute_python = pyqtSignal(str)  # code
    execute_cross_syntax = pyqtSignal(str)  # code

    # Sinal para executar múltiplos blocos em sequência
    # Emite lista de tuplas: [(language, code, block), ...]
    execute_queue = pyqtSignal(list)

    # Sinal de cancelamento
    cancel_execution = pyqtSignal()

    # Sinal quando conteúdo muda
    content_changed = pyqtSignal()

    def __init__(self, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self._blocks: List[CodeBlock] = []
        self._focused_block: Optional[CodeBlock] = None
        self._executing_index: int = -1  # Índice do bloco sendo executado em batch
        self._execution_queue_blocks: List[CodeBlock] = []  # Blocos na fila de execução
        self._current_executing_block: Optional[CodeBlock] = None  # Bloco atualmente executando
        self._dragging_block: Optional[CodeBlock] = None  # Bloco sendo arrastado

        self._setup_ui()

        # Habilitar drop
        self.setAcceptDrops(True)

        # Criar primeiro bloco vazio
        self.add_block()

    def _setup_ui(self):
        """Configura a UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scroll area para os blocos
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        # Container dos blocos
        self.blocks_container = QWidget()
        self.blocks_layout = QVBoxLayout(self.blocks_container)
        self.blocks_layout.setContentsMargins(8, 8, 8, 8)
        self.blocks_layout.setSpacing(12)
        self.blocks_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll_area.setWidget(self.blocks_container)
        main_layout.addWidget(self.scroll_area)

        # Botão para adicionar novo bloco (linha horizontal com +)
        self.add_button_container = QWidget()
        add_layout = QHBoxLayout(self.add_button_container)
        add_layout.setContentsMargins(8, 4, 8, 8)

        # Linha horizontal (como <hr/>)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("QFrame { color: #555; }")

        # Botão pequeno com ícone +
        self.add_btn = QPushButton()
        self.add_btn.setIcon(qta.icon("mdi.plus", color="#888"))
        self.add_btn.setToolTip("Adicionar bloco")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setFixedSize(24, 24)  # Botão pequeno 24x24
        self.add_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #555;
                border-radius: 12px;
            }
            QPushButton:hover {
                background: #333;
                border-color: #888;
            }
        """)
        self.add_btn.clicked.connect(lambda: self.add_block())

        # Layout: linha horizontal + botão +
        add_layout.addWidget(line, 1)  # Linha ocupa todo espaço disponível
        add_layout.addWidget(self.add_btn)  # Botão + no final

        # Adiciona o botão ao container dos blocos
        self.blocks_layout.addWidget(self.add_button_container)

    def keyPressEvent(self, event: QKeyEvent):
        """Intercepta teclas para atalhos de execução"""
        # F5 - Executar (seleção do bloco focado, ou bloco inteiro, ou todos)
        if event.key() == Qt.Key.Key_F5 and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._execute_smart()
            return

        # Shift+Enter - Executar bloco focado e avançar
        if event.key() == Qt.Key.Key_Return and event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self._execute_focused_and_advance()
            return

        # Ctrl+Enter - Executar todos os blocos
        if event.key() == Qt.Key.Key_Return and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.execute_all_blocks()
            return

        super().keyPressEvent(event)

    def _execute_smart(self):
        """
        Executa de forma inteligente:
        - Se há seleção no bloco focado: executa a seleção com linguagem do bloco
        - Se não há seleção: executa todos os blocos
        """
        if self._focused_block and self._focused_block.has_selection():
            # Executa seleção
            code = self._focused_block.get_selected_text()
            lang = self._focused_block.get_language()
            self._execute_code(code, lang, self._focused_block)
        else:
            # Executa todos os blocos
            self.execute_all_blocks()

    def _execute_focused_and_advance(self):
        """Executa o bloco focado e move foco para o próximo"""
        if self._focused_block:
            self._execute_block(self._focused_block)

            # Avança para próximo bloco
            index = self._blocks.index(self._focused_block)
            if index < len(self._blocks) - 1:
                self._blocks[index + 1].focus_editor()
            else:
                # Se é o último, cria novo bloco
                new_block = self.add_block()
                new_block.focus_editor()

    def _execute_block(self, block: CodeBlock):
        """Executa um bloco específico"""
        code = block.get_code().strip()
        if not code:
            return

        lang = block.get_language()
        self._execute_code(code, lang, block)

    def _execute_code(self, code: str, language: str, block: CodeBlock):
        """Emite o sinal de execução apropriado"""
        block.set_running(True)

        if language == "sql":
            self.execute_sql.emit(code)
        elif language == "python":
            self.execute_python.emit(code)
        elif language == "cross":
            self.execute_cross_syntax.emit(code)

        # Nota: o chamador precisa chamar mark_execution_finished depois

    def execute_all_blocks(self):
        """Executa todos os blocos em sequência"""
        if not self._blocks:
            return

        # Coleta todos os blocos com código para executar
        queue = []
        self._execution_queue_blocks = []

        for block in self._blocks:
            code = block.get_code().strip()
            if code:
                queue.append((block.get_language(), code, block))
                self._execution_queue_blocks.append(block)
                block.set_waiting(True)  # Marca como aguardando

        if queue:
            # Marca o primeiro como executando
            if self._execution_queue_blocks:
                first_block = self._execution_queue_blocks[0]
                first_block.set_running(True)
                self._current_executing_block = first_block

            # Emite a fila para o SessionWidget processar sequencialmente
            self.execute_queue.emit(queue)

    def mark_block_started(self, block: CodeBlock):
        """Marca que um bloco específico começou a executar"""
        self._current_executing_block = block
        block.set_running(True)

    def mark_execution_finished(self, block: CodeBlock = None, has_error: bool = False):
        """Marca que a execução de um bloco terminou"""
        if block:
            if has_error:
                block.set_error()
            else:
                block.set_running(False)
            # Remove da fila se ainda estiver lá
            if block in self._execution_queue_blocks:
                self._execution_queue_blocks.remove(block)
            # Marca próximo como executando
            if self._execution_queue_blocks:
                next_block = self._execution_queue_blocks[0]
                next_block.set_running(True)
                self._current_executing_block = next_block
            else:
                self._current_executing_block = None
        else:
            # Se não especificou, marca todos como não executando
            for b in self._blocks:
                b.set_running(False)
                b.set_waiting(False)
            self._execution_queue_blocks = []
            self._current_executing_block = None

    def cancel_all_executions(self):
        """Cancela todas as execuções pendentes"""
        # Marca bloco atual como cancelado
        if self._current_executing_block:
            self._current_executing_block.set_cancelled()

        # Marca blocos aguardando como cancelados também
        for block in self._execution_queue_blocks:
            if block != self._current_executing_block:
                block.set_cancelled()

        self._execution_queue_blocks = []
        self._current_executing_block = None

        # Emite sinal de cancelamento
        self.cancel_execution.emit()

    def get_current_executing_block(self) -> Optional[CodeBlock]:
        """Retorna o bloco atualmente em execução"""
        return self._current_executing_block

    # === Gerenciamento de Blocos ===

    def add_block(self, language: str = None, code: str = "", after_block: CodeBlock = None) -> CodeBlock:
        """
        Adiciona um novo bloco.

        Args:
            language: 'python', 'sql', ou 'cross'. Se None, usa 'sql' para primeiro bloco e 'python' para segundo
            code: Código inicial
            after_block: Se especificado, insere após este bloco

        Returns:
            O novo bloco criado
        """
        # Se linguagem não especificada, usa SQL para primeiro bloco e Python para todos os outros
        if language is None:
            if len(self._blocks) == 0:
                language = "sql"  # Primeiro bloco
            else:
                language = "python"  # Segundo bloco em diante

        block = CodeBlock(theme_manager=self.theme_manager, default_language=language)
        if code:
            block.set_code(code)

        # Conectar sinais
        # execute_requested usa a mesma lógica do F5: seleção ou todos
        block.execute_requested.connect(lambda b: self._on_block_execute_requested(b))
        block.remove_requested.connect(self.remove_block)
        block.cancel_requested.connect(lambda b: self.cancel_all_executions())
        block.focus_changed.connect(self._on_block_focus_changed)
        block.move_requested.connect(self._on_block_move_requested)
        block.editor.textChanged.connect(self.content_changed.emit)

        # Determinar posição
        if after_block and after_block in self._blocks:
            index = self._blocks.index(after_block) + 1
        else:
            index = len(self._blocks)

        # Inserir na lista e no layout
        self._blocks.insert(index, block)

        # Remover o botão de adicionar temporariamente
        self.blocks_layout.removeWidget(self.add_button_container)

        # Inserir bloco na posição correta
        self.blocks_layout.insertWidget(index, block)

        # Re-adicionar botão no final
        self.blocks_layout.addWidget(self.add_button_container)

        # Focar no novo bloco após renderização
        QTimer.singleShot(50, block.focus_editor)

        self.content_changed.emit()
        return block

    def remove_block(self, block: CodeBlock):
        """Remove um bloco"""
        if block not in self._blocks:
            return

        # Não remove o último bloco
        if len(self._blocks) <= 1:
            # Em vez de remover, apenas limpa
            block.set_code("")
            return

        index = self._blocks.index(block)
        self._blocks.remove(block)

        # Remover do layout
        self.blocks_layout.removeWidget(block)
        block.deleteLater()

        # Atualizar foco
        if self._focused_block == block:
            if self._blocks:
                new_index = min(index, len(self._blocks) - 1)
                self._blocks[new_index].focus_editor()
            self._focused_block = None

        self.content_changed.emit()

    def clear_blocks(self):
        """Remove todos os blocos e adiciona um vazio"""
        for block in self._blocks[:]:
            self.blocks_layout.removeWidget(block)
            block.deleteLater()
        self._blocks.clear()
        self._focused_block = None
        self.add_block()

    def _on_block_focus_changed(self, block: CodeBlock, has_focus: bool):
        """Quando um bloco ganha/perde foco"""
        if has_focus:
            self._focused_block = block
        elif self._focused_block == block:
            self._focused_block = None

    # === API Pública ===

    def get_focused_block(self) -> Optional[CodeBlock]:
        """Retorna o bloco focado atual"""
        return self._focused_block

    def focus_first_block(self):
        """Foca no primeiro bloco de código"""
        if self._blocks:
            self._blocks[0].focus_editor()

    def get_blocks(self) -> List[CodeBlock]:
        """Retorna lista de todos os blocos"""
        return self._blocks.copy()

    def get_block_count(self) -> int:
        """Retorna número de blocos"""
        return len(self._blocks)

    def get_all_code(self) -> str:
        """Retorna todo o código concatenado (com separadores)"""
        parts = []
        for i, block in enumerate(self._blocks):
            code = block.get_code().strip()
            if code:
                lang = block.get_language()
                parts.append(f"# === Bloco {i + 1} ({lang.upper()}) ===")
                parts.append(code)
                parts.append("")
        return "\n".join(parts)

    def text(self) -> str:
        """Alias para get_all_code - compatibilidade"""
        return self.get_all_code()

    def setText(self, text: str):
        """
        Define o texto (compatibilidade com editor antigo).
        Tenta detectar blocos no texto ou coloca tudo em um bloco.
        """
        self.clear_blocks()

        if not text.strip():
            return

        # Tenta detectar marcadores de bloco
        if "# === Bloco" in text:
            self._parse_blocks_from_text(text)
        else:
            # Coloca tudo em um único bloco
            # Detecta linguagem pelo conteúdo
            lang = self._detect_language(text)
            self._blocks[0].set_language(lang)
            self._blocks[0].set_code(text)

    def _parse_blocks_from_text(self, text: str):
        """Parseia texto com marcadores de bloco"""
        import re

        # Pattern: # === Bloco N (LANG) ===
        pattern = r"# === Bloco \d+ \((\w+)\) ==="
        parts = re.split(pattern, text)

        # parts[0] é texto antes do primeiro marcador (geralmente vazio)
        # Depois alterna: lang, code, lang, code, ...

        if len(parts) > 1:
            self._blocks[0].set_code("")  # Limpa primeiro bloco

            i = 1
            first = True
            while i < len(parts):
                lang = parts[i].lower()
                code = parts[i + 1].strip() if i + 1 < len(parts) else ""

                if first:
                    self._blocks[0].set_language(lang)
                    self._blocks[0].set_code(code)
                    first = False
                else:
                    self.add_block(lang, code)

                i += 2

    def _detect_language(self, text: str) -> str:
        """Detecta linguagem provável do código"""
        text_lower = text.lower()

        # Cross-syntax tem {{ }}
        if "{{" in text and "}}" in text:
            return "cross"

        # SQL keywords
        sql_keywords = ["select", "insert", "update", "delete", "create", "drop", "alter", "from", "where", "join"]
        sql_count = sum(1 for kw in sql_keywords if kw in text_lower)

        # Python keywords
        py_keywords = ["def ", "class ", "import ", "from ", "if ", "for ", "while ", "print(", "return "]
        py_count = sum(1 for kw in py_keywords if kw in text_lower)

        if sql_count > py_count:
            return "sql"
        return "python"

    def apply_theme(self):
        """Aplica tema a todos os blocos"""
        for block in self._blocks:
            block.apply_theme()

    def to_list(self) -> List[dict]:
        """Serializa todos os blocos para lista de dicts"""
        return [block.to_dict() for block in self._blocks]

    def from_list(self, blocks_data: List[dict]):
        """Carrega blocos a partir de lista de dicts"""
        self.clear_blocks()

        if not blocks_data:
            return

        for i, data in enumerate(blocks_data):
            if i == 0:
                # Primeiro bloco já existe
                self._blocks[0].set_language(data.get("language", "python"))
                self._blocks[0].set_code(data.get("code", ""))
            else:
                self.add_block(language=data.get("language", "python"), code=data.get("code", ""))

    # === Compatibilidade com UnifiedEditor ===

    def clear(self):
        """Compatibilidade: limpa todos os blocos"""
        self.clear_blocks()

    def get_selected_or_all_text(self) -> str:
        """Compatibilidade: retorna seleção ou todo código"""
        if self._focused_block and self._focused_block.has_selection():
            return self._focused_block.get_selected_text()
        return self.get_all_code()

    def get_focused_block_code(self) -> str:
        """Retorna o código do bloco atualmente focado"""
        if self._focused_block:
            return self._focused_block.get_code()
        # Se não há bloco focado, retorna o primeiro
        if self._blocks:
            return self._blocks[0].get_code()
        return ""

    def execute_focused_block(self):
        """Executa apenas o bloco focado com sua linguagem"""
        block = self._focused_block
        if not block and self._blocks:
            block = self._blocks[0]

        if block:
            if block.has_selection():
                code = block.get_selected_text()
            else:
                code = block.get_code()
            lang = block.get_language()
            self._execute_code(code, lang, block)

    def hasSelectedText(self) -> bool:
        """Compatibilidade: verifica se há seleção"""
        return self._focused_block and self._focused_block.has_selection()

    def selectedText(self) -> str:
        """Compatibilidade: retorna texto selecionado"""
        if self._focused_block:
            return self._focused_block.get_selected_text()
        return ""

    # === Execução unificada (F5 e botão fazem a mesma coisa) ===

    def _on_block_execute_requested(self, block: CodeBlock):
        """
        Handler quando um bloco pede para executar (F5 ou botão ▶).

        Lógica:
        - Se há seleção no bloco: executa só a seleção
        - Se não há seleção: executa todos os blocos
        """
        if block.has_selection():
            # Executa apenas a seleção deste bloco
            code = block.get_selected_text()
            lang = block.get_language()
            self._execute_code(code, lang, block)
        else:
            # Executa todos os blocos
            self.execute_all_blocks()

    # === Drag and Drop ===

    def _on_block_move_requested(self, block: CodeBlock, new_index: int):
        """Quando um bloco inicia drag"""
        if new_index == -1:
            # Drag iniciou
            self._dragging_block = block

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Aceita drag de blocos e arquivos"""
        mime_data = event.mimeData()

        # Aceitar drag de blocos
        if mime_data.hasText():
            text = mime_data.text()
            if text.startswith("block:"):
                event.acceptProposedAction()
                return

        # Aceitar drag de arquivos CSV, JSON, XLSX, SQL, PY, DPW
        if mime_data.hasUrls():
            urls = mime_data.urls()
            for url in urls:
                file_path = url.toLocalFile()
                if file_path.lower().endswith((".csv", ".json", ".xlsx", ".xls", ".sql", ".py")):
                    event.acceptProposedAction()
                    return

    def dragMoveEvent(self, event):
        """Durante o drag, mostra onde o bloco será inserido"""
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """Quando um bloco ou arquivo é solto"""
        mime_data = event.mimeData()

        # Processar drop de arquivos
        if mime_data.hasUrls():
            urls = mime_data.urls()
            for url in urls:
                file_path = url.toLocalFile()
                lower_path = file_path.lower()
                if lower_path.endswith((".csv", ".json", ".xlsx", ".xls")):
                    import_code = self._generate_import_code(file_path)
                    if import_code:
                        self.add_block(language="python", code=import_code)
                        self.content_changed.emit()
                elif lower_path.endswith(".sql"):
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        self.add_block(language="sql", code=content)
                        self.content_changed.emit()
                    except Exception:
                        pass
                elif lower_path.endswith(".py"):
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        self.add_block(language="python", code=content)
                        self.content_changed.emit()
                    except Exception:
                        pass
            event.acceptProposedAction()
            return

        # Processar drop de blocos (código existente)
        if not self._dragging_block:
            return

        # Encontrar posição de drop
        drop_pos = event.position().toPoint()
        drop_index = self._find_drop_index(drop_pos)

        # Mover bloco
        self._move_block(self._dragging_block, drop_index)

        self._dragging_block = None
        event.acceptProposedAction()

    def _find_drop_index(self, pos) -> int:
        """Encontra o índice onde o bloco deve ser inserido"""
        # Mapear posição para o scroll area
        scroll_pos = self.scroll_area.mapFromParent(pos)
        container_pos = self.blocks_container.mapFromParent(scroll_pos)

        for i, block in enumerate(self._blocks):
            block_geometry = block.geometry()
            block_center_y = block_geometry.y() + block_geometry.height() // 2

            if container_pos.y() < block_center_y:
                return i

        return len(self._blocks)

    def _move_block(self, block: CodeBlock, new_index: int):
        """Move um bloco para nova posição"""
        if block not in self._blocks:
            return

        old_index = self._blocks.index(block)
        if old_index == new_index:
            return

        # Ajustar índice se movendo para frente
        if new_index > old_index:
            new_index -= 1

        # Remover da posição atual
        self._blocks.remove(block)
        self.blocks_layout.removeWidget(block)

        # Inserir na nova posição
        self._blocks.insert(new_index, block)
        self.blocks_layout.insertWidget(new_index, block)

        self.content_changed.emit()

    def _generate_import_code(self, file_path: str) -> Optional[str]:
        """
        Gera código de importação pandas baseado na extensão do arquivo.

        Args:
            file_path: Caminho completo do arquivo

        Returns:
            Código Python para importar o arquivo ou None se extensão não suportada
        """
        if not file_path:
            return None

        # Normalizar caminho (usar raw string para Windows)
        # Usar barras normais pois Python aceita em ambos os sistemas
        normalized_path = file_path.replace("\\", "/")

        # Extrair extensão
        _, ext = os.path.splitext(file_path.lower())

        # Gerar codigo baseado na extensao
        # pandas ja esta disponivel como 'pd' no namespace de execucao
        if ext == ".csv":
            return f"df = pd.read_csv('{normalized_path}')"
        elif ext == ".json":
            return f"df = pd.read_json('{normalized_path}')"
        elif ext in (".xlsx", ".xls"):
            return f"df = pd.read_excel('{normalized_path}')"

        return None
