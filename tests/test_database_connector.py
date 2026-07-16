"""
Testes do DatabaseConnector
"""

import pytest
from unittest.mock import MagicMock, call, patch
import pandas as pd
from urllib.parse import unquote
import sys
import types


# Mock para pyodbc.drivers() - no CI Linux nao ha ODBC driver instalado
_MOCK_ODBC_DRIVERS = ["ODBC Driver 18 for SQL Server"]


def _set_result_rows(mock, rows):
    """Configure a mock cursor/result for the production fetch contract.

    Production fetches rows via ``fetch_rows_chunked`` (cursor.fetchmany in a
    loop until empty), not ``fetchall``. A MagicMock only given ``fetchall``
    returns a truthy MagicMock from ``fetchmany`` forever → infinite loop.
    Configure ``fetchmany`` to yield the rows once then drain.
    """
    rows = list(rows)
    mock.fetchall.return_value = rows
    chunks = iter([rows])
    mock.fetchmany.side_effect = lambda *_a, **_k: next(chunks, [])


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
        result, connect_args = connector._build_connection_string(
            db_type="postgresql", host="localhost", port=5432, database="testdb", username="user", password="pass"
        )

        assert "postgresql+psycopg2" in result
        assert "localhost" in result
        assert "client_encoding" not in result
        assert connect_args == {}

    def test_postgresql_connection_string_accepts_encoding_fallback(self):
        """Fallback de encoding deve ir em connect_args, nao na URL."""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, connect_args = connector._build_connection_string(
            db_type="postgresql",
            host="localhost",
            port=5432,
            database="testdb",
            username="user",
            password="pass",
            postgresql_client_encoding="WIN1252",
        )

        assert "postgresql+psycopg2" in result
        assert "client_encoding" not in result
        assert connect_args == {"client_encoding": "WIN1252"}

    def test_postgresql_undefined_table_mixed_case_gets_identifier_hint(self):
        """Erro de tabela inexistente com CamelCase deve explicar aspas no PostgreSQL."""
        from database.database_connector import _format_sql_error_for_user

        error = RuntimeError('(psycopg2.errors.UndefinedTable) ERRO:  relação "xmlpackages" não existe')

        message = _format_sql_error_for_user(error, "postgresql", "SELECT * FROM XmlPackages")

        assert "xmlpackages" in message
        assert "XmlPackages" in message
        assert 'public."XmlPackages"' in message

    def test_postgresql_undefined_table_lowercase_does_not_get_case_hint(self):
        """Tabela lowercase ausente nao deve sugerir problema de CamelCase."""
        from database.database_connector import _format_sql_error_for_user

        error = RuntimeError('relation "xmlpackages" does not exist')

        message = _format_sql_error_for_user(error, "postgresql", "SELECT * FROM xmlpackages")

        assert message == 'relation "xmlpackages" does not exist'

    def test_non_postgresql_undefined_table_does_not_get_postgres_hint(self):
        """Hints de case-sensitive sao especificos do PostgreSQL."""
        from database.database_connector import _format_sql_error_for_user

        error = RuntimeError('relation "xmlpackages" does not exist')

        message = _format_sql_error_for_user(error, "mysql", "SELECT * FROM XmlPackages")

        assert message == 'relation "xmlpackages" does not exist'

    def test_connect_postgresql_retries_with_win1252_after_utf8_decode_error(self):
        """Falha de decode no startup do PostgreSQL deve tentar encoding Windows comum."""
        from database.database_connector import DatabaseConnector

        first_engine = MagicMock()
        first_conn = MagicMock()
        first_conn.__enter__ = MagicMock(side_effect=UnicodeDecodeError("utf-8", b"conex\xe7ao", 5, 6, "invalid continuation byte"))
        first_conn.__exit__ = MagicMock(return_value=False)
        first_engine.connect.return_value = first_conn

        retry_engine = MagicMock()
        retry_conn = MagicMock()
        retry_conn.__enter__ = MagicMock(return_value=retry_conn)
        retry_conn.__exit__ = MagicMock(return_value=False)
        retry_engine.connect.return_value = retry_conn

        with patch("database.database_connector.create_engine", side_effect=[first_engine, retry_engine]) as mock_create_engine:
            connector = DatabaseConnector()
            connected = connector.connect("postgresql", "localhost", 5432, "testdb", "user", "pass")

        assert connected is True
        assert connector.engine is retry_engine
        assert mock_create_engine.call_args_list[1].kwargs["connect_args"] == {"client_encoding": "WIN1252"}
        assert connector._connection_config["postgresql_client_encoding"] == "WIN1252"

    def test_connect_postgresql_decode_retry_preserves_readable_fallback_error(self):
        """Se o retry revelar erro real, ele deve ser propagado em vez do codec cru."""
        from database.database_connector import DatabaseConnector

        first_engine = MagicMock()
        first_conn = MagicMock()
        first_conn.__enter__ = MagicMock(side_effect=UnicodeDecodeError("utf-8", b"conex\xe7ao", 5, 6, "invalid continuation byte"))
        first_conn.__exit__ = MagicMock(return_value=False)
        first_engine.connect.return_value = first_conn

        retry_engine = MagicMock()
        retry_conn = MagicMock()
        retry_conn.__enter__ = MagicMock(side_effect=RuntimeError("database docfis does not exist"))
        retry_conn.__exit__ = MagicMock(return_value=False)
        retry_engine.connect.return_value = retry_conn

        with patch("database.database_connector.create_engine", side_effect=[first_engine, retry_engine]):
            connector = DatabaseConnector()
            with pytest.raises(RuntimeError, match="database docfis does not exist"):
                connector.connect("postgresql", "localhost", 5432, "docfis", "user", "pass")

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

    @patch("database.database_connector.pyodbc.drivers", return_value=_MOCK_ODBC_DRIVERS)
    def test_sqlserver_mfa_connection_string_uses_interactive_auth(self, _mock_drivers):
        """Conexao SQL Server com MFA deve usar token Entra no lugar do auth do driver."""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, _ = connector._build_connection_string(
            db_type="sqlserver",
            host="azure-sql.database.windows.net",
            port=1433,
            database="testdb",
            username="user@tenant.com",
            password="ignored",
            sqlserver_auth_mode="entra_mfa",
        )

        decoded = unquote(result)
        assert "SERVER=azure-sql.database.windows.net,1433" in decoded
        assert "Encrypt=yes" in decoded
        assert "Authentication=ActiveDirectoryInteractive" not in decoded
        assert "UID=" not in decoded
        assert "PWD=" not in decoded
        assert "Trusted_Connection=yes" not in decoded

    @patch("database.database_connector.pyodbc.drivers", return_value=_MOCK_ODBC_DRIVERS)
    def test_sqlserver_mfa_without_username_builds_connection_string(self, _mock_drivers):
        """MFA deve permitir omitir username e usar a tela Microsoft para escolher a conta."""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, _ = connector._build_connection_string(
            db_type="sqlserver",
            host="azure-sql.database.windows.net",
            port=1433,
            database="testdb",
            username="",
            password="",
            sqlserver_auth_mode="mfa",
        )

        decoded = unquote(result)
        assert "Encrypt=yes" in decoded
        assert "UID=" not in decoded
        assert "Authentication=" not in decoded

    def test_sqlserver_access_token_struct_uses_utf16le(self):
        """Struct de access token deve seguir o formato esperado pelo ODBC."""
        from database.database_connector import _build_sqlserver_access_token_struct

        packed = _build_sqlserver_access_token_struct("abc")
        expected_payload = "abc".encode("utf-16-le")

        assert packed[:4] == len(expected_payload).to_bytes(4, "little")
        assert packed[4:] == expected_payload

    @patch("database.database_connector.pyodbc.drivers", return_value=_MOCK_ODBC_DRIVERS)
    def test_connect_sqlserver_mfa_registers_access_token_handler(self, _mock_drivers):
        """Conexao MFA deve injetar access token via do_connect do SQLAlchemy."""
        from database.database_connector import (
            DatabaseConnector,
            SQLSERVER_ENTRA_SCOPE,
            SQL_COPT_SS_ACCESS_TOKEN,
            _build_sqlserver_access_token_struct,
        )

        connector = DatabaseConnector()
        mock_credential = MagicMock()
        mock_credential.get_token.return_value = type("Token", (), {"token": "token-123"})()
        listeners = {}

        def fake_listens_for(target, name):
            def decorator(fn):
                listeners[name] = fn
                return fn
            return decorator

        with patch("database.database_connector._create_sqlserver_mfa_credential", return_value=mock_credential):
            with patch("database.database_connector.create_engine") as mock_create_engine:
                with patch("database.database_connector.event.listens_for", side_effect=fake_listens_for):
                    mock_engine = MagicMock()
                    mock_conn = MagicMock()
                    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
                    mock_conn.__exit__ = MagicMock(return_value=False)
                    mock_engine.connect.return_value = mock_conn
                    mock_create_engine.return_value = mock_engine

                    connector.connect(
                        "sqlserver",
                        "azure-sql.database.windows.net",
                        1433,
                        "testdb",
                        username="",
                        password="",
                        sqlserver_auth_mode="entra_mfa",
                    )

        assert "do_connect" in listeners
        cparams = {}
        listeners["do_connect"](None, None, [], cparams)
        mock_credential.get_token.assert_called_once_with(SQLSERVER_ENTRA_SCOPE)
        assert cparams["attrs_before"][SQL_COPT_SS_ACCESS_TOKEN] == _build_sqlserver_access_token_struct("token-123")

    def test_prepare_sqlserver_mfa_credential_persists_auth_record(self, tmp_path):
        """Primeira autenticacao MFA deve persistir AuthenticationRecord para reuse silencioso."""
        from database.database_connector import _prepare_sqlserver_mfa_credential, SQLSERVER_ENTRA_SCOPE

        first_credential = MagicMock()
        first_record = MagicMock()
        persisted_credential = MagicMock()

        with patch("database.database_connector._read_sqlserver_auth_record", return_value=None):
            with patch("database.database_connector._write_sqlserver_auth_record") as mock_write:
                with patch(
                    "database.database_connector._create_sqlserver_mfa_credential",
                    side_effect=[first_credential, persisted_credential],
                ):
                    first_credential.authenticate.return_value = first_record
                    result = _prepare_sqlserver_mfa_credential("azure-sql.database.windows.net")

        first_credential.authenticate.assert_called_once_with(scopes=[SQLSERVER_ENTRA_SCOPE])
        mock_write.assert_called_once_with("azure-sql.database.windows.net", first_record)
        first_credential.close.assert_called_once()
        assert result is persisted_credential

    def test_read_sqlserver_auth_record_deserializes_file(self, tmp_path):
        """AuthenticationRecord persistido deve ser carregado do disco."""
        from database.database_connector import _read_sqlserver_auth_record

        auth_record_path = tmp_path / "record.json"
        auth_record_path.write_text("serialized-record", encoding="utf-8")

        fake_authentication_record = MagicMock()
        fake_authentication_record.deserialize.return_value = "record"
        fake_identity_module = types.SimpleNamespace(AuthenticationRecord=fake_authentication_record)

        with patch("database.database_connector._get_sqlserver_auth_record_path", return_value=auth_record_path):
            with patch.dict(sys.modules, {"azure.identity": fake_identity_module}):
                result = _read_sqlserver_auth_record("azure-sql.database.windows.net")

        fake_authentication_record.deserialize.assert_called_once_with("serialized-record")
        assert result == "record"

    def test_azure_sql_change_database_reconnects(self):
        """Azure SQL Database deve reconectar em vez de emitir USE."""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "sqlserver"
        connector.engine = MagicMock()
        connector.connection_params = {
            "host": "tenant.database.windows.net",
            "port": 1433,
            "database": "db1",
            "sqlserver_supports_use": False,
        }
        connector._connection_config = {
            "db_type": "sqlserver",
            "host": "tenant.database.windows.net",
            "port": 1433,
            "database": "db1",
            "username": "",
            "password": "",
            "sqlserver_auth_mode": "entra_mfa",
        }

        with patch.object(connector, "connect", return_value=True) as mock_connect:
            with patch.object(connector, "disconnect") as mock_disconnect:
                assert connector.change_database("db2") is True

        mock_disconnect.assert_called_once()
        mock_connect.assert_called_once_with(
            "sqlserver",
            "tenant.database.windows.net",
            1433,
            "db2",
            "",
            "",
            sqlserver_auth_mode="entra_mfa",
        )

    def test_execute_query_use_on_azure_sql_reconnects(self):
        """USE isolado em Azure SQL deve virar troca de conexao, sem erro 40508."""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "sqlserver"
        connector.engine = MagicMock()
        connector.connection_params = {
            "host": "tenant.database.windows.net",
            "port": 1433,
            "database": "db1",
            "sqlserver_supports_use": False,
        }

        with patch.object(connector, "change_database", return_value=True) as mock_change:
            result = connector.execute_query("USE [db2]")

        mock_change.assert_called_once_with("db2")
        assert result.iloc[0, 0] == "Database changed to: db2"

    def test_azure_sql_batches_skip_init_use(self):
        """Azure SQL batches nao devem executar USE inicial na raw connection."""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "sqlserver"
        connector.connection_params = {"database": "db1", "sqlserver_supports_use": False}

        mock_cursor = MagicMock()
        mock_cursor.description = [(
            "col1",
        )]
        _set_result_rows(mock_cursor, [(1,)])
        mock_cursor.nextset.return_value = False

        mock_raw_conn = MagicMock()
        mock_raw_conn.cursor.return_value = mock_cursor

        mock_engine = MagicMock()
        mock_engine.raw_connection.return_value = mock_raw_conn
        connector.engine = mock_engine

        result = connector._execute_mssql_batches(["SELECT 1"])

        mock_cursor.execute.assert_called_once_with("SELECT 1")
        assert result.iloc[0, 0] == 1

    @patch("database.database_connector.pyodbc.drivers", return_value=_MOCK_ODBC_DRIVERS)
    def test_sqlserver_legacy_windows_flag_keeps_backward_compatibility(self, _mock_drivers):
        """Flag antiga de Windows Auth deve continuar funcionando sem auth_mode salvo."""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result, _ = connector._build_connection_string(
            db_type="sqlserver",
            host="localhost",
            port=1433,
            database="testdb",
            username="legacy-user",
            password="legacy-pass",
            use_windows_auth=True,
        )

        decoded = unquote(result)
        assert "Trusted_Connection=yes" in decoded
        assert "Authentication=ActiveDirectoryInteractive" not in decoded
        assert "UID=" not in decoded


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

    def test_execute_query_returns_dataframe(self):
        """execute_query deve retornar DataFrame preservando strings numericas."""
        from database.database_connector import DatabaseConnector

        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__ = lambda s: mock_connection
        mock_engine.connect.return_value.__exit__ = lambda s, *args: None

        connector = DatabaseConnector()
        connector.engine = mock_engine
        connector.db_type = "mysql"

        mock_result = MagicMock()
        mock_result.keys.return_value = ["col"]
        _set_result_rows(mock_result, [("001",), ("002",), ("003",)])
        mock_connection.execute.return_value = mock_result

        result = connector.execute_query("SELECT * FROM test")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert result["col"].tolist() == ["001", "002", "003"]
        assert all(isinstance(value, str) for value in result["col"])

    def test_execute_query_preserves_text_columns_with_nulls(self):
        """SELECT generico nao deve converter texto numerico em inteiro mesmo com NULL."""
        from database.database_connector import DatabaseConnector

        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__ = lambda s: mock_connection
        mock_engine.connect.return_value.__exit__ = lambda s, *args: None

        connector = DatabaseConnector()
        connector.engine = mock_engine
        connector.db_type = "postgresql"

        mock_result = MagicMock()
        mock_result.keys.return_value = ["external_id"]
        _set_result_rows(mock_result, [("123",), (None,), ("045",)])
        mock_connection.execute.return_value = mock_result

        result = connector.execute_query("SELECT external_id FROM customer")

        assert result["external_id"].iloc[0] == "123"
        assert pd.isna(result["external_id"].iloc[1])
        assert result["external_id"].iloc[2] == "045"
        assert all(isinstance(value, str) for value in result["external_id"].dropna())

    def test_execute_query_multiple_selects_preserve_driver_values(self):
        """Multiplos SELECTs devem retornar DataFrames sem passar por inferencia do pandas.read_sql."""
        from database.database_connector import DatabaseConnector

        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__ = lambda s: mock_connection
        mock_engine.connect.return_value.__exit__ = lambda s, *args: None

        connector = DatabaseConnector()
        connector.engine = mock_engine
        connector.db_type = "mariadb"

        first_result = MagicMock()
        first_result.keys.return_value = ["code"]
        _set_result_rows(first_result, [("0007",)])

        second_result = MagicMock()
        second_result.keys.return_value = ["reference"]
        _set_result_rows(second_result, [("9001",)])

        mock_connection.execute.side_effect = [first_result, second_result]

        result = connector.execute_query("SELECT code FROM first_table; SELECT reference FROM second_table;")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["code"].tolist() == ["0007"]
        assert result[1]["reference"].tolist() == ["9001"]
        assert all(isinstance(value, str) for value in result[0]["code"])
        assert all(isinstance(value, str) for value in result[1]["reference"])

    def test_postgresql_create_database_runs_with_autocommit(self):
        """CREATE DATABASE no PostgreSQL deve executar fora de bloco de transacao."""
        from database.database_connector import DatabaseConnector

        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_autocommit_connection = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = -1
        mock_autocommit_connection.execute.return_value = mock_result
        mock_connection.execution_options.return_value = mock_autocommit_connection
        mock_engine.connect.return_value.__enter__ = lambda s: mock_connection
        mock_engine.connect.return_value.__exit__ = lambda s, *args: None

        connector = DatabaseConnector()
        connector.engine = mock_engine
        connector.db_type = "postgresql"

        result = connector.execute_query("CREATE DATABASE docfis")

        mock_connection.execution_options.assert_called_once_with(isolation_level="AUTOCOMMIT")
        mock_autocommit_connection.execute.assert_called_once()
        mock_connection.commit.assert_not_called()
        assert result["Result"].iloc[0] == "Command executed successfully."

    def test_postgresql_create_database_detection_ignores_leading_comments(self):
        """Comentarios antes do CREATE DATABASE nao devem impedir autocommit."""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "postgresql"

        assert connector._requires_postgresql_autocommit("-- criar banco\nCREATE DATABASE docfis") is True
        assert connector._requires_postgresql_autocommit("/* criar banco */\nCREATE DATABASE docfis") is True
        assert connector._requires_postgresql_autocommit("-- etapa 1\n  /* etapa 2 */\nCREATE DATABASE docfis") is True

    def test_postgresql_regular_statement_keeps_transaction_commit(self):
        """DML comum continua usando transacao normal."""
        from database.database_connector import DatabaseConnector

        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_connection.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__ = lambda s: mock_connection
        mock_engine.connect.return_value.__exit__ = lambda s, *args: None

        connector = DatabaseConnector()
        connector.engine = mock_engine
        connector.db_type = "postgresql"

        result = connector.execute_query("UPDATE customer SET active = true")

        mock_connection.execution_options.assert_not_called()
        mock_connection.commit.assert_called_once()
        assert result["Result"].iloc[0] == "Command executed successfully. 1 row(s) affected."


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
        _set_result_rows(mock_cursor, [(1, "a")])
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
        _set_result_rows(mock_cursor2, [(42,)])
        mock_cursor2.nextset.return_value = False

        mock_raw_conn = MagicMock()
        mock_raw_conn.cursor.side_effect = [mock_cursor1, mock_cursor2]

        mock_engine = MagicMock()
        mock_engine.raw_connection.return_value = mock_raw_conn
        connector.engine = mock_engine

        result = connector._execute_mssql_batches(["CREATE TABLE #t (id INT)", "SELECT * FROM #t"])

        mock_cursor1.execute.assert_called_once_with("CREATE TABLE #t (id INT)")
        mock_cursor2.execute.assert_called_once_with("SELECT * FROM #t")


