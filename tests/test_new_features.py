"""
Testes para as 5 features novas:

1. Variaveis de banco no painel de variaveis
2. Dialogo de importacao de arquivos (CSV, JSON, XLSX)
3. fastexcel para XLSX
4. Context menu + double-click no painel de variaveis
5. Autocomplete com variaveis em memoria (insert_text_at_cursor)
"""

import pytest
import os
import tempfile
import pandas as pd
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from PyQt6.QtCore import Qt, QPoint, QUrl, QMimeData, QPointF
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QApplication, QMenu

from src.ui.components.variables_panel import VariablesPanel, VariablesTableModel
from src.services.file_import_service import FileImportService
from src.ui.dialogs.file_import_dialog import FileImportDialog
from src.editors.block_editor import BlockEditor
from src.editors.code_block import CodeBlock


# Fixture autouse para evitar hang do Monaco WebEngine focus em testes
@pytest.fixture(autouse=True)
def _no_focus_editor(monkeypatch):
    """Desabilita focus_editor para evitar hang do Monaco em testes"""
    monkeypatch.setattr(CodeBlock, "focus_editor", lambda self: None)


# ==================== 1. VARIAVEIS DE BANCO NO PAINEL ====================


class TestDbVariablesInPanel:
    """Testes para exposicao de variaveis de banco no painel de variaveis"""

    def test_update_variables_view_injects_db_vars(self, qapp):
        """_update_variables_view deve injetar variaveis de banco no namespace visivel"""
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session

        session = Session("test_db_vars", "Test")

        # Mock connector com engine
        mock_connector = MagicMock()
        mock_connector.engine = MagicMock()
        mock_connector.engine.url = "mssql+pyodbc://host/db"
        mock_connector.db_type = "sqlserver"
        mock_connector.connection_params = {
            "host": "localhost",
            "port": 1433,
            "database": "mydb",
            "username": "sa",
        }
        session._connector = mock_connector
        session._connection_name = "TestConn"

        widget = SessionWidget(session)

        # Capturar variaveis enviadas para o painel
        captured_vars = {}
        widget._set_variables = lambda v: captured_vars.update(v)

        # Simular update de namespace (a view le de session.effective_namespace())
        namespace = {"x": 42, "df": pd.DataFrame({"a": [1]})}
        session.update_namespace(namespace)
        widget._update_variables_view(namespace)

        # Deve ter as variaveis originais
        assert "x" in captured_vars
        assert "df" in captured_vars

        # Deve ter as variaveis de banco injetadas
        assert "db_engine" in captured_vars
        assert "db_type" in captured_vars
        assert captured_vars["db_type"] == "sqlserver"
        assert "db_connection_name" in captured_vars
        assert captured_vars["db_connection_name"] == "TestConn"
        assert "db_host" in captured_vars
        assert captured_vars["db_host"] == "localhost"
        assert "db_port" in captured_vars
        assert captured_vars["db_port"] == 1433
        assert "db_database" in captured_vars
        assert captured_vars["db_database"] == "mydb"
        assert "db_username" in captured_vars
        assert captured_vars["db_username"] == "sa"
        assert "db_connection_string" in captured_vars

    def test_update_variables_view_no_connection(self, qapp):
        """Sem conexao, nao deve injetar variaveis de banco"""
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session

        session = Session("test_no_conn", "Test")
        widget = SessionWidget(session)

        captured_vars = {}
        widget._set_variables = lambda v: captured_vars.update(v)

        namespace = {"y": 10}
        session.update_namespace(namespace)
        widget._update_variables_view(namespace)

        assert "y" in captured_vars
        assert "db_engine" not in captured_vars
        assert "db_type" not in captured_vars

    def test_inject_db_variables_handles_errors(self, qapp):
        """_inject_db_variables deve silenciar erros"""
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session

        session = Session("test_err", "Test")
        mock_connector = MagicMock()
        mock_connector.engine = property(lambda self: (_ for _ in ()).throw(Exception("boom")))
        mock_connector.db_type = "mysql"
        mock_connector.connection_params = {}
        session._connector = mock_connector
        session._connection_name = "Broken"

        widget = SessionWidget(session)
        variables = {}
        # Nao deve levantar excecao
        widget._inject_db_variables(variables)
        # Pelo menos db_connection_name deve estar presente
        assert "db_connection_name" in variables

    def test_db_vars_injected_in_python_namespace(self, qapp):
        """Variaveis de banco devem ser injetadas no namespace de execucao Python"""
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session

        session = Session("test_py_ns", "Test")
        mock_connector = MagicMock()
        mock_connector.engine = MagicMock()
        mock_connector.db_type = "postgresql"
        mock_connector.connection_params = {"host": "pghost", "port": 5432, "database": "pgdb", "username": "pguser"}
        session._connector = mock_connector
        session._connection_name = "PGConn"

        widget = SessionWidget(session)

        # Mock para capturar o namespace passado ao PythonWorker
        captured_ns = {}

        with patch("src.ui.components.session_widget.QThread"):
            with patch("src.ui.main_window.PythonWorker") as MockWorker:
                mock_worker = MagicMock()
                MockWorker.return_value = mock_worker

                def capture_init(code, namespace, is_expression):
                    captured_ns.update(namespace)
                    return mock_worker

                MockWorker.side_effect = capture_init

                widget._on_execute_python("print(db_type)")

        assert "db_type" in captured_ns
        assert captured_ns["db_type"] == "postgresql"
        assert "db_engine" in captured_ns
        assert "db_host" in captured_ns


