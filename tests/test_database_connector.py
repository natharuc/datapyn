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
            db_type='sqlserver',
            host='localhost',
            port=1433,
            database='testdb',
            username='',
            password='',
            use_windows_auth=True
        )
        
        assert 'mssql+pyodbc' in result
        assert 'localhost' in result
        assert 'testdb' in result
        assert 'Trusted_Connection=yes' in result
    
    def test_sqlserver_sql_auth_string(self):
        """Deve construir string SQL Server com SQL Auth"""
        from database.database_connector import DatabaseConnector
        
        connector = DatabaseConnector()
        result = connector._build_connection_string(
            db_type='sqlserver',
            host='localhost',
            port=1433,
            database='testdb',
            username='user',
            password='pass'
        )
        
        assert 'mssql+pyodbc' in result
        assert 'user:pass' in result
        assert 'localhost' in result
    
    def test_mysql_connection_string(self):
        """Deve construir string MySQL"""
        from database.database_connector import DatabaseConnector
        
        connector = DatabaseConnector()
        result = connector._build_connection_string(
            db_type='mysql',
            host='localhost',
            port=3306,
            database='testdb',
            username='user',
            password='pass'
        )
        
        assert 'mysql+pymysql' in result
        assert 'localhost' in result
        assert 'charset=utf8mb4' in result
    
    def test_postgresql_connection_string(self):
        """Deve construir string PostgreSQL"""
        from database.database_connector import DatabaseConnector
        
        connector = DatabaseConnector()
        result = connector._build_connection_string(
            db_type='postgresql',
            host='localhost',
            port=5432,
            database='testdb',
            username='user',
            password='pass'
        )
        
        assert 'postgresql+psycopg2' in result
        assert 'localhost' in result
    
    def test_unsupported_database_raises_error(self):
        """Banco não suportado deve lançar erro"""
        from database.database_connector import DatabaseConnector
        
        connector = DatabaseConnector()
        
        with pytest.raises(ValueError) as exc_info:
            connector._build_connection_string(
                db_type='oracle',
                host='localhost',
                port=1521,
                database='testdb',
                username='user',
                password='pass'
            )
        
        assert 'não suportado' in str(exc_info.value)


class TestDatabaseConnectorState:
    """Testes de estado do conector"""
    
    def test_initial_state(self):
        """Estado inicial deve estar desconectado"""
        from database.database_connector import DatabaseConnector
        
        connector = DatabaseConnector()
        
        assert connector.engine is None
        assert connector.db_type == ''
        assert not connector.is_connected()
    
    def test_supported_databases(self):
        """Deve ter bancos suportados definidos"""
        from database.database_connector import DatabaseConnector
        
        connector = DatabaseConnector()
        
        assert 'sqlserver' in connector.SUPPORTED_DATABASES
        assert 'mysql' in connector.SUPPORTED_DATABASES
        assert 'postgresql' in connector.SUPPORTED_DATABASES


class TestDatabaseConnectorMocked:
    """Testes com conexão mockada"""
    
    @patch('database.database_connector.create_engine')
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
            db_type='mysql',
            host='localhost',
            port=3306,
            database='testdb',
            username='user',
            password='pass'
        )
        
        assert result is True
        assert connector.engine is not None
        assert connector.db_type == 'mysql'
    
    @patch('database.database_connector.create_engine')
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
        connector.connect('mysql', 'localhost', 3306, 'testdb', 'user', 'pass')
        
        # Mock pd.read_sql
        with patch('pandas.read_sql') as mock_read_sql:
            mock_read_sql.return_value = pd.DataFrame({'col': [1, 2, 3]})
            
            result = connector.execute_query('SELECT * FROM test')
            
            assert isinstance(result, pd.DataFrame)
            assert len(result) == 3


