"""Tests for grid selection summary stats."""

import pandas as pd
import pytest

from src.ui.components.summarize_stats import build_selection_summary


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "amount": [10.0, 20.0, 30.0, 40.0],
        "qty": [1, 2, 3, 4],
        "region": ["North", "South", "North", "East"],
        "note": ["a", "b", None, "a"],
    })


def test_empty_dataframe():
    payload = build_selection_summary(pd.DataFrame(), [])
    assert payload["subtitle"] == "no_data"
    assert payload["columns"] == []


def test_no_summary_without_selection(sample_df):
    payload = build_selection_summary(sample_df, [])
    assert payload["scope"] == "empty"
    assert payload["columns"] == []
    assert payload["subtitle"] == "no_selection"


def test_selection_subset(sample_df):
    cells = [(0, 0), (1, 0), (0, 2), (1, 2)]
    payload = build_selection_summary(sample_df, cells)
    assert payload["scope"] == "selection"
    assert payload["rows_selected"] == 2
    assert payload["cols_selected"] == 2
    assert payload["cells_selected"] == 4
    assert len(payload["columns"]) == 2

    amount = next(c for c in payload["columns"] if c["name"] == "amount")
    assert amount["sum_raw"] == 30.0

    region = next(c for c in payload["columns"] if c["name"] == "region")
    assert region["top"].startswith("North")


def test_grand_total_across_numeric_columns(sample_df):
    cells = [(0, 0), (0, 1), (1, 0), (1, 1)]
    payload = build_selection_summary(sample_df, cells)
    assert payload["grand_total"] == 33.0
    assert payload["aggregates"][4]["key"] == "sum"
    assert payload["aggregates"][4]["value"] == "33.00"


def test_numeric_hint_respected(sample_df):
    payload = build_selection_summary(
        sample_df,
        [(0, 1), (1, 1), (2, 1), (3, 1)],
        numeric_column_indices={1},
    )
    qty = payload["columns"][0]
    assert qty["name"] == "qty"
    assert qty["kind"] == "numeric"
    assert qty["sum_raw"] == 10.0


def test_scientific_notation_object_column():
    df = pd.DataFrame({
        "ValorBase": ["0.069734873671", "21.780000000000", "0.007369129005"],
        "ValorComissao": ["0E-12", "0.087666856972", "8.710000000000"],
    })
    payload = build_selection_summary(df, [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1)])
    for name in ("ValorBase", "ValorComissao"):
        col = next(c for c in payload["columns"] if c["name"] == name)
        assert col["kind"] == "numeric", f"{name} should be numeric"
    assert payload["grand_total"] is not None


def test_column_format_applied(sample_df):
    payload = build_selection_summary(
        sample_df,
        [(0, 0), (1, 0), (2, 0), (3, 0)],
        column_formats={"amount": {"type": "currency", "prefix": "$ ", "decimals": 2}},
    )
    amount = next(c for c in payload["columns"] if c["name"] == "amount")
    assert amount["sum"].startswith("$ ")


def test_large_selection_uses_row_ranges(sample_df):
    payload = build_selection_summary(
        sample_df,
        [],
        row_ranges=[(0, 3)],
        bound_cols=[0, 2],
    )
    assert payload["scope"] == "selection"
    assert payload["rows_selected"] == 4
    assert payload["cols_selected"] == 2
    assert payload["cells_selected"] == 8
    assert {col["name"] for col in payload["columns"]} == {"amount", "region"}

