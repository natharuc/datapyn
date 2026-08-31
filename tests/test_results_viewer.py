"""Tests for ResultsViewer copy selection functionality."""
import sys
import os
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))


class TestGridNumberDisplay:
    """Integer-valued floats (columns upcast to float by a NULL) must not show
    the trailing '.0' in the grid; real decimals stay intact."""

    def test_integer_valued_float_drops_dot_zero(self):
        from src.ui.components.results_viewer import _grid_format_display_value

        assert _grid_format_display_value(1569845.0, "default") == "1569845"
        assert _grid_format_display_value(np.float64(1569845.0), "default") == "1569845"

    def test_real_decimal_is_preserved(self):
        from src.ui.components.results_viewer import _grid_format_display_value

        assert _grid_format_display_value(8.58, "default") == "8.58"

    def test_huge_float_not_fabricated_as_exact_int(self):
        from src.ui.components.results_viewer import _grid_format_display_value

        big = 1e20  # beyond 2**53 — floats can't represent ints exactly here
        assert _grid_format_display_value(big, "default") == str(big)

    def test_bool_is_not_treated_as_number(self):
        from src.ui.components.results_viewer import _grid_format_display_value

        assert _grid_format_display_value(True, "default") == "True"

    def test_prepared_grid_cleans_id_column_keeps_decimals(self):
        from src.ui.components.results_viewer import prepare_grid_data

        df = pd.DataFrame(
            {"IdExterno": [1569845.0, float("nan")], "Valor": [8.58, 199.0]}
        )
        prepared = prepare_grid_data(df, {}, {}, 1000).prepared

        assert prepared.display_value(0, 0) == "1569845"   # id float → clean int
        assert prepared.display_value(0, 1) == "8.58"       # real decimal kept
        assert prepared.display_value(1, 0) == "NULL"       # NaN id → NULL
        assert prepared.display_value(1, 1) == "199"        # 199.0 → clean int


def _chart_page_ready(page) -> bool:
    from src.ui.components.results_viewer import ResultsViewer

    return ResultsViewer._chart_page_has_content(page)


def _switch_result_tab(viewer, qtbot, index: int, *, min_rows: int | None = None):
    """Switch result tabs and wait for the deferred handler to finish."""
    viewer._result_tabs.setCurrentIndex(index)
    qtbot.waitUntil(
        lambda: viewer._result_tabs.currentIndex() == index and viewer._pending_result_tab_index is None,
        timeout=5000,
    )
    if min_rows is not None:
        qtbot.waitUntil(lambda: viewer.model.rowCount() == min_rows, timeout=5000)


class TestResultsViewerCopySelection:
    """Tests for Ctrl+C copy selection in the results grid."""

    @pytest.fixture
    def viewer(self, qtbot):
        from src.ui.components.results_viewer import ResultsViewer
        v = ResultsViewer()
        qtbot.addWidget(v)
        return v

    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame({
            "nome": ["Alice", "Bob", "Carol", "Dave"],
            "idade": [25, 30, 35, 40],
            "cidade": ["SP", "RJ", "BH", "POA"],
        })

    def test_copy_selection_single_cell(self, viewer, sample_df, qtbot):
        """Copying a single selected cell (Ctrl+C) should have only data."""
        from PyQt6.QtWidgets import QApplication

        viewer.display_dataframe(sample_df)
        # Select cell (0, 0) = "Alice"
        model = viewer.table_view.model()
        idx = model.index(0, 0)
        viewer.table_view.selectionModel().select(
            idx,
            viewer.table_view.selectionModel().SelectionFlag.ClearAndSelect,
        )

        viewer._copy_selection_to_clipboard()

        text = QApplication.instance().clipboard().text()
        lines = text.strip().split("\n")
        assert len(lines) == 1  # data only, no header
        assert "Alice" in lines[0]

    def test_copy_selection_multiple_rows(self, viewer, sample_df, qtbot):
        """Copying multiple rows should include all selected rows (no header)."""
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QItemSelection, QItemSelectionModel

        viewer.display_dataframe(sample_df)
        model = viewer.table_view.model()
        sel_model = viewer.table_view.selectionModel()

        # Select rows 0-2, column 0 (nome)
        for row in range(3):
            idx = model.index(row, 0)
            sel_model.select(idx, QItemSelectionModel.SelectionFlag.Select)

        viewer._copy_selection_to_clipboard()

        text = QApplication.instance().clipboard().text()
        lines = text.strip().split("\n")
        assert len(lines) == 3  # 3 data rows, no header
        assert "Alice" in lines[0]
        assert "Bob" in lines[1]
        assert "Carol" in lines[2]

    def test_copy_selection_full_column(self, viewer, sample_df, qtbot):
        """Selecting a full column should copy all values (no header by default)."""
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QItemSelectionModel

        viewer.display_dataframe(sample_df)
        model = viewer.table_view.model()
        sel_model = viewer.table_view.selectionModel()

        # Select all rows for column 1 (idade)
        for row in range(4):
            idx = model.index(row, 1)
            sel_model.select(idx, QItemSelectionModel.SelectionFlag.Select)

        viewer._copy_selection_to_clipboard()

        text = QApplication.instance().clipboard().text()
        lines = text.strip().split("\n")
        assert len(lines) == 4  # 4 data rows, no header
        assert "25" in lines[0]
        assert "30" in lines[1]
        assert "35" in lines[2]
        assert "40" in lines[3]

    def test_copy_selection_with_headers(self, viewer, sample_df, qtbot):
        """Copy with Headers should include column names as first line."""
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QItemSelectionModel

        viewer.display_dataframe(sample_df)
        model = viewer.table_view.model()
        sel_model = viewer.table_view.selectionModel()

        for row in range(4):
            idx = model.index(row, 1)
            sel_model.select(idx, QItemSelectionModel.SelectionFlag.Select)

        viewer._copy_selection_to_clipboard(include_headers=True)

        text = QApplication.instance().clipboard().text()
        lines = text.strip().split("\n")
        assert len(lines) == 5  # header + 4 data rows
        assert "idade" in lines[0]
        assert "25" in lines[1]

    def test_copy_selection_multiple_columns(self, viewer, sample_df, qtbot):
        """Selecting cells across multiple columns should preserve structure."""
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QItemSelectionModel

        viewer.display_dataframe(sample_df)
        model = viewer.table_view.model()
        sel_model = viewer.table_view.selectionModel()

        # Select row 0, columns 0 and 2 (nome, cidade)
        sel_model.select(model.index(0, 0), QItemSelectionModel.SelectionFlag.Select)
        sel_model.select(model.index(0, 2), QItemSelectionModel.SelectionFlag.Select)

        viewer._copy_selection_to_clipboard(include_headers=True)

        text = QApplication.instance().clipboard().text()
        lines = text.strip().split("\n")
        assert len(lines) == 2  # header + 1 data row
        assert "nome" in lines[0]
        assert "cidade" in lines[0]
        assert "\t" in lines[0]
        assert "Alice" in lines[1]
        assert "SP" in lines[1]

    def test_copy_no_selection_falls_back_to_all(self, viewer, sample_df, qtbot):
        """When nothing is selected, should copy the entire DataFrame."""
        from PyQt6.QtWidgets import QApplication

        viewer.display_dataframe(sample_df)
        # Clear any selection
        viewer.table_view.selectionModel().clearSelection()

        viewer._copy_selection_to_clipboard()

        text = QApplication.instance().clipboard().text()
        # Should contain all rows (fall back to _copy_to_clipboard)
        assert "Alice" in text
        assert "Bob" in text
        assert "Carol" in text
        assert "Dave" in text

    def test_copy_selection_tab_separated(self, viewer, sample_df, qtbot):
        """Copied data should be tab-separated (pasteable into Excel)."""
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QItemSelectionModel

        viewer.display_dataframe(sample_df)
        model = viewer.table_view.model()
        sel_model = viewer.table_view.selectionModel()

        # Select row 0, all 3 columns
        for col in range(3):
            sel_model.select(model.index(0, col), QItemSelectionModel.SelectionFlag.Select)

        viewer._copy_selection_to_clipboard(include_headers=True)

        text = QApplication.instance().clipboard().text()
        lines = text.strip().split("\n")
        # Header
        header_parts = lines[0].split("\t")
        assert len(header_parts) == 3
        assert header_parts == ["nome", "idade", "cidade"]
        # Data
        data_parts = lines[1].split("\t")
        assert len(data_parts) == 3
        assert data_parts[0] == "Alice"
        assert data_parts[1] == "25"
        assert data_parts[2] == "SP"