class TestSplitSqlStatements:
    """Tests for _split_sql_statements - DELIMITER-aware SQL splitting"""

    def _split(self, query):
        from database.database_connector import DatabaseConnector
        return DatabaseConnector._split_sql_statements(query)

    # --- Basic splitting on semicolon ---

    def test_single_statement_no_semicolon(self):
        """Single statement without trailing semicolon"""
        result = self._split("SELECT 1")
        assert result == ["SELECT 1"]

    def test_single_statement_with_semicolon(self):
        """Single statement with trailing semicolon"""
        result = self._split("SELECT 1;")
        assert result == ["SELECT 1"]

    def test_multiple_statements(self):
        """Multiple statements separated by semicolons"""
        result = self._split("SELECT 1; SELECT 2; SELECT 3;")
        assert result == ["SELECT 1", "SELECT 2", "SELECT 3"]

    def test_empty_input(self):
        """Empty string returns empty list"""
        result = self._split("")
        assert result == []

    def test_whitespace_only(self):
        """Whitespace-only input returns empty list"""
        result = self._split("   \n\n  ")
        assert result == []

    # --- DELIMITER support ---

    def test_delimiter_create_function(self):
        """MySQL CREATE FUNCTION with DELIMITER $$ should be one statement"""
        query = """DELIMITER $$

CREATE FUNCTION SENHA_HASH(p_senha VARCHAR(255))
RETURNS CHAR(41)
DETERMINISTIC
BEGIN
    RETURN CONCAT(
        '*',
        UPPER(
            SHA1(
                UNHEX(
                    SHA1(p_senha)
                )
            )
        )
    );
END$$

DELIMITER ;"""
        result = self._split(query)
        assert len(result) == 1
        assert result[0].startswith("CREATE FUNCTION")
        assert "END" in result[0]
        # Semicolons inside the body must NOT split the statement
        assert "SHA1(p_senha)" in result[0]

    def test_delimiter_create_procedure(self):
        """MySQL CREATE PROCEDURE with DELIMITER // should be one statement"""
        query = """DELIMITER //

CREATE PROCEDURE sp_test(IN p_id INT)
BEGIN
    DECLARE v_name VARCHAR(100);
    SELECT name INTO v_name FROM users WHERE id = p_id;
    SELECT v_name;
END//

DELIMITER ;"""
        result = self._split(query)
        assert len(result) == 1
        assert "CREATE PROCEDURE" in result[0]
        assert "DECLARE v_name" in result[0]

    def test_delimiter_with_statements_before_and_after(self):
        """DELIMITER block with regular statements before and after"""
        query = """DROP FUNCTION IF EXISTS my_func;

DELIMITER $$

CREATE FUNCTION my_func(x INT) RETURNS INT
DETERMINISTIC
BEGIN
    RETURN x * 2;
END$$

DELIMITER ;

SELECT my_func(5);"""
        result = self._split(query)
        assert len(result) == 3
        assert result[0] == "DROP FUNCTION IF EXISTS my_func"
        assert result[1].startswith("CREATE FUNCTION")
        assert result[2] == "SELECT my_func(5)"

    def test_delimiter_multiple_routines(self):
        """Multiple routines in one script with same DELIMITER block"""
        query = """DELIMITER $$

CREATE FUNCTION f1() RETURNS INT
DETERMINISTIC
BEGIN
    RETURN 1;
END$$

CREATE FUNCTION f2() RETURNS INT
DETERMINISTIC
BEGIN
    RETURN 2;
END$$

DELIMITER ;"""
        result = self._split(query)
        assert len(result) == 2
        assert "f1" in result[0]
        assert "f2" in result[1]

    def test_delimiter_case_insensitive(self):
        """DELIMITER directive should be case-insensitive"""
        query = """delimiter $$
CREATE FUNCTION f() RETURNS INT
BEGIN
    RETURN 1;
END$$
delimiter ;"""
        result = self._split(query)
        assert len(result) == 1
        assert "CREATE FUNCTION" in result[0]

    # --- String literals ---

    def test_semicolon_inside_string_literal(self):
        """Semicolons inside string literals should not split"""
        result = self._split("SELECT 'hello; world';")
        assert len(result) == 1
        assert "'hello; world'" in result[0]

    def test_semicolon_inside_double_quoted_string(self):
        """Semicolons inside double-quoted strings should not split"""
        result = self._split('SELECT "val;ue";')
        assert len(result) == 1
        assert '"val;ue"' in result[0]

    def test_escaped_quotes_in_string(self):
        """Escaped quotes inside strings should be handled"""
        result = self._split("SELECT 'it''s a test; really';")
        assert len(result) == 1
        assert "'it''s a test; really'" in result[0]

    # --- Comments ---

    def test_semicolon_in_line_comment(self):
        """Semicolons in -- comments should not split"""
        result = self._split("-- this is a comment; not a split\nSELECT 1;")
        assert len(result) == 1
        assert "SELECT 1" in result[0]

    def test_semicolon_in_block_comment(self):
        """Semicolons in /* */ comments should not split"""
        result = self._split("/* comment; here */\nSELECT 1;")
        assert len(result) == 1
        assert "SELECT 1" in result[0]

    def test_hash_comment_mysql(self):
        """MySQL # comments should be handled"""
        result = self._split("# comment; here\nSELECT 1;")
        assert len(result) == 1
        assert "SELECT 1" in result[0]

    # --- Edge cases ---

    def test_delimiter_pipe_pipe(self):
        """DELIMITER with || as delimiter"""
        query = """DELIMITER ||
CREATE TRIGGER t1 BEFORE INSERT ON tbl
FOR EACH ROW
BEGIN
    SET NEW.created = NOW();
END||
DELIMITER ;"""
        result = self._split(query)
        assert len(result) == 1
        assert "CREATE TRIGGER" in result[0]

    def test_no_trailing_delimiter_semicolon(self):
        """Script without final DELIMITER ; should still work"""
        query = """DELIMITER $$
CREATE FUNCTION f() RETURNS INT
BEGIN
    RETURN 1;
END$$"""
        result = self._split(query)
        assert len(result) == 1
        assert "CREATE FUNCTION" in result[0]

    def test_regular_multiline_query(self):
        """Regular multi-line query without DELIMITER should work normally"""
        query = """CREATE TABLE users (
    id INT PRIMARY KEY,
    name VARCHAR(100)
);

INSERT INTO users VALUES (1, 'test');"""
        result = self._split(query)
        assert len(result) == 2
        assert "CREATE TABLE" in result[0]
        assert "INSERT INTO" in result[1]

    def test_delimiter_with_trailing_semicolon(self):
        """DELIMITER $$; (user typo with semicolon) should still work"""
        query = "DELIMITER $$;\n\nCREATE FUNCTION f() RETURNS INT\nBEGIN\n    RETURN 1;\nEND$$\n\nDELIMITER ;"
        result = self._split(query)
        assert len(result) == 1
        assert result[0].startswith("CREATE FUNCTION")
        assert "END" in result[0]
        # DELIMITER directive must NOT appear in the output
        assert "DELIMITER" not in result[0]

    def test_delimiter_with_trailing_semicolon_crlf(self):
        """DELIMITER $$; with Windows \\r\\n line endings"""
        query = "DELIMITER $$;\r\n\r\nCREATE FUNCTION SENHA_HASH(p_senha VARCHAR(255))\r\nRETURNS CHAR(41)\r\nDETERMINISTIC\r\nBEGIN\r\n    RETURN CONCAT(\r\n        '*',\r\n        UPPER(\r\n            SHA1(\r\n                UNHEX(\r\n                    SHA1(p_senha)\r\n                )\r\n            )\r\n        )\r\n    );\r\nEND$$\r\n\r\nDELIMITER ;"
        result = self._split(query)
        assert len(result) == 1
        assert "CREATE FUNCTION SENHA_HASH" in result[0]
        assert "DELIMITER" not in result[0]
        assert "SHA1(p_senha)" in result[0]

    def test_only_delimiter_directives_returns_empty(self):
        """Only DELIMITER directives with no actual SQL returns empty list"""
        query = "DELIMITER $$\nDELIMITER ;"
        result = self._split(query)
        assert result == []


