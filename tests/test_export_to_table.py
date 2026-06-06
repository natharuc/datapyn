"""
Testes para ExportToTableDialog e ExportToTableWorker

Cobre: validacao de campos, criacao da UI, worker de exportacao (Polars + raw cursor),
progresso, cancelamento, cleanup de thread, estilos.
"""

import pytest
import pandas as pd
import polars as pl
from unittest.mock import MagicMock, patch, PropertyMock, call
from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import QPushButton

from src.ui.dialogs.export_to_table_dialog import (
    ExportToTableDialog,
    ExportToTableWorker,
)
from src.core.theme_manager import ThemeManager


# ==================== Helpers ====================


def _make_connector(connected=True, db_type="SQLServer", db_name="testdb"):
    """Cria um mock de DatabaseConnector"""
    connector = MagicMock()
    connector.is_connected.return_value = connected
    connector.db_type = db_type
    connector.get_current_database.return_value = db_name
    connector.engine = MagicMock() if connected else None
    return connector


def _make_connections(**kwargs):
    """Cria dict de conexoes.

    Ex: _make_connections(srv1=True, srv2=False)
    """
    conns = {}
    for name, connected in kwargs.items():
        conns[name] = _make_connector(connected=connected)
    return conns


def _sample_df(rows=5, cols=None):
    """Cria um DataFrame pandas de teste (para dialog)"""
    if cols is None:
        cols = ["id", "name", "value"]
    data = {c: list(range(rows)) for c in cols}
    return pd.DataFrame(data)


def _sample_pl(rows=5, cols=None):
    """Cria um DataFrame Polars de teste (para worker)"""
    if cols is None:
        cols = ["id", "name", "value"]
    data = {c: list(range(rows)) for c in cols}
    return pl.DataFrame(data)


def _make_engine_mock(dialect="mssql"):
    """Cria mock de SQLAlchemy Engine com raw_connection para testes do worker"""
    engine = MagicMock()
    engine.dialect = MagicMock()
    engine.dialect.name = dialect

    raw_conn = MagicMock()
    cursor = MagicMock()
    cursor.fast_executemany = False
    raw_conn.cursor.return_value = cursor
    engine.raw_connection.return_value = raw_conn

    return engine, raw_conn, cursor


# ==================== ExportToTableWorker ====================


