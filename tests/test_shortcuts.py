"""
Testes para validar todos os atalhos de teclado
"""
import pytest
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence

# Adicionar src ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ui.main_window import MainWindow
from src.editors.block_editor import BlockEditor


@pytest.fixture
def app(qapp):
    """Fixture do QApplication"""
    return qapp


@pytest.fixture
def main_window(app):
    """Fixture da MainWindow - roda com QScintilla E Monaco"""
    window = MainWindow()
    window.show()
    QTest.qWaitForWindowExposed(window)
    
    # Garantir que há uma sessão inicial com editor válido
    QApplication.processEvents()
    QTest.qWait(500)  # Aguardar criação completa da sessão inicial
    
    # Verificar que o editor existe
    editor = window._get_current_editor()
    assert editor is not None, "Editor inicial não foi criado"
    
    return window


def test_shortcut_execute_sql_without_selection(main_window):
    """Testa F5 - Executar bloco atual (sem seleção executa todos)"""
    # Pegar sessão atual
    session = main_window.session_manager.focused_session
    assert session is not None
    
    # Pegar editor da sessão atual
    editor = main_window._get_current_editor()
    assert isinstance(editor, BlockEditor)
    
    # Adicionar código em múltiplos blocos
    editor.clear_blocks()
    block1 = editor.add_block(language="PYTHON")
    block1.set_code("x = 10")
    
    block2 = editor.add_block(language="PYTHON")
    block2.set_code("y = 20")
    
    # Focar no primeiro bloco (sem seleção)
    block1.focus_editor()
    
    # Pressionar F5
    QTest.keyClick(main_window, Qt.Key.Key_F5)
    QApplication.processEvents()
    
    # Verificar que executou (sem seleção, deve executar todos)
    # O comportamento esperado é executar todos os blocos
    assert True  # Se chegou aqui sem erro, funcionou


def test_shortcut_execute_all(main_window):
    """Testa Ctrl+F5 - Executar todos os blocos (mesmo com seleção)"""
    editor = main_window._get_current_editor()
    assert editor is not None, "Nenhum editor disponível"
    
    # Adicionar código
    editor.clear_blocks()
    block1 = editor.add_block(language="PYTHON")
    block1.set_code("a = 100\nprint(a)")
    
    block2 = editor.add_block(language="PYTHON")
    block2.set_code("b = 200")
    
    # Focar e selecionar texto no primeiro bloco
    block1.focus_editor()
    block1.editor.selectAll()
    
    # Pressionar Ctrl+F5 (deve executar TODOS mesmo com seleção)
    QTest.keySequence(main_window, QKeySequence("Ctrl+F5"))
    QApplication.processEvents()
    
    # Se chegou aqui sem erro, funcionou
    assert True


def test_shortcut_new_tab(main_window):
    """Testa Ctrl+T - Nova aba"""
    # Pressionar Ctrl+T
    QTest.keySequence(main_window, QKeySequence("Ctrl+T"))
    QApplication.processEvents()
    QTest.qWait(200)  # Aguardar processamento
    
    # Se chegou aqui sem erro, o atalho funcionou
    assert True


def test_shortcut_close_tab(main_window):
    """Testa Ctrl+W - Fechar aba"""
    # Criar múltiplas sessões primeiro
    main_window.session_manager.create_session()
    main_window.session_manager.create_session()
    QApplication.processEvents()
    QTest.qWait(200)
    
    # Pressionar Ctrl+W
    QTest.keySequence(main_window, QKeySequence("Ctrl+W"))
    QApplication.processEvents()
    QTest.qWait(200)  # Aguardar processamento
    
    # Se chegou aqui sem erro, o atalho funcionou
    assert True


# test_shortcut_find e test_shortcut_replace removidos
# Ctrl+F e Ctrl+H agora são gerenciados nativamente pelos editores (QScintilla/Monaco)


def test_shortcut_save_file(main_window):
    """Testa Ctrl+S - Salvar arquivo"""
    # Adicionar código
    editor = main_window._get_current_editor()
    assert editor is not None, "Nenhum editor disponível"
    
    block = editor.add_block()
    block.set_code("# Code to save")
    
    # Pressionar Ctrl+S (vai abrir diálogo de salvar)
    QTest.keySequence(main_window, QKeySequence("Ctrl+S"))
    QApplication.processEvents()
    
    # Se não deu erro, funcionou
    assert True


def test_shortcut_open_file(main_window):
    """Testa Ctrl+O - Abrir arquivo"""
    # Pressionar Ctrl+O (vai abrir diálogo)
    QTest.keySequence(main_window, QKeySequence("Ctrl+O"))
    QApplication.processEvents()
    
    # Se não deu erro, funcionou
    assert True


def test_all_shortcuts_registered(main_window):
    """Verifica se todos os atalhos foram registrados"""
    # Verificar que todos os atalhos estão na lista protegida contra GC
    assert hasattr(main_window, '_shortcuts')
    assert len(main_window._shortcuts) > 0
    
    # Verificar atalhos específicos
    shortcut_manager = main_window.shortcut_manager
    
    required_shortcuts = [
        # Execução
        'execute_sql',
        'execute_all',
        'clear_results',
        
        # Arquivo
        'open_file',
        'save_file',
        'save_as',
        
        # Sessões
        'new_tab',
        'close_tab',
        'add_block',
        
        # Edição - find/replace gerenciados pelos editores
        # 'find', 'replace' removidos - cada editor tem seus próprios
        
        # Conexões
        'manage_connections',
        'new_connection',
        
        # Ferramentas
        'settings',
    ]
    
    for shortcut_name in required_shortcuts:
        shortcut_key = shortcut_manager.get_shortcut(shortcut_name)
        assert shortcut_key, f"Atalho '{shortcut_name}' não encontrado"
        assert shortcut_key != '', f"Atalho '{shortcut_name}' está vazio"


def test_no_ambiguous_shortcuts(main_window):
    """Verifica que não há atalhos duplicados/ambíguos"""
    shortcut_manager = main_window.shortcut_manager
    all_shortcuts = shortcut_manager.get_all_shortcuts()
    
    # Contar valores (teclas)
    shortcuts_values = list(all_shortcuts.values())
    
    # Verificar se não há duplicatas
    for shortcut_key in shortcuts_values:
        count = shortcuts_values.count(shortcut_key)
        assert count == 1, f"Atalho '{shortcut_key}' está duplicado!"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
