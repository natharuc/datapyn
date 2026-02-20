"""
Testes para troca de banco de dados por bloco no editor

Funcionalidades testadas:
1. BlockDatabasePanel: panel clicavel com icone + nome do banco
2. Drag & drop de bancos do Object Explorer para blocos SQL
3. Persistencia: to_dict/from_dict salvam/restauram database_name
4. Sinais: database_changed propagado de CodeBlock -> BlockEditor -> SessionWidget
5. Sintaxe do comando USE para diferentes bancos (sqlserver, mysql, mariadb, postgresql)
6. Atualizacao do db_panel quando USE e executado
"""

import pytest
import re
from unittest.mock import Mock, MagicMock, patch
from PyQt6.QtCore import Qt, QMimeData, QPointF
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QApplication

from src.editors.code_block import CodeBlock, BlockDatabasePanel
from src.editors.block_editor import BlockEditor


# Fixture autouse para evitar hang do QScintilla focus em testes
@pytest.fixture(autouse=True)
def _no_focus_editor(monkeypatch):
    """Desabilita focus_editor para evitar hang do QScintilla em testes"""
    monkeypatch.setattr(CodeBlock, "focus_editor", lambda self: None)


# ===== BlockDatabasePanel =====


class TestBlockDatabasePanel:
    """Testes para o panel de banco de dados clicavel"""

    def test_panel_initial_state(self, qapp):
        """Panel should start without database (default)"""
        panel = BlockDatabasePanel()
        assert panel.get_database_name() is None
        assert panel.name_label.text() == "Default DB"

    def test_panel_set_database(self, qapp):
        """set_database deve atualizar nome"""
        panel = BlockDatabasePanel()
        panel.set_database("testdb")

        assert panel.get_database_name() == "testdb"
        assert panel.name_label.text() == "testdb"

    def test_panel_set_database_none_resets(self, qapp):
        """set_database(None) should return to default"""
        panel = BlockDatabasePanel()
        panel.set_database("testdb")

        panel.set_database(None)
        assert panel.get_database_name() is None
        assert panel.name_label.text() == "Default DB"

    def test_panel_accepts_drops(self, qapp):
        """Panel deve aceitar drops"""
        panel = BlockDatabasePanel()
        assert panel.acceptDrops()

    def test_panel_click_emits_signal(self, qapp):
        """Click no panel deve emitir database_clicked"""
        panel = BlockDatabasePanel()
        clicked = []
        panel.database_clicked.connect(lambda: clicked.append(True))

        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        panel.mousePressEvent(event)
        assert len(clicked) == 1

    def test_panel_drop_emits_signal(self, qapp):
        """Drop de banco deve emitir database_dropped(name)"""
        panel = BlockDatabasePanel()
        dropped = []
        panel.database_dropped.connect(lambda name: dropped.append(name))

        # Criar MimeData simulando drag de banco
        mime_data = QMimeData()
        mime_data.setData("application/x-database-name", b"production")

        # Criar evento de drop
        event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        panel.dropEvent(event)

        assert len(dropped) == 1
        assert dropped[0] == "production"

    def test_panel_drag_enter_accepts_database_mime(self, qapp):
        """dragEnterEvent deve aceitar mime application/x-database-name"""
        panel = BlockDatabasePanel()

        mime_data = QMimeData()
        mime_data.setData("application/x-database-name", b"testdb")

        event = MagicMock()
        event.mimeData.return_value = mime_data
        panel.dragEnterEvent(event)
        event.acceptProposedAction.assert_called_once()

    def test_panel_drag_enter_rejects_other_mime(self, qapp):
        """dragEnterEvent deve rejeitar outros tipos de mime"""
        panel = BlockDatabasePanel()

        mime_data = QMimeData()
        mime_data.setData("application/x-connection-name", b"TestConn")

        event = MagicMock()
        event.mimeData.return_value = mime_data
        panel.dragEnterEvent(event)
        event.acceptProposedAction.assert_not_called()


# ===== CodeBlock Database =====


