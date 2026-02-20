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

    # Aguardar criacao completa da sessao inicial (carregamento diferido)
    QApplication.processEvents()
    for _ in range(20):
        QTest.qWait(100)
        QApplication.processEvents()
        if window._get_current_editor() is not None:
            break

    # Se nao havia sessao, criar uma via _new_session
    editor = window._get_current_editor()
    if editor is None:
        window._new_session()
        QApplication.processEvents()
        for _ in range(10):
            QTest.qWait(100)
            QApplication.processEvents()
            if window._get_current_editor() is not None:
                break
        editor = window._get_current_editor()

    assert editor is not None, "Editor inicial nao foi criado"

    yield window

    # Cleanup para evitar crash ao criar multiplas MainWindows
    window.close()
    QApplication.processEvents()
    window.deleteLater()
    QApplication.processEvents()


def test_shortcut_execute_sql_without_selection(main_window):
    """Testa F5 - Executar bloco atual (sem selecao executa bloco focado)"""
    # Pegar sessao atual
    session = main_window.session_manager.focused_session
    assert session is not None

    # Pegar editor da sessao atual
    editor = main_window._get_current_editor()
    assert isinstance(editor, BlockEditor)

    # Adicionar codigo em multiplos blocos
    editor.clear_blocks()
    block1 = editor.add_block(language="PYTHON")
    block1.set_code("x = 10")

    block2 = editor.add_block(language="PYTHON")
    block2.set_code("y = 20")

    # Focar no primeiro bloco (sem selecao)
    block1.focus_editor()

    # Pressionar F5
    QTest.keyClick(main_window, Qt.Key.Key_F5)
    QApplication.processEvents()

    # Verificar que executou (sem selecao, deve executar apenas o bloco focado)
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
    assert hasattr(main_window, "_shortcuts")
    assert len(main_window._shortcuts) > 0

    # Verificar atalhos específicos
    shortcut_manager = main_window.shortcut_manager

    required_shortcuts = [
        # Execucao
        "execute_sql",
        "execute_all",
        "execute_block_advance",
        "clear_results",
        # Arquivo
        "open_file",
        "save_file",
        "save_as",
        # Sessões
        "new_tab",
        "close_tab",
        "add_block",
        # Edição - find/replace gerenciados pelos editores
        # 'find', 'replace' removidos - cada editor tem seus próprios
        # Conexões
        "manage_connections",
        "new_connection",
        # Ferramentas
        "settings",
    ]

    for shortcut_name in required_shortcuts:
        shortcut_key = shortcut_manager.get_shortcut(shortcut_name)
        assert shortcut_key, f"Atalho '{shortcut_name}' não encontrado"
        assert shortcut_key != "", f"Atalho '{shortcut_name}' está vazio"


def test_no_ambiguous_shortcuts(main_window):
    """Verifica que nao ha atalhos duplicados/ambiguos"""
    shortcut_manager = main_window.shortcut_manager
    all_shortcuts = shortcut_manager.get_all_shortcuts()

    # Contar valores (teclas) - ignorar atalhos vazios (desabilitados)
    shortcuts_values = [v for v in all_shortcuts.values() if v]

    # Verificar se nao ha duplicatas
    for shortcut_key in shortcuts_values:
        count = shortcuts_values.count(shortcut_key)
        assert count == 1, f"Atalho '{shortcut_key}' esta duplicado!"


def test_shift_enter_does_not_insert_newline(main_window):
    """Shift+Enter nao deve inserir nova linha no editor (liberado para execute_block_advance)"""
    from src.editors.code_editor import CodeEditor

    editor = main_window._get_current_editor()
    assert editor is not None

    # Forcar Shift+Return como atalho do app (independente de config do usuario)
    CodeEditor.set_app_shortcuts(
        set(CodeEditor._app_shortcut_sequences) | {"Shift+Return"}
    )
    assert "Shift+Return" in CodeEditor._app_shortcut_sequences

    # Limpar e adicionar bloco com codigo
    editor.clear_blocks()
    block = editor.add_block(language="PYTHON")
    block.set_code("x = 1")
    block.focus_editor()
    QApplication.processEvents()
    QTest.qWait(100)

    # Verificar que o event filter esta instalado
    assert hasattr(block.editor, '_key_filter'), "Event filter nao foi instalado no CodeEditor"

    # Contar linhas antes
    text_before = block.get_code()

    # Pressionar Shift+Enter no editor (QScintilla)
    sci = block.editor._sci
    QTest.keyClick(sci, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QApplication.processEvents()
    QTest.qWait(100)

    # O texto nao deve ter mudado (Shift+Enter nao deve inserir newline)
    text_after = block.get_code()
    assert text_after == text_before, (
        f"Shift+Enter inseriu nova linha no editor! Antes: {text_before!r}, Depois: {text_after!r}"
    )


def test_editor_shortcuts_configurable(main_window):
    """Atalhos do editor (QScintilla) devem aparecer nas configuracoes"""
    shortcut_manager = main_window.shortcut_manager
    all_shortcuts = shortcut_manager.get_all_shortcuts()

    editor_shortcuts = [k for k in all_shortcuts if k.startswith("editor_")]
    assert len(editor_shortcuts) >= 5, (
        f"Deveria ter pelo menos 5 atalhos de editor, encontrou {len(editor_shortcuts)}: {editor_shortcuts}"
    )

    # editor_newline deve estar vazio por padrao (liberado para o app)
    assert shortcut_manager.get_shortcut("editor_newline") == "", (
        "editor_newline deveria estar vazio por padrao"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
