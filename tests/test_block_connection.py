"""
Testes para conexao por bloco SQL

Funcionalidades testadas:
1. BlockConnectionPanel: panel clicavel com icone + nome
2. Drag & drop de conexoes para blocos SQL
3. Logica: bloco sem conexao usa conexao da aba, bloco com conexao usa a propria
4. Persistencia: to_dict/from_dict salvam/restauram conexao e db_type
5. Sinais: click no panel -> dialogo, drop -> atribuicao
6. execute_sql signal passa connection_name e block_name
"""

import pytest
import pandas as pd
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from PyQt6.QtCore import Qt, QMimeData, QPoint, QPointF
from PyQt6.QtGui import QDropEvent, QDragEnterEvent
from PyQt6.QtWidgets import QApplication

from src.editors.code_block import CodeBlock, BlockConnectionPanel
from src.editors.block_editor import BlockEditor
from src.ui.components.session_widget import SessionWidget


# Fixture autouse para evitar hang do QScintilla focus em testes
@pytest.fixture(autouse=True)
def _no_focus_editor(monkeypatch):
    """Desabilita focus_editor para evitar hang do QScintilla em testes"""
    monkeypatch.setattr(CodeBlock, "focus_editor", lambda self: None)


# ===== BlockConnectionPanel =====


class TestBlockConnectionPanel:
    """Testes para o panel de conexao clicavel"""

    def test_panel_initial_state(self, qapp):
        """Panel deve iniciar sem conexao (padrao da aba)"""
        panel = BlockConnectionPanel()
        assert panel.get_connection_name() is None
        assert panel._db_type is None
        assert panel.name_label.text() == "Padrao da aba"

    def test_panel_set_connection(self, qapp):
        """set_connection deve atualizar nome e db_type"""
        panel = BlockConnectionPanel()
        panel.set_connection("MinhaConn", "mysql")

        assert panel.get_connection_name() == "MinhaConn"
        assert panel._db_type == "mysql"
        assert panel.name_label.text() == "MinhaConn"

    def test_panel_set_connection_none_resets(self, qapp):
        """set_connection(None) deve voltar para 'Padrao da aba'"""
        panel = BlockConnectionPanel()
        panel.set_connection("MinhaConn", "mysql")

        panel.set_connection(None, None)
        assert panel.get_connection_name() is None
        assert panel.name_label.text() == "Padrao da aba"

    def test_panel_accepts_drops(self, qapp):
        """Panel deve aceitar drops"""
        panel = BlockConnectionPanel()
        assert panel.acceptDrops()

    def test_panel_click_emits_signal(self, qapp):
        """Click no panel deve emitir connection_clicked"""
        panel = BlockConnectionPanel()
        clicked = []
        panel.connection_clicked.connect(lambda: clicked.append(True))

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
        """Drop de conexao deve emitir connection_dropped(name, db_type)"""
        panel = BlockConnectionPanel()
        dropped = []
        panel.connection_dropped.connect(lambda name, db_type: dropped.append((name, db_type)))

        # Criar MimeData simulando drag de conexao
        mime_data = QMimeData()
        mime_data.setData("application/x-connection-name", b"TestConn")
        mime_data.setData("application/x-db-type", b"postgresql")

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
        assert dropped[0] == ("TestConn", "postgresql")

    def test_panel_drag_enter_accepts_connection_mime(self, qapp):
        """dragEnterEvent deve aceitar mime application/x-connection-name"""
        panel = BlockConnectionPanel()

        mime_data = QMimeData()
        mime_data.setData("application/x-connection-name", b"TestConn")

        # Usar mock para dragEnterEvent pois QDragEnterEvent nao e facilmente instanciavel
        event = MagicMock()
        event.mimeData.return_value = mime_data
        panel.dragEnterEvent(event)
        event.acceptProposedAction.assert_called_once()


# ===== CodeBlock Connection =====


