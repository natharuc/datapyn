"""
Configuração do pytest e fixtures compartilhadas
"""
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import json

# Adicionar src ao path
src_path = str(Path(__file__).parent.parent / 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)


# ==================== FIXTURES DE CONFIGURAÇÃO ====================

@pytest.fixture
def temp_dir():
    """Diretório temporário para testes"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_home_dir(temp_dir, monkeypatch):
    """Mock do diretório home para não poluir configs reais"""
    monkeypatch.setattr(Path, 'home', lambda: temp_dir)
    return temp_dir


# ==================== FIXTURES DE MANAGERS ====================

@pytest.fixture
def shortcut_manager(temp_dir):
    """ShortcutManager com config em temp"""
    from core.shortcut_manager import ShortcutManager
    config_path = temp_dir / 'shortcuts.json'
    return ShortcutManager(str(config_path))


@pytest.fixture
def workspace_manager(temp_dir):
    """WorkspaceManager com config em temp"""
    from core.workspace_manager import WorkspaceManager
    config_path = temp_dir / 'workspace.json'
    return WorkspaceManager(str(config_path))


@pytest.fixture
def results_manager():
    """ResultsManager limpo"""
    from core.results_manager import ResultsManager
    return ResultsManager()


@pytest.fixture
def connection_manager(temp_dir):
    """ConnectionManager com config em temp"""
    from database.connection_manager import ConnectionManager
    config_path = temp_dir / 'connections.json'
    manager = ConnectionManager(str(config_path))
    return manager


# ==================== FIXTURES DE DATABASE MOCK ====================

@pytest.fixture
def mock_db_connector():
    """Conector de banco de dados mockado"""
    connector = MagicMock()
    connector.is_connected.return_value = True
    connector.execute_query.return_value = MagicMock()
    return connector


@pytest.fixture
def sample_dataframe():
    """DataFrame de exemplo para testes"""
    import pandas as pd
    return pd.DataFrame({
        'id': [1, 2, 3],
        'nome': ['Alice', 'Bob', 'Carol']
    })


# ==================== FIXTURES DE MIXED EXECUTOR ====================

@pytest.fixture
def mixed_executor(mock_db_connector, results_manager):
    """MixedLanguageExecutor configurado"""
    from core.mixed_executor import MixedLanguageExecutor
    executor = MixedLanguageExecutor(mock_db_connector, results_manager)
    return executor


# ==================== HELPER FUNCTIONS ====================

def create_connection_config(name='test_conn', db_type='mssql', host='localhost', 
                             port=3306, database='testdb', username='user', 
                             use_windows_auth=False):
    """Cria config de conexão para testes"""
    return {
        'name': name,
        'db_type': db_type,
        'host': host,
        'port': port,
        'database': database,
        'username': username,
        'use_windows_auth': use_windows_auth,
        'group': 'default',
        'color': '#569cd6'
    }
