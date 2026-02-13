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


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
