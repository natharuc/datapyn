"""
Conector de banco de dados com suporte para múltiplos SGBDs
"""
from typing import Optional, Dict, Any
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
import logging


logger = logging.getLogger(__name__)


class DatabaseConnector:
    """Classe para gerenciar conexões com diferentes bancos de dados"""
    
    SUPPORTED_DATABASES = {
        'sqlserver': 'SQL Server',
        'mysql': 'MySQL',
        'mariadb': 'MariaDB',
        'postgresql': 'PostgreSQL',
    }
    
    def __init__(self):
        self.engine: Optional[Engine] = None
        self.connection_params: Dict[str, Any] = {}
        self.db_type: str = ''
        
    def connect(self, db_type: str, host: str, port: int, database: str, 
                username: str = '', password: str = '', **kwargs) -> bool:
        """
        Conecta ao banco de dados
        
        Args:
            db_type: Tipo do banco (sqlserver, mysql, mariadb, postgresql)
            host: Endereço do servidor
            port: Porta do servidor
            database: Nome do banco de dados
            username: Usuário (opcional para Windows Auth)
            password: Senha (opcional para Windows Auth)
            **kwargs: Parâmetros adicionais (use_windows_auth=True para SQL Server)
            
        Returns:
            bool: True se conectou com sucesso
        """
        try:
            connection_string = self._build_connection_string(
                db_type, host, port, database, username, password, **kwargs
            )
            
            self.engine = create_engine(connection_string, pool_pre_ping=True)
            
            # Testa a conexão
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            self.db_type = db_type
            self.connection_params = {
                'host': host,
                'port': port,
                'database': database,
                'username': username
            }
            
            logger.info(f"Conectado ao {self.SUPPORTED_DATABASES[db_type]}: {host}/{database}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao conectar ao banco: {str(e)}")
            raise
    
    def _build_connection_string(self, db_type: str, host: str, port: int, 
                                 database: str, username: str, password: str, 
                                 **kwargs) -> str:
        """Constrói a string de conexão baseada no tipo de banco"""
        
        if db_type == 'sqlserver':
            driver = kwargs.get('driver', 'ODBC Driver 17 for SQL Server')
            use_windows_auth = kwargs.get('use_windows_auth', False)
            
            if use_windows_auth:
                # Windows Authentication
                return f"mssql+pyodbc://{host}:{port}/{database}?driver={driver}&Trusted_Connection=yes"
            else:
                # SQL Server Authentication
                return f"mssql+pyodbc://{username}:{password}@{host}:{port}/{database}?driver={driver}"
        
        elif db_type == 'mysql':
            return f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}?charset=utf8mb4"
        
        elif db_type == 'mariadb':
            return f"mariadb+mariadbconnector://{username}:{password}@{host}:{port}/{database}"
        
        elif db_type == 'postgresql':
            return f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{database}"
        
        else:
            raise ValueError(f"Tipo de banco não suportado: {db_type}")
    
    def execute_query(self, query: str) -> pd.DataFrame:
        """
        Executa uma query SQL e retorna um DataFrame
        
        Tenta sempre buscar resultados primeiro. Se não houver dados,
        retorna mensagem de sucesso com linhas afetadas.
        
        Args:
            query: Query SQL a ser executada (pode conter múltiplos comandos)
            
        Returns:
            pd.DataFrame: Resultado da query ou mensagem de execução
        """
        if not self.engine:
            raise ConnectionError("Não há conexão ativa com o banco de dados")
        
        try:
            # Tenta buscar resultados (SELECT, SHOW, etc)
            try:
                df = pd.read_sql(query, self.engine)
                logger.info(f"Query executada com sucesso. Linhas retornadas: {len(df)}")
                return df
            except Exception as fetch_error:
                # Se falhou porque não retorna dados, executa como statement
                error_msg = str(fetch_error).lower()
                if 'does not return rows' in error_msg or 'no result' in error_msg or 'closed automatically' in error_msg:
                    # Comando que não retorna dados (INSERT, UPDATE, DELETE, etc)
                    with self.engine.connect() as conn:
                        result = conn.execute(text(query))
                        conn.commit()
                        rows_affected = result.rowcount
                        
                        # Retorna DataFrame informativo
                        if rows_affected >= 0:
                            msg = f"✓ Comando executado com sucesso. {rows_affected} linha(s) afetada(s)."
                        else:
                            msg = "✓ Comando executado com sucesso."
                        
                        logger.info(msg)
                        return pd.DataFrame({'Resultado': [msg]})
                else:
                    # Outro tipo de erro - propaga
                    raise
                    
        except Exception as e:
            logger.error(f"Erro ao executar query: {str(e)}")
            raise
    
    def execute_statement(self, statement: str) -> int:
        """
        Executa um statement SQL (INSERT, UPDATE, DELETE, etc)
        
        Args:
            statement: Statement SQL a ser executado
            
        Returns:
            int: Número de linhas afetadas
        """
        if not self.engine:
            raise ConnectionError("Não há conexão ativa com o banco de dados")
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(statement))
                conn.commit()
                rows_affected = result.rowcount
                logger.info(f"Statement executado. Linhas afetadas: {rows_affected}")
                return rows_affected
        except Exception as e:
            logger.error(f"Erro ao executar statement: {str(e)}")
            raise
    
    def change_database(self, database: str) -> bool:
        """
        Troca o banco de dados atual
        
        Args:
            database: Nome do novo banco de dados
            
        Returns:
            bool: True se trocou com sucesso
        """
        if not self.engine:
            raise ConnectionError("Não há conexão ativa com o banco de dados")
        
        try:
            with self.engine.connect() as conn:
                conn.execute(text(f"USE [{database}]"))
                conn.commit()
            
            # Atualiza params internos
            self.connection_params['database'] = database
            logger.info(f"Banco alterado para: {database}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao trocar banco: {str(e)}")
            raise
    
    def get_current_database(self) -> str:
        """Retorna o nome do banco de dados atual"""
        return self.connection_params.get('database', '')
    
    def disconnect(self):
        """Desconecta do banco de dados"""
        if self.engine:
            self.engine.dispose()
            self.engine = None
            logger.info("Desconectado do banco de dados")
    
    def is_connected(self) -> bool:
        """Verifica se há uma conexão ativa"""
        if not self.engine:
            return False
        
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except:
            return False
    
    def get_tables(self) -> pd.DataFrame:
        """Retorna lista de tabelas do banco"""
        if not self.engine:
            raise ConnectionError("Não há conexão ativa com o banco de dados")
        
        queries = {
            'sqlserver': """
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """,
            'mysql': """
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME
            """,
            'mariadb': """
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME
            """,
            'postgresql': """
                SELECT schemaname as TABLE_SCHEMA, tablename as TABLE_NAME, 'BASE TABLE' as TABLE_TYPE
                FROM pg_tables
                WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                ORDER BY schemaname, tablename
            """
        }
        
        query = queries.get(self.db_type, queries['postgresql'])
        return self.execute_query(query)
