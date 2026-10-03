"""Exact sparse-selection, numeric string, Decimal and combined legacy statistics."""

from decimal import Decimal

import numpy as np
import pandas as pd
import polars as pl
import pytest

from datapyn_runtime.data_tools import dispatch
from datapyn_runtime.kernel import ResultStore


def summary(frame, **params):
    return dispatch("result.summary", {"variable_name": "df", **params}, {"df": frame}, ResultStore(pd, pl))


def test_combined_sparse_selection_counts_only_actual_cells_and_deduplicates_overlap():
    frame = pd.DataFrame({"a": [1, 2, 900, 800], "b": [700, 600, 3, 4]})
    result = summary(frame, scope={"rectangles": [{"x": 0, "y": 0, "width": 1, "height": 2},
                    {"x": 0, "y": 1, "width": 1, "height": 1}, {"x": 1, "y": 2, "width": 1, "height": 2}]})
    assert result["cell_count"] == 4 and result["row_count"] == 4 and result["column_count"] == 2
    aggregates = result["aggregates"]
    assert aggregates["count_numeric"] == 4
    assert aggregates["sum"] == 10 and aggregates["mean"] == 2.5 and aggregates["median"] == 2.5
    assert aggregates["min"] == 1 and aggregates["max"] == 4
    assert aggregates["coefficient"] == pytest.approx(np.std([1, 2, 3, 4]) / 2.5 * 100)


def test_numeric_strings_follow_legacy_detection_and_invalid_values_are_not_numeric():
    result = summary(pd.DataFrame({"number": ["1.25", "2.75", "missing", None], "text": ["a", "b", "c", None]}))
    column, text = result["columns"]
    assert column["count"] == 4 and column["null_count"] == 1 and column["numeric_count"] == 2
    assert column["sum"] == "4.00" and column["median"] == "2.00" and column["distinct"] == 2
    assert "sum" not in text and text["distinct"] == 3
    assert result["aggregates"]["sum"] == "4.00"


def test_decimal_statistics_do_not_round_large_identifiers_or_small_differences():
    first = Decimal("123456789012345678901234567890.00000000000000000001")
    second = Decimal("123456789012345678901234567890.00000000000000000003")
    result = summary(pd.DataFrame({"amount": [first, second, None]}))
    column = result["columns"][0]
    assert column["sum"] == "246913578024691357802469135780.00000000000000000004"
    assert column["mean"] == "123456789012345678901234567890.00000000000000000002"
    assert column["median"] == column["mean"] and column["distinct"] == 2
    assert Decimal(column["std"]) > 0 and Decimal(result["aggregates"]["coefficient"]) > 0


def test_integer_reductions_do_not_overflow_signed_or_unsigned_64_bits():
    result = summary(pd.DataFrame({"signed": [2**62 + 1] * 3, "unsigned": pd.Series([2**64 - 1] * 3, dtype="uint64")}))
    assert result["columns"][0]["sum"] == str((2**62 + 1) * 3)
    assert result["columns"][0]["median"] == str(2**62 + 1)
    assert result["columns"][1]["sum"] == str((2**64 - 1) * 3)
    assert result["aggregates"]["sum"] == str(((2**62 + 1) + (2**64 - 1)) * 3)


def test_combined_sum_does_not_overflow_when_each_individual_column_is_safe():
    frame = pd.DataFrame(np.full((50, 50), 2**52, dtype=np.int64))
    result = summary(frame)
    assert result["columns"][0]["sum"] == str(2**52 * 50)
    assert result["aggregates"]["sum"] == str(2**52 * 2500)


def test_empty_and_nonfinite_numeric_selection_has_no_nan_on_the_wire():
    result = summary(pd.DataFrame({"value": [np.nan, np.inf, -np.inf]}))
    assert result["aggregates"]["count_numeric"] == 0
    assert result["aggregates"]["sum"] is None and result["aggregates"]["coefficient"] is None
    assert result["columns"][0]["numeric_count"] == 0


def test_distinct_sampling_is_explicit_and_other_statistics_cover_the_full_column():
    result = summary(pd.DataFrame({"value": np.arange(100_005)}))
    column = result["columns"][0]
    assert column["distinct"] == 100_000 and column["distinct_sampled"]
    assert column["sample_rows"] == 100_000 and column["count"] == 100_005
    assert column["sum"] == sum(range(100_005))


def test_combined_decimal_and_float_columns_remain_exact_and_source_is_unchanged():
    frame = pd.DataFrame({"a": [Decimal("0.1"), Decimal("0.2")], "b": [0.1, 0.2]})
    original = frame.copy(deep=True)
    result = summary(frame)
    assert result["aggregates"]["sum"] == "0.6" and result["aggregates"]["median"] == "0.15"
    pd.testing.assert_frame_equal(frame, original)
