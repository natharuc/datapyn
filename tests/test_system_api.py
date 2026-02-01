"""
Testes do Sistema Completo - Verifica todas as funcionalidades
"""
import pytest
import pandas as pd
import sqlite3
from io import StringIO
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


# ==================== TESTES DO CONNECTION MANAGER ====================

class TestConnectionManagerAPI:
    """Testes da API completa do ConnectionManager"""
    
    def test_save_connection_config(self, connection_manager):
        """Deve salvar configuração de conexão"""
        connection_manager.save_connection_config(
            name='Test DB',
            db_type='mssql',
            host='localhost',
            port=1433,
            database='testdb'
        )
        
        assert 'Test DB' in connection_manager.get_saved_connections()
    
    def test_get_saved_connections_returns_list(self, connection_manager):
        """get_saved_connections deve retornar lista de nomes"""
        connection_manager.save_connection_config(
            name='DB1', db_type='mssql', host='h1', port=1433, database='db1'
        )
        connection_manager.save_connection_config(
            name='DB2', db_type='mssql', host='h2', port=1433, database='db2'
        )
        
        result = connection_manager.get_saved_connections()
        
        assert isinstance(result, list)
        assert 'DB1' in result
        assert 'DB2' in result
    
    def test_get_connection_config(self, connection_manager):
        """Deve retornar configuração de conexão"""
        connection_manager.save_connection_config(
            name='MyDB',
            db_type='mysql',
            host='myhost',
            port=3306,
            database='mydb',
            username='user'
        )
        
        config = connection_manager.get_connection_config('MyDB')
        
        assert config['db_type'] == 'mysql'
        assert config['host'] == 'myhost'
        assert config['port'] == 3306
        assert config['database'] == 'mydb'
    
    def test_delete_connection_config(self, connection_manager):
        """Deve remover configuração"""
        connection_manager.save_connection_config(
            name='ToDelete', db_type='mssql', host='h', port=1433, database='db'
        )
        
        connection_manager.delete_connection_config('ToDelete')
        
        assert 'ToDelete' not in connection_manager.get_saved_connections()
    
    def test_update_connection_config(self, connection_manager):
        """Deve atualizar configuração existente"""
        connection_manager.save_connection_config(
            name='Original', db_type='mssql', host='old', port=1433, database='db'
        )
        
        connection_manager.update_connection_config(
            old_name='Original',
            new_name='Updated',
            db_type='mssql',
            host='new',
            port=1433,
            database='newdb'
        )
        
        assert 'Original' not in connection_manager.get_saved_connections()
        assert 'Updated' in connection_manager.get_saved_connections()
        
        config = connection_manager.get_connection_config('Updated')
        assert config['host'] == 'new'
    
    def test_create_group(self, connection_manager):
        """Deve criar grupo"""
        connection_manager.create_group('Production')
        
        groups = connection_manager.get_groups()
        assert 'Production' in groups
    
    def test_delete_group(self, connection_manager):
        """Deve deletar grupo"""
        connection_manager.create_group('ToDelete')
        connection_manager.delete_group('ToDelete')
        
        groups = connection_manager.get_groups()
        assert 'ToDelete' not in groups
    
    def test_rename_group(self, connection_manager):
        """Deve renomear grupo"""
        connection_manager.create_group('OldName')
        connection_manager.rename_group('OldName', 'NewName')
        
        groups = connection_manager.get_groups()
        assert 'OldName' not in groups
        assert 'NewName' in groups
    
    def test_get_connections_by_group(self, connection_manager):
        """Deve retornar conexões por grupo"""
        connection_manager.create_group('Dev')
        connection_manager.save_connection_config(
            name='DevDB', db_type='mssql', host='h', port=1433, database='db', group='Dev'
        )
        
        conns = connection_manager.get_connections_by_group('Dev')
        assert 'DevDB' in conns
    
    def test_mark_connection_used(self, connection_manager):
        """Deve marcar conexão como usada"""
        connection_manager.save_connection_config(
            name='UsedDB', db_type='mssql', host='h', port=1433, database='db'
        )
        
        connection_manager.mark_connection_used('UsedDB')
        
        config = connection_manager.get_connection_config('UsedDB')
        assert config['last_used'] is not None
    
    def test_active_connection_property(self, connection_manager):
        """Propriedade active_connection deve funcionar"""
        assert connection_manager.active_connection is None
        
        connection_manager.active_connection = 'test'
        assert connection_manager.active_connection == 'test'


# ==================== TESTES DO WORKSPACE MANAGER ====================

