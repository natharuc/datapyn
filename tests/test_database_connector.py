"""
Testes do DatabaseConnector
"""

import pytest
from unittest.mock import MagicMock, call, patch
import pandas as pd


# Mock para pyodbc.drivers() - no CI Linux nao ha ODBC driver instalado
_MOCK_ODBC_DRIVERS = ["ODBC Driver 18 for SQL Server"]


class TestDatabaseConnectorConnectionString:
    """Testes de construção de string de conexão"""

    @patch("database.database_connector.pyodbc.drivers", return_value=_MOCK_ODBC_DRIVERS)
    def test_sqlserver_windows_auth_string(self, _mock_drivers):
        """Deve construir string SQL Server com Windows Auth"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, _ = connector._build_connection_string(
            db_type="sqlserver",
            host="localhost",
            port=1433,
            database="testdb",
            username="",
            password="",
            use_windows_auth=True,
        )

        assert "mssql+pyodbc" in result
        assert "odbc_connect" in result
        assert "SERVER=localhost" in result or "SERVER%3Dlocalhost" in result
        assert "Trusted_Connection" in result or "Trusted_Connection%3D" in result

    @patch("database.database_connector.pyodbc.drivers", return_value=_MOCK_ODBC_DRIVERS)
    def test_sqlserver_sql_auth_string(self, _mock_drivers):
        """Deve construir string SQL Server com SQL Auth"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, _ = connector._build_connection_string(
            db_type="sqlserver", host="localhost", port=1433, database="testdb", username="user", password="pass"
        )

        assert "mssql+pyodbc" in result
        assert "odbc_connect" in result
        # Verifica se contem UID e PWD (URL-encoded ou nao)
        assert "UID" in result or "UID%3D" in result

    def test_mysql_connection_string(self):
        """Deve construir string MySQL"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, _ = connector._build_connection_string(
            db_type="mysql", host="localhost", port=3306, database="testdb", username="user", password="pass"
        )

        assert "mysql+pymysql" in result
        assert "localhost" in result
        assert "charset=utf8mb4" in result

    def test_postgresql_connection_string(self):
        """Deve construir string PostgreSQL"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, _ = connector._build_connection_string(
            db_type="postgresql", host="localhost", port=5432, database="testdb", username="user", password="pass"
        )

        assert "postgresql+psycopg2" in result
        assert "localhost" in result

    def test_databricks_connection_string(self):
        """Deve construir string Databricks com token"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, connect_args = connector._build_connection_string(
            db_type="databricks",
            host="my-workspace.cloud.databricks.com",
            port=443,
            database="my_catalog",
            username="",
            password="dapi12345abcdef",
            http_path="/sql/1.0/warehouses/abc123",
        )

        assert "databricks://" in result
        assert "token:" in result
        assert "my-workspace.cloud.databricks.com" in result
        assert "http_path" in result
        assert "catalog=my_catalog" in result
        assert connect_args == {}  # PAT auth does not need extra connect_args

    def test_databricks_connection_string_without_http_path(self):
        """Deve construir string Databricks sem http_path"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, _ = connector._build_connection_string(
            db_type="databricks",
            host="my-workspace.cloud.databricks.com",
            port=443,
            database="",
            username="",
            password="dapi12345",
        )

        assert "databricks://" in result
        assert "token:" in result
        assert "http_path" not in result
    
    def test_databricks_oauth_connection_string(self):
        """Deve construir string Databricks com OAuth quando sem token"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, connect_args = connector._build_connection_string(
            db_type="databricks",
            host="my-workspace.cloud.databricks.com",
            port=443,
            database="my_catalog",
            username="",
            password="",  # Empty password triggers OAuth
            http_path="/sql/1.0/warehouses/abc123",
        )

        assert "databricks://" in result
        assert "token:" not in result  # No token in OAuth mode
        assert "auth_type" in connect_args
        assert connect_args["auth_type"] == "databricks-oauth"
        assert "experimental_oauth_persistence" in connect_args

    def test_unsupported_database_raises_error(self):
        """Banco nao suportado deve lancar erro"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()

        with pytest.raises(ValueError) as exc_info:
            connector._build_connection_string(
                db_type="oracle", host="localhost", port=1521, database="testdb", username="user", password="pass"
            )

        assert "Unsupported database type" in str(exc_info.value)

    @patch("database.database_connector.pyodbc.drivers", return_value=_MOCK_ODBC_DRIVERS)
    def test_sqlserver_localdb_connection_string(self, _mock_drivers):
        """Deve construir string LocalDB sem porta e com Windows Auth automatico"""
        from database.database_connector import DatabaseConnector
        from urllib.parse import unquote

        connector = DatabaseConnector()
        result, _ = connector._build_connection_string(
            db_type="sqlserver",
            host="(localdb)\\MSSQLLocalDB",
            port=1433,  # porta deve ser ignorada
            database="testdb",
            username="user",  # deve ser ignorado - LocalDB usa Windows Auth
            password="pass",
            use_windows_auth=False,  # deve ser forcado para True
        )

        decoded = unquote(result)
        assert "mssql+pyodbc" in result
        # LocalDB nao usa porta - formato SERVER=(localdb)\Instance
        assert "SERVER=(localdb)\\MSSQLLocalDB" in decoded
        assert ",1433" not in decoded  # porta NAO deve aparecer
        # LocalDB sempre usa Windows Auth
        assert "Trusted_Connection=yes" in decoded
        # Nao deve ter credenciais SQL Auth
        assert "UID=" not in decoded
        assert "PWD=" not in decoded

    @patch("database.database_connector.pyodbc.drivers", return_value=_MOCK_ODBC_DRIVERS)
    def test_sqlserver_standard_connection_still_uses_port(self, _mock_drivers):
        """Conexao SQL Server padrao deve continuar usando porta"""
        from database.database_connector import DatabaseConnector
        from urllib.parse import unquote

        connector = DatabaseConnector()
        result, _ = connector._build_connection_string(
            db_type="sqlserver",
            host="localhost",
            port=1433,
            database="testdb",
            username="user",
            password="pass",
            use_windows_auth=False,
        )

        decoded = unquote(result)
        assert "SERVER=localhost,1433" in decoded
        assert "UID=user" in decoded
        assert "PWD=pass" in decoded


