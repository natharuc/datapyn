"""Offline reflection fakes: metadata must never own the manual socket."""
from contextlib import contextmanager

import pytest

from datapyn_runtime.explorer import ObjectExplorer


class ManualSocket:
    def __init__(self, connector):
        self.connector = connector

    def execute(self, sql, params):
        assert "WHERE c.object_id = OBJECT_ID(:name, 'U')" in str(sql)
        assert " LIKE " not in str(sql)
        quoted = params["name"].removeprefix("tempdb..")
        assert quoted.startswith("[") and quoted.endswith("]")
        name = quoted[1:-1].replace("]]", "]")
        self.connector.reflections.append((name, None))
        self.connector.column_queries.append((str(sql), params))
        if self.connector.failure:
            raise ValueError("transaction aborted")
        return self

    def mappings(self):
        return self

    def all(self):
        return [{"name": "OwnColumn", "data_type": "INTEGER", "nullable": False, "default": None}]


class Inspector:
    def __init__(self, connector):
        self.connector = connector

    def get_schema_names(self):
        return ["dbo", "information_schema"]

    def get_table_names(self, schema=None):
        return ["regular"]

    def get_view_names(self, schema=None):
        return []

    def get_columns(self, name, schema=None):
        self.connector.reflections.append((name, schema))
        if self.connector.failure:
            raise ValueError("transaction aborted")
        return [{"name": "OwnColumn", "type": "INTEGER", "nullable": False}]


class ManualConnector:
    automatic_transactions = False

    def __init__(self, dialect="sqlserver"):
        self.db_type = dialect
        self.connection_params = {"database": "db", "schema": "dbo" if dialect == "sqlserver" else "public"}
        self.engine, self.socket = object(), ManualSocket(self)
        self.borrowed, self.reflections, self.existing, self.existence_checks = [], [], set(), []
        self.column_queries = []
        self.failure = False

    @contextmanager
    def table_export_connection(self):
        self.borrowed.append(self.socket)
        yield self.socket

    def execute_query(self, sql):
        import pandas as pd
        return pd.DataFrame({"name": ["db"]})


@pytest.fixture
def reflected(monkeypatch):
    connector = ManualConnector()
    monkeypatch.setattr("sqlalchemy.inspect", lambda connection: Inspector(connector) if connection is connector.socket else pytest.fail("metadata borrowed another physical connection"))
    def temporary_exists(connection, name, dialect):
        assert connection is connector.socket
        connector.existence_checks.append(name)
        return name in connector.existing
    monkeypatch.setattr("datapyn_runtime.table_export._temporary_exists", temporary_exists)
    return connector, ObjectExplorer(connector)


def test_all_reflection_borrows_the_manual_block_without_pool_checkout(reflected):
    connector, explorer = reflected
    assert explorer.schemas() == ["dbo"]
    assert explorer.objects("dbo", "table")[0]["name"] == "regular"
    assert explorer.columns("regular", "dbo")[0]["name"] == "OwnColumn"
    assert connector.borrowed == [connector.socket] * 3


def test_sqlserver_create_select_into_confirm_only_actual_same_block_tables(reflected):
    connector, explorer = reflected
    connector.existing = {"#MixedTemp", "##global_name"}
    code = "SELECT 'CREATE TABLE #literal(a int)'; -- CREATE TABLE #comment(a int)\nCREATE TABLE [#MixedTemp](OwnColumn int); SELECT 1 INTO ##global_name; CREATE TABLE #failed(a int);"
    assert explorer.refresh_sql_temporaries(code)
    assert set(connector._datapyn_temporary_tables) == {"#MixedTemp", "##global_name"}
    assert connector.reflections == [("##global_name", None), ("#MixedTemp", None)]
    assert explorer.columns("#MixedTemp", "")[0]["name"] == "OwnColumn"
    snapshot = explorer.completion_schema("SELECT t. FROM #MixedTemp t")
    assert "#MixedTemp" in snapshot["columns"]
    assert any(table["name"] == "#MixedTemp" and table["schema"] == "" for table in snapshot["tables"])
    assert explorer.query({"name": "#MixedTemp", "schema": "dbo"})["code"] == "SELECT TOP (1000) *\nFROM [#MixedTemp];"
    assert "CREATE TABLE [#MixedTemp]" in explorer.details({"name": "#MixedTemp", "schema": "dbo"})["definition"]


def test_rollback_and_failed_metadata_never_guess_that_a_temporary_disappeared(reflected):
    connector, explorer = reflected
    connector.existing = {"#t"}
    assert explorer.refresh_sql_temporaries("CREATE TABLE #t(id INTEGER)")
    connector.failure = True
    assert not explorer.refresh_sql_temporaries("ALTER TABLE #t ADD x INT")
    assert "#t" in connector._datapyn_temporary_tables
    connector.failure = False
    connector.existing.clear()
    assert explorer.refresh_sql_temporaries("ROLLBACK")
    assert not connector._datapyn_temporary_tables
    assert not connector.has_temporary_tables


def test_failed_existence_probe_preserves_registry_and_caches(reflected, monkeypatch):
    connector, explorer = reflected
    connector.existing = {"#t"}
    assert explorer.refresh_sql_temporaries("CREATE TABLE #t(id INTEGER)")
    explorer.cache["sentinel"] = (0, ["known"])
    def failed_probe(*_args):
        raise ValueError("connection state unknown")
    monkeypatch.setattr("datapyn_runtime.table_export._temporary_exists", failed_probe)
    assert not explorer.refresh_sql_temporaries("ROLLBACK")
    assert "#t" in connector._datapyn_temporary_tables
    assert "sentinel" in explorer.cache