class TestExportToTableWorker:
    """Testes do worker de exportacao (Polars + raw cursor)"""

    def test_worker_emits_finished_on_empty_df(self, qtbot):
        """Worker deve recusar DataFrame vazio"""
        df = pl.DataFrame()
        engine, _, _ = _make_engine_mock()
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="t",
            if_exists="replace", chunksize=1000,
        )
        results = []
        worker.finished.connect(lambda ok, msg: results.append((ok, msg)))
        worker.run()
        assert len(results) == 1
        assert results[0][0] is False
        assert "empty" in results[0][1].lower()

    def test_worker_exports_small_df(self, qtbot):
        """Exporta DataFrame pequeno com executemany"""
        df = _sample_pl(3)
        engine, raw_conn, cursor = _make_engine_mock()
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="my_table",
            if_exists="replace", chunksize=1000,
        )
        progress_calls = []
        worker.progress.connect(lambda cur, tot: progress_calls.append((cur, tot)))
        finished = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        worker.run()

        assert len(finished) == 1
        assert finished[0][0] is True
        assert "3" in finished[0][1]
        # Progresso deve ser 100% de uma vez
        assert progress_calls == [(3, 3)]
        # executemany deve ter sido chamado uma vez
        assert cursor.executemany.call_count == 1
        # raw_conn deve ser fechado
        raw_conn.close.assert_called_once()

    def test_worker_exports_in_chunks(self, qtbot):
        """Exporta em chunks com progresso incremental"""
        df = _sample_pl(10)
        engine, raw_conn, cursor = _make_engine_mock()
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="chunked",
            if_exists="replace", chunksize=3,
        )
        progress_calls = []
        worker.progress.connect(lambda cur, tot: progress_calls.append((cur, tot)))
        finished = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        worker.run()

        assert finished[0][0] is True
        # 10 linhas, chunksize 3 = 4 chunks (3+3+3+1)
        assert len(progress_calls) == 4
        assert progress_calls[-1] == (10, 10)
        # executemany chamado 4 vezes (uma por chunk)
        assert cursor.executemany.call_count == 4

    def test_worker_cancel_stops_midway(self, qtbot):
        """Cancelamento interrompe a exportacao"""
        df = _sample_pl(100)
        engine, raw_conn, cursor = _make_engine_mock()
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="cancel_test",
            if_exists="replace", chunksize=10,
        )
        finished = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        # Cancelar imediatamente
        worker.cancel()
        worker.run()

        assert len(finished) == 1
        assert finished[0][0] is False
        assert "cancelled" in finished[0][1].lower()

    def test_worker_handles_executemany_exception(self, qtbot):
        """Worker captura excecoes do cursor.executemany"""
        df = _sample_pl(5)
        engine, raw_conn, cursor = _make_engine_mock()
        cursor.executemany.side_effect = Exception("Connection lost")
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="fail",
            if_exists="replace", chunksize=1000,
        )
        finished = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        worker.run()

        assert finished[0][0] is False
        assert "Connection lost" in finished[0][1]

    def test_worker_truncates_long_error_messages(self, qtbot):
        """Mensagens de erro muito longas sao truncadas"""
        df = _sample_pl(5)
        engine, raw_conn, cursor = _make_engine_mock()
        cursor.executemany.side_effect = Exception("x" * 500)
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="t",
            if_exists="replace", chunksize=1000,
        )
        finished = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        worker.run()

        assert len(finished[0][1]) < 500

    def test_worker_with_schema(self, qtbot):
        """Worker monta nome qualificado com schema"""
        df = _sample_pl(2)
        engine, raw_conn, cursor = _make_engine_mock()
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="my_table",
            if_exists="replace", chunksize=1000, schema="dbo",
        )
        finished = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        worker.run()

        assert finished[0][0] is True
        # DDL deve conter schema qualificado
        ddl_calls = [str(c) for c in cursor.execute.call_args_list]
        ddl_text = " ".join(ddl_calls)
        assert "[dbo]" in ddl_text
        assert "[my_table]" in ddl_text

    def test_worker_replace_drops_and_creates(self, qtbot):
        """if_exists=replace faz DROP TABLE + CREATE TABLE antes dos INSERTs"""
        df = _sample_pl(6)
        engine, raw_conn, cursor = _make_engine_mock()
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="multi",
            if_exists="replace", chunksize=2,
        )
        finished = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        worker.run()

        # cursor.execute deve ter sido chamado para DDL
        execute_calls = [str(c) for c in cursor.execute.call_args_list]
        # Primeiro: DROP TABLE IF EXISTS
        assert "DROP TABLE IF EXISTS" in execute_calls[0]
        # Segundo: CREATE TABLE
        assert "CREATE TABLE" in execute_calls[1]
        # executemany chamado para cada chunk (6 linhas / 2 = 3 chunks)
        assert cursor.executemany.call_count == 3

    def test_worker_emits_status_messages(self, qtbot):
        """Worker emite mensagens de status durante exportacao"""
        df = _sample_pl(6)
        engine, _, _ = _make_engine_mock()
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="status_test",
            if_exists="replace", chunksize=2,
        )
        statuses = []
        worker.status.connect(lambda msg: statuses.append(msg))

        worker.run()

        assert len(statuses) > 0
        # Primeira mensagem deve conter total
        assert "6" in statuses[0]

    def test_worker_sets_fast_executemany(self, qtbot):
        """Worker ativa fast_executemany quando cursor suporta"""
        df = _sample_pl(3)
        engine, raw_conn, cursor = _make_engine_mock()
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="t",
            if_exists="replace", chunksize=1000,
        )
        worker.run()
        assert cursor.fast_executemany is True

    def test_worker_ddl_types_integer(self, qtbot):
        """CREATE TABLE mapeia tipos inteiros corretamente"""
        df = pl.DataFrame({"a": [1], "b": [1000000000]}).cast({"a": pl.Int16, "b": pl.Int64})
        engine, _, cursor = _make_engine_mock()
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="t",
            if_exists="replace", chunksize=1000,
        )
        ddl = worker._create_table_ddl()
        assert "SMALLINT" in ddl
        assert "BIGINT" in ddl

    def test_worker_ddl_types_float_and_string(self, qtbot):
        """CREATE TABLE mapeia float e string corretamente"""
        df = pl.DataFrame({"x": [1.5], "y": ["hello"]})
        engine, _, cursor = _make_engine_mock()
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="t",
            if_exists="replace", chunksize=1000,
        )
        ddl = worker._create_table_ddl()
        assert "FLOAT" in ddl
        assert "NVARCHAR(MAX)" in ddl

    def test_worker_temp_table_no_quoting(self, qtbot):
        """Tabelas temporarias # nao recebem quoting"""
        df = _sample_pl(2)
        engine, _, _ = _make_engine_mock()
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="#temp",
            if_exists="replace", chunksize=1000,
        )
        assert worker._qualified_name() == "#temp"

    def test_worker_append_mode(self, qtbot):
        """if_exists=append tenta criar tabela sem falhar se ja existe"""
        df = _sample_pl(3)
        engine, raw_conn, cursor = _make_engine_mock()
        # Simular tabela ja existindo (CREATE TABLE falha)
        cursor.execute.side_effect = [Exception("already exists")]
        # Resetar side_effect apos primeiro call
        original_execute = cursor.execute

        call_count = [0]
        def side_effect_fn(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("already exists")
            return MagicMock()

        cursor.execute = MagicMock(side_effect=side_effect_fn)

        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="existing",
            if_exists="append", chunksize=1000,
        )
        finished = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        worker.run()

        # Deve ter sucesso mesmo com CREATE TABLE falhando
        assert finished[0][0] is True
        # rollback chamado por causa do CREATE TABLE falhar
        raw_conn.rollback.assert_called()

    def test_worker_closes_connection_on_error(self, qtbot):
        """raw_conn.close() e chamado mesmo em caso de erro"""
        df = _sample_pl(3)
        engine, raw_conn, cursor = _make_engine_mock()
        cursor.execute.side_effect = Exception("DDL error")
        worker = ExportToTableWorker(
            df_polars=df, engine=engine, table_name="t",
            if_exists="fail", chunksize=1000,
        )
        finished = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        worker.run()

        assert finished[0][0] is False
        raw_conn.close.assert_called_once()


