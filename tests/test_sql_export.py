"""
Tests for the SQL INSERT export feature.

Covers:
- SQL generation for different database dialects
- Value formatting (NULL, strings, numbers, dates, booleans, bytes)
- Identifier quoting per dialect
- Multi-row batch INSERTs
- Empty DataFrame handling
- Schema-qualified table names
- Large DataFrames (performance)
- ResultsViewer SQL export button integration
"""

import math
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from source.src.utils.sql_insert_generator import (
    format_value,
    generate_inserts,
    quote_identifier,
)


# ---------------------------------------------------------------------------
# quote_identifier
# ---------------------------------------------------------------------------
class TestQuoteIdentifier:
    """Tests for identifier quoting per database dialect."""

    def test_sqlserver_brackets(self):
        assert quote_identifier("users", "sqlserver") == "[users]"
        assert quote_identifier("users", "mssql") == "[users]"

    def test_postgresql_double_quotes(self):
        assert quote_identifier("users", "postgresql") == '"users"'

    def test_mysql_backticks(self):
        assert quote_identifier("users", "mysql") == "`users`"
        assert quote_identifier("users", "mariadb") == "`users`"

    def test_databricks_backticks(self):
        assert quote_identifier("my_table", "databricks") == "`my_table`"

    def test_sqlite_double_quotes(self):
        assert quote_identifier("users", "sqlite") == '"users"'

    def test_special_chars_in_name(self):
        assert quote_identifier("my table", "sqlserver") == "[my table]"
        assert quote_identifier("col-1", "postgresql") == '"col-1"'


# ---------------------------------------------------------------------------
# format_value
# ---------------------------------------------------------------------------
class TestFormatValue:
    """Tests for SQL value formatting."""

    def test_none_is_null(self):
        assert format_value(None, "sqlserver") == "NULL"
        assert format_value(None, "postgresql") == "NULL"

    def test_nan_is_null(self):
        assert format_value(float("nan"), "sqlserver") == "NULL"

    def test_inf_is_null(self):
        assert format_value(float("inf"), "mysql") == "NULL"

    def test_integer(self):
        assert format_value(42, "sqlserver") == "42"
        assert format_value(0, "postgresql") == "0"
        assert format_value(-7, "mysql") == "-7"

    def test_float(self):
        result = format_value(3.14, "sqlserver")
        assert "3.14" in result

    def test_string_simple(self):
        assert format_value("hello", "sqlserver") == "'hello'"

    def test_string_with_single_quote(self):
        assert format_value("it's", "sqlserver") == "'it''s'"
        assert format_value("it's", "mysql") == "'it''s'"

    def test_string_with_backslash_mysql(self):
        assert format_value("path\\file", "mysql") == "'path\\\\file'"
        assert format_value("path\\file", "databricks") == "'path\\\\file'"

    def test_string_with_backslash_sqlserver(self):
        # SQL Server does not need backslash escaping
        assert format_value("path\\file", "sqlserver") == "'path\\file'"

    def test_boolean_sqlserver(self):
        assert format_value(True, "sqlserver") == "1"
        assert format_value(False, "sqlserver") == "0"

    def test_boolean_postgresql(self):
        assert format_value(True, "postgresql") == "TRUE"
        assert format_value(False, "postgresql") == "FALSE"

    def test_boolean_mysql(self):
        assert format_value(True, "mysql") == "TRUE"

    def test_date(self):
        d = date(2024, 1, 15)
        assert format_value(d, "sqlserver") == "'2024-01-15'"

    def test_datetime(self):
        dt = datetime(2024, 1, 15, 10, 30, 0)
        result = format_value(dt, "postgresql")
        assert "'2024-01-15" in result
        assert "10:30" in result

    def test_bytes_sqlserver(self):
        b = b"\xde\xad"
        assert format_value(b, "sqlserver") == "0xdead"

    def test_bytes_postgresql(self):
        b = b"\xca\xfe"
        assert format_value(b, "postgresql") == "'\\xcafe'"

    def test_bytes_mysql(self):
        b = b"\xbe\xef"
        assert format_value(b, "mysql") == "X'beef'"


