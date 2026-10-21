"""A restored-data notification makes columns immediately available to editors."""

from types import SimpleNamespace

import pytest

from datapyn_runtime import kernel, language, variable_snapshot


@pytest.mark.parametrize("startup", [True, False], ids=["startup", "explicit-restore"])
def test_restore_notification_already_has_completion_metadata(startup, monkeypatch, tmp_path):
    # No processes, real user packages, saved state or database connections.
    monkeypatch.setenv("DATAPYN_RUNTIME_STATE_PATH", str(tmp_path))
    monkeypatch.setenv("DATAPYN_WORKSPACE_PATH", str(tmp_path))
    for name in ("initialize_kernel_group", "isolate_kernel_output", "_watch_parent", "enable_user_packages"):
        monkeypatch.setattr(kernel, name, lambda: None)
    monkeypatch.setattr(variable_snapshot, "settings_get", lambda: {"enabled": True, "restore_on_startup": startup})

    def restore(params, namespace, store):
        frame = store.pd.DataFrame({"amount": [7]})
        namespace["Δados"] = frame
        return {"restored": True, "results": [store.register(frame, "Δados")]}

    monkeypatch.setattr(variable_snapshot, "restore", restore)
    jobs = [] if startup else [{"method": "snapshot.restore", "job_id": "restore", "params": {"session_id": "restored"}}]
    jobs.append({"method": "shutdown", "job_id": "shutdown", "params": {}})
    commands = SimpleNamespace(poll=lambda timeout: True, recv=lambda: jobs.pop(0), close=lambda: None)
    context, observed, messages = {}, [], []

    def send(message):
        messages.append(message)
        if "language_context" in message:
            context.update(message["language_context"])
        if message.get("event") == "namespace.changed" and message["payload"].get("restored"):
            # Request completion synchronously when data becomes visible. This
            # forces the Linux interleaving without a sleep or flaky retries.
            code = 'Δados["'
            result = language.dispatch("language.complete", {
                "language": "python", "code": code, "line": 1, "column": len(code) + 1,
            }, context)
            assert {item["label"] for item in result["items"]} == {"amount"}
            observed.append(message["payload"]["restored"])

    kernel.kernel_main("restored", commands, SimpleNamespace(send=send, close=lambda: None))
    assert observed == [True], messages