class TestCodeBlockConnection:
    """Testes para conexao per-block no CodeBlock"""

    def test_block_has_connection_name_attribute(self, qapp):
        """CodeBlock deve ter atributo connection_name"""
        block = CodeBlock()
        assert hasattr(block, "_connection_name")
        assert block.get_connection_name() is None

    def test_block_has_conn_panel(self, qapp):
        """CodeBlock deve ter conn_panel (BlockConnectionPanel)"""
        block = CodeBlock()
        assert hasattr(block, "conn_panel")
        assert isinstance(block.conn_panel, BlockConnectionPanel)

    def test_block_set_connection_name(self, qapp):
        """set_connection_name deve atualizar panel e _connection_name"""
        block = CodeBlock(default_language="sql")
        block.set_connection_name("MyConn", "mysql")

        assert block.get_connection_name() == "MyConn"
        assert block.conn_panel.get_connection_name() == "MyConn"
        assert block.conn_panel._db_type == "mysql"

    def test_block_connection_dropped_updates_state(self, qapp):
        """Drop de conexao no panel deve atualizar _connection_name"""
        block = CodeBlock(default_language="sql")
        block._on_connection_dropped("DroppedConn", "sqlserver")

        assert block.get_connection_name() == "DroppedConn"
        assert block.conn_panel.get_connection_name() == "DroppedConn"

    def test_block_panel_click_emits_select_connection(self, qapp):
        """Click no panel do bloco deve emitir select_connection_requested"""
        block = CodeBlock(default_language="sql")
        requested = []
        block.select_connection_requested.connect(lambda b: requested.append(b))

        block._on_connection_panel_clicked()
        assert len(requested) == 1
        assert requested[0] is block

    def test_block_to_dict_saves_connection(self, qapp):
        """to_dict deve salvar connection_name e db_type"""
        block = CodeBlock(default_language="sql")
        block.set_connection_name("SavedConn", "postgresql")

        data = block.to_dict()
        assert data["connection_name"] == "SavedConn"
        assert data["db_type"] == "postgresql"

    def test_block_to_dict_no_connection_no_key(self, qapp):
        """to_dict sem conexao customizada nao deve ter chave connection_name"""
        block = CodeBlock(default_language="sql")
        data = block.to_dict()
        assert "connection_name" not in data

    def test_block_from_dict_restores_connection(self, qapp):
        """from_dict deve restaurar connection_name e atualizar panel"""
        data = {"language": "sql", "code": "SELECT 1", "connection_name": "RestoredConn", "db_type": "mysql"}
        block = CodeBlock.from_dict(data)

        assert block.get_connection_name() == "RestoredConn"
        assert block.conn_panel.get_connection_name() == "RestoredConn"
        assert block.conn_panel._db_type == "mysql"

    def test_block_from_dict_without_connection(self, qapp):
        """from_dict sem connection_name deve manter None"""
        data = {"language": "sql", "code": "SELECT 1"}
        block = CodeBlock.from_dict(data)
        assert block.get_connection_name() is None

    def test_block_connection_none_means_tab_default(self, qapp):
        """get_connection_name() == None significa usar conexao da aba"""
        block = CodeBlock(default_language="sql")
        assert block.get_connection_name() is None  # padrao da aba


# ===== BlockEditor Connection Signal =====


