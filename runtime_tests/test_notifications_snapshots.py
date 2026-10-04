"""Preview secrets/transports are mocked; snapshots use real Parquet in temp dirs."""

from pathlib import Path
import json
import sys

import pandas as pd
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from datapyn_runtime.kernel import ResultStore
from datapyn_runtime import notifications as notify
from datapyn_runtime import variable_snapshot as snapshot


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "workspace"))
    monkeypatch.setenv("DATAPYN_SNAPSHOT_ROOT", str(tmp_path / "cache"))
    secrets = {}
    monkeypatch.setattr(notify, "secret_get", lambda key: secrets.get(key, ""))
    monkeypatch.setattr(notify, "secret_set", lambda key, value: secrets.__setitem__(key, value))
    return tmp_path, secrets


def test_notification_templates_never_evaluate_code_and_use_live_result(isolated):
    store = ResultStore(pd, pl)
    ref = store.register(pd.DataFrame({"value": [42]}), "df")
    response = notify.evaluate({"config": {"enabled": True, "title": "{{tab_name}}", "message": "{{rows}} {{result[0][0]}} {{name}} {{__import__('os')}}"},
                                "context": {"tab_name": "Analysis", "rows": 1000, "result_id": ref["result_id"]}}, {"name": "Nathan"}, store)
    assert response["title"] == "Analysis"
    assert response["message"] == "1,000 42 Nathan {{__import__('os')}}"


def test_notification_reads_native_polars_cells_without_converting_the_frame():
    frame = pl.DataFrame({"first": [1, 2], "second": ["Água", "Café"]})
    assert notify.render_template("{{result[1][1]}}", {}, result=frame) == "Café"
    assert notify.render_template("{{result[4][1]}}", {}, result=frame) == "{{result[4][1]}}"
    assert notify.render_template("{{result[1][1]}}", {}, result=[[1, "Água"], [2, "Café"]]) == "Café"


@pytest.mark.parametrize("operator,left,right,expected", [("equals", " ABC ", "abc", True), ("not_equals", "a", "A", False),
    ("contains", "Abc", "B", True), ("not_contains", "Abc", "x", True), ("greater_than", "1,000", "999", True),
    ("less_than", "1", "2", True), ("is_empty", " ", "", True), ("is_not_empty", "x", "", True), ("greater_than", "text", "1", False)])
def test_notification_rule_operators_match_legacy(operator, left, right, expected):
    assert notify.rule_matches(left, operator, right) is expected


def test_notification_rules_are_ordered_and_suppression_stops(isolated):
    response = notify.evaluate({"config": {"enabled": True, "color": "#000000", "rules": [
        {"left": "{{rows}}", "operator": "greater_than", "value": "10", "action": "set_color", "action_value": "#ff0000"},
        {"left": "{{rows}}", "operator": "equals", "value": "12", "action": "suppress"},
        {"left": "12", "operator": "equals", "value": "12", "action": "set_color", "action_value": "#00ff00"}]}, "context": {"rows": 12}})
    assert response["color"] == "#ff0000"
    assert response["suppressed"] is True
    assert response["send_external"] is False
    assert response["matched_rules"] == [0, 1]


def test_notification_settings_store_no_secrets_in_json(isolated):
    tmp_path, secrets = isolated
    result = notify.settings_set({"settings": {"telegram": {"enabled": True, "chat_id": "123"}}, "secrets": {"telegram_bot_token": "private-token"}})
    assert result["settings"]["telegram"]["configured"] is True
    assert result["secrets_present"]["telegram_bot_token"] is True
    assert "private-token" not in (tmp_path / "workspace" / "notifications.json").read_text()
    assert "private-token" not in json.dumps(result)
    assert secrets["telegram_bot_token"] == "private-token"


def test_notification_preview_and_settings_never_send(isolated, monkeypatch):
    deliveries = []
    monkeypatch.setattr(notify, "deliver", lambda *args: deliveries.append(args))
    notify.settings_set({"settings": {"telegram": {"enabled": True, "chat_id": "123"}}, "secrets": {"telegram_bot_token": "token"}})
    notify.evaluate({"config": {"enabled": True}, "context": {"rows": 2}})
    assert deliveries == []
    notify.send({"config": {"enabled": True}, "context": {"rows": 2}})
    assert len(deliveries) == 1
    notify.test_send({"channel": "telegram"})
    assert len(deliveries) == 2


def test_notification_transport_errors_redact_credentials(isolated, monkeypatch):
    notify.settings_set({"settings": {"telegram": {"enabled": True, "chat_id": "123"}}, "secrets": {"telegram_bot_token": "token"}})
    def fail(*args):
        raise RuntimeError("https://api.telegram.org/botSECRET/sendMessage")
    monkeypatch.setattr(notify, "deliver", fail)
    response = notify.send({"config": {"enabled": True}, "context": {"rows": 2}})
    assert "SECRET" not in json.dumps(response)
    with pytest.raises(RuntimeError) as error:
        notify.test_send({"channel": "telegram"})
    assert "SECRET" not in str(error.value)