class TestCodeBlockDatabase:
    """Testes para database per-block no CodeBlock"""

    def test_block_has_database_name_attribute(self, qapp):
        """CodeBlock deve ter atributo _database_name"""
        block = CodeBlock()
        assert hasattr(block, "_database_name")
        assert block.get_database_name() is None

    def test_block_has_db_panel(self, qapp):
        """CodeBlock deve ter db_panel (BlockDatabasePanel)"""
        block = CodeBlock()
        assert hasattr(block, "db_panel")
        assert isinstance(block.db_panel, BlockDatabasePanel)

    def test_block_set_database_name(self, qapp):
        """set_database_name deve atualizar panel e _database_name"""
        block = CodeBlock(default_language="sql")
        block.set_database_name("mydb")

        assert block.get_database_name() == "mydb"
        assert block.db_panel.get_database_name() == "mydb"

    def test_block_database_dropped_updates_state(self, qapp):
        """Drop de banco no panel deve atualizar _database_name"""
        block = CodeBlock(default_language="sql")
        block._on_database_dropped("dropped_db")

        assert block.get_database_name() == "dropped_db"
        assert block.db_panel.get_database_name() == "dropped_db"

    def test_block_database_changed_signal(self, qapp):
        """set_database_name deve emitir database_changed signal"""
        block = CodeBlock(default_language="sql")
        emitted = []
        block.database_changed.connect(lambda b, name: emitted.append((b, name)))

        block.set_database_name("signal_db")

        assert len(emitted) == 1
        assert emitted[0][0] is block
        assert emitted[0][1] == "signal_db"

    def test_block_db_panel_visible_for_sql(self, qapp):
        """db_panel deve ser visivel apenas para blocos SQL"""
        block = CodeBlock(default_language="sql")
        # Use isHidden() since isVisible() requires parent widget to be shown
        assert not block.db_panel.isHidden()

    def test_block_db_panel_hidden_for_python(self, qapp):
        """db_panel deve ser escondido para blocos Python"""
        block = CodeBlock(default_language="python")
        assert block.db_panel.isHidden()

    def test_block_db_panel_toggles_with_language(self, qapp):
        """db_panel visibilidade muda quando linguagem muda"""
        block = CodeBlock(default_language="sql")
        assert not block.db_panel.isHidden()

        block.set_language("python")
        assert block.db_panel.isHidden()

        block.set_language("sql")
        assert not block.db_panel.isHidden()


# ===== Persistencia Database =====


class TestDatabasePersistence:
    """Testes para persistencia de database_name nos blocos"""

    def test_to_dict_saves_database(self, qapp):
        """to_dict deve salvar database_name"""
        block = CodeBlock(default_language="sql")
        block.set_database_name("saved_db")

        data = block.to_dict()
        assert data["database_name"] == "saved_db"

    def test_to_dict_no_database_no_key(self, qapp):
        """to_dict sem database nao deve ter chave database_name"""
        block = CodeBlock(default_language="sql")
        data = block.to_dict()
        assert "database_name" not in data

    def test_from_dict_restores_database(self, qapp):
        """from_dict deve restaurar database_name"""
        data = {
            "language": "sql",
            "code": "SELECT 1",
            "database_name": "restored_db",
        }
        block = CodeBlock.from_dict(data)

        assert block.get_database_name() == "restored_db"
        assert block.db_panel.get_database_name() == "restored_db"

    def test_from_dict_without_database(self, qapp):
        """from_dict sem database_name deve manter None"""
        data = {"language": "sql", "code": "SELECT 1"}
        block = CodeBlock.from_dict(data)
        assert block.get_database_name() is None

    def test_roundtrip_to_dict_from_dict(self, qapp):
        """to_dict -> from_dict deve preservar database_name"""
        block1 = CodeBlock(default_language="sql")
        block1.set_code("SELECT * FROM users")
        block1.set_database_name("roundtrip_db")

        data = block1.to_dict()
        block2 = CodeBlock.from_dict(data)

        assert block2.get_database_name() == "roundtrip_db"
        assert block2.get_code() == "SELECT * FROM users"

    def test_roundtrip_with_connection_and_database(self, qapp):
        """to_dict -> from_dict deve preservar connection E database"""
        block1 = CodeBlock(default_language="sql")
        block1.set_connection_name("ProdConn", "sqlserver")
        block1.set_database_name("prod_db")

        data = block1.to_dict()
        block2 = CodeBlock.from_dict(data)

        assert block2.get_connection_name() == "ProdConn"
        assert block2.get_database_name() == "prod_db"


# ===== BlockEditor Database Signal =====