class TestDatabaseConnectorState:
    """Testes de estado do conector"""

    def test_initial_state(self):
        """Estado inicial deve estar desconectado"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()

        assert connector.engine is None
        assert connector.db_type == ""
        assert not connector.is_connected()

    def test_supported_databases(self):
        """Deve ter bancos suportados definidos"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()

        assert "sqlserver" in connector.SUPPORTED_DATABASES
        assert "mysql" in connector.SUPPORTED_DATABASES
        assert "postgresql" in connector.SUPPORTED_DATABASES
        assert "databricks" in connector.SUPPORTED_DATABASES


class TestDatabaseConnectorMocked:
    """Testes com conexão mockada"""

    @patch("database.database_connector.create_engine")
    def test_connect_success(self, mock_create_engine):
        """Conexão bem sucedida deve retornar True"""
        from database.database_connector import DatabaseConnector

        # Setup mock
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__ = lambda s: mock_connection
        mock_engine.connect.return_value.__exit__ = lambda s, *args: None
        mock_create_engine.return_value = mock_engine

        connector = DatabaseConnector()
        result = connector.connect(
            db_type="mysql", host="localhost", port=3306, database="testdb", username="user", password="pass"
        )

        assert result is True
        assert connector.engine is not None
        assert connector.db_type == "mysql"

    @patch("database.database_connector.create_engine")
    def test_execute_query_returns_dataframe(self, mock_create_engine):
        """execute_query deve retornar DataFrame"""
        from database.database_connector import DatabaseConnector

        # Setup mock
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__ = lambda s: mock_connection
        mock_engine.connect.return_value.__exit__ = lambda s, *args: None
        mock_create_engine.return_value = mock_engine

        connector = DatabaseConnector()
        connector.connect("mysql", "localhost", 3306, "testdb", "user", "pass")

        # Mock pd.read_sql
        with patch("pandas.read_sql") as mock_read_sql:
            mock_read_sql.return_value = pd.DataFrame({"col": [1, 2, 3]})

            result = connector.execute_query("SELECT * FROM test")

            assert isinstance(result, pd.DataFrame)
            assert len(result) == 3