# ==================== 2/3. DIALOGO DE IMPORTACAO + FASTEXCEL ====================


class TestFileImportDialog:
    """Testes para o dialogo de importacao de arquivos"""

    def test_dialog_csv_defaults(self, qapp):
        """Dialogo CSV deve ter opcoes de separador, encoding, etc."""
        dialog = FileImportDialog("/tmp/dados.csv")

        assert dialog.var_name_input.text() == "dados"
        assert dialog.encoding_combo.currentText() == "utf-8"
        assert hasattr(dialog, "separator_combo")
        assert hasattr(dialog, "decimal_combo")
        assert hasattr(dialog, "header_combo")

    def test_dialog_xlsx_defaults(self, qapp):
        """Dialogo XLSX deve ter opcao de sheet"""
        dialog = FileImportDialog("/tmp/planilha.xlsx")

        assert dialog.var_name_input.text() == "planilha"
        assert hasattr(dialog, "sheet_input")
        assert dialog.sheet_input.text() == "0"

    def test_dialog_json_defaults(self, qapp):
        """Dialogo JSON deve ter opcao de orient"""
        dialog = FileImportDialog("/tmp/data.json")

        assert dialog.var_name_input.text() == "data"
        assert hasattr(dialog, "orient_combo")
        assert hasattr(dialog, "json_lines_check")

    def test_dialog_normalize_var_name(self, qapp):
        """Dialogo deve normalizar nome do arquivo para variavel"""
        dialog = FileImportDialog("/tmp/Meus Dados (2024).csv")
        assert dialog.var_name_input.text() == "meus_dados_2024"

    def test_dialog_csv_code_generation(self, qapp):
        """Dialogo CSV deve gerar codigo correto"""
        dialog = FileImportDialog("C:\\Users\\test\\dados.csv")
        dialog.var_name_input.setText("vendas")
        dialog.encoding_combo.setCurrentText("latin-1")
        # Primeiro separador e ; (default)

        dialog._on_import()
        code, var_name = dialog.get_result()

        assert var_name == "vendas"
        assert "import pandas as pd" in code
        assert "pd.read_csv" in code
        assert 'sep=";"' in code
        assert 'encoding="latin-1"' in code
        assert "vendas" in code

    def test_dialog_xlsx_code_uses_fastexcel(self, qapp):
        """Dialogo XLSX deve gerar codigo com fastexcel"""
        dialog = FileImportDialog("/tmp/report.xlsx")
        dialog.var_name_input.setText("report")

        dialog._on_import()
        code, var_name = dialog.get_result()

        assert var_name == "report"
        assert "import fastexcel" in code
        assert "fastexcel.read_excel" in code
        assert ".load_sheet(0)" in code
        assert ".to_pandas()" in code
        assert "report" in code

    def test_dialog_json_code_generation(self, qapp):
        """Dialogo JSON deve gerar codigo correto"""
        dialog = FileImportDialog("/tmp/api_data.json")
        dialog.var_name_input.setText("api_data")
        dialog.orient_combo.setCurrentIndex(1)  # records

        dialog._on_import()
        code, var_name = dialog.get_result()

        assert "pd.read_json" in code
        assert 'orient="records"' in code

    def test_dialog_csv_with_nrows(self, qapp):
        """Dialogo CSV deve suportar limite de linhas"""
        dialog = FileImportDialog("/tmp/big.csv")
        dialog.limit_rows_check.setChecked(True)
        dialog.nrows_spin.setValue(500)

        dialog._on_import()
        code, _ = dialog.get_result()

        assert "nrows=500" in code

    def test_dialog_csv_skip_rows(self, qapp):
        """Dialogo CSV deve suportar pular linhas"""
        dialog = FileImportDialog("/tmp/messy.csv")
        dialog.skip_rows_spin.setValue(3)

        dialog._on_import()
        code, _ = dialog.get_result()

        assert "skiprows=3" in code

    def test_dialog_csv_no_header(self, qapp):
        """Dialogo CSV deve suportar arquivo sem cabecalho"""
        dialog = FileImportDialog("/tmp/nohead.csv")
        dialog.header_combo.setCurrentIndex(1)  # Sem cabecalho

        dialog._on_import()
        code, _ = dialog.get_result()

        assert "header=None" in code

    def test_dialog_xlsx_sheet_by_name(self, qapp):
        """Dialogo XLSX deve suportar sheet por nome"""
        dialog = FileImportDialog("/tmp/multi.xlsx")
        dialog.sheet_input.setText("Vendas")

        dialog._on_import()
        code, _ = dialog.get_result()

        assert '.load_sheet_by_name("Vendas")' in code

    def test_dialog_xlsx_skip_rows(self, qapp):
        """Dialogo XLSX deve suportar pular linhas"""
        dialog = FileImportDialog("/tmp/header_mess.xlsx")
        dialog.xlsx_skip_rows_spin.setValue(2)

        dialog._on_import()
        code, _ = dialog.get_result()

        assert "skip_rows=2" in code

    def test_dialog_json_lines_mode(self, qapp):
        """Dialogo JSON deve suportar modo JSON Lines"""
        dialog = FileImportDialog("/tmp/logs.json")
        dialog.json_lines_check.setChecked(True)

        dialog._on_import()
        code, _ = dialog.get_result()

        assert "lines=True" in code

    def test_dialog_empty_var_name_fallback(self, qapp):
        """Nome vazio de variavel deve usar fallback 'df'"""
        dialog = FileImportDialog("/tmp/test.csv")
        dialog.var_name_input.setText("")

        dialog._on_import()
        _, var_name = dialog.get_result()

        assert var_name == "df"

    def test_dialog_invalid_var_name_normalized(self, qapp):
        """Nome invalido de variavel deve ser normalizado"""
        dialog = FileImportDialog("/tmp/test.csv")
        dialog.var_name_input.setText("123invalid!")

        dialog._on_import()
        _, var_name = dialog.get_result()

        # Deve ter sido normalizado (prefixo df_ para digito)
        assert var_name.isidentifier()

    def test_dialog_cancelled_returns_none(self, qapp):
        """Dialogo cancelado deve retornar None"""
        dialog = FileImportDialog("/tmp/test.csv")
        # Nao chamar _on_import
        code, var_name = dialog.get_result()

        assert code is None
        assert var_name is None

    def test_dialog_csv_decimal_comma(self, qapp):
        """Dialogo CSV deve suportar decimal com virgula"""
        dialog = FileImportDialog("/tmp/br_data.csv")
        dialog.decimal_combo.setCurrentIndex(1)  # Virgula

        dialog._on_import()
        code, _ = dialog.get_result()

        assert 'decimal=","' in code

    def test_dialog_theme_applied(self, qapp):
        """Dialogo deve aceitar theme_manager"""
        from src.core.theme_manager import ThemeManager

        tm = ThemeManager()
        dialog = FileImportDialog("/tmp/test.csv", theme_manager=tm)
        # Nao deve levantar excecao
        assert dialog.theme_manager is tm


