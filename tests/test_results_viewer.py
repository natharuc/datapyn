"""Tests for ResultsViewer copy selection functionality."""
import sys
import os
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))


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
        viewer.export_destination.setCurrentIndex(0)  # clipboard
        viewer._export_excel()

        text = QApplication.instance().clipboard().text()
        assert "name" in text
        assert "age" in text
        assert "Alice" in text
