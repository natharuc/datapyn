"""
Testes para namespace isolado por bloco SQL

Cada bloco SQL deve criar variaveis b1_df, b2_df, b3_df, etc.
ao inves de sobrepor df, df1, df2.

Nota: Testes de conexao per-block (panel, drag & drop, sinais)
estao em test_block_connection.py
"""

import pytest
import pandas as pd
from unittest.mock import Mock, MagicMock
from PyQt6.QtCore import QTimer

from src.core.session import Session
from src.ui.components.session_widget import SessionWidget
from src.editors.code_block import CodeBlock


# Fixture autouse para evitar hang do QScintilla focus em testes
@pytest.fixture(autouse=True)
def _no_focus_editor(monkeypatch):
    """Desabilita focus_editor para evitar hang do QScintilla em testes"""
    monkeypatch.setattr(CodeBlock, "focus_editor", lambda self: None)


@pytest.fixture
def mock_connector():
    """Connector mockado que retorna DataFrames"""
    connector = Mock()
    connector.is_connected.return_value = True
    connector.get_current_database.return_value = "test_db"
    return connector


class TestBlockNamespace:
    """Testes para namespace isolado por bloco"""

    def test_block_has_connection_name_attribute(self, qapp):
        """CodeBlock deve ter atributo connection_name"""
        block = CodeBlock()
        assert hasattr(block, "_connection_name")
        assert block.get_connection_name() is None  # Padrao: None

    def test_block_to_dict_saves_connection_name(self, qapp):
        """to_dict deve salvar connection_name quando definido"""
        block = CodeBlock(default_language="sql")
        block._connection_name = "CustomConn"

        data = block.to_dict()
        assert "connection_name" in data
        assert data["connection_name"] == "CustomConn"

    def test_block_from_dict_restores_connection_name(self, qapp):
        """from_dict deve restaurar connection_name"""
        data = {"language": "sql", "code": "SELECT 1", "connection_name": "CustomConn"}

        block = CodeBlock.from_dict(data)
        assert block.get_connection_name() == "CustomConn"

    def test_block_editor_passes_connection_name_in_queue(self, qapp):
        """BlockEditor deve passar connection_name na fila de execucao"""
        from src.editors.block_editor import BlockEditor

        editor = BlockEditor()

        # Usar bloco padrao como bloco1 e adicionar bloco2
        block1 = editor._blocks[0]
        block1.set_language("sql")
        block1.set_code("SELECT 1")

        block2 = editor.add_block(language="sql", code="SELECT 2")
        block2._connection_name = "CustomConn"

        # Capturar fila emitida
        queue = []
        editor.execute_queue.connect(lambda q: queue.extend(q))

        editor.execute_all_blocks()

        # Verificar formato da tupla: (language, code, block, block_name, connection_name, database_name, sql_parameters)
        assert len(queue) == 2

        item1 = queue[0]
        assert len(item1) == 7
        assert item1[0] == "sql"  # language
        assert item1[3] == block1.get_block_name()  # block_name
        assert item1[4] is None  # connection_name (padrao)
        assert item1[5] is None  # database_name (padrao)
        assert item1[6] == []  # sql_parameters

        item2 = queue[1]
        assert item2[0] == "sql"
        assert item2[3] == block2.get_block_name()  # block_name
        assert item2[4] == "CustomConn"  # connection_name customizada
        assert item2[5] is None  # database_name (padrao)
