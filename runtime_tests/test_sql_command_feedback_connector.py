"""SQL feedback is driver metadata, never a guess from a result's text."""

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pyodbc
import pytest

from src.database.database_connector import DatabaseConnector, OperationCancelled


@dataclass
class Result:
    rowcount: object = -1
    columns: tuple = ()
    rows: tuple = ()


class Cursor:
    def __init__(self, physical):
        self.physical = physical
        self.messages = []
        self.description = None
        self.rowcount = -1
        self.rows = []
        self.following = []

    def _set(self, result):
        if isinstance(result, BaseException):
            raise result
        self.description = [(column,) for column in result.columns] or None
        self.rowcount = result.rowcount
        self.rows = list(result.rows)

    def execute(self, sql, *params):
        self.physical.executed.append(sql)
        if sql == "SELECT CONNECTION_ID()":
            self._set(Result(rows=((7,),)))
            return
        results = list(self.physical.plan[sql])
        self._set(results.pop(0))
        self.following = results
        if self.physical.cancel_at == sql:
            self.physical.connector.request_cancel()

    def fetchmany(self, size=1000):
        rows, self.rows = self.rows[:size], self.rows[size:]
        return rows

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def nextset(self):
        if not self.following:
            return False
        self._set(self.following.pop(0))
        return True

    def close(self):
        pass


class Physical:
    def __init__(self, plan):
        self.plan = plan
        self.executed = []
        self.commits = 0
        self.closed = 0
        self.cancel_at = None

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed += 1


def connector_for(db_type, plan):
    physical = Physical(plan)
    connector = DatabaseConnector()
    connector.db_type = db_type
    connector.engine = SimpleNamespace(raw_connection=lambda: physical)
    connector._reconcile_execution_context = lambda _raw: None
    physical.connector = connector
    return connector, physical


def feedback(index, command, count=None):
    return {"statement_index": index, "command": command, "rows_affected": count}


@pytest.mark.parametrize("db_type", ["mysql", "mariadb", "postgresql", "sqlite"])
@pytest.mark.parametrize("count, expected", [(0, 0), (14702, 14702), (-1, None), (None, None)])
def test_dml_feedback_marks_only_legacy_message_frames(db_type, count, expected):
    statement = "DELETE FROM codigodebarra"
    connector, physical = connector_for(db_type, {statement: [Result(count)]})
    result = connector.execute_query(statement)
    assert isinstance(result, pd.DataFrame)
    assert result.attrs["datapyn_command_result"] is True
    assert result.attrs["datapyn_command_results"] == [feedback(1, "DELETE", expected)]
    assert list(result.columns) == ["Result"]
    assert physical.executed.count(statement) == 1
    assert physical.commits == 1


@pytest.mark.parametrize("db_type", ["mysql", "mariadb", "postgresql", "sqlite", "databricks"])
def test_multiple_commands_report_each_count_without_reexecution(db_type):
    statements = ["DELETE FROM t", "UPDATE t SET n = 1", "CREATE TABLE other (n INT)", "DROP TABLE other"]
    connector, physical = connector_for(db_type, dict(zip(statements, [[Result(7)], [Result(0)], [Result()], [Result()]])))
    result = connector.execute_query("; ".join(statements))
    assert result.attrs["datapyn_command_result"] is True
    assert result.attrs["datapyn_command_results"] == [
        feedback(1, "DELETE", 7), feedback(2, "UPDATE", 0), feedback(3, "CREATE"), feedback(4, "DROP"),
    ]
    assert [sql for sql in physical.executed if sql != "SELECT CONNECTION_ID()"] == statements


