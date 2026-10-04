"""Offline acceptance of source/frozen feature paths; all state lives in a temp directory."""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import statistics
import tempfile
import time

from smoke_runtime import RuntimeClient


def smoke(executable=None, timeout=90, report=None):
    metrics = {}
    with tempfile.TemporaryDirectory(prefix="datapyn-parity-") as directory:
        root = Path(directory)
        keys = {
            "DATAPYN_RUNTIME_STATE_PATH": str(root / "workspace"),
            "DATAPYN_WORKSPACE_PATH": str(root / "workspace"),
            "DATAPYN_SNAPSHOT_ROOT": str(root / "snapshots"),
            "DATAPYN_RUNTIME_DATA_DIR": str(root / "packages"),
        }
        previous = {key: os.environ.get(key) for key in keys}
        os.environ.update(keys)
        client = None
        try:
            start = time.perf_counter()
            client = RuntimeClient(executable, timeout)
            assert client.request("system.info")["capabilities"]["qt_required"] is False
            client.request("session.create", {"session_id": "parity"})
            client.event("session.ready", session_id="parity")
            metrics["kernel_start_ms"] = round((time.perf_counter() - start) * 1000, 2)
            group = client.request("groups.save", {"group": {"name": "Offline acceptance", "color": "#5179ef"}})
            profile = client.request("connections.save", {"connection": {"name": "Temporary SQLite", "group_id": group["id"],
                "config": {"db_type": "sqlite", "database": str(root / "smoke.sqlite")}}})
            client.request("connection.connect", {"session_id": "parity", "connection_id": profile["id"]})
            finished = client.execute("parity", "sql", "sql", "CREATE TABLE sample(id INTEGER PRIMARY KEY, title TEXT); INSERT INTO sample VALUES (1,'one'),(2,'two'); SELECT * FROM sample;", "df")
            ref = finished["results"][0]
            page = client.request("result.page", {"session_id": "parity", "result_id": ref["result_id"], "offset": 0, "limit": 20})
            assert page["rows"] == [[1, "one"], [2, "two"]]
            header_values = client.request("result.column_values", {
                "session_id": "parity", "result_id": ref["result_id"], "column": "title"})
            assert header_values["kind"] == "text" and header_values["values"] == ["one", "two"]
            assert header_values["sampled"] is False
            header_view = {"session_id": "parity", "result_id": ref["result_id"],
                           "filter": {"filters": [{"column": "id", "operator": "between", "value": "1", "value_to": "2"},
                                                  {"column": "title", "operator": "ends_with", "value": "O"}]},
                           "sort": {"column": "id", "direction": "desc"}}
            header_page = client.request("result.page", header_view)
            assert header_page["rows"] == [[2, "two"]] and header_page["total_rows"] == 1
            header_export = client.request("result.export_text", {**header_view, "format": "json"})
            assert json.loads(header_export["text"]) == [{"id": 2, "title": "two"}]
            details = client.request("explorer.details", {"session_id": "parity", "name": "sample", "schema": "main"})
            assert details["primary_key"]["constrained_columns"] == ["id"]
            assert "CREATE TABLE" in details["definition"]
            completion = client.request("language.complete", {"session_id": "parity", "language": "sql", "code": "SELECT s. FROM sample s", "line": 1, "column": 10})
            if not completion["items"]:
                client.request("explorer.list", {"session_id": "parity"})
                completion = client.request("language.complete", {"session_id": "parity", "language": "sql", "code": "SELECT s. FROM sample s", "line": 1, "column": 10})
            assert {"id", "title"} <= {item["label"] for item in completion["items"]}, completion
            completion_start = time.perf_counter()
            python_completion = client.request("language.complete", {"session_id": "parity", "language": "python", "code": "df.", "line": 1, "column": 4})
            assert any(item["label"] == "columns" for item in python_completion["items"])
            metrics["python_completion_first_ms"] = round((time.perf_counter() - completion_start) * 1000, 2)
            completion_start = time.perf_counter()
            python_completion = client.request("language.complete", {"session_id": "parity", "language": "python", "code": "df.", "line": 1, "column": 4})
            assert any(item["label"] == "columns" for item in python_completion["items"])
            metrics["python_completion_reused_ms"] = round((time.perf_counter() - completion_start) * 1000, 2)
            formatted = client.request("language.format", {"language": "python", "code": "x=1\n"})
            assert formatted["error"] is None and "x = 1" in formatted["code"]
            malformed = client.request("language.diagnostics", {"language": "python", "code": "def broken(:"})
            assert malformed["markers"]
            # Dialects load lazily in sqlglot. Exercise their actual bundled
            # modules without a session or database metadata dependency.
            for dialect in ("sqlite", "sqlserver", "postgresql", "mysql", "databricks"):
                valid_sql = client.request("language.diagnostics", {
                    "language": "sql", "db_type": dialect, "code": "SELECT 1 AS value", "locale": "pt-BR"})
                assert valid_sql["status"] == "complete" and not valid_sql["markers"], (dialect, valid_sql)
                invalid_sql = client.request("language.diagnostics", {
                    "language": "sql", "db_type": dialect, "code": "SELECT FROM", "locale": "pt-BR"})
                assert invalid_sql["status"] == "complete", (dialect, invalid_sql)
                assert any(marker["severity"] == "error" and "esperado um nome de tabela" in marker["message"]
                           for marker in invalid_sql["markers"]), (dialect, invalid_sql)
            shared = client.request("parameters.scan", {"code": "SELECT @local, {{shared}}", "codes": ["SELECT @local, {{shared}}"]})
            assert shared["sql_parameters"] and shared["shared_parameters"]
            result = client.execute("parity", "python", "python", "df['value'] = df['id'] * 3\nprint('python namespace alive')\ndf")
            ref = next(item for item in result["results"] if item["variable_name"] == "df")
            selected = {"session_id": "parity", "result_id": ref["result_id"], "scope": {"row_ranges": [[1, 1]], "column_indices": [2]}}
            summary = client.request("result.summary", selected)
            assert summary["columns"][0]["sum"] == 6
            for extension in ("csv", "xlsx", "json", "parquet", "sql"):
                path = root / f"export.{extension}"
                client.request("result.export", {**selected, "path": str(path)})
                assert path.stat().st_size > 0
            copied = client.request("result.export_text", {**selected, "operation_id": "copy-csv", "format": "csv", "options": {"delimiter": "\t", "include_header": True}})
            assert copied["row_count"] == 1 and "value" in copied["text"] and "6" in copied["text"]
            generated = client.request("result.export_text", {**selected, "operation_id": "generate-sql", "format": "sql", "options": {
                "db_type": "sqlite", "table_name": "generated_export", "sql_mode": "create_insert", "include_transaction": True, "batch_size": 2}})
            created = client.execute("parity", "generated", "sql", generated["text"] + "\nSELECT value FROM generated_export;", "generated_result")
            created_page = client.request("result.page", {"session_id": "parity", "result_id": created["results"][0]["result_id"]})
            assert created_page["rows"] == [[6]]
            client.request("result.export_table", {**selected, "operation_id": "export-temp", "connection_id": profile["id"],
                "table": "export_temp", "temporary": True, "if_exists": "fail", "chunksize": 100})
            temporary = client.execute("parity", "temporary", "sql", "SELECT value FROM temp.export_temp;", "temporary_result")
            temporary_page = client.request("result.page", {"session_id": "parity", "result_id": temporary["results"][0]["result_id"]})
            assert temporary_page["rows"] == [[6]]
            imported = client.request("data.import", {"session_id": "parity", "path": str(root / "export.xlsx"), "variable_name": "imported"})
            assert imported["result"]["row_count"] == 1
            for extension in ("html", "png", "json", "jpg", "jpeg"):
                path = root / f"chart.{extension}"
                client.request("result.chart_export", {"session_id": "parity", "result_id": ref["result_id"], "path": str(path), "config": {"type": "bar", "x_column": "title", "y_columns": ["value"]}})
                assert path.stat().st_size > 100
                if extension in ("jpg", "jpeg"):
                    assert path.read_bytes().startswith(b"\xff\xd8\xff")
            preview = client.request("result.chart", {"session_id": "parity", "result_id": ref["result_id"],
                "config": {"type": "bar", "x_column": "title", "y_columns": ["value"], "sort": "original"}})
            assert preview["chart_id"] and preview["bounded"] is False
            original_figure = preview["figure"]
            client.execute("parity", "chart-source-mutation", "python", "df['value'] = [300, 600]")
            captured_path = root / "captured-chart.json"
            client.request("result.chart_export", {"session_id": "parity", "chart_id": preview["chart_id"], "path": str(captured_path), "format": "json"})
            captured = json.loads(captured_path.read_text(encoding="utf-8"))
            assert captured["figure"]["data"] == original_figure["data"]
            styled = client.request("result.chart", {"session_id": "parity", "chart_id": preview["chart_id"],
                "config": {**preview["config"], "title": "Captured title", "font_size": 18, "palette": "ocean"}})
            assert styled["chart_id"] != preview["chart_id"] and styled["figure"]["data"][0]["y"] == original_figure["data"][0]["y"]
            assert styled["figure"]["layout"]["font"]["size"] == 18
            # Scalar output does not publish a new result tab after reassignment.
            reassigned = client.execute("parity", "chart-source-reassignment", "python", "df = df.assign(value=[30, 60])\nlen(df)")
            assert not reassigned["results"]
            canonical = client.request("variable.inspect", {"session_id": "parity", "name": "df", "limit": 1})["result"]
            refreshed = client.request("result.chart", {"session_id": "parity", "result_id": canonical["result_id"], "config": preview["config"]})
            assert refreshed["figure"]["data"][0]["y"] == [30, 60]
            client.request("result.release", {"session_id": "parity", "result_id": canonical["result_id"]})
            unpinned = client.request("result.chart", {"session_id": "parity", "variable_name": "df", "config": preview["config"]})
            assert unpinned["figure"]["data"][0]["y"] == [30, 60]
            rich = client.execute("parity", "rich", "python", "import matplotlib.pyplot as plt\nplt.plot([1,2],[2,4])\nplt.show()")
            artifact = next(item for item in rich["rich_outputs"] if item["type"] == "image")
            path = root / "figure.png"
            client.request("result.artifact_write", {"session_id": "parity", "artifact_id": artifact["artifact_id"], "path": str(path)})
            assert path.read_bytes().startswith(b"\x89PNG")
            jpeg = root / "figure.jpg"
            client.request("result.artifact_write", {"session_id": "parity", "artifact_id": artifact["artifact_id"], "path": str(jpeg)})
            assert jpeg.read_bytes().startswith(b"\xff\xd8\xff")
            archive = root / "public-variables"
            client.request("variable.archive.export", {"session_id": "parity", "operation_id": "export-archive", "path": str(archive), "names": ["df"]})
            manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
            assert manifest["version"] == 2 and manifest["variables"][0]["name"] == "df"
            restored_archive = client.request("variable.archive.import", {"session_id": "parity", "path": str(archive), "overwrite": True})
            assert any(item["variable_name"] == "df" for item in restored_archive["results"])
            client.request("snapshot.settings.set", {"settings": {"enabled": True, "restore_on_startup": True, "max_size_mb": 50}})
            client.execute("parity", "snapshot-precision", "python",
                "snapshot_exact = pd.DataFrame({'large': pd.Series([None, 9007199254740993], dtype=object)})\n"
                "snapshot_native = pl.DataFrame({'large': pl.Series([None, 9223372036854775809], dtype=pl.UInt64)})")
            client.request("system.flush_workspace")
            client.request("session.close", {"session_id": "parity"})
            client.request("session.create", {"session_id": "parity"})
            client.event("session.ready", session_id="parity")
            restored = client.execute("parity", "restored", "python",
                "assert df.shape == (2,3)\n"
                "assert snapshot_exact['large'].dtype == object\n"
                "assert snapshot_exact['large'].tolist() == [None, 9007199254740993]\n"
                "assert snapshot_native.schema['large'] == pl.UInt64\n"
                "assert snapshot_native['large'].to_list() == [None, 9223372036854775809]\ndf")
            assert any(item["variable_name"] == "df" for item in restored["results"])
            client.request("snapshot.settings.set", {"settings": {"enabled": False}})
            result = client.execute("parity", "million", "python", "large = pd.DataFrame({'id': np.arange(10000000), 'group': np.arange(10000000) % 10})\nlarge")
            ref = next(item for item in result["results"] if item["variable_name"] == "large")
            assert ref["row_count"] == 10_000_000
            last_page = client.request("result.page", {"session_id": "parity", "result_id": ref["result_id"],
                "offset": 9_999_800, "limit": 200, "column_offset": 0, "column_limit": 1, "include_columns": False})
            assert last_page["rows"][0] == [9_999_800] and last_page["rows"][-1] == [9_999_999]
            assert last_page["columns"] == [] and last_page["total_columns"] == 2
            started = time.perf_counter()
            bounded_values = client.request("result.column_values", {
                "session_id": "parity", "result_id": ref["result_id"], "column": "group", "limit": 50})
            metrics["header_suggestions_10m_ms"] = round((time.perf_counter() - started) * 1000, 2)
            assert bounded_values["values"] == list(range(10)) and bounded_values["sampled"] is True
            assert bounded_values["scanned_rows"] <= 10_000 and bounded_values["total_rows"] == 10_000_000
            filtered = {"session_id": "parity", "result_id": ref["result_id"], "offset": 0, "limit": 100,
                        "filter": {"filters": [{"column": "group", "operator": "equals", "value": "4"}]},
                        "sort": {"column": "id", "direction": "desc"}}
            measurements = []
            for _ in range(6):
                started = time.perf_counter()
                page = client.request("result.page", filtered)
                measurements.append((time.perf_counter() - started) * 1000)
                assert len(page["rows"]) == 100 and page["total_rows"] == 1_000_000
            metrics.update({"rows": 10_000_000, "page_rows": 100, "filter_sort_cold_ms": round(measurements[0], 2),
                            "filter_sort_cached_median_ms": round(statistics.median(measurements[1:]), 2)})
            chart_started = time.perf_counter()
            large_chart = client.request("result.chart", {"session_id": "parity", "result_id": ref["result_id"],
                "config": {"type": "bar", "x_column": "group", "y_columns": ["id"], "aggregation": "count"}})
            metrics["chart_10m_ms"] = round((time.perf_counter() - chart_started) * 1000, 2)
            assert large_chart["source_rows"] == 10_000_000 and large_chart["point_count"] == 10 and large_chart["bounded"] is False
            assert large_chart["figure"]["data"][0]["y"] == [1_000_000] * 10
            chart_started = time.perf_counter()
            large_restyle = client.request("result.chart", {"session_id": "parity", "chart_id": large_chart["chart_id"],
                "config": {**large_chart["config"], "title": "Restyled ten million", "palette": "warm"}})
            metrics["chart_restyle_10m_ms"] = round((time.perf_counter() - chart_started) * 1000, 2)
            metrics["chart_10m_payload_bytes"] = len(json.dumps(large_chart).encode())
            assert large_restyle["source_rows"] == 10_000_000 and large_restyle["point_count"] == 10
            client.request("result.release", {"session_id": "parity", "result_id": ref["result_id"]})
            client.execute("parity", "release", "python", "assert large.shape == (10000000,2)")
            native = client.execute("parity", "native-polars", "python", "native_large = pl.from_pandas(large)\nnative_large")
            native_ref = next(item for item in native["results"] if item["variable_name"] == "native_large")
            native_page = client.request("result.page", {"session_id": "parity", "result_id": native_ref["result_id"],
                "offset": 9_999_999, "limit": 1, "column_offset": 1, "column_limit": 1, "include_columns": False})
            assert native_page["rows"] == [[9]] and native_page["total_rows"] == 10_000_000
            assert client.request("pynia.catalog")["agents"]
            client.execute("parity", "drivers", "python", "import pyodbc, pymssql, psycopg2, pymysql, mysql.connector, databricks.sql, azure.identity, jedi, jinja2, openpyxl, fastexcel\nassert pyodbc.version")
            precision_probe = client.execute("parity", "combined-precision", "python", "precision_probe = pd.DataFrame(np.full((50,50), 2**52, dtype=np.int64))\nprecision_probe")
            precision_ref = next(item for item in precision_probe["results"] if item["variable_name"] == "precision_probe")
            combined = client.request("result.summary", {"session_id": "parity", "result_id": precision_ref["result_id"]})
            assert Decimal(str(combined["aggregates"]["sum"])) == Decimal(2**52 * 2500)
            precise_path = root / "precise-stream.parquet"
            precise_code = (
                "from decimal import Decimal\n"
                "from pathlib import Path\n"
                "import pyarrow.parquet as pq\n"
                "from src.database.query_stream_exporter import stream_result_set_to_file\n"
                "exact = Decimal('123456789012345678901234567890.123456')\n"
                "chunks = iter([(['amount'], [(exact,)]), (['amount'], [(1.5,)]), (['amount'], [(2.5,)])])\n"
                f"stream_result_set_to_file(['amount'], chunks, path=Path({str(precise_path)!r}), export_format='parquet')\n"
                f"assert pq.read_table({str(precise_path)!r}).column('amount').to_pylist() == [str(exact), '1.5', '2.5']"
            )
            client.execute("parity", "precise-stream", "python", precise_code)
            diagnostics = client.request("diagnostics.info")
            assert diagnostics["runtime"]["qt_loaded"] is False
            no_qt = client.execute("parity", "no-qt", "python", "import sys\nassert not any(name.startswith(('PyQt','PySide')) for name in sys.modules)")
            assert no_qt["status"] == "succeeded"
            # Completion notifications are captured inside the kernel, before
            # another block can change its namespace/result. Exercise the real
            # execution protocol here: no external channel is ever enabled.
            notification_start = time.perf_counter()
            loaded = client.request("notifications.settings.get")["settings"]
            settings = {
                **loaded, "enabled": True, "sound": False,
                "telegram": {**loaded["telegram"], "enabled": False},
                "email": {**loaded["email"], "enabled": False},
            }
            saved = client.request("notifications.settings.set", {"settings": settings})["settings"]
            assert saved["enabled"] is True and saved["sound"] is False
            assert saved["telegram"]["enabled"] is False and saved["email"]["enabled"] is False
            # Snapshot restart above intentionally discarded database handles.
            client.request("connection.connect", {"session_id": "parity", "connection_id": profile["id"]})
            context = {"workspace_id": "parity-workspace", "tab_name": "Notification parity", "blocks": 1}
            config = {
                "enabled": True, "title": "{{tab_name}} / {{block_name}}",
                "message": "{{type}}: {{rows}} rows; first={{result[0][0]}}",
                "color": "#5179ef", "rules": [], "channels": {"telegram": False, "email": False},
            }
            sql_id = "notification-sql"
            queued = client.request("execution.run", {
                "session_id": "parity", "execution_id": sql_id, "language": "sql",
                "code": "SELECT 91 AS value UNION ALL SELECT 92 AS value", "variable_name": "notification_df",
                "notification": {"context": {**context, "block_id": "notification-block-sql", "block_name": "SQL completion"}, "config": config},
            })
            assert queued == {"execution_id": sql_id, "status": "queued"}
            sql_finished = client.event("execution.finished", execution_id=sql_id, session_id="parity")
            assert sql_finished["session_id"] == "parity" and sql_finished["execution_id"] == sql_id
            assert sql_finished["status"] == "succeeded", sql_finished
            sql_ref = sql_finished["results"][0]
            assert sql_ref["row_count"] == 2
            notice = sql_finished["notification"]
            assert notice["enabled"] is True and notice["sound"] is False, notice
            assert notice["success"] is True and notice["status"] == "succeeded", notice
            assert notice["title"] == "Notification parity / SQL completion", notice
            assert notice["message"] == "sql: 2 rows; first=91", notice
            assert not notice["suppressed"] and not any(notice["channels"].values()), notice

            # A print-only Python block must report zero rows and must not
            # render the previous SQL table through the legacy preview fallback.
            print_id = "notification-print"
            client.request("execution.run", {
                "session_id": "parity", "execution_id": print_id, "language": "python",
                "code": "print('notification print-only')",
                "notification": {"context": {**context, "block_id": "notification-block-print", "block_name": "Python print"}, "config": config},
            })
            print_finished = client.event("execution.finished", execution_id=print_id, session_id="parity")
            assert print_finished["status"] == "succeeded" and print_finished["results"] == [], print_finished
            assert print_finished["execution_id"] == print_id and print_finished["session_id"] == "parity"
            print_notice = print_finished["notification"]
            assert print_notice["enabled"] is True and print_notice["sound"] is False
            assert print_notice["title"] == "Notification parity / Python print", print_notice
            assert print_notice["message"].startswith("python: 0 rows; first="), print_notice
            assert "first=91" not in print_notice["message"] and "first=92" not in print_notice["message"], print_notice
            assert sql_finished["notification"]["message"] == "sql: 2 rows; first=91"
            output = client.event("execution.output", execution_id=print_id, session_id="parity")
            assert output["stream"] == "stdout" and "notification print-only" in output["text"], output

            # An explicit SQL result from this same queue remains available to
            # the final Python block, even when that block returns no table.
            queue_id = "notification-queue"
            queue_result = {"result_id": sql_ref["result_id"], "rows": 2}
            client.request("execution.run", {
                "session_id": "parity", "execution_id": queue_id, "language": "python",
                "code": "print('queue completed without a new table')",
                "notification": {"context": {**context, "blocks": 2, "block_id": "notification-block-queue", "block_name": "Queue completion"},
                                 "config": config, "queue_result": queue_result},
            })
            queue_finished = client.event("execution.finished", execution_id=queue_id, session_id="parity")
            assert queue_finished["status"] == "succeeded" and queue_finished["results"] == [], queue_finished
            assert queue_finished["execution_id"] == queue_id and queue_finished["session_id"] == "parity"
            queue_notice = queue_finished["notification"]
            assert queue_notice["title"] == "Notification parity / Queue completion", queue_notice
            assert queue_notice["message"] == "python: 2 rows; first=91", queue_notice
            assert queue_notice["success"] is True and queue_notice["sound"] is False

            error_id = "notification-error"
            client.request("execution.run", {
                "session_id": "parity", "execution_id": error_id, "language": "python",
                "code": "raise RuntimeError('notification-parity-error')",
                "notification": {"context": {**context, "block_id": "notification-block-error", "block_name": "Error completion"},
                                 "config": {**config, "message": "{{status}}: {{error}}; rows={{rows}}"}},
            })
            error_finished = client.event("execution.finished", execution_id=error_id, session_id="parity")
            assert error_finished["status"] == "failed" and "notification-parity-error" in error_finished["error"], error_finished
            assert error_finished["execution_id"] == error_id and error_finished["session_id"] == "parity"
            error_notice = error_finished["notification"]
            assert error_notice["title"] == "Notification parity / Error completion", error_notice
            assert error_notice["enabled"] is True and error_notice["sound"] is False
            assert error_notice["success"] is False and error_notice["status"] == "failed", error_notice
            assert error_notice["message"].startswith("failed:") and "notification-parity-error" in error_notice["message"], error_notice
            assert error_notice["message"].endswith("rows=0"), error_notice

            suppressed_config = {**config, "rules": [{"enabled": True, "left": "{{rows}}", "operator": "equals",
                                                      "value": "2", "action": "suppress", "action_value": ""}]}
            preview = client.request("notifications.evaluate", {
                "session_id": "parity", "config": suppressed_config,
                "context": {**context, "block_id": "notification-block-suppressed", "block_name": "Suppressed SQL",
                            "rows": 2, "result_id": sql_ref["result_id"], "success": True, "type": "sql"},
            })
            assert preview["enabled"] is True and preview["sound"] is False
            assert preview["suppressed"] is True and preview["send_external"] is False, preview
            assert preview["matched_rules"] == [0] and not any(preview["channels"].values()), preview
            suppress_id = "notification-suppressed"
            client.request("execution.run", {
                "session_id": "parity", "execution_id": suppress_id, "language": "sql",
                "code": "SELECT 91 AS value UNION ALL SELECT 92 AS value", "variable_name": "suppressed_notification_df",
                "notification": {"context": {**context, "block_id": "notification-block-suppressed", "block_name": "Suppressed SQL"},
                                 "config": suppressed_config},
            })
            suppressed_finished = client.event("execution.finished", execution_id=suppress_id, session_id="parity")
            assert suppressed_finished["status"] == "succeeded" and suppressed_finished["results"][0]["row_count"] == 2, suppressed_finished
            suppressed_notice = suppressed_finished["notification"]
            assert suppressed_notice["suppressed"] is True and suppressed_notice["send_external"] is False, suppressed_notice
            assert suppressed_notice["message"] == "sql: 2 rows; first=91" and suppressed_notice["matched_rules"] == [0], suppressed_notice
            assert not any(suppressed_notice["channels"].values()), suppressed_notice
            metrics["notification_cases"] = 6
            metrics["notification_capture_ms"] = round((time.perf_counter() - notification_start) * 1000, 2)
        finally:
            if client:
                client.close()
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    if report:
        Path(report).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print("Feature acceptance: SQLite/catalog, Explorer, completion/format, parameters, precise selections, five export formats, Excel import, PNG/JPEG/chart/rich exports, snapshot restart, precise streamed Parquet, projected ten-million-row Pandas/Polars results, immutable completion/queue/error/suppressed notifications and Qt-free kernel OK.")
    print(json.dumps(metrics))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--report")
    args = parser.parse_args()
    smoke(args.executable, args.timeout, args.report)
