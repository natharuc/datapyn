"""Actual SQLite downloads and atomic failures; no external databases needed."""

import csv
from pathlib import Path
import os
import subprocess
import sys
from unittest.mock import Mock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from datapyn_runtime.database import SQLiteConnector
from datapyn_runtime import stream_export
from src.database.query_stream_exporter import StreamExportResult, stream_arrow_to_file


@pytest.fixture
def connector():
    connection = SQLiteConnector(":memory:")
    connection.connection.execute("CREATE TABLE sample (id INTEGER, name TEXT)")
    connection.connection.executemany("INSERT INTO sample VALUES (?, ?)", ((index, f"name {index}") for index in range(12003)))
    connection.connection.commit()
    yield connection
    connection.disconnect()


def test_actual_sqlite_csv_download_has_multiple_bounded_chunks(connector, tmp_path):
    progress = []
    # Neither pandas nor execute_query is used by the streaming path.
    connector.execute_query = Mock(side_effect=AssertionError("must not materialize a DataFrame"))
    path = tmp_path / "download.csv"
    response = stream_export.run(connector, "SELECT * FROM sample ORDER BY id", path=path,
                                 options={"delimiter": ";"}, on_progress=progress.append)
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.reader(source, delimiter=";"))
    assert len(rows) == 12004
    assert rows[1] == ["0", "name 0"]
    assert rows[-1] == ["12002", "name 12002"]
    assert [item["rows"] for item in progress] == [5000, 10000, 12003]
    assert response["total_rows"] == 12003
    assert response["files"][0]["size_bytes"] == path.stat().st_size
    assert not list(tmp_path.glob(".datapyn-*"))


def test_actual_parquet_download(connector, tmp_path):
    path = tmp_path / "download.parquet"
    response = stream_export.run(connector, "SELECT * FROM sample", path=path, export_format="parquet")
    table = pq.read_table(path)
    assert response["total_rows"] == table.num_rows == 12003
    assert table.column("id")[12002].as_py() == 12002
    assert pq.ParquetFile(path).num_row_groups == 3


def test_bound_parameters_and_semicolon_in_string(connector, tmp_path):
    path = tmp_path / "params.csv"
    response = stream_export.run(connector, "SELECT '{{literal}};' AS text, id FROM sample WHERE id >= :minimum ORDER BY id",
                                 path=path, parameters={"minimum": 12001})
    assert response["total_rows"] == 2
    assert "12002" in path.read_text(encoding="utf-8-sig")
    assert "{{literal}};" in path.read_text(encoding="utf-8-sig")


def test_multiple_result_sets(connector, tmp_path):
    path = tmp_path / "sets.csv"
    response = stream_export.run(connector, "SELECT 1 AS a; SELECT 2 AS b;", path=path)
    assert [Path(item["path"]).name for item in response["files"]] == ["sets.csv", "sets_2.csv"]
    assert response["total_rows"] == 2
    assert (tmp_path / "sets_2.csv").read_text(encoding="utf-8-sig").strip() == "b\n2"


def test_empty_query_result_has_header(connector, tmp_path):
    response = stream_export.run(connector, "SELECT id FROM sample WHERE 0", path=tmp_path / "empty.csv")
    assert response["total_rows"] == 0
    assert (tmp_path / "empty.csv").read_text(encoding="utf-8-sig") == "id\n"


def test_cancel_preserves_existing_file_and_cleans_stages(connector, tmp_path):
    path = tmp_path / "existing.csv"
    path.write_text("original", encoding="utf-8")
    cancelled = False
    def progress(_):
        nonlocal cancelled
        cancelled = True
    response = stream_export.run(connector, "SELECT * FROM sample", path=path,
                                 on_progress=progress, is_cancelled=lambda: cancelled)
    assert response["cancelled"]
    assert path.read_text() == "original"
    assert not list(tmp_path.glob(".datapyn-*"))


def test_query_failure_preserves_existing_file_and_cleans_stages(connector, tmp_path):
    path = tmp_path / "existing.csv"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(Exception, match="missing"):
        stream_export.run(connector, "SELECT * FROM sample; SELECT * FROM missing;", path=path)
    assert path.read_text() == "original"
    assert not list(tmp_path.glob(".datapyn-*"))


def test_extra_result_never_overwrites_an_unselected_file(connector, tmp_path):
    path = tmp_path / "existing.csv"
    path.write_text("base", encoding="utf-8")
    extra = tmp_path / "existing_2.csv"
    extra.write_text("extra", encoding="utf-8")
    with pytest.raises(FileExistsError, match="additional"):
        stream_export.run(connector, "SELECT 1; SELECT 2;", path=path)
    assert path.read_text() == "base"
    assert extra.read_text() == "extra"
    assert not list(tmp_path.glob(".datapyn-*"))