class TestExportSettingsDialog:
    """Tests for the ExportSettingsDialog."""

    @pytest.fixture
    def clear_settings(self):
        """Clear export settings before/after each test."""
        from PyQt6.QtCore import QSettings
        settings = QSettings("DataPyn", "ExportSettings")
        settings.clear()
        yield
        settings.clear()

    def test_dialog_creation(self, qtbot, clear_settings):
        """Dialog should create without errors."""
        from src.ui.components.results_viewer import ExportSettingsDialog
        dialog = ExportSettingsDialog()
        qtbot.addWidget(dialog)
        assert dialog.copy_sep_combo.currentData() == "\t"  # default tab
        assert dialog.null_combo.currentData() == ""  # default empty
        assert dialog.open_folder_check.isChecked()  # default True
        # include_headers was removed from the dialog
        assert not hasattr(dialog, "header_check")

    def test_settings_persist(self, qtbot, clear_settings):
        """Settings should be saved and restored via QSettings."""
        from src.ui.components.results_viewer import ExportSettingsDialog
        from PyQt6.QtCore import QSettings

        settings = QSettings("DataPyn", "ExportSettings")
        settings.setValue("copy_separator", ";")
        settings.setValue("null_display", "NULL")
        settings.setValue("open_folder", False)

        dialog = ExportSettingsDialog()
        qtbot.addWidget(dialog)
        assert dialog.copy_sep_combo.currentData() == ";"
        assert dialog.null_combo.currentData() == "NULL"
        assert not dialog.open_folder_check.isChecked()

    def test_get_settings_static(self, clear_settings):
        """get_settings() should return defaults when nothing saved."""
        from src.ui.components.results_viewer import ExportSettingsDialog

        es = ExportSettingsDialog.get_settings()
        assert es["copy_separator"] == "\t"
        assert es["null_display"] == ""
        assert es["open_folder"] is True
        # include_headers no longer in settings
        assert "include_headers" not in es

    def test_get_settings_after_save(self, qtbot, clear_settings):
        """get_settings() should return saved values after dialog accept."""
        from src.ui.components.results_viewer import ExportSettingsDialog

        dialog = ExportSettingsDialog()
        qtbot.addWidget(dialog)
        dialog.copy_sep_combo.setCurrentIndex(1)  # comma
        dialog._save_settings()

        es = ExportSettingsDialog.get_settings()
        assert es["copy_separator"] == ","


class TestResultsViewerVisualizationTools:
    """Tests for the public visualization API used by Copilot tools."""

    @pytest.fixture
    def viewer(self, qtbot, monkeypatch):
        from src.ui.components.results_viewer import ResultsViewer

        v = ResultsViewer()
        qtbot.addWidget(v)
        monkeypatch.setattr(v, "_render_visualization_page", lambda page: None)
        return v

    @pytest.fixture
    def sales_df(self):
        return pd.DataFrame({
            "month": ["Jan", "Feb", "Mar"],
            "sales": [10, 20, 30],
            "cost": [4, 6, 9],
        })

    def test_create_visualization_lists_config_and_source(self, viewer, sales_df):
        viewer.display_dataframe(sales_df, "sales_df")

        created = viewer.create_visualization({
            "type": "bar",
            "title": "Sales",
            "x_column": "month",
            "y_columns": ["sales"],
        })

        listing = viewer.list_visualizations()
        assert created["index"] == 0
        assert created["config"]["x_column"] == "month"
        assert listing["visualizations"][0]["config"]["title"] == "Sales"
        assert listing["sources"][0]["columns"] == ["month", "sales", "cost"]
        assert listing["sources"][0]["numeric_columns"] == ["sales", "cost"]

    def test_update_visualization_merges_and_normalizes_config(self, viewer, sales_df):
        viewer.display_dataframe(sales_df, "sales_df")
        viewer.create_visualization({"type": "bar", "x_column": "month", "y_columns": ["sales"]})

        updated = viewer.update_visualization(0, {
            "type": "line",
            "y_columns": ["cost"],
            "line_width": 50,
        })

        assert updated["config"]["type"] == "line"
        assert updated["config"]["x_column"] == "month"
        assert updated["config"]["y_columns"] == ["cost"]
        assert updated["config"]["line_width"] == 10

    def test_delete_and_export_visualization(self, viewer, sales_df, tmp_path):
        viewer.display_dataframe(sales_df, "sales_df")
        viewer.create_visualization({"type": "bar", "x_column": "month", "y_columns": ["sales"]})
        viewer._chart_pages[0]._image_bytes = b"png-bytes"

        export = viewer.export_visualization(0, str(tmp_path / "chart"))
        assert export["bytes"] == len(b"png-bytes")
        assert os.path.exists(export["path"])

        listing = viewer.delete_visualization(0)
        assert listing["visualizations"] == []


class TestResultsViewerGridStyle:
    """Tests for the compact SQL-result grid style."""

    @pytest.fixture
    def grid_zoom_settings(self):
        from PyQt6.QtCore import QSettings
        from src.ui.components.results_viewer import ResultsViewer

        settings = QSettings("DataPyn", "DataPyn")
        key = ResultsViewer.SETTINGS_KEY_GRID_FONT_SIZE
        previous = settings.value(key, None)
        settings.remove(key)
        yield settings
        if previous is None:
            settings.remove(key)
        else:
            settings.setValue(key, previous)

    @pytest.fixture
    def viewer(self, qtbot):
        from src.ui.components.results_viewer import ResultsViewer
        v = ResultsViewer()
        qtbot.addWidget(v)
        return v

    def test_model_displays_and_highlights_null_values(self):
        """Null-like scalar values should render as highlighted NULL cells."""
        from PyQt6.QtCore import Qt
        from src.ui.components.results_viewer import PandasModel

        model = PandasModel(pd.DataFrame({"name": [None, "Alice"], "amount": [float("nan"), 42]}))

        name_null = model.index(0, 0)
        amount_null = model.index(0, 1)
        normal_cell = model.index(1, 0)

        assert model.data(name_null, Qt.ItemDataRole.DisplayRole) == "NULL"
        assert model.data(amount_null, Qt.ItemDataRole.DisplayRole) == "NULL"
        assert model.data(name_null, Qt.ItemDataRole.BackgroundRole).name() == model._null_bg.name()
        assert model.data(name_null, Qt.ItemDataRole.ForegroundRole).name() == model._null_text.name()
        assert model.data(normal_cell, Qt.ItemDataRole.DisplayRole) == "Alice"
        assert model.data(normal_cell, Qt.ItemDataRole.BackgroundRole).name() != model._null_bg.name()

    def test_result_grid_restores_persisted_font_size(self, qtbot, grid_zoom_settings):
        """Results grid should restore the saved user zoom/font preference."""
        from src.ui.components.results_viewer import ResultsViewer

        grid_zoom_settings.setValue(ResultsViewer.SETTINGS_KEY_GRID_FONT_SIZE, 13)

        viewer = ResultsViewer()
        qtbot.addWidget(viewer)

        assert viewer.get_grid_font_size() == 13
        assert viewer.table_view.verticalHeader().defaultSectionSize() == 26
        assert "font-size: 16px" in viewer.table_view.styleSheet()

    def test_result_grid_font_size_persists_and_updates_primary(self, qtbot, grid_zoom_settings):
        """Changing Results zoom should persist and restyle the primary grid."""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        qtbot.addWidget(viewer)

        viewer.set_grid_font_size(12)

        assert grid_zoom_settings.value(ResultsViewer.SETTINGS_KEY_GRID_FONT_SIZE, type=int) == 12
        assert viewer.table_view.verticalHeader().defaultSectionSize() == 25
        assert "font-size: 15px" in viewer.table_view.styleSheet()

    def test_result_grid_zoom_wheel_changes_font_size(self, qtbot, grid_zoom_settings):
        """Ctrl+wheel handler should zoom the Results grid in one-point steps."""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        qtbot.addWidget(viewer)
        viewer.set_grid_font_size(9, persist=False)

        assert viewer._handle_result_zoom_wheel(120) is True
        assert viewer.get_grid_font_size() == 10
        assert grid_zoom_settings.value(ResultsViewer.SETTINGS_KEY_GRID_FONT_SIZE, type=int) == 10

        assert viewer._handle_result_zoom_wheel(-120) is True
        assert viewer.get_grid_font_size() == 9
        assert viewer._handle_result_zoom_wheel(0) is False

    def test_primary_result_grid_uses_compact_database_style(self, grid_zoom_settings, viewer):
        """The primary result grid should be dense, bordered and easy to scan."""
        df = pd.DataFrame({"id": [1, 2], "name": ["Alice", None]})

        viewer.display_dataframe(df, "result")
        stylesheet = viewer.table_view.styleSheet()

        assert viewer.table_view.showGrid() is True
        assert viewer.table_view.wordWrap() is False
        assert viewer.table_view.verticalHeader().defaultSectionSize() == 22
        assert viewer.table_view.horizontalHeader().minimumHeight() == 24
        assert "gridline-color: transparent" not in stylesheet
        assert "padding: 1px 6px" in stylesheet
        assert "font-size: 12px" in stylesheet

    def test_secondary_result_grid_reuses_compact_null_style(self, grid_zoom_settings, viewer):
        """Secondary multi-result tabs should keep the same compact/null styling."""
        from PyQt6.QtCore import Qt

        first = pd.DataFrame({"id": [1]})
        second = pd.DataFrame({"id": [2], "note": [None]})

        viewer.display_dataframes([("first", first), ("second", second)])
        page = viewer._result_tabs.widget(1)
        table_view = page._table_view
        model = page._model
        null_index = model.index(0, 1)

        assert table_view.showGrid() is True
        assert table_view.verticalHeader().defaultSectionSize() == 22
        assert "padding: 1px 6px" in table_view.styleSheet()
        assert model.data(null_index, Qt.ItemDataRole.DisplayRole) == "NULL"
        assert model.data(null_index, Qt.ItemDataRole.BackgroundRole).name() == model._null_bg.name()

    def test_result_grid_zoom_updates_secondary_tabs(self, viewer, grid_zoom_settings):
        """Existing secondary result tabs should receive the same zoom setting."""
        first = pd.DataFrame({"id": [1]})
        second = pd.DataFrame({"id": [2]})

        viewer.display_dataframes([("first", first), ("second", second)])
        viewer.set_grid_font_size(11)
        page = viewer._result_tabs.widget(1)

        assert page._table_view.verticalHeader().defaultSectionSize() == 24
        assert "font-size: 14px" in page._table_view.styleSheet()


