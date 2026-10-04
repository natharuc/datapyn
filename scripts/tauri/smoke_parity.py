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
            client.request("system.flush_workspace")
            client.request("session.close", {"session_id": "parity"})
            client.request("session.create", {"session_id": "parity"})
            client.event("session.ready", session_id="parity")
            restored = client.execute("parity", "restored", "python", "assert df.shape == (2,3)\ndf")
            assert any(item["variable_name"] == "df" for item in restored["results"])
            client.request("snapshot.settings.set", {"settings": {"enabled": False}})
            result = client.execute("parity", "million", "python", "large = pd.DataFrame({'id': np.arange(1000000), 'group': np.arange(1000000) % 10})\nlarge")
            ref = next(item for item in result["results"] if item["variable_name"] == "large")
            assert ref["row_count"] == 1_000_000
            filtered = {"session_id": "parity", "result_id": ref["result_id"], "offset": 0, "limit": 100,
                        "filter": {"filters": [{"column": "group", "operator": "equals", "value": "4"}]},
                        "sort": {"column": "id", "direction": "desc"}}
            measurements = []
            for _ in range(6):
                started = time.perf_counter()
                page = client.request("result.page", filtered)
                measurements.append((time.perf_counter() - started) * 1000)
                assert len(page["rows"]) == 100 and page["total_rows"] == 100_000
            metrics.update({"rows": 1_000_000, "page_rows": 100, "filter_sort_cold_ms": round(measurements[0], 2),
                            "filter_sort_cached_median_ms": round(statistics.median(measurements[1:]), 2)})
            client.request("result.release", {"session_id": "parity", "result_id": ref["result_id"]})
            client.execute("parity", "release", "python", "assert large.shape == (1000000,2)")
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
    print("Feature acceptance: SQLite/catalog, Explorer, completion/format, parameters, precise selections, five export formats, Excel import, PNG/JPEG/chart/rich exports, snapshot restart, precise streamed Parquet, paged million-row result and Qt-free kernel OK.")
    print(json.dumps(metrics))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--report")
    args = parser.parse_args()
    smoke(args.executable, args.timeout, args.report)