@pytest.mark.parametrize("dialect,name,code,schema", [
    ("postgresql", "MixedName", 'CREATE TEMP TABLE "MixedName"(id INTEGER)', ""),
    ("postgresql", "unquoted", "CREATE TEMPORARY TABLE UNQUOTED(id INTEGER)", ""),
    ("mysql", "MixedName", "CREATE TEMPORARY TABLE `MixedName`(id INTEGER)", ""),
    ("sqlite", "MixedName", 'CREATE TEMP TABLE "MixedName"(id INTEGER)', "temp"),
])
def test_dialect_name_case_and_temporary_scope(reflected, dialect, name, code, schema):
    connector, explorer = reflected
    connector.db_type = dialect
    connector.existing = {name}
    assert explorer.refresh_sql_temporaries(code)
    assert connector._datapyn_temporary_tables[name]["schema"] == schema
    assert connector.reflections == [(name, schema or None)]


def test_automatic_mode_uses_normal_metadata_and_never_scans_sql_temporary_names(reflected):
    connector, explorer = reflected
    connector.automatic_transactions = True
    assert not explorer.refresh_sql_temporaries("CREATE TABLE #t(id INTEGER)")
    assert not connector.borrowed


def test_read_and_dml_add_no_metadata_queries_to_a_hundred_temporary_tables(reflected):
    connector, explorer = reflected
    connector.existing = {f"#t{index}" for index in range(100)}
    assert explorer.refresh_sql_temporaries(";".join(f"CREATE TABLE {name}(id int)" for name in connector.existing))
    connector.reflections.clear()
    connector.existence_checks.clear()
    connector.borrowed.clear()
    for code in ("SELECT 1", "SELECT * FROM #t1", "INSERT INTO #t1 SELECT 1", "UPDATE #t1 SET id = 2", "DELETE FROM #t1", "SELECT 'COMMIT' AS [CREATE TABLE #fake]"):
        assert not explorer.refresh_sql_temporaries(code)
    assert not connector.borrowed
    assert not connector.reflections
    assert not connector.existence_checks


def test_commit_and_forced_failure_check_only_existence_without_reloading_columns(reflected):
    connector, explorer = reflected
    connector.existing = {"#t", "#other"}
    assert explorer.refresh_sql_temporaries("CREATE TABLE #t(id int); CREATE TABLE #other(id int)")
    connector.reflections.clear()
    connector.existence_checks.clear()
    assert not explorer.refresh_sql_temporaries("COMMIT TRANSACTION")
    assert connector.existence_checks == ["#other", "#t"]
    assert not connector.reflections
    connector.existing.remove("#t")
    assert explorer.refresh_sql_temporaries("SELECT * FROM absent", force=True)
    assert set(connector._datapyn_temporary_tables) == {"#other"}
    assert not connector.reflections


def test_alter_and_drop_probe_only_the_affected_temporary_table(reflected):
    connector, explorer = reflected
    connector.existing = {"#t", "#other"}
    assert explorer.refresh_sql_temporaries("CREATE TABLE #t(id int); CREATE TABLE #other(id int)")
    connector.reflections.clear()
    connector.existence_checks.clear()
    assert not explorer.refresh_sql_temporaries("ALTER TABLE #t ADD extra int")
    assert connector.existence_checks == ["#t"]
    assert connector.reflections == [("#t", None)]
    connector.existing.remove("#t")
    assert explorer.refresh_sql_temporaries("DROP TABLE #t")
    assert set(connector._datapyn_temporary_tables) == {"#other"}


def test_postgresql_standalone_end_checks_existence_but_case_end_does_not(reflected):
    connector, explorer = reflected
    connector.db_type = "postgresql"
    connector.existing = {"t"}
    assert explorer.refresh_sql_temporaries("CREATE TEMP TABLE t(id int)")
    connector.existence_checks.clear()
    connector.reflections.clear()
    assert not explorer.refresh_sql_temporaries("SELECT CASE WHEN id = 1 THEN 2 ELSE 3 END FROM t")
    assert not connector.existence_checks
    assert not explorer.refresh_sql_temporaries("END WORK")
    assert connector.existence_checks == ["t"]
    assert not connector.reflections


def test_renamed_temporary_is_confirmed_and_old_metadata_removed(reflected):
    connector, explorer = reflected
    connector.db_type = "postgresql"
    connector.existing = {"Original"}
    assert explorer.refresh_sql_temporaries('CREATE TEMP TABLE "Original"(id int)')
    connector.existing = {"Renamed"}
    connector.existence_checks.clear()
    connector.reflections.clear()
    assert explorer.refresh_sql_temporaries('ALTER TABLE "Original" RENAME TO "Renamed"')
    assert set(connector._datapyn_temporary_tables) == {"Renamed"}
    assert connector.existence_checks == ["Original", "Renamed"]
    assert connector.reflections == [("Renamed", None)]


def test_sqlserver_temporary_columns_use_owner_object_id_instead_of_ambiguous_like(reflected, monkeypatch):
    connector, explorer = reflected
    name = "#same.name] across sessions"
    connector.existing = {name}
    def ambiguous_inspector(*_args, **_kwargs):
        pytest.fail("SQLAlchemy's LIKE resolver would also match another user's #table")
    monkeypatch.setattr(Inspector, "get_columns", ambiguous_inspector)
    assert explorer.refresh_sql_temporaries("CREATE TABLE [#same.name]] across sessions](OwnColumn int)")
    assert list(connector._datapyn_temporary_tables) == [name]
    assert connector.column_queries[0][1] == {"name": "tempdb..[#same.name]] across sessions]"}
    assert connector._datapyn_temporary_tables[name]["columns"][0]["name"] == "OwnColumn"
