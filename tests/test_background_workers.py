"""
Testes para workers de background - DatabaseSwitchWorker e BlockConnectionWorker

Verifica que operacoes de carga sao processadas em threads separadas,
evitando bloqueios na interface.
"""

import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import QThread

from src.workers import (
    BaseWorker,
    DatabaseSwitchWorker,
    BlockConnectionWorker,
    FileReadWorker,
    FileExportWorker,
    execute_worker,
)


class TestDatabaseSwitchWorker:
    """Testes para DatabaseSwitchWorker"""

    def test_worker_inherits_base(self):
        """DatabaseSwitchWorker deve herdar de BaseWorker"""
        connector = MagicMock()
        worker = DatabaseSwitchWorker(connector, "new_db")
        assert isinstance(worker, BaseWorker)

    def test_worker_has_switch_success_signal(self):
        """Worker deve ter sinal switch_success"""
        connector = MagicMock()
        worker = DatabaseSwitchWorker(connector, "new_db")
        assert hasattr(worker, "switch_success")

    def test_worker_stores_params(self):
        """Worker deve armazenar connector e database_name"""
        connector = MagicMock()
        worker = DatabaseSwitchWorker(connector, "new_db")
        assert worker.connector is connector
        assert worker.database_name == "new_db"

    def test_run_success_emits_signals(self, qtbot):
        """Worker deve emitir switch_success e finished ao trocar banco"""
        connector = MagicMock()
        connector.change_database.return_value = True
        worker = DatabaseSwitchWorker(connector, "target_db")

        signals_received = {"started": False, "success": None, "finished": False}

        worker.started.connect(lambda: signals_received.__setitem__("started", True))
        worker.switch_success.connect(lambda db: signals_received.__setitem__("success", db))
        worker.finished.connect(lambda: signals_received.__setitem__("finished", True))

        worker.run()

        assert signals_received["started"] is True
        assert signals_received["success"] == "target_db"
        assert signals_received["finished"] is True
        connector.change_database.assert_called_once_with("target_db")

    def test_run_error_emits_error_signal(self, qtbot):
        """Worker deve emitir error se change_database falhar"""
        connector = MagicMock()
        connector.change_database.side_effect = Exception("DB offline")
        worker = DatabaseSwitchWorker(connector, "bad_db")

        error_received = {"msg": None}
        worker.error.connect(lambda msg: error_received.__setitem__("msg", msg))

        worker.run()

        assert error_received["msg"] is not None
        assert "DB offline" in error_received["msg"]

    def test_run_always_emits_finished(self, qtbot):
        """Worker deve sempre emitir finished, mesmo em caso de erro"""
        connector = MagicMock()
        connector.change_database.side_effect = RuntimeError("fail")
        worker = DatabaseSwitchWorker(connector, "db")

        finished = {"called": False}
        worker.finished.connect(lambda: finished.__setitem__("called", True))

        worker.run()

        assert finished["called"] is True

    def test_worker_runs_in_thread(self, qtbot):
        """Worker deve poder executar em QThread via execute_worker"""
        connector = MagicMock()
        connector.change_database.return_value = True
        worker = DatabaseSwitchWorker(connector, "test_db")

        result = {"db": None}
        worker.switch_success.connect(lambda db: result.__setitem__("db", db))

        thread = execute_worker(worker)
        assert isinstance(thread, QThread)

        qtbot.waitUntil(lambda: result["db"] is not None, timeout=3000)
        assert result["db"] == "test_db"