class TestBlockEditorConnection:
    """Testes para sinais de conexao no BlockEditor"""

    def test_block_editor_has_select_connection_signal(self, qapp):
        """BlockEditor deve ter sinal select_connection_for_block"""
        editor = BlockEditor()
        assert hasattr(editor, "select_connection_for_block")

    def test_block_editor_propagates_select_connection(self, qapp):
        """Click em panel de bloco deve propagar para BlockEditor"""
        editor = BlockEditor()
        requested = []
        editor.select_connection_for_block.connect(lambda b: requested.append(b))

        block = editor._blocks[0]
        block.set_language("sql")

        block._on_connection_panel_clicked()

        assert len(requested) == 1
        assert requested[0] is block

    def test_execute_sql_signal_carries_connection_info(self, qapp):
        """execute_sql signal deve passar block_name e connection_name"""
        editor = BlockEditor()

        # Usar bloco padrao que ja existe
        block = editor._blocks[0]
        block.set_language("sql")
        block.set_code("SELECT 1")
        block._connection_name = "TestConn"

        # Capturar signal
        emitted = []
        editor.execute_sql.connect(lambda q, bn, cn: emitted.append((q, bn, cn)))

        editor._execute_block(block)

        assert len(emitted) == 1
        query, block_name, connection_name = emitted[0]
        assert query == "SELECT 1"
        assert block_name == block.get_block_name()
        assert connection_name == "TestConn"

    def test_execute_sql_signal_none_connection(self, qapp):
        """execute_sql sem conexao customizada deve passar None"""
        editor = BlockEditor()

        # Usar bloco padrao
        block = editor._blocks[0]
        block.set_language("sql")
        block.set_code("SELECT 1")

        emitted = []
        editor.execute_sql.connect(lambda q, bi, cn: emitted.append((q, bi, cn)))

        editor._execute_block(block)

        assert len(emitted) == 1
        _, _, connection_name = emitted[0]
        assert connection_name is None

    def test_execute_all_passes_connection_in_queue(self, qapp):
        """execute_all_blocks deve passar connection_name na fila"""
        editor = BlockEditor()

        # Usar bloco padrao como bloco1 e adicionar bloco2
        block1 = editor._blocks[0]
        block1.set_language("sql")
        block1.set_code("SELECT 1")

        block2 = editor.add_block(language="sql", code="SELECT 2")
        block2._connection_name = "CustomConn"

        queue = []
        editor.execute_queue.connect(lambda q: queue.extend(q))

        editor.execute_all_blocks()

        assert len(queue) == 2

        # Bloco 1: sem conexao customizada
        assert queue[0][0] == "sql"
        assert queue[0][3] == block1.get_block_name()  # block_name
        assert queue[0][4] is None  # connection_name

        # Bloco 2: com conexao customizada
        assert queue[1][0] == "sql"
        assert queue[1][3] == block2.get_block_name()  # block_name
        assert queue[1][4] == "CustomConn"


# ===== Connection Resolution Logic =====


class TestConnectionResolution:
    """Testes para logica de resolucao de conexao"""

    def test_no_block_connection_uses_session_default(self, qapp):
        """Sem conexao no bloco, deve usar conexao da sessao (aba)"""
        block = CodeBlock(default_language="sql")
        # Sem conexao customizada -> get_connection_name() retorna None
        assert block.get_connection_name() is None
        # Isso significa que ao executar, usara a conexao da sessao/aba

    def test_block_connection_name_overrides_session(self, qapp):
        """Conexao definida no bloco deve ter prioridade sobre conexao da sessao"""
        block = CodeBlock(default_language="sql")
        block.set_connection_name("BlockSpecificConn", "mysql")

        # Bloco tem conexao propria
        assert block.get_connection_name() == "BlockSpecificConn"

    def test_on_execute_sql_no_connection_uses_session(self, qapp):
        """_on_execute_sql sem connection_name verifica session.is_connected"""
        from src.core.session import Session

        session = Session("test")
        # Sessao SEM conexao
        widget = SessionWidget(session)

        # Sem connection_name e sem sessao conectada -> erro
        outputs = []
        widget.append_output = lambda text, error=False: outputs.append(text)
        widget.status_changed = MagicMock()

        widget._on_execute_sql("SELECT 1", block_name="bloco1", connection_name=None)

        # Deve ter emitido erro porque sessao nao esta conectada
        assert any("Nenhuma" in o or "ERRO" in o for o in outputs)

    def test_on_execute_sql_with_connection_auto_connects(self, qapp):
        """_on_execute_sql com connection_name deve auto-conectar"""
        from src.core.session import Session

        session = Session("test")
        widget = SessionWidget(session)

        mock_config = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "database": "testdb",
            "username": "user",
            "password": "pass",
            "use_windows_auth": False,
        }

        mock_db_connector = MagicMock()
        mock_db_connector.is_connected = True

        with (
            patch("src.database.connection_manager.ConnectionManager") as MockMgr,
            patch("src.database.database_connector.DatabaseConnector") as MockConn,
        ):
            mock_manager = MockMgr.return_value
            mock_manager.get_connection.return_value = None  # Nao conectado ainda
            mock_manager.get_connection_config.return_value = mock_config
            mock_manager.connections = {}

            MockConn.return_value = mock_db_connector

            # Mock para nao criar thread real
            widget._is_executing = True  # Forca ir para a fila ao inves de executar

            widget._on_execute_sql("SELECT 1", block_name="bloco1", connection_name="BlockConn")

            # Deve ter tentado auto-conectar
            MockConn.return_value.connect.assert_called_once_with(
                db_type="mysql",
                host="localhost",
                port=3306,
                database="testdb",
                username="user",
                password="pass",
                use_windows_auth=False,
            )


