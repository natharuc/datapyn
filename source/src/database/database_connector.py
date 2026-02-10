"""
Conector de banco de dados com suporte para múltiplos SGBDs
"""

from typing import Optional, Dict, Any, List, Union
import pandas as pd
from sqlalchemy import create_engine, text, event
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
        self._active_raw_conn = None  # Referencia para cancelamento
        self._active_cursor = None  # Referencia ao cursor para cancelamento
        self._cancelled = False  # Flag de cancelamento

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

            # Registrar evento no pool para garantir que toda conexao
            # retirada do pool use o banco correto (resolve o problema
            # com USE <db> que so afeta uma conexao do pool)
            if db_type == "sqlserver":
                connector_ref = self

                @event.listens_for(self.engine, "checkout")
                def on_checkout(dbapi_conn, connection_record, connection_proxy):
                    current_db = connector_ref.connection_params.get("database", "")
                    if current_db:
                        try:
                            cursor = dbapi_conn.cursor()
                            cursor.execute(f"USE [{current_db}]")
                            cursor.close()
                        except Exception:
                            pass  # Silenciar - o USE no batch vai pegar o erro

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

    def _get_available_odbc_driver(self) -> str:
        """
        Detecta o driver ODBC do SQL Server instalado no sistema.
        Retorna o driver mais recente disponivel por ordem de prioridade.

        Returns:
            str: Nome do driver ODBC encontrado

        Raises:
            RuntimeError: Se nenhum driver compativel for encontrado
        """
        # Ordem de prioridade: drivers mais recentes primeiro
        preferred_drivers = [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "ODBC Driver 13.1 for SQL Server",
            "ODBC Driver 13 for SQL Server",
            "ODBC Driver 11 for SQL Server",
            "SQL Server Native Client 11.0",
            "SQL Server Native Client 10.0",
            "SQL Server",  # Driver antigo, ultima opcao
        ]

        try:
            available_drivers = pyodbc.drivers()
            logger.info(f"Drivers ODBC disponiveis: {available_drivers}")

            for driver in preferred_drivers:
                if driver in available_drivers:
                    logger.info(f"Driver ODBC selecionado: {driver}")
                    return driver

            # Se nenhum driver preferido encontrado, tenta usar qualquer um com "SQL Server"
            for driver in available_drivers:
                if "SQL Server" in driver:
                    logger.warning(f"Usando driver alternativo: {driver}")
                    return driver

        except Exception as e:
            logger.error(f"Erro ao listar drivers ODBC: {e}")

        raise RuntimeError(
            "Nenhum driver ODBC do SQL Server encontrado.\n"
            "Instale o 'ODBC Driver 18 for SQL Server' em:\n"
            "https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server"
        )

    def _build_connection_string(
        self, db_type: str, host: str, port: int, database: str, username: str, password: str, **kwargs
    ) -> str:
        """Constrói a string de conexão baseada no tipo de banco"""
        from urllib.parse import quote_plus

        if db_type == "sqlserver":
            # Detectar driver automaticamente ou usar o especificado
            driver = kwargs.get("driver")
            if not driver:
                driver = self._get_available_odbc_driver()

            use_windows_auth = kwargs.get("use_windows_auth", False)
            trust_cert = kwargs.get("trust_server_certificate", False)

            # Usar connection string ODBC direta
            if use_windows_auth:
                # Windows Authentication
                odbc_string = (
                    f"DRIVER={{{driver}}};"
                    f"SERVER={host},{port};"
                    f"DATABASE={database};"
                    f"Trusted_Connection=yes"
                )
            else:
                # SQL Server Authentication
                odbc_string = (
                    f"DRIVER={{{driver}}};"
                    f"SERVER={host},{port};"
                    f"DATABASE={database};"
                    f"UID={username};"
                    f"PWD={password}"
                )

            # Adicionar TrustServerCertificate se solicitado
            if trust_cert:
                odbc_string += ";TrustServerCertificate=yes"

            return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_string)}"

        elif db_type == "mysql":
            # URL encode username e password para caracteres especiais
            user_encoded = quote_plus(username)
            pass_encoded = quote_plus(password)
            return f"mysql+pymysql://{user_encoded}:{pass_encoded}@{host}:{port}/{database}?charset=utf8mb4"

        elif db_type == "mariadb":
            # URL encode username e password para caracteres especiais
            user_encoded = quote_plus(username)
            pass_encoded = quote_plus(password)
            return f"mariadb+mariadbconnector://{user_encoded}:{pass_encoded}@{host}:{port}/{database}"

        elif db_type == "postgresql":
            # URL encode username e password para caracteres especiais
            # Importante para Azure PostgreSQL onde o usuario e "user@server"
            user_encoded = quote_plus(username)
            pass_encoded = quote_plus(password)
            return f"postgresql+psycopg2://{user_encoded}:{pass_encoded}@{host}:{port}/{database}"

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

    def cancel_query(self):
        """Cancela a query em execucao.

        Funciona para SQL Server (pyodbc) e PostgreSQL (psycopg2).
        Para MySQL/MariaDB, interrompe via flag.
        """
        self._cancelled = True

        try:
            if self.db_type == "sqlserver":
                # pyodbc: cancel() e metodo do Cursor, nao da Connection
                cursor = self._active_cursor
                if cursor is not None:
                    cursor.cancel()
                    logger.info("Query SQL Server cancelada via cursor.cancel()")
                else:
                    logger.warning("Cancel solicitado mas cursor nao disponivel")
            elif self.db_type == "postgresql":
                # psycopg2: cancel() envia cancel request ao servidor
                raw_conn = self._active_raw_conn
                if raw_conn is not None and hasattr(raw_conn, "cancel"):
                    raw_conn.cancel()
                    logger.info("Query PostgreSQL cancelada via connection.cancel()")
            else:
                # MySQL/MariaDB: nao tem cancel nativo no driver,
                # mas a flag _cancelled ira interromper o processamento
                logger.info(f"Cancel solicitado para {self.db_type} (via flag)")
        except Exception as e:
            logger.warning(f"Erro ao cancelar query: {e}")

    def _execute_mssql_batch(self, query: str) -> pd.DataFrame:
        """Executa batch de comandos SQL Server e retorna último resultado"""
        import pyodbc

        self._cancelled = False
        last_error = None  # Declarar ANTES do try para ser acessível no finally
        cursor = None
        raw_conn = None

        try:
            # Usar raw connection do pyodbc para acessar nextset()
            raw_conn = self.engine.raw_connection()
            self._active_raw_conn = raw_conn  # Expor para cancelamento
            cursor = raw_conn.cursor()
            self._active_cursor = cursor  # Expor cursor para cancelamento

            # CRITICO: Garantir que esta conexao do pool esta no banco correto.
            # O pool do SQLAlchemy pode devolver qualquer conexao, e um comando
            # USE anterior pode ter sido executado em outra conexao do pool.
            current_db = self.connection_params.get("database", "")
            if current_db:
                try:
                    cursor.execute(f"USE [{current_db}]")
                    # Consumir possivel result set do USE
                    while cursor.nextset():
                        pass
                except Exception as e:
                    logger.warning(f"Falha ao definir banco [{current_db}]: {e}")

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
            self._active_raw_conn = None  # Limpar referencia
            self._active_cursor = None  # Limpar referencia cursor
            # Fechar cursor e conexao
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