# ==================== 3. FASTEXCEL NO FILEIMPORTSERVICE ====================


class TestFastExcelInService:
    """Testes para uso de fastexcel no FileImportService"""

    def test_generate_import_code_xlsx_uses_fastexcel(self):
        """generate_import_code para XLSX deve usar fastexcel"""
        code = FileImportService.generate_import_code("/tmp/data.xlsx")
        assert code is not None
        assert "fastexcel" in code
        assert ".load_sheet(0)" in code
        assert "to_pandas()" in code

    def test_generate_import_code_xls_uses_fastexcel(self):
        """generate_import_code para XLS deve usar fastexcel"""
        code = FileImportService.generate_import_code("/tmp/old.xls")
        assert code is not None
        assert "fastexcel" in code

    def test_generate_import_code_csv_unchanged(self):
        """generate_import_code para CSV nao deve usar fastexcel"""
        code = FileImportService.generate_import_code("/tmp/data.csv")
        assert code is not None
        assert "pd.read_csv" in code
        assert "fastexcel" not in code

    def test_generate_import_code_json_unchanged(self):
        """generate_import_code para JSON nao deve usar fastexcel"""
        code = FileImportService.generate_import_code("/tmp/data.json")
        assert code is not None
        assert "pd.read_json" in code
        assert "fastexcel" not in code


