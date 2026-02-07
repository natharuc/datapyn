"""
Workers - Threads de background para operações pesadas

Separa completamente a lógica de processamento da UI.
Cada worker emite sinais com resultados, nunca manipula UI diretamente.
"""

import sys
import traceback
from io import StringIO
from typing import Any, Dict

import pandas as pd
from PyQt6.QtCore import QObject, QThread, pyqtSignal


class BaseWorker(QObject):
    """
    Base abstrata para workers

    Garante que todos os workers sigam o mesmo padrão:
    - started: Emitido ao iniciar
    - finished: Emitido ao terminar (sempre)
    - error: Emitido se houver erro
    """

    started = pyqtSignal()
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def run(self):
        """Sobrescrever em subclasses"""
        raise NotImplementedError


class SqlExecutionWorker(BaseWorker):
    """
    Worker para execução de queries SQL em background

    Signals:
        - result_ready(DataFrame): Query executada com sucesso
        - error(str): Erro na execução
    """

    result_ready = pyqtSignal(object)  # pd.DataFrame ou None

    def __init__(self, connector, query: str):
        super().__init__()
        self.connector = connector
        self.query = query

    def run(self):
        """Executa query SQL"""
        self.started.emit()

        try:
            df = self.connector.execute_query(self.query)
            self.result_ready.emit(df)
        except Exception as e:
            error_msg = f"Erro SQL: {str(e)}"
            self.error.emit(error_msg)
        finally:
            self.finished.emit()


class DatabaseConnectionWorker(BaseWorker):
    """
    Worker para conectar a banco de dados em background

    Signals:
        - connection_success(): Conexão estabelecida
        - error(str): Erro na conexão
    """

    connection_success = pyqtSignal()

    def __init__(
        self,
        connection_manager,
        conn_name: str,
        db_type: str,
        host: str,
        port: int,
        database: str,
        username: str = "",
        password: str = "",
        use_windows_auth: bool = False,
    ):
        super().__init__()
        self.connection_manager = connection_manager
        self.conn_name = conn_name
        self.db_type = db_type
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.use_windows_auth = use_windows_auth

    def run(self):
        """Conecta ao banco"""
        self.started.emit()

        try:
            self.connection_manager.create_connection(
                self.conn_name,
                self.db_type,
                self.host,
                self.port,
                self.database,
                self.username,
                self.password,
                use_windows_auth=self.use_windows_auth,
            )
            self.connection_success.emit()
        except Exception as e:
            error_msg = f"Erro de conexão: {str(e)}\n{traceback.format_exc()}"
            self.error.emit(error_msg)
        finally:
            self.finished.emit()


class PythonExecutionWorker(BaseWorker):
    """REMOVIDO - usar PythonWorker do main_window.py"""

    execution_complete = pyqtSignal(object, str, str)

    def __init__(self, code: str, namespace: dict, is_expression: bool = False):
        super().__init__()
        raise NotImplementedError("Use PythonWorker do main_window.py - execução centralizada!")


class MixedSyntaxExecutionWorker(BaseWorker):
    """
    Worker para execução de sintaxe mista (SQL + Python)

    Executa código com padrão {{ SQL }} integrado.

    Signals:
        - execution_complete(result_dict): Execução finalizada
        - error(str): Erro na execução
    """

    execution_complete = pyqtSignal(dict)  # {output, queries_executed, result}

    def __init__(self, executor, code: str, namespace: dict):
        super().__init__()
        self.executor = executor
        self.code = code
        self.namespace = namespace

    def run(self):
        """Executa sintaxe mista"""
        self.started.emit()

        try:
            result = self.executor.parse_and_execute(self.code, self.namespace)
            self.execution_complete.emit(result)
        except Exception as e:
            error_msg = f"Erro Mixed Syntax:\n{traceback.format_exc()}"
            self.error.emit(error_msg)
        finally:
            self.finished.emit()


class DataFrameOperationWorker(BaseWorker):
    """
    Worker genérico para operações em DataFrames

    Útil para operações pesadas como:
    - Merge de grandes datasets
    - Group by complexos
    - Transformações custosas

    Signals:
        - operation_complete(result): Operação finalizada
        - error(str): Erro na operação
    """

    operation_complete = pyqtSignal(object)  # pd.DataFrame ou outro resultado

    def __init__(self, operation_func, *args, **kwargs):
        """
        Args:
            operation_func: Função que retorna um DataFrame
            *args, **kwargs: Argumentos para operation_func
        """
        super().__init__()
        self.operation_func = operation_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        """Executa operação"""
        self.started.emit()

        try:
            result = self.operation_func(*self.args, **self.kwargs)
            self.operation_complete.emit(result)
        except Exception as e:
            error_msg = f"Erro na operação: {str(e)}\n{traceback.format_exc()}"
            self.error.emit(error_msg)
        finally:
            self.finished.emit()


# Utility function para executar workers facilmente
def execute_worker(worker: BaseWorker, parent_thread: QThread = None) -> QThread:
    """
    Helper para executar um worker em uma thread separada

    Args:
        worker: Instância do worker
        parent_thread: Thread pai (opcional)

    Returns:
        QThread: Thread criada

    Exemplo:
        worker = SqlExecutionWorker(connector, "SELECT * FROM users")
        worker.result_ready.connect(self.on_result)
        worker.error.connect(self.on_error)
        thread = execute_worker(worker)
    """
    thread = QThread(parent_thread)
    worker.moveToThread(thread)

    # Conectar sinais de lifecycle
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    # Iniciar thread
    thread.start()

    return thread
