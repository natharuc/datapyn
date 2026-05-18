"""
Testes completos do sistema de blocos

Testa todas as funcionalidades do BlockEditor e CodeBlock,
simulando interações reais do usuário.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from src.editors.code_block import CodeBlock
from src.editors.block_editor import BlockEditor
from src.core.theme_manager import ThemeManager
from src.core.session import Session
from src.ui.components.session_widget import SessionWidget


class TestCodeBlock:
    """Testes do componente CodeBlock"""

    @pytest.fixture
    def theme_manager(self):
        return ThemeManager()

    @pytest.fixture
    def block(self, theme_manager, qtbot):
        block = CodeBlock(theme_manager=theme_manager)
        qtbot.addWidget(block)
        return block

    def test_block_creation(self, block):
        """Bloco deve ser criado com valores padrão"""
        assert block.get_language() == "sql"  # Padrão agora é SQL
        assert block.get_code() == ""
        assert not block.is_focused()

    def test_set_language_python(self, block):
        """Deve permitir mudar para Python"""
        block.set_language("python")
        assert block.get_language() == "python"

    def test_set_language_sql(self, block):
        """Deve permitir mudar para SQL"""
        block.set_language("sql")
        assert block.get_language() == "sql"

    def test_set_code(self, block):
        """Deve permitir definir código"""
        block.set_code("print('hello')")
        assert block.get_code() == "print('hello')"

    def test_language_change_updates_lexer(self, block):
        """Mudar linguagem deve atualizar o lexer"""
        # Começar com Python (diferente do padrão SQL)
        block.set_language("python")
        assert block.editor.get_language() == "python"

        # Mudar para SQL
        block.set_language("sql")
        assert block.editor.get_language() == "sql"

    def test_execute_signal_emitted(self, block, qtbot):
        """Clicar no botão executar deve emitir sinal"""
        with qtbot.waitSignal(block.execute_requested, timeout=1000):
            block.run_btn.click()

    def test_remove_signal_emitted(self, block, qtbot):
        """Clicar no botão remover deve emitir sinal"""
        with qtbot.waitSignal(block.remove_requested, timeout=1000):
            block.remove_btn.click()

    def test_language_changed_signal(self, block, qtbot):
        """Mudar linguagem deve emitir sinal"""
        # Bloco começa em SQL (index 0), mudar para Python (index 1) para garantir mudança
        with qtbot.waitSignal(block.language_changed, timeout=1000):
            block.lang_combo.setCurrentIndex(1)  # Python

    def test_to_dict_serialization(self, block):
        """Deve serializar corretamente"""
        block.set_language("sql")
        block.set_code("SELECT 1")

        data = block.to_dict()
        assert data["language"] == "sql"
        assert data["code"] == "SELECT 1"

    def test_sql_parameters_panel_appears_for_detected_tokens(self, block):
        """Bloco SQL deve detectar @param e mostrar painel lateral."""
        block.set_language("sql")
        block.set_code("select * from pessoa where id = @pessoaId")

        params = block.get_sql_parameters()
        assert [param["name"] for param in params] == ["pessoaId"]
        assert not block.sql_parameters_panel.isHidden()

    def test_sql_parameters_persist_in_block_dict(self, block):
        """to_dict/from_dict devem preservar parametros SQL customizados."""
        block.set_language("sql")
        block.set_code("select * from pessoa where id = @pessoaId")
        params = block.get_sql_parameters()
        params[0]["label"] = "Pessoa"
        params[0]["sql_type"] = "integer"
        params[0]["value"] = "55"
        block.set_sql_parameters(params)

        data = block.to_dict()

        assert data["sql_parameters"][0]["name"] == "pessoaId"
        assert data["sql_parameters"][0]["label"] == "Pessoa"
        assert data["sql_parameters"][0]["sql_type"] == "integer"
        assert data["sql_parameters"][0]["value"] == "55"

    def test_sql_parameters_refresh_from_schema_when_available(self, block):
        """Schema carregado deve atualizar tipo inferido do parametro."""
        block.set_language("sql")
        block.set_code("select * from dbo.pedidos where encerramento = @encerramento")

        block.set_sql_schema(
            {
                "columns": {
                    "dbo.pedidos": [
                        {"name": "encerramento", "type": "date"},
                    ]
                }
            }
        )

        params = block.get_sql_parameters()
        assert params[0]["sql_type"] == "date"
        assert params[0]["default_value"] == ""

    def test_sql_parameters_panel_can_be_disabled_for_manual_variables(self, block):
        block.set_language("sql")
        block.set_code("select * from pessoa where id = @pessoaId")

        block.sql_parameters_panel.close_btn.click()

        assert block.is_sql_parameters_enabled() is False
        assert block.sql_parameters_panel.isHidden()
        assert not block.show_sql_parameters_btn.isHidden()
        assert block.get_sql_parameters_for_query("select * from pessoa where id = @pessoaId") == []

    def test_sql_parameters_manual_mode_persists_in_block_dict(self, theme_manager, qtbot):
        block = CodeBlock(theme_manager=theme_manager)
        qtbot.addWidget(block)
        block.set_language("sql")
        block.set_code("select * from pessoa where id = @pessoaId")
        block.sql_parameters_panel.close_btn.click()

        data = block.to_dict()
        restored = CodeBlock.from_dict(data, theme_manager)
        qtbot.addWidget(restored)

        assert data["sql_parameters_enabled"] is False
        assert restored.is_sql_parameters_enabled() is False
        assert restored.sql_parameters_panel.isHidden()
        assert not restored.show_sql_parameters_btn.isHidden()

    def test_show_parameters_button_reenables_panel(self, block):
        block.set_language("sql")
        block.set_code("select * from pessoa where id = @pessoaId")
        block.sql_parameters_panel.close_btn.click()

        block.show_sql_parameters_btn.click()

        assert block.is_sql_parameters_enabled() is True
        assert block.show_sql_parameters_btn.isHidden()
        assert not block.sql_parameters_panel.isHidden()
        assert [param["name"] for param in block.get_sql_parameters_for_query(block.get_code())] == ["pessoaId"]

    def test_execute_sql_ignores_custom_parameters_in_manual_mode(self, qapp):
        editor = BlockEditor()
        block = editor._blocks[0]
        block.set_language("sql")
        block.set_code("declare @id int = 1; select @id")
        block.sql_parameters_panel.close_btn.click()

        emitted = []
        editor.execute_sql.connect(lambda q, bn, cn, dn, sp: emitted.append((q, bn, cn, dn, sp)))

        editor._execute_block(block)

        assert len(emitted) == 1
        assert emitted[0][4] == []

    def test_sql_parameters_for_selected_query_filters_tokens(self, block):
        """Execucao de selecao deve usar so parametros presentes no SQL selecionado."""
        block.set_language("sql")
        block.set_code("select * from pessoa where id = @id and loja = @loja")
        params = block.get_sql_parameters()

        selected = block.get_sql_parameters_for_query("select * from pessoa where id = @id")

        assert [param["name"] for param in params] == ["id", "loja"]
        assert [param["name"] for param in selected] == ["id"]

    def test_sql_parameters_are_removed_when_query_token_is_deleted(self, block):
        block.set_language("sql")
        block.set_code("select * from pessoa where id = @id")

        block.set_code("select * from pessoa")

        assert block.get_sql_parameters() == []
        assert block.sql_parameters_panel.isHidden()

    def test_schedule_sql_parameter_sync_removes_orphans_without_waiting(self, block):
        block._sql_parameters = [
            {
                "id": "sqlparam:id",
                "name": "id",
                "order": 0,
                "sql_type": "integer",
                "input_kind": "value",
                "value": "1",
                "required": True,
                "options": [],
                "multi_select": False,
            }
        ]

        with patch.object(block, "get_code", return_value="select * from pessoa"):
            with patch.object(block, "sync_sql_parameters_from_query") as sync_mock:
                with patch.object(block._sql_parameter_sync_timer, "start") as timer_start:
                    block._schedule_sql_parameter_sync()

        assert sync_mock.call_count == 1
        timer_start.assert_not_called()

    def test_schedule_sql_parameter_sync_keeps_debounce_when_tokens_still_exist(self, block):
        block._sql_parameters = [
            {
                "id": "sqlparam:id",
                "name": "id",
                "order": 0,
                "sql_type": "integer",
                "input_kind": "value",
                "value": "1",
                "required": True,
                "options": [],
                "multi_select": False,
            }
        ]

        with patch.object(block, "get_code", return_value="select * from pessoa where id = @id and loja = @loja"):
            with patch.object(block, "sync_sql_parameters_from_query") as sync_mock:
                with patch.object(block._sql_parameter_sync_timer, "start") as timer_start:
                    block._schedule_sql_parameter_sync()

        sync_mock.assert_not_called()
        assert timer_start.call_count == 1

    def test_from_dict_deserialization(self, theme_manager, qtbot):
        """Deve deserializar corretamente"""
        data = {"language": "python", "code": "x = 1"}
        block = CodeBlock.from_dict(data, theme_manager)
        qtbot.addWidget(block)

        assert block.get_language() == "python"
        assert block.get_code() == "x = 1"

    def test_from_dict_restores_sql_parameters(self, theme_manager, qtbot):
        """from_dict deve restaurar parametros customizados."""
        data = {
            "language": "sql",
            "code": "select * from pessoa where id = @id",
            "sql_parameters": [
                {
                    "id": "sqlparam:id",
                    "name": "id",
                    "order": 0,
                    "sql_type": "integer",
                    "input_kind": "value",
                    "value": "9",
                    "required": True,
                    "options": [],
                    "multi_select": False,
                }
            ],
        }
        block = CodeBlock.from_dict(data, theme_manager)
        qtbot.addWidget(block)

        params = block.get_sql_parameters()
        assert params[0]["name"] == "id"
        assert params[0]["sql_type"] == "integer"
        assert params[0]["value"] == "9"

    def test_running_state(self, block):
        """Deve mudar estado de execucao e mostrar tempo"""
        # Botao usa icone (sem texto) ao inves de caracteres unicode
        assert block.run_btn.text() == ""

        block.set_running(True)
        # Initially shows "Running" (or localized equivalent)
        assert block.status_label.text() != ""

        block.set_running(False)
        # Apos execucao, mostra tempo de execucao
        assert any(unit in block.status_label.text() for unit in ["us", "ms", "s"]) or block.status_label.text() == ""


class TestBlockRunningTimer:
    """Tests for the elapsed time counter on running blocks"""

    @pytest.fixture
    def block(self, qtbot):
        b = CodeBlock(theme_manager=ThemeManager())
        qtbot.addWidget(b)
        return b

    def test_timer_starts_on_running(self, block):
        """Timer must start when block enters running state"""
        block.set_running(True)
        assert block._execution_tick_timer.isActive()
        block.set_running(False)

    def test_timer_stops_on_finished(self, block):
        """Timer must stop when block finishes running"""
        block.set_running(True)
        assert block._execution_tick_timer.isActive()
        block.set_running(False)
        assert not block._execution_tick_timer.isActive()

    def test_timer_stops_on_error(self, block):
        """Timer must stop when block has error"""
        block.set_running(True)
        block.set_error()
        assert not block._execution_tick_timer.isActive()

    def test_timer_stops_on_cancel(self, block):
        """Timer must stop when block is cancelled"""
        block.set_running(True)
        block.set_cancelled()
        assert not block._execution_tick_timer.isActive()

    def test_label_updates_with_elapsed(self, block, qtbot):
        """Status label must show elapsed time while running"""
        import time
        block._execution_start_time = time.time() - 2.5  # Fake 2.5s ago
        block._is_running = True
        block._update_running_elapsed()
        text = block.status_label.text()
        # Must contain the elapsed time (around 2.5s)
        assert "2." in text or "3." in text  # tolerance for timing

    def test_format_execution_time_seconds(self, block):
        """Format must use seconds for < 60s"""
        assert "s" in block._format_execution_time(5.23)
        assert "5.23" in block._format_execution_time(5.23)

    def test_format_execution_time_minutes(self, block):
        """Format must show minutes for >= 60s"""
        result = block._format_execution_time(125.3)
        assert "2m" in result
        assert "5." in result

    def test_format_execution_time_milliseconds(self, block):
        """Format must use ms for < 1s"""
        result = block._format_execution_time(0.345)
        assert "ms" in result


class TestBlockEditor:
    """Testes do container BlockEditor"""

    @pytest.fixture
    def theme_manager(self):
        return ThemeManager()

    @pytest.fixture
    def editor(self, theme_manager, qtbot):
        editor = BlockEditor(theme_manager=theme_manager)
        qtbot.addWidget(editor)
        return editor

    def test_starts_with_one_block(self, editor):
        """Deve iniciar com um bloco"""
        assert editor.get_block_count() == 1

    def test_add_block(self, editor):
        """Deve adicionar blocos"""
        editor.add_block()
        assert editor.get_block_count() == 2

        editor.add_block()
        assert editor.get_block_count() == 3

    def test_add_block_with_language(self, editor):
        """Deve adicionar bloco com linguagem específica"""
        # Primeiro bloco já existe (SQL), adicionar mais um vai ser Python por padrão
        # Mas se especificar explicitamente a linguagem, deve respeitar
        block = editor.add_block(language="python")
        assert block.get_language() == "python"

    def test_add_block_with_code(self, editor):
        """Deve adicionar bloco com código"""
        block = editor.add_block(code="SELECT 1")
        assert block.get_code() == "SELECT 1"

    def test_remove_block(self, editor):
        """Deve remover blocos"""
        editor.add_block()
        editor.add_block()
        assert editor.get_block_count() == 3

        blocks = editor.get_blocks()
        editor.remove_block(blocks[1])
        assert editor.get_block_count() == 2

    def test_cannot_remove_last_block(self, editor):
        """Não deve remover o último bloco"""
        assert editor.get_block_count() == 1
        blocks = editor.get_blocks()
        editor.remove_block(blocks[0])
        # Ainda tem 1 bloco (limpa em vez de remover)
        assert editor.get_block_count() == 1

    def test_clear_blocks(self, editor):
        """Deve limpar todos os blocos"""
        editor.add_block()
        editor.add_block()
        assert editor.get_block_count() == 3

        editor.clear_blocks()
        assert editor.get_block_count() == 1

    def test_execute_sql_signal(self, editor, qtbot):
        """Deve emitir sinal SQL quando bloco é SQL"""
        blocks = editor.get_blocks()
        blocks[0].set_language("sql")
        blocks[0].set_code("SELECT 1")

        with qtbot.waitSignal(editor.execute_sql, timeout=1000) as blocker:
            editor._execute_block(blocks[0])

        assert blocker.args[0] == "SELECT 1"

    def test_execute_sql_signal_includes_custom_parameters(self, editor, qtbot):
        """Deve emitir parametros customizados junto com SQL."""
        block = editor.get_blocks()[0]
        block.set_language("sql")
        block.set_code("select * from pessoa where id = @id")
        params = block.get_sql_parameters()
        params[0]["sql_type"] = "integer"
        params[0]["value"] = "12"
        block.set_sql_parameters(params)

        with qtbot.waitSignal(editor.execute_sql, timeout=1000) as blocker:
            editor._execute_block(block)

        emitted_params = blocker.args[4]
        assert blocker.args[0] == "select * from pessoa where id = @id"
        assert emitted_params[0]["name"] == "id"
        assert emitted_params[0]["sql_type"] == "integer"
        assert emitted_params[0]["value"] == "12"

    def test_execute_python_signal(self, editor, qtbot):
        """Deve emitir sinal Python quando bloco é Python"""
        blocks = editor.get_blocks()
        blocks[0].set_language("python")
        blocks[0].set_code("print(1)")

        with qtbot.waitSignal(editor.execute_python, timeout=1000) as blocker:
            editor._execute_block(blocks[0])

        assert blocker.args[0] == "print(1)"

    def test_change_language_then_execute(self, editor, qtbot):
        """Mudar linguagem e executar deve usar a nova linguagem"""
        blocks = editor.get_blocks()

        # Começa como Python
        blocks[0].set_language("python")
        blocks[0].set_code("x = 1")

        # Muda para SQL
        blocks[0].set_language("sql")
        blocks[0].set_code("SELECT 1")

        # Deve emitir SQL, não Python
        with qtbot.waitSignal(editor.execute_sql, timeout=1000) as blocker:
            editor._execute_block(blocks[0])

        assert blocker.args[0] == "SELECT 1"

    def test_multiple_blocks_different_languages(self, editor, qtbot):
        """Múltiplos blocos com linguagens diferentes"""
        # Bloco 1: SQL
        blocks = editor.get_blocks()
        blocks[0].set_language("sql")
        blocks[0].set_code("SELECT 1")

        # Bloco 2: Python
        block2 = editor.add_block(language="python", code="print(1)")

        # Executar bloco SQL
        with qtbot.waitSignal(editor.execute_sql, timeout=1000):
            editor._execute_block(blocks[0])

        # Executar bloco Python
        with qtbot.waitSignal(editor.execute_python, timeout=1000):
            editor._execute_block(block2)

    def test_serialization_multiple_blocks(self, editor):
        """Deve serializar múltiplos blocos"""
        editor.get_blocks()[0].set_language("sql")
        editor.get_blocks()[0].set_code("SELECT 1")
        editor.add_block(language="python", code="x = 1")

        data = editor.to_list()

        assert len(data) == 2
        # Verificar campos principais (height pode variar)
        assert data[0]["language"] == "sql"
        assert data[0]["code"] == "SELECT 1"
        assert data[1]["language"] == "python"
        assert data[1]["code"] == "x = 1"

    def test_deserialization_multiple_blocks(self, editor):
        """Deve deserializar múltiplos blocos"""
        data = [
            {"language": "sql", "code": "SELECT 1"},
            {"language": "python", "code": "x = 1"},
        ]

        editor.from_list(data)

        blocks = editor.get_blocks()
        assert len(blocks) == 2
        assert blocks[0].get_language() == "sql"
        assert blocks[0].get_code() == "SELECT 1"
        assert blocks[1].get_language() == "python"
        assert blocks[1].get_code() == "x = 1"

    def test_from_list_restores_sql_parameter_manual_mode(self, editor):
        data = [
            {
                "language": "sql",
                "code": "select * from pessoa where id = @id",
                "sql_parameters": [
                    {
                        "id": "sqlparam:id",
                        "name": "id",
                        "order": 0,
                        "sql_type": "integer",
                        "input_kind": "value",
                        "value": "",
                        "default_value": "",
                        "required": True,
                        "options": [],
                        "multi_select": False,
                    }
                ],
                "sql_parameters_enabled": False,
            }
        ]

        editor.from_list(data)

        block = editor.get_blocks()[0]
        assert block.is_sql_parameters_enabled() is False
        assert block.sql_parameters_panel.isHidden()
        assert not block.show_sql_parameters_btn.isHidden()


class TestBlockEditorExecution:
    """Testes de execução do BlockEditor"""

    @pytest.fixture
    def theme_manager(self):
        return ThemeManager()

    @pytest.fixture
    def editor(self, theme_manager, qtbot):
        editor = BlockEditor(theme_manager=theme_manager)
        qtbot.addWidget(editor)
        return editor

    def test_execute_all_blocks_emits_correct_signals(self, editor, qtbot):
        """execute_all_blocks deve emitir fila com blocos corretos"""
        # Setup blocos
        editor.get_blocks()[0].set_language("sql")
        editor.get_blocks()[0].set_code("SELECT 1")
        editor.add_block(language="python", code="x = 1")

        # Captura sinal de fila
        queue_received = []
        editor.execute_queue.connect(lambda q: queue_received.extend(q))

        # Executa todos
        editor.execute_all_blocks()

        # Verifica que a fila contém os blocos na ordem
        # Formato novo: (language, code, block)
        assert len(queue_received) == 2
        assert queue_received[0][0] == "sql"
        assert queue_received[0][1] == "SELECT 1"
        assert queue_received[1][0] == "python"
        assert queue_received[1][1] == "x = 1"

    def test_empty_blocks_not_executed(self, editor, qtbot):
        """Blocos vazios não devem ser executados"""
        editor.get_blocks()[0].set_code("")  # Vazio
        editor.add_block(language="python", code="x = 1")

        queue_received = []
        editor.execute_queue.connect(lambda q: queue_received.extend(q))

        editor.execute_all_blocks()

        # Apenas o segundo bloco (não vazio)
        assert len(queue_received) == 1
        assert queue_received[0][0] == "python"
        assert queue_received[0][1] == "x = 1"

    def test_mark_execution_finished(self, editor):
        """Deve marcar blocos como não executando"""
        blocks = editor.get_blocks()
        blocks[0].set_running(True)

        editor.mark_execution_finished()

        assert not blocks[0]._is_running


class TestSessionWidgetWithBlocks:
    """Testes de integração SessionWidget + BlockEditor"""

    @pytest.fixture
    def theme_manager(self):
        return ThemeManager()

    @pytest.fixture
    def session(self):
        return Session(session_id="test-session", title="Test")

    @pytest.fixture
    def widget(self, session, theme_manager, qtbot):
        widget = SessionWidget(session=session, theme_manager=theme_manager)
        qtbot.addWidget(widget)
        return widget

    def test_widget_has_block_editor(self, widget):
        """Widget deve ter BlockEditor"""
        assert isinstance(widget.editor, BlockEditor)

    def test_execute_python_without_connection(self, widget, qtbot):
        """Python deve executar sem conexão"""
        # Setup bloco Python
        blocks = widget.editor.get_blocks()
        blocks[0].set_language("python")
        blocks[0].set_code("x = 1 + 1")

        # Não deve exigir conexão para Python
        # O sinal deve ser emitido
        with qtbot.waitSignal(widget.editor.execute_python, timeout=1000):
            widget.editor._execute_block(blocks[0])

    def test_sql_requires_connection(self, widget, qtbot):
        """SQL deve mostrar erro se sem conexão"""
        blocks = widget.editor.get_blocks()
        blocks[0].set_language("sql")
        blocks[0].set_code("SELECT 1")

        # Mock para capturar output
        outputs = []

        # Mock dos métodos de log diretamente no widget
        widget._log_error = lambda msg: outputs.append(msg)
        widget.append_output = lambda msg, error=False: outputs.append(msg) if error else None

        # Executa sem conexão
        widget._on_execute_sql("SELECT 1")

        # Deve ter erro de conexão
        assert any("connection" in o.lower() or "no active" in o.lower() for o in outputs)

    def test_change_language_multiple_times(self, widget):
        """Deve funcionar mudar linguagem múltiplas vezes"""
        blocks = widget.editor.get_blocks()

        # Python -> SQL -> Python
        blocks[0].set_language("python")
        assert blocks[0].get_language() == "python"

        blocks[0].set_language("sql")
        assert blocks[0].get_language() == "sql"

        blocks[0].set_language("python")
        assert blocks[0].get_language() == "python"

    def test_blocks_persist_to_session(self, widget):
        """Blocos devem ser salvos na sessão"""
        # Cria blocos
        widget.editor.get_blocks()[0].set_language("sql")
        widget.editor.get_blocks()[0].set_code("SELECT 1")
        widget.editor.add_block(language="python", code="x = 1")

        # Sincroniza
        widget.sync_to_session()

        # Verifica
        assert len(widget.session.blocks) == 2
        assert widget.session.blocks[0]["language"] == "sql"
        assert widget.session.blocks[1]["language"] == "python"

    def test_blocks_restore_from_session(self, session, theme_manager, qtbot):
        """Blocos devem ser restaurados da sessão"""
        # Setup sessão com blocos
        session.blocks = [{"language": "sql", "code": "SELECT 1"}, {"language": "python", "code": "x = 1"}]

        # Cria widget
        widget = SessionWidget(session=session, theme_manager=theme_manager)
        qtbot.addWidget(widget)

        # Verifica blocos
        blocks = widget.editor.get_blocks()
        assert len(blocks) == 2
        assert blocks[0].get_language() == "sql"
        assert blocks[1].get_language() == "python"


class TestBlockEditorKeyboardShortcuts:
    """Testes de atalhos de teclado"""

    @pytest.fixture
    def theme_manager(self):
        return ThemeManager()

    @pytest.fixture
    def editor(self, theme_manager, qtbot):
        editor = BlockEditor(theme_manager=theme_manager)
        qtbot.addWidget(editor)
        return editor

    def test_f5_executes(self, editor, qtbot):
        """F5 deve executar apenas o bloco focado (nao todos)"""
        editor.get_blocks()[0].set_language("python")
        editor.get_blocks()[0].set_code("x = 1")

        # Focus the block
        editor._focused_block = editor.get_blocks()[0]

        python_received = []
        editor.execute_python.connect(lambda code: python_received.append(code))

        # Simula F5
        from PyQt6.QtGui import QKeyEvent

        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_F5, Qt.KeyboardModifier.NoModifier)
        editor.keyPressEvent(event)

        # F5 sem selecao executa apenas o bloco focado
        assert len(python_received) == 1
        assert python_received[0] == "x = 1"

    def test_f5_executes_only_focused_block(self, editor, qtbot):
        """F5 deve executar apenas o bloco focado, nao todos os blocos"""
        editor.get_blocks()[0].set_language("python")
        editor.get_blocks()[0].set_code("x = 1")
        editor.add_block(language="python", code="y = 2")

        # Focus on second block
        editor._focused_block = editor.get_blocks()[1]

        python_received = []
        editor.execute_python.connect(lambda code: python_received.append(code))

        queue_received = []
        editor.execute_queue.connect(lambda q: queue_received.extend(q))

        # Simula F5
        from PyQt6.QtGui import QKeyEvent

        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_F5, Qt.KeyboardModifier.NoModifier)
        editor.keyPressEvent(event)

        # Deve executar apenas o bloco focado (segundo), nao todos
        assert len(python_received) == 1
        assert python_received[0] == "y = 2"
        assert len(queue_received) == 0  # Nao deve emitir execute_queue

    def test_run_button_executes_only_that_block(self, editor, qtbot):
        """Botao de executar do bloco deve executar apenas aquele bloco"""
        editor.get_blocks()[0].set_language("python")
        editor.get_blocks()[0].set_code("x = 1")
        block2 = editor.add_block(language="python", code="y = 2")

        python_received = []
        editor.execute_python.connect(lambda code: python_received.append(code))

        queue_received = []
        editor.execute_queue.connect(lambda q: queue_received.extend(q))

        # Simula clique no botao de executar do bloco 2
        editor._on_block_execute_requested(block2)

        # Deve executar apenas o bloco 2
        assert len(python_received) == 1
        assert python_received[0] == "y = 2"
        assert len(queue_received) == 0  # Nao deve emitir execute_queue


class TestRealWorldScenarios:
    """Testes de cenários do mundo real"""

    @pytest.fixture
    def theme_manager(self):
        return ThemeManager()

    @pytest.fixture
    def session(self):
        return Session(session_id="test", title="Test")

    @pytest.fixture
    def widget(self, session, theme_manager, qtbot):
        widget = SessionWidget(session=session, theme_manager=theme_manager)
        qtbot.addWidget(widget)
        return widget

    def test_scenario_data_analysis_workflow(self, widget, qtbot):
        """Cenario: Fluxo de analise de dados

        1. Carrega dados via SQL
        2. Processa com Python
        3. Mais processamento Python
        """
        editor = widget.editor

        # Bloco 1: SQL para carregar dados
        blocks = editor.get_blocks()
        blocks[0].set_language("sql")
        blocks[0].set_code("SELECT * FROM clientes")

        # Bloco 2: Python para processar
        block2 = editor.add_block(language="python", code="df_filtered = df[df.ativo == 1]")

        # Bloco 3: Python para analise final
        block3 = editor.add_block(language="python", code="resultado = df_filtered.describe()")

        # Verifica estrutura
        all_blocks = editor.get_blocks()
        assert len(all_blocks) == 3
        assert all_blocks[0].get_language() == "sql"
        assert all_blocks[1].get_language() == "python"
        assert all_blocks[2].get_language() == "python"

        # Serializa e verifica
        data = editor.to_list()
        assert len(data) == 3

    def test_scenario_change_mind_about_language(self, widget, qtbot):
        """Cenário: Usuário muda de ideia sobre linguagem

        1. Começa escrevendo SQL (default)
        2. Percebe que é Python
        3. Muda para Python
        4. Executa
        """
        editor = widget.editor
        blocks = editor.get_blocks()

        # Usuário começa com SQL (padrão)
        assert blocks[0].get_language() == "sql"

        # Escreve código pensando que é SQL
        blocks[0].set_code('print("Hello")')

        # Percebe que é Python, muda
        blocks[0].set_language("python")

        # Verifica que linguagem mudou
        assert blocks[0].get_language() == "python"

        # Verifica que código ainda está lá
        assert blocks[0].get_code() == 'print("Hello")'

        # Simula execução - deve usar Python agora
        sql_executed = []
        python_executed = []
        editor.execute_sql.connect(lambda c, _bn, _cn, _dn, _sp: sql_executed.append(c))
        editor.execute_python.connect(lambda c: python_executed.append(c))

        editor._execute_block(blocks[0])

        # Deve ter executado como Python
        assert python_executed == ['print("Hello")']
        assert sql_executed == []

    def test_scenario_mixed_execution(self, widget, qtbot):
        """Cenario: Execucao mista de blocos

        Cria 4 blocos de linguagens diferentes e executa todos
        """
        editor = widget.editor

        # Setup
        editor.get_blocks()[0].set_language("python")
        editor.get_blocks()[0].set_code("a = 1")

        editor.add_block(language="sql", code="SELECT 1 as num")
        editor.add_block(language="python", code="b = 2")
        editor.add_block(language="sql", code="SELECT 3 as num")

        # Rastreador de fila
        queue_received = []
        editor.execute_queue.connect(lambda q: queue_received.extend(q))

        # Executa todos
        editor.execute_all_blocks()

        # Verifica ordem correta na fila (novo formato: language, code, block)
        assert len(queue_received) == 4
        assert queue_received[0][0] == "python"
        assert queue_received[0][1] == "a = 1"
        assert queue_received[1][0] == "sql"
        assert queue_received[1][1] == "SELECT 1 as num"
        assert queue_received[2][0] == "python"
        assert queue_received[2][1] == "b = 2"
        assert queue_received[3][0] == "sql"
        assert queue_received[3][1] == "SELECT 3 as num"

    def test_scenario_session_persistence(self, session, theme_manager, qtbot):
        """Cenário: Persistência de sessão

        1. Cria blocos
        2. Fecha sessão (salva)
        3. Reabre sessão
        4. Blocos devem estar lá
        """
        # Cria widget e blocos
        widget1 = SessionWidget(session=session, theme_manager=theme_manager)
        qtbot.addWidget(widget1)

        widget1.editor.get_blocks()[0].set_language("sql")
        widget1.editor.get_blocks()[0].set_code("SELECT * FROM products")
        widget1.editor.add_block(language="python", code="total = df.sum()")

        # Salva
        widget1.sync_to_session()

        # Serializa sessão (simula fechar)
        session_data = session.serialize()

        # Deserializa (simula reabrir)
        new_session = Session.deserialize(session_data)

        # Cria novo widget
        widget2 = SessionWidget(session=new_session, theme_manager=theme_manager)
        qtbot.addWidget(widget2)

        # Verifica
        blocks = widget2.editor.get_blocks()
        assert len(blocks) == 2
        assert blocks[0].get_language() == "sql"
        assert blocks[0].get_code() == "SELECT * FROM products"
        assert blocks[1].get_language() == "python"
        assert blocks[1].get_code() == "total = df.sum()"

    def test_session_serialization_preserves_databricks_database_context(self):
        session = Session(session_id="test-session", title="Test")
        session.database_context = "mag_bronze.esim"

        session_data = session.serialize()
        restored = Session.deserialize(session_data)

        assert restored.database_context == "mag_bronze.esim"


class TestEdgeCases:
    """Testes de casos extremos"""

    @pytest.fixture
    def theme_manager(self):
        return ThemeManager()

    @pytest.fixture
    def editor(self, theme_manager, qtbot):
        editor = BlockEditor(theme_manager=theme_manager)
        qtbot.addWidget(editor)
        return editor

    def test_empty_code_not_executed(self, editor, qtbot):
        """Código vazio não deve ser executado"""
        editor.get_blocks()[0].set_language("python")
        editor.get_blocks()[0].set_code("")

        executed = []
        editor.execute_python.connect(lambda c: executed.append(c))

        editor.execute_all_blocks()

        assert executed == []

    def test_whitespace_only_not_executed(self, editor, qtbot):
        """Código só com espaços não deve ser executado"""
        editor.get_blocks()[0].set_language("python")
        editor.get_blocks()[0].set_code("   \n\t\n   ")

        executed = []
        editor.execute_python.connect(lambda c: executed.append(c))

        editor.execute_all_blocks()

        assert executed == []

    def test_many_blocks(self, editor):
        """Deve suportar muitos blocos"""
        for i in range(20):
            editor.add_block(language="python", code=f"x{i} = {i}")

        assert editor.get_block_count() == 21  # 1 inicial + 20 adicionados

    def test_rapid_language_changes(self, editor):
        """Deve suportar mudancas rapidas de linguagem"""
        block = editor.get_blocks()[0]

        for _ in range(10):
            block.set_language("python")
            block.set_language("sql")

        # Ultima deve ser sql
        assert block.get_language() == "sql"

    def test_special_characters_in_code(self, editor, qtbot):
        """Deve suportar caracteres especiais"""
        code = "print('áéíóú ñ 日本語 emoji: 🎉')"
        editor.get_blocks()[0].set_language("python")
        editor.get_blocks()[0].set_code(code)

        executed = []
        editor.execute_python.connect(lambda c: executed.append(c))

        editor._execute_block(editor.get_blocks()[0])

        assert executed == [code]

    def test_multiline_code(self, editor, qtbot):
        """Deve suportar código multilinha"""
        code = """def hello():
    print("Hello")
    return 42