@pytest.mark.parametrize("db_type", ["mysql", "mariadb", "postgresql", "sqlite", "databricks"])
def test_mixed_results_attach_feedback_once_and_preserve_real_result_column(db_type):
    statements = ["DELETE FROM t", "SELECT 'Command executed successfully.' AS Result", "UPDATE t SET n = 1", "SELECT n FROM t"]
    connector, _physical = connector_for(db_type, {
        statements[0]: [Result(3)],
        statements[1]: [Result(1, ("Result",), (("Command executed successfully.",),))],
        statements[2]: [Result(0)],
        statements[3]: [Result(0, ("n",))],
    })
    frames = connector.execute_query("; ".join(statements))
    assert len(frames) == 2
    assert frames[0]["Result"].tolist() == ["Command executed successfully."]
    assert frames[1].empty and list(frames[1].columns) == ["n"]
    assert all(frame.attrs.get("datapyn_command_result") is not True for frame in frames)
    assert frames[0].attrs["datapyn_command_results"] == [feedback(1, "DELETE", 3), feedback(3, "UPDATE", 0)]
    assert "datapyn_command_results" not in frames[1].attrs


@pytest.mark.parametrize("db_type", ["postgresql", "sqlite"])
def test_dml_returning_keeps_real_rows_and_command_count(db_type):
    statement = "UPDATE t SET n = 1 RETURNING n"
    connector, physical = connector_for(db_type, {statement: [Result(2, ("n",), ((1,), (1,)))]})
    result = connector.execute_query(statement)
    assert result["n"].tolist() == [1, 1]
    assert result.attrs.get("datapyn_command_result") is not True
    assert result.attrs["datapyn_command_results"] == [feedback(1, "UPDATE", 2)]
    assert physical.commits == 1


