"""Offline destructive SQL review across dialects and managed Python calls."""

import json

import pytest

from datapyn_runtime.sql_safety import analyze_python, analyze_sql


@pytest.mark.parametrize("dialect", ["sqlserver", "postgresql", "mysql", "mariadb", "databricks", "sqlite"])
@pytest.mark.parametrize("code,operation,filtered", [
    ("DELETE FROM items", "DELETE", False),
    ("DELETE FROM items WHERE id=1", "DELETE", True),
    ("UPDATE items SET active=0", "UPDATE", False),
    ("UPDATE items SET active=0 WHERE id=1", "UPDATE", True),
    ("TRUNCATE TABLE items", "TRUNCATE", False),
    ("DROP TABLE items", "DROP", False),
    ("ALTER TABLE items DROP COLUMN secret", "ALTER", False),
])
def test_every_destructive_mutation_requires_review_even_with_where(dialect, code, operation, filtered):
    risks = analyze_sql(code, dialect)
    assert len(risks) == 1
    assert risks[0]["operation"] == operation
    assert risks[0]["target"] == "items"
    assert risks[0]["has_where"] is filtered
    assert risks[0]["preview"] == code
    json.dumps(risks, allow_nan=False)


@pytest.mark.parametrize("code", [
    "SELECT 'DELETE FROM items; UPDATE x SET a=1' AS text",
    'SELECT "DELETE", "UPDATE", "DROP" FROM "TRUNCATE"',
    "SELECT 1 AS delete, 2 AS update, 3 AS drop",
    "-- DELETE FROM t\nSELECT 1 /* UPDATE t SET a=1 */",
    "/* outer /* DROP TABLE x */ UPDATE y SET a=1 */ SELECT 1",
    "SELECT update AS delete FROM items",
    "INSERT INTO items(id) VALUES(1)",
    "SELECT REPLACE('abc', 'b', 'x')",
    "CREATE TABLE items(id INTEGER)",
    "BEGIN TRANSACTION; SELECT 1; COMMIT",
    "WITH t AS (SELECT * FROM items WHERE id=1) SELECT * FROM t",
])
def test_read_only_literals_comments_identifiers_and_append_inserts_do_not_prompt(code):
    assert analyze_sql(code, "postgresql") == []


def test_delete_filter_is_not_taken_from_a_cte_or_subquery():
    for code in [
        "WITH t AS (SELECT id FROM source WHERE id=1) DELETE FROM items",
        "UPDATE items SET value=(SELECT MAX(value) FROM source WHERE id=1)",
        "DELETE FROM items USING (SELECT id FROM source WHERE id=1) AS x",
    ]:
        [risk] = analyze_sql(code, "postgresql")
        assert risk["has_where"] is False and risk["unfiltered"] is True
    [risk] = analyze_sql("DELETE FROM items WHERE id IN (SELECT id FROM source WHERE id=1)", "postgresql")
    assert risk["has_where"] is True and risk["unfiltered"] is False


def test_writable_cte_inside_select_is_still_reviewed():
    [risk] = analyze_sql("WITH changed AS (DELETE FROM items WHERE id=1 RETURNING *) SELECT * FROM changed", "postgresql")
    assert risk["operation"] == "DELETE" and risk["target"] == "items"
    assert risk["has_where"] is True


def test_go_batches_and_semicolons_inside_sqlserver_literals_keep_statement_boundaries():
    risks = analyze_sql("SELECT 'GO; DELETE FROM fake';\nGO\nUPDATE [dbo].[real] SET x='; WHERE';\nGO 2\nDELETE FROM [dbo].[other] WHERE id=1", "sqlserver")
    assert [(risk["operation"], risk["target"], risk["has_where"]) for risk in risks] == [
        ("UPDATE", "[dbo].[real]", False), ("DELETE", "[dbo].[other]", True),
    ]


@pytest.mark.parametrize("dialect,code,operation,target", [
    ("mysql", "REPLACE INTO items(id) VALUES(1)", "REPLACE", "items"),
    ("sqlite", "INSERT OR REPLACE INTO items(id) VALUES(1)", "REPLACE", "items"),
    ("mysql", "INSERT INTO items VALUES(1) ON DUPLICATE KEY UPDATE value=1", "UPSERT", "items"),
    ("postgresql", "INSERT INTO items VALUES(1) ON CONFLICT(id) DO UPDATE SET value=1", "UPSERT", "items"),
    ("databricks", "INSERT OVERWRITE TABLE cat.schema.items SELECT * FROM source", "INSERT OVERWRITE", "cat.schema.items"),
    ("postgresql", "CREATE OR REPLACE VIEW items AS SELECT 1 AS id", "CREATE OR REPLACE", "items"),
    ("databricks", "VACUUM cat.schema.items", "VACUUM", "cat.schema.items"),
    ("sqlserver", "RESTORE DATABASE sample FROM DISK='sample.bak' WITH REPLACE", "RESTORE", "sample"),
    ("mysql", "RENAME TABLE source TO destination", "RENAME", "source"),
    ("sqlserver", "EXEC sp_executesql N'DELETE FROM items'", "EXECUTE", "sp_executesql"),
    ("postgresql", "CALL cleanup_items()", "CALL", "cleanup_items"),
])
def test_replacement_ddl_and_opaque_commands_are_reviewed(dialect, code, operation, target):
    risks = analyze_sql(code, dialect)
    assert risks, code
    assert risks[0]["operation"] == operation
    assert risks[0]["target"] == target