class TestBlockEditorDatabaseSignal:
    """Testes para sinais de database no BlockEditor"""

    def test_block_editor_has_database_signal(self, qapp):
        """BlockEditor deve ter sinal block_database_changed"""
        editor = BlockEditor()
        assert hasattr(editor, "block_database_changed")

    def test_block_editor_propagates_database_changed(self, qapp):
        """set_database_name em bloco deve propagar para BlockEditor"""
        editor = BlockEditor()
        emitted = []
        editor.block_database_changed.connect(lambda b, name: emitted.append((b, name)))

        block = editor._blocks[0]
        block.set_language("sql")
        block.set_database_name("propagated_db")

        assert len(emitted) == 1
        assert emitted[0][0] is block
        assert emitted[0][1] == "propagated_db"

    def test_execute_sql_signal_includes_database_name(self, qapp):
        """execute_sql signal deve incluir database_name quando definido"""
        editor = BlockEditor()

        block = editor._blocks[0]
        block.set_language("sql")
        block.set_code("SELECT 1")
        block.set_database_name("custom_db")

        # Capturar signal
        emitted = []
        editor.execute_sql.connect(lambda q, bn, cn, dn: emitted.append((q, bn, cn, dn)))

        editor._execute_block(block)

        assert len(emitted) == 1
        query, block_name, connection_name, database_name = emitted[0]
        assert query == "SELECT 1"
        assert block_name == block.get_block_name()
        assert connection_name is None  # padrao
        assert database_name == "custom_db"

    def test_execute_sql_signal_database_name_none_by_default(self, qapp):
        """execute_sql signal deve emitir database_name=None quando nao definido"""
        editor = BlockEditor()

        block = editor._blocks[0]
        block.set_language("sql")
        block.set_code("SELECT 1")
        # Nao definir database_name

        emitted = []
        editor.execute_sql.connect(lambda q, bn, cn, dn: emitted.append((q, bn, cn, dn)))

        editor._execute_block(block)

        assert len(emitted) == 1
        _, _, _, database_name = emitted[0]
        assert database_name is None

    def test_execute_queue_includes_database_name(self, qapp):
        """execute_queue deve incluir database_name na tupla"""
        editor = BlockEditor()

        block1 = editor._blocks[0]
        block1.set_language("sql")
        block1.set_code("SELECT 1")
        block1.set_database_name("db1")

        block2 = editor.add_block(language="sql", code="SELECT 2")
        block2.set_database_name("db2")

        queue = []
        editor.execute_queue.connect(lambda q: queue.extend(q))

        editor.execute_all_blocks()

        assert len(queue) == 2
        # Formato: (language, code, block, block_name, connection_name, database_name)
        assert queue[0][5] == "db1"
        assert queue[1][5] == "db2"


# ===== USE Command Syntax =====