def test_preparation_never_sends_and_broker_uses_captured_profile(isolated, monkeypatch):
    tmp_path, secrets = isolated
    notify.settings_set({"settings": {"telegram": {"enabled": True, "chat_id": "first-recipient"}},
                         "secrets": {"telegram_bot_token": "first-secret"}})
    calls = []
    monkeypatch.setattr(notify, "deliver", lambda *args: calls.append(args))
    prepared = notify.prepare({"config": {"enabled": True, "message": "{{value}}"}}, {"value": "first-value"})
    assert calls == []
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "another-workspace"))
    secrets["telegram_bot_token"] = "second-secret"
    result = notify.deliver_prepared(prepared)
    assert calls[0][1]["telegram"]["chat_id"] == "first-recipient"
    assert calls[0][2]["message"] == "first-value"
    assert result["deliveries"] == {"telegram": {"status": "sent"}}
    assert "first-secret" not in json.dumps(result)
    assert "second-secret" not in json.dumps(result)
    assert "_secrets" not in prepared


def test_prepared_delivery_does_not_read_new_keyring(isolated, monkeypatch):
    notify.settings_set({"settings": {"telegram": {"enabled": True, "chat_id": "first"}},
                         "secrets": {"telegram_bot_token": "secret"}})
    prepared = notify.prepare({"config": {"enabled": True}})
    monkeypatch.setattr(notify, "secret_get", lambda _: pytest.fail("Broker must use captured credentials"))
    sent = []
    def post(url, **kwargs):
        sent.append((url, kwargs))
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return {"ok": True}
        return Response()
    import requests
    monkeypatch.setattr(requests, "post", post)
    result = notify.deliver_prepared(prepared)
    assert "botsecret/sendMessage" in sent[0][0]
    assert sent[0][1]["json"]["chat_id"] == "first"
    assert result["deliveries"]["telegram"]["status"] == "sent"


def test_numeric_zero_rule_is_not_empty():
    assert notify.rule_matches(0, "equals", "0")
    assert not notify.rule_matches(0, "is_empty", "")


def test_snapshot_disabled_by_default(isolated):
    store = ResultStore(pd, pl)
    response = snapshot.save({"session_id": "session-1"}, {"df": pd.DataFrame({"x": [1]})}, store)
    assert response == {"saved": False, "reason": "disabled", "variables": []}


def test_snapshot_preserves_pandas_index_series_and_polars(isolated):
    snapshot.settings_set({"settings": {"enabled": True, "max_size_mb": 50}})
    namespace = {"df": pd.DataFrame({"x": [1, 2]}, index=pd.Index([10, 20], name="id")),
                 "series": pd.Series([3, 4], name="named"), "polars": pl.DataFrame({"a": [1, 2]})}
    store = ResultStore(pd, pl)
    saved = snapshot.save({"session_id": "session-1"}, namespace, store)
    assert saved["saved"] is True
    restored = {}
    result = snapshot.restore({"session_id": "session-1"}, restored, store)
    pd.testing.assert_frame_equal(namespace["df"], restored["df"])
    pd.testing.assert_series_equal(namespace["series"], restored["series"])
    assert namespace["polars"].equals(restored["polars"])
    assert len(result["results"]) == 3
    assert len(snapshot.list_snapshots({})["snapshots"]) == 1


def test_snapshot_existing_variables_remain_until_explicit_overwrite(isolated):
    snapshot.settings_set({"settings": {"enabled": True}})
    store = ResultStore(pd, pl)
    snapshot.save({"session_id": "session-1"}, {"df": pd.DataFrame({"x": [1]})}, store)
    namespace = {"df": "preserve"}
    result = snapshot.restore({"session_id": "session-1"}, namespace, store)
    assert namespace["df"] == "preserve"
    assert result["skipped"] == ["df"]
    snapshot.restore({"session_id": "session-1", "overwrite": True}, namespace, store)
    assert isinstance(namespace["df"], pd.DataFrame)


def test_snapshot_new_generation_is_atomic_and_workspace_isolated(isolated, monkeypatch):
    tmp_path, _ = isolated
    snapshot.settings_set({"settings": {"enabled": True}})
    store = ResultStore(pd, pl)
    snapshot.save({"session_id": "same-session"}, {"df": pd.DataFrame({"x": [1]})}, store)
    snapshot.save({"session_id": "same-session"}, {"df": pd.DataFrame({"x": [2]})}, store)
    namespace = {}
    snapshot.restore({"session_id": "same-session"}, namespace, store)
    assert namespace["df"].iat[0, 0] == 2
    session_path = snapshot._session_path("same-session")
    assert len([path for path in session_path.iterdir() if path.is_dir()]) == 1
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path / "other-workspace"))
    assert snapshot.list_snapshots()["snapshots"] == []


@pytest.mark.parametrize("session_id", ["../outside", "C:\\Windows", "", ".", "a/b"])
def test_snapshot_paths_never_escape_cache(isolated, session_id):
    with pytest.raises(ValueError):
        snapshot.delete({"session_id": session_id})


def test_snapshot_rejects_tampered_parquet_filename(isolated):
    snapshot.settings_set({"settings": {"enabled": True}})
    store = ResultStore(pd, pl)
    snapshot.save({"session_id": "session-1"}, {"df": pd.DataFrame({"x": [1]})}, store)
    path, manifest = snapshot._current("session-1")
    manifest["variables"][0]["file"] = "../../other.parquet"
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="path"):
        snapshot.restore({"session_id": "session-1"}, {}, store)


def test_snapshot_delete_only_selected_session(isolated):
    snapshot.settings_set({"settings": {"enabled": True}})
    store = ResultStore(pd, pl)
    for session_id in ("a", "b"):
        snapshot.save({"session_id": session_id}, {"df": pd.DataFrame({"x": [1]})}, store)
    snapshot.delete({"session_id": "a"})
    assert [item["session_id"] for item in snapshot.list_snapshots()["snapshots"]] == ["b"]