class TestBlockConnectionWorker:
    """Testes para BlockConnectionWorker"""

    def test_worker_inherits_base(self):
        """BlockConnectionWorker deve herdar de BaseWorker"""
        worker = BlockConnectionWorker(
            db_type="sqlserver", host="localhost", port=1433, database="testdb"
        )
        assert isinstance(worker, BaseWorker)

    def test_worker_has_connection_ready_signal(self):
        """Worker deve ter sinal connection_ready"""
        worker = BlockConnectionWorker(
            db_type="sqlserver", host="localhost", port=1433, database="testdb"
        )
        assert hasattr(worker, "connection_ready")

    def test_worker_stores_params(self):
        """Worker deve armazenar parametros de conexao"""
        worker = BlockConnectionWorker(
            db_type="postgresql",
            host="db.example.com",
            port=5432,
            database="mydb",
            username="user",
            password="pass",
            use_windows_auth=False,
            trust_server_certificate=True,
        )
        assert worker.db_type == "postgresql"
        assert worker.host == "db.example.com"
        assert worker.port == 5432
        assert worker.database == "mydb"
        assert worker.username == "user"
        assert worker.password == "pass"
        assert worker.use_windows_auth is False
        assert worker.trust_server_certificate is True
        assert worker.sqlserver_auth_mode == ""

    @patch("src.database.database_connector.DatabaseConnector")
    def test_run_success_emits_connection_ready(self, mock_connector_cls, qtbot):
        """Worker deve emitir connection_ready ao conectar com sucesso"""
        mock_connector = MagicMock()
        mock_connector.is_connected.return_value = True
        mock_connector_cls.return_value = mock_connector

        worker = BlockConnectionWorker(
            db_type="sqlserver", host="localhost", port=1433, database="testdb"
        )

        signals = {"started": False, "ready": None, "finished": False}
        worker.started.connect(lambda: signals.__setitem__("started", True))
        worker.connection_ready.connect(lambda c: signals.__setitem__("ready", c))
        worker.finished.connect(lambda: signals.__setitem__("finished", True))

        worker.run()

        assert signals["started"] is True
        assert signals["ready"] is mock_connector
        assert signals["finished"] is True
        mock_connector.connect.assert_called_once()

    @patch("src.database.database_connector.DatabaseConnector")
    def test_run_error_emits_error_signal(self, mock_connector_cls, qtbot):
        """Worker deve emitir error se connect falhar"""
        mock_connector = MagicMock()
        mock_connector.connect.side_effect = Exception("Connection refused")
        mock_connector_cls.return_value = mock_connector

        worker = BlockConnectionWorker(
            db_type="sqlserver", host="bad_host", port=1433, database="testdb"
        )

        error_received = {"msg": None}
        worker.error.connect(lambda msg: error_received.__setitem__("msg", msg))

        worker.run()

        assert error_received["msg"] is not None
        assert "Erro de conexão" in error_received["msg"] or "Connection refused" in error_received["msg"]

    @patch("src.database.database_connector.DatabaseConnector")
    def test_run_not_connected_emits_error(self, mock_connector_cls, qtbot):
        """Worker deve emitir error se connector nao ficar conectado"""
        mock_connector = MagicMock()
        mock_connector.is_connected.return_value = False
        mock_connector_cls.return_value = mock_connector

        worker = BlockConnectionWorker(
            db_type="sqlserver", host="localhost", port=1433, database="testdb"
        )

        error_received = {"msg": None}
        worker.error.connect(lambda msg: error_received.__setitem__("msg", msg))

        worker.run()

        assert error_received["msg"] is not None
        assert "Failed to connect" in error_received["msg"]

    @patch("src.database.database_connector.DatabaseConnector")
    def test_run_always_emits_finished(self, mock_connector_cls, qtbot):
        """Worker deve sempre emitir finished, mesmo em caso de erro"""
        mock_connector = MagicMock()
        mock_connector.connect.side_effect = RuntimeError("crash")
        mock_connector_cls.return_value = mock_connector

        worker = BlockConnectionWorker(
            db_type="sqlserver", host="localhost", port=1433, database="testdb"
        )

        finished = {"called": False}
        worker.finished.connect(lambda: finished.__setitem__("called", True))

        worker.run()

        assert finished["called"] is True

    @patch("src.database.database_connector.DatabaseConnector")
    def test_worker_passes_all_params_to_connect(self, mock_connector_cls, qtbot):
        """Worker deve passar todos os parametros ao connector.connect()"""
        mock_connector = MagicMock()
        mock_connector.is_connected.return_value = True
        mock_connector_cls.return_value = mock_connector

        worker = BlockConnectionWorker(
            db_type="postgresql",
            host="db.example.com",
            port=5432,
            database="mydb",
            username="admin",
            password="secret",
            use_windows_auth=True,
            trust_server_certificate=True,
        )

        worker.run()

        mock_connector.connect.assert_called_once_with(
            db_type="postgresql",
            host="db.example.com",
            port=5432,
            database="mydb",
            username="admin",
            password="secret",
            use_windows_auth=True,
            trust_server_certificate=True,
        )

    @patch("src.database.database_connector.DatabaseConnector")
    def test_worker_passes_sqlserver_auth_mode_to_connect(self, mock_connector_cls, qtbot):
        """Worker deve propagar o auth mode do SQL Server para MFA."""
        mock_connector = MagicMock()
        mock_connector.is_connected.return_value = True
        mock_connector_cls.return_value = mock_connector

        worker = BlockConnectionWorker(
            db_type="sqlserver",
            host="server.database.windows.net",
            port=1433,
            database="db",
            username="user@tenant.com",
            sqlserver_auth_mode="entra_mfa",
        )

        worker.run()

        mock_connector.connect.assert_called_once_with(
            db_type="sqlserver",
            host="server.database.windows.net",
            port=1433,
            database="db",
            username="user@tenant.com",
            password="",
            use_windows_auth=False,
            sqlserver_auth_mode="entra_mfa",
            trust_server_certificate=False,
        )

    @patch("src.database.database_connector.DatabaseConnector")
    def test_worker_applies_databricks_database_context_after_connect(self, mock_connector_cls, qtbot):
        """Databricks block worker deve aplicar catalog.schema apos conectar."""
        mock_connector = MagicMock()
        mock_connector.is_connected.return_value = True
        mock_connector_cls.return_value = mock_connector

        worker = BlockConnectionWorker(
            db_type="databricks",
            host="workspace.cloud.databricks.com",
            port=443,
            database="main",
            username="",
            password="token",
            http_path="/sql/1.0/warehouses/abc",
            database_context="mag_bronze.esim",
        )

        worker.run()

        mock_connector.connect.assert_called_once_with(
            db_type="databricks",
            host="workspace.cloud.databricks.com",
            port=443,
            database="main",
            username="",
            password="token",
            use_windows_auth=False,
            trust_server_certificate=False,
            http_path="/sql/1.0/warehouses/abc",
        )
        mock_connector.change_database.assert_called_once_with("mag_bronze.esim")


