from datetime import date

import pytest

from src.core.session import Session
from src.utils.sql_parameter_service import (
    SqlParameterError,
    extract_shared_parameter_names,
    extract_shared_parameter_tokens,
    merge_shared_parameter_definitions,
    prepare_generic_sql,
    prepare_python_code_with_shared_parameters,
    prepare_sqlserver_batch,
    shared_parameter_id,
)


def _shared_param(name, value="123", sql_type="integer", input_kind="value", options=None, default_value=""):
    return {
        "id": shared_parameter_id(name),
        "name": name,
        "order": 0,
        "sql_type": sql_type,
        "input_kind": input_kind,
        "value": value,
        "default_value": default_value,
        "required": True,
        "options": options or [],
        "multi_select": input_kind == "multi_choice",
    }


class TestSharedParameterScanner:
    def test_extract_shared_parameter_tokens(self):
        text = "select * from t where id = {{x}} and name = {{ y }}"
        assert extract_shared_parameter_names(text) == ["x", "y"]

    def test_triple_brace_is_not_a_token(self):
        text = "select {{{a}}} from t"
        assert extract_shared_parameter_names(text) == []


class TestSharedParameterMerge:
    def test_merge_shared_definitions_aggregates_across_blocks(self):
        codes = [
            "select * from a where id = {{x}}",
            "print({{x}})",
        ]
        merged = merge_shared_parameter_definitions(codes, [])
        assert [item["name"] for item in merged] == ["x"]
        assert merged[0]["id"] == shared_parameter_id("x")

    def test_merge_preserves_existing_configuration(self):
        existing = [_shared_param("x", value="99", sql_type="integer")]
        merged = merge_shared_parameter_definitions(["where id = {{x}}"], existing)
        assert merged[0]["value"] == "99"


class TestSharedSqlPreparation:
    def test_prepare_generic_sql_replaces_shared_token(self):
        prepared = prepare_generic_sql(
            "select * from t where id = {{x}}",
            [_shared_param("x", value="7", sql_type="integer")],
        )
        assert prepared.query == "select * from t where id = :shared_x"
        assert prepared.params == {"shared_x": 7}

    def test_prepare_generic_sql_mixed_block_and_shared(self):
        block_param = {
            "id": "sqlparam:a",
            "name": "a",
            "order": 0,
            "sql_type": "integer",
            "input_kind": "value",
            "value": "1",
            "default_value": "",
            "required": True,
            "options": [],
            "multi_select": False,
        }
        prepared = prepare_generic_sql(
            "select * from t where a = @a and b = {{b}}",
            [block_param, _shared_param("b", value="2", sql_type="integer")],
        )
        assert prepared.query == "select * from t where a = :a and b = :shared_b"
        assert prepared.params == {"a": 1, "shared_b": 2}

    def test_prepare_sqlserver_batch_shared_positional(self):
        block_param = {
            "id": "sqlparam:a",
            "name": "a",
            "order": 0,
            "sql_type": "integer",
            "input_kind": "value",
            "value": "1",
            "default_value": "",
            "required": True,
            "options": [],
            "multi_select": False,
        }
        prepared = prepare_sqlserver_batch(
            "select @a as a, {{b}} as b",
            [block_param, _shared_param("b", value="2", sql_type="integer")],
        )
        assert "DECLARE @a INT = ?;" in prepared.query
        assert "DECLARE @shared_b INT = ?;" in prepared.query
        assert "@shared_b" in prepared.query
        assert prepared.params == [1, 2]


class TestSharedPythonPreparation:
    def test_substitute_shared_in_python_string(self):
        code = 'print("date=", {{nome}})'
        prepared = prepare_python_code_with_shared_parameters(
            code,
            [_shared_param("nome", value="Joao", sql_type="text")],
        )
        assert prepared == 'print("date=", \'Joao\')'

    def test_substitute_shared_in_python_boolean(self):
        code = "active = {{active}}"
        prepared = prepare_python_code_with_shared_parameters(
            code,
            [_shared_param("active", value="true", sql_type="boolean")],
        )
        assert prepared == "active = True"

    def test_substitute_shared_in_python_date(self):
        code = "start = {{start}}"
        prepared = prepare_python_code_with_shared_parameters(
            code,
            [_shared_param("start", value="2024-07-09", sql_type="date")],
        )
        assert prepared == "start = '2024-07-09'"

    def test_substitute_shared_in_python_missing_value_raises(self):
        with pytest.raises(SqlParameterError):
            prepare_python_code_with_shared_parameters(
                "value = {{missing}}",
                [_shared_param("missing", value="", sql_type="text")],
            )


class TestSessionSharedPersistence:
    def test_session_serialize_roundtrip_shared_parameters(self):
        session = Session(session_id="s1", title="Tab")
        session.shared_parameters = [_shared_param("x", value="1")]
        session.shared_parameters_enabled = True

        restored = Session.deserialize(session.serialize())
        assert restored.shared_parameters[0]["name"] == "x"
        assert restored.shared_parameters_enabled is True


def test_shared_panel_hides_when_no_parameters(qtbot):
    from src.editors.sql_parameters_panel import SharedParametersPanel

    panel = SharedParametersPanel()
    qtbot.addWidget(panel)

    panel.set_parameters([_shared_param("x", value="1")])
    assert panel.isVisible() is True

    panel.set_parameters([])
    assert panel.isVisible() is False
