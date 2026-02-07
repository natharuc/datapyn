"""
Services - Camada de serviços (lógica de negócio)

Separa completamente regras de negócio da UI.
Cada serviço é responsável por uma área funcional.
"""

from .connection_service import ConnectionConfig, ConnectionService
from .python_execution_service import PythonExecutionResult, PythonExecutionService
from .query_service import QueryResult, QueryService

__all__ = [
    "QueryService",
    "QueryResult",
    "PythonExecutionService",
    "PythonExecutionResult",
    "ConnectionService",
    "ConnectionConfig",
]