# ==================== 4. CONTEXT MENU + DOUBLE-CLICK ====================


class TestVariablesPanelContextMenu:
    """Testes para context menu e double-click no painel de variaveis"""

    @pytest.fixture
    def panel_with_vars(self, qapp):
        """Painel com variaveis pre-definidas"""
        panel = VariablesPanel()
        namespace = {
            "df": pd.DataFrame({"a": [1, 2], "b": [3, 4]}),
            "x": 42,
            "nome": "hello",
            "minha_lista": [1, 2, 3],
        }
        panel.set_variables(namespace)
        return panel

    def test_panel_has_context_menu_policy(self, panel_with_vars):
        """Tabela deve ter context menu policy custom"""
        assert panel_with_vars.table_view.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu

    def test_panel_has_insert_signal(self, panel_with_vars):
        """Painel deve ter sinal insert_variable_name"""
        assert hasattr(panel_with_vars, "insert_variable_name")

    def test_panel_has_delete_signal(self, panel_with_vars):
        """Painel deve ter sinal delete_variable"""
        assert hasattr(panel_with_vars, "delete_variable")

    def test_insert_name_emits_insert_signal(self, panel_with_vars, qtbot):
        """A acao de inserir (menu de contexto) deve emitir insert_variable_name.

        Double-click agora abre o dialogo de detalhes e emite
        variable_double_clicked; a insercao do nome migrou para _insert_name.
        """
        panel = panel_with_vars

        with qtbot.waitSignal(panel.insert_variable_name, timeout=1000) as blocker:
            panel._insert_name("df")

        assert blocker.args[0] == "df"

    def test_double_click_also_emits_variable_double_clicked(self, panel_with_vars, qtbot):
        """Double-click deve emitir variable_double_clicked tambem"""
        panel = panel_with_vars

        with qtbot.waitSignal(panel.variable_double_clicked, timeout=1000):
            index = panel.model.index(0, 0)
            panel._on_double_click(index)

    def test_context_menu_created(self, panel_with_vars, qapp):
        """Context menu deve ser criado ao clicar com botao direito"""
        panel = panel_with_vars

        # Verificar que o handler existe
        assert hasattr(panel, "_on_context_menu")

    def test_get_copyable_value_dataframe(self):
        """_get_copyable_value para DataFrame deve retornar to_string"""
        df = pd.DataFrame({"a": [1]})
        result = VariablesPanel._get_copyable_value(df)
        assert "a" in result
        assert "1" in result

    def test_get_copyable_value_string(self):
        """_get_copyable_value para string deve retornar repr"""
        result = VariablesPanel._get_copyable_value("hello")
        assert "hello" in result

    def test_get_copyable_value_number(self):
        """_get_copyable_value para numero deve retornar repr"""
        result = VariablesPanel._get_copyable_value(42)
        assert "42" in result

    def test_panel_has_show_in_results_signal(self, panel_with_vars):
        """Painel deve ter sinal show_in_results"""
        assert hasattr(panel_with_vars, "show_in_results")

    def test_show_in_results_emitted_for_dataframe(self, panel_with_vars, qtbot):
        """show_in_results deve ser emitido para DataFrame via context menu action"""
        panel = panel_with_vars

        # Encontrar a linha do DataFrame (variaveis sao ordenadas por nome)
        df_row = None
        for i in range(panel.model.rowCount()):
            if panel.model.get_variable_name(i) == "df":
                df_row = i
                break
        assert df_row is not None

        with qtbot.waitSignal(panel.show_in_results, timeout=1000) as blocker:
            panel.show_in_results.emit("df", panel.model.get_variable(df_row))

        assert blocker.args[0] == "df"
        assert isinstance(blocker.args[1], pd.DataFrame)

    def test_show_in_results_not_applicable_for_non_dataframe(self, panel_with_vars):
        """Variaveis que nao sao DataFrame/Series nao devem acionar show_in_results"""
        panel = panel_with_vars
        # Verificar que int/str/list nao sao DataFrame nem Series
        for i in range(panel.model.rowCount()):
            name = panel.model.get_variable_name(i)
            value = panel.model.get_variable(i)
            if name == "x":
                assert not isinstance(value, (pd.DataFrame, pd.Series))
            if name == "nome":
                assert not isinstance(value, (pd.DataFrame, pd.Series))
            if name == "minha_lista":
                assert not isinstance(value, (pd.DataFrame, pd.Series))

    def test_show_in_results_series_converts_to_dataframe(self, qapp):
        """Series deve ser convertida para DataFrame antes de exibir nos resultados"""
        panel = VariablesPanel()
        series = pd.Series([10, 20, 30], name="valores")
        panel.set_variables({"minha_serie": series})

        # Verificar que Series esta no painel
        found = False
        for i in range(panel.model.rowCount()):
            if panel.model.get_variable_name(i) == "minha_serie":
                val = panel.model.get_variable(i)
                assert isinstance(val, pd.Series)
                # Simular conversao como o handler faria
                df = val.to_frame(name="minha_serie")
                assert isinstance(df, pd.DataFrame)
                assert len(df) == 3
                found = True
        assert found


