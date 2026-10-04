"""Real editor protocol contracts across metadata, inference and session lifetimes."""

from contextlib import closing
import sqlite3

import pytest

from test_runtime import Client


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Exercise the shipped supervisor with a private workspace, never personal state.
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    value = Client()
    try:
        yield value
    finally:
        value.close()


def complete(client, session, code, *, language="python", **params):
    line = code.count("\n") + 1
    column = len(code.split("\n")[-1].encode("utf-16-le")) // 2 + 1
    return client.request("language.complete", {
        "session_id": session, "block_id": f"editor-{session}",
        "completion_id": f"request-{client.sequence + 1}",
        "language": language, "code": code, "line": line, "column": column,
        **params,
    })


def test_sql_metadata_event_and_followup_completion_agree_on_schema_shape(client, tmp_path):
    database = tmp_path / "acceptance.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample(id INTEGER, title TEXT)")
    client.session("a")
    client.request("connection.connect", {
        "session_id": "a", "config": {"db_type": "sqlite", "database": str(database)},
    })
    code = "SELECT s. FROM main.sample s"
    complete(client, "a", code, language="sql", column=10)
    update = client.wait(lambda message: message.get("event") == "language.context_updated"
                         and message["payload"].get("session_id") == "a"
                         and "schema_snapshot" in message["payload"])["payload"]
    schema = update["schema_snapshot"]
    assert update["version"] > 0 and isinstance(update["variables"], dict)
    assert schema["db_type"] == "sqlite" and schema["current_schema"] == "main"
    assert any(table["key"] == "main.sample" and table["name"] == "sample"
               for table in schema["tables"])
    assert {column["name"] for column in schema["columns"]["main.sample"]} == {"id", "title"}
    result = complete(client, "a", code, language="sql", column=10)
    assert {item["label"] for item in result["items"]} == {"id", "title"}
    assert result["context_version"] == update["version"]
    # Real catalog IO + supervisor delivery + the exact editor protocol must
    # agree for quoted aliases and comments containing statement delimiters.
    for marked in ['SELECT "s".| /* ; */ FROM main.sample "s"', "SELECT s . | FROM main.sample s", 'SELECT s."ti|tle" FROM main.sample s']:
        offset = marked.index("|")
        result = complete(client, "a", marked.replace("|", ""), language="sql", column=offset + 1)
        assert {item["label"] for item in result["items"]} == ({"title"} if '"ti|' in marked else {"id", "title"})
    # Editing the selected field does not require another metadata generation.
    for prefix in ("t", "ti", "tit"):
        changed = f"SELECT s.{prefix} FROM main.sample s"
        result = complete(client, "a", changed, language="sql", column=10 + len(prefix))
        assert result["context_version"] == update["version"]
    client.request("variable.inspect", {"session_id": "a", "variable_name": "__namespace__"})
    published = [message["payload"] for message in client.all_messages
                 if message.get("event") == "language.context_updated"
                 and "schema_snapshot" in message["payload"]]
    assert len(published) == 1
    finished = client.execute("ALTER TABLE sample ADD COLUMN archived INTEGER", "alter-schema", language="sql")
    assert finished["status"] == "succeeded"
    invalidated = client.wait(lambda message: message.get("event") == "language.context_updated"
                              and message["payload"].get("metadata_invalidated"))["payload"]
    assert invalidated["schema_snapshot"] == {} and invalidated["version"] > update["version"]
    complete(client, "a", code, language="sql", column=10)
    refreshed = client.wait(lambda message: message.get("event") == "language.context_updated"
                            and message["payload"].get("schema_snapshot", {}).get("tables"))["payload"]
    assert {column["name"] for column in refreshed["schema_snapshot"]["columns"]["main.sample"]} == {"id", "title", "archived"}
    result = complete(client, "a", code, language="sql", column=10)
    assert {item["label"] for item in result["items"]} == {"id", "title", "archived"}