def test_cte_dml_is_detected_without_confusing_commands_inside_cte():
    statement = "/* comment UPDATE */ WITH src AS (SELECT n FROM t) UPDATE t SET n = 1"
    connector, _physical = connector_for("postgresql", {statement: [Result(4)]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_results"] == [feedback(1, "UPDATE", 4)]


@pytest.mark.parametrize("db_type", ["postgresql", "sqlserver"])
def test_select_into_is_command_feedback_instead_of_an_empty_grid(db_type):
    statement = "SELECT n INTO new_table FROM t"
    connector, _physical = connector_for(db_type, {statement: [Result(7)]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_result"] is True
    assert result.attrs["datapyn_command_results"] == [feedback(1, "SELECT", 7)]


@pytest.mark.parametrize("db_type", ["mysql", "mariadb", "postgresql", "sqlite", "databricks"])
def test_completed_feedback_survives_later_error_and_copies_are_defensive(db_type):
    connector, _physical = connector_for(db_type, {"DELETE FROM t": [Result(5)], "FAIL": [RuntimeError("invalid SQL")]})
    events = []
    connector.command_result_callback = events.append
    with pytest.raises(RuntimeError, match="invalid SQL"):
        connector.execute_query("DELETE FROM t; FAIL")
    assert events == [feedback(1, "DELETE", 5)]
    assert connector.get_last_command_results() == events
    events[0]["rows_affected"] = 999
    snapshot = connector.get_last_command_results()
    snapshot[0]["command"] = "FAKE"
    assert connector.get_last_command_results() == [feedback(1, "DELETE", 5)]


@pytest.mark.parametrize("db_type", ["mysql", "mariadb", "postgresql", "sqlite", "databricks"])
def test_cancel_retains_previous_commands_and_never_executes_next_command(db_type):
    connector, physical = connector_for(db_type, {"DELETE FROM t": [Result(5)], "UPDATE t SET n = 1": [Result(2)]})
    physical.cancel_at = "UPDATE t SET n = 1"
    with pytest.raises(OperationCancelled):
        connector.execute_query("DELETE FROM t; UPDATE t SET n = 1; DROP TABLE t")
    assert connector.get_last_command_results() == [feedback(1, "DELETE", 5)]
    assert "DROP TABLE t" not in physical.executed


def test_starting_a_new_query_resets_feedback_and_observer_errors_do_not_change_sql():
    connector, physical = connector_for("sqlite", {"DELETE FROM t": [Result(1)], "SELECT n FROM t": [Result(1, ("n",), ((7,),))]})
    connector.command_result_callback = lambda _result: (_ for _ in ()).throw(RuntimeError("observer failed"))
    connector.execute_query("DELETE FROM t")
    result = connector.execute_query("SELECT n FROM t")
    assert result["n"].tolist() == [7]
    assert connector.get_last_command_results() == []
    assert physical.executed == ["DELETE FROM t", "SELECT n FROM t"]


def test_postgresql_autocommit_commands_keep_indices_in_mixed_script():
    statement = "CREATE DATABASE example"
    connector, physical = connector_for("postgresql", {"SELECT 7": [Result(1, ("n",), ((7,),))]})
    connection = MagicMock()
    connection.execution_options.return_value.execute.return_value.rowcount = -1
    connector.engine.connect = MagicMock(return_value=connection)
    result = connector.execute_query(f"SELECT 7; {statement}")
    assert result.attrs["datapyn_command_results"] == [feedback(2, "CREATE")]
    connection.__enter__.return_value.execution_options.assert_called_once_with(isolation_level="AUTOCOMMIT")
    assert physical.executed == ["SELECT 7"]


def test_databricks_delta_dml_metrics_are_messages_but_select_metrics_are_real_data():
    statement = "MERGE INTO target USING source ON target.n = source.n WHEN MATCHED THEN DELETE"
    columns = ("num_affected_rows", "num_updated_rows", "num_deleted_rows", "num_inserted_rows")
    connector, _physical = connector_for("databricks", {statement: [Result(-1, columns, ((12, 0, 12, 0),))], "SELECT num_affected_rows FROM stats": [Result(1, ("num_affected_rows",), ((12,),))]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_result"] is True
    assert result.attrs["datapyn_command_results"] == [feedback(1, "MERGE", 12)]
    result = connector.execute_query("SELECT num_affected_rows FROM stats")
    assert result.attrs.get("datapyn_command_result") is not True
    assert connector.get_last_command_results() == []


def test_databricks_mixed_metadata_is_carried_by_real_frame_only():
    connector, _physical = connector_for("databricks", {"DELETE FROM t": [Result(-1, ("num_affected_rows",), ((0,),))], "SELECT n FROM t": [Result(1, ("n",), ((9,),))]})
    frames = connector.execute_query("DELETE FROM t; SELECT n FROM t")
    assert frames[0].attrs["datapyn_command_result"] is True
    assert "datapyn_command_results" not in frames[0].attrs
    assert frames[1].attrs["datapyn_command_results"] == [feedback(1, "DELETE", 0)]


def test_sqlserver_four_dml_commands_capture_each_nextset_count():
    statement = "; ".join(["DELETE FROM codigodebarra"] * 4)
    connector, physical = connector_for("sqlserver", {statement: [Result(14702), Result(0), Result(0), Result(-1)]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_result"] is True
    assert result.attrs["datapyn_command_results"] == [feedback(1, "DELETE", 14702), feedback(2, "DELETE", 0), feedback(3, "DELETE", 0), feedback(4, "DELETE")]
    assert physical.executed == [statement]
    assert physical.commits == 1


def test_sqlserver_mixed_batches_keep_select_result_and_script_statement_indices():
    batch = "DELETE FROM t; SELECT 'text' AS Result; UPDATE t SET n = 1"
    connector, physical = connector_for("sqlserver", {batch: [Result(2), Result(1, ("Result",), (("text",),)), Result(0)], "DROP TABLE t": [Result()]})
    result = connector.execute_query(f"{batch}\nGO\nDROP TABLE t")
    assert result["Result"].tolist() == ["text"]
    assert result.attrs.get("datapyn_command_result") is not True
    assert result.attrs["datapyn_command_results"] == [feedback(1, "DELETE", 2), feedback(3, "UPDATE", 0), feedback(4, "DROP")]
    assert physical.executed == [batch, "DROP TABLE t"]


def test_sqlserver_nocount_returns_unknown_per_command_without_fabricating_zero():
    statement = "SET NOCOUNT ON; DELETE FROM t; UPDATE t SET n = 1"
    connector, _physical = connector_for("sqlserver", {statement: [Result()]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_results"] == [feedback(1, "SET"), feedback(2, "DELETE"), feedback(3, "UPDATE")]


def test_sqlserver_skips_set_tokens_when_assigning_dml_counts():
    statement = "SET NOCOUNT OFF; DELETE FROM t"
    connector, _physical = connector_for("sqlserver", {statement: [Result(3)]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_results"] == [feedback(1, "SET"), feedback(2, "DELETE", 3)]


def test_sqlserver_output_remains_real_data_with_following_count_token():
    statement = "UPDATE t SET n = 1 OUTPUT inserted.n"
    connector, _physical = connector_for("sqlserver", {statement: [Result(-1, ("n",), ((1,), (1,))), Result(2)]})
    result = connector.execute_query(statement)
    assert result["n"].tolist() == [1, 1]
    assert result.attrs.get("datapyn_command_result") is not True
    assert result.attrs["datapyn_command_results"] == [feedback(1, "UPDATE", 2)]


def test_sqlserver_deferred_error_retains_only_confirmed_completed_commands():
    statement = "DELETE FROM t; FAIL"
    connector, _physical = connector_for("sqlserver", {statement: [Result(5), pyodbc.Error("syntax error")]})
    with pytest.raises(Exception, match="syntax error"):
        connector.execute_query(statement)
    assert connector.get_last_command_results() == [feedback(1, "DELETE", 5)]


def test_sqlserver_unknown_count_before_deferred_error_is_not_claimed_as_success():
    statement = "FAIL"
    connector, _physical = connector_for("sqlserver", {statement: [Result(), pyodbc.Error("syntax error")]})
    with pytest.raises(Exception, match="syntax error"):
        connector.execute_query(statement)
    assert connector.get_last_command_results() == []


def test_sqlserver_newline_commands_without_semicolons_keep_all_driver_counts():
    statement = "DELETE FROM t\nDELETE FROM t\nUPDATE t SET n = 1"
    connector, physical = connector_for("sqlserver", {statement: [Result(7), Result(0), Result(2)]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_results"] == [feedback(1, "DELETE", 7), feedback(2, "DELETE", 0), feedback(3, "UPDATE", 2)]
    assert physical.executed == [statement]


def test_sqlserver_unknown_extra_tokens_keep_counts_and_next_batch_indices_unique():
    # Same-line omitted separators deliberately fail conservative parsing.
    batch = "DELETE FROM t UPDATE other SET n = 1"
    connector, _physical = connector_for("sqlserver", {batch: [Result(7), Result(2)], "DROP TABLE t": [Result()]})
    result = connector.execute_query(f"{batch}\nGO\nDROP TABLE t")
    assert result.attrs["datapyn_command_results"] == [feedback(1, "DELETE", 7), feedback(2, "SQL", 2), feedback(3, "DROP")]


def test_sqlserver_control_flow_uses_only_reported_counts_not_unexecuted_branches():
    batch = "IF 1=1\nBEGIN\nDELETE FROM t;\nEND\nELSE\nBEGIN\nUPDATE t SET n = 1;\nEND"
    connector, physical = connector_for("sqlserver", {batch: [Result(7)], "DROP TABLE t": [Result()]})
    result = connector.execute_query(f"{batch}\nGO\nDROP TABLE t")
    assert result.attrs["datapyn_command_results"] == [feedback(1, "SQL", 7), feedback(2, "DROP")]
    assert physical.executed == [batch, "DROP TABLE t"]


def test_sqlserver_control_flow_multiple_counts_and_procedure_tokens_are_preserved():
    batch = "IF 1=1 BEGIN DELETE FROM t; UPDATE t SET n = 1; END"
    connector, _physical = connector_for("sqlserver", {batch: [Result(7), Result(2), Result(0)], "EXEC p": [Result(4), Result(1)]})
    result = connector.execute_query(f"{batch}\nGO\nEXEC p")
    assert result.attrs["datapyn_command_results"] == [feedback(1, "SQL", 7), feedback(2, "SQL", 2), feedback(3, "SQL", 0), feedback(4, "SQL", 4), feedback(5, "SQL", 1)]


def test_sqlserver_declare_never_receives_a_later_dml_count():
    batch = "DECLARE @n INT = 1\nDELETE FROM t\nUPDATE t SET n = 1"
    connector, _physical = connector_for("sqlserver", {batch: [Result(7), Result(2)]})
    result = connector.execute_query(batch)
    assert result.attrs["datapyn_command_results"] == [feedback(1, "DECLARE"), feedback(2, "DELETE", 7), feedback(3, "UPDATE", 2)]


def test_sqlserver_insert_select_and_union_are_not_split_into_fake_commands():
    statement = "INSERT INTO t (n)\nSELECT n FROM source\nUNION ALL\nSELECT n FROM other"
    connector, _physical = connector_for("sqlserver", {statement: [Result(8)]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_results"] == [feedback(1, "INSERT", 8)]


def test_sqlserver_create_procedure_body_is_one_unexecuted_definition():
    statement = "CREATE PROCEDURE p AS BEGIN DELETE FROM t; UPDATE t SET n = 1; END"
    connector, _physical = connector_for("sqlserver", {statement: [Result()]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_results"] == [feedback(1, "CREATE")]


@pytest.mark.parametrize("statement", ["SELECT @n = 1", "SELECT TOP (1) @n = n FROM t", "WITH src AS (SELECT n FROM t) SELECT @n = n FROM src"])
def test_sqlserver_variable_select_without_table_is_execution_feedback(statement):
    connector, physical = connector_for("sqlserver", {statement: [Result()]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_result"] is True
    assert result.attrs["datapyn_command_results"] == [feedback(1, "SELECT")]
    assert physical.executed == [statement]


def test_sqlserver_multiple_assignments_have_separate_feedback():
    statement = "SELECT @n = 1; SELECT @m = 2"
    connector, _physical = connector_for("sqlserver", {statement: [Result(), Result()]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_results"] == [feedback(1, "SELECT"), feedback(2, "SELECT")]


def test_sqlserver_unrecognized_success_without_table_still_has_one_execution_message():
    statement = "SELECT ALL @n = 1"
    connector, _physical = connector_for("sqlserver", {statement: [Result()]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_result"] is True
    assert result.attrs["datapyn_command_results"] == [feedback(1, "SELECT")]


@pytest.mark.parametrize("db_type", ["mysql", "mariadb", "postgresql", "sqlite", "databricks", "sqlserver"])
def test_empty_tabular_select_with_description_is_never_a_command(db_type):
    statement = "SELECT n FROM t WHERE 1 = 0"
    connector, _physical = connector_for(db_type, {statement: [Result(0, ("n",))]})
    result = connector.execute_query(statement)
    assert result.empty and list(result.columns) == ["n"]
    assert result.attrs.get("datapyn_command_result") is not True
    assert connector.get_last_command_results() == []


@pytest.mark.parametrize("db_type", ["mysql", "mariadb", "postgresql", "sqlite", "databricks"])
def test_successful_statement_without_description_has_feedback_instead_of_empty_frame(db_type):
    statement = "SELECT n"
    connector, _physical = connector_for(db_type, {statement: [Result()]})
    result = connector.execute_query(statement)
    assert result.attrs["datapyn_command_result"] is True
    assert result.attrs["datapyn_command_results"] == [feedback(1, "SELECT")]
