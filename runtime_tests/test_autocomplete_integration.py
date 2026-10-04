"""Real editor protocol contracts across metadata, inference and session lifetimes."""

import sqlite3

import pytest

from test_runtime import Client


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Exercise the shipped supervisor with a private workspace, never personal state.
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "state"))
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