def test_prepare_switches_saved_connections_and_forces_real_metadata_reload(client, tmp_path):
    profiles = []
    for name, field in (("alpha", "alpha_value"), ("beta", "beta_value")):
        database = tmp_path / f"{name}.sqlite"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute(f"CREATE TABLE sample({field} INTEGER)")
        profile = client.request("connections.save", {"connection": {"name": name, "config": {"db_type": "sqlite", "database": str(database)}}})
        profiles.append((profile["id"], database, field))
    client.session()
    client.execute("preserved_value = 7", "namespace")
    code = "SELECT s. FROM sample s"
    for identifier, database, field in profiles:
        result = client.request("language.prepare", {"session_id": "a", "connection_id": identifier, "code": code})
        assert result["status"] == "queued"
        payload = client.wait(lambda item: item.get("event") == "language.context_updated"
                              and item["payload"].get("connection_id") == identifier
                              and item["payload"].get("metadata_state") == "ready")["payload"]
        assert payload["requested_scope"] == {"connection_id": identifier, "database": None, "schema": None}
        assert payload["database"] == str(database) and payload["schema"] == "main"
        assert "preserved_value" in payload["variables"]
        assert {item["label"] for item in complete(client, "a", code, language="sql", column=10, connection_id=identifier)["items"]} == {field}
    identifier, database, field = profiles[1]
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("ALTER TABLE sample ADD COLUMN external_change TEXT")
    assert {item["label"] for item in complete(client, "a", code, language="sql", column=10, connection_id=identifier)["items"]} == {field}
    assert client.request("language.prepare", {"session_id": "a", "connection_id": identifier, "code": code, "refresh": True})["status"] == "queued"
    client.wait(lambda item: item.get("event") == "language.context_updated"
                and item["payload"].get("connection_id") == identifier
                and any(column["name"] == "external_change" for column in item["payload"].get("schema_snapshot", {}).get("columns", {}).get("main.sample", [])))
    assert {item["label"] for item in complete(client, "a", code, language="sql", column=10, connection_id=identifier)["items"]} == {field, "external_change"}
    other_identifier, _, other_field = profiles[0]
    assert {item["label"] for item in complete(client, "a", code, language="sql", column=10, connection_id=other_identifier)["items"]} == {other_field}


def test_prepare_reports_connection_failure_without_erasing_namespace(client, tmp_path):
    profile = client.request("connections.save", {"connection": {"name": "Unavailable", "config": {"db_type": "sqlite", "database": str(tmp_path / "missing" / "unavailable.sqlite")}}})
    client.session()
    client.execute("preserved_value = 12", "namespace")
    assert client.request("language.prepare", {"session_id": "a", "connection_id": profile["id"], "code": "SELECT * FROM sample"})["status"] == "queued"
    payload = client.wait(lambda item: item.get("event") == "language.context_updated"
                          and item["payload"].get("metadata_state") == "error")["payload"]
    assert payload["schema_snapshot"] == {} and payload["schema_error"]
    assert payload["requested_scope"]["connection_id"] == profile["id"]
    assert "preserved_value" in payload["variables"]
    result = complete(client, "a", "preserved_value", language="python")
    assert "preserved_value" in {item["label"] for item in result["items"]}


