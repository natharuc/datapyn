"""Tests for Plotly session chart HTML generation."""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))

plotly = pytest.importorskip("plotly")


def test_render_session_chart_html_bar_contains_plotly():
    from src.services.visualization.plotly_charts import render_session_chart_html

    df = pd.DataFrame({"month": ["Jan", "Feb", "Mar"], "sales": [10, 20, 15]})
    config = {"type": "bar", "x_column": "month", "y_columns": ["sales"], "title": "Sales"}
    html = render_session_chart_html(df, config)

    assert "<html" in html.lower()
    assert "plotly" in html.lower()
    assert "Sales" in html
