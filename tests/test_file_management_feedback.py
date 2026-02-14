"""
Testes para feedback visual de gerenciamento de arquivos
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

from src.ui.components.statusbar import MainStatusBar
from src.ui.main_window import MainWindow
from src.core.workspace_manager import WorkspaceManager


@pytest.fixture
def statusbar(qapp):
    """Fixture para MainStatusBar isolada"""
    bar = MainStatusBar()
    return bar


@pytest.fixture
def main_window(qapp):
    """Fixture da MainWindow"""
    window = MainWindow()
    window.show()
    QTest.qWaitForWindowExposed(window)
    max_wait_time = 10000
    wait_interval = 100
    max_iterations = max_wait_time // wait_interval

    for _ in range(max_iterations):
        QApplication.processEvents()
        QTest.qWait(50)
        if not hasattr(window, "_sessions_to_load") or not window._sessions_to_load:
            break
        QTest.qWait(wait_interval)

    QApplication.processEvents()
    QTest.qWait(100)
    return window


@pytest.fixture
def temp_sql_file():
    """Cria arquivo SQL temporario"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False, encoding="utf-8") as f:
        f.write("SELECT * FROM users WHERE id = 1;\n")
        temp_path = f.name

    yield temp_path

    if os.path.exists(temp_path):
        os.remove(temp_path)


