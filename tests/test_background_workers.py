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