class TestWorkspaceManagerAPI:
    """Testes da API completa do WorkspaceManager"""
    
    def test_save_workspace(self, workspace_manager):
        """Deve salvar workspace"""
        tabs = [
            {'code': 'SELECT 1', 'connection': None, 'title': 'Script 1'}
        ]
        
        workspace_manager.save_workspace(tabs, 0, 'conn1')
        
        assert workspace_manager.config_path.exists()
    
    def test_load_workspace(self, workspace_manager):
        """Deve carregar workspace"""
        tabs = [
            {'code': 'SELECT 1', 'connection': None, 'title': 'Tab 1'},
            {'code': 'print(1)', 'connection': None, 'title': 'Tab 2'},
        ]
        workspace_manager.save_workspace(tabs, 1, 'myconn')
        
        loaded = workspace_manager.load_workspace()
        
        assert len(loaded['tabs']) == 2
        assert loaded['active_tab'] == 1
        assert loaded['active_connection'] == 'myconn'
    
    def test_clear_workspace(self, workspace_manager):
        """Deve limpar workspace"""
        workspace_manager.save_workspace([{'code': 'x', 'connection': None, 'title': 't'}], 0, None)
        workspace_manager.clear_workspace()
        
        assert not workspace_manager.config_path.exists()
    
    def test_load_empty_returns_default(self, workspace_manager):
        """Workspace vazio retorna default"""
        loaded = workspace_manager.load_workspace()
        
        assert 'tabs' in loaded
        assert len(loaded['tabs']) >= 1
        assert 'active_tab' in loaded


# ==================== TESTES DO SHORTCUT MANAGER ====================

class TestShortcutManagerAPI:
    """Testes da API completa do ShortcutManager"""
    
    def test_get_all_shortcuts(self, shortcut_manager):
        """Deve retornar todos os atalhos"""
        shortcuts = shortcut_manager.get_all_shortcuts()
        
        assert isinstance(shortcuts, dict)
        assert 'execute_sql' in shortcuts
        assert 'execute_python' in shortcuts
        assert 'execute_cross_syntax' in shortcuts
    
    def test_get_shortcut(self, shortcut_manager):
        """Deve retornar atalho específico"""
        assert shortcut_manager.get_shortcut('execute_sql') == 'F5'
        assert shortcut_manager.get_shortcut('execute_python') == 'Shift+Return'
    
    def test_set_shortcut(self, shortcut_manager):
        """Deve definir atalho"""
        shortcut_manager.set_shortcut('execute_sql', 'F6')
        assert shortcut_manager.get_shortcut('execute_sql') == 'F6'
    
    def test_reset_to_defaults(self, shortcut_manager):
        """Deve resetar para padrões"""
        shortcut_manager.set_shortcut('execute_sql', 'F99')
        shortcut_manager.reset_to_defaults()
        
        assert shortcut_manager.get_shortcut('execute_sql') == 'F5'
    
    def test_get_nonexistent_shortcut(self, shortcut_manager):
        """Atalho inexistente retorna string vazia"""
        result = shortcut_manager.get_shortcut('nonexistent')
        assert result == ''


# ==================== TESTES DO RESULTS MANAGER ====================

class TestResultsManagerAPI:
    """Testes da API completa do ResultsManager"""
    
    def test_add_result(self, results_manager, sample_dataframe):
        """Deve adicionar resultado"""
        name = results_manager.add_result(sample_dataframe, 'SELECT 1')
        
        assert name == 'df1'
        assert 'df1' in results_manager.results
    
    def test_get_result(self, results_manager, sample_dataframe):
        """Deve retornar resultado"""
        results_manager.add_result(sample_dataframe)
        
        df = results_manager.get_result('df1')
        
        assert df is not None
        assert isinstance(df, pd.DataFrame)
    
    def test_get_namespace(self, results_manager, sample_dataframe):
        """Namespace deve incluir pd, np e resultados"""
        results_manager.add_result(sample_dataframe)
        
        ns = results_manager.get_namespace()
        
        assert 'pd' in ns
        assert 'np' in ns
        assert 'df1' in ns
        assert 'df' in ns  # último resultado
    
    def test_clear_result(self, results_manager, sample_dataframe):
        """Deve limpar resultado específico"""
        results_manager.add_result(sample_dataframe)
        results_manager.clear_result('df1')
        
        assert results_manager.get_result('df1') is None
    
    def test_clear_all(self, results_manager, sample_dataframe):
        """Deve limpar todos os resultados"""
        results_manager.add_result(sample_dataframe)
        results_manager.add_result(sample_dataframe)
        results_manager.clear_all()
        
        assert len(results_manager.results) == 0
    
    def test_metadata_saved(self, results_manager, sample_dataframe):
        """Metadata deve ser salva"""
        results_manager.add_result(sample_dataframe, 'SELECT * FROM test')
        
        meta = results_manager.metadata['df1']
        assert 'query' in meta
        assert 'rows' in meta
        assert 'columns' in meta
    
    def test_history_tracking(self, results_manager, sample_dataframe):
        """Histórico deve ser rastreado"""
        results_manager.add_result(sample_dataframe)
        results_manager.add_result(sample_dataframe)
        
        assert len(results_manager.history) == 2