class TestGridContextMenu:
    """Tests for the right-click context menu on the results grid."""

    @pytest.fixture
    def viewer(self, qtbot):
        from src.ui.components.results_viewer import ResultsViewer
        v = ResultsViewer()
        qtbot.addWidget(v)
        return v

    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame({
            "name": ["Alice", "Bob"],
            "age": [25, 30],
        })

    def test_copy_without_headers(self, viewer, sample_df):
        """Copy (Ctrl+C) should NOT include headers."""
        from PyQt6.QtWidgets import QApplication

        viewer.display_dataframe(sample_df)
        viewer._copy_to_clipboard(include_headers=False)

        text = QApplication.instance().clipboard().text()
        assert "name" not in text
        assert "age" not in text
        assert "Alice" in text
        assert "Bob" in text

    def test_copy_with_headers(self, viewer, sample_df):
        """Copy with Headers should include column names."""
        from PyQt6.QtWidgets import QApplication

        viewer.display_dataframe(sample_df)
        viewer._copy_to_clipboard(include_headers=True)

        text = QApplication.instance().clipboard().text()
        assert "name" in text
        assert "age" in text
        assert "Alice" in text

    def test_selection_copy_without_headers(self, viewer, sample_df, qtbot):
        """Selection copy without headers should have only data."""
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QItemSelectionModel

        viewer.display_dataframe(sample_df)
        model = viewer.table_view.model()
        sel_model = viewer.table_view.selectionModel()
        sel_model.select(model.index(0, 0), QItemSelectionModel.SelectionFlag.Select)

        viewer._copy_selection_to_clipboard(include_headers=False)

        text = QApplication.instance().clipboard().text()
        lines = text.strip().split("\n")
        assert len(lines) == 1
        assert "Alice" in lines[0]
        assert "name" not in text

    def test_selection_copy_with_headers(self, viewer, sample_df, qtbot):
        """Selection copy with headers should include column names as first line."""
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QItemSelectionModel

        viewer.display_dataframe(sample_df)
        model = viewer.table_view.model()
        sel_model = viewer.table_view.selectionModel()
        sel_model.select(model.index(0, 0), QItemSelectionModel.SelectionFlag.Select)

        viewer._copy_selection_to_clipboard(include_headers=True)

        text = QApplication.instance().clipboard().text()
        lines = text.strip().split("\n")
        assert len(lines) == 2
        assert "name" in lines[0]
        assert "Alice" in lines[1]

    def test_copy_with_semicolon_separator(self, viewer, sample_df, qtbot):
        """Copy should use the configured separator."""
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QSettings, QItemSelectionModel

        QSettings("DataPyn", "ExportSettings").setValue("copy_separator", ";")
        viewer.display_dataframe(sample_df)

        model = viewer.table_view.model()
        sel_model = viewer.table_view.selectionModel()
        for col in range(2):
            sel_model.select(model.index(0, col), QItemSelectionModel.SelectionFlag.Select)

        viewer._copy_selection_to_clipboard(include_headers=True)

        text = QApplication.instance().clipboard().text()
        lines = text.strip().split("\n")
        assert ";" in lines[0]
        assert ";" in lines[1]
        # cleanup
        QSettings("DataPyn", "ExportSettings").clear()

    def test_context_menu_policy_set(self, viewer):
        """Table view and headers should have custom context menu policy."""
        from PyQt6.QtCore import Qt
        assert viewer.table_view.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
        assert viewer.table_view.horizontalHeader().contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
        assert viewer.table_view.verticalHeader().contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu

    def test_settings_button_exists(self, viewer):
        """The export settings button should exist in the toolbar."""
        assert hasattr(viewer, "btn_export_settings")
        assert viewer.btn_export_settings is not None

    def test_excel_clipboard_always_has_headers(self, viewer, sample_df):
        """Excel clipboard copy should always include headers."""
        from PyQt6.QtWidgets import QApplication

        viewer.display_dataframe(sample_df)
        viewer.btn_export_dest_clipboard.setChecked(True)
        viewer._export_excel()

        text = QApplication.instance().clipboard().text()
        assert "name" in text
        assert "age" in text
        assert "Alice" in text


class TestResultsViewerMultiTab:
    """Tests for multi-result tabs (display_dataframes)."""

    @pytest.fixture
    def viewer(self, qtbot):
        from src.ui.components.results_viewer import ResultsViewer
        v = ResultsViewer()
        qtbot.addWidget(v)
        return v

    @pytest.fixture
    def df_a(self):
        return pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})

    @pytest.fixture
    def df_b(self):
        return pd.DataFrame({"x": ["foo", "bar"], "y": [10, 20]})

    @pytest.fixture
    def df_c(self):
        return pd.DataFrame({"k": [True, False, True, False]})

    def test_single_dataframe_keeps_tab_bar_visible(self, viewer, df_a):
        """display_dataframe() keeps the tab bar visible for chart actions."""
        viewer.display_dataframe(df_a, "df")
        assert viewer._result_tabs.count() == 1
        assert viewer._result_tabs.tabBar().isHidden() is False
        assert viewer.current_df is df_a

    def test_single_dataframe_tab_uses_result_label(self, viewer, df_a):
        """A single result tab should still use the block/result name."""
        viewer.display_dataframe(df_a, "green1")

        assert viewer._result_tabs.count() == 1
        assert viewer._result_tabs.tabText(0) == "green1"

    def test_display_dataframes_renders_primary_with_secondary_tabs(self, viewer, qtbot):
        """Primary tab must render even while secondary tabs prepare in parallel."""
        first = pd.DataFrame({"a": [1, 2, 3]})
        second = pd.DataFrame({"b": list(range(250))})
        viewer.display_dataframes([("first", first), ("second", second)])

        qtbot.waitUntil(lambda: viewer.model.rowCount() == len(first), timeout=5000)
        assert viewer._result_tabs.currentIndex() == 0
        assert viewer.table_view is viewer._primary_table_view
        assert viewer.model.data(viewer.model.index(0, 0)) == "1"

    def test_display_dataframes_creates_n_tabs(self, viewer, df_a, df_b, df_c):
        """display_dataframes() with N items creates N tabs and shows the bar."""
        viewer.display_dataframes([
            ("products", df_a),
            ("customers", df_b),
            ("orders", df_c),
        ])
        assert viewer._result_tabs.count() == 3
        assert viewer._result_tabs.tabBar().isHidden() is False
        assert viewer._result_tabs.tabText(0) == "products"
        assert viewer._result_tabs.tabText(1) == "customers"
        assert viewer._result_tabs.tabText(2) == "orders"
        # Active tab is the first one and current_df reflects it
        assert viewer._result_tabs.currentIndex() == 0
        assert viewer.current_df is df_a

    def test_display_dataframes_accepts_bare_dataframes(self, viewer, df_a, df_b):
        """Bare DataFrame items get auto-generated labels."""
        viewer.display_dataframes([df_a, df_b])
        assert viewer._result_tabs.count() == 2
        # Auto label uses the tab_label format key ("Result {n}" in en-US)
        assert "1" in viewer._result_tabs.tabText(0)
        assert "2" in viewer._result_tabs.tabText(1)

    def test_tab_change_swaps_current_df_and_table_view(self, viewer, df_a, df_b, qtbot):
        """Switching to a secondary tab updates current_df/table_view/model."""
        viewer.display_dataframes([("first", df_a), ("second", df_b)])

        primary_table_view = viewer.table_view
        _switch_result_tab(viewer, qtbot, 1, min_rows=len(df_b))

        assert viewer.current_df is df_b
        assert viewer.table_view is not primary_table_view
        assert viewer.model.rowCount() == len(df_b)

        _switch_result_tab(viewer, qtbot, 0, min_rows=len(df_a))
        assert viewer.current_df is df_a
        assert viewer.table_view is primary_table_view

    def test_single_display_dataframe_collapses_secondary_tabs(self, viewer, df_a, df_b, df_c):
        """A new single-result execution removes any leftover secondary tabs."""
        viewer.display_dataframes([("a", df_a), ("b", df_b), ("c", df_c)])
        assert viewer._result_tabs.count() == 3

        viewer.display_dataframe(df_a, "df")
        assert viewer._result_tabs.count() == 1
        assert viewer._result_tabs.tabBar().isHidden() is False
        # current_df points to the new primary df
        assert viewer.current_df is df_a

    def test_close_secondary_tab(self, viewer, df_a, df_b, df_c):
        """Closing a secondary tab removes it and keeps the primary."""
        viewer.display_dataframes([("a", df_a), ("b", df_b), ("c", df_c)])
        assert viewer._result_tabs.count() == 3

        viewer._on_result_tab_close_requested(1)
        assert viewer._result_tabs.count() == 2
        # Remaining tabs: primary ("a") and former "c"
        assert viewer._result_tabs.tabText(0) == "a"
        assert viewer._result_tabs.tabText(1) == "c"

    def test_result_tabs_use_painted_close_controls_with_session_tab_style(self, viewer, df_a, df_b):
        """Result tabs should paint close controls with the same style as main tabs."""

        viewer.display_dataframes([("a", df_a), ("b", df_b)])

        assert viewer._result_tabs.tabsClosable() is False
        stylesheet = viewer._result_tabs.styleSheet()
        assert "padding-right: 28px" in stylesheet
        for index in range(viewer._result_tabs.count()):
            rect = viewer._result_tabs.tabBar()._close_button_rect(index)
            assert rect.isValid()
            assert rect.width() == 20
            assert rect.height() == 20

    def test_result_tabs_use_connection_color_for_indicator(self, viewer, df_a, df_b):
        """Result tabs should use the active connection color instead of a fixed green border."""
        viewer.set_connection_color("#ff5733")
        viewer.display_dataframes([("a", df_a), ("b", df_b)])

        tab_bar = viewer._result_tabs.tabBar()
        stylesheet = viewer._result_tabs.styleSheet()

        assert tab_bar._connection_color == "#ff5733"
        assert "border-bottom: 3px solid transparent" in stylesheet
        assert "border-bottom: 3px solid #22c55e" not in stylesheet

    def test_set_session_resolves_connection_color(self, viewer):
        """Setting a session should sync the result tab color from the connection config."""
        session = MagicMock(connection_name="analytics", connection_group="Prod")
        manager = MagicMock()
        manager.get_connection_config.return_value = {"color": "#8b5cf6"}

        with patch("src.database.connection_manager.ConnectionManager", return_value=manager):
            viewer.set_session(session)

        manager.get_connection_config.assert_called_once_with("Prod", "analytics")
        assert viewer._connection_color == "#8b5cf6"
        assert viewer._result_tabs.tabBar()._connection_color == "#8b5cf6"

    def test_visualization_button_matches_result_tab_style(self, viewer):
        """The chart action should be a small flat tab-bar accessory control."""
        from src.design_system.tab_controls import TAB_ACCESSORY_BUTTON_SIZE, TAB_ACCESSORY_ICON_SIZE

        button = viewer.btn_visualization
        stylesheet = button.styleSheet()

        assert button.autoRaise() is True
        assert button.width() == TAB_ACCESSORY_BUTTON_SIZE
        assert button.height() == TAB_ACCESSORY_BUTTON_SIZE
        assert button.iconSize().width() == TAB_ACCESSORY_ICON_SIZE
        assert "border: none" in stylesheet
        assert "background: transparent" in stylesheet

    def test_reusable_tab_close_helper_styles_buttons(self, viewer, qtbot):
        """Shared tab close helper should provide the same icon and hover style."""
        from PyQt6.QtWidgets import QToolButton
        from src.design_system.tab_controls import style_tab_close_button

        button = QToolButton()
        qtbot.addWidget(button)

        style_tab_close_button(button)

        assert button.property("datapynTabCloseButton") is True
        assert button.icon().isNull() is False
        assert button.width() == 20
        assert "rgba(239, 68, 68, 0.20)" in button.styleSheet()

    def test_painted_close_button_removes_secondary_tab(self, viewer, df_a, df_b, qtbot):
        """Clicking a secondary painted close button removes that tab."""
        from PyQt6.QtCore import Qt

        viewer.display_dataframes([("a", df_a), ("b", df_b)])
        tab_bar = viewer._result_tabs.tabBar()
        close_rect = tab_bar._close_button_rect(1)

        qtbot.mouseClick(tab_bar, Qt.MouseButton.LeftButton, pos=close_rect.center())
        qtbot.waitUntil(lambda: viewer._result_tabs.count() == 1, timeout=1000)

        assert viewer._result_tabs.count() == 1
        assert viewer._result_tabs.tabText(0) == "a"

    def test_painted_close_button_on_primary_clears_results(self, viewer, df_a, df_b, qtbot):
        """Clicking the primary painted close button clears instead of removing the stack tab."""
        from PyQt6.QtCore import Qt

        viewer.display_dataframes([("a", df_a), ("b", df_b)])
        tab_bar = viewer._result_tabs.tabBar()
        close_rect = tab_bar._close_button_rect(0)

        qtbot.mouseClick(tab_bar, Qt.MouseButton.LeftButton, pos=close_rect.center())
        qtbot.waitUntil(lambda: viewer.current_df is None, timeout=1000)

        assert viewer._result_tabs.count() == 1
        assert viewer.current_df is None
        assert viewer._result_tabs.tabBar().isHidden() is False

    def test_close_primary_tab_clears_all(self, viewer, df_a, df_b):
        """Closing primary tab clears results and collapses secondaries."""
        viewer.display_dataframes([("a", df_a), ("b", df_b)])
        assert viewer._result_tabs.count() == 2

        viewer._on_result_tab_close_requested(0)

        # Primary tab is preserved (hosts the stack) but content is cleared
        assert viewer._result_tabs.count() == 1
        assert viewer.current_df is None
        assert viewer._result_tabs.tabBar().isHidden() is False

    def test_clear_collapses_to_primary(self, viewer, df_a, df_b):
        """clear() drops secondary tabs and resets primary state."""
        viewer.display_dataframes([("a", df_a), ("b", df_b)])
        viewer.clear()
        assert viewer._result_tabs.count() == 1
        assert viewer._result_tabs.tabBar().isHidden() is False
        assert viewer.current_df is None

    def test_display_dataframes_empty_is_noop(self, viewer):
        """Empty items list should not change state."""
        viewer.display_dataframes([])
        assert viewer._result_tabs.count() == 1
        assert viewer._result_tabs.tabBar().isHidden() is False
        assert viewer.current_df is None