# ===== SessionWidget Dialog =====


class TestSessionWidgetDialog:
    """Testes para dialogo de selecao de conexao"""

    def test_block_select_connection_opens_dialog(self, qapp):
        """Click no panel deve abrir ConnectionsManagerDialog"""
        from src.core.session import Session

        session = Session("test")
        widget = SessionWidget(session)

        block = MagicMock()
        block.set_connection_name = MagicMock()

        with (
            patch("src.database.connection_manager.ConnectionManager") as MockMgr,
            patch("src.ui.dialogs.connections_manager_dialog.ConnectionsManagerDialog") as MockDialog,
        ):
            mock_manager = MockMgr.return_value
            mock_manager.get_connection_config.return_value = {"db_type": "postgresql"}

            mock_dialog = MockDialog.return_value
            mock_dialog.exec.return_value = True
            mock_dialog.selected_connection = "SelectedConn"

            widget._on_block_select_connection(block)

            # Deve ter chamado set_connection_name no bloco
            block.set_connection_name.assert_called_once_with("SelectedConn", "postgresql")

    def test_block_select_connection_cancelled(self, qapp):
        """Cancelar dialogo nao deve alterar conexao do bloco"""
        from src.core.session import Session

        session = Session("test")
        widget = SessionWidget(session)

        block = MagicMock()

        with (
            patch("src.database.connection_manager.ConnectionManager") as MockMgr,
            patch("src.ui.dialogs.connections_manager_dialog.ConnectionsManagerDialog") as MockDialog,
        ):
            mock_dialog = MockDialog.return_value
            mock_dialog.exec.return_value = False

            widget._on_block_select_connection(block)

            # Nao deve ter chamado set_connection_name
            block.set_connection_name.assert_not_called()


# ===== Drag & Drop =====


class TestDragAndDrop:
    """Testes para drag & drop de conexoes"""

    def test_draggable_connection_list_exists(self, qapp):
        """DraggableConnectionList deve existir e ser importavel"""
        from src.ui.components.connection_panel import DraggableConnectionList

        lst = DraggableConnectionList()
        assert lst.dragEnabled()

    def test_connection_item_has_data(self, qapp):
        """ConnectionItem deve ter connection_name e config"""
        from src.ui.components.connection_panel import ConnectionItem

        config = {"db_type": "mysql", "host": "localhost", "database": "test"}
        item = ConnectionItem("TestConn", config)
        assert item.connection_name == "TestConn"
        assert item.config == config

    def test_drop_on_panel_updates_block(self, qapp):
        """Arrastar conexao para panel do bloco deve atualizar conexao"""
        block = CodeBlock(default_language="sql")

        # Simular drop
        mime_data = QMimeData()
        mime_data.setData("application/x-connection-name", b"DroppedConn")
        mime_data.setData("application/x-db-type", b"sqlserver")

        event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        block.conn_panel.dropEvent(event)

        assert block.get_connection_name() == "DroppedConn"
        assert block.conn_panel._db_type == "sqlserver"

    def test_mime_data_format(self, qapp):
        """MimeData deve usar formato application/x-connection-name"""
        mime_data = QMimeData()
        mime_data.setData("application/x-connection-name", "TestConn".encode("utf-8"))
        mime_data.setData("application/x-db-type", "mysql".encode("utf-8"))

        assert mime_data.hasFormat("application/x-connection-name")
        assert mime_data.data("application/x-connection-name").data().decode("utf-8") == "TestConn"
        assert mime_data.data("application/x-db-type").data().decode("utf-8") == "mysql"


