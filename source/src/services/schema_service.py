"""
SchemaService - Servico em background para carregar e cachear a estrutura do banco de dados.

Usa information_schema para carregar tabelas, colunas, tipos e chaves.
Fornece os dados para autocomplete SQL no Monaco Editor.
"""

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class SchemaWorker(QObject):
    """Worker que carrega schema do banco em background thread"""

    finished = pyqtSignal(dict)  # {tables: [...], columns: {...}}
    error = pyqtSignal(str)
    progress = pyqtSignal(str)  # mensagem de progresso

    def __init__(self, connector):
        super().__init__()
        self.connector = connector

    def run(self):
        """Carrega schema completo do banco via information_schema"""
        try:
            self.progress.emit("Carregando estrutura do banco...")
            schema = {"tables": [], "columns": {}, "database": ""}

            # Obter banco atual
            try:
                db_name = self.connector.get_current_database()
                schema["database"] = db_name or ""
            except Exception:
                schema["database"] = ""

            # Obter tabelas e views
            try:
                tables_query = self._get_tables_query()
                df = self.connector.execute_query(tables_query)
                if df is not None and len(df) > 0:
                    for _, row in df.iterrows():
                        table_info = {
                            "name": str(row.get("table_name", row.iloc[0])),
                            "schema": str(row.get("table_schema", "")) if "table_schema" in df.columns else "",
                            "type": str(row.get("table_type", "TABLE")) if "table_type" in df.columns else "TABLE",
                        }
                        schema["tables"].append(table_info)
                        self.progress.emit(f"Tabela: {table_info['name']}")
            except Exception as e:
                logger.debug(f"Erro ao carregar tabelas: {e}")

            # Obter colunas de todas as tabelas
            try:
                columns_query = self._get_columns_query()
                df = self.connector.execute_query(columns_query)
                if df is not None and len(df) > 0:
                    for _, row in df.iterrows():
                        table_name = str(row.get("table_name", row.iloc[0]))
                        col_info = {
                            "name": str(row.get("column_name", row.iloc[1])),
                            "type": str(row.get("data_type", "")) if "data_type" in df.columns else "",
                            "nullable": str(row.get("is_nullable", "YES")) if "is_nullable" in df.columns else "YES",
                        }
                        if table_name not in schema["columns"]:
                            schema["columns"][table_name] = []
                        schema["columns"][table_name].append(col_info)
            except Exception as e:
                logger.debug(f"Erro ao carregar colunas: {e}")

            self.progress.emit(
                f"Schema carregado: {len(schema['tables'])} tabelas, "
                f"{sum(len(v) for v in schema['columns'].values())} colunas"
            )
            self.finished.emit(schema)

        except Exception as e:
            self.error.emit(str(e))

    def _get_tables_query(self) -> str:
        """Query para obter tabelas - compativel com todos os SGBDs"""
        db_type = getattr(self.connector, "db_type", "").lower()

        if db_type in ("mssql", "sqlserver"):
            return """
                SELECT TABLE_SCHEMA as table_schema,
                       TABLE_NAME as table_name,
                       TABLE_TYPE as table_type
                FROM INFORMATION_SCHEMA.TABLES
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """
        elif db_type == "postgresql":
            return """
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name
            """
        else:
            # MySQL, MariaDB e outros
            return """
                SELECT TABLE_SCHEMA as table_schema,
                       TABLE_NAME as table_name,
                       TABLE_TYPE as table_type
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME
            """

    def _get_columns_query(self) -> str:
        """Query para obter colunas - compativel com todos os SGBDs"""
        db_type = getattr(self.connector, "db_type", "").lower()

        if db_type in ("mssql", "sqlserver"):
            return """
                SELECT TABLE_NAME as table_name,
                       COLUMN_NAME as column_name,
                       DATA_TYPE as data_type,
                       IS_NULLABLE as is_nullable,
                       ORDINAL_POSITION as ordinal_position
                FROM INFORMATION_SCHEMA.COLUMNS
                ORDER BY TABLE_NAME, ORDINAL_POSITION
            """
        elif db_type == "postgresql":
            return """
                SELECT table_name, column_name, data_type, is_nullable,
                       ordinal_position
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_name, ordinal_position
            """
        else:
            # MySQL, MariaDB
            return """
                SELECT TABLE_NAME as table_name,
                       COLUMN_NAME as column_name,
                       DATA_TYPE as data_type,
                       IS_NULLABLE as is_nullable,
                       ORDINAL_POSITION as ordinal_position
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME, ORDINAL_POSITION
            """


class SchemaService(QObject):
    """
    Servico que gerencia o cache de schema do banco de dados.

    Carrega schema em background quando uma conexao e estabelecida.
    Emite sinal com o schema carregado para atualizar o autocomplete.
    """

    schema_loaded = pyqtSignal(dict, str)  # Emite schema completo + connection_name
    schema_error = pyqtSignal(str)
    loading_progress = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[SchemaWorker] = None
        self._cache: Dict[str, dict] = {}  # connection_name -> schema

    def load_schema(self, connector, connection_name: str = ""):
        """
        Inicia carregamento do schema em background.

        Args:
            connector: DatabaseConnector com conexao ativa
            connection_name: Nome da conexao (para cache)
        """
        # Cancela carregamento anterior
        self._cancel_current()

        # Verificar cache
        if connection_name and connection_name in self._cache:
            self.schema_loaded.emit(self._cache[connection_name])
            return

        # Criar worker e thread
        self._thread = QThread()
        self._worker = SchemaWorker(connector)
        self._worker.moveToThread(self._thread)

        # Conectar sinais
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(lambda schema: self._on_finished(schema, connection_name))
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(self.loading_progress.emit)

        # Cleanup
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _on_finished(self, schema: dict, connection_name: str):
        """Schema carregado com sucesso"""
        if connection_name:
            self._cache[connection_name] = schema
        self.schema_loaded.emit(schema, connection_name)

    def _on_error(self, error: str):
        """Erro ao carregar schema"""
        logger.warning(f"Erro ao carregar schema: {error}")
        self.schema_error.emit(error)

    def get_cached_schema(self, connection_name: str) -> Optional[dict]:
        """Retorna schema cacheado ou None"""
        return self._cache.get(connection_name)

    def invalidate_cache(self, connection_name: str = ""):
        """Invalida cache de uma conexao ou todas"""
        if connection_name:
            self._cache.pop(connection_name, None)
        else:
            self._cache.clear()

    def _cancel_current(self):
        """Cancela carregamento em andamento"""
        try:
            if self._thread and self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(1000)
        except RuntimeError:
            pass

    def cleanup(self):
        """Limpa recursos"""
        self._cancel_current()
        self._cache.clear()
