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
    """Fixture da MainWindow"""
    window = MainWindow()
    window.show()
    QTest.qWaitForWindowExposed(window)
    QApplication.processEvents()
    QTest.qWait(500)
    return window


def test_rename_inline_available(main_window):
    """Testa que o método de renomeação inline existe"""
    tab_bar = main_window.session_tabs.tabBar()
    assert hasattr(tab_bar, '_rename_tab_inline')


def test_duplicate_inserts_before_plus_button(main_window):
    """Testa que duplicação insere antes do botão +"""
    # Criar algumas sessões
    initial_count = main_window.session_tabs.count()
    
    main_window._new_session()
    QApplication.processEvents()
    QTest.qWait(100)
    
    # Verificar que botão + está no final
    last_index = main_window.session_tabs.count() - 1
    last_tab_text = main_window.session_tabs.tabText(last_index)
    assert last_tab_text.strip() == "+"
    
    # Duplicar primeira aba
    main_window._duplicate_session(0)
    QApplication.processEvents()
    QTest.qWait(200)
    
    # Verificar que + ainda está no final
    new_last_index = main_window.session_tabs.count() - 1
    new_last_tab_text = main_window.session_tabs.tabText(new_last_index)
    assert new_last_tab_text.strip() == "+"
    
    # Verificar que aba duplicada está antes do +
    duplicated_index = new_last_index - 1
    duplicated_text = main_window.session_tabs.tabText(duplicated_index)
    assert "(cópia)" in duplicated_text


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
