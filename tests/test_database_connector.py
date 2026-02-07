"""
Testes do DatabaseConnector
"""

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd


class TestDatabaseConnectorConnectionString:
    """Testes de construção de string de conexão"""

    def test_sqlserver_windows_auth_string(self):
        """Deve construir string SQL Server com Windows Auth"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result = connector._build_connection_string(
            db_type="sqlserver",
            host="localhost",
            port=1433,
            database="testdb",
            username="",
            password="",
            use_windows_auth=True,
        )

        assert "mssql+pyodbc" in result
        assert "localhost" in result
        assert "testdb" in result
        assert "Trusted_Connection=yes" in result

    def test_sqlserver_sql_auth_string(self):
        """Deve construir string SQL Server com SQL Auth"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result = connector._build_connection_string(
            db_type="sqlserver", host="localhost", port=1433, database="testdb", username="user", password="pass"
        )

        assert "mssql+pyodbc" in result
        assert "user:pass" in result
        assert "localhost" in result

    def test_mysql_connection_string(self):
        """Deve construir string MySQL"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result = connector._build_connection_string(
            db_type="mysql", host="localhost", port=3306, database="testdb", username="user", password="pass"
        )

        assert "mysql+pymysql" in result
        assert "localhost" in result
        assert "charset=utf8mb4" in result

    def test_postgresql_connection_string(self):
        """Deve construir string PostgreSQL"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result = connector._build_connection_string(
            db_type="postgresql", host="localhost", port=5432, database="testdb", username="user", password="pass"
        )

        assert "postgresql+psycopg2" in result
        assert "localhost" in result

    def test_unsupported_database_raises_error(self):
        """Banco não suportado deve lançar erro"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()

        with pytest.raises(ValueError) as exc_info:
            connector._build_connection_string(
                db_type="oracle", host="localhost", port=1521, database="testdb", username="user", password="pass"
            )

        assert "não suportado" in str(exc_info.value)


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
        result = connector._build_connection_string(
            db_type="mysql", host="localhost", port=3306, database="testdb", username="user", password="p@ss!w0rd#$%"
        )

        # Deve incluir a senha (pode precisar de encoding em casos reais)
        assert "p@ss!w0rd#$%" in result

    def test_custom_driver_sqlserver(self):
        """Driver customizado SQL Server"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        result = connector._build_connection_string(
            db_type="sqlserver",
            host="localhost",
            port=1433,
            database="testdb",
            username="user",
            password="pass",
            driver="ODBC Driver 18 for SQL Server",
        )

        assert "ODBC Driver 18" in result
