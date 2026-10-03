from __future__ import annotations

import json
import sys

import pytest

from datapyn_runtime.rich_outputs import RichOutputs, json_preview
from datapyn_runtime.language import dispatch
from test_runtime import Client


def test_json_preview_is_bounded_and_handles_cycles():
    cyclic = {"answer": 37}
    cyclic["self"] = cyclic
    assert json_preview(cyclic) == {"answer": 37, "self": "[circular reference]"}
    assert len(json_preview(list(range(10000)))) == 1001


def test_artifacts_retain_bounded_handles_and_write_atomically(tmp_path):
    capture = RichOutputs()
    for index in range(70):
        capture.begin()
        assert capture.capture({"answer": index})
    assert len(capture.artifacts) == 64
    output = capture.outputs[0]
    path = tmp_path / "result.json"
    result = capture.write({"artifact_id": output["artifact_id"], "path": str(path)})
    assert result["format"] == "json" and json.loads(path.read_text()) == {"answer": 69}
    path.write_text("original")
    with pytest.raises(ValueError):
        capture.write({"artifact_id": output["artifact_id"], "path": str(path), "format": "png"})
    assert path.read_text() == "original"
    assert not list(tmp_path.glob(".*.tmp"))


def test_frozen_formatter_finds_unix_root_binary(tmp_path, monkeypatch):
    executable = tmp_path / "ruff"
    executable.write_bytes(b"fake")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    import datapyn_runtime.language as language
    class Result:
        returncode = 0
        stdout = "x = 37\n"
    def run(arguments, **kwargs):
        assert arguments[0] == str(executable)
        return Result()
    monkeypatch.setattr(language.subprocess, "run", run)
    assert dispatch("language.format", {"language": "python", "code": "x=37"}) == {"code": "x = 37\n", "error": None}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path / "state"))
    client = Client()
    client.session()
    yield client
    client.close()


def test_python_json_html_plotly_and_png_outputs_export_without_roundtrip(client, tmp_path):
    for code, output_type, extension in (
        ("{'answer': 37}", "json", "json"),
        ("class HTML:\n def _repr_html_(self): return '<b>37</b>'\nHTML()", "html", "html"),
        ("import plotly.graph_objects as go\ngo.Figure(data=[go.Bar(x=['a'],y=[37])])", "plotly", "html"),
        ("import matplotlib.pyplot as plt\nplt.plot([1,2],[3,4])\nplt.gcf()", "image", "png"),
    ):
        finished = client.execute(code, f"rich-{output_type}")
        assert finished["status"] == "succeeded", finished
        assert len(finished["rich_outputs"]) == 1
        output = finished["rich_outputs"][0]
        assert output["type"] == output_type and output["artifact_id"]
        path = tmp_path / f"rich-{output_type}.{extension}"
        written = client.request("result.artifact_write", {"session_id": "a", "artifact_id": output["artifact_id"], "path": str(path)})
        assert written["bytes"] == path.stat().st_size and written["bytes"] > 0
        if output_type == "image":
            assert path.read_bytes().startswith(b"\x89PNG")
        if output_type == "plotly":
            assert "plotly.js" in path.read_text(encoding="utf-8").lower()


def test_display_captures_multiple_outputs_without_corrupting_stdout(client):
    finished = client.execute("display({'first': 1}, {'second': 2}); print('streamed')", "display-values")
    assert [output["data"] for output in finished["rich_outputs"]] == [{"first": 1}, {"second": 2}]
    assert "streamed" in client.output("display-values")


def test_notification_preparation_stays_private_and_namespace_is_usable(client):
    client.execute("answer = 37", "notification-variable")
    sent = client.request("notifications.send", {"session_id": "a", "config": {"enabled": True, "title": "Local", "message": "Answer {{answer}}"}})
    assert "37" in sent["message"]
    assert not any(key.startswith("_") for key in sent)
    assert not any("notification_delivery" in message for message in client.all_messages)
    assert client.page(client.execute("pd.DataFrame({'answer':[answer]})", "after-notification"))["rows"] == [[37]]
