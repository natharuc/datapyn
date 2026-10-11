"""Pending authentication stays inside its kernel, through the real stdio broker."""

import json
import time

import pytest

from test_runtime import Client


@pytest.fixture
def client():
    value = Client()
    try:
        yield value
    finally:
        value.close()


def send(client, method, params):
    client.sequence += 1
    request_id = client.sequence
    client.process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
    client.process.stdin.flush()
    return request_id


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "closed"])
def test_new_tabs_connect_and_execute_while_another_tab_authenticates(client, tmp_path, outcome):
    client.session("authenticating")
    started, release = tmp_path / "started", tmp_path / "release"
    # Replace only the current test kernel's connection function. SQLite remains
    # real and no network, browser, credentials or production connection is used.
    setup = (
        "import time\n"
        "from pathlib import Path\n"
        "import datapyn_runtime.database as _database\n"
        "_original_connect = _database.connect\n"
        "def _gated_connect(config):\n"
        "    if config.get('host') == 'wait-for-auth':\n"
        f"        Path({str(started)!r}).write_text('started')\n"
        "        deadline = time.monotonic() + 30\n"
        f"        while not Path({str(release)!r}).exists():\n"
        "            if time.monotonic() >= deadline: raise TimeoutError('Test authentication gate expired')\n"
        "            time.sleep(0.01)\n"
        + ("        raise ConnectionError('Authentication failed in this tab')\n" if outcome == "failed" else "")
        + "    return _original_connect(config)\n"
        "_database.connect = _gated_connect\n"
        "private_value = 'first-tab'\n"
    )
    assert client.execute(setup, session_id="authenticating")["status"] == "succeeded"
    authentication_id = send(client, "connection.connect", {"session_id": "authenticating", "config": {
        "db_type": "sqlite", "host": "wait-for-auth", "database": ":memory:",
    }})
    try:
        deadline = time.monotonic() + 10
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists(), "The first tab must actually be inside authentication"
        for session_id, amount in (("second", 2), ("third", 3)):
            client.session(session_id)
            response = client.request("connection.connect", {"session_id": session_id, "config": {
                "db_type": "sqlite", "database": ":memory:",
            }})
            assert response["status"] == "connected"
            finished = client.execute(
                f"SELECT {amount} AS amount", execution_id=f"sql-{session_id}", session_id=session_id, language="sql", variable_name="sql_frame",
            )
            assert client.page(finished, session_id)["rows"] == [[amount]]
            isolated = client.execute(
                "pd.DataFrame({'isolated': ['private_value' not in globals()]})",
                execution_id=f"isolated-{session_id}", session_id=session_id,
            )
            assert client.page(isolated, session_id)["rows"] == [[True]]
        assert not any(message.get("id") == authentication_id for message in client.all_messages)
        if outcome == "closed":
            assert client.request("session.close", {"session_id": "authenticating"})["status"] == "closed"
        else:
            release.touch()
        response = client.wait(lambda message: message.get("id") == authentication_id)
        if outcome == "succeeded":
            assert response["result"]["status"] == "connected"
        else:
            assert "error" in response
            if outcome == "failed":
                assert "Authentication failed in this tab" in response["error"]["message"]
        # Closing/failing the pending tab cannot discard another tab's engine
        # or dataframe, and responses remain correlated to the requested tab.
        continued = client.execute("sql_frame.assign(continued=True)", execution_id="continued", session_id="third")
        assert client.page(continued, "third")["rows"] == [[3, True]]
    finally:
        release.touch()
