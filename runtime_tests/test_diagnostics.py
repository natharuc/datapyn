import json
from pathlib import Path

import pytest

from datapyn_runtime import diagnostics


def test_report_is_allowlisted_and_never_echoes_private_input(monkeypatch):
    params = {"application": {"version": "0.1.0", "name": "SECRET-NAME"},
              "incident": {"kind": "react_render", "component": "editor", "message": "SECRET-CODE", "stack": "SECRET-PATH"},
              "namespace": {"df": "SECRET-DATA"}, "connection": {"password": "SECRET-PASSWORD"}}
    report = diagnostics.info(params)
    data = json.dumps(report)
    assert "SECRET" not in data
    assert str(Path.home()) not in data
    assert report["application"]["version"] == "0.1.0"
    assert report["incident"] == {"kind": "react_render", "component": "editor"}
    assert set(report["runtime"]) == {"python", "implementation", "qt_loaded"}
    assert len(report["packages"]) == len(diagnostics.PACKAGES)


def test_unknown_incident_and_nonversion_strings_are_discarded():
    report = diagnostics.info({"application": {"version": "SECRET"}, "incident": {"kind": "SECRET", "component": "SECRET"}})
    assert "incident" not in report
    assert report["application"]["version"] is None
    assert "SECRET" not in json.dumps(report)


def test_save_creates_actual_atomic_report(tmp_path):
    path = tmp_path / "report.json"
    response = diagnostics.dispatch("diagnostics.save", {"path": str(path), "application": {"version": "0.1.0"}})
    report = json.loads(path.read_text(encoding="utf-8"))
    assert response["report_id"] == report["report_id"]
    assert response["bytes"] == path.stat().st_size
    assert list(tmp_path.iterdir()) == [path]


def test_failed_report_save_preserves_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    path.write_text("original", encoding="utf-8")
    def fail(_):
        raise RuntimeError("source unavailable")
    monkeypatch.setattr(diagnostics, "info", fail)
    with pytest.raises(RuntimeError):
        diagnostics.save({"path": str(path)})
    assert path.read_text() == "original"
