"""
Testes para a funcionalidade de exportar análise como script Python
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, mock_open
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog
import tempfile
import os


@pytest.fixture(autouse=True)
def mock_all_dialogs():
    """Mock automático de TODOS os diálogos do QMessageBox para evitar interação manual"""
    with (
        patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok),
        patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok),
        patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Ok),
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
        patch.object(QMessageBox, "about", return_value=None),
    ):
        yield


@pytest.fixture
def main_window(qapp, qtbot, tmp_path):
    """Cria MainWindow para testes"""
    from src.ui.main_window import MainWindow

    with (
        patch("src.ui.main_window.ConnectionManager") as MockConnManager,
        patch("src.ui.main_window._main.ConnectionManager") as MockMainConnManager,
        patch("src.core.session_manager.Path.home", return_value=tmp_path),
    ):
        mock_conn_manager = MockConnManager.return_value
        MockMainConnManager.return_value = mock_conn_manager
        mock_conn_manager.get_saved_connections.return_value = ["Test Connection"]
        mock_conn_manager.get_connection_config.return_value = {
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "database": "test_db",
            "username": "test_user",
            "use_windows_auth": False,
        }
        mock_conn_manager.get_connections_by_group.return_value = {
            "Test Connection": {"db_type": "mysql", "group": "Desenvolvimento"}
        }
        mock_conn_manager.get_groups.return_value = {"Desenvolvimento": {"color": "#007acc"}}
        mock_conn_manager.active_connection = None
        mock_conn_manager.get_active_connection.return_value = None
        mock_conn_manager.get_connection.return_value = None
        mock_conn_manager.mark_connection_used = Mock()
        mock_conn_manager.create_connection = Mock()

        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)

        if not window._get_current_session_widget():
            window._new_session()
            qtbot.wait(100)

        yield window

        window.close()


class TestExportScriptBasic:
    """Testes básicos da funcionalidade de exportar script"""

    def test_export_menu_item_exists(self, main_window):
        """Verifica se o item de menu 'Exportar como Script...' existe"""
        menubar = main_window.menuBar()
        file_menu = None
        
        for action in menubar.actions():
            if "File" in action.text():
                file_menu = action.menu()
                break
        
        assert file_menu is not None, "Menu File not found"
        
        export_action = None
        for action in file_menu.actions():
            if "Export as Script" in action.text():
                export_action = action
                break
        
        assert export_action is not None, "Item 'Export as Script...' not found in menu"

    def test_export_method_exists(self, main_window):
        """Verifica se o método _export_as_script existe"""
        assert hasattr(main_window, "_export_as_script"), "Método _export_as_script não existe"
        assert callable(main_window._export_as_script), "Método _export_as_script não é chamável"

    def test_export_without_session_shows_warning(self, main_window, qtbot):
        """Exportar sem sessão ativa deve mostrar aviso"""
        # Simular situação sem sessão
        original_method = main_window._get_current_session_widget
        main_window._get_current_session_widget = Mock(return_value=None)
        
        with patch("src.ui.main_window._file_io.show_warning") as mock_warning:
            main_window._export_as_script()
            mock_warning.assert_called_once()
            assert "No active session" in str(mock_warning.call_args)

        main_window._get_current_session_widget = original_method

    def test_export_without_blocks_shows_warning(self, main_window, qtbot):
        """Exportar sem blocos deve mostrar aviso"""
        session_widget = main_window._get_current_session_widget()
        
        # Mock get_blocks para retornar lista vazia (clear_blocks sempre deixa 1 bloco)
        with (
            patch.object(session_widget.editor, "get_blocks", return_value=[]),
            patch("src.ui.main_window._file_io.show_warning") as mock_warning,
            patch.object(QFileDialog, "getSaveFileName", return_value=("", "")),
        ):
            main_window._export_as_script()
            mock_warning.assert_called_once()
            assert "no code blocks" in str(mock_warning.call_args).lower()

    def test_export_dialog_cancelled_does_nothing(self, main_window, qtbot):
        """Cancelar diálogo de salvar não deve fazer nada"""
        session_widget = main_window._get_current_session_widget()
        
        # Adicionar um bloco
        session_widget.editor.add_block("sql")
        session_widget.editor.get_blocks()[0].set_code("SELECT 1")
        
        # Simular cancelamento do diálogo
        with patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
            # Não deve gerar exceção
            main_window._export_as_script()


class TestExportScriptGeneration:
    """Testes de geração do conteúdo do script exportado"""

    def test_export_single_sql_block(self, main_window, qtbot, tmp_path):
        """Exportar bloco SQL único deve gerar script correto"""
        session_widget = main_window._get_current_session_widget()
        
        # Adicionar bloco SQL
        session_widget.editor.add_block("sql")
        session_widget.editor.get_blocks()[0].set_code("SELECT * FROM users")
        
        output_file = tmp_path / "test_export.py"
        
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output_file), "")):
            main_window._export_as_script()
        
        # Verificar que arquivo foi criado
        assert output_file.exists(), "Arquivo de exportação não foi criado"
        
        # Verificar conteúdo
        content = output_file.read_text(encoding='utf-8')
        
        # Deve ter imports necessários
        assert "import pandas as pd" in content
        assert "from sqlalchemy import create_engine" in content
        
        # Deve ter a query SQL
        assert "SELECT * FROM users" in content
        assert "pd.read_sql" in content
        
        # Deve ter comentários
        assert "Python Script Exported from DataPyn" in content
        assert "Block 1: SQL" in content

    def test_export_single_python_block(self, main_window, qtbot, tmp_path):
        """Exportar bloco Python único deve gerar script correto"""
        session_widget = main_window._get_current_session_widget()
        
        # Adicionar bloco Python
        session_widget.editor.add_block("python")
        python_code = "x = 1 + 1\nprint(x)"
        session_widget.editor.get_blocks()[-1].set_code(python_code)
        
        output_file = tmp_path / "test_export_python.py"
        
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output_file), "")):
            main_window._export_as_script()
        
        assert output_file.exists()
        
        content = output_file.read_text(encoding='utf-8')
        
        # Deve ter o codigo Python
        assert python_code in content
        assert "PYTHON" in content.upper()

    def test_export_multiple_blocks_preserves_order(self, main_window, qtbot, tmp_path):
        """Exportar múltiplos blocos deve preservar a ordem"""
        session_widget = main_window._get_current_session_widget()
        
        # Adicionar 3 blocos
        session_widget.editor.add_block("sql")
        session_widget.editor.get_blocks()[0].set_code("SELECT * FROM table1")
        
        session_widget.editor.add_block("python")
        session_widget.editor.get_blocks()[1].set_code("x = 1")
        
        session_widget.editor.add_block("sql")
        session_widget.editor.get_blocks()[2].set_code("SELECT * FROM table2")
        
        output_file = tmp_path / "test_export_multi.py"
        
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output_file), "")):
            main_window._export_as_script()
        
        assert output_file.exists()
        
        content = output_file.read_text(encoding='utf-8')
        
        # Verificar ordem dos blocos
        pos_table1 = content.find("table1")
        pos_x = content.find("x = 1")
        pos_table2 = content.find("table2")
        
        assert pos_table1 < pos_x < pos_table2, "Ordem dos blocos não preservada"

    def test_export_with_block_names(self, main_window, qtbot, tmp_path):
        """Exportar blocos com nomes deve incluir os nomes nos comentários"""
        session_widget = main_window._get_current_session_widget()
        
        # Adicionar bloco com nome
        session_widget.editor.add_block("sql")
        block = session_widget.editor.get_blocks()[0]
        block.set_code("SELECT * FROM users")
        block.set_block_name("get_users")
        
        output_file = tmp_path / "test_export_named.py"
        
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output_file), "")):
            main_window._export_as_script()
        
        assert output_file.exists()
        
        content = output_file.read_text(encoding='utf-8')
        
        # Deve incluir o nome do bloco
        assert "get_users" in content

    def test_export_with_connection_includes_config(self, main_window, qtbot, tmp_path):
        """Exportar com conexão ativa deve incluir configuração de conexão"""
        session_widget = main_window._get_current_session_widget()
        
        # Simular conexão ativa
        session_widget.session.set_connection("Test Connection", Mock())
        
        # Adicionar bloco SQL
        session_widget.editor.add_block("sql")
        session_widget.editor.get_blocks()[0].set_code("SELECT 1")
        
        output_file = tmp_path / "test_export_conn.py"
        
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output_file), "")):
            main_window._export_as_script()
        
        assert output_file.exists()
        
        content = output_file.read_text(encoding='utf-8')
        
        # Deve incluir configuração de conexão
        assert "DB_HOST" in content
        assert "localhost" in content
        assert "test_db" in content
        assert "test_user" in content
        assert "create_engine" in content

    def test_export_skips_empty_blocks(self, main_window, qtbot, tmp_path):
        """Exportar deve ignorar blocos vazios"""
        session_widget = main_window._get_current_session_widget()
        
        # Adicionar blocos com e sem código
        session_widget.editor.add_block("sql")
        session_widget.editor.get_blocks()[0].set_code("SELECT 1")
        
        session_widget.editor.add_block("python")
        session_widget.editor.get_blocks()[1].set_code("")  # Vazio
        
        session_widget.editor.add_block("sql")
        session_widget.editor.get_blocks()[2].set_code("SELECT 2")
        
        output_file = tmp_path / "test_export_skip.py"
        
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output_file), "")):
            main_window._export_as_script()
        
        assert output_file.exists()
        
        content = output_file.read_text(encoding='utf-8')
        
        # Deve ter apenas 2 blocos (SELECT 1 e SELECT 2)
        assert content.count("Block") >= 2
        assert "SELECT 1" in content
        assert "SELECT 2" in content


class TestExportScriptDatabaseTypes:
    """Testes de exportação com diferentes tipos de banco de dados"""

    def test_export_mysql_connection_string(self, main_window, qtbot, tmp_path):
        """Exportar com MySQL deve gerar connection string correta"""
        session_widget = main_window._get_current_session_widget()
        session_widget.session.set_connection("Test Connection", Mock())
        
        session_widget.editor.add_block("sql")
        session_widget.editor.get_blocks()[0].set_code("SELECT 1")
        
        output_file = tmp_path / "test_mysql.py"
        
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output_file), "")):
            main_window._export_as_script()
        
        content = output_file.read_text(encoding='utf-8')
        assert "mysql+pymysql" in content

    def test_export_postgresql_connection_string(self, main_window, qtbot, tmp_path):
        """Exportar com PostgreSQL deve gerar connection string correta"""
        session_widget = main_window._get_current_session_widget()
        
        # Mock conexão PostgreSQL
        with patch.object(
            main_window.connection_manager,
            "get_connection_config",
            return_value={
                "db_type": "postgresql",
                "host": "localhost",
                "port": 5432,
                "database": "test_db",
                "username": "postgres",
            }
        ):
            session_widget.session.set_connection("Postgres Connection", Mock())
            
            session_widget.editor.add_block("sql")
            session_widget.editor.get_blocks()[0].set_code("SELECT 1")
            
            output_file = tmp_path / "test_postgres.py"
            
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output_file), "")):
                main_window._export_as_script()
            
            content = output_file.read_text(encoding='utf-8')
            assert "postgresql" in content

    def test_export_sqlserver_connection_string(self, main_window, qtbot, tmp_path):
        """Exportar com SQL Server deve gerar connection string correta"""
        session_widget = main_window._get_current_session_widget()
        
        # Mock conexão SQL Server
        with patch.object(
            main_window.connection_manager,
            "get_connection_config",
            return_value={
                "db_type": "sqlserver",
                "host": "localhost",
                "port": 1433,
                "database": "test_db",
                "username": "sa",
            }
        ):
            session_widget.session.set_connection("SQL Server Connection", Mock())
            
            session_widget.editor.add_block("sql")
            session_widget.editor.get_blocks()[0].set_code("SELECT 1")
            
            output_file = tmp_path / "test_sqlserver.py"
            
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output_file), "")):
                main_window._export_as_script()
            
            content = output_file.read_text(encoding='utf-8')
            assert "mssql+pyodbc" in content or "sqlserver" in content.lower()


class TestExportScriptEdgeCases:
    """Testes de casos extremos e edge cases"""

    def test_export_with_special_characters(self, main_window, qtbot, tmp_path):
        """Exportar com caracteres especiais não deve falhar"""
        session_widget = main_window._get_current_session_widget()
        
        session_widget.editor.add_block("sql")
        session_widget.editor.get_blocks()[0].set_code("SELECT 'São Paulo', 'Ação' FROM table")
        
        output_file = tmp_path / "test_special.py"
        
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output_file), "")):
            main_window._export_as_script()
        
        assert output_file.exists()
        content = output_file.read_text(encoding='utf-8')
        assert "São Paulo" in content

    def test_export_adds_py_extension_if_missing(self, main_window, qtbot, tmp_path):
        """Exportar deve adicionar extensão .py se não fornecida"""
        session_widget = main_window._get_current_session_widget()
        
        session_widget.editor.add_block("python")
        session_widget.editor.get_blocks()[0].set_code("x = 1")
        
        # Arquivo sem extensão
        output_file_no_ext = tmp_path / "test_export"
        output_file_with_ext = tmp_path / "test_export.py"
        
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output_file_no_ext), "")):
            main_window._export_as_script()
        
        # Deve criar com .py
        assert output_file_with_ext.exists()

    def test_export_handles_multiline_sql(self, main_window, qtbot, tmp_path):
        """Exportar deve lidar com SQL multilinha"""
        session_widget = main_window._get_current_session_widget()
        
        session_widget.editor.add_block("sql")
        multiline_sql = """SELECT 
    id,
    name,
    email
FROM users
WHERE active = 1"""
        session_widget.editor.get_blocks()[0].set_code(multiline_sql)
        
        output_file = tmp_path / "test_multiline.py"
        
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output_file), "")):
            main_window._export_as_script()
        
        assert output_file.exists()
        content = output_file.read_text(encoding='utf-8')
        assert "SELECT" in content
        assert "WHERE active = 1" in content

    def test_export_with_error_handling(self, main_window, qtbot):
        """Exportar deve tratar erros de escrita"""
        session_widget = main_window._get_current_session_widget()
        
        session_widget.editor.add_block("python")
        session_widget.editor.get_blocks()[0].set_code("x = 1")
        
        # Simular erro de escrita
        with (
            patch.object(QFileDialog, "getSaveFileName", return_value=("/invalid/path/test.py", "")),
            patch("src.ui.main_window._file_io.show_danger") as mock_error,
        ):
            main_window._export_as_script()
            # Deve mostrar mensagem de erro
            mock_error.assert_called_once()