def test_append_on_conflict_do_nothing_is_not_a_destructive_upsert():
    assert analyze_sql("INSERT INTO items VALUES(1) ON CONFLICT(id) DO NOTHING", "postgresql") == []


@pytest.mark.parametrize("dialect,code", [
    ("sqlite", "INSERT INTO items(id,x) VALUES(1,2) ON CONFLICT(id) DO UPDATE SET x=excluded.x"),
    ("postgresql", "INSERT INTO items(id,x) VALUES(1,2) ON CONFLICT(id) DO UPDATE SET x=excluded.x"),
    ("mysql", "INSERT INTO items(id,x) VALUES(1,2) ON DUPLICATE KEY UPDATE x=VALUES(x)"),
])
def test_upsert_is_one_operation_without_a_fake_unfiltered_update(dialect, code):
    [risk] = analyze_sql(code, dialect)
    assert (risk["operation"], risk["target"], risk["unfiltered"]) == ("UPSERT", "items", False)


def test_create_or_alter_is_one_replacement_operation():
    [risk] = analyze_sql("CREATE OR ALTER PROCEDURE p AS SELECT 1", "sqlserver")
    assert (risk["operation"], risk["target"]) == ("CREATE OR REPLACE", "p")


def test_unsupported_begin_blocks_do_not_hide_later_mutations_or_borrow_where():
    risks = analyze_sql("BEGIN\n UPDATE items SET x=1\n DELETE FROM source WHERE id=1\nEND", "sqlserver")
    assert [(risk["operation"], risk["has_where"]) for risk in risks] == [("UPDATE", False), ("DELETE", True)]
    risks = analyze_sql("IF EXISTS (SELECT 1 FROM t WHERE a=1) BEGIN DELETE FROM dbo.items END", "sqlserver")
    assert any(risk["operation"] == "DELETE" and risk["unfiltered"] for risk in risks)


@pytest.mark.parametrize("code", [
    "IF 1=1 DELETE FROM items",
    "SELECT 1\nDELETE FROM items",
    "IF 1=1 EXEC cleanup_items",
    "WITH t AS (DELETE FROM items RETURNING *) SELECT * FROM t",
])
def test_valid_tsql_not_fully_understood_by_parser_still_reviews_mutations(code):
    assert analyze_sql(code, "sqlserver")


def test_tsql_following_select_does_not_filter_preceding_delete():
    [risk] = analyze_sql("DELETE FROM items\nSELECT * FROM source WHERE id=1", "sqlserver")
    assert risk["has_where"] is False and risk["unfiltered"] is True


def test_tsql_top_does_not_produce_a_second_fake_table():
    [risk] = analyze_sql("DELETE TOP (10) FROM dbo.items WHERE id=1", "sqlserver")
    assert (risk["operation"], risk["target"], risk["has_where"]) == ("DELETE", "dbo.items", True)


def test_tsql_condition_does_not_hide_an_opaque_admin_command():
    [risk] = analyze_sql("IF 1=1 DBCC CHECKDB(items, REPAIR_ALLOW_DATA_LOSS)", "sqlserver")
    assert risk["operation"] == "DBCC"


@pytest.mark.parametrize("dialect,code,operation", [
    ("mysql", "/*! DELETE FROM items */ SELECT 1", "DELETE"),
    ("mysql", "/*!50000 DROP TABLE items */", "DROP"),
    ("mariadb", "/*M!100100 UPDATE items SET x=1 */", "UPDATE"),
])
def test_mysql_executable_comments_are_sql_not_ignored_comment_text(dialect, code, operation):
    [risk] = analyze_sql(code, dialect)
    assert risk["operation"] == operation
    assert risk["unfiltered"] is True
    assert analyze_sql("SELECT '/*! DELETE FROM items */' AS text", dialect) == []
    assert analyze_sql("/* DELETE FROM items */ SELECT 1", dialect) == []


