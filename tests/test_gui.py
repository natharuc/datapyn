"""
Testes de Interface Gráfica (GUI) - Executam com a janela real

Estes testes abrem a interface gráfica real e simulam interações do usuário.
São úteis para validar que a aplicação funciona visualmente.

Para executar apenas estes testes:
    python -m pytest tests/test_gui.py -v

Para executar todos os testes incluindo GUI:
    python -m pytest -v

Para executar o teste visual interativo:
    python -m tests.test_gui --visual
"""
import sys
import pytest
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest

from src.ui.main_window import MainWindow
from src.editors.block_editor import BlockEditor
from src.editors.code_block import CodeBlock
from src.core.theme_manager import ThemeManager


# === Fixtures ===

@pytest.fixture(scope="module")
def qapp():
    """QApplication singleton para todos os testes"""
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    yield app


@pytest.fixture
def theme_manager():
    return ThemeManager()


@pytest.fixture
def main_window(qapp, tmp_path, monkeypatch):
    """Cria MainWindow para testes GUI - agora usa apenas QScintilla"""
    # Evita salvar configurações reais
    monkeypatch.setenv('DATAPYN_CONFIG_PATH', str(tmp_path))
    
    # Cria janela
    window = MainWindow()
    window.show()
    QTest.qWaitForWindowExposed(window)
    
    # Aguarda um pouco para a sessão ser criada (tempo aumentado para Linux)
    QTest.qWait(500)
    
    yield window
    
    window.close()


def get_editor_safely(window):
    """Helper para obter editor de forma segura"""
    widget = window._get_current_session_widget()
    if widget is None:
        # Cria nova sessão se não existir
        window._new_session()
        QTest.qWait(300)  # Tempo aumentado para Linux
        widget = window._get_current_session_widget()
    
    if widget is None:
        pytest.skip("Não foi possível criar sessão para teste GUI")
    
    return widget.editor, widget


# === Testes de Blocos na GUI ===

class TestBlockEditorGUI:
    """Testes do BlockEditor com interface visual"""
    
    def test_create_block_visually(self, main_window):
        """Teste: Criar bloco visualmente"""
        editor, widget = get_editor_safely(main_window)
        
        initial_count = len(editor.get_blocks())
        editor.add_block()
        
        assert len(editor.get_blocks()) == initial_count + 1
    
    def test_change_language_visually(self, main_window):
        """Teste: Mudar linguagem do bloco visualmente"""
        editor, widget = get_editor_safely(main_window)
        block = editor.get_blocks()[0]
        
        # Muda para SQL
        block.set_language('sql')
        QTest.qWait(100)
        assert block.get_language() == 'sql'
        
        # Muda para Cross
        block.set_language('cross')
        QTest.qWait(100)
        assert block.get_language() == 'cross'
        
        # Muda para Python
        block.set_language('python')
        QTest.qWait(100)
        assert block.get_language() == 'python'
    
    def test_write_code_visually(self, main_window):
        """Teste: Escrever código no bloco"""
        editor, widget = get_editor_safely(main_window)
        block = editor.get_blocks()[0]
        
        test_code = "SELECT * FROM teste"
        block.set_code(test_code)
        QTest.qWait(100)
        
        assert block.get_code() == test_code
    
    def test_multiple_blocks_different_languages(self, main_window):
        """Teste: Múltiplos blocos com linguagens diferentes"""
        editor, widget = get_editor_safely(main_window)
        
        # Limpa blocos existentes
        while len(editor.get_blocks()) > 1:
            editor.remove_block(editor.get_blocks()[-1])
        
        # Configura primeiro bloco como SQL
        sql_block = editor.get_blocks()[0]
        sql_block.set_language('sql')
        sql_block.set_code('SELECT * FROM cliente')
        
        # Adiciona bloco Cross
        cross_block = editor.add_block(language='cross')
        cross_block.set_code('df = {{SELECT * FROM produto}}')
        
        # Adiciona bloco Python
        python_block = editor.add_block(language='python')
        python_block.set_code('print(df.head())')
        
        QTest.qWait(200)
        
        # Verifica
        blocks = editor.get_blocks()
        assert len(blocks) == 3
        assert blocks[0].get_language() == 'sql'
        assert blocks[1].get_language() == 'cross'
        assert blocks[2].get_language() == 'python'


