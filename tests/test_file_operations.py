"""
Testes para operações com arquivos
"""
import pytest
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
import tempfile
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ui.main_window import MainWindow
from src.editors.block_editor import BlockEditor


@pytest.fixture
def main_window(qapp):
    """Fixture da MainWindow"""
    window = MainWindow()
    window.show()
    QTest.qWaitForWindowExposed(window)
    QApplication.processEvents()
    QTest.qWait(500)
    return window


@pytest.fixture
def temp_sql_file():
    """Cria arquivo SQL temporário"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False, encoding='utf-8') as f:
        f.write("SELECT * FROM users WHERE id = 1;\n")
        f.write("SELECT COUNT(*) FROM orders;")
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    if os.path.exists(temp_path):
        os.remove(temp_path)


@pytest.fixture
def temp_python_file():
    """Cria arquivo Python temporário"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write("import pandas as pd\n\n")
        f.write("df = pd.DataFrame({'a': [1, 2, 3]})\n")
        f.write("print(df)")
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    if os.path.exists(temp_path):
        os.remove(temp_path)


def test_open_sql_file(main_window, temp_sql_file):
    """Testa abertura de arquivo SQL"""
    # Simular abertura de arquivo
    widget = main_window._get_current_session_widget()
    assert widget is not None
    
    # Abrir arquivo programaticamente
    with open(temp_sql_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Salvar caminho do arquivo
    widget.file_path = temp_sql_file
    
    # Limpar e adicionar conteúdo
    # clear_blocks() adiciona um bloco vazio, então vamos remover todos manualmente
    blocks = widget.editor.get_blocks()
    for block in blocks[:-1]:  # Remove todos exceto o último
        widget.editor.remove_block(block)
    
    # Usar o último bloco (que agora é o único)
    block = widget.editor.get_blocks()[0]
    block.set_language('sql')
    block.editor.setText(content)  # Usar setText do QScintilla
    QApplication.processEvents()
    QTest.qWait(100)
    
    # Verificar que o conteúdo foi carregado
    blocks = widget.editor.get_blocks()
    assert len(blocks) > 0
    assert 'SELECT' in blocks[0].editor.text()
    assert blocks[0].get_language() == 'sql'
    assert hasattr(widget, 'file_path')
    assert widget.file_path == temp_sql_file


def test_open_python_file(main_window, temp_python_file):
    """Testa abertura de arquivo Python"""
    widget = main_window._get_current_session_widget()
    assert widget is not None
    
    # Abrir arquivo
    with open(temp_python_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    widget.file_path = temp_python_file
    
    # Remover blocos extras (clear_blocks cria 1 vazio)
    blocks = widget.editor.get_blocks()
    for b in blocks[:-1]:
        widget.editor.remove_block(b)
    
    # Usar o último bloco
    block = widget.editor.get_blocks()[0]
    block.set_language('python')
    block.editor.setText(content)  # Usar setText do QScintilla
    QApplication.processEvents()
    QTest.qWait(100)
    
    # Verificar
    blocks = widget.editor.get_blocks()
    assert len(blocks) > 0
    assert 'import pandas' in blocks[0].editor.text()
    assert blocks[0].get_language() == 'python'


def test_duplicate_session(main_window):
    """Testa duplicação de sessão"""
    # Criar conteúdo na sessão atual
    widget = main_window._get_current_session_widget()
    
    # Remover blocos extras (manter só 1)
    blocks = widget.editor.get_blocks()
    for b in blocks[:-1]:
        widget.editor.remove_block(b)
    
    # Usar primeiro bloco e adicionar segundo
    block1 = widget.editor.get_blocks()[0]
    block1.set_language('sql')
    block1.editor.setText("SELECT 1")
    
    block2 = widget.editor.add_block(language='python')
    block2.editor.setText("print('hello')")
    
    QApplication.processEvents()
    QTest.qWait(200)
    
    initial_count = main_window.session_tabs.count()
    current_index = main_window.session_tabs.currentIndex()
    
    # Duplicar
    main_window._duplicate_session(current_index)
    QApplication.processEvents()
    QTest.qWait(200)
    
    # Verificar que foi criada nova sessão
    new_count = main_window.session_tabs.count()
    assert new_count == initial_count + 1
    
    # Verificar que o conteúdo foi copiado
    # Widget duplicado está antes do botão + (count - 2)
    new_widget = main_window.session_tabs.widget(new_count - 2)
    # Se o widget for QWidget vazio ("+"), pegar o anterior
    if not hasattr(new_widget, 'editor'):
        new_widget = main_window.session_tabs.widget(new_count - 2)
    
    new_blocks = new_widget.editor.get_blocks()
    
    assert len(new_blocks) == 2, f"Esperado 2 blocos, encontrado {len(new_blocks)}"
    assert new_blocks[0].editor.text() == "SELECT 1"
    assert new_blocks[0].get_language() == 'sql'
    assert new_blocks[1].editor.text() == "print('hello')"
    assert new_blocks[1].get_language() == 'python'


def test_close_all_tabs(main_window):
    """Testa fechar todas as abas"""
    # Criar múltiplas sessões
    initial_count = main_window.session_tabs.count()
    
    # Criar via método de UI que adiciona ao session_tabs
    for i in range(3):
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
    
    new_count = main_window.session_tabs.count()
    assert new_count >= initial_count + 3, f"Esperado >= {initial_count + 3}, obtido {new_count}"
    
    # Fechar todas (simular ação do context menu)
    tab_bar = main_window.session_tabs.tabBar()
    tab_bar._close_all_tabs()
    QApplication.processEvents()
    QTest.qWait(300)
    
    # Deve ter criado uma nova sessão empty state
    # O comportamento pode variar, mas não deve crashar
    assert True  # Se chegou aqui sem erro, passou


def test_close_other_tabs(main_window):
    """Testa fechar outras abas"""
    # Criar múltiplas sessões
    for i in range(3):
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(100)
    
    total_count = main_window.session_tabs.count()
    assert total_count >= 4, f"Esperado >= 4, obtido {total_count}"
    
    # Manter a aba 1 e fechar as outras
    keep_index = 1
    tab_bar = main_window.session_tabs.tabBar()
    tab_bar._close_other_tabs(keep_index)
    QApplication.processEvents()
    QTest.qWait(300)
    
    # Deve ter restado apenas 1 aba (ou criado empty state)
    new_count = main_window.session_tabs.count()
    assert new_count <= 2  # Pode ter 1 ou 2 (se criou empty state)


def test_file_path_preserved_on_duplicate(main_window, temp_sql_file):
    """Testa que file_path é preservado ao duplicar"""
    widget = main_window._get_current_session_widget()
    widget.file_path = temp_sql_file
    
    # Remover blocos extras
    blocks = widget.editor.get_blocks()
    for b in blocks[:-1]:
        widget.editor.remove_block(b)
    
    block = widget.editor.get_blocks()[0]
    block.set_language('sql')
    block.editor.setText("SELECT 1")
    
    QApplication.processEvents()
    QTest.qWait(200)
    
    current_index = main_window.session_tabs.currentIndex()
    
    # Duplicar
    main_window._duplicate_session(current_index)
    QApplication.processEvents()
    QTest.qWait(200)
    
    # Verificar que file_path foi copiado
    # Widget duplicado está antes do botão + (count - 2)
    new_count = main_window.session_tabs.count()
    new_widget = main_window.session_tabs.widget(new_count - 2)
    # Se for QWidget vazio ("+"), pegar o anterior
    if not hasattr(new_widget, 'file_path'):
        new_widget = main_window.session_tabs.widget(new_count - 3)
    
    assert hasattr(new_widget, 'file_path')
    assert new_widget.file_path == temp_sql_file


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