class TestDatabaseConnectorEdgeCases:
    """Testes de casos de borda"""

    def test_special_characters_in_password(self):
        """Senha com caracteres especiais"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, _ = connector._build_connection_string(
            db_type="mysql", host="localhost", port=3306, database="testdb", username="user", password="p@ss!w0rd#$%"
        )

        # Deve incluir a senha (URL-encoded)
        from urllib.parse import unquote
        assert "p@ss!w0rd#$%" in unquote(result)

    def test_custom_driver_sqlserver(self):
        """Driver customizado SQL Server"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, _ = connector._build_connection_string(
            db_type="sqlserver",
            host="localhost",
            port=1433,
            database="testdb",
            username="user",
            password="pass",
            driver="ODBC Driver 18 for SQL Server",
        )

        # Deve usar odbc_connect e conter o driver (URL-encoded)
        assert "odbc_connect" in result
        assert "ODBC" in result or "ODBC+Driver" in result


class TestUseDatabasePersistence:
    """Testes para garantir que USE <db> persiste entre execucoes"""

    def test_connection_params_updated_on_use(self):
        """USE deve atualizar connection_params['database']"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.connection_params = {"database": "gecon"}
        connector.db_type = "sqlserver"
        connector.engine = MagicMock()

        # Simular execucao de USE esim
        import re

        query = "USE esim"
        use_match = re.search(r"\bUSE\s+\[?(\w+)\]?\s*;?\s*$", query.strip(), re.IGNORECASE | re.MULTILINE)
        assert use_match is not None
        assert use_match.group(1) == "esim"

        # O execute_query deveria atualizar connection_params
        connector.connection_params["database"] = use_match.group(1)
        assert connector.connection_params["database"] == "esim"
        assert connector.get_current_database() == "esim"

    def test_use_with_brackets(self):
        """USE [esim] com colchetes deve funcionar"""
        import re

        query = "USE [esim]"
        use_match = re.search(r"\bUSE\s+\[?(\w+)\]?\s*;?\s*$", query.strip(), re.IGNORECASE | re.MULTILINE)
        assert use_match is not None
        assert use_match.group(1) == "esim"

    def test_use_with_semicolon(self):
        """USE esim; com ponto-e-virgula deve funcionar"""
        import re

        query = "USE esim;"
        use_match = re.search(r"\bUSE\s+\[?(\w+)\]?\s*;?\s*$", query.strip(), re.IGNORECASE | re.MULTILINE)
        assert use_match is not None
        assert use_match.group(1) == "esim"

    def test_mssql_batch_sends_use_before_query(self):
        """_execute_mssql_batches deve enviar USE antes da query"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "sqlserver"
        connector.connection_params = {"database": "esim"}

        # Criar mocks
        mock_cursor = MagicMock()
        mock_cursor.description = [("col1",), ("col2",)]
        mock_cursor.fetchall.return_value = [(1, "a")]
        mock_cursor.nextset.return_value = False

        mock_init_cursor = MagicMock()
        mock_init_cursor.nextset.return_value = False

        mock_raw_conn = MagicMock()
        mock_raw_conn.cursor.side_effect = [mock_init_cursor, mock_cursor]

        mock_engine = MagicMock()
        mock_engine.raw_connection.return_value = mock_raw_conn
        connector.engine = mock_engine

        connector._execute_mssql_batches(["SELECT 1"])

        # init_cursor deve ter executado USE [esim]
        mock_init_cursor.execute.assert_called_once_with("USE [esim]")
        # batch cursor deve ter executado a query
        mock_cursor.execute.assert_called_once_with("SELECT 1")

    @patch("database.database_connector.pyodbc.drivers", return_value=_MOCK_ODBC_DRIVERS)
    def test_checkout_event_registered_for_sqlserver(self, _mock_drivers):
        """Engine SQL Server deve registrar evento checkout no pool"""
        from database.database_connector import DatabaseConnector
        from sqlalchemy import event

        connector = DatabaseConnector()

        with patch("database.database_connector.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_engine.connect.return_value = mock_conn
            mock_create_engine.return_value = mock_engine

            with patch("database.database_connector.event") as mock_event:
                connector.connect("sqlserver", "localhost", 1433, "testdb", use_windows_auth=True)

                # Deve ter registrado evento "checkout" no pool
                mock_event.listens_for.assert_called_once_with(mock_engine, "checkout")


class TestSplitSqlBatches:
    """Testes para split de batches SQL no separador GO"""

    def _split(self, query):
        from database.database_connector import DatabaseConnector
        return DatabaseConnector._split_sql_batches(query)

    def test_single_batch_no_go(self):
        """Query sem GO deve retornar um unico batch"""
        result = self._split("SELECT 1")
        assert result == ["SELECT 1"]

    def test_two_batches_separated_by_go(self):
        """Duas queries separadas por GO"""
        sql = "SELECT 1\nGO\nSELECT 2"
        result = self._split(sql)
        assert len(result) == 2
        assert result[0] == "SELECT 1"
        assert result[1] == "SELECT 2"

    def test_go_case_insensitive(self):
        """GO deve ser case-insensitive"""
        sql = "SELECT 1\ngo\nSELECT 2\nGo\nSELECT 3"
        result = self._split(sql)
        assert len(result) == 3

    def test_go_with_leading_whitespace(self):
        """GO com espacos antes deve funcionar"""
        sql = "SELECT 1\n   GO\nSELECT 2"
        result = self._split(sql)
        assert len(result) == 2

    def test_go_with_trailing_whitespace(self):
        """GO com espacos depois deve funcionar"""
        sql = "SELECT 1\nGO   \nSELECT 2"
        result = self._split(sql)
        assert len(result) == 2

    def test_go_with_repeat_count(self):
        """GO N (repeat count) deve ser tratado como separador"""
        sql = "INSERT INTO t VALUES(1)\nGO 5\nSELECT 1"
        result = self._split(sql)
        assert len(result) == 2

    def test_go_does_not_match_inside_identifier(self):
        """GO dentro de palavras como ALGO, category nao deve separar"""
        sql = "SELECT ALGO FROM category WHERE gopher = 1"
        result = self._split(sql)
        assert len(result) == 1
        assert "ALGO" in result[0]
        assert "category" in result[0]
        assert "gopher" in result[0]

    def test_go_crlf_line_endings(self):
        """GO com line endings Windows (CRLF) deve funcionar"""
        sql = "SELECT 1\r\nGO\r\nSELECT 2"
        result = self._split(sql)
        assert len(result) == 2

    def test_empty_batches_filtered(self):
        """Batches vazios entre GOs consecutivos devem ser ignorados"""
        sql = "SELECT 1\nGO\n\nGO\nSELECT 2"
        result = self._split(sql)
        assert len(result) == 2

    def test_go_at_end_of_script(self):
        """GO no final do script nao deve gerar batch vazio"""
        sql = "SELECT 1\nGO"
        result = self._split(sql)
        assert len(result) == 1
        assert result[0] == "SELECT 1"

    def test_go_at_start_of_script(self):
        """GO no inicio do script nao deve gerar batch vazio"""
        sql = "GO\nSELECT 1"
        result = self._split(sql)
        assert len(result) == 1

    def test_complex_tsql_script(self):
        """Script T-SQL complexo com CREATE PROCEDURE entre GOs"""
        sql = (
            "USE Gecon;\n"
            "GO\n"
            "DECLARE @x INT = 1\n"
            "SELECT @x\n"
            "GO\n"
            "CREATE PROCEDURE #MyProc AS SELECT 1\n"
            "GO\n"
            "EXEC #MyProc\n"
            "GO\n"
        )
        result = self._split(sql)
        assert len(result) == 4
        assert "USE Gecon" in result[0]
        assert "DECLARE @x" in result[1]
        assert "CREATE PROCEDURE" in result[2]
        assert "EXEC #MyProc" in result[3]

    def test_go_not_in_string_literal(self):
        """GO sozinho na linha sempre separa (mesmo conceito do SSMS)"""
        # In SSMS, GO on its own line always separates regardless of context
        sql = "SELECT 'some text'\nGO\nSELECT 2"
        result = self._split(sql)
        assert len(result) == 2


class TestMssqlBatchesExecution:
    """Testes para execucao de multiplos batches SQL Server"""

    def test_multiple_batches_executed_sequentially(self):
        """Cada batch deve ser executado em sequencia na mesma conexao"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "sqlserver"
        connector.connection_params = {}

        mock_cursor1 = MagicMock()
        mock_cursor1.description = None
        mock_cursor1.nextset.return_value = False

        mock_cursor2 = MagicMock()
        mock_cursor2.description = [("col1",)]
        mock_cursor2.fetchall.return_value = [(42,)]
        mock_cursor2.nextset.return_value = False

        mock_raw_conn = MagicMock()
        mock_raw_conn.cursor.side_effect = [mock_cursor1, mock_cursor2]

        mock_engine = MagicMock()
        mock_engine.raw_connection.return_value = mock_raw_conn
        connector.engine = mock_engine

        result = connector._execute_mssql_batches(["CREATE TABLE #t (id INT)", "SELECT * FROM #t"])

        mock_cursor1.execute.assert_called_once_with("CREATE TABLE #t (id INT)")
        mock_cursor2.execute.assert_called_once_with("SELECT * FROM #t")

    def test_batch_error_continues_and_reports(self):
        """Erro num batch deve continuar executando os demais (como SSMS)"""
        import pyodbc
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "sqlserver"
        connector.connection_params = {}

        # First batch fails, second succeeds
        mock_cursor_bad = MagicMock()
        mock_cursor_bad.execute.side_effect = pyodbc.Error("42000", "Syntax error")

        mock_cursor_ok = MagicMock()
        mock_cursor_ok.description = [("col1",)]
        mock_cursor_ok.fetchall.return_value = [(1,)]
        mock_cursor_ok.nextset.return_value = False

        mock_raw_conn = MagicMock()
        mock_raw_conn.cursor.side_effect = [mock_cursor_bad, mock_cursor_ok]

        mock_engine = MagicMock()
        mock_engine.raw_connection.return_value = mock_raw_conn
        connector.engine = mock_engine

        # Should NOT raise - continues past the error
        result = connector._execute_mssql_batches(["BAD SQL", "SELECT 1"])
        # Second batch produced a result, plus error DataFrame appended
        assert isinstance(result, list)
        # At least one result DF and one error DF
        assert len(result) >= 2

    def test_all_batches_fail_raises_error(self):
        """Se todos os batches falharem, deve levantar excecao"""
        import pyodbc
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "sqlserver"
        connector.connection_params = {}

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = pyodbc.Error("42000", "Syntax error")

        mock_raw_conn = MagicMock()
        mock_raw_conn.cursor.return_value = mock_cursor

        mock_engine = MagicMock()
        mock_engine.raw_connection.return_value = mock_raw_conn
        connector.engine = mock_engine

        with pytest.raises(Exception, match="Batch 1/2"):
            connector._execute_mssql_batches(["BAD SQL", "ALSO BAD"])


class TestDatabricksOAuthRetry:
    """Testes para retry automatico quando OAuth token do Databricks expira"""

    @patch("database.database_connector._get_oauth_token_cache_path")
    @patch("database.database_connector.create_engine")
    def test_retry_on_expired_oauth_token(self, mock_create_engine, mock_cache_path):
        """Deve limpar cache e reconectar quando token OAuth expira"""
        from database.database_connector import DatabaseConnector

        # First engine raises KeyError('access_token') on connect,
        # second engine succeeds
        mock_conn_fail = MagicMock()
        mock_conn_fail.__enter__ = MagicMock(side_effect=KeyError("access_token"))
        mock_conn_fail.__exit__ = MagicMock(return_value=False)

        mock_conn_ok = MagicMock()
        mock_conn_ok.__enter__ = MagicMock(return_value=mock_conn_ok)
        mock_conn_ok.__exit__ = MagicMock(return_value=False)

        mock_engine_fail = MagicMock()
        mock_engine_fail.connect.return_value = mock_conn_fail

        mock_engine_ok = MagicMock()
        mock_engine_ok.connect.return_value = mock_conn_ok

        mock_create_engine.side_effect = [mock_engine_fail, mock_engine_ok]

        # Mock cache path that exists
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_cache_path.return_value = mock_path

        connector = DatabaseConnector()
        result = connector.connect(
            "databricks", "my-workspace.databricks.com", 443, "",
            username="", password="",
            http_path="/sql/1.0/warehouses/abc"
        )

        assert result is True
        # Cache file should have been deleted
        mock_path.unlink.assert_called_once()
        # Engine should have been created twice (original + retry)
        assert mock_create_engine.call_count == 2
        # First engine should have been disposed
        mock_engine_fail.dispose.assert_called_once()

    @patch("database.database_connector.create_engine")
    def test_non_databricks_keyerror_propagates(self, mock_create_engine):
        """KeyError que nao e de OAuth Databricks deve propagar normalmente"""
        from database.database_connector import DatabaseConnector

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(side_effect=KeyError("something_else"))
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        connector = DatabaseConnector()
        with pytest.raises(KeyError, match="something_else"):
            connector.connect(
                "databricks", "host.databricks.com", 443, "",
                username="", password="",
                http_path="/sql/1.0/warehouses/abc"
            )

    @patch("database.database_connector._get_oauth_token_cache_path")
    @patch("database.database_connector.create_engine")
    def test_retry_works_even_without_cache_file(self, mock_create_engine, mock_cache_path):
        """Retry deve funcionar mesmo se arquivo de cache nao existir"""
        from database.database_connector import DatabaseConnector

        mock_conn_fail = MagicMock()
        mock_conn_fail.__enter__ = MagicMock(side_effect=KeyError("access_token"))
        mock_conn_fail.__exit__ = MagicMock(return_value=False)

        mock_conn_ok = MagicMock()
        mock_conn_ok.__enter__ = MagicMock(return_value=mock_conn_ok)
        mock_conn_ok.__exit__ = MagicMock(return_value=False)

        mock_engine_fail = MagicMock()
        mock_engine_fail.connect.return_value = mock_conn_fail

        mock_engine_ok = MagicMock()
        mock_engine_ok.connect.return_value = mock_conn_ok

        mock_create_engine.side_effect = [mock_engine_fail, mock_engine_ok]

        # Cache file does NOT exist
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_cache_path.return_value = mock_path

        connector = DatabaseConnector()
        result = connector.connect(
            "databricks", "my-workspace.databricks.com", 443, "",
            username="", password="",
            http_path="/sql/1.0/warehouses/abc"
        )

        assert result is True
        mock_path.unlink.assert_not_called()
