from datetime import date

from src.utils.sql_parameter_service import (
    extract_sql_parameter_names,
    merge_parameter_definitions,
    prepare_generic_sql,
    prepare_sqlserver_batch,
    validate_and_convert_parameters,
)


def _param(name, value="123", sql_type="integer", input_kind="value", options=None, default_value=""):
    return {
        "id": f"sqlparam:{name.lower()}",
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


class TestSqlParameterParser:
    def test_detects_unique_parameters_in_order(self):
        sql = "select * from pessoa where id = @pessoaId and loja = @lojaId or id = @pessoaId"
        assert extract_sql_parameter_names(sql) == ["pessoaId", "lojaId"]

    def test_ignores_strings_comments_and_system_variables(self):
        sql = """
        select '@literal' as value, @@ROWCOUNT as rows
        -- where id = @commented
        /* and x = @blockComment */
        from pessoa where id = @id
        """
        assert extract_sql_parameter_names(sql) == ["id"]

    def test_merge_preserves_existing_configuration(self):
        existing = [_param("id", value="42", sql_type="integer")]
        merged = merge_parameter_definitions("select * from t where id = @id and name = @name", existing)
        assert [item["name"] for item in merged] == ["id", "name"]
        assert merged[0]["value"] == "42"
        assert merged[0]["sql_type"] == "integer"
        assert merged[1]["sql_type"] == "text"

    def test_merge_drops_existing_parameters_removed_from_query(self):
        existing = [_param("id", value="42", sql_type="integer"), _param("name", value="ana", sql_type="text")]

        merged = merge_parameter_definitions("select * from t where id = @id", existing)

        assert [item["name"] for item in merged] == ["id"]
        assert merged[0]["value"] == "42"

    def test_name_heuristics_assign_expected_types(self):
        merged = merge_parameter_definitions(
            "select * from t where data = @data and valor = @valor and nome = @nome"
        )

        by_name = {item["name"]: item for item in merged}
        assert by_name["data"]["sql_type"] == "date"
        assert by_name["data"]["default_value"] == ""
        assert by_name["valor"]["sql_type"] == "decimal"
        assert by_name["nome"]["sql_type"] == "text"

    def test_inferred_types_do_not_create_implicit_default_value(self):
        schema = {
            "columns": {
                "dbo.pedidos": [
                    {"name": "encerramento", "type": "date"},
                ]
            }
        }

        merged = merge_parameter_definitions(
            "select * from dbo.pedidos where encerramento = @encerramento",
            sql_schema=schema,
        )

        assert merged[0]["sql_type"] == "date"
        assert merged[0]["default_value"] == ""

    def test_schema_inference_prefers_compared_column_type(self):
        schema = {
            "columns": {
                "dbo.pedidos": [
                    {"name": "encerramento", "type": "date"},
                    {"name": "ativo", "type": "bit"},
                ]
            }
        }

        merged = merge_parameter_definitions(
            "select * from dbo.pedidos where encerramento = @flagDate and ativo = @flag",
            sql_schema=schema,
        )

        by_name = {item["name"]: item for item in merged}
        assert by_name["flagDate"]["sql_type"] == "date"
        assert by_name["flagDate"]["type_source"] == "schema"
        assert by_name["flag"]["sql_type"] == "boolean"


class TestSqlParameterValidation:
    def test_missing_required_value_returns_error(self):
        converted, errors = validate_and_convert_parameters(
            "select * from t where id = @id",
            [_param("id", value="")],
        )
        assert converted == []
        assert errors
        assert "@id" in errors[0]

    def test_converts_integer_value(self):
        converted, errors = validate_and_convert_parameters(
            "select * from t where id = @id",
            [_param("id", value="77")],
        )
        assert errors == []
        assert converted[0]["converted_value"] == 77

    def test_validates_fixed_choice_options(self):
        converted, errors = validate_and_convert_parameters(
            "select * from t where status = @status",
            [_param("status", value="A", sql_type="text", input_kind="choice", options=["A", "I"])],
        )
        assert errors == []
        assert converted[0]["converted_value"] == "A"

    def test_uses_default_value_when_field_is_blank(self):
        converted, errors = validate_and_convert_parameters(
            "select * from t where data = @data",
            [_param("data", value="", sql_type="date", default_value="today")],
        )

        assert errors == []
        assert converted[0]["converted_value"] == date.today()

    def test_null_default_value_allows_required_blank_parameter(self):
        converted, errors = validate_and_convert_parameters(
            "select * from t where encerramento = @encerramento",
            [_param("encerramento", value="", sql_type="date", default_value="null")],
        )

        assert errors == []
        assert converted[0]["converted_value"] is None


class TestSqlParameterPreparation:
    def test_generic_sql_uses_named_binds(self):
        prepared = prepare_generic_sql(
            "select * from pessoa where id = @id",
            [_param("id", value="10")],
        )
        assert prepared.query == "select * from pessoa where id = :id"
        assert prepared.params == {"id": 10}

    def test_generic_multi_choice_expands_in_clause(self):
        prepared = prepare_generic_sql(
            "select * from pessoa where status in (@status)",
            [_param("status", value=["A", "I"], sql_type="text", input_kind="multi_choice", options=["A", "I"])],
        )
        assert prepared.query == "select * from pessoa where status in (:status_0, :status_1)"
        assert prepared.params == {"status_0": "A", "status_1": "I"}

    def test_sqlserver_declares_scalar_parameters(self):
        prepared = prepare_sqlserver_batch(
            "select * from pessoa where id = @id",
            [_param("id", value="10")],
        )
        assert prepared.query.startswith("DECLARE @id INT = ?;")
        assert "where id = @id" in prepared.query
        assert prepared.params == [10]

    def test_sqlserver_multi_choice_expands_in_clause(self):
        prepared = prepare_sqlserver_batch(
            "select * from pessoa where status in (@status)",
            [_param("status", value=["A", "I"], sql_type="text", input_kind="multi_choice", options=["A", "I"])],
        )
        assert "status in (?, ?)" in prepared.query
        assert prepared.params == ["A", "I"]
