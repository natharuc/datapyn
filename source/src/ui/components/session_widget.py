"""
SessionWidget - Widget completo que representa uma sessão

Contém todos os componentes de uma sessão:
- Editor de código (UnifiedEditor)
- BottomTabs (Resultados, Output, Variáveis)
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QLabel
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont
import pandas as pd
import sys
import traceback
from io import StringIO
from typing import Optional, Dict, Any
from datetime import datetime

from src.core.session import Session
from src.core.theme_manager import ThemeManager
from src.editors import BlockEditor
# from src.ui.components.bottom_tabs import BottomTabs  # Removido - usando painéis globais


class SessionConnectionWorker(QObject):
    """Worker para conectar ao banco em background"""

    finished = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, session, connection_name, password):
        super().__init__()
        self.session = session
        self.connection_name = connection_name
        self.password = password

    def run(self):
        try:
            success = self.session.connect(self.connection_name, self.password)
            if success:
                self.finished.emit(True, f"✓ Conectado a {self.connection_name}")
            else:
                self.finished.emit(False, f"✗ Falha ao conectar a {self.connection_name}")
        except Exception as e:
            self.finished.emit(False, f"[ERRO] {str(e)}")


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
            self.finished.emit(df, "")
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
        """REMOVIDO - usar PythonWorker centralizado do main_window.py"""
        raise NotImplementedError("Use PythonWorker do main_window.py - execução centralizada!")


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
    connection_changed = pyqtSignal(str, str)  # (connection_name, database)

    def __init__(self, session: Session, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)

        self.session = session
        self.theme_manager = theme_manager or ThemeManager()

        # Workers ativos
        self._sql_thread: Optional[QThread] = None
        self._python_thread: Optional[QThread] = None
        self._connection_thread: Optional[QThread] = None
        self._connection_worker: Optional[SessionConnectionWorker] = None

        # Cor da conexão (será definida ao conectar)
        self._connection_color: str = "#007ACC"  # Default: azul primário

        # Fila de execução para múltiplos blocos
        self._execution_queue: list = []  # Lista de (language, code, block, block_name, connection_name)
        self._is_executing: bool = False
        self._cancel_requested: bool = False  # Flag de cancelamento
        self._current_block_name: str = None  # Nome do bloco atualmente executando (para namespace isolado)

        # Overlay de loading
        self._loading_overlay: Optional[QLabel] = None

        self._setup_ui()
        self._connect_signals()

        # Restaurar blocos se existirem
        if session.blocks:
            self.editor.from_list(session.blocks)
        elif session.code:
            # Compatibilidade: código antigo sem blocos
            self.editor.setText(session.code)

        # Conexoes sao selecionadas por bloco via panel clicavel (nao precisa popular lista)

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

        # Nota: BottomTabs removido - usando painéis globais da MainWindow
        # Layout agora é só o editor (painéis Results/Output/Variables são dockable)

        layout.addWidget(self.editor)  # Layout simplificado: apenas editor

        # Overlay de loading (inicialmente oculto)
        self._loading_overlay = QLabel(self)
        self._loading_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Estilo será definido dinamicamente em _show_loading
        self._loading_overlay.hide()
        self._loading_overlay.raise_()

    # === Propriedades de compatibilidade ===

    @property
    def results_viewer(self):
        """Compatibilidade: delega para o painel global da MainWindow"""
        main_window = self._get_main_window()
        return main_window.global_results_viewer if main_window else None

    @property
    def output_text(self):
        """Compatibilidade: delega para o painel global da MainWindow"""
        main_window = self._get_main_window()
        return main_window.global_output_panel if main_window else None

    @property
    def variables_viewer(self):
        """Compatibilidade: delega para o painel global da MainWindow"""
        main_window = self._get_main_window()
        return main_window.global_variables_panel if main_window else None

    @property
    def bottom_tabs(self):
        """Compatibilidade: retorna objeto que delega para painéis dockable"""
        # Sempre retornar o mesmo objeto para manter consistência
        if not hasattr(self, "_bottom_tabs_cache"):
            main_window = self._get_main_window()
            self._bottom_tabs_cache = main_window.bottom_tabs if main_window else None
        return self._bottom_tabs_cache

    def _get_main_window(self):
        """Obtém referência à MainWindow"""
        parent = self.parent()
        while parent and not hasattr(parent, "global_results_viewer"):
            parent = parent.parent()
        return parent

    # === Métodos de delegação para painéis globais ===

    def _show_output(self):
        """Mostra o painel de output"""
        main_window = self._get_main_window()
        if main_window:
            main_window.show_panel("output")

    def _set_results(self, data, name="result"):
        """Define resultados no painel global"""
        main_window = self._get_main_window()
        if main_window and main_window.global_results_viewer:
            main_window.global_results_viewer.display_dataframe(data, name)
            main_window.show_panel("results")

    def _set_figures(self, figures: list, label: str = "Resultado"):
        """Exibe rich outputs (imagens, HTML, JSON) no painel global de resultados"""
        main_window = self._get_main_window()
        if main_window and main_window.global_results_viewer:
            main_window.global_results_viewer.display_rich_output(figures, label)
            main_window.show_panel("results")

    def _log_error(self, text):
        """Registra erro no output global"""
        main_window = self._get_main_window()
        if main_window and main_window.global_output_panel:
            main_window.global_output_panel.error(text)
            self._show_output()

    def _log(self, text):
        """Registra texto no output global"""
        main_window = self._get_main_window()
        if main_window and main_window.global_output_panel:
            main_window.global_output_panel.log(text)

    def _clear_output(self):
        """Limpa output global"""
        main_window = self._get_main_window()
        if main_window and main_window.global_output_panel:
            main_window.global_output_panel.clear()

    def _set_variables(self, variables_dict):
        """Define variáveis no painel global"""
        main_window = self._get_main_window()
        if main_window and main_window.global_variables_panel:
            main_window.global_variables_panel.set_variables(
                variables_dict
            )  # Corrigido de refresh_variables para set_variables

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

        # Seleção de conexão para bloco específico
        self.editor.select_connection_for_block.connect(self._on_block_select_connection)

        # Conectar sinais da sessão
        self.session.variables_changed.connect(self._update_variables_view)

    def _format_log(self, log_type: str, message: str = "") -> str:
        """Formata mensagem de log com timestamp e tipo"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        if message:
            return f"[{timestamp}][{log_type}] {message}"
        return f"[{timestamp}][{log_type}]"

    # === EXECUÇÃO SQL ===

    def _on_execute_sql(self, query: str, block_name: str = None, connection_name: str = None):
        """Executa SQL em background

        Args:
            query: SQL query
            block_name: Nome do bloco (para namespace isolado {nome}_df)
            connection_name: Nome da conexao customizada (None = usa padrao da sessao)
        """
        # Determinar qual conexao usar
        if connection_name:
            # Buscar conexao especifica - auto-conectar se necessario
            from src.database.connection_manager import ConnectionManager
            from src.database.database_connector import DatabaseConnector

            manager = ConnectionManager()
            connector = manager.get_connection(connection_name)
            if not connector or not connector.is_connected():
                # Tentar auto-conectar a partir da config salva
                config = manager.get_connection_config(connection_name)
                if config:
                    try:
                        connector = DatabaseConnector()
                        connector.connect(
                            db_type=config["db_type"],
                            host=config["host"],
                            port=config["port"],
                            database=config["database"],
                            username=config.get("username", ""),
                            password=config.get("password", ""),
                            use_windows_auth=config.get("use_windows_auth", False),
                        )
                        if connector.is_connected:
                            manager.connections[connection_name] = connector
                        else:
                            self.append_output(f"[ERRO] Falha ao conectar a '{connection_name}'", error=True)
                            self.status_changed.emit("Erro: Conexao falhou")
                            self._process_next_in_queue()
                            return
                    except Exception as e:
                        self.append_output(f"[ERRO] Erro ao conectar a '{connection_name}': {e}", error=True)
                        self.status_changed.emit("Erro: Conexao falhou")
                        self._process_next_in_queue()
                        return
                else:
                    self.append_output(f"[ERRO] Conexao '{connection_name}' nao encontrada", error=True)
                    self.status_changed.emit("Erro: Conexao indisponivel")
                    self._process_next_in_queue()
                    return
            conn_label = connection_name
        else:
            # Usar conexao padrao da sessao
            if not self.session.is_connected:
                self.append_output("[ERRO] Nenhuma conexão ativa nesta sessão", error=True)
                self.status_changed.emit("Erro: Sem conexão")
                self._process_next_in_queue()
                return
            connector = self.session.connector
            conn_label = "padrao"

        if self._is_executing or (self._sql_thread and self._sql_thread.isRunning()):
            self._execution_queue.append(("sql", query, None, block_name, connection_name))
            return

        self._is_executing = True
        self.session.start_execution("sql")
        self.status_changed.emit(f"Executando SQL ({conn_label})...")

        # Criar worker e thread
        self._sql_thread = QThread()
        self._sql_worker = SessionSqlWorker(connector, query)
        self._sql_worker.moveToThread(self._sql_thread)

        # Guardar block_name para usar no callback
        self._current_block_name = block_name

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
            self.append_output(self._format_log("SQL", f"ERRO: {error}"), error=True)
            self.session.finish_execution(False, f"Erro: {error[:50]}...")
            self.status_changed.emit("Erro SQL")
            self._show_output()
        else:
            # Determinar prefixo do namespace (isolado por bloco ou global)
            if self._current_block_name:
                var_prefix = f"{self._current_block_name}_"  # {nome}_
            else:
                var_prefix = ""  # df, df1, df2 (compatibilidade)

            # Verificar se retornou lista de DataFrames (múltiplos SELECTs)
            if isinstance(df, list):
                # Múltiplos DataFrames - criar variáveis
                total_rows = sum(len(d) for d in df)
                self.append_output(self._format_log("SQL", f"{len(df)} consultas, {total_rows:,} linhas totais"))

                # Criar variáveis: df/b1_df, df1/b1_df1, df2/b1_df2, ...
                for i, dataframe in enumerate(df):
                    if var_prefix:
                        var_name = f"{var_prefix}df" if i == 0 else f"{var_prefix}df{i}"
                    else:
                        var_name = "df" if i == 0 else f"df{i}"
                    self.session.set_variable(var_name, dataframe)
                    self.append_output(self._format_log("SQL", f"{var_name}: {len(dataframe):,} linhas"))

                # Exibir apenas o último DataFrame no grid
                last_df = df[-1]
                last_var_name = f"{var_prefix}df{len(df) - 1}" if len(df) > 1 else f"{var_prefix}df"
                self._set_results(last_df, last_var_name)
                self.session.set_variable("_last_result", last_df)

                self.session.finish_execution(True, f"SQL: {len(df)} consultas")
                self.status_changed.emit(f"✓ SQL: {len(df)} consultas")
            else:
                # DataFrame único
                rows = len(df) if df is not None else 0
                var_name = f"{var_prefix}df"
                self.append_output(self._format_log("SQL", f"{rows:,} linhas -> {var_name}"))
                self._set_results(df, var_name)
                self.session.finish_execution(True, f"SQL: {rows:,} linhas")
                self.status_changed.emit(f"✓ SQL: {rows:,} linhas")

                # Salvar no namespace da sessão
                self.session.set_variable(var_name, df)
                self.session.set_variable("_last_result", df)

            # Limpar block_name apos uso
            self._current_block_name = None

            # Verificar se banco mudou (comando USE)
            if self.session.connector:
                current_db = self.session.connector.get_current_database()
                if self.session.connection_name:
                    self.connection_changed.emit(self.session.connection_name, current_db)

        # Processar próximo da fila se houver
        self._is_executing = False
        self._process_next_in_queue()

    # === EXECUÇÃO PYTHON ===

    def _on_execute_python(self, code: str):
        """Executa Python em background"""
        # Se já está executando, adiciona na fila
        if self._is_executing or (self._python_thread and self._python_thread.isRunning()):
            self._execution_queue.append(("python", code))
            return

        self._is_executing = True
        self.session.start_execution("python")
        self.status_changed.emit("Executando Python...")
        # Preparar namespace com df se existir
        namespace = self.session.namespace.copy()
        namespace["pd"] = pd

        # Verificar se é expressão
        is_expression = False
        try:
            compile(code, "<string>", "eval")
            is_expression = True
        except SyntaxError:
            pass

        # Usar PythonWorker CENTRALIZADO do main_window
        from src.ui.main_window import PythonWorker

        # Criar worker e thread
        self._python_thread = QThread()
        self._python_worker = PythonWorker(code, namespace, is_expression)
        self._python_worker.moveToThread(self._python_thread)

        self.session.register_thread(self._python_thread)

        self._python_thread.started.connect(self._python_worker.run)
        self._python_worker.finished.connect(self._on_python_finished_adapted)

        self._python_thread.start()

    def _on_python_finished_adapted(self, result, output: str, error: str, namespace: dict, figures: list = None):
        """Adapter para usar PythonWorker centralizado"""
        # Chama o callback original com namespace atualizado
        self._on_python_finished(result, output, error, namespace, figures or [])

    def _on_python_finished(self, result, output: str, error: str, updated_namespace: dict, figures: list = None):
        """Callback quando Python termina"""
        figures = figures or []

        if self._python_thread:
            self._python_thread.quit()
            self._python_thread.wait()
            self.session.unregister_thread(self._python_thread)
            self._python_thread = None

        # Marcar bloco atual como finalizado
        current_block = self.editor.get_current_executing_block()
        self.editor.mark_execution_finished(current_block)

        if error:
            self.append_output(self._format_log("PYTHON", f"ERRO:\n{error}"), error=True)
            self.session.finish_execution(False, "Erro Python")
            self.status_changed.emit("Erro Python")
            self._show_output()
        else:
            has_dataframe_result = False
            has_figures = bool(figures)
            has_output = bool(output)

            # 1. Logs/print -> Output
            if output:
                self.append_output(self._format_log("PYTHON", output))

            # 2. Resultado -> Results (DataFrame) ou Output (outro)
            if result is not None:
                if isinstance(result, pd.DataFrame):
                    has_dataframe_result = True
                    self._set_results(result, "result")
                    self.append_output(self._format_log("PYTHON", f"DataFrame: {len(result):,} linhas"))
                else:
                    self.append_output(self._format_log("PYTHON", f"{repr(result)}"))
                    has_output = True

            # 3. Figuras matplotlib -> Results (imagem)
            if has_figures:
                self._set_figures(figures)

            # Logica de exibicao:
            # - Figuras + DataFrame -> mostra figuras (prioridade visual)
            # - Figuras -> mostra figuras
            # - DataFrame -> mostra grid
            # - Output -> mostra output
            if has_figures:
                if has_dataframe_result:
                    self.status_changed.emit(f"Grafico + dados gerados!")
                else:
                    self.status_changed.emit(f"Grafico exibido!")
            elif has_dataframe_result:
                self.status_changed.emit(f"DataFrame {len(result):,} linhas")
            elif has_output:
                self._show_output()
                self.status_changed.emit("Python executado")
            else:
                self.status_changed.emit("Python executado")

            # Atualizar namespace da sessao
            if updated_namespace:
                self.session.update_namespace(updated_namespace)

            self.session.finish_execution(True, "Python executado")

        # Processar proximo da fila se houver
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

        self.append_output(self._format_log("CANCELADO", "Execução cancelada pelo usuário"), error=True)
        self._show_output()

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

        # Suporta formatos:
        # Antigo: (language, code)
        # Medio: (language, code, block)
        # Novo: (language, code, block, block_name, connection_name)
        if len(item) >= 5:
            language, code, block, block_name, connection_name = item[:5]
            if block:
                self.editor.mark_block_started(block)
        elif len(item) == 3:
            language, code, block = item
            block_name = None
            connection_name = None
            if block:
                self.editor.mark_block_started(block)
        else:
            language, code = item
            block = None
            block_name = None
            connection_name = None

        # Executa de acordo com a linguagem
        if language == "sql":
            self._on_execute_sql(code, block_name=block_name, connection_name=connection_name)
        elif language == "python":
            self._on_execute_python(code)
        elif language == "cross":
            self._on_execute_cross_syntax(code)
            # Cross-syntax é síncrono (processado pela MainWindow)
            # Então continuamos para o próximo
            self._process_next_in_queue()

    # === OUTPUT/LOG ===

    def append_output(self, text: str, error: bool = False):
        """Adiciona texto ao output"""
        if error:
            self._log_error(text)
        else:
            self._log(text)

    def clear_output(self):
        """Limpa o output"""
        self._clear_output()

    # === VARIÁVEIS ===

    def _update_variables_view(self, namespace: dict):
        """Atualiza visualização de variáveis"""
        # Filtrar variáveis internas
        visible_vars = {k: v for k, v in namespace.items() if not k.startswith("_") and k not in ("pd", "np", "plt")}

        # Usar o método do BottomTabs
        self._set_variables(visible_vars)

    # === TEMA ===

    def apply_theme(self):
        """Aplica o tema atual"""
        self.editor.apply_theme()
        # Theme manager delegado para painéis globais - não necessário mais

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

    def _on_block_select_connection(self, block):
        """Abre dialogo para selecionar conexao de um bloco SQL"""
        try:
            from src.database.connection_manager import ConnectionManager
            from src.ui.dialogs.connections_manager_dialog import ConnectionsManagerDialog

            manager = ConnectionManager()
            dialog = ConnectionsManagerDialog(manager, self.theme_manager, self)

            if dialog.exec():
                conn_name = dialog.selected_connection
                if conn_name:
                    config = manager.get_connection_config(conn_name)
                    db_type = config.get("db_type", "mysql") if config else "mysql"
                    block.set_connection_name(conn_name, db_type)
        except Exception as e:
            print(f"Erro ao abrir dialogo de conexao: {e}")

    # === CONEXÃO ===

    def connect_to_database(self, connection_name: str, password: str = "") -> bool:
        """
        Conecta esta sessão a um banco de dados (em background)

        Args:
            connection_name: Nome da conexão
            password: Senha (se necessário)

        Returns:
            True (sempre, pois é assíncrono)
        """
        # Obter cor da conexão
        from src.database.connection_manager import ConnectionManager

        manager = ConnectionManager()
        config = manager.get_connection_config(connection_name)
        if config:
            self._connection_color = config.get("color", "#007ACC") or "#007ACC"

        # Cancelar conexão anterior se ainda estiver rodando
        try:
            if self._connection_thread and self._connection_thread.isRunning():
                self._connection_thread.quit()
                self._connection_thread.wait(500)  # Esperar até 500ms
        except RuntimeError:
            pass  # Thread já foi deletada

        # Mostrar loading overlay
        self._show_loading(f"Conectando a {connection_name}...")

        # Criar worker e thread
        self._connection_thread = QThread()
        self._connection_worker = SessionConnectionWorker(self.session, connection_name, password)
        self._connection_worker.moveToThread(self._connection_thread)

        # Conectar sinais
        self._connection_thread.started.connect(self._connection_worker.run)
        self._connection_worker.finished.connect(self._on_connection_finished)
        self._connection_worker.finished.connect(self._connection_thread.quit)
        self._connection_worker.finished.connect(self._connection_worker.deleteLater)
        self._connection_thread.finished.connect(self._connection_thread.deleteLater)

        # Iniciar
        self._connection_thread.start()

        return True

    def is_connecting(self) -> bool:
        """Verifica se está em processo de conexão"""
        try:
            return self._connection_thread is not None and self._connection_thread.isRunning()
        except RuntimeError:
            return False  # Thread foi deletada

    def _on_connection_finished(self, success: bool, message: str):
        """Callback quando conexão termina"""
        # Esconder loading
        self._hide_loading()

        # Mostrar resultado
        if success:
            self.append_output(message)
            self.status_changed.emit(message)
            # Emitir sinal de mudança de conexão
            if self.session.connection_name and self.session.connector:
                db = (
                    self.session.connector.get_current_database()
                    if hasattr(self.session.connector, "get_current_database")
                    else ""
                )
                self.connection_changed.emit(self.session.connection_name, db)
        else:
            self.append_output(message, error=True)
            self.status_changed.emit("Erro na conexão")

    def _show_loading(self, message: str):
        """Mostra overlay de loading"""
        if self._loading_overlay:
            self._loading_overlay.setText(message)
            # Aplicar estilo com cor dinâmica
            self._loading_overlay.setStyleSheet(f"""
                QLabel {{
                    background-color: rgba(30, 30, 30, 230);
                    color: {self._connection_color};
                    font-size: 16px;
                    font-weight: bold;
                    border: 3px solid {self._connection_color};
                    border-radius: 10px;
                    padding: 30px 50px;
                }}
            """)
            # Ajustar tamanho e posição
            self._loading_overlay.resize(self.size())
            self._loading_overlay.move(0, 0)
            self._loading_overlay.show()
            self._loading_overlay.raise_()

    def _hide_loading(self):
        """Esconde overlay de loading"""
        if self._loading_overlay:
            self._loading_overlay.hide()

    def resizeEvent(self, event):
        """Ajusta overlay de loading ao redimensionar"""
        super().resizeEvent(event)
        if self._loading_overlay and self._loading_overlay.isVisible():
            self._loading_overlay.resize(self.size())

    # === CLEANUP ===

    def cleanup(self):
        """Limpa recursos"""
        try:
            if self._sql_thread and self._sql_thread.isRunning():
                self._sql_thread.quit()
                self._sql_thread.wait()
        except RuntimeError:
            pass  # Thread já foi deletada

        try:
            if self._python_thread and self._python_thread.isRunning():
                self._python_thread.quit()
                self._python_thread.wait()
        except RuntimeError:
            pass  # Thread já foi deletada

        try:
            if self._connection_thread and self._connection_thread.isRunning():
                self._connection_thread.quit()
                self._connection_thread.wait()
        except RuntimeError:
            pass  # Thread já foi deletada