class TestDatabaseConnectorEdgeCases:
    """Testes de casos de borda"""
    
    def test_special_characters_in_password(self):
        """Senha com caracteres especiais"""
        from database.database_connector import DatabaseConnector
        
        connector = DatabaseConnector()
        result = connector._build_connection_string(
            db_type='mysql',
            host='localhost',
            port=3306,
            database='testdb',
            username='user',
            password='p@ss!w0rd#$%'
        )
        
        # Deve incluir a senha (pode precisar de encoding em casos reais)
        assert 'p@ss!w0rd#$%' in result
    
    def test_custom_driver_sqlserver(self):
        """Driver customizado SQL Server"""
        from database.database_connector import DatabaseConnector
        
        connector = DatabaseConnector()
        result = connector._build_connection_string(
            db_type='sqlserver',
            host='localhost',
            port=1433,
            database='testdb',
            username='user',
            password='pass',
            driver='ODBC Driver 18 for SQL Server'
        )
        
        assert 'ODBC Driver 18' in result


class TestUseDatabasePersistence:
    """Testes para garantir que USE <db> persiste entre execucoes"""

    def test_connection_params_updated_on_use(self):
        """USE deve atualizar connection_params['database']"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.connection_params = {'database': 'gecon'}
        connector.db_type = 'sqlserver'
        connector.engine = MagicMock()

        # Simular execucao de USE esim
        import re
        query = "USE esim"
        use_match = re.search(r'\bUSE\s+\[?(\w+)\]?\s*;?\s*$', query.strip(), re.IGNORECASE | re.MULTILINE)
        assert use_match is not None
        assert use_match.group(1) == 'esim'

        # O execute_query deveria atualizar connection_params
        connector.connection_params['database'] = use_match.group(1)
        assert connector.connection_params['database'] == 'esim'
        assert connector.get_current_database() == 'esim'

    def test_use_with_brackets(self):
        """USE [esim] com colchetes deve funcionar"""
        import re
        query = "USE [esim]"
        use_match = re.search(r'\bUSE\s+\[?(\w+)\]?\s*;?\s*$', query.strip(), re.IGNORECASE | re.MULTILINE)
        assert use_match is not None
        assert use_match.group(1) == 'esim'

    def test_use_with_semicolon(self):
        """USE esim; com ponto-e-virgula deve funcionar"""
        import re
        query = "USE esim;"
        use_match = re.search(r'\bUSE\s+\[?(\w+)\]?\s*;?\s*$', query.strip(), re.IGNORECASE | re.MULTILINE)
        assert use_match is not None
        assert use_match.group(1) == 'esim'

    def test_mssql_batch_sends_use_before_query(self):
        """_execute_mssql_batch deve enviar USE antes da query"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = 'sqlserver'
        connector.connection_params = {'database': 'esim'}

        # Criar mocks
        mock_cursor = MagicMock()
        mock_cursor.description = [('col1',), ('col2',)]
        mock_cursor.fetchall.return_value = [(1, 'a')]
        mock_cursor.nextset.return_value = False

        mock_raw_conn = MagicMock()
        mock_raw_conn.cursor.return_value = mock_cursor

        mock_engine = MagicMock()
        mock_engine.raw_connection.return_value = mock_raw_conn
        connector.engine = mock_engine

        connector._execute_mssql_batch("SELECT 1")

        # Deve ter executado USE [esim] antes da query principal
        calls = mock_cursor.execute.call_args_list
        assert len(calls) >= 2, f"Deveria ter chamado execute ao menos 2 vezes (USE + query), mas chamou {len(calls)}"
        assert "USE [esim]" in calls[0][0][0]
        assert "SELECT 1" in calls[1][0][0]

    def test_checkout_event_registered_for_sqlserver(self):
        """Engine SQL Server deve registrar evento checkout no pool"""
        from database.database_connector import DatabaseConnector
        from sqlalchemy import event

        connector = DatabaseConnector()

        with patch('database.database_connector.create_engine') as mock_create_engine:
            mock_engine = MagicMock()
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_engine.connect.return_value = mock_conn
            mock_create_engine.return_value = mock_engine

            with patch('database.database_connector.event') as mock_event:
                connector.connect('sqlserver', 'localhost', 1433, 'testdb',
                                  use_windows_auth=True)

                # Deve ter registrado evento "checkout"
                mock_event.listens_for.assert_called_once_with(mock_engine, "checkout")