class TestResultsViewerEmptyGrid:
    """Empty result sets must render column headers with zero rows."""

    @pytest.fixture
    def viewer(self, qtbot):
        from src.ui.components.results_viewer import ResultsViewer
        v = ResultsViewer()
        qtbot.addWidget(v)
        return v

    def test_empty_with_columns_renders_headers(self, viewer):
        from PyQt6.QtCore import Qt

        df = pd.DataFrame(columns=["id", "name"])
        viewer.display_dataframe(df, "result")

        model = viewer.model
        assert model.columnCount() == 2
        assert model.rowCount() == 0
        assert model.headerData(0, Qt.Orientation.Horizontal) == "id"
        assert model.headerData(1, Qt.Orientation.Horizontal) == "name"

    def test_clear_resets_to_empty(self, viewer):
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        viewer.display_dataframe(df, "result")
        assert viewer.model.rowCount() == 3

        viewer.clear()
        assert viewer.current_df is None
        assert viewer.model.rowCount() == 0


class TestResultsViewerFiltering:
    """Tests for the ResultsViewer grid filter."""

    @pytest.fixture
    def viewer(self, qtbot):
        from src.ui.components.results_viewer import ResultsViewer
        v = ResultsViewer()
        qtbot.addWidget(v)
        return v

    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame({
            "nome": ["Alice", "Bob", "Carla", "Daniel"],
            "idade": [25, 30, 35, 40],
            "cidade": ["Sao Paulo", "Rio", "Belo Horizonte", "Curitiba"],
        })

    def test_toolbar_filter_controls_are_removed(self, viewer):
        """The redundant toolbar filter controls should not be part of Results anymore."""
        from PyQt6.QtWidgets import QLineEdit
        from src.language import S

        assert not hasattr(viewer, "filter_column_combo")
        assert not hasattr(viewer, "filter_edit")
        assert not hasattr(viewer, "btn_clear_filter")
        assert all(line_edit.placeholderText() != S.results.filter_placeholder for line_edit in viewer.toolbar.findChildren(QLineEdit))

    def test_column_filter_matches_text_case_insensitively(self, viewer, sample_df):
        """Column filters should remain available through the header menu flow."""
        viewer.display_dataframe(sample_df, "clientes")

        viewer._set_column_filter("cidade", "rio")

        assert viewer.model.rowCount() == 1
        assert list(viewer.current_df["nome"]) == ["Bob"]
        assert "1 of 4" in viewer.info_label.text()

    def test_clear_filter_restores_original_rows(self, viewer, sample_df):
        """Clearing filters should restore the active DataFrame view."""
        viewer.display_dataframe(sample_df, "clientes")
        viewer._set_column_filter("nome", "carla")
        assert viewer.model.rowCount() == 1

        viewer._clear_grid_filter()

        assert viewer._column_filters == {}
        assert viewer.model.rowCount() == len(sample_df)
        assert viewer.current_df is sample_df

    def test_column_filter_stays_limited_to_selected_column(self, viewer, sample_df):
        """Column filtering should stop matches from other columns leaking in."""
        viewer.display_dataframe(sample_df, "clientes")

        viewer._set_column_filter("cidade", "30")

        assert viewer.model.rowCount() == 0
        assert viewer.current_df.empty

    def test_column_filter_is_applied_when_switching_multi_result_tabs(self, viewer, qtbot):
        """Column filters should apply to whichever result tab is active."""
        products = pd.DataFrame({"name": ["desk", "chair"], "sku": ["P01", "P02"]})
        customers = pd.DataFrame({"name": ["Foo Store", "Bar Market"], "city": ["Santos", "Recife"]})

        viewer.display_dataframes([("products", products), ("customers", customers)])
        viewer._set_column_filter("name", "foo")
        assert viewer.model.rowCount() == 0

        _switch_result_tab(viewer, qtbot, 1, min_rows=1)

        assert list(viewer.current_df["name"]) == ["Foo Store"]
        assert "customers" in viewer.info_label.text()

    def test_row_limit_keeps_multi_result_tabs_and_active_column_filter(self, viewer, qtbot):
        """Changing the row limit should not collapse multi-result tabs."""
        first = pd.DataFrame({"name": [f"first-{i}" for i in range(14)]})
        second = pd.DataFrame({"name": [f"keep-{i}" for i in range(12)] + ["drop-a", "drop-b"]})

        viewer.display_dataframes([("first", first), ("second", second)])
        _switch_result_tab(viewer, qtbot, 1)
        viewer._set_column_filter("name", "keep")

        viewer.row_limit_spin.setValue(10)
        viewer._on_row_limit_changed(10)

        assert viewer._result_tabs.count() == 2
        assert viewer._result_tabs.currentIndex() == 1
        assert viewer.model.rowCount() == 10
        assert len(viewer.current_df) == 12

    def _filter_chip_buttons(self, viewer):
        from PyQt6.QtWidgets import QToolButton
        buttons = []
        for index in range(viewer.filter_chip_layout.count()):
            widget = viewer.filter_chip_layout.itemAt(index).widget()
            if isinstance(widget, QToolButton):
                buttons.append(widget)
        return buttons

    def test_result_grid_uses_header_with_column_menu_target(self, viewer, sample_df):
        """The grid header should expose a per-column menu target."""
        from src.ui.components.results_viewer import ResultGridHeader

        viewer.display_dataframe(sample_df, "clientes")

        assert isinstance(viewer.table_view.horizontalHeader(), ResultGridHeader)

    def test_column_menu_button_is_visible_only_for_hovered_section(self, viewer, sample_df):
        """The column menu target should not be painted on every header all the time."""
        viewer.display_dataframe(sample_df, "clientes")
        header = viewer.table_view.horizontalHeader()

        assert header.is_menu_button_visible(0) is False

        header._set_hovered_section(0)

        assert header.is_menu_button_visible(0) is True
        assert header.is_menu_button_visible(1) is False

        header._set_hovered_section(-1)
        assert header.is_menu_button_visible(0) is False

    def test_column_menu_is_separate_from_grid_export_menu(self, viewer, sample_df):
        """Column menu should contain only filter/format actions, not grid export actions."""
        from src.language import S

        viewer.display_dataframe(sample_df, "clientes")
        menu = viewer._create_column_menu("cidade")
        action_texts = [action.text() for action in menu.actions()]

        assert action_texts == [S.results.ctx_filter_column, S.results.ctx_format_column]
        assert S.results.btn_csv not in action_texts
        assert S.results.btn_excel not in action_texts
        assert S.results.ctx_copy not in action_texts
        assert menu.actions()[1].menu() is not None

    def test_column_filter_adds_chip_and_filters_column(self, viewer, sample_df):
        """Applying a column filter should filter rows and show a removable chip."""
        viewer.display_dataframe(sample_df, "clientes")

        viewer._set_column_filter("cidade", "rio")

        assert viewer.model.rowCount() == 1
        assert list(viewer.current_df["nome"]) == ["Bob"]
        assert viewer.filter_chip_bar.isHidden() is False
        assert any("cidade" in button.text() and "rio" in button.text() for button in self._filter_chip_buttons(viewer))

    def test_column_filter_chip_removes_filter(self, viewer, sample_df):
        """Clicking a filter chip should remove that column filter."""
        viewer.display_dataframe(sample_df, "clientes")
        viewer._set_column_filter("cidade", "rio")
        chip = self._filter_chip_buttons(viewer)[0]

        chip.click()

        assert "cidade" not in viewer._column_filters
        assert viewer.model.rowCount() == len(sample_df)
        assert viewer.current_df is sample_df
        assert viewer.filter_chip_bar.isHidden() is True

    def test_column_filters_are_combined(self, viewer):
        """Multiple column filters should narrow the visible rows together."""
        df = pd.DataFrame({
            "nome": ["Ana", "Ana", "Bia"],
            "cidade": ["Rio", "Sao Paulo", "Rio"],
        })
        viewer.display_dataframe(df, "clientes")

        viewer._set_column_filter("nome", "ana")
        viewer._set_column_filter("cidade", "rio")

        assert viewer.model.rowCount() == 1
        assert list(viewer.current_df["cidade"]) == ["Rio"]
        assert len(self._filter_chip_buttons(viewer)) == 2

    def test_column_filter_popup_sets_selected_column(self, viewer, sample_df):
        """The column filter popup should store the entered value as a column filter."""
        from PyQt6.QtCore import Qt, QPoint
        from PyQt6.QtWidgets import QLineEdit, QPushButton

        viewer.display_dataframe(sample_df, "clientes")
        popup = viewer._show_column_filter_popup("cidade", viewer.mapToGlobal(QPoint(0, 0)))
        input_edit = popup.findChild(QLineEdit, "columnFilterInput")
        apply_button = popup.findChild(QPushButton, "columnFilterApply")

        assert popup.windowFlags() & Qt.WindowType.Popup
        assert input_edit is not None
        assert apply_button is not None

        input_edit.setText("Rio")
        apply_button.click()

        assert viewer._column_filters["cidade"]["value"] == "Rio"
        assert viewer.model.rowCount() == 1

    def test_column_filter_popup_clear_removes_filter(self, viewer, sample_df):
        """The popup clear button should remove the active column filter."""
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QPushButton

        viewer.display_dataframe(sample_df, "clientes")
        viewer._set_column_filter("cidade", "Rio")
        popup = viewer._show_column_filter_popup("cidade", viewer.mapToGlobal(QPoint(0, 0)))
        clear_button = popup.findChild(QPushButton, "columnFilterClear")

        assert clear_button is not None
        clear_button.click()

        assert "cidade" not in viewer._column_filters
        assert viewer.model.rowCount() == len(sample_df)

    def test_column_format_changes_display_without_changing_dataframe(self, viewer):
        """Column format should affect the grid display only."""
        df = pd.DataFrame({"valor": [1234.5], "taxa": [0.125]})
        viewer.display_dataframe(df, "valores")

        viewer._set_column_format("valor", "currency")
        viewer._set_column_format("taxa", "percent")

        assert viewer.model.data(viewer.model.index(0, 0)) == "$ 1,234.50"
        assert viewer.model.data(viewer.model.index(0, 1)) == "12.50%"
        assert viewer.current_df is df

        viewer._set_column_format("valor", "default")
        assert viewer.model.data(viewer.model.index(0, 0)) == "1234.5"

    def test_column_format_persists_to_session_and_reapplies_when_column_returns(self, viewer):
        """Column formats should be session state and survive unrelated results."""
        from src.core.session import Session

        session = Session("s1")
        viewer.set_session(session)
        df_values = pd.DataFrame({"valor": [1234.567]})
        viewer.display_dataframe(df_values, "valores")

        viewer._set_column_format("valor", {"type": "currency", "prefix": "R$ ", "decimals": 1})

        assert session.result_view_state["column_formats"]["valor"]["prefix"] == "R$ "
        assert viewer.model.data(viewer.model.index(0, 0)) == "R$ 1,234.6"

        viewer.display_dataframe(pd.DataFrame({"outro": [1]}), "outro")
        viewer.display_dataframe(df_values, "valores")

        assert viewer.model.data(viewer.model.index(0, 0)) == "R$ 1,234.6"

    def test_numeric_column_filter_uses_interval(self, viewer):
        """Numeric column filters should use min/max ranges."""
        df = pd.DataFrame({"valor": [5, 10, 15, 20, 25]})
        viewer.display_dataframe(df, "valores")

        viewer._set_column_filter("valor", {"type": "number", "min": "10", "max": "20"})

        assert list(viewer.current_df["valor"]) == [10, 15, 20]
        assert viewer.model.rowCount() == 3

    def test_boolean_column_filter_uses_boolean_value(self, viewer):
        """Boolean column filters should match true/false values."""
        df = pd.DataFrame({"ativo": [True, False, True], "nome": ["A", "B", "C"]})
        viewer.display_dataframe(df, "clientes")

        viewer._set_column_filter("ativo", {"type": "bool", "value": True})

        assert list(viewer.current_df["nome"]) == ["A", "C"]
        assert viewer.model.rowCount() == 2

    def _tiny_png_bytes(self) -> bytes:
        from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
        from PyQt6.QtGui import QColor, QImage

        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image = QImage(2, 2, QImage.Format.Format_ARGB32)
        image.fill(QColor("#4f8cff"))
        image.save(buffer, "PNG")
        return bytes(byte_array)

    def _tiny_chart_html(self) -> str:
        """Minimal Plotly-style HTML payload for chart render mocks."""
        return "<html><body><div id='chart' style='width:640px;height:360px'>ok</div></body></html>"

    def test_visualization_button_and_config_are_session_state(self, viewer, qtbot, monkeypatch):
        """Chart configuration should create a Results tab and live in session state."""
        from src.core.session import Session

        chart_html = self._tiny_chart_html()
        monkeypatch.setattr(viewer, "_render_chart_image", lambda *_: chart_html)

        session = Session("s1")
        viewer.set_session(session)
        viewer.display_dataframe(pd.DataFrame({"mes": ["Jan"], "valor": [10]}), "vendas")

        assert viewer._result_tabs.tabBar().isHidden() is False
        assert viewer.btn_visualization.toolTip()

        viewer._set_visualization_config({
            "type": "bar",
            "x_column": "mes",
            "y_columns": ["valor"],
            "group_by": "",
            "stacking": "none",
            "normalize": False,
            "nulls": "zero",
        })

        assert viewer._result_tabs.count() == 2
        chart_page = viewer._result_tabs.widget(1)
        assert chart_page._page_kind == "chart"
        qtbot.waitUntil(lambda: _chart_page_ready(chart_page), timeout=5000)
        assert chart_page._chart_html or chart_page._image_bytes
        chart_view = getattr(chart_page, "_chart_view", None)
        assert chart_view is not None
        assert session.result_view_state["charts"]["configs"][0]["x_column"] == "mes"
        assert session.result_view_state["charts"]["configs"][0]["y_columns"] == ["valor"]

    def test_visualization_editor_tabs_have_working_controls(self, viewer, qtbot):
        """Visualization editor tabs should expose real controls, not blank placeholders."""
        from PyQt6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QPushButton, QSpinBox, QWidget
        from src.ui.components.results_viewer import VisualizationEditorDialog

        df = pd.DataFrame({"mes": ["Jan", "Fev"], "valor": [10, 20], "canal": ["A", "B"]})
        dialog = VisualizationEditorDialog(df, {}, parent=viewer, theme_manager=viewer.theme_manager)
        qtbot.addWidget(dialog)

        assert dialog.findChild(QWidget, "visualizationXAxisTab") is not None
        assert dialog.findChild(QWidget, "visualizationYAxisTab") is not None
        assert dialog.findChild(QWidget, "visualizationSeriesTab") is not None
        assert dialog.findChild(QWidget, "visualizationColorsTab") is not None
        assert dialog.findChild(QWidget, "visualizationStyleTab") is not None
        assert dialog.findChild(QWidget, "visualizationDataLabelsTab") is not None

        x_combo = dialog.findChild(QComboBox, "visualizationXColumnCombo")
        palette_combo = dialog.findChild(QComboBox, "visualizationPaletteCombo")
        labels_check = dialog.findChild(QCheckBox, "visualizationDataLabelsCheck")
        add_y_button = dialog.findChild(QPushButton, "visualizationAddYButton")
        text_color_edit = dialog.findChild(QLineEdit, "visualizationTextColorInput")
        label_color_edit = dialog.findChild(QLineEdit, "visualizationLabelColorInput")
        show_grid_check = dialog.findChild(QCheckBox, "visualizationShowGridCheck")
        line_style_combo = dialog.findChild(QComboBox, "visualizationLineStyleCombo")
        line_width_spin = dialog.findChild(QSpinBox, "visualizationLineWidthSpin")
        bar_opacity_spin = dialog.findChild(QSpinBox, "visualizationBarOpacitySpin")

        assert x_combo.count() == 4
        assert palette_combo.findData("warm") >= 0

        before = len(dialog._y_column_combos)
        add_y_button.click()
        labels_check.setChecked(True)
        palette_combo.setCurrentIndex(palette_combo.findData("warm"))
        text_color_edit.setText("#eeeeee")
        label_color_edit.setText("#ffdd55")
        show_grid_check.setChecked(False)
        line_style_combo.setCurrentIndex(line_style_combo.findData("dashed"))
        line_width_spin.setValue(4)
        bar_opacity_spin.setValue(55)

        config = dialog.get_config()
        assert len(dialog._y_column_combos) == before + 1
        assert config["palette"] == "warm"
        assert config["show_data_labels"] is True
        assert config["text_color"] == "#eeeeee"
        assert config["label_color"] == "#ffdd55"
        assert config["show_grid"] is False
        assert config["line_style"] == "dashed"
        assert config["line_width"] == 4
        assert config["bar_opacity"] == 55
        assert config["x_column"] == "mes"
        assert config["y_columns"]

    def test_visualization_editor_window_has_only_close_button(self, viewer, qtbot):
        """Visualization editor should not expose minimize/maximize window controls."""
        from PyQt6.QtCore import Qt
        from src.ui.components.results_viewer import VisualizationEditorDialog

        df = pd.DataFrame({"mes": ["Jan"], "valor": [10]})
        dialog = VisualizationEditorDialog(df, {}, parent=viewer, theme_manager=viewer.theme_manager)
        qtbot.addWidget(dialog)

        flags = dialog.windowFlags()
        assert bool(flags & Qt.WindowType.CustomizeWindowHint) is True
        assert bool(flags & Qt.WindowType.WindowCloseButtonHint) is True
        assert bool(flags & Qt.WindowType.WindowMinimizeButtonHint) is False
        assert bool(flags & Qt.WindowType.WindowMaximizeButtonHint) is False
        assert bool(flags & Qt.WindowType.WindowMinMaxButtonsHint) is False

    def test_chart_tokens_use_flat_app_surface(self, viewer):
        """Default chart colors should avoid the framed matplotlib panel look."""
        from src.design_system.tokens import get_chart_colors

        chart_colors = get_chart_colors()

        assert chart_colors.axes_bg == chart_colors.figure_bg
        assert chart_colors.axes_edge != chart_colors.axes_bg

    def test_cartesian_chart_style_removes_matplotlib_frame(self, viewer):
        """Cartesian charts should render with a dashboard-style frameless axis."""
        from matplotlib.figure import Figure

        figure = Figure()
        axis = figure.add_subplot(111)

        viewer._style_cartesian_axis(axis, ["Jan", "Fev", "Mar"], {"type": "bar", "x_column": "mes"})

        assert all(not spine.get_visible() for spine in axis.spines.values())
        assert axis.xaxis.get_tick_params()["length"] == 0
        assert axis.yaxis.get_tick_params()["length"] == 0

    def test_cartesian_chart_style_honors_axis_and_text_colors(self, viewer):
        """Axis style options should affect text colors and optional axis lines."""
        from matplotlib.colors import to_hex
        from matplotlib.figure import Figure

        figure = Figure()
        axis = figure.add_subplot(111)

        viewer._style_cartesian_axis(
            axis,
            ["Jan", "Fev"],
            {
                "type": "bar",
                "x_column": "mes",
                "text_color": "#ff00ff",
                "axis_color": "#abcdef",
                "show_axis_line": True,
                "show_grid": False,
            },
        )

        assert axis.xaxis.label.get_color() == "#ff00ff"
        assert axis.yaxis.label.get_color() == "#ff00ff"
        assert axis.spines["left"].get_visible() is True
        assert axis.spines["bottom"].get_visible() is True
        assert to_hex(axis.spines["left"].get_edgecolor()) == "#abcdef"

    def test_line_chart_can_hide_line_and_keep_markers(self, viewer):
        """Line charts should support marker-only rendering."""
        from matplotlib.figure import Figure

        figure = Figure()
        axis = figure.add_subplot(111)
        data = pd.DataFrame({"valor": [10, 20, 15]})

        viewer._plot_cartesian_chart(
            axis,
            data,
            ["Jan", "Fev", "Mar"],
            {"type": "line", "show_line": False, "show_markers": True, "marker_size": 6},
            ["#22c55e"],
        )

        assert len(axis.lines) == 0
        assert len(axis.collections) == 1

    def test_bar_chart_applies_configured_opacity(self, viewer):
        """Bar opacity should be configurable per chart."""
        from matplotlib.figure import Figure
        import numpy as np

        figure = Figure()
        axis = figure.add_subplot(111)
        data = pd.DataFrame({"valor": [10, 20]})

        viewer._plot_bar_chart(axis, data, np.array([0, 1]), ["valor"], {"bar_opacity": 45}, ["#22c55e"], False)

        assert axis.patches[0].get_alpha() == 0.45

    def test_visualization_config_normalizes_style_options(self, viewer):
        """Persisted chart configs should keep valid style settings and discard invalid colors."""
        df = pd.DataFrame({"mes": ["Jan", "Fev"], "valor": [10, 20]})

        config = viewer._normalize_visualization_config(
            {
                "type": "line",
                "x_column": "mes",
                "y_columns": ["valor"],
                "text_color": "#eeeeee",
                "label_color": "not-a-color",
                "grid_color": "#123456",
                "show_grid": False,
                "show_axis_line": True,
                "show_line": False,
                "show_markers": True,
                "line_style": "dotted",
                "line_width": 20,
                "marker_size": 0,
                "bar_opacity": 5,
                "area_opacity": 95,
            },
            df,
            "vendas",
        )

        assert config["text_color"] == "#eeeeee"
        assert config["label_color"] == ""
        assert config["grid_color"] == "#123456"
        assert config["show_grid"] is False
        assert config["show_axis_line"] is True
        assert config["show_line"] is False
        assert config["show_markers"] is True
        assert config["line_style"] == "dotted"
        assert config["line_width"] == 10
        assert config["marker_size"] == 1
        assert config["bar_opacity"] == 10
        assert config["area_opacity"] == 90

    def test_visualization_editor_tabs_have_comfortable_padding(self, viewer, qtbot):
        """Visualization editor tab content should not sit flush against the pane border."""
        from PyQt6.QtWidgets import QWidget
        from src.ui.components.results_viewer import VisualizationEditorDialog

        df = pd.DataFrame({"mes": ["Jan"], "valor": [10]})
        dialog = VisualizationEditorDialog(df, {}, parent=viewer, theme_manager=viewer.theme_manager)
        qtbot.addWidget(dialog)

        for object_name in ["visualizationGeneralTab", "visualizationXAxisTab", "visualizationYAxisTab"]:
            tab = dialog.findChild(QWidget, object_name)
            margins = tab.layout().contentsMargins()
            assert margins.left() >= 20
            assert margins.top() >= 18
            assert tab.layout().spacing() >= 16

    def test_visualization_config_updates_active_chart_tab(self, viewer, qtbot):
        """Editing an active chart should update the chart tab instead of creating another one."""
        df = pd.DataFrame({"mes": ["Jan", "Fev"], "valor": [10, 20]})
        viewer.display_dataframe(df, "vendas")

        viewer._set_visualization_config({
            "type": "bar",
            "title": "Vendas",
            "x_column": "mes",
            "y_columns": ["valor"],
        })
        assert viewer._result_tabs.count() == 2
        chart_page = viewer._result_tabs.widget(1)
        qtbot.waitUntil(lambda: _chart_page_ready(chart_page), timeout=5000)

        viewer._set_visualization_config({
            "type": "line",
            "title": "Vendas por mes",
            "x_column": "mes",
            "y_columns": ["valor"],
            "show_data_labels": True,
        })

        assert viewer._result_tabs.count() == 2
        assert viewer._chart_configs[0]["type"] == "line"
        assert viewer._chart_configs[0]["title"] == "Vendas por mes"
        assert viewer._result_tabs.tabText(1) == "Vendas por mes"
        qtbot.waitUntil(lambda: not getattr(chart_page, "_rendering", False), timeout=5000)

    def test_chart_render_request_while_busy_finishes_without_stuck_status(self, viewer, qtbot, monkeypatch):
        """A chart edited during render should queue one fresh render and clear the rendering status."""
        import threading

        png_bytes = self._tiny_png_bytes()

        first_render_started = threading.Event()
        release_first_render = threading.Event()
        render_titles = []

        def fake_render(_df, config):
            render_titles.append(config.get("title", ""))
            if len(render_titles) == 1:
                first_render_started.set()
                if not release_first_render.wait(30):
                    raise RuntimeError("render was not released")
            return png_bytes

        monkeypatch.setattr(viewer, "_render_chart_image", fake_render)
        viewer.display_dataframe(pd.DataFrame({"mes": ["Jan", "Fev"], "valor": [10, 20]}), "vendas")
        viewer._set_visualization_config({"type": "bar", "title": "First", "x_column": "mes", "y_columns": ["valor"]})
        chart_page = viewer._result_tabs.widget(1)

        qtbot.waitUntil(first_render_started.is_set, timeout=3000)
        viewer._set_visualization_config({"type": "bar", "title": "Second", "x_column": "mes", "y_columns": ["valor"]})
        assert getattr(chart_page, "_render_pending", False) is True

        release_first_render.set()
        qtbot.waitUntil(
            lambda: len(render_titles) >= 2
            and _chart_page_ready(chart_page)
            and not chart_page._rendering,
            timeout=5000,
        )

        assert render_titles[:2] == ["First", "Second"]
        assert chart_page._status_label.isVisible() is False

    def test_replacing_results_while_chart_renders_does_not_restart_deleted_page(self, viewer, qtbot, monkeypatch):
        """Refreshing query results while a chart renders should retire the old chart page safely."""
        import threading
        from src.core.session import Session

        png_bytes = self._tiny_png_bytes()
        render_started = threading.Event()
        release_render = threading.Event()

        def fake_render(_df, _config):
            render_started.set()
            if not release_render.wait(30):
                raise RuntimeError("render was not released")
            return png_bytes

        monkeypatch.setattr(viewer, "_render_chart_image", fake_render)
        session = Session("s1")
        session.result_view_state = {
            "charts": {
                "active_index": 0,
                "configs": [{"type": "area", "x_column": "bairro", "y_columns": ["valor"], "source_label": "df1"}],
            }
        }
        viewer.set_session(session)
        first_df = pd.DataFrame({"produto": range(3), "valor": [1, 2, 3]})
        second_df = pd.DataFrame({"bairro": ["A", "B", "C"], "valor": [1, 2, 3]})
        items = [("df", first_df), ("df1", second_df)]

        viewer.display_dataframes(items)
        old_chart_page = viewer._result_tabs.widget(2)
        viewer._result_tabs.setCurrentIndex(2)
        qtbot.waitUntil(lambda: viewer._pending_result_tab_index is None, timeout=5000)
        qtbot.waitUntil(render_started.is_set, timeout=3000)

        viewer.display_dataframes(items)

        assert getattr(old_chart_page, "_disposed", False) is True
        assert old_chart_page not in viewer._chart_pages
        assert old_chart_page not in viewer._chart_render_queue
        assert viewer._result_tabs.count() == 3

        release_render.set()
        qtbot.waitUntil(lambda: viewer._active_chart_render_job is None, timeout=5000)

    def test_closing_chart_tab_while_rendering_retires_page_safely(self, viewer, qtbot, monkeypatch):
        """Clicking a chart tab close button during render should not leave live page references."""
        import threading
        from PyQt6.QtWidgets import QTabBar

        png_bytes = self._tiny_png_bytes()
        render_started = threading.Event()
        release_render = threading.Event()

        def fake_render(_df, _config):
            render_started.set()
            if not release_render.wait(30):
                raise RuntimeError("render was not released")
            return png_bytes

        monkeypatch.setattr(viewer, "_render_chart_image", fake_render)
        viewer.display_dataframe(pd.DataFrame({"mes": ["Jan", "Fev"], "valor": [10, 20]}), "vendas")
        viewer._set_visualization_config({"type": "bar", "title": "Close me", "x_column": "mes", "y_columns": ["valor"]})
        chart_page = viewer._result_tabs.widget(1)
        qtbot.waitUntil(render_started.is_set, timeout=3000)

        from PyQt6.QtCore import Qt

        tab_bar = viewer._result_tabs.tabBar()
        qtbot.mouseClick(tab_bar, Qt.MouseButton.LeftButton, pos=tab_bar._close_button_rect(1).center())
        qtbot.waitUntil(lambda: viewer._result_tabs.count() == 1, timeout=1000)

        assert viewer._result_tabs.count() == 1
        assert getattr(chart_page, "_disposed", False) is True
        assert chart_page not in viewer._chart_pages
        assert chart_page not in viewer._chart_render_queue

        release_render.set()
        qtbot.waitUntil(lambda: viewer._active_chart_render_job is None, timeout=5000)

    def test_chart_renders_are_serialized_across_pages(self, viewer, qtbot, monkeypatch):
        """Only one matplotlib chart render should run at a time."""
        import threading

        png_bytes = self._tiny_png_bytes()
        first_render_started = threading.Event()
        release_first_render = threading.Event()
        render_titles = []

        def fake_render(_df, config):
            render_titles.append(config.get("title", ""))
            if len(render_titles) == 1:
                first_render_started.set()
                if not release_first_render.wait(30):
                    raise RuntimeError("render was not released")
            return png_bytes

        monkeypatch.setattr(viewer, "_render_chart_image", fake_render)
        viewer.display_dataframe(pd.DataFrame({"mes": ["Jan", "Fev"], "valor": [10, 20]}), "vendas")
        viewer._set_visualization_config({"type": "bar", "title": "First", "x_column": "mes", "y_columns": ["valor"]})
        first_page = viewer._result_tabs.widget(1)
        qtbot.waitUntil(first_render_started.is_set, timeout=3000)

        viewer._result_tabs.setCurrentIndex(0)
        viewer._set_visualization_config({"type": "line", "title": "Second", "x_column": "mes", "y_columns": ["valor"]})
        second_page = viewer._result_tabs.widget(2)
        qtbot.waitUntil(
            lambda: viewer._pending_result_tab_index is None and second_page._render_pending,
            timeout=5000,
        )

        assert render_titles == ["First"]
        assert first_page._rendering is True
        assert second_page._render_pending is True
        assert second_page in viewer._chart_render_queue

        release_first_render.set()
        qtbot.waitUntil(
            lambda: render_titles == ["First", "Second"]
            and _chart_page_ready(second_page),
            timeout=5000,
        )

    def test_collapse_to_primary_discards_queued_chart_pages(self, viewer, qtbot, monkeypatch):
        """Clearing result tabs should remove queued chart renders for pages that no longer exist."""
        import threading

        png_bytes = self._tiny_png_bytes()
        first_render_started = threading.Event()
        release_first_render = threading.Event()

        def fake_render(_df, _config):
            if not first_render_started.is_set():
                first_render_started.set()
                if not release_first_render.wait(30):
                    raise RuntimeError("render was not released")
            return png_bytes

        monkeypatch.setattr(viewer, "_render_chart_image", fake_render)
        try:
            viewer.display_dataframe(pd.DataFrame({"mes": ["Jan", "Fev"], "valor": [10, 20]}), "vendas")
            viewer._set_visualization_config({"type": "bar", "title": "First", "x_column": "mes", "y_columns": ["valor"]})
            qtbot.waitUntil(first_render_started.is_set, timeout=3000)

            viewer._result_tabs.setCurrentIndex(0)
            viewer._set_visualization_config({"type": "line", "title": "Second", "x_column": "mes", "y_columns": ["valor"]})
            second_page = viewer._result_tabs.widget(2)
            qtbot.waitUntil(lambda: viewer._pending_result_tab_index is None, timeout=5000)
            if second_page not in viewer._chart_render_queue:
                viewer._render_visualization_page(second_page)

            assert viewer._chart_render_queue

            viewer._collapse_to_primary()

            assert viewer._chart_pages == []
            assert viewer._chart_render_queue == []
        finally:
            release_first_render.set()
        qtbot.waitUntil(lambda: viewer._active_chart_render_job is None, timeout=5000)

    def test_saved_visualization_config_restores_chart_tab_for_new_results(self, viewer, qtbot, monkeypatch):
        """Saved chart configs should become result tabs when matching data is displayed."""
        from src.core.session import Session

        chart_html = self._tiny_chart_html()
        monkeypatch.setattr(viewer, "_render_chart_image", lambda *_: chart_html)

        session = Session("s1")
        session.result_view_state = {
            "charts": {
                "active_index": 0,
                "configs": [{
                    "type": "bar",
                    "title": "Saved chart",
                    "x_column": "mes",
                    "y_columns": ["valor"],
                    "source_label": "vendas",
                }],
            }
        }
        viewer.set_session(session)

        viewer.display_dataframe(pd.DataFrame({"mes": ["Jan", "Fev"], "valor": [10, 20]}), "vendas")

        assert viewer._result_tabs.count() == 2
        assert viewer._result_tabs.tabText(1) == "Saved chart"
        chart_page = viewer._result_tabs.widget(1)
        assert chart_page._image_bytes is None

        _switch_result_tab(viewer, qtbot, 1)

        qtbot.waitUntil(lambda: _chart_page_ready(chart_page), timeout=5000)
        assert chart_page._chart_html or chart_page._image_bytes

    def test_saved_visualization_does_not_render_on_display_dataframe(self, viewer, monkeypatch):
        """Displaying query results must not block the UI by rendering saved chart tabs immediately."""
        from src.core.session import Session

        session = Session("s1")
        session.result_view_state = {
            "charts": {
                "active_index": 0,
                "configs": [{"type": "bar", "x_column": "mes", "y_columns": ["valor"], "source_label": "vendas"}],
            }
        }
        viewer.set_session(session)
        calls = []
        monkeypatch.setattr(viewer, "_render_chart_image", lambda *_: calls.append(True))

        viewer.display_dataframe(pd.DataFrame({"mes": ["Jan"], "valor": [10]}), "vendas")

        assert viewer._result_tabs.count() == 2
        assert calls == []

    def test_grouped_visualization_renders_chart_image(self, viewer, qtbot, monkeypatch):
        """Grouped chart settings should produce a real chart image tab."""
        chart_html = self._tiny_chart_html()
        monkeypatch.setattr(viewer, "_render_chart_image", lambda *_: chart_html)

        df = pd.DataFrame({
            "mes": ["Jan", "Jan", "Fev", "Fev"],
            "canal": ["Online", "Loja", "Online", "Loja"],
            "valor": [10, 5, 12, 8],
        })
        viewer.display_dataframe(df, "vendas")

        viewer._set_visualization_config({
            "type": "bar",
            "x_column": "mes",
            "y_columns": ["valor"],
            "group_by": "canal",
            "stacking": "stacked",
            "show_data_labels": True,
        })

        chart_page = viewer._result_tabs.widget(1)
        qtbot.waitUntil(lambda: _chart_page_ready(chart_page), timeout=5000)
        assert chart_page._chart_html or chart_page._image_bytes
        payload = chart_page._chart_html or chart_page._image_bytes
        assert len(payload) > 50