def test_python_completion_isolated_live_namespace_and_context_never_execute(client):
    for session, column in (("a", "alpha"), ("b", "beta")):
        client.session(session)
        finished = client.execute(
            f"frame = pd.DataFrame({{'{column}': [1]}})\n"
            f"polar = pl.DataFrame({{'{column}': [1]}})",
            execution_id=f"seed-{session}", session_id=session,
        )
        assert finished["status"] == "succeeded"
        client.wait(lambda message: message.get("event") == "language.context_updated"
                    and message["payload"].get("session_id") == session
                    and "frame" in message["payload"].get("variables", {}))
    for session, expected in (("a", "alpha"), ("b", "beta")):
        result = complete(client, session, 'frame["')
        assert {item["label"] for item in result["items"]} == {expected}
    result = complete(client, "a", "polar.with_c")
    assert "with_columns" in {item["label"] for item in result["items"]}
    result = complete(client, "a", "dt.da", global_imports="import datetime as dt")
    assert "date" in {item["label"] for item in result["items"]}
    result = complete(client, "a", "side_effect", preamble=(
        "side_effect_marker = 42\n"
        "raise AssertionError('completion context must not execute')\n"
    ))
    assert "side_effect_marker" in {item["label"] for item in result["items"]}
    namespace = client.request("variable.inspect", {"session_id": "a", "variable_name": "__namespace__"})
    assert "side_effect_marker" not in {variable["name"] for variable in namespace["variables"]}
    client.request("variable.delete", {"session_id": "a", "name": "frame"})
    removed = client.wait(lambda message: message.get("event") == "language.context_updated"
                          and message["payload"].get("session_id") == "a"
                          and "frame" not in message["payload"].get("variables", {})
                          and "polar" in message["payload"].get("variables", {}))["payload"]
    assert "frame" not in removed["variables"]
    assert complete(client, "a", 'frame["')["items"] == []
    assert {item["label"] for item in complete(client, "b", 'frame["')["items"]} == {"beta"}


def completed_namespace(client, session, execution_id):
    """The last editor snapshot must already exist when completion is announced."""
    messages = client.all_messages
    index = next(index for index, message in enumerate(messages)
                 if message.get("event") == "execution.finished"
                 and message["payload"].get("session_id") == session
                 and message["payload"].get("execution_id") == execution_id)
    updates = [message["payload"] for message in messages[:index]
               if message.get("event") == "language.context_updated"
               and message["payload"].get("session_id") == session]
    assert updates, "execution.finished arrived before its namespace snapshot"
    return updates[-1]["variables"]


def test_sql_frames_publish_before_finished_and_work_in_every_python_block(client):
    client.session("sql-session")
    client.session("other-session")
    client.request("connection.connect", {
        "session_id": "sql-session", "config": {"db_type": "sqlite"},
    })
    # Warm the completion cache with the previous, empty namespace.
    assert not any(item["label"].startswith("orders") for item in
                   complete(client, "sql-session", "orders", block_id="python-before-sql")["items"])
    finished = client.execute(
        "SELECT 7 AS order_id, 'paid' AS status; SELECT 12.5 AS gross_total",
        "sql-multiple", "sql-session", "sql", variable_name="orders", block_id="sql-source",
    )
    assert finished["status"] == "succeeded"
    assert [result["variable_name"] for result in finished["results"]] == ["orders", "orders1"]
    snapshot = completed_namespace(client, "sql-session", "sql-multiple")
    assert snapshot["orders"] == {
        "type": "DataFrame", "module": "pandas.core.frame", "columns": ["order_id", "status"],
    }
    assert snapshot["orders1"]["columns"] == ["gross_total"]
    assert "rows" not in snapshot["orders"] and "data" not in snapshot["orders"]
    for block in ("python-before-sql", "python-after-sql", "python-independent"):
        names = {item["label"] for item in complete(client, "sql-session", "orders", block_id=block)["items"]}
        assert {"orders", "orders1"} <= names
        columns = complete(client, "sql-session", 'orders["', block_id=block)["items"]
        assert {item["label"] for item in columns} == {"order_id", "status"}
        methods = complete(client, "sql-session", "orders.he", block_id=block)["items"]
        assert "head" in {item["label"] for item in methods}
        assert {item["label"] for item in complete(client, "sql-session", 'orders1["', block_id=block)["items"]} == {"gross_total"}
    assert not any(item["label"].startswith("orders") for item in complete(client, "other-session", "orders")["items"])
    assert complete(client, "other-session", 'orders["')["items"] == []
    # Python sees the same objects stored by SQL, including modifications made
    # from a different block. Completion must not synthesize replacement frames.
    finished = client.execute(
        "orders['verified'] = orders.order_id * 2\n"
        "assert orders1.gross_total.iloc[0] == 12.5\norders[['verified']]",
        "python-consumer", "sql-session", block_id="python-independent",
    )
    assert client.page(finished, "sql-session")["rows"] == [[14]]
    snapshot = completed_namespace(client, "sql-session", "python-consumer")
    assert snapshot["orders"]["columns"] == ["order_id", "status", "verified"]
    # Re-running the SQL block replaces its frame, rather than retaining its
    # old columns in any block's completion cache.
    finished = client.execute("SELECT 9 AS replacement", "sql-overwrite", "sql-session", "sql", variable_name="orders")
    assert finished["status"] == "succeeded"
    assert completed_namespace(client, "sql-session", "sql-overwrite")["orders"]["columns"] == ["replacement"]
    assert {item["label"] for item in complete(client, "sql-session", 'orders["', block_id="python-before-sql")["items"]} == {"replacement"}
    client.request("variable.delete", {"session_id": "sql-session", "name": "orders1"})
    assert complete(client, "sql-session", 'orders1["', block_id="python-after-sql")["items"] == []


