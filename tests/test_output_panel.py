"""
Tests for the refactored Output Panel (LogEntry, parse_error_line, OutputPanel, LogDetailDialog).
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from src.ui.components.output_panel import (
    LogEntry, parse_error_line, parse_error_position,
    _find_token_in_sql, _extract_error_token, OutputPanel,
)


# ======================================================================
# LogEntry dataclass
# ======================================================================

class TestLogEntry:
    """Tests for the LogEntry dataclass."""

    def test_default_values(self):
        entry = LogEntry()
        assert entry.level == "info"
        assert entry.message == ""
        assert entry.block_index is None
        assert entry.line_number is None
        assert entry.duration_ms is None
        assert entry.code_snippet == ""
        assert isinstance(entry.timestamp, datetime)

    def test_custom_values(self):
        entry = LogEntry(
            level="error",
            log_type="SQL",
            message="Syntax error near 'SELCT'",
            detail="Msg 102, Level 15, State 1, Line 3",
            block_index=2,
            block_name="query_users",
            line_number=3,
            duration_ms=145.2,
            code_snippet="SELCT * FROM users",
            connection_name="prod-db",
            database_name="mydb",
        )
        assert entry.level == "error"
        assert entry.log_type == "SQL"
        assert entry.block_index == 2
        assert entry.line_number == 3
        assert entry.duration_ms == 145.2
        assert entry.connection_name == "prod-db"

    def test_multiple_entries_independent(self):
        e1 = LogEntry(level="info", message="ok")
        e2 = LogEntry(level="error", message="fail")
        assert e1.level != e2.level
        assert e1.message != e2.message


# ======================================================================
# parse_error_line
# ======================================================================

class TestParseErrorLine:
    """Tests for parse_error_line()."""

    def test_none_input(self):
        assert parse_error_line(None) is None

    def test_empty_string(self):
        assert parse_error_line("") is None

    def test_no_line_info(self):
        assert parse_error_line("Something went wrong") is None

    def test_sql_server_format(self):
        error = "Msg 102, Level 15, State 1, Line 5\nIncorrect syntax near 'SELCT'."
        assert parse_error_line(error, "SQL") == 5

    def test_mysql_format(self):
        error = "You have an error in your SQL syntax; check the manual at line 12"
        assert parse_error_line(error, "SQL") == 12

    def test_postgresql_format(self):
        error = 'ERROR:  syntax error at or near "SELCT"\nLINE 3: SELCT * FROM users\n        ^'
        assert parse_error_line(error, "SQL") == 3

    def test_python_traceback(self):
        error = '  File "<string>", line 7, in <module>\nNameError: name \'x\' is not defined'
        assert parse_error_line(error, "PYTHON") == 7

    def test_generic_line_ref(self):
        error = "Error on line 42"
        assert parse_error_line(error) == 42

    def test_case_insensitive(self):
        assert parse_error_line("line 10") == 10
        assert parse_error_line("LINE 10:") == 10
        assert parse_error_line("Line 10") == 10


# ======================================================================
# OutputPanel widget
# ======================================================================

@pytest.fixture
def output_panel(qtbot):
    panel = OutputPanel()
    qtbot.addWidget(panel)
    return panel


class TestOutputPanel:
    """Tests for the new OutputPanel widget."""

    def test_initial_state(self, output_panel):
        assert output_panel._entries == []
        assert output_panel.get_text() == ""
        assert output_panel._list.count() == 0

    def test_append_creates_entry(self, output_panel):
        output_panel.append("Hello world", "info")
        assert len(output_panel._entries) == 1
        assert output_panel._entries[0].level == "info"
        assert output_panel._entries[0].message == "Hello world"
        assert output_panel._list.count() == 1

    def test_log_method(self, output_panel):
        output_panel.log("Info message")
        assert len(output_panel._entries) == 1
        assert output_panel._entries[0].level == "info"

    def test_error_method(self, output_panel):
        output_panel.error("Error message")
        assert len(output_panel._entries) == 1
        assert output_panel._entries[0].level == "error"

    def test_success_method(self, output_panel):
        output_panel.success("Success message")
        assert output_panel._entries[0].level == "success"

    def test_warning_method(self, output_panel):
        output_panel.warning("Warning message")
        assert output_panel._entries[0].level == "warning"

    def test_debug_method(self, output_panel):
        output_panel.debug("Debug message")
        assert output_panel._entries[0].level == "debug"

    def test_append_output_compat(self, output_panel):
        output_panel.append_output("Normal text", error=False)
        output_panel.append_output("Error text", error=True)
        assert len(output_panel._entries) == 2
        assert output_panel._entries[0].level == "info"
        assert output_panel._entries[1].level == "error"

    def test_clear(self, output_panel):
        output_panel.log("msg1")
        output_panel.error("msg2")
        assert len(output_panel._entries) == 2
        output_panel.clear()
        assert len(output_panel._entries) == 0
        assert output_panel._list.count() == 0

    def test_get_text_format(self, output_panel):
        output_panel.log("Hello")
        text = output_panel.get_text()
        assert "Hello" in text
        # Should contain timestamp
        assert "[" in text

    def test_toPlainText_compat(self, output_panel):
        output_panel.log("test")
        assert output_panel.toPlainText() == output_panel.get_text()

    def test_add_entry_structured(self, output_panel):
        entry = LogEntry(
            level="error",
            log_type="SQL",
            message="Syntax error",
            detail="Msg 102, Level 15, State 1, Line 3",
            block_index=0,
            block_name="main_query",
            line_number=3,
            duration_ms=250,
            code_snippet="SELCT * FROM users",
        )
        output_panel.add_entry(entry)
        assert len(output_panel._entries) == 1
        assert output_panel._list.count() == 1

    def test_filter_errors_only(self, output_panel):
        output_panel.log("info msg")
        output_panel.error("error msg")
        output_panel.success("ok msg")
        assert output_panel._list.count() == 3

        # Enable filter
        output_panel._filter_btn.setChecked(True)
        # Should only show error
        assert output_panel._list.count() == 1

        # Disable filter
        output_panel._filter_btn.setChecked(False)
        assert output_panel._list.count() == 3

    def test_filter_shows_warnings_too(self, output_panel):
        output_panel.warning("warn")
        output_panel.log("info")
        output_panel._filter_btn.setChecked(True)
        assert output_panel._list.count() == 1  # only warning

    def test_navigate_signal_on_double_click(self, output_panel, qtbot):
        entry = LogEntry(
            level="error", message="fail", block_index=2, line_number=5,
        )
        output_panel.add_entry(entry)

        with qtbot.waitSignal(output_panel.navigate_to_block, timeout=1000) as blocker:
            item = output_panel._list.item(0)
            output_panel._on_item_double_clicked(item)

        assert blocker.args == [2, 5, 0]

    def test_navigate_default_line_1(self, output_panel, qtbot):
        entry = LogEntry(level="error", message="fail", block_index=1)
        output_panel.add_entry(entry)

        with qtbot.waitSignal(output_panel.navigate_to_block, timeout=1000) as blocker:
            item = output_panel._list.item(0)
            output_panel._on_item_double_clicked(item)

        assert blocker.args == [1, 1, 0]  # default line=1, col=0

    def test_multiple_entries_ordering(self, output_panel):
        for i in range(5):
            output_panel.log(f"msg {i}")
        assert len(output_panel._entries) == 5
        assert output_panel._list.count() == 5
        assert output_panel._entries[0].message == "msg 0"
        assert output_panel._entries[4].message == "msg 4"

    def test_cleared_signal(self, output_panel, qtbot):
        output_panel.log("test")
        with qtbot.waitSignal(output_panel.cleared, timeout=1000):
            output_panel.clear()

    def test_vertical_scrollbar_compat(self, output_panel):
        sb = output_panel.verticalScrollBar()
        assert sb is not None

    def test_get_text_with_log_type(self, output_panel):
        entry = LogEntry(log_type="SQL", message="Done")
        output_panel.add_entry(entry)
        text = output_panel.get_text()
        assert "[SQL]" in text
        assert "Done" in text


# ======================================================================
# OutputPanel._format_duration
# ======================================================================

class TestFormatDuration:
    """Tests for the static _format_duration helper."""

    def test_milliseconds(self):
        assert OutputPanel._format_duration(45) == "45ms"
        assert OutputPanel._format_duration(999) == "999ms"

    def test_seconds(self):
        assert OutputPanel._format_duration(1500) == "1.5s"
        assert OutputPanel._format_duration(30000) == "30.0s"

    def test_minutes(self):
        assert OutputPanel._format_duration(90000) == "1m30s"
        assert OutputPanel._format_duration(125000) == "2m5s"


# ======================================================================
# OutputPanel._truncate
# ======================================================================

class TestTruncate:
    """Tests for the static _truncate helper."""

    def test_short_text(self):
        assert OutputPanel._truncate("hello", 10) == "hello"

    def test_long_text(self):
        result = OutputPanel._truncate("a" * 300, 200)
        assert len(result) == 203  # 200 + "..."
        assert result.endswith("...")

    def test_multiline_uses_first_line(self):
        assert OutputPanel._truncate("line1\nline2\nline3", 200) == "line1"


# ======================================================================
# LogDetailDialog
# ======================================================================

class TestLogDetailDialog:
    """Tests for LogDetailDialog."""

    def test_dialog_creates_for_error(self, qtbot):
        from src.ui.dialogs.log_detail_dialog import LogDetailDialog
        entry = LogEntry(
            level="error",
            log_type="SQL",
            message="Syntax error",
            detail="Msg 102, Level 15, State 1, Line 3\nIncorrect syntax.",
            block_index=0,
            block_name="query1",
            line_number=3,
            duration_ms=100,
            code_snippet="SELCT * FROM users",
            connection_name="local",
            database_name="testdb",
        )
        dlg = LogDetailDialog(entry)
        qtbot.addWidget(dlg)
        assert dlg.windowTitle()

    def test_dialog_creates_for_info(self, qtbot):
        from src.ui.dialogs.log_detail_dialog import LogDetailDialog
        entry = LogEntry(level="info", message="All good")
        dlg = LogDetailDialog(entry)
        qtbot.addWidget(dlg)
        assert dlg.windowTitle()

    def test_resolve_signal(self, qtbot):
        from src.ui.dialogs.log_detail_dialog import LogDetailDialog
        entry = LogEntry(
            level="error",
            log_type="SQL",
            message="fail",
            detail="bad query",
            code_snippet="SELECT * FRM t",
            block_index=0,
            block_name="q1",
        )
        dlg = LogDetailDialog(entry)
        qtbot.addWidget(dlg)

        with qtbot.waitSignal(dlg.resolve_requested, timeout=1000) as blocker:
            dlg._on_resolve_copilot()

        ctx = blocker.args[0]
        assert ctx["error"] == "bad query"
        assert ctx["code"] == "SELECT * FRM t"
        assert ctx["block_name"] == "q1"


# ======================================================================
# _find_token_in_sql
# ======================================================================

class TestFindTokenInSql:
    """Tests for _find_token_in_sql()."""

    def test_none_inputs(self):
        assert _find_token_in_sql(None, "SELECT 1") is None
        assert _find_token_in_sql("col", None) is None
        assert _find_token_in_sql("", "SELECT 1") is None
        assert _find_token_in_sql("col", "") is None

    def test_single_line(self):
        sql = "SELECT pa.adicionalid FROM pedidos pa"
        result = _find_token_in_sql("adicionalid", sql)
        assert result is not None
        assert result[0] == 1  # line 1
        assert result[1] == 11  # column 11 (after "SELECT pa.")

    def test_multiline(self):
        sql = "SELECT\n  pa.nome,\n  pa.adicionalid\nFROM pedidos pa"
        result = _find_token_in_sql("adicionalid", sql)
        assert result is not None
        assert result[0] == 3  # line 3
        assert result[1] == 6  # "  pa.adicionalid" -> col 6

    def test_case_insensitive(self):
        sql = "SELECT PA.AdicionalId FROM pedidos"
        result = _find_token_in_sql("adicionalid", sql)
        assert result is not None
        assert result[0] == 1

    def test_not_found(self):
        sql = "SELECT id FROM users"
        assert _find_token_in_sql("nonexistent", sql) is None

    def test_qualified_column(self):
        sql = "SELECT a.id,\n  b.nome\nFROM tab_a a\nJOIN tab_b b ON a.xid = b.xid"
        result = _find_token_in_sql("b.xid", sql)
        assert result is not None
        assert result[0] == 4


# ======================================================================
# _extract_error_token
# ======================================================================

class TestExtractErrorToken:
    """Tests for _extract_error_token()."""

    def test_unknown_column_mysql(self):
        error = "(1054, \"Unknown column 'pa.adicionalid' in 'on clause'\")"
        assert _extract_error_token(error) == "pa.adicionalid"

    def test_invalid_column_sqlserver(self):
        error = "Invalid column name 'adicionalid'."
        assert _extract_error_token(error) == "adicionalid"

    def test_column_not_exist_postgresql(self):
        error = 'ERROR: column "adicionalid" does not exist'
        assert _extract_error_token(error) == "adicionalid"

    def test_invalid_object_name(self):
        error = "Invalid object name 'dbo.pedidos'."
        assert _extract_error_token(error) == "dbo.pedidos"

    def test_table_not_exist_mysql(self):
        error = "Table 'mydb.pedidos' doesn't exist"
        assert _extract_error_token(error) == "mydb.pedidos"

    def test_relation_not_exist_postgresql(self):
        error = 'ERROR: relation "pedidos" does not exist'
        assert _extract_error_token(error) == "pedidos"

    def test_near_single_quotes(self):
        error = "You have an error in your SQL syntax; check near 'SELCT'"
        assert _extract_error_token(error) == "SELCT"

    def test_no_token(self):
        assert _extract_error_token("Connection refused") is None
        assert _extract_error_token("") is None


# ======================================================================
# parse_error_position
# ======================================================================

class TestParseErrorPosition:
    """Tests for parse_error_position()."""

    def test_line_from_message_no_sql(self):
        error = "Msg 102, Level 15, State 1, Line 3\nIncorrect syntax near 'SELCT'."
        line, col = parse_error_position(error)
        assert line == 3
        assert col is None

    def test_line_and_column_from_token(self):
        error = "(1054, \"Unknown column 'pa.adicionalid' in 'on clause'\")"
        sql = "SELECT pa.nome\nFROM pedidos pa\nJOIN adicional ad\n  ON pa.adicionalid = ad.id"
        line, col = parse_error_position(error, sql, "SQL")
        assert line == 4
        assert col == 6  # "  ON pa.adicionalid..." -> col 6

    def test_fallback_token_no_line_in_message(self):
        # MySQL 1054 has NO line number in the message
        error = "(1054, \"Unknown column 'xpto' in 'field list'\")"
        sql = "SELECT id,\n  xpto\nFROM users"
        line, col = parse_error_position(error, sql, "SQL")
        assert line == 2
        assert col == 3

    def test_no_info_at_all(self):
        error = "Connection timed out"
        line, col = parse_error_position(error, "SELECT 1")
        assert line is None
        assert col is None

    def test_python_traceback(self):
        error = '  File "<string>", line 5, in <module>\nNameError: name \'xx\' is not defined'
        code = "a = 1\nb = 2\nc = 3\nd = 4\nxx = yy"
        line, col = parse_error_position(error, code, "PYTHON")
        assert line == 5

    def test_line_from_message_plus_token_on_same_line(self):
        error = "Msg 102, Level 15, State 1, Line 2\nIncorrect syntax near 'SELCT'."
        sql = "SELECT id FROM users\nSELCT * FROM orders"
        line, col = parse_error_position(error, sql, "SQL")
        assert line == 2
        assert col == 1  # SELCT starts at col 1

    def test_empty_sql(self):
        error = "(1054, \"Unknown column 'x' in 'field list'\")"
        line, col = parse_error_position(error, "", "SQL")
        assert line is None


# ======================================================================
# Navigate signal includes column
# ======================================================================

class TestNavigateSignalColumn:
    """Tests that navigate_to_block emits block_index, line, column."""

    def test_navigate_emits_three_args(self, output_panel, qtbot):
        entry = LogEntry(
            level="error",
            log_type="SQL",
            message="Error",
            block_index=2,
            line_number=4,
            column_number=42,
        )
        output_panel.add_entry(entry)

        with qtbot.waitSignal(output_panel.navigate_to_block, timeout=1000) as blocker:
            item = output_panel._list.item(0)
            output_panel._on_item_double_clicked(item)

        assert blocker.args == [2, 4, 42]

    def test_navigate_no_column(self, output_panel, qtbot):
        entry = LogEntry(
            level="error",
            log_type="SQL",
            message="Error",
            block_index=1,
            line_number=3,
        )
        output_panel.add_entry(entry)

        with qtbot.waitSignal(output_panel.navigate_to_block, timeout=1000) as blocker:
            item = output_panel._list.item(0)
            output_panel._on_item_double_clicked(item)

        assert blocker.args == [1, 3, 0]

    def test_column_in_log_entry(self):
        entry = LogEntry(column_number=42)
        assert entry.column_number == 42

        entry2 = LogEntry()
        assert entry2.column_number is None
