"""
SchemaService - Servico em background para carregar e cachear a estrutura do banco de dados.

Usa information_schema para carregar tabelas, colunas, tipos e chaves.
Fornece os dados para autocomplete SQL no Monaco Editor.

Thread-safe: cada carregamento usa thread propria com cleanup seguro.
Erros sao silenciados - o usuario pode forcar recarga manualmente.
"""

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from typing import Dict, List, Optional
import logging
import traceback

logger = logging.getLogger(__name__)


class SchemaWorker(QObject):
    """Worker que carrega schema do banco em background thread"""

    finished = pyqtSignal(dict)  # {tables: [...], columns: {...}}
    error = pyqtSignal(str)
    progress = pyqtSignal(str)  # mensagem de progresso

    def __init__(self, connector):
        super().__init__()
        self.connector = connector
        self._cancelled = False

    def cancel(self):
        """Marca worker como cancelado"""
        self._cancelled = True

    def run(self):
        """Carrega schema completo do banco via information_schema.

        Silencia erros individuais - retorna schema parcial se algo falhar.
        """
        try:
            self.progress.emit("Carregando estrutura do banco...")
            schema = {"tables": [], "columns": {}, "database": "", "databases": []}

            if self._cancelled:
                return

            # Obter banco atual
            try:
                db_name = self.connector.get_current_database()
                schema["database"] = db_name or ""
            except Exception:
                schema["database"] = ""

            if self._cancelled:
                return

            # Obter lista de todos os bancos do servidor
            try:
                databases_query = self._get_databases_query()
                df = self.connector.execute_query(databases_query)
                if df is not None and len(df) > 0:
                    for _, row in df.iterrows():
                        db = str(row.iloc[0])
                        schema["databases"].append(db)
            except Exception as e:
                logger.debug(f"Erro ao carregar lista de bancos: {e}")

            if self._cancelled:
                return

            # Obter tabelas e views
            try:
                tables_query = self._get_tables_query()
                df = self.connector.execute_query(tables_query)
                if df is not None and len(df) > 0:
                    for _, row in df.iterrows():
                        if self._cancelled:
                            return
                        table_info = {
                            "name": str(row.get("table_name", row.iloc[0])),
                            "schema": str(row.get("table_schema", "")) if "table_schema" in df.columns else "",
                            "type": str(row.get("table_type", "TABLE")) if "table_type" in df.columns else "TABLE",
                        }
                        schema["tables"].append(table_info)
            except Exception as e:
                logger.debug(f"Erro ao carregar tabelas: {e}")

            if self._cancelled:
                return

            # Obter colunas de todas as tabelas
            try:
                columns_query = self._get_columns_query()
                df = self.connector.execute_query(columns_query)
                if df is not None and len(df) > 0:
                    for _, row in df.iterrows():
                        if self._cancelled:
                            return
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

            if self._cancelled:
                return

            self.progress.emit(
                f"Schema carregado: {len(schema['tables'])} tabelas, "
                f"{sum(len(v) for v in schema['columns'].values())} colunas"
            )
            self.finished.emit(schema)

        except Exception as e:
            # Silenciar erros - nao interromper o usuario
            logger.warning(f"Erro ao carregar schema: {e}")
            try:
                self.error.emit(str(e))
            except RuntimeError:
                pass  # Qt object pode ter sido deletado

    def _get_databases_query(self) -> str:
        """Query para obter lista de todos os bancos do servidor"""
        db_type = getattr(self.connector, "db_type", "").lower()

        if db_type in ("mssql", "sqlserver"):
            return "SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' ORDER BY name"
        elif db_type == "postgresql":
            return "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname"
        else:
            # MySQL, MariaDB
            return "SHOW DATABASES"

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

    Thread-safe: guarda referencia a threads ativas para evitar
    "QThread: Destroyed while thread is still running".
    """

    schema_loaded = pyqtSignal(dict, str)  # Emite schema completo + connection_name
    schema_error = pyqtSignal(str)
    loading_progress = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_threads: list = []  # threads ativas para manter referencia
        self._cache: Dict[str, dict] = {}  # connection_name -> schema

    def load_schema(self, connector, connection_name: str = ""):
        """
        Inicia carregamento do schema em background.

        Thread-safe: cancela worker anterior mas deixa thread finalizar naturalmente.

        Args:
            connector: DatabaseConnector com conexao ativa
            connection_name: Nome da conexao (para cache)
        """
        # Cancelar workers anteriores (nao emitirao sinais)
        self._cancel_pending_workers()

        # Verificar cache
        if connection_name and connection_name in self._cache:
            self.schema_loaded.emit(self._cache[connection_name], connection_name)
            return

        try:
            # Criar worker e thread
            thread = QThread()
            worker = SchemaWorker(connector)
            worker.moveToThread(thread)

            # Conectar sinais
            thread.started.connect(worker.run)
            worker.finished.connect(lambda schema: self._on_finished(schema, connection_name))
            worker.error.connect(self._on_error)
            worker.progress.connect(self.loading_progress.emit)

            # Cleanup seguro: worker e thread sao deletados apos finalizacao
            worker.finished.connect(thread.quit)
            worker.error.connect(thread.quit)
            thread.finished.connect(lambda: self._cleanup_thread(thread, worker))

            # Guardar referencia para evitar garbage collection
            self._active_threads.append((thread, worker))

            thread.start()
        except Exception as e:
            logger.warning(f"Erro ao iniciar carregamento de schema: {e}")

    def _on_finished(self, schema: dict, connection_name: str):
        """Schema carregado com sucesso"""
        try:
            if connection_name:
                self._cache[connection_name] = schema
            self.schema_loaded.emit(schema, connection_name)
        except RuntimeError:
            pass  # Qt object pode ter sido deletado

    def _on_error(self, error: str):
        """Erro ao carregar schema - silencia para nao atrapalhar o usuario"""
        logger.warning(f"Erro ao carregar schema: {error}")
        try:
            self.schema_error.emit(error)
        except RuntimeError:
            pass

    def get_cached_schema(self, connection_name: str) -> Optional[dict]:
        """Retorna schema cacheado ou None"""
        return self._cache.get(connection_name)

    def invalidate_cache(self, connection_name: str = ""):
        """Invalida cache de uma conexao ou todas"""
        if connection_name:
            self._cache.pop(connection_name, None)
        else:
            self._cache.clear()

    def _cancel_pending_workers(self):
        """Cancela workers pendentes (marca como cancelados)"""
        for thread, worker in self._active_threads:
            try:
                if worker:
                    worker.cancel()
            except RuntimeError:
                pass

    def _cleanup_thread(self, thread, worker):
        """Remove thread finalizada da lista de ativas e agenda deleteLater"""
        try:
            self._active_threads = [
                (t, w) for t, w in self._active_threads if t is not thread
            ]
            if worker:
                worker.deleteLater()
            if thread:
                thread.deleteLater()
        except RuntimeError:
            pass

    def cleanup(self):
        """Limpa recursos - espera threads finalizarem com timeout"""
        # Cancelar todos os workers
        for thread, worker in self._active_threads:
            try:
                if worker:
                    worker.cancel()
            except RuntimeError:
                pass

        # Esperar threads finalizarem
        for thread, worker in self._active_threads:
            try:
                if thread and thread.isRunning():
                    thread.quit()
                    thread.wait(2000)  # 2s timeout
            except RuntimeError:
                pass

        self._active_threads.clear()
        self._cache.clear()
