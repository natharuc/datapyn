"""Responsive, atomic file imports using the real native readers and protocol."""

import json
from pathlib import Path
import sys

import pandas as pd
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from datapyn_runtime import data_tools
from datapyn_runtime.export_control import ExportCancelled
from datapyn_runtime.result_store import ResultStore
from test_runtime import Client


def import_file(path, namespace=None, store=None, **params):
    namespace = namespace if namespace is not None else {}
    store = store or ResultStore(pd, pl)
    result = data_tools.dispatch("data.import", {"path": str(path), "variable_name": "imported", **params}, namespace, store)
    return result, namespace, store


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_auto_csv_uses_native_parser_and_preserves_quotes_newlines_and_unicode(tmp_path, monkeypatch, delimiter):
    path = tmp_path / "sample.csv"
    expected = pd.DataFrame({"id": [1, 2], "text": [f"á{delimiter}quoted", 'line one\nline "two"']})
    expected.to_csv(path, sep=delimiter, index=False, encoding="utf-8-sig")
    original, calls = pd.read_csv, []

    def read(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", read)
    response, namespace, _ = import_file(path, options={"delimiter": None})
    pd.testing.assert_frame_equal(namespace["imported"], expected)
    assert response["result"]["row_count"] == 2
    assert response["options"] == {"delimiter": delimiter, "encoding": "utf-8-sig", "decimal": "."}
    assert len(calls) == 1 and calls[0]["engine"] == "c" and calls[0]["sep"] == delimiter


def test_auto_single_column_never_guesses_a_letter_as_delimiter(tmp_path):
    path = tmp_path / "single.csv"
    path.write_text("name\nAna\nMaria\n", encoding="utf-8")
    _, namespace, _ = import_file(path, options={"delimiter": None})
    assert namespace["imported"].to_dict("list") == {"name": ["Ana", "Maria"]}


def test_csv_encoding_decimal_and_multibyte_sample_boundary(tmp_path):
    path = tmp_path / "encoded.csv"
    path.write_text("name;amount\ncafé;12,34\n", encoding="cp1252")
    _, namespace, _ = import_file(path, options={"delimiter": None, "encoding": "cp1252", "decimal": ","})
    assert namespace["imported"].to_dict("list") == {"name": ["café"], "amount": [12.34]}
    path.write_text("name;amount\n" + "é" * 40000 + ";1\n", encoding="utf-8")
    _, namespace, _ = import_file(path, options={"delimiter": None})
    assert namespace["imported"].iloc[0].tolist() == ["é" * 40000, 1]


def test_large_csv_keeps_single_parser_dtype_inference_and_bounded_metadata(tmp_path):
    path = tmp_path / "large.csv"
    path.write_text("id;value\n" + "".join(f"{index};{index}\n" for index in range(40000)) + "40000;text\n", encoding="utf-8")
    expected = pd.read_csv(path, sep=";")
    namespace, store, progress = {}, ResultStore(pd, pl), []
    response = data_tools.dispatch("data.import", {"path": str(path), "variable_name": "imported"}, namespace, store,
                                   progress=progress.append)
    pd.testing.assert_frame_equal(namespace["imported"], expected)
    assert [item["phase"] for item in progress if item["phase"] != "reading"] == ["registering", "completed"]
    assert progress[0] == {"phase": "reading", "current": 0, "total": path.stat().st_size}
    assert progress[-1]["current"] == progress[-1]["total"] == path.stat().st_size
    assert all(a["current"] <= b["current"] for a, b in zip(progress, progress[1:]))
    assert len(json.dumps(response)) < 2000
    assert len(json.dumps(progress)) < 3000
    assert "rows" not in response["result"]


def test_conflicting_import_is_rejected_before_reading_file(tmp_path, monkeypatch):
    path = tmp_path / "duplicate.csv"
    path.write_text("id\n1\n")
    previous = pd.DataFrame({"keep": [73]})
    monkeypatch.setattr(pd, "read_csv", lambda *args, **kwargs: pytest.fail("Duplicate import read the file"))
    with pytest.raises(ValueError, match="already exists"):
        import_file(path, {"imported": previous})


@pytest.mark.parametrize("cancel_phase", ["reading", "registering"])
def test_cancelled_import_keeps_previous_namespace_and_result_handles(tmp_path, cancel_phase):
    path = tmp_path / "replace.csv"
    path.write_text("id;value\n" + "1;2\n" * 100000)
    previous = pd.DataFrame({"keep": [73]})
    namespace, store = {"imported": previous}, ResultStore(pd, pl)
    previous_ref = store.register(previous, "imported")
    cancelled, progress = [False], []

    def update(item):
        progress.append(item)
        if item["phase"] == cancel_phase and (item["current"] > 0 or cancel_phase == "registering"):
            cancelled[0] = True

    with pytest.raises(ExportCancelled, match="Import cancelled"):
        data_tools.dispatch("data.import", {"path": str(path), "variable_name": "imported", "overwrite": True},
                            namespace, store, progress=update, cancelled=lambda: cancelled[0])
    assert namespace["imported"] is previous
    assert list(store.frames) == [previous_ref["result_id"]]
    assert progress[-1]["phase"] == "cancelled"
    assert not any(item["phase"] == "completed" for item in progress)


def test_cancel_arriving_after_commit_boundary_keeps_a_complete_import(tmp_path, monkeypatch):
    path = tmp_path / "data.csv"
    path.write_text("id;value\n1;2\n")
    previous = pd.DataFrame({"keep": [73]})
    namespace, store = {"imported": previous}, ResultStore(pd, pl)
    previous_ref = store.register(previous, "imported")
    original, cancelled = store.register, [False]

    def register(*args):
        result = original(*args)
        cancelled[0] = True
        return result

    monkeypatch.setattr(store, "register", register)
    response = data_tools.dispatch("data.import", {"path": str(path), "variable_name": "imported", "overwrite": True},
                                   namespace, store, cancelled=lambda: cancelled[0])
    assert namespace["imported"].values.tolist() == [[1, 2]]
    assert store.frames[previous_ref["result_id"]] is previous
    assert store.frames[response["result"]["result_id"]] is namespace["imported"]


def test_excel_sheet_name_uses_native_reader_and_reports_phases(tmp_path):
    path = tmp_path / "workbook.xlsx"
    expected = pd.DataFrame({"id": [1, 2], "name": ["á", "other"]})
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"ignored": [5]}).to_excel(writer, sheet_name="first", index=False)
        expected.to_excel(writer, sheet_name="chosen", index=False)
    namespace, store, progress = {}, ResultStore(pd, pl), []
    data_tools.dispatch("data.import", {"path": str(path), "variable_name": "imported", "options": {"sheet": "chosen"}},
                        namespace, store, progress=progress.append)
    pd.testing.assert_frame_equal(namespace["imported"], expected, check_dtype=False)
    assert [item["phase"] for item in progress] == ["reading", "registering", "completed"]