class TestBlockExecutionGUI:
    """Testes de execução de blocos na GUI"""
    
    def test_execute_emits_correct_signal(self, main_window):
        """Teste: Executar bloco emite sinal correto"""
        editor, widget = get_editor_safely(main_window)
        
        # Configura bloco SQL
        block = editor.get_blocks()[0]
        block.set_language('sql')
        block.set_code('SELECT 1')
        
        # Rastreia sinais
        sql_emitted = []
        editor.execute_sql.connect(lambda code: sql_emitted.append(code))
        
        # Executa
        editor.execute_focused_block()
        QTest.qWait(100)
        
        assert len(sql_emitted) == 1
        assert 'SELECT 1' in sql_emitted[0]
    
    def test_cross_syntax_emits_cross_signal(self, main_window):
        """Teste: Cross-syntax emite sinal correto (não SQL)"""
        editor, widget = get_editor_safely(main_window)
        
        # Configura bloco Cross
        block = editor.get_blocks()[0]
        block.set_language('cross')
        block.set_code('df = {{SELECT * FROM teste}}')
        
        # Rastreia sinais
        cross_emitted = []
        sql_emitted = []
        
        editor.execute_cross_syntax.connect(lambda code: cross_emitted.append(code))
        editor.execute_sql.connect(lambda code: sql_emitted.append(code))
        
        # Executa
        editor.execute_focused_block()
        QTest.qWait(300)
        
        # Cross-syntax deve emitir cross, NÃO sql
        assert len(cross_emitted) == 1
        assert len(sql_emitted) == 0
        assert '{{SELECT' in cross_emitted[0]
    
    def test_execute_all_blocks_in_order(self, main_window):
        """Teste: Executar todos os blocos na ordem correta"""
        editor, widget = get_editor_safely(main_window)
        
        # Limpa e cria blocos
        while len(editor.get_blocks()) > 1:
            editor.remove_block(editor.get_blocks()[-1])
        
        # Bloco 1: SQL
        block1 = editor.get_blocks()[0]
        block1.set_language('sql')
        block1.set_code('SELECT 1')
        
        # Bloco 2: Cross
        block2 = editor.add_block(language='cross')
        block2.set_code('x = {{SELECT 2}}')
        
        # Bloco 3: Python
        block3 = editor.add_block(language='python')
        block3.set_code('print(x)')
        
        # Rastreia fila
        queue_received = []
        editor.execute_queue.connect(lambda q: queue_received.extend(q))
        
        # Executa todos
        editor.execute_all_blocks()
        QTest.qWait(200)
        
        # Verifica ordem
        assert len(queue_received) == 3
        assert queue_received[0][0] == 'sql'
        assert queue_received[1][0] == 'cross'
        assert queue_received[2][0] == 'python'


class TestSessionPersistenceGUI:
    """Testes de persistência de sessão na GUI"""
    
    def test_blocks_persist_to_session(self, main_window):
        """Teste: Blocos são salvos na sessão"""
        editor, widget = get_editor_safely(main_window)
        session = widget.session
        
        # Configura blocos
        block = editor.get_blocks()[0]
        block.set_language('sql')
        block.set_code('SELECT * FROM teste')
        
        # Sincroniza com sessão
        widget.sync_to_session()
        
        # Verifica
        blocks_data = session.blocks
        assert len(blocks_data) >= 1
        assert blocks_data[0]['language'] == 'sql'
        assert 'SELECT' in blocks_data[0]['code']
    
    def test_resize_block_persists(self, main_window):
        """Teste: Redimensionar bloco persiste altura"""
        editor, widget = get_editor_safely(main_window)
        block = editor.get_blocks()[0]
        
        # Simula resize
        block._set_editor_height(200)
        QTest.qWait(100)
        
        # Serializa
        data = block.to_dict()
        
        assert data['height'] == 200


class TestThemeGUI:
    """Testes de tema na GUI"""
    
    def test_apply_theme_no_crash(self, main_window):
        """Teste: Aplicar tema não causa crash"""
        editor, widget = get_editor_safely(main_window)
        
        # Aplica tema
        for block in editor.get_blocks():
            block.apply_theme()
        
        QTest.qWait(100)
        # Se chegou aqui, não crashou
        assert True


# === Teste Visual Interativo ===