class TestSessionResultViewState:
    """Tests for session serialization of result-view settings."""

    def test_session_serializes_result_view_state(self):
        from src.core.session import Session

        session = Session("s1")
        session.result_view_state = {
            "column_formats": {"valor": {"type": "number", "decimals": 0}},
            "charts": {"active_index": 0, "configs": [{"type": "bar"}]},
        }

        data = session.serialize()
        restored = Session.deserialize(data)

        assert restored.result_view_state["column_formats"]["valor"]["decimals"] == 0
        assert restored.result_view_state["charts"]["configs"][0]["type"] == "bar"


class TestResultsViewerGridPrepare:
    """Tests for async grid preparation and cached model rendering."""

    def test_prepare_grid_data_limits_display_rows(self):
        from src.ui.components.results_viewer import prepare_grid_data

        df = pd.DataFrame({"value": range(500)})
        result = prepare_grid_data(df, {}, {}, limit=120)

        assert result.prepared.filtered_row_count == 500
        assert result.prepared.row_count == 120
        assert result.prepared.limited is True

    def test_prepare_grid_data_sorts_before_limit(self):
        from src.ui.components.results_viewer import prepare_grid_data

        df = pd.DataFrame({"name": ["b", "a", "c"], "value": [2, 1, 3]})
        result = prepare_grid_data(
            df,
            {},
            {},
            limit=2,
            sort_column="name",
            sort_ascending=True,
        )

        assert result.prepared.row_count == 2
        assert result.prepared.columns == ["name", "value"]
        assert result.prepared.column_values[0].tolist()[:2] == ["a", "b"]

    def test_large_grid_prepares_off_ui_thread(self, qtbot):
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        qtbot.addWidget(viewer)
        viewer.row_limit_spin.setValue(1500)

        df = pd.DataFrame({"name": [f"row-{index}" for index in range(1800)], "value": range(1800)})
        viewer.display_dataframe(df, "large_df")

        qtbot.waitUntil(lambda: viewer.model.rowCount() == 1500, timeout=5000)
        assert viewer.current_df is not None
        assert len(viewer.current_df) == 1800
        assert viewer.model.data(viewer.model.index(0, 0)) == "row-0"

    def test_empty_result_replaces_large_async_prepare(self, qtbot):
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        qtbot.addWidget(viewer)
        viewer.row_limit_spin.setValue(1500)

        large_df = pd.DataFrame(
            {"name": [f"row-{index}" for index in range(1800)], "value": range(1800)}
        )
        viewer.display_dataframe(large_df, "large_df")

        empty_df = pd.DataFrame({"name": [], "value": []})
        viewer.display_dataframe(empty_df, "empty_df")

        qtbot.waitUntil(lambda: viewer.model.rowCount() == 0, timeout=3000)
        assert viewer.current_df is not None
        assert len(viewer.current_df) == 0
        assert viewer._primary_df is not None
        assert len(viewer._primary_df) == 0

        # Stale async job from the large result must not repopulate the grid.
        qtbot.wait(200)
        assert viewer.model.rowCount() == 0
        assert len(viewer.current_df) == 0

    def test_prepare_grid_data_keeps_numeric_epoch_looking_ids_as_numbers(self):
        from src.ui.components.results_viewer import prepare_grid_data

        df = pd.DataFrame(
            {
                "EventoOperacionalId": [1642585836, 1642585837],
                "DataCriacao": [1779799229610000000, 1779799227757000000],
                "Total": [0.0, 31.28],
            }
        )
        result = prepare_grid_data(df, {}, {}, limit=10)

        # Name/value heuristics must not promote ints to datetime.
        assert result.prepared.display_value(0, 0) == "1642585836"
        assert result.prepared.display_value(0, 1) == "1779799229610000000"
        # Integer-valued floats display without the trailing ".0"; real decimals stay.
        assert result.prepared.display_value(0, 2) == "0"
        assert result.prepared.display_value(1, 2) == "31.28"

    def test_prepare_grid_data_auto_formats_real_datetime_dtype(self):
        from src.ui.components.results_viewer import prepare_grid_data

        df = pd.DataFrame(
            {
                "created_at": pd.to_datetime(
                    ["2022-01-19 09:50:36", "2022-01-20 10:00:00"]
                ),
            }
        )
        result = prepare_grid_data(df, {}, {}, limit=10)
        assert result.prepared.display_value(0, 0) == "2022-01-19 09:50:36"

    def test_prepare_grid_data_respects_explicit_datetime_format(self):
        from src.ui.components.results_viewer import prepare_grid_data

        df = pd.DataFrame({"created_at": [1779799229610000000]})
        formats = {"created_at": {"type": "datetime"}}
        result = prepare_grid_data(df, {}, formats, limit=10)

        assert "2026" in result.prepared.display_value(0, 0)
        assert "1779799229610000000" not in result.prepared.display_value(0, 0)




