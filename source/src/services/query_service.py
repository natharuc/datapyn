"""
Query Service - Serviço para execução de queries SQL

Responsabilidades:
- Executar queries SQL via workers
- Validar queries
- Gerenciar histórico de queries
- Tratar erros de forma consistente
"""

from typing import Optional, Callable, List
from datetime import datetime
from dataclasses import dataclass
import pandas as pd

from ..workers import SqlExecutionWorker, execute_worker
from ..state import ApplicationState


@dataclass
class QueryResult:
    """Resultado de uma query"""

    dataframe: Optional[pd.DataFrame]
    query: str
    execution_time: float
    rows_affected: int
    error: Optional[str] = None
    executed_at: datetime = None

    def __post_init__(self):
        if self.executed_at is None:
            self.executed_at = datetime.now()

    @property
    def is_success(self) -> bool:
        return self.error is None

    @property
    def row_count(self) -> int:
        if self.dataframe is not None:
            return len(self.dataframe)
        return 0


class QueryService:
    """
    Serviço de execução de queries SQL

    Usa ApplicationState para obter conexão ativa.
    Executa queries via workers assíncronos.

    Exemplo:
        service = QueryService()
        service.execute_query(
            "SELECT * FROM users",
            on_success=self.handle_result,
            on_error=self.handle_error
        )
    """

    def __init__(self):
        self.app_state = ApplicationState.instance()
        self._query_history: List[QueryResult] = []

    def execute_query(
        self,
        query: str,
        *,
        on_success: Optional[Callable[[QueryResult], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_started: Optional[Callable[[], None]] = None,
        on_finished: Optional[Callable[[], None]] = None,
    ):
        """
        Executa query SQL de forma assíncrona

        Args:
            query: SQL a executar
            on_success: Callback com QueryResult
            on_error: Callback com mensagem de erro
            on_started: Callback ao iniciar
            on_finished: Callback ao finalizar (sempre)
        """
        # Valida que há conexão ativa
        conn = self.app_state.get_active_connection()
        if not conn or not conn.is_connected:
            error_msg = "Nenhuma conexão ativa disponível"
            if on_error:
                on_error(error_msg)
            return

        # Cria worker
        from ..database import ConnectionManager

        conn_manager = ConnectionManager()
        connector = conn_manager.get_connection(conn.name)

        if not connector:
            error_msg = f"Conexão '{conn.name}' não encontrada"
            if on_error:
                on_error(error_msg)
            return

        worker = SqlExecutionWorker(connector, query)

        # Tempo de início
        start_time = datetime.now()

        # Conectar callbacks
        if on_started:
            worker.started.connect(on_started)

        if on_finished:
            worker.finished.connect(on_finished)

        def handle_result(df: pd.DataFrame):
            """Handler interno para resultado"""
            execution_time = (datetime.now() - start_time).total_seconds()

            result = QueryResult(
                dataframe=df, query=query, execution_time=execution_time, rows_affected=len(df) if df is not None else 0
            )

            # Adiciona ao histórico
            self._query_history.append(result)

            # Atualiza estado da conexão
            self.app_state.update_connection_status(conn.name, True)

            if on_success:
                on_success(result)

        def handle_error(error_msg: str):
            """Handler interno para erro"""
            execution_time = (datetime.now() - start_time).total_seconds()

            result = QueryResult(
                dataframe=None, query=query, execution_time=execution_time, rows_affected=0, error=error_msg
            )

            # Adiciona ao histórico
            self._query_history.append(result)

            if on_error:
                on_error(error_msg)

        worker.result_ready.connect(handle_result)
        worker.error.connect(handle_error)

        # Executa worker
        execute_worker(worker)

    def get_query_history(self, limit: int = 50) -> List[QueryResult]:
        """Retorna histórico de queries"""
        return self._query_history[-limit:]

    def clear_history(self):
        """Limpa histórico de queries"""
        self._query_history.clear()

    def validate_query(self, query: str) -> tuple[bool, str]:
        """
        Valida query SQL (básico)

        Returns:
            (is_valid, error_message)
        """
        query = query.strip()

        if not query:
            return False, "Query vazia"

        # Validações básicas
        dangerous_keywords = ["DROP DATABASE", "DROP SCHEMA", "TRUNCATE TABLE"]
        query_upper = query.upper()

        for keyword in dangerous_keywords:
            if keyword in query_upper:
                return False, f"Operação perigosa detectada: {keyword}"

        return True, ""
