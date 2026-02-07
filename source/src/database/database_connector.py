"""
Conector de banco de dados com suporte para múltiplos SGBDs
"""

from typing import Optional, Dict, Any, List, Union
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
import logging
import pyodbc


logger = logging.getLogger(__name__)


class DatabaseConnector:
    """Classe para gerenciar conexões com diferentes bancos de dados"""

    SUPPORTED_DATABASES = {
        "sqlserver": "SQL Server",
        "mysql": "MySQL",
        "mariadb": "MariaDB",
        "postgresql": "PostgreSQL",
    }

    def __init__(self):
        self.engine: Optional[Engine] = None
        self.connection_params: Dict[str, Any] = {}
        self.db_type: str = ""

    def connect(
        self, db_type: str, host: str, port: int, database: str, username: str = "", password: str = "", **kwargs
    ) -> bool:
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
            self.connection_params = {"host": host, "port": port, "database": database, "username": username}

            logger.info(f"Conectado ao {self.SUPPORTED_DATABASES[db_type]}: {host}/{database}")
            return True

        except Exception as e:
            logger.error(f"Erro ao conectar ao banco: {str(e)}")
            raise

    def _build_connection_string(
        self, db_type: str, host: str, port: int, database: str, username: str, password: str, **kwargs
    ) -> str:
        """Constrói a string de conexão baseada no tipo de banco"""

        if db_type == "sqlserver":
            driver = kwargs.get("driver", "ODBC Driver 17 for SQL Server")
            use_windows_auth = kwargs.get("use_windows_auth", False)

            if use_windows_auth:
                # Windows Authentication
                return f"mssql+pyodbc://{host}:{port}/{database}?driver={driver}&Trusted_Connection=yes"
            else:
                # SQL Server Authentication
                return f"mssql+pyodbc://{username}:{password}@{host}:{port}/{database}?driver={driver}"

        elif db_type == "mysql":
            return f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}?charset=utf8mb4"

        elif db_type == "mariadb":
            return f"mariadb+mariadbconnector://{username}:{password}@{host}:{port}/{database}"

        elif db_type == "postgresql":
            return f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{database}"

        else:
            raise ValueError(f"Tipo de banco não suportado: {db_type}")

    def execute_query(self, query: str) -> Union[pd.DataFrame, List[pd.DataFrame]]:
        """
        Executa uma query SQL e retorna um DataFrame ou lista de DataFrames

        Suporta múltiplos comandos SQL. Para queries com múltiplos SELECTs,
        retorna uma lista de DataFrames (um para cada SELECT).

        Args:
            query: Query SQL a ser executada (pode conter múltiplos comandos)

        Returns:
            Union[pd.DataFrame, List[pd.DataFrame]]: Resultado da query ou lista de resultados
        """
        if not self.engine:
            raise ConnectionError("Não há conexão ativa com o banco de dados")

        try:
            # Detectar comando USE para atualizar banco atual
            import re

            use_match = re.search(r"\bUSE\s+\[?(\w+)\]?\s*;?\s*$", query.strip(), re.IGNORECASE | re.MULTILINE)
            if use_match:
                new_db = use_match.group(1)
                logger.info(f"Detectado comando USE {new_db}")
                # Atualizar banco atual
                self.connection_params["database"] = new_db

            # Remove comandos GO (SQL Server)
            query_clean = query.replace("GO\n", "\n").replace("GO ", " ")

            # Para SQL Server, executar como batch e capturar resultados
            if self.db_type == "sqlserver":
                return self._execute_mssql_batch(query_clean)

            # Para outros bancos, usar lógica antiga
            return self._execute_generic_query(query_clean)

        except Exception as e:
            logger.error(f"Erro ao executar query: {str(e)}")
            raise

    def _execute_mssql_batch(self, query: str) -> pd.DataFrame:
        """Executa batch de comandos SQL Server e retorna último resultado"""
        import pyodbc

        last_error = None  # Declarar ANTES do try para ser acessível no finally
        cursor = None
        raw_conn = None

        try:
            # Usar raw connection do pyodbc para acessar nextset()
            raw_conn = self.engine.raw_connection()
            cursor = raw_conn.cursor()

            # Executar query completa
            cursor.execute(query)

            # Capturar todos os result sets
            dataframes = []
            result_set_count = 0

            # Processar todos os result sets em um loop
            while True:
                result_set_count += 1

                try:
                    if cursor.description:  # Tem colunas (é um SELECT)
                        # Preservar case original das colunas
                        columns = [col[0] for col in cursor.description]
                        rows = cursor.fetchall()
                        logger.info(f"Result set {result_set_count}: {len(rows)} linhas, colunas: {columns}")
                        if rows:
                            df = pd.DataFrame.from_records(rows, columns=columns)
                            dataframes.append(df)
                    else:
                        logger.info(f"Result set {result_set_count}: sem descrição (não retorna dados)")
                except pyodbc.Error as e:
                    last_error = str(e)
                    logger.error(f"Erro PYODBC no result set {result_set_count}: {last_error}")
                    break  # Para ao encontrar erro
                except Exception as e:
                    last_error = str(e)
                    logger.error(f"Erro GENERICO no result set {result_set_count}: {last_error}")
                    break  # Para ao encontrar erro

                # Tentar próximo result set
                try:
                    logger.info(f"Tentando nextset após result set {result_set_count}...")
                    has_next = cursor.nextset()
                    logger.info(f"nextset retornou: {has_next}")

                    # CRÍTICO: pyodbc NÃO lança exceção em nextset() quando há erro!
                    # O erro fica em cursor.messages - precisamos verificar ANTES de continuar
                    if hasattr(cursor, "messages") and cursor.messages:
                        logger.info(f"Mensagens após nextset: {cursor.messages}")
                        for msg in cursor.messages:
                            # Mensagens são tuplas: (estado_sql, mensagem)
                            if len(msg) >= 2:
                                sql_state = msg[0]
                                error_msg = msg[1]
                                logger.info(f"SQL State: {sql_state}, Mensagem: {error_msg}")

                                # Estados SQL de erro começam com classe 01-99 (exceto 01 que é warning)
                                # 42S02 = Invalid object name
                                # 42000 = Syntax error
                                if sql_state and sql_state != "01000":  # 01000 é informational
                                    last_error = error_msg
                                    logger.error(f"ERRO SQL detectado em messages: {last_error}")
                                    break

                    if last_error:
                        break  # Para se encontrou erro nas mensagens

                    if not has_next:
                        break
                except pyodbc.Error as e:
                    # Erro ao tentar próximo result set - pode ser erro SQL
                    last_error = str(e)
                    logger.error(f"Erro PYODBC ao processar nextset: {last_error}")
                    break
                except Exception as e:
                    last_error = str(e)
                    logger.error(f"Erro GENERICO ao processar nextset: {last_error}")
                    break

            # Se houve erro, lançar exceção para reportar ao usuário
            if last_error:
                raise Exception(last_error)

            # Commit
            raw_conn.commit()

            logger.info(f"Total de result sets: {result_set_count}, DataFrames capturados: {len(dataframes)}")

            # Se capturou múltiplos resultados, retornar lista de DataFrames
            if len(dataframes) > 1:
                logger.info(f"Retornando lista com {len(dataframes)} DataFrames")
                return dataframes

            # Se capturou um único resultado, retornar diretamente
            if dataframes:
                logger.info(f"Retornando único DataFrame com {len(dataframes[0])} linhas")
                return dataframes[0]

            # Nenhum resultado - retornar mensagem de sucesso
            rows_affected = cursor.rowcount
            if rows_affected >= 0:
                msg = f"Comando executado com sucesso. {rows_affected} linha(s) afetada(s)."
            else:
                msg = "Comando executado com sucesso."

            logger.info(msg)
            return pd.DataFrame({"Resultado": [msg]})

        except Exception as e:
            logger.error(f"Erro ao executar batch SQL Server: {str(e)}")
            raise  # Re-lançar erro para o usuário ver

        finally:
            # Fechar cursor e conexão
            if cursor:
                try:
                    cursor.close()
                except:
                    pass

            if raw_conn:
                try:
                    raw_conn.close()
                except:
                    pass

    def _execute_generic_query(self, query: str) -> pd.DataFrame:
        """Executa query genérica para bancos não-MSSQL"""
        # Separa por ponto e vírgula para detectar múltiplos comandos
        commands = [cmd.strip() for cmd in query.split(";") if cmd.strip()]

        if len(commands) > 1:
            # Múltiplos comandos - executar todos e capturar resultados dos SELECTs
            dataframes = []

            with self.engine.connect() as conn:
                for cmd in commands:
                    cmd_upper = cmd.strip().upper()

                    if cmd_upper.startswith("SELECT") or cmd_upper.startswith("SHOW"):
                        # É SELECT - captura resultado
                        try:
                            df = pd.read_sql(cmd, self.engine)
                            logger.info(f"SELECT executado: {len(df)} linhas retornadas")
                            dataframes.append(df)
                        except Exception as e:
                            logger.error(f"Erro ao executar SELECT: {str(e)}")
                            raise
                    else:
                        # Não é SELECT - executa como statement
                        conn.execute(text(cmd))

                conn.commit()

            # Se capturou múltiplos resultados, retornar lista de DataFrames
            if len(dataframes) > 1:
                logger.info(f"Retornando lista com {len(dataframes)} DataFrames")
                return dataframes

            # Se capturou um único resultado, retornar diretamente
            if dataframes:
                logger.info(f"Retornando único DataFrame com {len(dataframes[0])} linhas")
                return dataframes[0]

            # Nenhum SELECT executado - retornar mensagem de sucesso
            msg = "Comandos executados com sucesso."
            logger.info(msg)
            return pd.DataFrame({"Resultado": [msg]})
        else:
            # Comando único - tenta buscar resultados
            try:
                df = pd.read_sql(query, self.engine)
                logger.info(f"Query executada com sucesso. Linhas retornadas: {len(df)}")
                return df
            except:
                # Não retorna dados - executa como statement
                with self.engine.connect() as conn:
                    result = conn.execute(text(query))
                    conn.commit()
                    rows_affected = result.rowcount

                    if rows_affected >= 0:
                        msg = f"Comando executado com sucesso. {rows_affected} linha(s) afetada(s)."
                    else:
                        msg = "Comando executado com sucesso."

                    logger.info(msg)
                    return pd.DataFrame({"Resultado": [msg]})

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
            self.connection_params["database"] = database
            logger.info(f"Banco alterado para: {database}")
            return True

        except Exception as e:
            logger.error(f"Erro ao trocar banco: {str(e)}")
            raise

    def get_current_database(self) -> str:
        """Retorna o nome do banco de dados atual"""
        return self.connection_params.get("database", "")

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
            "sqlserver": """
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """,
            "mysql": """
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME
            """,
            "mariadb": """
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME
            """,
            "postgresql": """
                SELECT schemaname as TABLE_SCHEMA, tablename as TABLE_NAME, 'BASE TABLE' as TABLE_TYPE
                FROM pg_tables
                WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                ORDER BY schemaname, tablename
            """,
        }

        query = queries.get(self.db_type, queries["postgresql"])
        return self.execute_query(query)
