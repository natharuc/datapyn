"""Exercise durable incremental session restore through two real runtime processes."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time

from smoke_runtime import RuntimeClient


def smoke(executable=None, timeout=90, report=None):
    metrics = {}
    with tempfile.TemporaryDirectory(prefix="datapyn-persistence-") as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        marker = root / "must-not-execute.txt"
        original = {
            "documents": [{"sessionId": "restore", "title": "Unsaved analysis", "modified": True,
                           "filePath": "C:/synthetic/analysis.dpw", "document": {
                               "version": "1.0", "blocks": [
                                   {"block_key": "first", "language": "sql", "code": "SELECT 1", "height": 210},
                                   {"block_key": "second", "language": "python", "code": f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')", "height": 190}],
                               "desktop": {"focused_block_key": "second"}, "unknown": {"preserved": "áβ"}},
                           "editorViewState": {"second": {"scrollTop": 120, "position": {"lineNumber": 2, "column": 8}}}}],
            "activeIndex": 0, "preferences": {"editorFontSize": 16}, "shortcuts": {"run": "F9"},
            "layout": {"panel": "summary", "rightPanel": "pynia", "custom": 42}, "future": {"kept": True},
        }
        legacy = workspace / "workspace_state.json"
        legacy.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        legacy_bytes = legacy.read_bytes()
        environment = {
            "DATAPYN_RUNTIME_STATE_PATH": str(workspace), "DATAPYN_WORKSPACE_PATH": str(workspace),
            "DATAPYN_SNAPSHOT_ROOT": str(root / "snapshots"), "DATAPYN_RUNTIME_DATA_DIR": str(root / "packages"),
        }
        previous = {key: os.environ.get(key) for key in environment}
        os.environ.update(environment)
        client = None
        try:
            client = RuntimeClient(executable, timeout)
            assert client.request("system.info")["capabilities"]["qt_required"] is False
            restored = client.request("workspace.profiles.state")
            assert restored["state"]["documents"] == original["documents"]
            assert restored["state"]["future"] == original["future"]
            assert legacy.read_bytes() == legacy_bytes
            source_config = root / "pyqt-config"
            source_config.mkdir()
            config = {"connections": {"Empty": {}, "Compat": {"Local": {"db_type": "sqlite", "host": "", "port": 0,
                      "database": ":memory:", "schema": "main", "unknown": "á", "password": "synthetic-never-import"}}},
                      "groups": {"Empty": {"color": "", "future": True}, "Compat": {"color": "#5179ef", "parent": "Empty"}}}
            (source_config / "connections.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            (source_config / "shortcuts.json").write_text('{"shortcuts":{"execute_sql":"F9","future_action":"Alt+F8"}}', encoding="utf-8")
            (source_config / "DataPyn.ini").write_text("[editor]\ncode_font_size=16\n[notifications]\nenabled=false\nsound=false\n", encoding="utf-8")
            (source_config / "CSVExport.ini").write_text('[General]\ndelimiter=","\ndecimal=","\nencoding=cp1252\nheader=false\nopen_folder=false\n', encoding="utf-8")
            (source_config / "ExportSettings.ini").write_text('[General]\ncopy_separator=";"\nnull_display=NULL\nopen_folder=false\n', encoding="utf-8")
            (source_config / "PyniaSettings.ini").write_text('[General]\ndefault_agent_id=copilot\nmodel_id=fixture-model\nthought_level=high\n', encoding="utf-8")
            (source_config / "PackageManager.ini").write_text('[General]\nextra_index_urls=https://packages.invalid/simple\n', encoding="utf-8")
            preview = client.request("configurations.inspect", {"path": str(source_config)})
            assert preview["connections"] == 1 and preview["shortcuts"]["run"] == "F9"
            assert preview["preferences"]["editorFontSize"] == 16
            imported = client.request("configurations.import", {"path": str(source_config), "preview_token": preview["preview_token"]})
            assert imported["imported_connections"] == 1
            defaults = client.request("configurations.defaults.get")["defaults"]
            assert defaults["export_settings"]["include_header"] is False and defaults["export_settings"]["encoding"] == "cp1252"
            assert defaults["copy_separator"] == ";" and defaults["copy_null_display"] == "NULL"
            assert defaults["pynia"]["model_id"] == "fixture-model"
            assert client.request("packages.sources")["sources"][0]["url"] == "https://packages.invalid/simple"
            public = client.request("configurations.export", {"path": str(root / "export-config"), "preferences": original["preferences"], "shortcuts": original["shortcuts"]})
            exported = json.loads((root / "export-config/connections.json").read_text(encoding="utf-8"))
            assert exported["connections"]["Compat"]["Local"]["unknown"] == "á"
            assert "password" not in exported["connections"]["Compat"]["Local"]
            assert exported["groups"]["Empty"]["future"] is True
            assert json.loads((root / "export-config/shortcuts.json").read_text(encoding="utf-8"))["shortcuts"]["execute_sql"] == "F9"
            metrics["configuration_export_files"] = len(public["files"])
            client.request("session.create", {"session_id": "restore"})
            client.event("session.ready", session_id="restore")
            assert not marker.exists(), "Restoring a document must never execute saved code"
            client.request("session.close", {"session_id": "restore"})

            state = deepcopy(original)
            state["documents"] += [
                {"sessionId": f"large_{index}", "title": f"Analysis {index}", "modified": True,
                 "document": {"version": "1.0", "blocks": [{"block_key": f"b{index}", "language": "python", "code": "# saved code\n" * 6800}]}}
                for index in range(120)
            ]
            state["activeIndex"] = 57
            started = time.perf_counter()
            saved = client.request("workspace.profiles.save", {"state": state})
            metrics["initial_save_ms"] = round((time.perf_counter() - started) * 1000, 2)
            assert saved["changed_payloads"] == 120
            edited = deepcopy(state["documents"][58])
            edited["document"]["blocks"][0]["code"] += "print('one changed document')\n"
            patch = {"profile_id": "default", "upserts": [edited], "metadata": {"activeIndex": 58}}
            metrics["full_state_bytes"] = len(json.dumps(state, ensure_ascii=False).encode("utf-8"))
            metrics["edit_patch_bytes"] = len(json.dumps(patch, ensure_ascii=False).encode("utf-8"))
            started = time.perf_counter()
            changed = client.request("workspace.profiles.patch", patch)
            metrics["incremental_save_ms"] = round((time.perf_counter() - started) * 1000, 2)
            assert changed["changed_payloads"] == changed["changed_documents"] == 1
            unchanged = client.request("workspace.profiles.patch", patch)
            assert unchanged["changed_payloads"] == unchanged["changed_documents"] == 0
            cursor = client.request("workspace.profiles.patch", {"upserts": [{"sessionId": "large_57", "editorViewState": {"b57": {"scrollTop": 200}}}]})
            assert cursor["changed_payloads"] == 0 and cursor["changed_headers"] == 1

            # Simulate an abrupt app exit after an acknowledged commit; no clean
            # shutdown or checkpoint is sent before starting the second process.
            client.process.kill()
            client.process.wait(timeout=10)
            client.close()
            client = RuntimeClient(executable, timeout)
            started = time.perf_counter()
            reopened = client.request("workspace.profiles.state")
            metrics["restart_restore_ms"] = round((time.perf_counter() - started) * 1000, 2)
            current = reopened["state"]
            assert len(current["documents"]) == 121 and current["activeIndex"] == 58
            assert current["documents"][58]["document"] == edited["document"]
            assert current["documents"][58]["editorViewState"] == {"b57": {"scrollTop": 200}}
            assert current["documents"][0] == original["documents"][0]
            assert current["documents"][119]["document"] == state["documents"][119]["document"]
            assert current["layout"] == original["layout"] and current["future"] == original["future"]
            assert not marker.exists() and legacy.read_bytes() == legacy_bytes
            assert client.request("configurations.defaults.get")["defaults"] == defaults
            metrics["storage"] = reopened["storage"]
            metrics["journal_mode"] = reopened["journal_mode"]
            metrics["saved_documents"] = len(current["documents"])
            metrics["edit_changed_payloads"] = changed["changed_payloads"]
            metrics["cursor_changed_payloads"] = cursor["changed_payloads"]
            metrics["payload_reduction_percent"] = round(100 * (1 - metrics["edit_patch_bytes"] / metrics["full_state_bytes"]), 2)
        finally:
            if client:
                client.close()
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    if report:
        Path(report).write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--report")
    args = parser.parse_args()
    smoke(args.executable, args.timeout, args.report)