@pytest.fixture
def temp_python_file():
    """Cria arquivo Python temporario"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("import pandas as pd\nprint('hello')\n")
        temp_path = f.name

    yield temp_path

    if os.path.exists(temp_path):
        os.remove(temp_path)


class TestStatusBarFileInfo:
    """Testes para exibicao de informacoes de arquivo na statusbar"""

    def test_file_label_exists(self, statusbar):
        """Verifica que file_label foi criado na statusbar"""
        assert hasattr(statusbar, "file_label")

    def test_set_file_info_shows_path(self, statusbar):
        """Verifica que set_file_info exibe o caminho do arquivo"""
        statusbar.set_file_info("/home/user/test.sql")
        assert "/home/user/test.sql" in statusbar.file_label.text()
        assert statusbar.file_label.toolTip() == "/home/user/test.sql"

    def test_set_file_info_empty_clears(self, statusbar):
        """Verifica que set_file_info com string vazia limpa o label"""
        statusbar.set_file_info("/home/user/test.sql")
        statusbar.set_file_info("")
        assert statusbar.file_label.text() == ""
        assert statusbar.file_label.toolTip() == ""

    def test_set_file_info_no_args_clears(self, statusbar):
        """Verifica que set_file_info sem argumentos limpa o label"""
        statusbar.set_file_info("/home/user/test.sql")
        statusbar.set_file_info()
        assert statusbar.file_label.text() == ""


class TestStatusBarSaveFeedback:
    """Testes para feedback visual de salvamento"""

    def test_show_save_feedback_updates_text(self, statusbar):
        """Verifica que show_save_feedback atualiza o texto"""
        statusbar.show_save_feedback("Arquivo salvo: /tmp/test.sql")
        assert "Arquivo salvo" in statusbar.action_label.text()
        assert "/tmp/test.sql" in statusbar.action_label.text()

    def test_show_save_feedback_applies_highlight_style(self, statusbar):
        """Verifica que show_save_feedback aplica estilo de destaque"""
        statusbar.show_save_feedback("Salvo com sucesso")
        style = statusbar.action_label.styleSheet()
        assert "#4caf50" in style

    def test_feedback_timer_is_configured(self, statusbar):
        """Verifica que o timer de feedback esta configurado"""
        assert hasattr(statusbar, "_feedback_timer")
        assert statusbar._feedback_timer.isSingleShot()

    def test_restore_action_style(self, statusbar):
        """Verifica que _restore_action_style restaura o estilo padrao"""
        statusbar.show_save_feedback("Teste")
        statusbar._restore_action_style()
        style = statusbar.action_label.styleSheet()
        assert "#999999" in style


class TestWindowTitleFileInfo:
    """Testes para exibicao de informacoes de arquivo no titulo da janela"""

    def test_window_title_includes_datapyn(self, main_window):
        """Verifica que o titulo da janela contem DataPyn"""
        assert "DataPyn" in main_window.windowTitle()

    def test_window_title_includes_context_indicator(self, main_window):
        """Verifica que o titulo contem indicador de contexto"""
        title = main_window.windowTitle()
        has_indicator = "[SQL]" in title or "[Python]" in title or "[Workspace]" in title
        assert has_indicator, f"Titulo '{title}' nao contem indicador de contexto"

    def test_window_title_shows_file_path_after_open(self, main_window, temp_sql_file):
        """Verifica que o titulo mostra caminho completo apos abrir arquivo"""
        main_window._open_code_file(temp_sql_file)
        QApplication.processEvents()
        QTest.qWait(200)

        title = main_window.windowTitle()
        assert temp_sql_file in title, f"Titulo '{title}' nao contem caminho '{temp_sql_file}'"


class TestSaveFileFeedback:
    """Testes para feedback ao salvar arquivos"""

    def test_save_single_file_shows_feedback(self, main_window, temp_sql_file):
        """Verifica feedback visual ao salvar arquivo SQL"""
        main_window._open_code_file(temp_sql_file)
        QApplication.processEvents()
        QTest.qWait(200)

        main_window._save_single_file(temp_sql_file, "sql")
        QApplication.processEvents()

        action_text = main_window.main_statusbar.action_label.text()
        assert "Arquivo salvo" in action_text
        assert temp_sql_file in action_text

    def test_save_updates_statusbar_file_info(self, main_window, temp_sql_file):
        """Verifica que salvar atualiza info de arquivo na statusbar"""
        main_window._open_code_file(temp_sql_file)
        QApplication.processEvents()
        QTest.qWait(200)

        main_window._save_single_file(temp_sql_file, "sql")
        QApplication.processEvents()

        file_text = main_window.main_statusbar.file_label.text()
        assert temp_sql_file in file_text

    def test_save_intelligently_workspace_shows_feedback(self, main_window):
        """Verifica feedback ao salvar workspace via _save_intelligently"""
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(200)

        main_window._original_file_path = None
        main_window._original_file_type = "workspace"
        main_window._save_intelligently()
        QApplication.processEvents()

        action_text = main_window.main_statusbar.action_label.text()
        assert "Workspace salvo" in action_text

    def test_open_file_shows_path_in_statusbar(self, main_window, temp_sql_file):
        """Verifica que abrir arquivo exibe caminho na statusbar"""
        main_window._open_code_file(temp_sql_file)
        QApplication.processEvents()
        QTest.qWait(200)

        file_text = main_window.main_statusbar.file_label.text()
        assert temp_sql_file in file_text


class TestWorkspaceManager:
    """Testes para WorkspaceManager"""

    def test_workspace_manager_current_file_path(self, temp_dir):
        """Verifica que current_file_path e atualizado ao salvar"""
        wm = WorkspaceManager(str(temp_dir / "workspace.json"))
        target_path = str(temp_dir / "test.dpw")

        wm.save_workspace(
            tabs=[{"code": "", "connection": None, "title": "Script 1"}],
            active_tab=0,
            file_path=target_path,
        )

        assert wm.current_file_path == Path(target_path)


class TestTabCloseCleanup:
    """Testes para limpeza de estado ao fechar aba"""

    def test_close_tab_clears_file_path(self, main_window, temp_sql_file):
        """Verifica que fechar aba com arquivo limpa _original_file_path"""
        main_window._open_code_file(temp_sql_file)
        QApplication.processEvents()
        QTest.qWait(200)

        assert main_window._original_file_path == temp_sql_file

        # Fechar a aba
        current_index = main_window.session_tabs.currentIndex()
        main_window._close_session_tab(current_index)
        QApplication.processEvents()
        QTest.qWait(200)

        assert main_window._original_file_path is None
        assert main_window._original_file_type is None

    def test_new_session_has_no_file_path(self, main_window):
        """Verifica que nova sessao inicia sem vinculo de arquivo"""
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(200)

        widget = main_window._get_current_session_widget()
        assert widget is not None
        assert widget.file_path is None
        assert widget._original_file_type is None

    def test_new_session_after_file_open_has_no_file(self, main_window, temp_sql_file):
        """Verifica que nova sessao apos abrir arquivo nao herda o arquivo"""
        main_window._open_code_file(temp_sql_file)
        QApplication.processEvents()
        QTest.qWait(200)

        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(200)

        widget = main_window._get_current_session_widget()
        assert widget is not None
        assert widget.file_path is None


class TestHashModificationTracking:
    """Testes para rastreamento de modificacoes por hash"""

    def test_widget_has_content_hash(self, main_window):
        """Verifica que widget criado tem _content_hash"""
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(200)

        widget = main_window._get_current_session_widget()
        assert hasattr(widget, "_content_hash")
        assert widget._content_hash != ""

    def test_opened_file_starts_unmodified(self, main_window, temp_sql_file):
        """Verifica que arquivo aberto inicia sem marcador de modificacao"""
        main_window._open_code_file(temp_sql_file)
        QApplication.processEvents()
        QTest.qWait(200)

        widget = main_window._get_current_session_widget()
        assert widget._is_modified is False

        index = main_window.session_tabs.indexOf(widget)
        tab_text = main_window.session_tabs.tabText(index)
        assert not tab_text.endswith(" *"), f"Tab '{tab_text}' nao deveria ter asterisco"

    def test_modification_adds_asterisk(self, main_window, temp_sql_file):
        """Verifica que editar conteudo adiciona asterisco na aba"""
        main_window._open_code_file(temp_sql_file)
        QApplication.processEvents()
        QTest.qWait(200)

        widget = main_window._get_current_session_widget()
        blocks = widget.editor.get_blocks()
        assert len(blocks) > 0

        # Modificar conteudo
        blocks[0].set_code("SELECT 999 FROM modified_table;")
        QApplication.processEvents()
        QTest.qWait(100)

        # Disparar _on_editor_modified manualmente (signal pode nao ter sido emitido no test)
        main_window._on_editor_modified(widget)
        QApplication.processEvents()

        assert widget._is_modified is True
        index = main_window.session_tabs.indexOf(widget)
        tab_text = main_window.session_tabs.tabText(index)
        assert tab_text.endswith(" *"), f"Tab '{tab_text}' deveria ter asterisco"

    def test_reverting_content_removes_asterisk(self, main_window, temp_sql_file):
        """Verifica que reverter conteudo para original remove asterisco"""
        main_window._open_code_file(temp_sql_file)
        QApplication.processEvents()
        QTest.qWait(200)

        widget = main_window._get_current_session_widget()
        blocks = widget.editor.get_blocks()
        original_code = blocks[0].get_code()

        # Modificar conteudo
        blocks[0].set_code("SELECT 999 FROM modified;")
        main_window._on_editor_modified(widget)
        QApplication.processEvents()
        assert widget._is_modified is True

        # Reverter para conteudo original
        blocks[0].set_code(original_code)
        main_window._on_editor_modified(widget)
        QApplication.processEvents()

        assert widget._is_modified is False
        index = main_window.session_tabs.indexOf(widget)
        tab_text = main_window.session_tabs.tabText(index)
        assert not tab_text.endswith(" *"), f"Tab '{tab_text}' nao deveria ter asterisco apos reverter"

    def test_save_updates_hash(self, main_window, temp_sql_file):
        """Verifica que salvar atualiza o hash e remove asterisco"""
        main_window._open_code_file(temp_sql_file)
        QApplication.processEvents()
        QTest.qWait(200)

        widget = main_window._get_current_session_widget()
        blocks = widget.editor.get_blocks()

        # Modificar conteudo
        blocks[0].set_code("SELECT 999 FROM modified;")
        main_window._on_editor_modified(widget)
        QApplication.processEvents()
        assert widget._is_modified is True

        # Salvar
        main_window._save_single_file(temp_sql_file, "sql")
        QApplication.processEvents()

        # Hash deve ter sido atualizado, nao esta mais modificado
        assert widget._is_modified is False
        index = main_window.session_tabs.indexOf(widget)
        tab_text = main_window.session_tabs.tabText(index)
        assert not tab_text.endswith(" *"), f"Tab '{tab_text}' nao deveria ter asterisco apos salvar"

    def test_compute_widget_content_hash_deterministic(self, main_window):
        """Verifica que o hash e determinisico para o mesmo conteudo"""
        main_window._new_session()
        QApplication.processEvents()
        QTest.qWait(200)

        widget = main_window._get_current_session_widget()
        hash1 = main_window._compute_widget_content_hash(widget)
        hash2 = main_window._compute_widget_content_hash(widget)
        assert hash1 == hash2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
