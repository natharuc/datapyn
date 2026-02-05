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
        assert block.get_language() == 'sql'  # Padrão agora é SQL
        assert block.get_code() == ''
        assert not block.is_focused()
    
    def test_set_language_python(self, block):
        """Deve permitir mudar para Python"""
        block.set_language('python')
        assert block.get_language() == 'python'
    
    def test_set_language_sql(self, block):
        """Deve permitir mudar para SQL"""
        block.set_language('sql')
        assert block.get_language() == 'sql'
    
    def test_set_language_cross(self, block):
        """Deve permitir mudar para Cross-Syntax"""
        block.set_language('cross')
        assert block.get_language() == 'cross'
    
    def test_set_code(self, block):
        """Deve permitir definir código"""
        block.set_code("print('hello')")
        assert block.get_code() == "print('hello')"
    
    def test_language_change_updates_lexer(self, block):
        """Mudar linguagem deve atualizar o lexer"""
        # Começar com Python (diferente do padrão SQL)
        block.set_language('python')
        assert block.editor.get_language() == 'python'
        
        # Mudar para SQL
        block.set_language('sql')
        assert block.editor.get_language() == 'sql'
    
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
        # Bloco começa em SQL (index 1), mudar para Python (index 0) para garantir mudança
        with qtbot.waitSignal(block.language_changed, timeout=1000):
            block.lang_combo.setCurrentIndex(0)  # Python
    
    def test_to_dict_serialization(self, block):
        """Deve serializar corretamente"""
        block.set_language('sql')
        block.set_code('SELECT 1')
        
        data = block.to_dict()
        assert data['language'] == 'sql'
        assert data['code'] == 'SELECT 1'
    
    def test_from_dict_deserialization(self, theme_manager, qtbot):
        """Deve deserializar corretamente"""
        data = {'language': 'python', 'code': 'x = 1'}
        block = CodeBlock.from_dict(data, theme_manager)
        qtbot.addWidget(block)
        
        assert block.get_language() == 'python'
        assert block.get_code() == 'x = 1'
    
    def test_running_state(self, block):
        """Deve mudar estado de execução e mostrar tempo"""
        assert block.run_btn.text() == "▶"
        
        block.set_running(True)
        assert block.run_btn.text() == "◼"
        assert "Executando" in block.status_label.text()
        
        block.set_running(False)
        assert block.run_btn.text() == "▶"
        # Após execução, mostra tempo de execução (µs, ms ou s)
        assert any(unit in block.status_label.text() for unit in ["µs", "ms", "s"]) or block.status_label.text() == ""


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
        block = editor.add_block(language='python')
        assert block.get_language() == 'python'
    
    def test_add_block_with_code(self, editor):
        """Deve adicionar bloco com código"""
        block = editor.add_block(code='SELECT 1')
        assert block.get_code() == 'SELECT 1'
    
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
        blocks[0].set_language('sql')
        blocks[0].set_code('SELECT 1')
        
        with qtbot.waitSignal(editor.execute_sql, timeout=1000) as blocker:
            editor._execute_block(blocks[0])
        
        assert blocker.args[0] == 'SELECT 1'
    
    def test_execute_python_signal(self, editor, qtbot):
        """Deve emitir sinal Python quando bloco é Python"""
        blocks = editor.get_blocks()
        blocks[0].set_language('python')
        blocks[0].set_code('print(1)')
        
        with qtbot.waitSignal(editor.execute_python, timeout=1000) as blocker:
            editor._execute_block(blocks[0])
        
        assert blocker.args[0] == 'print(1)'
    
    def test_execute_cross_signal(self, editor, qtbot):
        """Deve emitir sinal Cross quando bloco é Cross"""
        blocks = editor.get_blocks()
        blocks[0].set_language('cross')
        blocks[0].set_code('df = {{SELECT 1}}')
        
        with qtbot.waitSignal(editor.execute_cross_syntax, timeout=1000) as blocker:
            editor._execute_block(blocks[0])
        
        assert blocker.args[0] == 'df = {{SELECT 1}}'
    
    def test_change_language_then_execute(self, editor, qtbot):
        """Mudar linguagem e executar deve usar a nova linguagem"""
        blocks = editor.get_blocks()
        
        # Começa como Python
        blocks[0].set_language('python')
        blocks[0].set_code('x = 1')
        
        # Muda para SQL
        blocks[0].set_language('sql')
        blocks[0].set_code('SELECT 1')
        
        # Deve emitir SQL, não Python
        with qtbot.waitSignal(editor.execute_sql, timeout=1000) as blocker:
            editor._execute_block(blocks[0])
        
        assert blocker.args[0] == 'SELECT 1'
    
    def test_multiple_blocks_different_languages(self, editor, qtbot):
        """Múltiplos blocos com linguagens diferentes"""
        # Bloco 1: SQL
        blocks = editor.get_blocks()
        blocks[0].set_language('sql')
        blocks[0].set_code('SELECT 1')
        
        # Bloco 2: Python
        block2 = editor.add_block(language='python', code='print(1)')
        
        # Bloco 3: Cross
        block3 = editor.add_block(language='cross', code='df = {{SELECT 2}}')
        
        # Executar bloco SQL
        with qtbot.waitSignal(editor.execute_sql, timeout=1000):
            editor._execute_block(blocks[0])
        
        # Executar bloco Python
        with qtbot.waitSignal(editor.execute_python, timeout=1000):
            editor._execute_block(block2)
        
        # Executar bloco Cross
        with qtbot.waitSignal(editor.execute_cross_syntax, timeout=1000):
            editor._execute_block(block3)
    
    def test_serialization_multiple_blocks(self, editor):
        """Deve serializar múltiplos blocos"""
        editor.get_blocks()[0].set_language('sql')
        editor.get_blocks()[0].set_code('SELECT 1')
        editor.add_block(language='python', code='x = 1')
        editor.add_block(language='cross', code='y = {{SELECT 2}}')
        
        data = editor.to_list()
        
        assert len(data) == 3
        # Verificar campos principais (height pode variar)
        assert data[0]['language'] == 'sql'
        assert data[0]['code'] == 'SELECT 1'
        assert data[1]['language'] == 'python'
        assert data[1]['code'] == 'x = 1'
        assert data[2]['language'] == 'cross'
        assert data[2]['code'] == 'y = {{SELECT 2}}'
    
    def test_deserialization_multiple_blocks(self, editor):
        """Deve deserializar múltiplos blocos"""
        data = [
            {'language': 'sql', 'code': 'SELECT 1'},
            {'language': 'python', 'code': 'x = 1'},
            {'language': 'cross', 'code': 'y = {{SELECT 2}}'}
        ]
        
        editor.from_list(data)
        
        blocks = editor.get_blocks()
        assert len(blocks) == 3
        assert blocks[0].get_language() == 'sql'
        assert blocks[0].get_code() == 'SELECT 1'
        assert blocks[1].get_language() == 'python'
        assert blocks[1].get_code() == 'x = 1'
        assert blocks[2].get_language() == 'cross'
        assert blocks[2].get_code() == 'y = {{SELECT 2}}'


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
        editor.get_blocks()[0].set_language('sql')
        editor.get_blocks()[0].set_code('SELECT 1')
        editor.add_block(language='python', code='x = 1')
        
        # Captura sinal de fila
        queue_received = []
        editor.execute_queue.connect(lambda q: queue_received.extend(q))
        
        # Executa todos
        editor.execute_all_blocks()
        
        # Verifica que a fila contém os blocos na ordem
        # Formato novo: (language, code, block)
        assert len(queue_received) == 2
        assert queue_received[0][0] == 'sql'
        assert queue_received[0][1] == 'SELECT 1'
        assert queue_received[1][0] == 'python'
        assert queue_received[1][1] == 'x = 1'
    
    def test_empty_blocks_not_executed(self, editor, qtbot):
        """Blocos vazios não devem ser executados"""
        editor.get_blocks()[0].set_code('')  # Vazio
        editor.add_block(language='python', code='x = 1')
        
        queue_received = []
        editor.execute_queue.connect(lambda q: queue_received.extend(q))
        
        editor.execute_all_blocks()
        
        # Apenas o segundo bloco (não vazio)
        assert len(queue_received) == 1
        assert queue_received[0][0] == 'python'
        assert queue_received[0][1] == 'x = 1'
    
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
        return Session(session_id='test-session', title='Test')
    
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
        blocks[0].set_language('python')
        blocks[0].set_code('x = 1 + 1')
        
        # Não deve exigir conexão para Python
        # O sinal deve ser emitido
        with qtbot.waitSignal(widget.editor.execute_python, timeout=1000):
            widget.editor._execute_block(blocks[0])
    
    def test_sql_requires_connection(self, widget, qtbot):
        """SQL deve mostrar erro se sem conexão"""
        blocks = widget.editor.get_blocks()
        blocks[0].set_language('sql')
        blocks[0].set_code('SELECT 1')
        
        # Mock para capturar output
        outputs = []
        
        # Mock dos métodos de log diretamente no widget
        widget._log_error = lambda msg: outputs.append(msg)
        widget.append_output = lambda msg, error=False: outputs.append(msg) if error else None
        
        # Executa sem conexão
        widget._on_execute_sql('SELECT 1')
        
        # Deve ter erro de conexão
        assert any('conexão' in o.lower() for o in outputs)
    
    def test_change_language_multiple_times(self, widget):
        """Deve funcionar mudar linguagem múltiplas vezes"""
        blocks = widget.editor.get_blocks()
        
        # Python -> SQL -> Cross -> Python
        blocks[0].set_language('python')
        assert blocks[0].get_language() == 'python'
        
        blocks[0].set_language('sql')
        assert blocks[0].get_language() == 'sql'
        
        blocks[0].set_language('cross')
        assert blocks[0].get_language() == 'cross'
        
        blocks[0].set_language('python')
        assert blocks[0].get_language() == 'python'
    
    def test_blocks_persist_to_session(self, widget):
        """Blocos devem ser salvos na sessão"""
        # Cria blocos
        widget.editor.get_blocks()[0].set_language('sql')
        widget.editor.get_blocks()[0].set_code('SELECT 1')
        widget.editor.add_block(language='python', code='x = 1')
        
        # Sincroniza
        widget.sync_to_session()
        
        # Verifica
        assert len(widget.session.blocks) == 2
        assert widget.session.blocks[0]['language'] == 'sql'
        assert widget.session.blocks[1]['language'] == 'python'
    
    def test_blocks_restore_from_session(self, session, theme_manager, qtbot):
        """Blocos devem ser restaurados da sessão"""
        # Setup sessão com blocos
        session.blocks = [
            {'language': 'sql', 'code': 'SELECT 1'},
            {'language': 'python', 'code': 'x = 1'}
        ]
        
        # Cria widget
        widget = SessionWidget(session=session, theme_manager=theme_manager)
        qtbot.addWidget(widget)
        
        # Verifica blocos
        blocks = widget.editor.get_blocks()
        assert len(blocks) == 2
        assert blocks[0].get_language() == 'sql'
        assert blocks[1].get_language() == 'python'


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
        """F5 deve executar (emite fila quando não há seleção)"""
        editor.get_blocks()[0].set_language('python')
        editor.get_blocks()[0].set_code('x = 1')
        
        queue_received = []
        editor.execute_queue.connect(lambda q: queue_received.extend(q))
        
        # Simula F5
        from PyQt6.QtGui import QKeyEvent
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_F5,
            Qt.KeyboardModifier.NoModifier
        )
        editor.keyPressEvent(event)
        
        # F5 sem seleção executa todos os blocos via fila
        assert len(queue_received) == 1
        assert queue_received[0][0] == 'python'
        assert queue_received[0][1] == 'x = 1'


