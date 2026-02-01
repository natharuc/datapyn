"""
SessionWidget - Widget completo que representa uma sessão

Contém todos os componentes de uma sessão:
- Editor de código (UnifiedEditor)
- BottomTabs (Resultados, Output, Variáveis)
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont
import pandas as pd
import sys
import traceback
from io import StringIO
from typing import Optional, Dict, Any

from src.core.session import Session
from src.core.theme_manager import ThemeManager
from src.editors import BlockEditor
from src.ui.components.bottom_tabs import BottomTabs


class SessionSqlWorker(QObject):
    """Worker para executar SQL em background para uma sessão"""
    finished = pyqtSignal(object, str)  # (result_df ou None, error_msg)
    
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


class SessionPythonWorker(QObject):
    """Worker para executar Python em background para uma sessão"""
    finished = pyqtSignal(object, str, str, dict)  # (result, output, error, updated_namespace)
    
    def __init__(self, code, namespace, is_expression):
        super().__init__()
        self.code = code
        self.namespace = namespace.copy()  # Cópia para thread safety
        self.is_expression = is_expression
    
    def run(self):
        try:
            old_stdout = sys.stdout
            sys.stdout = captured_output = StringIO()
            
            result_value = None
            
            if self.is_expression:
                result_value = eval(self.code, self.namespace)
            else:
                exec(self.code, self.namespace)
            
            sys.stdout = old_stdout
            output = captured_output.getvalue()
            
            self.finished.emit(result_value, output, '', self.namespace)
        except Exception as e:
            sys.stdout = old_stdout
            self.finished.emit(None, '', traceback.format_exc(), {})


class SessionWidget(QWidget):
    """
    Widget completo que representa uma sessão.
    
    Contém:
    - Editor de código
    - Tabela de resultados
    - Output/Logs
    - Variáveis em memória
    """
    
    # Sinais para a MainWindow
    execute_sql = pyqtSignal(str)  # query
    execute_python = pyqtSignal(str)  # code
    execute_cross_syntax = pyqtSignal(str)  # code
    status_changed = pyqtSignal(str)  # status message
    
    def __init__(self, session: Session, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        
        self.session = session
        self.theme_manager = theme_manager or ThemeManager()
        
        # Workers ativos
        self._sql_thread: Optional[QThread] = None
        self._python_thread: Optional[QThread] = None
        
        # Fila de execução para múltiplos blocos
        self._execution_queue: list = []  # Lista de (language, code, block)
        self._is_executing: bool = False
        self._cancel_requested: bool = False  # Flag de cancelamento
        
        self._setup_ui()
        self._connect_signals()
        
        # Restaurar blocos se existirem
        if session.blocks:
            self.editor.from_list(session.blocks)
        elif session.code:
            # Compatibilidade: código antigo sem blocos
            self.editor.setText(session.code)
    
    def _setup_ui(self):
        """Configura a UI do widget"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Splitter principal (vertical) - Editor em cima, Resultados embaixo
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        
        # === PARTE SUPERIOR: Editor de Blocos ===
        editor_container = QWidget()
        editor_layout = QVBoxLayout(editor_container)
        editor_layout.setContentsMargins(5, 5, 5, 5)
        
        # Editor de blocos (substitui o UnifiedEditor)
        self.editor = BlockEditor(theme_manager=self.theme_manager)
        editor_layout.addWidget(self.editor)
        
        self.splitter.addWidget(editor_container)
        
        # === PARTE INFERIOR: BottomTabs (Resultados, Output, Variáveis) ===
        self.bottom_tabs = BottomTabs(theme_manager=self.theme_manager)
        self.splitter.addWidget(self.bottom_tabs)
        
        # Tamanho inicial (60% editor, 40% resultados)
        self.splitter.setSizes([360, 240])
        
        layout.addWidget(self.splitter)
    
    # === Propriedades de compatibilidade ===
    
    @property
    def results_viewer(self):
        """Compatibilidade: retorna o results_viewer do BottomTabs"""
        return self.bottom_tabs.results_viewer
    
    @property
    def output_text(self):
        """Compatibilidade: retorna o output_text do BottomTabs"""
        return self.bottom_tabs.output_text
    
    @property
    def variables_viewer(self):
        """Compatibilidade: retorna o variables_panel do BottomTabs"""
        return self.bottom_tabs.variables_panel
    
    def _connect_signals(self):
        """Conecta sinais do editor"""
        # BlockEditor emite sinais com a linguagem correta
        self.editor.execute_sql.connect(self._on_execute_sql)
        self.editor.execute_python.connect(self._on_execute_python)
        self.editor.execute_cross_syntax.connect(self._on_execute_cross_syntax)
        
        # Fila de execução (múltiplos blocos)
        self.editor.execute_queue.connect(self._on_execute_queue)
        
        # Cancelamento
        self.editor.cancel_execution.connect(self._on_cancel_execution)
        
        # Conectar sinais da sessão
        self.session.variables_changed.connect(self._update_variables_view)
    
    # === EXECUÇÃO SQL ===
    
    def _on_execute_sql(self, query: str):
        """Executa SQL em background"""
        if not self.session.is_connected:
            self.append_output("[ERRO] Nenhuma conexão ativa nesta sessão", error=True)
            self.status_changed.emit("Erro: Sem conexão")
            # Processar próximo da fila mesmo com erro
            self._process_next_in_queue()
            return
        
        # Se já está executando, adiciona na fila
        if self._is_executing or (self._sql_thread and self._sql_thread.isRunning()):
            self._execution_queue.append(('sql', query))
            return
        
        self._is_executing = True
        self.session.start_execution('sql')
        self.status_changed.emit("Executando SQL...")
        self.append_output(f"▶ Executando SQL...")
        
        # Criar worker e thread
        self._sql_thread = QThread()
        self._sql_worker = SessionSqlWorker(self.session.connector, query)
        self._sql_worker.moveToThread(self._sql_thread)
        
        # Registrar thread na sessão
        self.session.register_thread(self._sql_thread)
        
        # Conectar sinais
        self._sql_thread.started.connect(self._sql_worker.run)
        self._sql_worker.finished.connect(self._on_sql_finished)
        
        # Iniciar
        self._sql_thread.start()
    
    def _on_sql_finished(self, df: Optional[pd.DataFrame], error: str):
        """Callback quando SQL termina"""
        # Parar thread
        if self._sql_thread:
            self._sql_thread.quit()
            self._sql_thread.wait()
            self.session.unregister_thread(self._sql_thread)
            self._sql_thread = None
        
        # Marcar bloco atual como finalizado
        current_block = self.editor.get_current_executing_block()
        self.editor.mark_execution_finished(current_block)
        
        if error:
            self.append_output(f"[ERRO SQL] {error}", error=True)
            self.session.finish_execution(False, f"Erro: {error[:50]}...")
            self.bottom_tabs.show_output()
        else:
            rows = len(df) if df is not None else 0
            self.append_output(f"Query executada: {rows:,} linhas")
            self.bottom_tabs.set_results(df, "df")
            self.session.finish_execution(True, f"SQL: {rows:,} linhas")
            
            # Salvar no namespace da sessão
            self.session.set_variable('df', df)
            self.session.set_variable('_last_result', df)
        
        # Processar próximo da fila se houver
        self._is_executing = False
        self._process_next_in_queue()
    
    # === EXECUÇÃO PYTHON ===
    
    def _on_execute_python(self, code: str):
        """Executa Python em background"""
        # Se já está executando, adiciona na fila
        if self._is_executing or (self._python_thread and self._python_thread.isRunning()):
            self._execution_queue.append(('python', code))
            return
        
        self._is_executing = True
        self.session.start_execution('python')
        self.status_changed.emit("Executando Python...")
        self.append_output(f"▶ Executando Python...")
        
        # Preparar namespace com df se existir
        namespace = self.session.namespace.copy()
        namespace['pd'] = pd
        
        # Verificar se é expressão
        is_expression = False
        try:
            compile(code, '<string>', 'eval')
            is_expression = True
        except SyntaxError:
            pass
        
        # Criar worker e thread
        self._python_thread = QThread()
        self._python_worker = SessionPythonWorker(code, namespace, is_expression)
        self._python_worker.moveToThread(self._python_thread)
        
        self.session.register_thread(self._python_thread)
        
        self._python_thread.started.connect(self._python_worker.run)
        self._python_worker.finished.connect(self._on_python_finished)
        
        self._python_thread.start()
    
    def _on_python_finished(self, result, output: str, error: str, updated_namespace: dict):
        """Callback quando Python termina"""
        if self._python_thread:
            self._python_thread.quit()
            self._python_thread.wait()
            self.session.unregister_thread(self._python_thread)
            self._python_thread = None
        
        # Marcar bloco atual como finalizado
        current_block = self.editor.get_current_executing_block()
        self.editor.mark_execution_finished(current_block)
        
        if error:
            self.append_output(f"[ERRO PYTHON]\n{error}", error=True)
            self.session.finish_execution(False, "Erro Python")
            self.bottom_tabs.show_output()
        else:
            if output:
                self.append_output(output)
            
            if result is not None:
                if isinstance(result, pd.DataFrame):
                    self.bottom_tabs.set_results(result, "result")
                    self.append_output(f"DataFrame: {len(result):,} linhas")
                else:
                    self.append_output(f"→ {repr(result)}")
            
            # Atualizar namespace da sessão
            if updated_namespace:
                self.session.update_namespace(updated_namespace)
            
            self.session.finish_execution(True, "Python executado")
        
        # Processar próximo da fila se houver
        self._is_executing = False
        self._process_next_in_queue()
    
    # === EXECUÇÃO CROSS-SYNTAX ===
    
    def _on_execute_cross_syntax(self, code: str):
        """Emite sinal para MainWindow processar cross-syntax"""
        self.execute_cross_syntax.emit(code)
    
    # === FILA DE EXECUÇÃO ===
    
    def _on_execute_queue(self, queue: list):
        """
        Recebe uma fila de blocos para executar sequencialmente.
        
        Args:
            queue: Lista de tuplas (language, code, block)
        """
        # Reset flag de cancelamento
        self._cancel_requested = False
        
        # Adiciona todos à fila
        self._execution_queue.extend(queue)
        
        # Inicia processamento se não estiver executando
        if not self._is_executing:
            self._process_next_in_queue()
    
    def _on_cancel_execution(self):
        """Cancela a execução atual e limpa a fila"""
        self._cancel_requested = True
        self._execution_queue.clear()
        self._is_executing = False
        
        # Tentar cancelar threads ativas
        if self._sql_thread and self._sql_thread.isRunning():
            self._sql_thread.quit()
            self._sql_thread.wait(1000)
        
        if self._python_thread and self._python_thread.isRunning():
            self._python_thread.quit()
            self._python_thread.wait(1000)
        
        self.append_output("⊘ Execução cancelada pelo usuário", error=True)
    
    def _process_next_in_queue(self):
        """Processa o próximo item da fila de execução"""
        # Verifica se foi cancelado
        if self._cancel_requested:
            self._cancel_requested = False
            return
        
        if not self._execution_queue:
            # Fila vazia, marca todos os blocos como finalizados
            self.editor.mark_execution_finished()
            return
        
        # Pega próximo da fila
        item = self._execution_queue.pop(0)
        
        # Suporta formato antigo (language, code) e novo (language, code, block)
        if len(item) == 3:
            language, code, block = item
            # Marca o bloco como executando
            self.editor.mark_block_started(block)
        else:
            language, code = item
            block = None
        
        # Executa de acordo com a linguagem
        if language == 'sql':
            self._on_execute_sql(code)
        elif language == 'python':
            self._on_execute_python(code)
        elif language == 'cross':
            self._on_execute_cross_syntax(code)
            # Cross-syntax é síncrono (processado pela MainWindow)
            # Então continuamos para o próximo
            self._process_next_in_queue()
    
    # === OUTPUT/LOG ===
    
    def append_output(self, text: str, error: bool = False):
        """Adiciona texto ao output"""
        if error:
            self.bottom_tabs.log_error(text)
        else:
            self.bottom_tabs.log(text)
    
    def clear_output(self):
        """Limpa o output"""
        self.bottom_tabs.clear_output()
    
    # === VARIÁVEIS ===
    
    def _update_variables_view(self, namespace: dict):
        """Atualiza visualização de variáveis"""
        # Filtrar variáveis internas
        visible_vars = {
            k: v for k, v in namespace.items()
            if not k.startswith('_') and k not in ('pd', 'np', 'plt')
        }
        
        # Usar o método do BottomTabs
        self.bottom_tabs.set_variables(visible_vars)
    
    # === TEMA ===
    
    def apply_theme(self):
        """Aplica o tema atual"""
        self.editor.apply_theme()
        self.bottom_tabs.set_theme_manager(self.theme_manager)
    
    # === ESTADO ===
    
    def get_code(self) -> str:
        """Retorna o código atual do editor"""
        return self.editor.text()
    
    def set_code(self, code: str):
        """Define o código do editor"""
        self.editor.setText(code)
    
    def sync_to_session(self):
        """Sincroniza estado do widget para a sessão"""
        self.session.code = self.get_code()  # Compatibilidade
        self.session.blocks = self.editor.to_list()  # Novo: blocos
    
    def sync_from_session(self):
        """Sincroniza estado da sessão para o widget"""
        if self.session.blocks:
            self.editor.from_list(self.session.blocks)
        elif self.session.code:
            self.set_code(self.session.code)
    
    # === CLEANUP ===
    
    def cleanup(self):
        """Limpa recursos"""
        if self._sql_thread and self._sql_thread.isRunning():
            self._sql_thread.quit()
            self._sql_thread.wait()
        
        if self._python_thread and self._python_thread.isRunning():
            self._python_thread.quit()
            self._python_thread.wait()