class TestFileReadWorker:
    """Testes para FileReadWorker"""

    def test_worker_inherits_base(self):
        """FileReadWorker deve herdar de BaseWorker"""
        worker = FileReadWorker("/path/to/file.txt")
        assert isinstance(worker, BaseWorker)

    def test_worker_has_file_read_signal(self):
        """Worker deve ter sinal file_read"""
        worker = FileReadWorker("/path/to/file.txt")
        assert hasattr(worker, "file_read")

    def test_worker_stores_path(self):
        """Worker deve armazenar o caminho do arquivo"""
        worker = FileReadWorker("/path/to/test.csv")
        assert worker.file_path == "/path/to/test.csv"

    def test_run_success_emits_file_read(self, qtbot, tmp_path):
        """Worker deve emitir file_read ao ler arquivo com sucesso"""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!", encoding="utf-8")

        worker = FileReadWorker(str(test_file))

        signals = {"started": False, "content": None, "path": None, "finished": False}
        worker.started.connect(lambda: signals.__setitem__("started", True))
        worker.file_read.connect(lambda c, p: (signals.__setitem__("content", c), signals.__setitem__("path", p)))
        worker.finished.connect(lambda: signals.__setitem__("finished", True))

        worker.run()

        assert signals["started"] is True
        assert signals["content"] == "Hello, World!"
        assert signals["path"] == str(test_file)
        assert signals["finished"] is True

    def test_run_error_emits_error_signal(self, qtbot):
        """Worker deve emitir error se arquivo nao existir"""
        worker = FileReadWorker("/nonexistent/path/file.txt")

        error_received = {"msg": None}
        worker.error.connect(lambda msg: error_received.__setitem__("msg", msg))

        worker.run()

        assert error_received["msg"] is not None

    def test_run_always_emits_finished(self, qtbot):
        """Worker deve sempre emitir finished, mesmo em caso de erro"""
        worker = FileReadWorker("/nonexistent/file.txt")

        finished = {"called": False}
        worker.finished.connect(lambda: finished.__setitem__("called", True))

        worker.run()

        assert finished["called"] is True

    def test_read_file_with_utf8(self, qtbot, tmp_path):
        """Worker deve ler arquivo UTF-8 corretamente"""
        test_file = tmp_path / "unicode.txt"
        test_file.write_text("Ola, mundo! Acao, coracao", encoding="utf-8")

        worker = FileReadWorker(str(test_file))
        result = {"content": None}
        worker.file_read.connect(lambda c, p: result.__setitem__("content", c))
        worker.run()

        assert "Ola" in result["content"]
        assert "coracao" in result["content"]

    def test_read_file_with_latin1_fallback(self, qtbot, tmp_path):
        """Worker deve fazer fallback para latin-1 se UTF-8 falhar"""
        test_file = tmp_path / "latin1.txt"
        test_file.write_bytes("Acao e coracao".encode("latin-1"))

        worker = FileReadWorker(str(test_file))
        result = {"content": None}
        worker.file_read.connect(lambda c, p: result.__setitem__("content", c))
        worker.run()

        # Worker conseguiu ler (pode ter caracteres diferentes, mas nao deu erro)
        assert result["content"] is not None


