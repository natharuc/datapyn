"""The actual supervisor/kernel and HTTP client, against an owned local API."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from test_runtime import Client


@contextmanager
def elastic_api():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def answer(self, payload, status=200):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            requests.append(("GET", self.path, None))
            if self.path == "/_resolve/index/*":
                self.answer({"indices": [{"name": "events"}], "aliases": [], "data_streams": []})
            elif self.path == "/events/_mapping":
                self.answer({"events": {"mappings": {"properties": {
                    "id": {"type": "long"}, "at": {"type": "date"}, "label": {"type": "keyword"},
                    "address": {"properties": {"city": {"type": "keyword"}}},
                }}}})
            else:
                self.answer({}, 404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            requests.append(("POST", self.path, body))
            if self.headers.get("Authorization") != "ApiKey synthetic-test-only":
                self.answer({}, 401)
            elif self.path == "/_sql/close":
                self.answer({"succeeded": True})
            elif body.get("query") == "SELECT 1":
                self.answer({"columns": [{"name": "1", "type": "integer"}], "rows": [[1]]})
            elif body.get("query") == "SELECT * FROM denied":
                self.answer({"error": {"reason": "denied; token=should-not-escape"}}, 403)
            elif "cursor" in body:
                if body["cursor"] == "first":
                    self.answer({"rows": [], "cursor": "second"})
                else:
                    self.answer({"rows": [[2**60 + 5, "2026-11-11T12:00:00Z", "last"]]})
            else:
                self.answer({"columns": [{"name": "id", "type": "long"}, {"name": "at", "type": "datetime"},
                                          {"name": "label", "type": "keyword"}],
                             "rows": [[2**60 + 3, "2026-11-11T10:00:00Z", "first"],
                                      [2**60 + 4, None, "middle"]], "cursor": "first"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_elastic_sql_to_dataframe_python_completion_and_export_via_real_protocol(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "workspace"))
    with elastic_api() as (endpoint, requests):
        client = Client()
        try:
            client.session()
            config = {"db_type": "elasticsearch", "endpoint": endpoint, "auth_mode": "api_key",
                      "api_key": "synthetic-test-only", "database": "", "host": "", "username": ""}
            assert client.request("connection.test", {"config": config})["success"]
            client.request("connection.connect", {"session_id": "a", "config": config})
            sql = "SELECT * FROM events"
            finished = client.execute(sql, language="sql", variable_name="events")
            assert finished["status"] == "succeeded", finished
            assert finished["results"][0]["row_count"] == 3
            rows = client.page(finished)["rows"]
            assert [row[0] for row in rows] == [str(2**60 + 3), str(2**60 + 4), str(2**60 + 5)]
            assert rows[0][1].startswith("2026-11-11T10:00:00")
            # The script is submitted once, followed by two cursor fetches;
            # an empty intermediate page must not terminate the result.
            assert sum(body.get("query") == sql for _, path, body in requests if body and path == "/_sql") == 1
            assert sum("cursor" in body for _, path, body in requests if body and path == "/_sql") == 2
            python = client.execute("assert 'db_engine' not in globals()\n"
                                    "pd.DataFrame({'sum': [int(events.id.sum())], 'native_dates': [isinstance(events['at'].iloc[0], __import__('datetime').datetime)]})",
                                    "python")
            assert client.page(python)["rows"] == [[str(3 * 2**60 + 12), True]]
            exported = client.request("result.export_text", {"session_id": "a", "variable_name": "events", "format": "json"})
            assert json.loads(exported["text"])[0]["id"] == {"$numberLong": str(2**60 + 3)}
            snapshot = client.request("schema.get", {"session_id": "a"})
            assert snapshot["db_type"] == "elasticsearch"
            assert snapshot["capabilities"]["read_only"] is True
            assert not any(message.get("invalid_protocol") for message in client.all_messages)
        finally:
            client.close()


def test_permission_error_is_not_a_lost_connection_and_next_query_works(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "workspace"))
    with elastic_api() as (endpoint, requests):
        client = Client()
        try:
            client.session()
            client.request("connection.connect", {"session_id": "a", "config": {
                "db_type": "elasticsearch", "endpoint": endpoint, "auth_mode": "api_key", "api_key": "synthetic-test-only"}})
            failed = client.execute("SELECT * FROM denied", language="sql")
            assert failed["status"] == "failed"
            assert failed["error_info"]["category"] == "permission"
            assert "should-not-escape" not in json.dumps(failed)
            assert not any(message.get("event") == "connection.recovery" for message in client.all_messages)
            assert client.execute("SELECT * FROM events", "next", language="sql")["status"] == "succeeded"
            assert sum(body.get("query") == "SELECT * FROM denied" for _, _, body in requests if body) == 1
        finally:
            client.close()