# ---------------------------------------------------------------------------
# generate_inserts
# ---------------------------------------------------------------------------
class TestGenerateInserts:
    """Tests for full INSERT statement generation."""

    @pytest.fixture
    def simple_df(self):
        return pd.DataFrame(
            {"id": [1, 2, 3], "name": ["Alice", "Bob", "Charlie"], "age": [30, 25, 35]}
        )

    def test_basic_sqlserver(self, simple_df):
        sql = generate_inserts(simple_df, "users", db_type="sqlserver")
        assert "INSERT INTO [users]" in sql
        assert "([id], [name], [age])" in sql
        assert "VALUES (1, 'Alice', 30);" in sql
        assert "VALUES (2, 'Bob', 25);" in sql
        assert "VALUES (3, 'Charlie', 35);" in sql

    def test_basic_postgresql(self, simple_df):
        sql = generate_inserts(simple_df, "users", db_type="postgresql")
        assert 'INSERT INTO "users"' in sql
        assert '("id", "name", "age")' in sql
        assert "VALUES (1, 'Alice', 30);" in sql

    def test_basic_mysql(self, simple_df):
        sql = generate_inserts(simple_df, "users", db_type="mysql")
        assert "INSERT INTO `users`" in sql
        assert "(`id`, `name`, `age`)" in sql

    def test_basic_databricks(self, simple_df):
        sql = generate_inserts(simple_df, "users", db_type="databricks")
        assert "INSERT INTO `users`" in sql
        assert "(`id`, `name`, `age`)" in sql

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["a", "b"])
        sql = generate_inserts(df, "empty_table", db_type="sqlserver")
        assert "Empty DataFrame" in sql
        assert "INSERT INTO" not in sql

    def test_null_values(self):
        df = pd.DataFrame({"id": [1, 2], "value": [None, "ok"]})
        sql = generate_inserts(df, "data", db_type="postgresql")
        assert "NULL" in sql
        assert "'ok'" in sql

    def test_nan_values(self):
        df = pd.DataFrame({"id": [1], "score": [float("nan")]})
        sql = generate_inserts(df, "scores", db_type="sqlserver")
        assert "NULL" in sql

    def test_schema_qualified(self, simple_df):
        sql = generate_inserts(simple_df, "users", db_type="sqlserver", schema_name="dbo")
        assert "[dbo].[users]" in sql

    def test_schema_qualified_pg(self, simple_df):
        sql = generate_inserts(simple_df, "users", db_type="postgresql", schema_name="public")
        assert '"public"."users"' in sql

    def test_multi_row_batch(self, simple_df):
        sql = generate_inserts(simple_df, "users", db_type="postgresql", batch_size=2)
        # Should have 2 INSERT statements: one with 2 rows, one with 1 row
        assert sql.count("INSERT INTO") == 2
        assert sql.count("VALUES") == 2

    def test_multi_row_batch_exact(self):
        df = pd.DataFrame({"x": [1, 2, 3, 4]})
        sql = generate_inserts(df, "t", db_type="mysql", batch_size=2)
        assert sql.count("INSERT INTO") == 2

    def test_include_go_sqlserver(self, simple_df):
        sql = generate_inserts(simple_df, "users", db_type="sqlserver", include_go=True)
        assert "GO" in sql

    def test_include_go_ignored_for_pg(self, simple_df):
        sql = generate_inserts(simple_df, "users", db_type="postgresql", include_go=True)
        assert "GO" not in sql

    def test_special_chars_in_values(self):
        df = pd.DataFrame({"msg": ["it's a \"test\"", "line1\nline2"]})
        sql = generate_inserts(df, "messages", db_type="sqlserver")
        assert "it''s" in sql

    def test_boolean_values_mixed(self):
        df = pd.DataFrame({"flag": [True, False]})
        sql_ss = generate_inserts(df, "flags", db_type="sqlserver")
        # SQL Server: booleans should be 1/0
        assert "VALUES (1)" in sql_ss
        assert "VALUES (0)" in sql_ss

        sql_pg = generate_inserts(df, "flags", db_type="postgresql")
        assert "TRUE" in sql_pg
        assert "FALSE" in sql_pg

    def test_date_columns(self):
        df = pd.DataFrame({"dt": [date(2024, 6, 15)]})
        sql = generate_inserts(df, "dates", db_type="sqlserver")
        assert "'2024-06-15'" in sql

    def test_comment_header(self, simple_df):
        sql = generate_inserts(simple_df, "users", db_type="sqlserver")
        assert "-- INSERT statements for [users]" in sql
        assert "3 rows x 3 columns" in sql

    def test_large_dataframe_performance(self):
        """Ensure generation of 10k rows completes without issues."""
        df = pd.DataFrame(
            {"id": range(10000), "value": [f"row_{i}" for i in range(10000)]}
        )
        sql = generate_inserts(df, "big_table", db_type="postgresql")
        assert sql.count("INSERT INTO") == 10000

    def test_column_names_with_spaces(self):
        df = pd.DataFrame({"First Name": ["Alice"], "Last Name": ["Smith"]})
        sql = generate_inserts(df, "people", db_type="sqlserver")
        assert "[First Name]" in sql
        assert "[Last Name]" in sql