def test_failed_python_block_updates_sql_frame_metadata_before_finished(client):
    client.session()
    client.request("connection.connect", {"session_id": "a", "config": {"db_type": "sqlite"}})
    client.execute("SELECT 4 AS value", "sql-seed", language="sql")
    failed = client.execute("df['partial'] = df.value + 1\nraise ValueError('expected')", "partial-change")
    assert failed["status"] == "failed"
    assert completed_namespace(client, "a", "partial-change")["df"]["columns"] == ["value", "partial"]
    assert {item["label"] for item in complete(client, "a", 'df["', block_id="other-block")["items"]} == {"value", "partial"}
    assert client.page(client.execute("df[['partial']]", "read-partial"))["rows"] == [[5]]


def test_restored_unicode_sql_results_complete_and_execute_in_new_blocks(client):
    client.request("snapshot.settings.set", {"settings": {"enabled": True, "restore_on_startup": True, "max_size_mb": 10}})
    client.session("restored-sql")
    client.event("namespace.changed", session_id="restored-sql")
    client.request("connection.connect", {"session_id": "restored-sql", "config": {"db_type": "sqlite"}})
    finished = client.execute(
        "SELECT 7 AS amount; SELECT 'saved' AS state", "unicode-query", "restored-sql", "sql", variable_name="Δados",
    )
    assert finished["status"] == "succeeded"
    assert {"Δados", "Δados1"} <= completed_namespace(client, "restored-sql", "unicode-query").keys()
    assert {item["label"] for item in complete(client, "restored-sql", 'Δados["', block_id="live-python")["items"]} == {"amount"}
    saved = client.request("snapshot.save", {"session_id": "restored-sql"})
    assert saved["saved"] and {item["name"] for item in saved["variables"]} == {"Δados", "Δados1"}
    client.request("session.close", {"session_id": "restored-sql"})
    client.session("restored-sql")
    restored = client.event("namespace.changed", session_id="restored-sql")
    assert restored["restored"] and {result["variable_name"] for result in restored["results"]} == {"Δados", "Δados1"}
    client.wait(lambda message: message.get("event") == "language.context_updated"
                and message["payload"].get("session_id") == "restored-sql"
                and "Δados1" in message["payload"].get("variables", {}))
    for block in ("restored-first-python", "restored-second-python"):
        assert {item["label"] for item in complete(client, "restored-sql", 'Δados["', block_id=block)["items"]} == {"amount"}
        assert {item["label"] for item in complete(client, "restored-sql", 'Δados1["', block_id=block)["items"]} == {"state"}
        assert "head" in {item["label"] for item in complete(client, "restored-sql", "Δados.he", block_id=block)["items"]}
    # Restored frames are immediately usable without reconnecting SQL.
    executed = client.execute("Δados.assign(state=Δados1.state.iloc[0])", "restored-python", "restored-sql")
    assert client.page(executed, "restored-sql")["rows"] == [[7, "saved"]]