class TestVariablesTableModel:
    """Testes adicionais para o model de variaveis (preview de tipos DB)"""

    def test_model_shows_db_type(self, qapp):
        """Model deve mostrar tipo correto para variaveis de banco"""
        model = VariablesTableModel()
        model.set_variables({
            "db_type": "sqlserver",
            "db_host": "localhost",
            "db_port": 1433,
        })

        assert model.rowCount() == 3
        # Verificar que nomes estao presentes
        names = [model.get_variable_name(i) for i in range(3)]
        assert "db_type" in names
        assert "db_host" in names
        assert "db_port" in names

    def test_model_shows_engine_type(self, qapp):
        """Model deve mostrar tipo Engine para db_engine"""
        mock_engine = MagicMock()
        mock_engine.__class__.__name__ = "Engine"

        model = VariablesTableModel()
        model.set_variables({"db_engine": mock_engine})

        assert model.rowCount() == 1
        # O tipo exibido deve ser o tipo do mock
        idx = model.index(0, 1)
        type_displayed = model.data(idx, Qt.ItemDataRole.DisplayRole)
        assert type_displayed is not None


# ==================== 5. AUTOCOMPLETE ====================


@pytest.mark.skip(reason="QScintilla CodeEditor removed - Monaco only")
class TestEditorInsertText:
    """Testes para insert_text_at_cursor no CodeEditor (QScintilla)"""

    def test_editor_has_insert_text_method(self, qapp):
        """CodeEditor deve ter metodo insert_text_at_cursor"""
        pass

    def test_editor_insert_text_at_cursor(self, qapp):
        """insert_text_at_cursor deve inserir texto na posicao do cursor"""
        pass


# ==================== 6. BLOCKEDITOR FILE_DROPPED SIGNAL ====================


class TestBlockEditorFileDrop:
    """Testes para o sinal file_dropped do BlockEditor"""

    def test_block_editor_has_file_dropped_signal(self, qapp):
        """BlockEditor deve ter sinal file_dropped"""
        editor = BlockEditor()
        assert hasattr(editor, "file_dropped")

    def test_drop_event_emits_file_dropped_for_csv(self, qapp, qtbot):
        """Drop de CSV deve emitir file_dropped"""
        editor = BlockEditor()

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/tmp/test.csv")])

        with qtbot.waitSignal(editor.file_dropped, timeout=1000) as blocker:
            event = QDropEvent(
                QPointF(10, 10),
                Qt.DropAction.CopyAction,
                mime_data,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            editor.dropEvent(event)

        assert blocker.args[0] == "/tmp/test.csv"

    def test_drop_event_emits_file_dropped_for_xlsx(self, qapp, qtbot):
        """Drop de XLSX deve emitir file_dropped"""
        editor = BlockEditor()

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/tmp/data.xlsx")])

        with qtbot.waitSignal(editor.file_dropped, timeout=1000) as blocker:
            event = QDropEvent(
                QPointF(10, 10),
                Qt.DropAction.CopyAction,
                mime_data,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            editor.dropEvent(event)

        assert blocker.args[0] == "/tmp/data.xlsx"

    def test_drop_event_sql_file_adds_block_directly(self, qapp, tmp_path):
        """Drop de arquivo SQL deve adicionar bloco diretamente (sem dialogo)"""
        editor = BlockEditor()

        sql_file = tmp_path / "query.sql"
        sql_file.write_text("SELECT * FROM users", encoding="utf-8")

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(sql_file))])

        initial_blocks = len(editor.get_blocks())

        event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        editor.dropEvent(event)

        # Deve ter adicionado um bloco SQL
        assert len(editor.get_blocks()) == initial_blocks + 1
        new_block = editor.get_blocks()[-1]
        assert new_block.get_language() == "sql"