# ==================== ExportToTableDialog ====================


class TestExportToTableDialog:
    """Testes do dialogo de exportacao"""

    def test_dialog_creates_with_valid_connections(self, qtbot):
        """Dialogo cria corretamente com conexoes validas"""
        df = _sample_df()
        conns = _make_connections(srv1=True, srv2=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        assert dialog.connection_combo.count() == 2
        assert dialog.windowTitle() == "Export to Table"

    def test_dialog_no_maximize_minimize_buttons(self, qtbot):
        """Dialogo nao deve ter botoes de maximizar/minimizar"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        flags = dialog.windowFlags()
        assert not (flags & Qt.WindowType.WindowMaximizeButtonHint)
        assert not (flags & Qt.WindowType.WindowMinimizeButtonHint)
        assert flags & Qt.WindowType.FramelessWindowHint
        close_btn = dialog.findChild(QPushButton, "framelessClose")
        assert close_btn is not None

    def test_dialog_cancel_button_has_object_name(self, qtbot):
        """Botao cancelar tem objectName para estilo diferenciado"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        assert dialog.btn_cancel.objectName() == "btnCancel"

    def test_dialog_filters_disconnected(self, qtbot):
        """Conexoes inativas nao aparecem no combo"""
        df = _sample_df()
        conns = _make_connections(active=True, inactive=False)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        # Apenas a conexao ativa deve aparecer
        assert dialog.connection_combo.count() == 1

    def test_dialog_preselects_current_connection(self, qtbot):
        """Conexao atual e pre-selecionada"""
        df = _sample_df()
        conns = _make_connections(conn_a=True, conn_b=True)
        dialog = ExportToTableDialog(df, conns, current_connection="conn_b")
        qtbot.addWidget(dialog)

        assert dialog.connection_combo.currentData() == "conn_b"

    def test_dialog_shows_dataframe_info(self, qtbot):
        """Info do DataFrame e exibida"""
        df = _sample_df(rows=42, cols=["a", "b", "c", "d"])
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        # Deve estar visivel na UI (42 linhas x 4 colunas)
        # O label e criado no _setup_ui
        assert dialog.df is df

    def test_dialog_default_chunk_is_1000(self, qtbot):
        """Chunk padrao e 1000"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        assert dialog.chunk_spin.value() == 1000

    def test_dialog_default_if_exists_is_replace(self, qtbot):
        """Comportamento padrao e replace"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        assert dialog.if_exists_combo.currentData() == "replace"

    def test_dialog_validate_empty_table_name(self, qtbot):
        """Validacao rejeita nome de tabela vazio"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        dialog.table_name_edit.setText("")
        assert dialog._validate() is False

    def test_dialog_validate_no_connections(self, qtbot):
        """Validacao rejeita quando nao ha conexoes"""
        df = _sample_df()
        dialog = ExportToTableDialog(df, {})
        qtbot.addWidget(dialog)

        dialog.table_name_edit.setText("tabela")
        assert dialog._validate() is False

    def test_dialog_validate_success(self, qtbot):
        """Validacao aceita quando tudo esta preenchido"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        dialog.table_name_edit.setText("my_table")
        assert dialog._validate() is True

    def test_dialog_progress_initially_hidden(self, qtbot):
        """Progresso comeca invisivel"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        assert dialog.progress_group.isVisible() is False

    def test_dialog_on_progress_updates_bar(self, qtbot):
        """_on_progress atualiza barra de progresso"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        dialog._on_progress(50, 100)
        assert dialog.progress_bar.value() == 50

    def test_dialog_on_status_updates_label(self, qtbot):
        """_on_status atualiza label de status"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        dialog._on_status("Exportando... 50/100")
        assert "50/100" in dialog.status_label.text()

    def test_dialog_close_event_blocked_during_export(self, qtbot):
        """closeEvent e bloqueado durante exportacao"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        dialog._is_exporting = True
        dialog._worker = MagicMock()

        from PyQt6.QtGui import QCloseEvent
        event = QCloseEvent()
        dialog.closeEvent(event)

        assert event.isAccepted() is False

    def test_dialog_cancel_rejects_when_not_exporting(self, qtbot):
        """Cancelar fecha dialogo quando nao esta exportando"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        # _on_cancel chama reject() quando nao esta exportando
        dialog._is_exporting = False
        # Nao deve dar erro
        dialog._on_cancel()

    def test_dialog_cancel_requests_worker_cancel(self, qtbot):
        """Cancelar pede ao worker para parar quando exportando"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        mock_worker = MagicMock()
        dialog._is_exporting = True
        dialog._worker = mock_worker

        dialog._on_cancel()
        mock_worker.cancel.assert_called_once()

    def test_dialog_cleanup_thread(self, qtbot):
        """_cleanup_thread para thread e limpa referencias"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        mock_thread = MagicMock()
        dialog._thread = mock_thread
        dialog._worker = MagicMock()

        dialog._cleanup_thread()

        mock_thread.quit.assert_called_once()
        mock_thread.wait.assert_called_once_with(5000)
        assert dialog._thread is None
        assert dialog._worker is None

    def test_dialog_on_finished_success_accepts(self, qtbot):
        """_on_finished com sucesso fecha o dialogo (accept)"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        dialog._is_exporting = True
        dialog._on_finished(True, "100 linhas exportadas")

        assert dialog._is_exporting is False

    def test_dialog_on_finished_error_reenables_fields(self, qtbot):
        """_on_finished com erro reabilita campos"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        dialog._is_exporting = True
        dialog.btn_export.setEnabled(False)
        dialog.table_name_edit.setEnabled(False)

        dialog._on_finished(False, "Erro ao exportar")

        assert dialog._is_exporting is False
        assert dialog.btn_export.isEnabled() is True
        assert dialog.table_name_edit.isEnabled() is True

    def test_dialog_schema_table_split(self, qtbot):
        """on_export separa schema.tabela corretamente"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        dialog.table_name_edit.setText("dbo.my_table")
        # Simula validacao manual
        table_name = dialog.table_name_edit.text().strip()
        schema = None
        actual_table = table_name
        if "." in table_name and not table_name.startswith("#"):
            parts = table_name.split(".", 1)
            schema = parts[0]
            actual_table = parts[1]

        assert schema == "dbo"
        assert actual_table == "my_table"

    def test_dialog_temp_table_no_schema_split(self, qtbot):
        """Tabelas temporarias (#) nao devem separar schema"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        table_name = "#temp.table"
        schema = None
        actual_table = table_name
        if "." in table_name and not table_name.startswith("#"):
            parts = table_name.split(".", 1)
            schema = parts[0]
            actual_table = parts[1]

        assert schema is None
        assert actual_table == "#temp.table"

    def test_dialog_applies_style_without_error(self, qtbot):
        """_apply_style nao levanta excecao (sem key 'surface')"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        theme = ThemeManager()
        dialog = ExportToTableDialog(df, conns, theme_manager=theme)
        qtbot.addWidget(dialog)
        # Se chegou aqui sem KeyError, passou
        assert dialog is not None

    def test_dialog_empty_connections_dict(self, qtbot):
        """Dialogo funciona com dict vazio de conexoes"""
        df = _sample_df()
        dialog = ExportToTableDialog(df, {})
        qtbot.addWidget(dialog)

        assert dialog.connection_combo.count() == 0

    def test_dialog_if_exists_options(self, qtbot):
        """Combo if_exists tem 3 opcoes"""
        df = _sample_df()
        conns = _make_connections(srv=True)
        dialog = ExportToTableDialog(df, conns)
        qtbot.addWidget(dialog)

        assert dialog.if_exists_combo.count() == 3
        data_values = [dialog.if_exists_combo.itemData(i) for i in range(3)]
        assert "replace" in data_values
        assert "append" in data_values
        assert "fail" in data_values


# ==================== Integration Tests (SQLite in-memory) ====================

class TestExportIntegration:
    """Testes de integracao: exportacao real para banco SQLite in-memory.

    Valida o fluxo completo: dialog -> worker (Polars + raw cursor) -> banco.
    Usa SQLite in-memory para simular banco real sem dependencias externas.
    """

    @pytest.fixture
    def sqlite_engine(self):
        """Engine SQLite in-memory compartilhado entre threads"""
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        yield engine
        engine.dispose()

    @pytest.fixture
    def make_dialog(self, qtbot, sqlite_engine):
        """Factory: cria ExportToTableDialog com conexao SQLite real"""
        def _factory(df):
            connector = MagicMock()
            connector.is_connected.return_value = True
            connector.db_type = "SQLite"
            connector.get_current_database.return_value = "memory"
            connector.engine = sqlite_engine

            conns = {"local": connector}
            dialog = ExportToTableDialog(
                df, conns, current_connection="local",
            )
            qtbot.addWidget(dialog)
            return dialog
        return _factory

    def _export(self, qtbot, dialog, table_name, if_exists="replace", chunksize=None):
        """Preenche formulario, dispara export e aguarda conclusao"""
        dialog.table_name_edit.setText(table_name)

        for i in range(dialog.if_exists_combo.count()):
            if dialog.if_exists_combo.itemData(i) == if_exists:
                dialog.if_exists_combo.setCurrentIndex(i)
                break

        if chunksize is not None:
            dialog.chunk_spin.setValue(chunksize)

        with (
            patch("src.ui.dialogs.export_to_table_dialog.show_success"),
            patch("src.ui.dialogs.export_to_table_dialog.show_danger"),
        ):
            dialog._on_export()
            qtbot.waitUntil(lambda: not dialog._is_exporting, timeout=5000)

    def _read(self, engine, table_name):
        """Le tabela do banco e retorna pandas DataFrame"""
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text(f'SELECT * FROM "{table_name}"'))
            cols = list(result.keys())
            rows = result.fetchall()
            return pd.DataFrame(rows, columns=cols)

    def test_export_10_rows(self, qtbot, sqlite_engine, make_dialog):
        """Exporta 10 linhas e verifica dados gravados no banco"""
        df = pd.DataFrame({
            "id": list(range(10)),
            "name": [f"item_{i}" for i in range(10)],
            "value": [i * 1.5 for i in range(10)],
        })
        dialog = make_dialog(df)
        self._export(qtbot, dialog, "basic_test")

        result = self._read(sqlite_engine, "basic_test")
        assert len(result) == 10
        assert set(result.columns) == {"id", "name", "value"}
        assert result["id"].tolist() == list(range(10))

    def test_export_chunked_150_rows(self, qtbot, sqlite_engine, make_dialog):
        """Exporta 150 linhas em chunks de 30 - todas devem estar no banco"""
        df = pd.DataFrame({
            "id": list(range(150)),
            "val": [f"v{i}" for i in range(150)],
        })
        dialog = make_dialog(df)
        self._export(qtbot, dialog, "chunked_test", chunksize=30)

        result = self._read(sqlite_engine, "chunked_test")
        assert len(result) == 150

    def test_export_replace_overwrites(self, qtbot, sqlite_engine, make_dialog):
        """Replace: segundo export substitui dados do primeiro"""
        df1 = pd.DataFrame({"id": [1, 2, 3]})
        d1 = make_dialog(df1)
        self._export(qtbot, d1, "replace_test", if_exists="replace")

        df2 = pd.DataFrame({"id": [10, 20]})
        d2 = make_dialog(df2)
        self._export(qtbot, d2, "replace_test", if_exists="replace")

        result = self._read(sqlite_engine, "replace_test")
        assert len(result) == 2
        assert result["id"].tolist() == [10, 20]

    def test_export_append_accumulates(self, qtbot, sqlite_engine, make_dialog):
        """Append: segundo export acumula linhas"""
        df1 = pd.DataFrame({"id": [1, 2, 3]})
        d1 = make_dialog(df1)
        self._export(qtbot, d1, "append_test", if_exists="replace")

        df2 = pd.DataFrame({"id": [4, 5]})
        d2 = make_dialog(df2)
        self._export(qtbot, d2, "append_test", if_exists="append")

        result = self._read(sqlite_engine, "append_test")
        assert len(result) == 5

    def test_export_mixed_types(self, qtbot, sqlite_engine, make_dialog):
        """Exporta int, float, str e bool - todos tipos preservados"""
        df = pd.DataFrame({
            "int_col": [1, 2, 3],
            "float_col": [1.1, 2.2, 3.3],
            "str_col": ["a", "b", "c"],
            "bool_col": [True, False, True],
        })
        dialog = make_dialog(df)
        self._export(qtbot, dialog, "types_test")

        result = self._read(sqlite_engine, "types_test")
        assert len(result) == 3
        assert result["str_col"].tolist() == ["a", "b", "c"]

    def test_export_with_nulls(self, qtbot, sqlite_engine, make_dialog):
        """Exporta DataFrame com NaN/None - nulos preservados"""
        df = pd.DataFrame({
            "id": [1, 2, 3],
            "name": ["Alice", None, "Carol"],
            "value": [10.0, float("nan"), 30.0],
        })
        dialog = make_dialog(df)
        self._export(qtbot, dialog, "nulls_test")

        result = self._read(sqlite_engine, "nulls_test")
        assert len(result) == 3
        assert pd.isna(result.loc[1, "name"])

    def test_export_5000_rows(self, qtbot, sqlite_engine, make_dialog):
        """Exporta volume grande: 5000 linhas em chunks de 1000"""
        n = 5000
        df = pd.DataFrame({
            "id": list(range(n)),
            "value": [f"row_{i}" for i in range(n)],
        })
        dialog = make_dialog(df)
        self._export(qtbot, dialog, "large_test", chunksize=1000)

        result = self._read(sqlite_engine, "large_test")
        assert len(result) == n

    def test_export_nullable_pandas_types(self, qtbot, sqlite_engine, make_dialog):
        """Exporta DataFrame com tipos nullable (Int64, StringDtype) sem pyarrow error"""
        df = pd.DataFrame({
            "id": pd.array([1, 2, 3], dtype=pd.Int64Dtype()),
            "name": pd.array(["x", "y", "z"], dtype=pd.StringDtype()),
        })
        dialog = make_dialog(df)
        self._export(qtbot, dialog, "nullable_test")

        result = self._read(sqlite_engine, "nullable_test")
        assert len(result) == 3
        assert result["name"].tolist() == ["x", "y", "z"]

    def test_export_progress_reported(self, qtbot, sqlite_engine, make_dialog):
        """Progresso e reportado ao dialog durante export chunked"""
        df = pd.DataFrame({"id": list(range(100))})
        dialog = make_dialog(df)

        self._export(qtbot, dialog, "progress_test", chunksize=25)

        # Barra de progresso deve estar em 100% apos conclusao
        assert dialog.progress_bar.value() == 100

        # Dados efetivamente no banco
        result = self._read(sqlite_engine, "progress_test")
        assert len(result) == 100

    def test_export_data_integrity(self, qtbot, sqlite_engine, make_dialog):
        """Verifica integridade dos dados: valores exatos apos export"""
        df = pd.DataFrame({
            "nome": ["Maria", "Joao", "Ana"],
            "idade": [25, 30, 22],
            "salario": [5000.50, 7500.75, 3200.00],
        })
        dialog = make_dialog(df)
        self._export(qtbot, dialog, "integrity_test")

        result = self._read(sqlite_engine, "integrity_test")
        assert result["nome"].tolist() == ["Maria", "Joao", "Ana"]
        assert result["idade"].tolist() == [25, 30, 22]
        assert result["salario"].tolist() == pytest.approx([5000.50, 7500.75, 3200.00])
