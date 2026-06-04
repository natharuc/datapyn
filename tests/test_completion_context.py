import pandas as pd

from src.editors.completion_context import (
    build_dataframe_member_completions,
    describe_namespace_dataframes,
    dataframe_column_names,
)


def test_dataframe_column_names_from_pandas():
    df = pd.DataFrame({"IdPremio": [1], "Nome": ["a"]})
    assert dataframe_column_names(df) == ["IdPremio", "Nome"]


def test_describe_namespace_dataframes_lists_real_columns():
    df = pd.DataFrame({"IdPremio": [1], "Nome": ["a"]})
    text = describe_namespace_dataframes({"block1": df})
    assert "block1" in text
    assert "IdPremio" in text
    assert "Nome" in text
    assert "NomePremio" not in text


def test_build_dataframe_member_completions_filter_text():
    df = pd.DataFrame({"IdPremio": [1]})
    items = build_dataframe_member_completions({"block1": df})
    assert any(i["label"] == "IdPremio" and i["filterText"] == "block1.IdPremio" for i in items)