# ===== Persistencia =====


class TestConnectionPersistence:
    """Testes para persistencia de conexao nos blocos"""

    def test_roundtrip_to_dict_from_dict(self, qapp):
        """to_dict -> from_dict deve preservar conexao"""
        block1 = CodeBlock(default_language="sql")
        block1.set_code("SELECT * FROM users")
        block1.set_connection_name("ProdDB", "sqlserver")

        data = block1.to_dict()

        block2 = CodeBlock.from_dict(data)

        assert block2.get_connection_name() == "ProdDB"
        assert block2.conn_panel._db_type == "sqlserver"
        assert block2.get_code() == "SELECT * FROM users"
        assert block2.get_language() == "sql"

    def test_roundtrip_without_connection(self, qapp):
        """to_dict -> from_dict sem conexao deve manter None"""
        block1 = CodeBlock(default_language="python")
        block1.set_code('print("hello")')

        data = block1.to_dict()
        block2 = CodeBlock.from_dict(data)

        assert block2.get_connection_name() is None
        assert block2.get_language() == "python"

    def test_block_editor_to_list_preserves_connections(self, qapp):
        """BlockEditor.to_list deve preservar connection_name dos blocos"""
        editor = BlockEditor()

        # Usar bloco padrao como bloco1 e adicionar bloco2
        block1 = editor._blocks[0]
        block1.set_language("sql")
        block1.set_code("SELECT 1")

        block2 = editor.add_block(language="sql", code="SELECT 2")
        block2.set_connection_name("SpecialDB", "postgresql")

        blocks_data = editor.to_list()

        assert len(blocks_data) == 2
        assert "connection_name" not in blocks_data[0]
        assert blocks_data[1]["connection_name"] == "SpecialDB"
        assert blocks_data[1]["db_type"] == "postgresql"

    def test_block_editor_from_list_restores_connections(self, qapp):
        """BlockEditor.from_list deve restaurar connection_name nos blocos"""
        editor = BlockEditor()

        blocks_data = [
            {"language": "sql", "code": "SELECT 1"},
            {"language": "sql", "code": "SELECT 2", "connection_name": "SpecialDB", "db_type": "mysql"},
        ]

        editor.from_list(blocks_data)
        qapp.processEvents()

        assert editor._blocks[0].get_connection_name() is None
        assert editor._blocks[1].get_connection_name() == "SpecialDB"


# ===== Queue Processing =====


class TestQueueProcessing:
    """Testes para processamento de fila com conexao per-block"""

    def test_process_queue_5_tuple(self, qapp):
        """_process_next_in_queue deve suportar tuplas de 5 elementos"""
        from src.core.session import Session

        session = Session("test")
        widget = SessionWidget(session)

        mock_block = MagicMock()

        widget._execution_queue = [("sql", "SELECT 1", mock_block, "bloco1", "CustomConn")]

        with patch.object(widget, "_on_execute_sql") as mock_exec:
            widget._process_next_in_queue()
            mock_exec.assert_called_once_with("SELECT 1", block_name="bloco1", connection_name="CustomConn")

    def test_process_queue_3_tuple(self, qapp):
        """_process_next_in_queue deve suportar tuplas de 3 elementos (legado)"""
        from src.core.session import Session

        session = Session("test")
        widget = SessionWidget(session)

        mock_block = MagicMock()

        widget._execution_queue = [("sql", "SELECT 1", mock_block)]

        with patch.object(widget, "_on_execute_sql") as mock_exec:
            widget._process_next_in_queue()
            mock_exec.assert_called_once_with("SELECT 1", block_name=None, connection_name=None)

    def test_process_queue_2_tuple(self, qapp):
        """_process_next_in_queue deve suportar tuplas de 2 elementos (legado)"""
        from src.core.session import Session

        session = Session("test")
        widget = SessionWidget(session)

        widget._execution_queue = [("python", 'print("hi")')]

        with patch.object(widget, "_on_execute_python") as mock_exec:
            widget._process_next_in_queue()
            mock_exec.assert_called_once_with('print("hi")')