# ---------------------------------------------------------------------------
# ResultsViewer integration (SQL export button)
# ---------------------------------------------------------------------------
class TestResultsViewerSQLExport:
    """Tests for the SQL export button on ResultsViewer."""

    @pytest.fixture
    def viewer(self, qtbot):
        from source.src.core.theme_manager import ThemeManager

        from source.src.ui.components.results_viewer import ResultsViewer

        tm = ThemeManager()
        rv = ResultsViewer(theme_manager=tm)
        qtbot.addWidget(rv)
        return rv

    def test_sql_button_exists(self, viewer):
        assert hasattr(viewer, "btn_export_sql")
        assert viewer.btn_export_sql is not None

    def test_sql_button_visible_after_dataframe(self, viewer):
        df = pd.DataFrame({"id": [1], "name": ["test"]})
        viewer.display_dataframe(df, "my_df")
        # isHidden() checks explicitly set visibility (not effective/rendered)
        assert not viewer.btn_export_sql.isHidden()

    def test_sql_button_hidden_for_image(self, viewer):
        # Create a minimal PNG
        import struct
        import zlib

        def _mini_png():
            sig = b"\x89PNG\r\n\x1a\n"
            ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
            ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc
            raw = zlib.compress(b"\x00\x00\x00\x00")
            idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + raw) & 0xFFFFFFFF)
            idat = struct.pack(">I", len(raw)) + b"IDAT" + raw + idat_crc
            iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
            iend = struct.pack(">I", 0) + b"IEND" + iend_crc
            return sig + ihdr + idat + iend

        viewer.display_image(_mini_png())
        assert viewer.btn_export_sql.isHidden()

    def test_sql_button_hidden_for_html(self, viewer):
        viewer.display_html("<p>Hello</p>")
        assert viewer.btn_export_sql.isHidden()

    def test_sql_button_hidden_for_json(self, viewer):
        viewer.display_json({"key": "value"})
        assert viewer.btn_export_sql.isHidden()

    def test_sql_export_clipboard(self, viewer, qtbot):
        df = pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})
        viewer.display_dataframe(df, "test_table")
        viewer.export_destination.setCurrentIndex(0)  # clipboard

        from PyQt6.QtWidgets import QApplication

        viewer._export_sql()
        clip = QApplication.instance().clipboard().text()
        assert "INSERT INTO" in clip
        assert "test_table" in clip
        assert "'Alice'" in clip
        assert "'Bob'" in clip

    def test_sql_export_uses_var_name_as_table(self, viewer, qtbot):
        df = pd.DataFrame({"x": [1]})
        viewer.display_dataframe(df, "sales_2024")
        viewer.export_destination.setCurrentIndex(0)

        from PyQt6.QtWidgets import QApplication

        viewer._export_sql()
        clip = QApplication.instance().clipboard().text()
        assert "sales_2024" in clip

    def test_get_active_db_type_default(self, viewer):
        """When no main window, defaults to sqlserver."""
        db_type = viewer._get_active_db_type()
        assert db_type == "sqlserver"

    def test_sql_button_restored_on_clear(self, viewer):
        df = pd.DataFrame({"id": [1]})
        viewer.display_dataframe(df, "t")
        viewer.clear()
        # After clear(), buttons are restored to DataFrame-mode visibility
        assert not viewer.btn_export_sql.isHidden()