class TestDuplicateColumns:
    """Grid must handle SQL results with duplicate column names (no crash)."""

    def test_prepare_grid_data_with_duplicate_columns(self):
        from src.ui.components.results_viewer import prepare_grid_data

        df = pd.DataFrame([[1, 2], [3, 4]], columns=["id", "id"])
        result = prepare_grid_data(df, {}, {}, 1500)
        # Duplicates get pandas-style suffixes; nothing crashes.
        assert result.prepared.columns == ["id", "id.1"]
        assert result.prepared.numeric_column_indices == frozenset({0, 1})
        assert result.prepared.filtered_row_count == 2

    def test_dedupe_does_not_mutate_input(self):
        from src.ui.components.results_viewer import _dedupe_grid_columns

        df = pd.DataFrame([[1, 2]], columns=["a", "a"])
        out = _dedupe_grid_columns(df)
        assert list(df.columns) == ["a", "a"]       # caller's frame untouched
        assert list(out.columns) == ["a", "a.1"]

    def test_dedupe_is_noop_when_unique(self):
        from src.ui.components.results_viewer import _dedupe_grid_columns

        df = pd.DataFrame([[1, 2]], columns=["a", "b"])
        assert _dedupe_grid_columns(df) is df       # no copy when already unique


class TestCSVExportDialog:
    def test_csv_export_dialog_decimal_getter(self, qtbot):
        from src.ui.components.results_viewer import CSVExportDialog

        dialog = CSVExportDialog()
        qtbot.addWidget(dialog)

        comma_index = dialog.decimal_combo.findData(",")
        dialog.decimal_combo.setCurrentIndex(comma_index)
        assert dialog.get_decimal() == ","

    def test_csv_export_dialog_decimal_persisted(self, qtbot):
        from PyQt6.QtCore import QSettings

        from src.ui.components.results_viewer import CSVExportDialog

        settings = QSettings("DataPyn", "CSVExport")
        settings.setValue("decimal", ",")

        dialog = CSVExportDialog()
        qtbot.addWidget(dialog)
        assert dialog.get_decimal() == ","

        dot_index = dialog.decimal_combo.findData(".")
        dialog.decimal_combo.setCurrentIndex(dot_index)
        dialog.accept()
        assert settings.value("decimal") == "."