class TestFileExportWorker:
    """Testes para FileExportWorker"""

    def test_worker_inherits_base(self):
        """FileExportWorker deve herdar de BaseWorker"""
        import pandas as pd
        df = pd.DataFrame({"a": [1, 2, 3]})
        worker = FileExportWorker(df, "/path/to/file.csv", "csv")
        assert isinstance(worker, BaseWorker)

    def test_worker_has_export_complete_signal(self):
        """Worker deve ter sinal export_complete"""
        import pandas as pd
        df = pd.DataFrame({"a": [1, 2, 3]})
        worker = FileExportWorker(df, "/path/to/file.csv", "csv")
        assert hasattr(worker, "export_complete")

    def test_worker_stores_params(self):
        """Worker deve armazenar parametros de exportacao"""
        import pandas as pd
        df = pd.DataFrame({"x": [1, 2]})
        worker = FileExportWorker(df, "/path/to/data.csv", "csv", sep=";", encoding="latin-1")
        assert worker.file_path == "/path/to/data.csv"
        assert worker.export_format == "csv"
        assert worker.options["sep"] == ";"
        assert worker.options["encoding"] == "latin-1"

    def test_export_csv_success(self, qtbot, tmp_path):
        """Worker deve exportar CSV com sucesso"""
        import pandas as pd
        df = pd.DataFrame({"col1": [1, 2, 3], "col2": ["a", "b", "c"]})
        output_file = tmp_path / "output.csv"

        worker = FileExportWorker(df, str(output_file), "csv", sep=",")

        signals = {"started": False, "path": None, "finished": False}
        worker.started.connect(lambda: signals.__setitem__("started", True))
        worker.export_complete.connect(lambda p: signals.__setitem__("path", p))
        worker.finished.connect(lambda: signals.__setitem__("finished", True))

        worker.run()

        assert signals["started"] is True
        assert signals["path"] == str(output_file)
        assert signals["finished"] is True
        assert output_file.exists()

        # Verify content
        content = output_file.read_text()
        assert "col1" in content
        assert "1" in content

    def test_export_json_success(self, qtbot, tmp_path):
        """Worker deve exportar JSON com sucesso"""
        import pandas as pd
        df = pd.DataFrame({"name": ["Alice", "Bob"], "age": [30, 25]})
        output_file = tmp_path / "output.json"

        worker = FileExportWorker(df, str(output_file), "json")

        result = {"path": None}
        worker.export_complete.connect(lambda p: result.__setitem__("path", p))
        worker.run()

        assert output_file.exists()
        content = output_file.read_text()
        assert "Alice" in content
        assert "Bob" in content

    def test_export_excel_success(self, qtbot, tmp_path):
        """Worker deve exportar Excel com sucesso"""
        import pandas as pd
        df = pd.DataFrame({"value": [100, 200, 300]})
        output_file = tmp_path / "output.xlsx"

        worker = FileExportWorker(df, str(output_file), "excel")

        result = {"path": None}
        worker.export_complete.connect(lambda p: result.__setitem__("path", p))
        worker.run()

        assert output_file.exists()
        assert output_file.stat().st_size > 0

    def test_export_error_emits_error_signal(self, qtbot):
        """Worker deve emitir error se exportacao falhar"""
        import pandas as pd
        df = pd.DataFrame({"a": [1]})
        
        # Invalid path that should fail
        worker = FileExportWorker(df, "/nonexistent/path/file.csv", "csv")

        error_received = {"msg": None}
        worker.error.connect(lambda msg: error_received.__setitem__("msg", msg))
        worker.run()

        assert error_received["msg"] is not None

    def test_export_always_emits_finished(self, qtbot):
        """Worker deve sempre emitir finished, mesmo em caso de erro"""
        import pandas as pd
        df = pd.DataFrame({"a": [1]})
        worker = FileExportWorker(df, "/invalid/path.csv", "csv")

        finished = {"called": False}
        worker.finished.connect(lambda: finished.__setitem__("called", True))
        worker.run()

        assert finished["called"] is True

    def test_export_invalid_format_emits_error(self, qtbot, tmp_path):
        """Worker deve emitir error para formato invalido"""
        import pandas as pd
        df = pd.DataFrame({"a": [1]})
        output_file = tmp_path / "output.xyz"

        worker = FileExportWorker(df, str(output_file), "xyz_invalid_format")

        error_received = {"msg": None}
        worker.error.connect(lambda msg: error_received.__setitem__("msg", msg))
        worker.run()

        assert error_received["msg"] is not None
        assert "Unsupported" in error_received["msg"]
