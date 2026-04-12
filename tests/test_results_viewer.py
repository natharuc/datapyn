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
        """Copying a single selected cell should include header + value."""
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
        assert len(lines) == 2  # header + 1 data row
        assert "nome" in lines[0]
        assert "Alice" in lines[1]

    def test_copy_selection_multiple_rows(self, viewer, sample_df, qtbot):
        """Copying multiple rows should include all selected rows."""
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
        assert len(lines) == 4  # header + 3 data rows
        assert "Alice" in lines[1]
        assert "Bob" in lines[2]
        assert "Carol" in lines[3]

    def test_copy_selection_full_column(self, viewer, sample_df, qtbot):
        """Selecting a full column should copy all values with header."""
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
        assert len(lines) == 5  # header + 4 data rows
        assert "idade" in lines[0]
        assert "25" in lines[1]
        assert "30" in lines[2]
        assert "35" in lines[3]
        assert "40" in lines[4]

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

        viewer._copy_selection_to_clipboard()

        text = QApplication.instance().clipboard().text()
        lines = text.strip().split("\n")
        assert len(lines) == 2  # header + 1 data row
        # Header should have both column names separated by tab
        assert "nome" in lines[0]
        assert "cidade" in lines[0]
        assert "\t" in lines[0]
        # Data row
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

        viewer._copy_selection_to_clipboard()

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