class TestMssqlBatchErrorHandling:
    """Tests for MSSQL batch error handling"""

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
        _set_result_rows(mock_cursor_ok, [(1,)])
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


class TestMssqlEmptyResultSet:
    """Empty result sets must produce a columns-only DataFrame, not a message row."""

    def test_zero_row_select_returns_columns_only(self):
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "sqlserver"
        connector.connection_params = {}

        mock_cursor = MagicMock()
        mock_cursor.description = [("id",), ("name",)]
        _set_result_rows(mock_cursor, [])  # 0 rows
        mock_cursor.nextset.return_value = False

        mock_raw_conn = MagicMock()
        mock_raw_conn.cursor.return_value = mock_cursor

        mock_engine = MagicMock()
        mock_engine.raw_connection.return_value = mock_raw_conn
        connector.engine = mock_engine

        result = connector._execute_mssql_batches(["SELECT * FROM t WHERE 1=0"])

        # Columns preserved, zero rows — NOT the {"Result": [...]} message frame.
        assert list(result.columns) == ["id", "name"]
        assert len(result) == 0
        assert "Result" not in result.columns

    def test_ddl_only_returns_success_message(self):
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "sqlserver"
        connector.connection_params = {}

        mock_cursor = MagicMock()
        mock_cursor.description = None  # no result set (DDL)
        mock_cursor.nextset.return_value = False

        mock_raw_conn = MagicMock()
        mock_raw_conn.cursor.return_value = mock_cursor

        mock_engine = MagicMock()
        mock_engine.raw_connection.return_value = mock_raw_conn
        connector.engine = mock_engine

        result = connector._execute_mssql_batches(["CREATE TABLE t (id INT)"])

        assert "Result" in result.columns
        assert len(result) == 1


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


class TestSqlAlchemyEnginePool:
  def test_build_engine_kwargs_on_prem_sqlserver_uses_recycle_not_pre_ping(self):
      from database.database_connector import build_sqlalchemy_engine_kwargs

      kwargs = build_sqlalchemy_engine_kwargs("sqlserver", "sql01.corp.local")
      assert kwargs["pool_recycle"] == 300
      assert kwargs["pool_size"] == 2
      assert "pool_pre_ping" not in kwargs

  def test_build_engine_kwargs_azure_sql_enables_pre_ping(self):
      from database.database_connector import build_sqlalchemy_engine_kwargs

      kwargs = build_sqlalchemy_engine_kwargs(
          "sqlserver", "myserver.database.windows.net"
      )
      assert kwargs["pool_pre_ping"] is True