# ==================== TESTES DO DATABASE CONNECTOR ====================

class TestDatabaseConnectorAPI:
    """Testes da API do DatabaseConnector"""
    
    def test_connection_string_sqlserver_windows_auth(self):
        """String de conexão SQL Server com Windows Auth"""
        from database.database_connector import DatabaseConnector
        
        conn = DatabaseConnector()
        result = conn._build_connection_string(
            'sqlserver', 'localhost', 1433, 'testdb', '', '', use_windows_auth=True
        )
        
        assert 'Trusted_Connection=yes' in result
    
    def test_connection_string_sqlserver_sql_auth(self):
        """String de conexão SQL Server com SQL Auth"""
        from database.database_connector import DatabaseConnector
        
        conn = DatabaseConnector()
        result = conn._build_connection_string(
            'sqlserver', 'localhost', 1433, 'testdb', 'user', 'pass'
        )
        
        assert 'user:pass' in result
    
    def test_connection_string_mysql(self):
        """String de conexão MySQL"""
        from database.database_connector import DatabaseConnector
        
        conn = DatabaseConnector()
        result = conn._build_connection_string(
            'mysql', 'localhost', 3306, 'testdb', 'user', 'pass'
        )
        
        assert 'mysql+pymysql' in result
    
    def test_connection_string_postgresql(self):
        """String de conexão PostgreSQL"""
        from database.database_connector import DatabaseConnector
        
        conn = DatabaseConnector()
        result = conn._build_connection_string(
            'postgresql', 'localhost', 5432, 'testdb', 'user', 'pass'
        )
        
        assert 'postgresql+psycopg2' in result
    
    def test_unsupported_database_raises(self):
        """Banco não suportado deve lançar erro"""
        from database.database_connector import DatabaseConnector
        
        conn = DatabaseConnector()
        
        with pytest.raises(ValueError):
            conn._build_connection_string('oracle', 'h', 1521, 'db', 'u', 'p')
    
    def test_initial_state(self):
        """Estado inicial deve ser desconectado"""
        from database.database_connector import DatabaseConnector
        
        conn = DatabaseConnector()
        
        assert conn.engine is None
        assert conn.db_type == ''
        assert not conn.is_connected()


# ==================== TESTES DO MIXED EXECUTOR ====================

class TestMixedExecutorAPI:
    """Testes da API do MixedLanguageExecutor"""
    
    def test_extract_queries(self, mixed_executor):
        """Deve extrair queries do código"""
        code = '''
df1 = {{SELECT * FROM table1}}
df2 = {{SELECT * FROM table2}}
'''
        queries = mixed_executor.extract_queries(code)
        
        assert len(queries) == 2
        assert queries[0][0] == 'df1'
        assert queries[1][0] == 'df2'
    
    def test_validate_syntax_valid(self, mixed_executor):
        """Sintaxe válida deve passar"""
        code = 'df = {{SELECT 1}}'
        
        is_valid, error = mixed_executor.validate_syntax(code)
        
        assert is_valid is True
    
    def test_validate_syntax_no_query(self, mixed_executor):
        """Código sem query deve ser inválido para cross-syntax"""
        code = 'x = 1 + 1'
        
        is_valid, error = mixed_executor.validate_syntax(code)
        
        assert is_valid is False
    
    def test_process_double_brace_syntax(self, mixed_executor):
        """Deve processar sintaxe {{ }}"""
        code = 'data = {{SELECT * FROM users}}'
        
        processed, extractions = mixed_executor._process_double_brace_syntax(code)
        
        assert len(extractions) == 1
        assert extractions[0][0] == 'data'
        assert 'SELECT * FROM users' in extractions[0][1]


# ==================== TESTES DE PERSISTÊNCIA ====================