class TestRealWorldScenarios:
    """Testes de cenários do mundo real"""
    
    @pytest.fixture
    def theme_manager(self):
        return ThemeManager()
    
    @pytest.fixture
    def session(self):
        return Session(session_id='test', title='Test')
    
    @pytest.fixture
    def widget(self, session, theme_manager, qtbot):
        widget = SessionWidget(session=session, theme_manager=theme_manager)
        qtbot.addWidget(widget)
        return widget
    
    def test_scenario_data_analysis_workflow(self, widget, qtbot):
        """Cenário: Fluxo de análise de dados
        
        1. Carrega dados via SQL
        2. Processa com Python
        3. Usa Cross-Syntax para mais dados
        """
        editor = widget.editor
        
        # Bloco 1: SQL para carregar dados
        blocks = editor.get_blocks()
        blocks[0].set_language('sql')
        blocks[0].set_code('SELECT * FROM clientes')
        
        # Bloco 2: Python para processar
        block2 = editor.add_block(language='python', code='df_filtered = df[df.ativo == 1]')
        
        # Bloco 3: Cross-syntax para mais dados
        block3 = editor.add_block(language='cross', code='vendas = {{SELECT * FROM vendas}}')
        
        # Bloco 4: Python para análise final
        block4 = editor.add_block(language='python', code='resultado = df_filtered.merge(vendas)')
        
        # Verifica estrutura
        all_blocks = editor.get_blocks()
        assert len(all_blocks) == 4
        assert all_blocks[0].get_language() == 'sql'
        assert all_blocks[1].get_language() == 'python'
        assert all_blocks[2].get_language() == 'cross'
        assert all_blocks[3].get_language() == 'python'
        
        # Serializa e verifica
        data = editor.to_list()
        assert len(data) == 4
    
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
        assert blocks[0].get_language() == 'sql'
        
        # Escreve código pensando que é SQL
        blocks[0].set_code('print("Hello")')
        
        # Percebe que é Python, muda
        blocks[0].set_language('python')
        
        # Verifica que linguagem mudou
        assert blocks[0].get_language() == 'python'
        
        # Verifica que código ainda está lá
        assert blocks[0].get_code() == 'print("Hello")'
        
        # Simula execução - deve usar Python agora
        sql_executed = []
        python_executed = []
        editor.execute_sql.connect(lambda c: sql_executed.append(c))
        editor.execute_python.connect(lambda c: python_executed.append(c))
        
        editor._execute_block(blocks[0])
        
        # Deve ter executado como Python
        assert python_executed == ['print("Hello")']
        assert sql_executed == []
    
    def test_scenario_mixed_execution(self, widget, qtbot):
        """Cenário: Execução mista de blocos
        
        Cria 4 blocos de linguagens diferentes e executa todos
        """
        editor = widget.editor
        
        # Setup
        editor.get_blocks()[0].set_language('python')
        editor.get_blocks()[0].set_code('a = 1')
        
        editor.add_block(language='sql', code='SELECT 1 as num')
        editor.add_block(language='python', code='b = 2')
        editor.add_block(language='cross', code='c = {{SELECT 3}}')
        
        # Rastreador de fila
        queue_received = []
        editor.execute_queue.connect(lambda q: queue_received.extend(q))
        
        # Executa todos
        editor.execute_all_blocks()
        
        # Verifica ordem correta na fila (novo formato: language, code, block)
        assert len(queue_received) == 4
        assert queue_received[0][0] == 'python'
        assert queue_received[0][1] == 'a = 1'
        assert queue_received[1][0] == 'sql'
        assert queue_received[1][1] == 'SELECT 1 as num'
        assert queue_received[2][0] == 'python'
        assert queue_received[2][1] == 'b = 2'
        assert queue_received[3][0] == 'cross'
        assert queue_received[3][1] == 'c = {{SELECT 3}}'
    
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
        
        widget1.editor.get_blocks()[0].set_language('sql')
        widget1.editor.get_blocks()[0].set_code('SELECT * FROM products')
        widget1.editor.add_block(language='python', code='total = df.sum()')
        
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
        assert blocks[0].get_language() == 'sql'
        assert blocks[0].get_code() == 'SELECT * FROM products'
        assert blocks[1].get_language() == 'python'
        assert blocks[1].get_code() == 'total = df.sum()'


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
        editor.get_blocks()[0].set_language('python')
        editor.get_blocks()[0].set_code('')
        
        executed = []
        editor.execute_python.connect(lambda c: executed.append(c))
        
        editor.execute_all_blocks()
        
        assert executed == []
    
    def test_whitespace_only_not_executed(self, editor, qtbot):
        """Código só com espaços não deve ser executado"""
        editor.get_blocks()[0].set_language('python')
        editor.get_blocks()[0].set_code('   \n\t\n   ')
        
        executed = []
        editor.execute_python.connect(lambda c: executed.append(c))
        
        editor.execute_all_blocks()
        
        assert executed == []
    
    def test_many_blocks(self, editor):
        """Deve suportar muitos blocos"""
        for i in range(20):
            editor.add_block(language='python', code=f'x{i} = {i}')
        
        assert editor.get_block_count() == 21  # 1 inicial + 20 adicionados
    
    def test_rapid_language_changes(self, editor):
        """Deve suportar mudanças rápidas de linguagem"""
        block = editor.get_blocks()[0]
        
        for _ in range(10):
            block.set_language('python')
            block.set_language('sql')
            block.set_language('cross')
        
        # Última deve ser cross
        assert block.get_language() == 'cross'
    
    def test_special_characters_in_code(self, editor, qtbot):
        """Deve suportar caracteres especiais"""
        code = "print('áéíóú ñ 日本語 emoji: 🎉')"
        editor.get_blocks()[0].set_language('python')
        editor.get_blocks()[0].set_code(code)
        
        executed = []
        editor.execute_python.connect(lambda c: executed.append(c))
        
        editor._execute_block(editor.get_blocks()[0])
        
        assert executed == [code]
    
    def test_multiline_code(self, editor, qtbot):
        """Deve suportar código multilinha"""
        code = '''def hello():
    print("Hello")
    return 42

result = hello()'''
        
        editor.get_blocks()[0].set_language('python')
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
        """Deve gerar código de importação para CSV"""
        code = editor._generate_import_code('/path/to/data.csv')
        assert code is not None
        assert 'import pandas as pd' in code
        assert "pd.read_csv('/path/to/data.csv')" in code
        assert 'df = ' in code
    
    def test_generate_import_code_json(self, editor):
        """Deve gerar código de importação para JSON"""
        code = editor._generate_import_code('/path/to/data.json')
        assert code is not None
        assert 'import pandas as pd' in code
        assert "pd.read_json('/path/to/data.json')" in code
        assert 'df = ' in code
    
    def test_generate_import_code_xlsx(self, editor):
        """Deve gerar código de importação para XLSX"""
        code = editor._generate_import_code('/path/to/data.xlsx')
        assert code is not None
        assert 'import pandas as pd' in code
        assert "pd.read_excel('/path/to/data.xlsx')" in code
        assert 'df = ' in code
    
    def test_generate_import_code_xls(self, editor):
        """Deve gerar código de importação para XLS"""
        code = editor._generate_import_code('/path/to/data.xls')
        assert code is not None
        assert 'import pandas as pd' in code
        assert "pd.read_excel('/path/to/data.xls')" in code
        assert 'df = ' in code
    
    def test_generate_import_code_case_insensitive(self, editor):
        """Deve reconhecer extensões em maiúsculas"""
        code_csv = editor._generate_import_code('/path/to/DATA.CSV')
        code_json = editor._generate_import_code('/path/to/DATA.JSON')
        code_xlsx = editor._generate_import_code('/path/to/DATA.XLSX')
        
        assert code_csv is not None
        assert 'pd.read_csv' in code_csv
        assert code_json is not None
        assert 'pd.read_json' in code_json
        assert code_xlsx is not None
        assert 'pd.read_excel' in code_xlsx
    
    def test_generate_import_code_unsupported_extension(self, editor):
        """Deve retornar None para extensões não suportadas"""
        code = editor._generate_import_code('/path/to/file.txt')
        assert code is None
        
        code = editor._generate_import_code('/path/to/file.pdf')
        assert code is None
    
    def test_generate_import_code_windows_path(self, editor):
        """Deve normalizar caminhos do Windows"""
        code = editor._generate_import_code(r'C:\Users\test\data.csv')
        assert code is not None
        assert 'C:/Users/test/data.csv' in code
    
    def test_generate_import_code_special_characters_in_path(self, editor):
        """Deve lidar com caracteres especiais no caminho"""
        code = editor._generate_import_code('/path/to/dados especiais.csv')
        assert code is not None
        assert 'dados especiais.csv' in code
    
    def test_drag_enter_accepts_csv_file(self, editor, qtbot):
        """Deve aceitar arrasto de arquivo CSV"""
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QDragEnterEvent
        
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile('/path/to/data.csv')])
        
        event = QDragEnterEvent(
            editor.rect().center(),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        
        editor.dragEnterEvent(event)
        assert event.isAccepted()
    
    def test_drag_enter_accepts_json_file(self, editor, qtbot):
        """Deve aceitar arrasto de arquivo JSON"""
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QDragEnterEvent
        
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile('/path/to/data.json')])
        
        event = QDragEnterEvent(
            editor.rect().center(),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        
        editor.dragEnterEvent(event)
        assert event.isAccepted()
    
    def test_drag_enter_accepts_xlsx_file(self, editor, qtbot):
        """Deve aceitar arrasto de arquivo XLSX"""
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QDragEnterEvent
        
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile('/path/to/data.xlsx')])
        
        event = QDragEnterEvent(
            editor.rect().center(),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        
        editor.dragEnterEvent(event)
        assert event.isAccepted()
    
    def test_drag_enter_rejects_unsupported_file(self, editor, qtbot):
        """Deve rejeitar arrasto de arquivo não suportado"""
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QDragEnterEvent
        
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile('/path/to/file.txt')])
        
        event = QDragEnterEvent(
            editor.rect().center(),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        
        editor.dragEnterEvent(event)
        assert not event.isAccepted()
    
    def test_drop_csv_creates_python_block(self, editor, qtbot):
        """Deve criar bloco Python ao soltar arquivo CSV"""
        from PyQt6.QtCore import QMimeData, QUrl, QPointF
        from PyQt6.QtGui import QDropEvent
        
        initial_block_count = editor.get_block_count()
        
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile('/path/to/data.csv')])
        
        event = QDropEvent(
            QPointF(editor.rect().center()),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        
        with qtbot.waitSignal(editor.content_changed, timeout=1000):
            editor.dropEvent(event)
        
        # Deve ter criado um novo bloco
        assert editor.get_block_count() == initial_block_count + 1
        
        # O novo bloco deve ser Python
        blocks = editor.get_blocks()
        new_block = blocks[-1]
        assert new_block.get_language() == 'python'
        
        # Deve conter código de importação
        code = new_block.get_code()
        assert 'import pandas as pd' in code
        assert 'pd.read_csv' in code
        assert '/path/to/data.csv' in code
    
    def test_drop_json_creates_python_block(self, editor, qtbot):
        """Deve criar bloco Python ao soltar arquivo JSON"""
        from PyQt6.QtCore import QMimeData, QUrl, QPointF
        from PyQt6.QtGui import QDropEvent
        
        initial_block_count = editor.get_block_count()
        
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile('/path/to/data.json')])
        
        event = QDropEvent(
            QPointF(editor.rect().center()),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        
        with qtbot.waitSignal(editor.content_changed, timeout=1000):
            editor.dropEvent(event)
        
        # Deve ter criado um novo bloco
        assert editor.get_block_count() == initial_block_count + 1
        
        # O novo bloco deve ser Python
        blocks = editor.get_blocks()
        new_block = blocks[-1]
        assert new_block.get_language() == 'python'
        
        # Deve conter código de importação
        code = new_block.get_code()
        assert 'import pandas as pd' in code
        assert 'pd.read_json' in code
        assert '/path/to/data.json' in code
    
    def test_drop_xlsx_creates_python_block(self, editor, qtbot):
        """Deve criar bloco Python ao soltar arquivo XLSX"""
        from PyQt6.QtCore import QMimeData, QUrl, QPointF
        from PyQt6.QtGui import QDropEvent
        
        initial_block_count = editor.get_block_count()
        
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile('/path/to/data.xlsx')])
        
        event = QDropEvent(
            QPointF(editor.rect().center()),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        
        with qtbot.waitSignal(editor.content_changed, timeout=1000):
            editor.dropEvent(event)
        
        # Deve ter criado um novo bloco
        assert editor.get_block_count() == initial_block_count + 1
        
        # O novo bloco deve ser Python
        blocks = editor.get_blocks()
        new_block = blocks[-1]
        assert new_block.get_language() == 'python'
        
        # Deve conter código de importação
        code = new_block.get_code()
        assert 'import pandas as pd' in code
        assert 'pd.read_excel' in code
        assert '/path/to/data.xlsx' in code
    
    def test_drop_multiple_files_creates_multiple_blocks(self, editor, qtbot):
        """Deve criar múltiplos blocos ao soltar múltiplos arquivos"""
        from PyQt6.QtCore import QMimeData, QUrl, QPointF
        from PyQt6.QtGui import QDropEvent
        
        initial_block_count = editor.get_block_count()
        
        mime_data = QMimeData()
        mime_data.setUrls([
            QUrl.fromLocalFile('/path/to/data1.csv'),
            QUrl.fromLocalFile('/path/to/data2.json'),
            QUrl.fromLocalFile('/path/to/data3.xlsx')
        ])
        
        event = QDropEvent(
            QPointF(editor.rect().center()),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        
        with qtbot.waitSignal(editor.content_changed, timeout=1000):
            editor.dropEvent(event)
        
        # Deve ter criado 3 novos blocos
        assert editor.get_block_count() == initial_block_count + 3
        
        # Todos devem ser Python
        blocks = editor.get_blocks()
        assert blocks[-3].get_language() == 'python'
        assert blocks[-2].get_language() == 'python'
        assert blocks[-1].get_language() == 'python'
        
        # Verificar que cada um tem o código correto
        assert 'data1.csv' in blocks[-3].get_code()
        assert 'pd.read_csv' in blocks[-3].get_code()
        
        assert 'data2.json' in blocks[-2].get_code()
        assert 'pd.read_json' in blocks[-2].get_code()
        
        assert 'data3.xlsx' in blocks[-1].get_code()
        assert 'pd.read_excel' in blocks[-1].get_code()
    
    def test_drop_preserves_existing_blocks(self, editor, qtbot):
        """Soltar arquivo não deve afetar blocos existentes"""
        from PyQt6.QtCore import QMimeData, QUrl, QPointF
        from PyQt6.QtGui import QDropEvent
        
        # Adicionar alguns blocos
        editor.get_blocks()[0].set_language('sql')
        editor.get_blocks()[0].set_code('SELECT 1')
        editor.add_block(language='python', code='print("test")')
        
        initial_blocks = [b.get_code() for b in editor.get_blocks()]
        initial_count = editor.get_block_count()
        
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile('/path/to/data.csv')])
        
        event = QDropEvent(
            QPointF(editor.rect().center()),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        
        with qtbot.waitSignal(editor.content_changed, timeout=1000):
            editor.dropEvent(event)
        
        # Blocos originais devem permanecer intactos
        blocks = editor.get_blocks()
        for i, original_code in enumerate(initial_blocks):
            assert blocks[i].get_code() == original_code