result = hello()"""

        editor.get_blocks()[0].set_language("python")
        editor.get_blocks()[0].set_code(code)

        executed = []
        editor.execute_python.connect(lambda c: executed.append(c))

        editor._execute_block(editor.get_blocks()[0])

        assert executed == [code]


class TestFileDragAndDrop:
    """Testes para arrastar e soltar arquivos CSV, JSON e XLSX"""

    @pytest.fixture
    def theme_manager(self):
        return ThemeManager()

    @pytest.fixture
    def editor(self, theme_manager, qtbot):
        editor = BlockEditor(theme_manager=theme_manager)
        qtbot.addWidget(editor)
        return editor

    def test_generate_import_code_csv(self, editor):
        """Deve gerar codigo de importacao para CSV"""
        code = editor._generate_import_code("/path/to/data.csv")
        assert code is not None
        assert "import pandas" not in code
        assert "pd.read_csv('/path/to/data.csv')" in code
        assert "df = " in code

    def test_generate_import_code_json(self, editor):
        """Deve gerar codigo de importacao para JSON"""
        code = editor._generate_import_code("/path/to/data.json")
        assert code is not None
        assert "import pandas" not in code
        assert "pd.read_json('/path/to/data.json')" in code
        assert "df = " in code


class TestBlockMaximize:
    """Testes da funcionalidade de maximizar bloco"""

    @pytest.fixture
    def theme_manager(self):
        return ThemeManager()

    @pytest.fixture
    def editor(self, theme_manager, qtbot):
        editor = BlockEditor(theme_manager=theme_manager)
        qtbot.addWidget(editor)
        return editor

    def test_maximize_hides_other_blocks(self, editor):
        """Maximizar um bloco deve esconder todos os outros"""
        block1 = editor._blocks[0]
        block2 = editor.add_block(code="SELECT 2")
        block3 = editor.add_block(code="SELECT 3")

        editor._toggle_maximize_block(block2)

        assert not block2.isHidden()
        assert block1.isHidden()
        assert block3.isHidden()
        assert editor.add_button_container.isHidden()

    def test_maximize_sets_block_state(self, editor):
        """Maximizar deve marcar o bloco como maximizado"""
        block = editor._blocks[0]
        editor.add_block()

        editor._toggle_maximize_block(block)

        assert block.is_maximized
        assert editor._maximized_block == block

    def test_restore_shows_all_blocks(self, editor):
        """Restaurar deve mostrar todos os blocos novamente"""
        block1 = editor._blocks[0]
        block2 = editor.add_block(code="SELECT 2")

        editor._toggle_maximize_block(block1)
        editor._toggle_maximize_block(block1)  # Toggle again to restore

        assert not block1.isHidden()
        assert not block2.isHidden()
        assert not editor.add_button_container.isHidden()
        assert not block1.is_maximized
        assert editor._maximized_block is None

    def test_maximize_different_block_switches(self, editor):
        """Maximizar outro bloco deve trocar o bloco maximizado"""
        block1 = editor._blocks[0]
        block2 = editor.add_block(code="SELECT 2")
        block3 = editor.add_block(code="SELECT 3")

        editor._toggle_maximize_block(block1)
        assert block1.is_maximized

        editor._toggle_maximize_block(block2)
        assert block2.is_maximized
        assert not block1.is_maximized
        assert block1.isHidden()
        assert not block2.isHidden()
        assert block3.isHidden()

    def test_remove_maximized_block_restores(self, editor):
        """Remover bloco maximizado deve restaurar os outros"""
        block1 = editor._blocks[0]
        block2 = editor.add_block(code="SELECT 2")
        block3 = editor.add_block(code="SELECT 3")

        editor._toggle_maximize_block(block2)
        editor.remove_block(block2)

        assert not block1.isHidden()
        assert not block3.isHidden()
        assert not editor.add_button_container.isHidden()
        assert editor._maximized_block is None

    def test_escape_key_restores_maximize(self, editor, qtbot):
        """Pressionar Escape deve sair do modo maximizado"""
        from PyQt6.QtTest import QTest

        block1 = editor._blocks[0]
        block2 = editor.add_block(code="SELECT 2")

        editor._toggle_maximize_block(block1)
        assert editor._maximized_block is not None

        QTest.keyClick(editor, Qt.Key.Key_Escape)

        assert editor._maximized_block is None
        assert not block1.isHidden()
        assert not block2.isHidden()

    def test_is_maximized_property(self, editor):
        """Propriedade is_maximized do editor deve refletir o estado"""
        assert not editor.is_maximized

        block = editor._blocks[0]
        editor.add_block()
        editor._toggle_maximize_block(block)
        assert editor.is_maximized

        editor._restore_all_blocks()
        assert not editor.is_maximized

    def test_generate_import_code_xlsx(self, editor):
        """Deve gerar codigo de importacao para XLSX"""
        code = editor._generate_import_code("/path/to/data.xlsx")
        assert code is not None
        assert "import pandas" not in code
        assert "pd.read_excel('/path/to/data.xlsx')" in code
        assert "df = " in code

    def test_generate_import_code_xls(self, editor):
        """Deve gerar codigo de importacao para XLS"""
        code = editor._generate_import_code("/path/to/data.xls")
        assert code is not None
        assert "import pandas" not in code
        assert "pd.read_excel('/path/to/data.xls')" in code
        assert "df = " in code

    def test_generate_import_code_case_insensitive(self, editor):
        """Deve reconhecer extensões em maiúsculas"""
        code_csv = editor._generate_import_code("/path/to/DATA.CSV")
        code_json = editor._generate_import_code("/path/to/DATA.JSON")
        code_xlsx = editor._generate_import_code("/path/to/DATA.XLSX")

        assert code_csv is not None
        assert "pd.read_csv" in code_csv
        assert code_json is not None
        assert "pd.read_json" in code_json
        assert code_xlsx is not None
        assert "pd.read_excel" in code_xlsx

    def test_generate_import_code_unsupported_extension(self, editor):
        """Deve retornar None para extensões não suportadas"""
        code = editor._generate_import_code("/path/to/file.txt")
        assert code is None

        code = editor._generate_import_code("/path/to/file.pdf")
        assert code is None

    def test_generate_import_code_windows_path(self, editor):
        """Deve normalizar caminhos do Windows"""
        code = editor._generate_import_code(r"C:\Users\test\data.csv")
        assert code is not None
        assert "C:/Users/test/data.csv" in code

    def test_generate_import_code_special_characters_in_path(self, editor):
        """Deve lidar com caracteres especiais no caminho"""
        code = editor._generate_import_code("/path/to/dados especiais.csv")
        assert code is not None
        assert "dados especiais.csv" in code

    def test_drag_enter_accepts_csv_file(self, editor, qtbot):
        """Deve aceitar arrasto de arquivo CSV"""
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QDragEnterEvent

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/path/to/data.csv")])

        event = QDragEnterEvent(
            editor.rect().center(),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        editor.dragEnterEvent(event)
        assert event.isAccepted()

    def test_drag_enter_accepts_json_file(self, editor, qtbot):
        """Deve aceitar arrasto de arquivo JSON"""
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QDragEnterEvent

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/path/to/data.json")])

        event = QDragEnterEvent(
            editor.rect().center(),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        editor.dragEnterEvent(event)
        assert event.isAccepted()

    def test_drag_enter_accepts_xlsx_file(self, editor, qtbot):
        """Deve aceitar arrasto de arquivo XLSX"""
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QDragEnterEvent

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/path/to/data.xlsx")])

        event = QDragEnterEvent(
            editor.rect().center(),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        editor.dragEnterEvent(event)
        assert event.isAccepted()

    def test_drag_enter_rejects_unsupported_file(self, editor, qtbot):
        """Deve rejeitar arrasto de arquivo não suportado"""
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QDragEnterEvent

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/path/to/file.txt")])

        event = QDragEnterEvent(
            editor.rect().center(),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        editor.dragEnterEvent(event)
        assert not event.isAccepted()

    def test_drop_csv_emits_file_dropped(self, editor, qtbot):
        """Deve emitir file_dropped ao soltar arquivo CSV"""
        from PyQt6.QtCore import QMimeData, QUrl, QPointF
        from PyQt6.QtGui import QDropEvent

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/path/to/data.csv")])

        event = QDropEvent(
            QPointF(editor.rect().center()),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        with qtbot.waitSignal(editor.file_dropped, timeout=1000) as blocker:
            editor.dropEvent(event)

        # Deve emitir o sinal com o path do arquivo
        assert "data.csv" in blocker.args[0]

    def test_drop_json_emits_file_dropped(self, editor, qtbot):
        """Deve emitir file_dropped ao soltar arquivo JSON"""
        from PyQt6.QtCore import QMimeData, QUrl, QPointF
        from PyQt6.QtGui import QDropEvent

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/path/to/data.json")])

        event = QDropEvent(
            QPointF(editor.rect().center()),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        with qtbot.waitSignal(editor.file_dropped, timeout=1000) as blocker:
            editor.dropEvent(event)

        # Deve emitir o sinal com o path do arquivo
        assert "data.json" in blocker.args[0]

    def test_drop_xlsx_emits_file_dropped(self, editor, qtbot):
        """Deve emitir file_dropped ao soltar arquivo XLSX"""
        from PyQt6.QtCore import QMimeData, QUrl, QPointF
        from PyQt6.QtGui import QDropEvent

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/path/to/data.xlsx")])

        event = QDropEvent(
            QPointF(editor.rect().center()),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        with qtbot.waitSignal(editor.file_dropped, timeout=1000) as blocker:
            editor.dropEvent(event)

        # Deve emitir o sinal com o path do arquivo
        assert "data.xlsx" in blocker.args[0]

    def test_drop_multiple_files_emits_for_first(self, editor, qtbot):
        """Deve emitir file_dropped para o primeiro arquivo de dados"""
        from PyQt6.QtCore import QMimeData, QUrl, QPointF
        from PyQt6.QtGui import QDropEvent

        mime_data = QMimeData()
        mime_data.setUrls(
            [
                QUrl.fromLocalFile("/path/to/data1.csv"),
                QUrl.fromLocalFile("/path/to/data2.json"),
                QUrl.fromLocalFile("/path/to/data3.xlsx"),
            ]
        )

        event = QDropEvent(
            QPointF(editor.rect().center()),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        # file_dropped emitido pelo menos para o primeiro data file
        with qtbot.waitSignal(editor.file_dropped, timeout=1000) as blocker:
            editor.dropEvent(event)

        assert "data1.csv" in blocker.args[0] or "data2.json" in blocker.args[0] or "data3.xlsx" in blocker.args[0]

    def test_drop_preserves_existing_blocks(self, editor, qtbot):
        """Soltar arquivo não deve afetar blocos existentes"""
        from PyQt6.QtCore import QMimeData, QUrl, QPointF
        from PyQt6.QtGui import QDropEvent

        # Adicionar alguns blocos
        editor.get_blocks()[0].set_language("sql")
        editor.get_blocks()[0].set_code("SELECT 1")
        editor.add_block(language="python", code='print("test")')

        initial_blocks = [b.get_code() for b in editor.get_blocks()]
        initial_count = editor.get_block_count()

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/path/to/data.csv")])

        event = QDropEvent(
            QPointF(editor.rect().center()),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        with qtbot.waitSignal(editor.content_changed, timeout=1000):
            editor.dropEvent(event)

        # Blocos originais devem permanecer intactos
        blocks = editor.get_blocks()
        for i, original_code in enumerate(initial_blocks):
            assert blocks[i].get_code() == original_code


class TestBlockActiveToggle:
    """Testes do toggle ativo/inativo nos blocos"""

    @pytest.fixture
    def theme_manager(self):
        return ThemeManager()

    @pytest.fixture
    def block(self, theme_manager, qtbot):
        block = CodeBlock(theme_manager=theme_manager)
        qtbot.addWidget(block)
        return block

    def test_block_active_by_default(self, block):
        """Bloco deve ser ativo por padrao"""
        assert block.is_active() is True
        assert block.active_toggle.isChecked() is True

    def test_set_active_false(self, block):
        """Deve desativar o bloco"""
        block.set_active(False)
        assert block.is_active() is False
        assert block.active_toggle.isChecked() is False

    def test_set_active_true(self, block):
        """Deve reativar o bloco"""
        block.set_active(False)
        block.set_active(True)
        assert block.is_active() is True
        assert block.active_toggle.isChecked() is True

    def test_toggle_click_changes_state(self, block):
        """Clicar no toggle deve mudar o estado"""
        block.active_toggle.setChecked(False)
        assert block.is_active() is False
        block.active_toggle.setChecked(True)
        assert block.is_active() is True

    def test_inactive_block_editor_disabled(self, block):
        """Editor deve ficar desabilitado quando bloco inativo"""
        block.set_active(False)
        assert block.editor_container.isEnabled() is False
        block.set_active(True)
        assert block.editor_container.isEnabled() is True

    def test_to_dict_saves_active_state(self, block):
        """to_dict deve salvar estado ativo"""
        block.set_active(False)
        data = block.to_dict()
        assert data["is_active"] is False

        block.set_active(True)
        data = block.to_dict()
        assert data["is_active"] is True

    def test_from_dict_restores_active_state(self, theme_manager, qtbot):
        """from_dict deve restaurar estado inativo"""
        data = {"language": "sql", "code": "SELECT 1", "is_active": False}
        block = CodeBlock.from_dict(data, theme_manager)
        qtbot.addWidget(block)
        assert block.is_active() is False

    def test_from_dict_defaults_active_true(self, theme_manager, qtbot):
        """from_dict sem is_active deve manter bloco ativo (compatibilidade)"""
        data = {"language": "sql", "code": "SELECT 1"}
        block = CodeBlock.from_dict(data, theme_manager)
        qtbot.addWidget(block)
        assert block.is_active() is True

    @pytest.fixture
    def _no_focus_editor(self, monkeypatch):
        """Prevent QScintilla from grabbing focus (avoids test hang)"""
        monkeypatch.setattr(CodeBlock, "focus_editor", lambda self: None)

    @pytest.fixture
    def editor(self, qtbot, _no_focus_editor):
        theme = ThemeManager()
        editor = BlockEditor(theme_manager=theme)
        qtbot.addWidget(editor)
        return editor

    def test_execute_all_skips_inactive(self, editor, qtbot):
        """Execute all deve pular blocos inativos"""
        editor.add_block("sql")
        editor.add_block("sql")
        editor.add_block("sql")

        blocks = editor.get_blocks()
        blocks[0].set_code("SELECT 1")
        blocks[1].set_code("SELECT 2")
        blocks[2].set_code("SELECT 3")

        # Desativar o bloco do meio
        blocks[1].set_active(False)

        # Capturar a queue emitida
        emitted_queue = []
        editor.execute_queue.connect(lambda q: emitted_queue.extend(q))
        editor.execute_all_blocks()

        # Deve ter apenas 2 blocos na queue (0 e 2)
        assert len(emitted_queue) == 2
        assert emitted_queue[0][1] == "SELECT 1"  # code of first block
        assert emitted_queue[1][1] == "SELECT 3"  # code of third block

    def test_execute_all_skips_all_inactive(self, editor, qtbot):
        """Se todos os blocos estao inativos, nada deve ser executado"""
        editor.add_block("sql")
        editor.add_block("sql")

        blocks = editor.get_blocks()
        blocks[0].set_code("SELECT 1")
        blocks[1].set_code("SELECT 2")
        blocks[0].set_active(False)
        blocks[1].set_active(False)

        emitted_queue = []
        editor.execute_queue.connect(lambda q: emitted_queue.extend(q))
        editor.execute_all_blocks()

        assert len(emitted_queue) == 0