class TestPersistence:
    """Testes de persistência de dados"""
    
    def test_shortcut_manager_persists(self, shortcut_manager, temp_dir):
        """ShortcutManager deve persistir alterações"""
        shortcut_manager.set_shortcut('custom', 'Ctrl+X')
        
        # Criar novo manager no mesmo path
        from core.shortcut_manager import ShortcutManager
        new_manager = ShortcutManager(str(shortcut_manager.config_path))
        
        assert new_manager.get_shortcut('custom') == 'Ctrl+X'
    
    def test_workspace_manager_persists(self, workspace_manager, temp_dir):
        """WorkspaceManager deve persistir"""
        tabs = [{'code': 'test code', 'connection': None, 'title': 'Test'}]
        workspace_manager.save_workspace(tabs, 0, None)
        
        from core.workspace_manager import WorkspaceManager
        new_manager = WorkspaceManager(str(workspace_manager.config_path))
        
        loaded = new_manager.load_workspace()
        assert loaded['tabs'][0]['code'] == 'test code'
    
    def test_connection_manager_persists(self, connection_manager, temp_dir):
        """ConnectionManager deve persistir"""
        connection_manager.save_connection_config(
            name='PersistTest',
            db_type='mssql',
            host='localhost',
            port=1433,
            database='test'
        )
        
        from database.connection_manager import ConnectionManager
        new_manager = ConnectionManager(str(connection_manager.config_path))
        
        assert 'PersistTest' in new_manager.get_saved_connections()


# ==================== TESTES DE EDGE CASES ====================

class TestEdgeCases:
    """Testes de casos de borda"""
    
    def test_corrupted_shortcut_config(self, temp_dir):
        """Config corrompido deve usar defaults"""
        config_path = temp_dir / 'shortcuts.json'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            f.write('invalid json {{{')
        
        from core.shortcut_manager import ShortcutManager
        manager = ShortcutManager(str(config_path))
        
        assert manager.get_shortcut('execute_sql') == 'F5'
    
    def test_corrupted_workspace_config(self, temp_dir):
        """Workspace corrompido deve usar default"""
        config_path = temp_dir / 'workspace.json'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            f.write('not json')
        
        from core.workspace_manager import WorkspaceManager
        manager = WorkspaceManager(str(config_path))
        
        loaded = manager.load_workspace()
        assert len(loaded['tabs']) >= 1
    
    def test_empty_tabs_workspace(self, temp_dir):
        """Workspace com tabs vazio deve ter default"""
        config_path = temp_dir / 'workspace.json'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump({'tabs': [], 'active_tab': 0}, f)
        
        from core.workspace_manager import WorkspaceManager
        manager = WorkspaceManager(str(config_path))
        
        loaded = manager.load_workspace()
        assert len(loaded['tabs']) >= 1
    
    def test_unicode_in_code(self, workspace_manager):
        """Deve suportar unicode no código"""
        tabs = [{'code': 'SELECT * FROM 日本語テーブル', 'connection': None, 'title': 'スクリプト'}]
        workspace_manager.save_workspace(tabs, 0, None)
        
        loaded = workspace_manager.load_workspace()
        assert '日本語' in loaded['tabs'][0]['code']
    
    def test_special_chars_in_connection_name(self, connection_manager):
        """Deve suportar caracteres especiais em nomes"""
        connection_manager.save_connection_config(
            name='Test [Prod] - Server (1)',
            db_type='mssql',
            host='localhost',
            port=1433,
            database='test'
        )
        
        config = connection_manager.get_connection_config('Test [Prod] - Server (1)')
        assert config is not None


# ==================== TESTES DE INTEGRAÇÃO ====================

class TestSystemIntegration:
    """Testes de integração do sistema"""
    
    def test_full_workflow(self, connection_manager, workspace_manager, shortcut_manager):
        """Workflow completo de uso"""
        # 1. Configurar conexão
        connection_manager.save_connection_config(
            name='DevDB',
            db_type='mssql',
            host='localhost',
            port=1433,
            database='devdb',
            group='Development'
        )
        
        # 2. Configurar atalhos
        shortcut_manager.set_shortcut('execute_sql', 'F5')
        
        # 3. Criar workspace
        tabs = [
            {'code': 'SELECT * FROM users', 'connection': 'DevDB', 'title': 'Users Query'},
            {'code': 'print("hello")', 'connection': None, 'title': 'Python Script'},
        ]
        workspace_manager.save_workspace(tabs, 0, 'DevDB')
        
        # 4. Verificar tudo persiste
        assert 'DevDB' in connection_manager.get_saved_connections()
        assert shortcut_manager.get_shortcut('execute_sql') == 'F5'
        
        loaded = workspace_manager.load_workspace()
        assert len(loaded['tabs']) == 2
        assert loaded['active_connection'] == 'DevDB'
    
    def test_results_namespace_integration(self, results_manager, sample_dataframe):
        """Resultados devem estar disponíveis no namespace"""
        # Adicionar resultados
        results_manager.add_result(sample_dataframe, 'query1')
        results_manager.add_result(sample_dataframe, 'query2')
        
        # Obter namespace
        ns = results_manager.get_namespace()
        
        # Deve ter os resultados e bibliotecas
        assert 'df1' in ns
        assert 'df2' in ns
        assert 'pd' in ns
        assert 'np' in ns
        
        # df deve apontar para o último
        assert ns['df'] is results_manager.last_result
