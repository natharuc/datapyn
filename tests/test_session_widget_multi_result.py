"""Tests for SessionWidget._set_results multi-DataFrame dispatch.

Reproduces the user-reported bug: running
    SELECT * FROM produto;
    SELECT * FROM cliente;
returned a list of DataFrames but only the last one (cliente) was shown.
After the fix, _set_results routes the list to the viewer's
display_dataframes API so every result set gets its own tab.
"""
import sys
import os
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))


def _make_widget_with_viewer(viewer):
    """Build a stand-in SessionWidget that exposes only what _set_results needs."""
    from src.ui.components.session_widget import SessionWidget

    widget = MagicMock(spec=SessionWidget)
    widget._connection_color = "#007ACC"
    widget._get_own_panels = MagicMock(return_value={"results": viewer})
    widget._get_main_window = MagicMock(return_value=MagicMock(show_panel=MagicMock()))
    widget._set_results = SessionWidget._set_results.__get__(widget)
    return widget


class TestSetResultsMultiDataFrame:
    def test_list_of_tuples_routes_to_display_dataframes(self):
        viewer = MagicMock(spec=["display_dataframe", "display_dataframes"])
        widget = _make_widget_with_viewer(viewer)

        df1 = pd.DataFrame({"id": [1, 2]})
        df2 = pd.DataFrame({"name": ["a", "b", "c"]})
        items = [("produto", df1), ("cliente", df2)]

        widget._set_results(items, "cliente")

        viewer.display_dataframes.assert_called_once_with(items)
        viewer.display_dataframe.assert_not_called()

    def test_single_dataframe_still_uses_display_dataframe(self):
        viewer = MagicMock(spec=["display_dataframe", "display_dataframes"])
        widget = _make_widget_with_viewer(viewer)

        df = pd.DataFrame({"a": [1]})
        widget._set_results(df, "result")

        viewer.display_dataframe.assert_called_once_with(df, "result")
        viewer.display_dataframes.assert_not_called()

    def test_list_fallback_when_viewer_lacks_multi_tab(self):
        # Viewer without display_dataframes (old API)
        viewer = MagicMock(spec=["display_dataframe"])
        widget = _make_widget_with_viewer(viewer)

        df1 = pd.DataFrame({"id": [1]})
        df2 = pd.DataFrame({"name": ["x"]})
        items = [("produto", df1), ("cliente", df2)]

        widget._set_results(items, "cliente")

        # Should fall back to displaying the last item only
        viewer.display_dataframe.assert_called_once_with(df2, "cliente")

    def test_empty_list_is_safe(self):
        viewer = MagicMock(spec=["display_dataframe", "display_dataframes"])
        widget = _make_widget_with_viewer(viewer)

        widget._set_results([], "result")

        # display_dataframes is called with empty list (which is a no-op there)
        viewer.display_dataframes.assert_called_once_with([])

    def test_connection_color_is_forwarded_to_results_viewer(self):
        viewer = MagicMock(spec=["display_dataframe", "display_dataframes", "set_connection_color"])
        widget = _make_widget_with_viewer(viewer)
        widget._connection_color = "#f97316"

        df = pd.DataFrame({"a": [1]})
        widget._set_results(df, "result")

        viewer.set_connection_color.assert_called_once_with("#f97316")
        viewer.display_dataframe.assert_called_once_with(df, "result")
