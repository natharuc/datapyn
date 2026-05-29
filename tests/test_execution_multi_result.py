"""Tests for multi-result dispatch in MainWindow._handle_execution_result.

Verifies that:
- list[pd.DataFrame] is routed to ResultsViewer.display_dataframes (creating tabs);
- single pd.DataFrame still calls display_dataframe (back-compat);
- mixed list with non-DataFrame items falls through to the existing
  list-to-DataFrame branch.
"""
import sys
import os
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))


def _make_handler():
    """Build a minimal stand-in for the MainWindow object exposing only the
    members that _handle_execution_result touches. We bind the real method
    from the mixin so this is a behavioural test of the production code."""
    from src.ui.main_window._execution import ExecutionMixin

    handler = MagicMock(spec=ExecutionMixin)
    handler.action_label = MagicMock()
    handler.global_results_viewer = MagicMock()
    handler.show_panel = MagicMock()
    handler._log = MagicMock()
    handler._log_info = MagicMock()
    handler._show_error_output = MagicMock()
    # Bind the real method to the mock so we exercise the real branching
    handler._handle_execution_result = ExecutionMixin._handle_execution_result.__get__(handler)
    return handler


class TestExecutionMultiResultDispatch:
    def test_list_of_dataframes_routes_to_display_dataframes(self):
        handler = _make_handler()
        df1 = pd.DataFrame({"a": [1, 2]})
        df2 = pd.DataFrame({"b": [3, 4, 5]})

        ok = handler._handle_execution_result(result=[df1, df2], execution_type="SQL")

        assert ok is True
        handler.global_results_viewer.display_dataframes.assert_called_once()
        items = handler.global_results_viewer.display_dataframes.call_args[0][0]
        assert len(items) == 2
        # Each item is (label, df)
        assert items[0][1] is df1
        assert items[1][1] is df2
        # Single-df API must NOT have been called for this branch
        handler.global_results_viewer.display_dataframe.assert_not_called()
        handler.show_panel.assert_called_with("results")

    def test_single_dataframe_still_calls_display_dataframe(self):
        handler = _make_handler()
        df = pd.DataFrame({"a": [1]})

        ok = handler._handle_execution_result(result=df, execution_type="SQL")

        assert ok is True
        handler.global_results_viewer.display_dataframe.assert_called_once()
        handler.global_results_viewer.display_dataframes.assert_not_called()

    def test_mixed_list_with_non_dataframe_falls_through(self):
        """A list that contains non-DataFrame items must NOT hit the multi-tab
        branch; it goes to the legacy list-to-DataFrame conversion path."""
        handler = _make_handler()
        df = pd.DataFrame({"a": [1]})

        ok = handler._handle_execution_result(
            result=[df, "not a dataframe"], execution_type="Python"
        )

        assert ok is True
        # Multi-tab API must not be invoked
        handler.global_results_viewer.display_dataframes.assert_not_called()

    def test_empty_list_does_not_hit_multi_tab_branch(self):
        handler = _make_handler()
        ok = handler._handle_execution_result(result=[], execution_type="SQL")
        assert ok is True
        handler.global_results_viewer.display_dataframes.assert_not_called()
        handler.global_results_viewer.display_dataframe.assert_not_called()