def test_excel_cancel_between_native_loading_and_conversion_does_not_publish(tmp_path, monkeypatch):
    import fastexcel
    path = tmp_path / "book.xlsx"
    pd.DataFrame({"id": [1]}).to_excel(path, index=False)
    cancelled, calls = [False], []

    class Book:
        def load_sheet(self, sheet):
            calls.append(sheet)
            cancelled[0] = True
            return self

        def to_pandas(self):
            pytest.fail("Cancelled Excel import should skip conversion")

    monkeypatch.setattr(fastexcel, "read_excel", lambda path: Book())
    namespace, store = {}, ResultStore(pd, pl)
    with pytest.raises(ExportCancelled):
        data_tools.dispatch("data.import", {"path": str(path)}, namespace, store, cancelled=lambda: cancelled[0])
    assert calls == [0] and not namespace and not store.frames


@pytest.mark.parametrize("extension", ["json", "parquet"])
def test_other_import_formats_keep_paged_result_contract(tmp_path, extension):
    path = tmp_path / f"data.{extension}"
    expected = pd.DataFrame({"id": [1, 2], "value": [3, 4]})
    if extension == "json":
        expected.to_json(path, orient="records")
    else:
        expected.to_parquet(path)
    response, namespace, store = import_file(path)
    pd.testing.assert_frame_equal(namespace["imported"], expected)
    assert store.page({"result_id": response["result"]["result_id"], "limit": 1})["rows"] == [[1, 3]]


def send(client, method, params):
    client.sequence += 1
    client.process.stdin.write(json.dumps({"id": client.sequence, "method": method, "params": params}) + "\n")
    client.process.stdin.flush()
    return client.sequence


def test_stdio_import_progress_exact_cancel_and_other_session_remain_responsive(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "state"))
    client = Client()
    try:
        client.session("a")
        client.session("b")
        assert client.execute(
            "marker=73\nimported=pd.DataFrame({'retained':[37]})\n"
            "_original_read_csv=pd.read_csv\n"
            "def _blocked_read_csv(source, *args, **kwargs):\n"
            "    import time\n"
            "    while not source.control.cancelled(): time.sleep(.01)\n"
            "    return _original_read_csv(source, *args, **kwargs)\n"
            "pd.read_csv=_blocked_read_csv", "seed")["status"] == "succeeded"
        path = tmp_path / "data.csv"
        path.write_text("id;value\n1;2\n")
        params = {"session_id": "a", "path": str(path), "variable_name": "imported", "overwrite": True, "operation_id": "active"}
        active = send(client, "data.import", params)
        initial = client.wait(lambda message: message.get("event") == "data.import_progress"
                              and message["payload"].get("operation_id") == "active")
        assert initial["payload"]["phase"] == "reading" and initial["payload"]["total"] == path.stat().st_size
        assert client.request("system.info")["protocol_version"] == 1
        other = client.execute("pd.DataFrame({'other':[91]})", "other-session", session_id="b")
        assert client.page(other, session_id="b")["rows"] == [[91]]
        assert client.response("data.import", params)["error"]["code"] == "duplicate_operation"
        assert client.request("data.import_cancel", {"session_id": "a", "operation_id": "stale"})["status"] == "already_finished"
        assert client.request("result.export_cancel", {"session_id": "a", "operation_id": "active"})["status"] == "already_finished"
        queued = send(client, "data.import", {**params, "operation_id": "queued"})
        assert client.request("data.import_cancel", {"session_id": "a", "operation_id": "queued"})["status"] == "cancelled"
        assert client.request("data.import_cancel", {"session_id": "a", "operation_id": "active"})["status"] == "cancelling"
        for identifier in (active, queued):
            assert client.wait(lambda message: message.get("id") == identifier)["error"]["code"] == "cancelled"
        finished = client.execute("pd.read_csv=_original_read_csv\nprint(marker)\nimported", "after-cancel")
        assert client.page(finished)["rows"] == [[37]] and "73" in client.output("after-cancel")
        imported = client.request("data.import", {**params, "operation_id": "retry"})
        assert imported["result"]["row_count"] == 1
        assert client.request("result.page", {"session_id": "a", "result_id": imported["result"]["result_id"], "limit": 1})["rows"] == [[1, 2]]
        assert any(message.get("event") == "data.import_progress" and message["payload"].get("operation_id") == "retry"
                   and message["payload"]["phase"] == "completed" for message in client.all_messages)
        assert not any(message.get("event") == "session.reset" for message in client.all_messages)
    finally:
        client.close()
