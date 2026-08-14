"""Tests for Pynia execution context (last error + active result)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from src.services.pynia.execution_context import build_execution_context, panels_for_session


def _make_main_window(output_panel=None, results_viewer=None):
    mw = MagicMock()
    mw._session_panel_indices = {}
    mw.global_output_panel = output_panel
    mw.global_results_viewer = results_viewer
    return mw


def test_build_execution_context_surfaces_last_error():
    output_panel = MagicMock()
    output_panel.get_last_error.return_value = {
        "message": "Unknown column 'totl'",
        "detail": "OperationalError: Unknown column 'totl' in 'field list'",
        "log_type": "SQL",
        "block_name": "vendas",
        "line_number": 2,
        "is_latest": True,
    }
    mw = _make_main_window(output_panel=output_panel, results_viewer=None)

    state = build_execution_context(mw, "sess-1")
    assert state is not None
    assert state["last_error"]["block_name"] == "vendas"
    assert state["last_error"]["is_latest"] is True


def test_build_execution_context_surfaces_active_result():
    df = pd.DataFrame({"mes": ["jan", "fev"], "total": [10, 20]})
    viewer = MagicMock()
    viewer.current_df = df
    viewer.list_visualizations.return_value = {
        "sources": [
            {"label": "Result 1", "rows": 2, "columns": ["mes", "total"], "numeric_columns": ["total"]}
        ]
    }
    mw = _make_main_window(output_panel=None, results_viewer=viewer)

    state = build_execution_context(mw, "sess-1")
    assert state is not None
    result = state["active_result"]
    assert result["rows"] == 2
    assert result["columns"] == ["mes", "total"]
    assert result["chart_sources"][0]["numeric_columns"] == ["total"]
    assert "total" in result["preview"]


def test_build_execution_context_prefers_session_specific_panels():
    output_panel = MagicMock()
    output_panel.get_last_error.return_value = {"message": "boom", "is_latest": True}
    mw = MagicMock()
    mw._session_panel_indices = {"sess-9": {"output": output_panel, "results": None}}
    # Global panel must NOT be used when the session is resolvable.
    mw.global_output_panel = MagicMock()
    mw.global_output_panel.get_last_error.return_value = {"message": "wrong-panel"}
    mw.global_results_viewer = None

    state = build_execution_context(mw, "sess-9")
    assert state["last_error"]["message"] == "boom"


def test_build_execution_context_empty_returns_none():
    viewer = MagicMock()
    viewer.current_df = None
    viewer.list_visualizations.return_value = {"sources": []}
    output_panel = MagicMock()
    output_panel.get_last_error.return_value = None
    mw = _make_main_window(output_panel=output_panel, results_viewer=viewer)

    assert build_execution_context(mw, "sess-1") is None


def test_panels_for_session_prefers_pinned_tab():
    pinned = MagicMock(name="pinned")
    visual = MagicMock(name="visual")
    mw = MagicMock()
    mw._session_panel_indices = {
        "tab-a": {"output": None, "results": pinned},
        "tab-b": {"output": None, "results": visual},
    }
    mw.global_results_viewer = visual
    mw.global_output_panel = None
    _out, results = panels_for_session(mw, "tab-a")
    assert results is pinned


def test_build_execution_context_handles_no_main_window():
    assert build_execution_context(None, "x") is None


def test_output_panel_get_last_error(qtbot):
    from src.ui.components.output_panel import LogEntry, OutputPanel

    panel = OutputPanel()
    qtbot.addWidget(panel)

    panel.log("Running query…")
    panel.add_entry(
        LogEntry(
            level="error",
            log_type="SQL",
            message="Unknown column 'totl'",
            detail="Traceback ...\nOperationalError: Unknown column 'totl'",
            block_name="vendas",
            line_number=3,
        )
    )

    err = panel.get_last_error()
    assert err is not None
    assert err["message"] == "Unknown column 'totl'"
    assert err["block_name"] == "vendas"
    assert err["line_number"] == 3
    assert err["is_latest"] is True

    # A later success means the error is no longer the current state.
    panel.success("Query OK")
    assert panel.get_last_error()["is_latest"] is False


def test_output_panel_get_last_error_none_when_clean(qtbot):
    from src.ui.components.output_panel import OutputPanel

    panel = OutputPanel()
    qtbot.addWidget(panel)
    panel.log("all good")
    assert panel.get_last_error() is None