def test_unknown_and_pass_through_commands_require_confirmation():
    for dialect, code, operation in [
        ("sqlserver", "DBCC CHECKDB(items, REPAIR_ALLOW_DATA_LOSS)", "DBCC"),
        ("sqlserver", "BACKUP DATABASE sample TO DISK='sample.bak' WITH FORMAT", "BACKUP"),
        ("postgresql", "COPY items FROM PROGRAM 'external-program'", "EXECUTE"),
        ("postgresql", "SELECT dblink_exec('remote', 'DELETE FROM items')", "EXECUTE"),
        ("sqlite", "PRAGMA user_version=123", "PRAGMA"),
    ]:
        assert any(risk["operation"] == operation for risk in analyze_sql(code, dialect))
    assert analyze_sql("PRAGMA table_info(items)", "sqlite") == []
    assert analyze_sql("COPY items FROM 'append.csv'", "postgresql") == []


def test_merge_branches_are_one_operation_not_fake_unfiltered_updates():
    code = "MERGE INTO items t USING source s ON t.id=s.id WHEN MATCHED THEN UPDATE SET t.value=s.value WHEN NOT MATCHED THEN INSERT(id) VALUES(s.id);"
    risks = analyze_sql(code, "sqlserver")
    assert [risk["operation"] for risk in risks] == ["MERGE"]


def test_postgres_anonymous_code_is_an_opaque_execution_not_a_read_only_literal():
    risks = analyze_sql("DO $$ BEGIN DELETE FROM items; END $$", "postgresql")
    assert risks[0]["operation"] == "DO"
    assert analyze_sql("SELECT $$ DELETE FROM items; $$ AS text", "postgresql") == []


def test_large_statement_uses_bounded_fallback_without_missing_a_delete():
    code = "UPDATE items SET value='" + "x" * 70000 + "'"
    [risk] = analyze_sql(code, "sqlserver")
    assert risk["operation"] == "UPDATE" and risk["unfiltered"] is True
    assert len(risk["preview"]) <= 500


def test_large_select_does_not_hide_an_opaque_sql_function():
    code = "SELECT dblink_exec('remote', 'DELETE FROM items'), '" + "x" * 70000 + "'"
    [risk] = analyze_sql(code, "postgresql")
    assert risk["operation"] == "EXECUTE" and risk["target"] == "dblink_exec"


def test_very_deep_expression_avoids_parser_recursion_without_hiding_mutation():
    code = "UPDATE items SET value=" + "(" * 200 + "1" + ")" * 200
    [risk] = analyze_sql(code, "sqlserver")
    assert risk["operation"] == "UPDATE" and risk["has_where"] is False


@pytest.mark.parametrize("code", [
    "sql('DELETE FROM items')",
    "connection.execute(text('UPDATE items SET x=1'))",
    "connection.exec_driver_sql('TRUNCATE TABLE items')",
    "cursor.executemany('DELETE FROM items WHERE id=?', values)",
    "pd.read_sql_query('DELETE FROM items RETURNING *', db_engine)",
    "sql(query='DELETE ' + 'FROM items')",
])
def test_python_known_sql_calls_review_their_literal_sql(code):
    [risk] = analyze_python(code, "postgresql")
    assert risk["operation"] in {"DELETE", "UPDATE", "TRUNCATE"}
    assert risk["target"] == "items"


@pytest.mark.parametrize("code", [
    "sql(f'DELETE FROM {table}')",
    "cursor.execute(query, parameters)",
    "db_engine.connect().execute(make_query())",
    "pd.read_sql(sql=query, con=engine)",
    "df.to_sql('items', db_engine, if_exists=mode)",
])
def test_python_unknown_query_and_replace_modes_require_conservative_confirmation(code):
    [risk] = analyze_python(code, "sqlserver")
    assert risk["operation"] == "DYNAMIC SQL"


def test_python_table_replace_requires_confirmation_but_append_and_pandas_ops_do_not():
    [risk] = analyze_python("df.to_sql('items', db_engine, if_exists='replace')")
    assert risk["operation"] == "REPLACE TABLE" and risk["target"] == "items"
    [risk] = analyze_python("df.to_sql('items', db_engine, if_exists='delete_rows')")
    assert (risk["operation"], risk["target"], risk["unfiltered"]) == ("DELETE", "items", True)
    assert analyze_python("df.to_sql('items', db_engine, if_exists='append')") == []
    assert analyze_python("df.to_sql('items', db_engine)") == []
    assert analyze_python("df.drop(columns=['items']).fillna('N/A')\ntext='DELETE FROM items'") == []
    assert analyze_python("sql('SELECT * FROM items WHERE id=1')") == []


@pytest.mark.parametrize("value", [None, 1, pytest.param("x" * (1024 * 1024 + 1), id="oversized")])
def test_oversized_or_invalid_code_is_rejected(value):
    with pytest.raises(ValueError):
        analyze_sql(value)
    with pytest.raises(ValueError):
        analyze_python(value)