class TestUseSyntax:
    """Testes para sintaxe do comando USE por tipo de banco"""

    def test_build_use_command_sqlserver(self):
        """SQL Server deve usar USE [database]"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "sqlserver"

        result = connector._build_use_command("testdb")
        assert result == "USE [testdb]"

    def test_build_use_command_mysql(self):
        """MySQL deve usar USE `database`"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "mysql"

        result = connector._build_use_command("testdb")
        assert result == "USE `testdb`"

    def test_build_use_command_mariadb(self):
        """MariaDB deve usar USE `database`"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "mariadb"

        result = connector._build_use_command("testdb")
        assert result == "USE `testdb`"

    def test_build_use_command_postgresql(self):
        """PostgreSQL deve usar SET search_path"""
        from database.database_connector import DatabaseConnector

        connector = DatabaseConnector()
        connector.db_type = "postgresql"

        result = connector._build_use_command("testdb")
        assert result == 'SET search_path TO "testdb"'

    def test_use_regex_matches_backtick_syntax(self):
        """Regex USE deve aceitar sintaxe com backticks"""
        pattern = r"^\s*USE\s+[\[`]?([^\]`\s;]+)[\]`]?\s*;?\s*$"

        # SQL Server: USE [db]
        match = re.match(pattern, "USE [testdb]", re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "testdb"

        # MySQL/MariaDB: USE `db`
        match = re.match(pattern, "USE `testdb`", re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "testdb"

        # Simples: USE db
        match = re.match(pattern, "USE testdb", re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "testdb"

        # Com ponto-e-virgula: USE db;
        match = re.match(pattern, "USE testdb;", re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "testdb"

    def test_use_regex_in_execute_query(self):
        """Regex USE no execute_query deve aceitar backticks"""
        pattern = r"\bUSE\s+[\[`]?(\w+)[\]`]?\s*;?\s*$"

        match = re.search(pattern, "USE `mydb`", re.IGNORECASE | re.MULTILINE)
        assert match is not None
        assert match.group(1) == "mydb"

        match = re.search(pattern, "USE [mydb]", re.IGNORECASE | re.MULTILINE)
        assert match is not None
        assert match.group(1) == "mydb"


# ===== Object Explorer Drag =====


class TestObjectExplorerDrag:
    """Testes para drag de bancos do Object Explorer"""

    def test_tree_drag_enabled(self, qtbot):
        """Tree do Object Explorer deve ter drag habilitado"""
        from PyQt6.QtWidgets import QMainWindow
        from src.ui.components.object_explorer_panel import ObjectExplorerPanel

        main = QMainWindow()
        qtbot.addWidget(main)
        panel = ObjectExplorerPanel()
        main.setCentralWidget(panel)
        main.show()
        qtbot.waitExposed(main)

        assert panel.tree.dragEnabled()

    def test_database_drop_on_block_panel(self, qapp):
        """Drop de banco do Object Explorer deve atualizar bloco"""
        block = CodeBlock(default_language="sql")

        # Simular drop de banco
        mime_data = QMimeData()
        mime_data.setData("application/x-database-name", b"production")

        event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        block.db_panel.dropEvent(event)

        assert block.db_panel.get_database_name() == "production"

    def test_database_mime_data_format(self, qapp):
        """MimeData deve usar formato application/x-database-name"""
        mime_data = QMimeData()
        mime_data.setData("application/x-database-name", "testdb".encode("utf-8"))

        assert mime_data.hasFormat("application/x-database-name")
        assert mime_data.data("application/x-database-name").data().decode("utf-8") == "testdb"


# ===== Database Selector Popup =====


class TestDatabaseSelectorPopup:
    """Testes para o seletor de banco com popup/menu"""

    def test_panel_set_available_databases(self, qapp):
        """set_available_databases deve armazenar a lista"""
        panel = BlockDatabasePanel()
        panel.set_available_databases(["db1", "db2", "db3"])
        assert panel.get_available_databases() == ["db1", "db2", "db3"]

    def test_panel_set_available_databases_none(self, qapp):
        """set_available_databases(None) deve limpar a lista"""
        panel = BlockDatabasePanel()
        panel.set_available_databases(["db1"])
        panel.set_available_databases(None)
        assert panel.get_available_databases() == []

    def test_panel_set_available_databases_empty(self, qapp):
        """set_available_databases([]) deve limpar a lista"""
        panel = BlockDatabasePanel()
        panel.set_available_databases(["db1"])
        panel.set_available_databases([])
        assert panel.get_available_databases() == []

    def test_panel_click_without_databases_emits_clicked(self, qapp):
        """Click sem lista de bancos deve emitir database_clicked (fallback)"""
        panel = BlockDatabasePanel()
        clicked = []
        panel.database_clicked.connect(lambda: clicked.append(True))

        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QEvent

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        panel.mousePressEvent(event)
        assert len(clicked) == 1

    def test_panel_click_with_databases_shows_menu(self, qapp):
        """Click com lista de bancos deve chamar _show_database_menu"""
        panel = BlockDatabasePanel()
        panel.set_available_databases(["db1", "db2"])

        clicked = []
        panel.database_clicked.connect(lambda: clicked.append(True))

        with patch.object(panel, "_show_database_menu") as mock_menu:
            from PyQt6.QtGui import QMouseEvent
            from PyQt6.QtCore import QEvent

            event = QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(10, 10),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            panel.mousePressEvent(event)
            mock_menu.assert_called_once()
            # database_clicked NAO deve ser emitido quando tem databases
            assert len(clicked) == 0

    def test_panel_has_database_selected_signal(self, qapp):
        """Panel deve ter sinal database_selected"""
        panel = BlockDatabasePanel()
        assert hasattr(panel, "database_selected")

    def test_codeblock_set_available_databases(self, qapp):
        """CodeBlock.set_available_databases deve delegar para db_panel"""
        block = CodeBlock()
        block.set_available_databases(["alpha", "beta"])
        assert block.db_panel.get_available_databases() == ["alpha", "beta"]

    def test_codeblock_database_selected_updates_state(self, qapp):
        """Selecionar banco via menu deve atualizar _database_name e emitir"""
        block = CodeBlock()
        changes = []
        block.database_changed.connect(lambda blk, db: changes.append((blk, db)))

        # Simular selecao via sinal do panel
        block.db_panel.database_selected.emit("analytics")

        assert block._database_name == "analytics"
        assert len(changes) == 1
        assert changes[0][1] == "analytics"

    def test_codeblock_database_selected_none_resets(self, qapp):
        """Selecionar 'Default' (None/empty) deve resetar banco"""
        block = CodeBlock()
        block._database_name = "old_db"

        block.db_panel.database_selected.emit("")

        assert block._database_name is None