def test_production_connector_streamer_receives_original_query_and_parameters(tmp_path):
    def driver(query, **params):
        params["base_path"].write_text("a\nvalue\n", encoding="utf-8")
        params["on_progress"](1, 1, 8)
        return StreamExportResult(files=[params["base_path"]], row_counts=[1], columns_per_file=[["a"]])
    connector = Mock(stream_query_to_files=Mock(side_effect=driver))
    parameters = [{"name": "x", "value": "value"}]
    result = stream_export.run(connector, "SELECT {{x}}; GO SELECT 'quote;'", path=tmp_path / "prod.csv", parameters=parameters)
    assert result["total_rows"] == 1
    call = connector.stream_query_to_files.call_args
    assert call.args[0] == "SELECT {{x}}; GO SELECT 'quote;'"
    assert call.kwargs["parameters"] is parameters


def test_driver_reports_partial_error_without_committing(tmp_path):
    def driver(_, **params):
        params["base_path"].write_text("partial", encoding="utf-8")
        return StreamExportResult(files=[params["base_path"]], errors=["query failed"])
    path = tmp_path / "prod.csv"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(RuntimeError, match="query failed"):
        stream_export.run(Mock(stream_query_to_files=driver), "SELECT", path=path)
    assert path.read_text() == "original"
    assert not list(tmp_path.glob(".datapyn-*"))


def test_cleanup_only_deletes_exact_stage_identifier(tmp_path):
    first = tmp_path / ".datapyn-export-one.csv"
    second = tmp_path / ".datapyn-export-one_2.parquet"
    other = tmp_path / ".datapyn-export-one-other.csv"
    for path in (first, second, other):
        path.write_text("stage", encoding="utf-8")
    stream_export.cleanup(tmp_path / "user.csv", "one")
    assert not first.exists() and not second.exists()
    assert other.exists()


@pytest.mark.parametrize("kill_target", ["sets_2.csv", "sets.csv"])
def test_hard_kill_during_multi_file_commit_recovers_original(tmp_path, kill_target):
    destination = tmp_path / "sets.csv"
    destination.write_text("original", encoding="utf-8")
    token = "kill-test"
    first = tmp_path / f".datapyn-export-{token}.csv"
    second = tmp_path / f".datapyn-export-{token}_2.csv"
    first.write_text("new primary", encoding="utf-8")
    second.write_text("new secondary", encoding="utf-8")
    program = """
import os,sys
from pathlib import Path
from datapyn_runtime import stream_export
root=Path(sys.argv[1]); target=sys.argv[2]
replace=stream_export.os.replace
def killed(source,destination):
    replace(source,destination)
    if Path(destination).name==target:
        os._exit(17)
stream_export.os.replace=killed
stream_export._commit([root/'.datapyn-export-kill-test.csv',root/'.datapyn-export-kill-test_2.csv'],[root/'sets.csv',root/'sets_2.csv'],False,'kill-test')
"""
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "source")}
    killed = subprocess.run([sys.executable, "-c", program, str(tmp_path), kill_target], env=environment, capture_output=True, timeout=20)
    assert killed.returncode == 17, killed.stderr.decode(errors="replace")
    stream_export.cleanup(destination, token)
    assert destination.read_text() == "original"
    assert not (tmp_path / "sets_2.csv").exists()
    assert list(tmp_path.iterdir()) == [destination]


def test_completed_multi_file_commit_discards_journal_and_backups(connector, tmp_path):
    destination = tmp_path / "sets.csv"
    destination.write_text("original", encoding="utf-8")
    response = stream_export.run(connector, "SELECT 1; SELECT 2;", path=destination, options={"stage_id": "committed"})
    assert response["total_rows"] == 2
    assert set(path.name for path in tmp_path.iterdir()) == {"sets.csv", "sets_2.csv"}


def test_arrow_schema_evolution_never_reads_whole_parquet(tmp_path, monkeypatch):
    batches = iter([pa.table({"v": list(range(12003))}), pa.table({"v": ["changed"]})])
    monkeypatch.setattr(pq, "read_table", Mock(side_effect=AssertionError("whole file reads prohibited")))
    path = tmp_path / "evolving.parquet"
    count = stream_arrow_to_file(lambda _: next(batches, None), path=path, export_format="parquet")
    assert count == 12004
    with pq.ParquetFile(path) as result:
        assert result.metadata.num_rows == 12004
        assert result.read().column("v")[12003].as_py() == "changed"
    assert not list(tmp_path.glob(".datapyn-*"))


@pytest.mark.parametrize("options", [{"delimiter": "xx"}, {"decimal": ":"}, {"stage_id": "../bad"}, {"header": "yes"}])
def test_invalid_options_rejected_before_execution(connector, tmp_path, options):
    with pytest.raises(ValueError):
        stream_export.run(connector, "SELECT 1", path=tmp_path / "invalid.csv", options=options)
    assert not list(tmp_path.iterdir())
