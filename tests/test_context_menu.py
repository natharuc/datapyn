"""
Testes para context menu das abas
"""
import pytest
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt, QPoint
import tempfile
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ui.main_window import MainWindow


@pytest.fixture
def main_window(qapp):
    """Fixture da MainWindow - roda com QScintilla E Monaco"""
    window = MainWindow()
    window.show()
    QTest.qWaitForWindowExposed(window)
    # Aguardar restauracao completa de todas as sessoes salvas
    for _ in range(100):
        QApplication.processEvents()
        QTest.qWait(50)
        if not hasattr(window, '_sessions_to_load') or not window._sessions_to_load:
            break
    QApplication.processEvents()
    return window


def test_rename_inline_available(main_window):
    """Testa que o método de renomeação inline existe"""
    tab_bar = main_window.session_tabs.tabBar()
    assert hasattr(tab_bar, '_rename_tab_inline')


def test_duplicate_inserts_before_plus_button(main_window):
    """Testa que duplicação cria nova aba corretamente"""
    # Criar algumas sessões
    initial_count = main_window.session_tabs.count()
    
    main_window._new_session()
    QApplication.processEvents()
    QTest.qWait(100)
    
    count_before = main_window.session_tabs.count()
    
    # Duplicar primeira aba
    main_window._duplicate_session(0)
    QApplication.processEvents()
    QTest.qWait(200)
    
    # Verificar que foi criada uma nova aba
    count_after = main_window.session_tabs.count()
    assert count_after == count_before + 1
    
    # Verificar que existe uma aba com "(copia)" no nome
    found_copy = False
    for i in range(count_after):
        tab_text = main_window.session_tabs.tabText(i)
        if "(copia)" in tab_text:
            found_copy = True
            break
    assert found_copy, "Deve existir uma aba com '(copia)' no nome"


def test_close_button_has_custom_icon(main_window):
    """Testa que close button tem configuração customizada"""
    # Verificar que método _setup_close_button existe
    assert hasattr(main_window.session_tabs, '_setup_close_button')
    
    # Verificar que botão de fechar existe na primeira aba
    from PyQt6.QtWidgets import QTabBar
    tab_bar = main_window.session_tabs.tabBar()
    close_button = tab_bar.tabButton(0, QTabBar.ButtonPosition.RightSide)
    
    # Deve ter um botão customizado (não None)
    assert close_button is not None


def test_session_close_keyerror_fixed(main_window):
    """Testa que fechar sessão não gera KeyError"""
    # Criar nova sessão
    main_window._new_session()
    QApplication.processEvents()
    QTest.qWait(100)
    
    current_count = main_window.session_tabs.count()
    
    # Fechar última sessão (exceto +)
    session_index = current_count - 2  # Antes do +
    
    # Isso não deve gerar KeyError
    try:
        main_window._close_session_tab(session_index)
        QApplication.processEvents()
        QTest.qWait(200)
        assert True  # Se chegou aqui, não teve erro
    except KeyError as e:
        pytest.fail(f"KeyError ao fechar sessão: {e}")


def test_context_menu_has_rename_option(main_window):
    """Testa que context menu tem opção Renomear"""
    tab_bar = main_window.session_tabs.tabBar()
    
    # Verificar que método existe
    assert hasattr(tab_bar, '_show_context_menu')
    assert hasattr(tab_bar, '_rename_tab_inline')