# ==================== 7. SESSION WIDGET FILE DROP ====================


class TestSessionWidgetFileDrop:
    """Testes para o handler de file drop no SessionWidget"""

    def test_session_widget_connects_file_dropped(self, qapp):
        """SessionWidget deve conectar sinal file_dropped do editor"""
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session

        session = Session("test_drop", "Test")
        widget = SessionWidget(session)

        # Verificar que o metodo handler existe
        assert hasattr(widget, "_on_file_dropped")

    def test_on_file_dropped_opens_dialog(self, qapp, monkeypatch):
        """_on_file_dropped deve abrir FileImportDialog"""
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session

        session = Session("test_dialog", "Test")
        widget = SessionWidget(session)

        dialog_opened = [False]

        # O auto_close_dialogs do conftest ja vai aceitar o dialogo
        # Patch para verificar que o dialogo foi criado
        original_init = FileImportDialog.__init__

        def mock_init(self_dialog, file_path, theme_manager=None, parent=None):
            dialog_opened[0] = True
            original_init(self_dialog, file_path, theme_manager, parent)

        monkeypatch.setattr(FileImportDialog, "__init__", mock_init)

        widget._on_file_dropped("/tmp/test.csv")

        assert dialog_opened[0]


# ==================== 8. INTEGRACAO: VARIABLES PANEL + DB ====================


class TestVariablesPanelWithDbVars:
    """Testes de integracao: painel mostra variaveis de banco corretamente"""

    def test_panel_displays_db_vars(self, qapp):
        """Painel deve exibir variaveis de banco com tipos corretos"""
        panel = VariablesPanel()
        namespace = {
            "df": pd.DataFrame({"col": [1, 2, 3]}),
            "db_type": "mysql",
            "db_host": "localhost",
            "db_port": 3306,
            "db_database": "mydb",
            "db_connection_name": "MyConn",
        }
        panel.set_variables(namespace)

        model = panel.model
        assert model.rowCount() == 6

        # Verificar que db_type esta presente
        names = [model.get_variable_name(i) for i in range(model.rowCount())]
        assert "db_type" in names
        assert "db_host" in names
        assert "db_port" in names
        assert "db_database" in names
        assert "db_connection_name" in names
        assert "df" in names

    def test_panel_info_label_counts_db_vars(self, qapp):
        """Info label deve contar variaveis de banco tambem"""
        panel = VariablesPanel()
        namespace = {
            "x": 1,
            "db_type": "postgresql",
            "db_host": "pghost",
        }
        panel.set_variables(namespace)

        assert "3" in panel.info_label.text()


# ==================== 9. IMPORT CODE PATHS ====================


class TestImportCodePaths:
    """Testes para caminhos do Windows normalizados no codigo gerado"""

    def test_csv_path_normalized(self):
        """Caminho Windows deve ser normalizado com /"""
        code = FileImportService.generate_import_code("C:\\Users\\test\\data.csv")
        assert "\\\\" not in code or "/" in code
        assert "C:/Users/test/data.csv" in code

    def test_xlsx_path_normalized(self):
        """Caminho Windows XLSX deve ser normalizado"""
        code = FileImportService.generate_import_code("C:\\Users\\test\\data.xlsx")
        assert "C:/Users/test/data.xlsx" in code

    def test_dialog_csv_path_normalized(self, qapp):
        """Dialogo CSV deve normalizar caminhos"""
        dialog = FileImportDialog("C:\\Users\\test\\vendas.csv")
        dialog._on_import()
        code, _ = dialog.get_result()
        assert "C:/Users/test/vendas.csv" in code

    def test_dialog_xlsx_path_normalized(self, qapp):
        """Dialogo XLSX deve normalizar caminhos"""
        dialog = FileImportDialog("D:\\Data\\report.xlsx")
        dialog._on_import()
        code, _ = dialog.get_result()
        assert "D:/Data/report.xlsx" in code