class VisualTester:
    """Executa testes visuais interativos (para debug)"""
    
    def __init__(self, window: MainWindow):
        self.window = window
    
    def log(self, msg):
        print(f"[TESTE] {msg}")
        try:
            widget = self.window._get_current_session_widget()
            if widget:
                widget.append_output(f"🧪 {msg}")
        except:
            pass
    
    def wait(self, ms=500):
        QTest.qWait(ms)
    
    def run_all_tests(self):
        """Executa todos os testes visuais"""
        self.log("=" * 50)
        self.log("TESTE VISUAL INTERATIVO")
        self.log("=" * 50)
        self.wait(500)
        
        try:
            self.test_01_initial_state()
            self.test_02_create_blocks()
            self.test_03_change_languages()
            self.test_04_write_code()
            self.test_05_execute()
            
            self.log("=" * 50)
            self.log("✅ TODOS OS TESTES PASSARAM!")
            self.log("=" * 50)
            
        except AssertionError as e:
            self.log(f"❌ FALHA: {e}")
        except Exception as e:
            self.log(f"❌ ERRO: {e}")
            import traceback
            traceback.print_exc()
    
    def test_01_initial_state(self):
        """Verifica estado inicial"""
        self.log("Passo 1: Verificando estado inicial...")
        
        widget = self.window._get_current_session_widget()
        assert widget is not None
        
        blocks = widget.editor.get_blocks()
        assert len(blocks) >= 1
        
        self.log(f"  ✓ {len(blocks)} bloco(s) encontrado(s)")
        self.wait()
    
    def test_02_create_blocks(self):
        """Cria múltiplos blocos"""
        self.log("Passo 2: Criando blocos...")
        
        widget = self.window._get_current_session_widget()
        editor = widget.editor
        
        # Limpa blocos extras
        while len(editor.get_blocks()) > 1:
            editor.remove_block(editor.get_blocks()[-1])
        
        # Adiciona 2 blocos novos
        editor.add_block()
        editor.add_block()
        
        self.wait(300)
        
        assert len(editor.get_blocks()) == 3
        self.log(f"  ✓ {len(editor.get_blocks())} blocos criados")
        self.wait()
    
    def test_03_change_languages(self):
        """Muda linguagens dos blocos"""
        self.log("Passo 3: Mudando linguagens...")
        
        widget = self.window._get_current_session_widget()
        blocks = widget.editor.get_blocks()
        
        blocks[0].set_language('sql')
        blocks[1].set_language('cross')
        blocks[2].set_language('python')
        
        self.wait(300)
        
        assert blocks[0].get_language() == 'sql'
        assert blocks[1].get_language() == 'cross'
        assert blocks[2].get_language() == 'python'
        
        self.log("  ✓ SQL, Cross, Python configurados")
        self.wait()
    
    def test_04_write_code(self):
        """Escreve código nos blocos"""
        self.log("Passo 4: Escrevendo código...")
        
        widget = self.window._get_current_session_widget()
        blocks = widget.editor.get_blocks()
        
        blocks[0].set_code('SELECT * FROM cliente LIMIT 5')
        blocks[1].set_code('df = {{SELECT id, nome FROM produto}}')
        blocks[2].set_code('print(f"Produtos: {len(df)}")')
        
        self.wait(300)
        
        self.log("  ✓ Código escrito em todos os blocos")
        for i, block in enumerate(blocks):
            self.log(f"     [{i+1}] {block.get_language().upper()}: {block.get_code()[:40]}...")
        self.wait()
    
    def test_05_execute(self):
        """Executa todos os blocos"""
        self.log("Passo 5: Executando blocos...")
        
        widget = self.window._get_current_session_widget()
        editor = widget.editor
        
        # Rastreia execuções
        executed = []
        editor.execute_queue.connect(lambda q: [executed.append((l, c[:30])) for l, c in q])
        
        # Executa
        editor.execute_all_blocks()
        self.wait(500)
        
        self.log(f"  ✓ {len(executed)} blocos executados")
        
        # Verifica que cross foi identificado corretamente
        for lang, code in executed:
            if '{{' in code:
                assert lang == 'cross', f"Cross deveria ser 'cross', não '{lang}'"
        
        self.log("  ✓ Linguagens identificadas corretamente!")
        self.wait(1000)


def run_visual_test():
    """Executa teste visual interativo"""
    app = QApplication(sys.argv)
    
    print("=" * 60)
    print("TESTE VISUAL INTERATIVO")
    print("A janela vai abrir e os testes serão executados.")
    print("=" * 60)
    
    window = MainWindow()
    window.show()
    
    tester = VisualTester(window)
    QTimer.singleShot(1500, tester.run_all_tests)
    
    sys.exit(app.exec())


if __name__ == '__main__':
    if '--visual' in sys.argv:
        run_visual_test()
    else:
        # Executa com pytest
        pytest.main([__file__, '-v'])
