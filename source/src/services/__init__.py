"""
Services - Camada de servicos (logica de negocio)

Separa completamente regras de negocio da UI.
Cada servico e responsavel por uma area funcional.
"""
from .query_service import QueryService, QueryResult
from .python_execution_service import PythonExecutionService, PythonExecutionResult
from .connection_service import ConnectionService, ConnectionConfig
from .session_lifecycle_service import SessionLifecycleService
from .panel_manager import PanelManager, PanelSet
from .file_import_service import FileImportService

__all__ = [
    'QueryService',
    'QueryResult',
    'PythonExecutionService',
    'PythonExecutionResult',
    'ConnectionService',
    'ConnectionConfig',
    'SessionLifecycleService',
    'PanelManager',
    'PanelSet',
    'FileImportService',
]
