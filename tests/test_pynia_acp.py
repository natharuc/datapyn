"""Pynia ACP client: catalog, handshake, tab lock, persistence, MCP, autocomplete."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.session import Session
from src.services.pynia.acp.binding import TabChatState
from src.services.pynia.acp.catalog import AGENT_IDS, list_agents, probe_status, resolve_launch
from src.services.pynia.acp.client import AcpClient
from src.services.pynia.acp.host import PyniaAcpHost
from src.services.pynia.acp.mcp_host import PyniaMcpHost

FAKE_AGENT = str(Path(__file__).parent / "helpers" / "fake_acp_agent.py")


def _fake_launch(_spec):
    return sys.executable, [FAKE_AGENT]


def test_catalog_lists_four_agents():
    specs = list_agents()
    assert [s.id for s in specs] == list(AGENT_IDS)
    assert {"claude", "cursor", "copilot", "codex"} == set(AGENT_IDS)


def test_catalog_probe_not_installed(monkeypatch):
    monkeypatch.setattr("src.services.pynia.acp.catalog.shutil.which", lambda _cmd: None)
    monkeypatch.setattr("src.services.pynia.acp.catalog.node_available", lambda: True)
    monkeypatch.setattr("src.services.pynia.acp.catalog.extra_bin_dirs", lambda: [])
    for spec in list_agents():
        if spec.id in {"claude", "codex"}:
            assert probe_status(spec) in {"not_installed", "missing_runtime"}
        else:
            assert probe_status(spec) == "not_installed"
        assert resolve_launch(spec) is None


def test_which_command_finds_extra_bin(tmp_path, monkeypatch):
    from src.services.pynia.acp.catalog import which_command

    name = "agent.cmd" if sys.platform == "win32" else "agent"
    exe = tmp_path / name
    exe.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr("src.services.pynia.acp.catalog.shutil.which", lambda _cmd: None)
    monkeypatch.setattr("src.services.pynia.acp.catalog.extra_bin_dirs", lambda: [tmp_path])
    assert which_command("agent") == str(exe)


def test_run_install_skips_when_present(monkeypatch):
    from src.services.pynia.acp import installer
    from src.services.pynia.acp.catalog import get_agent

    monkeypatch.setattr(
        installer,
        "resolve_global_launch",
        lambda _spec: (r"C:\Users\me\AppData\Roaming\npm\copilot.CMD", ["--acp", "--stdio"]),
    )
    code, out = installer.run_install(get_agent("copilot"))
    assert code == 0
    assert "Already installed" in out


def test_icon_data_uri_for_brand_svgs():
    from src.services.pynia.acp.catalog import get_agent, icon_data_uri, icon_path

    for agent_id in AGENT_IDS:
        spec = get_agent(agent_id)
        assert icon_path(spec).is_file()
        uri = icon_data_uri(spec)
        assert uri.startswith("data:image/svg+xml;base64,")


def test_popen_argv_wraps_windows_cmd():
    from src.services.pynia.acp.catalog import popen_argv

    wrapped = popen_argv(r"C:\npm\copilot.CMD", ["--acp", "--stdio"])
    if sys.platform == "win32":
        assert wrapped == ["cmd.exe", "/c", r"C:\npm\copilot.CMD", "--acp", "--stdio"]
    else:
        assert wrapped == [r"C:\npm\copilot.CMD", "--acp", "--stdio"]


def test_acp_handshake_initialize_session_prompt(qapp, tmp_path):
    client = AcpClient("fake")
    try:
        client.start(sys.executable, [FAKE_AGENT], cwd=str(tmp_path))
        init = client.initialize(client_name="DataPyn", client_version="test")
        assert init.get("protocolVersion") == 1
        sid = client.session_new(str(tmp_path), mcp_servers=[])
        assert sid.startswith("sess-")
        chunks: list[str] = []

        def on_update(_sid, update):
            if update.get("sessionUpdate") == "agent_message_chunk":
                chunks.append((update.get("content") or {}).get("text") or "")

        from PyQt6.QtCore import Qt

        client.session_update.connect(on_update, Qt.ConnectionType.DirectConnection)
        result = client.session_prompt(sid, "Reply with the single word: pong", timeout=10)
        assert result.get("stopReason") == "end_turn"
        qapp.processEvents()
        assert "pong" in "".join(chunks)
    finally:
        client.stop()


def test_agent_lock_after_first_prompt(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.pynia.acp.pool.resolve_launch", _fake_launch)
    monkeypatch.setattr("src.services.pynia.acp.catalog.resolve_launch", _fake_launch)
    monkeypatch.setattr("src.services.pynia.acp.host.default_cwd", lambda: str(tmp_path))
    host = PyniaAcpHost(mcp_registry=None)
    try:
        host.set_agent("tab-1", "claude")
        host.send_prompt("tab-1", "hello")
        import time

        deadline = time.time() + 15
        while host.state("tab-1").busy and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        qapp.processEvents()
        state = host.state("tab-1")
        assert state.locked is True
        assert state.agent_id == "claude"
        with pytest.raises(RuntimeError, match="locked"):
            host.set_agent("tab-1", "codex")
        host.set_agent("tab-2", "codex")
        assert host.state("tab-2").agent_id == "codex"
        assert host.state("tab-2").locked is False
    finally:
        host.shutdown()


def test_transcript_isolated_per_tab(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.pynia.acp.pool.resolve_launch", _fake_launch)
    monkeypatch.setattr("src.services.pynia.acp.catalog.resolve_launch", _fake_launch)
    monkeypatch.setattr("src.services.pynia.acp.host.default_cwd", lambda: str(tmp_path))
    host = PyniaAcpHost(mcp_registry=None)
    try:
        host.send_prompt("a", "hello a", agent_id="claude")
        host.send_prompt("b", "hello b", agent_id="claude")
        import time

        deadline = time.time() + 20
        while (host.state("a").busy or host.state("b").busy) and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        msgs_a = [m.get("content") for m in host.state("a").messages if m.get("role") == "user"]
        msgs_b = [m.get("content") for m in host.state("b").messages if m.get("role") == "user"]
        assert msgs_a == ["hello a"]
        assert msgs_b == ["hello b"]
        assert host.state("a").acp_session_id != host.state("b").acp_session_id
    finally:
        host.shutdown()


def test_session_pynia_roundtrip():
    session = Session(session_id="s1", title="Tab")
    session.pynia = {
        "agent_id": "cursor",
        "acp_session_id": "sess-9",
        "locked": True,
        "messages": [{"role": "user", "content": "hi"}],
        "acp_session_recreated": False,
    }
    data = session.serialize()
    restored = Session.deserialize(data)
    assert restored.pynia["agent_id"] == "cursor"
    assert restored.pynia["acp_session_id"] == "sess-9"
    assert restored.pynia["locked"] is True
    assert restored.pynia["messages"][0]["content"] == "hi"
    state = TabChatState.from_dict(restored.session_id, restored.pynia)
    assert state.locked is True
    assert state.agent_id == "cursor"


def test_mcp_proxy_dispatches_edit_and_run(qapp):
    registry = MagicMock()
    registry.list_tools.return_value = [{"name": "datapyn_edit"}]
    registry.execute.side_effect = lambda name, args: {"ok": name, "args": args}
    registry.pin_session = MagicMock()
    host = PyniaMcpHost(registry)
    host.start()
    try:
        sock = socket.create_connection(("127.0.0.1", host.port), timeout=5)
        sock.sendall((json.dumps({"token": host.token, "tab_id": "tab-x"}) + "\n").encode())

        def call(req_id, name, arguments):
            sock.sendall(
                (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "method": "tools/call",
                            "params": {"name": name, "arguments": arguments},
                        }
                    )
                    + "\n"
                ).encode()
            )
            sock.settimeout(0.2)
            buf = b""
            import time

            deadline = time.time() + 8
            while time.time() < deadline:
                qapp.processEvents()
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    line = buf.split(b"\n", 1)[0]
                    return json.loads(line.decode())
            raise AssertionError(f"no MCP response for {name}")

        response = call(1, "datapyn_edit", {"operation": "replace", "content": "x"})
        assert response["id"] == 1
        assert response["result"]["isError"] is False
        registry.pin_session.assert_called_with("tab-x")
        assert registry.execute.call_args[0][0] == "datapyn_edit"

        response2 = call(2, "datapyn_run", {"mode": "block"})
        assert response2["id"] == 2
        assert registry.execute.call_args[0][0] == "datapyn_run"
        sock.close()
    finally:
        host.stop()


def test_autocomplete_uses_separate_session(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.pynia.acp.pool.resolve_launch", _fake_launch)
    monkeypatch.setattr("src.services.pynia.acp.catalog.resolve_launch", _fake_launch)
    monkeypatch.setattr("src.services.pynia.acp.host.default_cwd", lambda: str(tmp_path))
    settings = type(
        "S",
        (),
        {"autocomplete_enabled": True, "default_agent_id": "claude"},
    )()
    monkeypatch.setattr("src.services.pynia.settings.get_pynia_settings", lambda: settings)

    host = PyniaAcpHost(mcp_registry=None)
    try:
        host.set_agent("tab-1", "claude")
        host.send_prompt("tab-1", "chat hello")
        import time

        deadline = time.time() + 15
        while host.state("tab-1").busy and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        chat_sid = host.state("tab-1").acp_session_id
        ghost = host.complete_inline("tab-1", "Complete at <CURSOR>\n```python\nx =<CURSOR>\n```", timeout=10)
        qapp.processEvents()
        assert ghost
        assert host.state("tab-1").completion_session_id
        assert host.state("tab-1").completion_session_id != chat_sid
        assert host.state("tab-1").acp_session_id == chat_sid
    finally:
        host.shutdown()


def test_inline_service_debounce_cancel(monkeypatch, qapp):
    from src.editors.monaco.inline_completion_service import InlineCompletionService
    from src.services.pynia.settings import get_pynia_settings

    monkeypatch.setattr(
        "src.editors.monaco.inline_completion_service.get_pynia_settings",
        lambda: type("S", (), {"autocomplete_enabled": True})(),
    )
    service = InlineCompletionService()
    fired = []
    service._start_worker = lambda *a: fired.append(a)
    service.set_pynia_client(MagicMock(complete_inline=lambda *a, **k: "x"))
    service.request_completion("import pandas as pd", "", "python", 1, 18)
    assert service._debounce.isActive()
    service.cancel_request()
    qapp.processEvents()
    assert fired == []
    assert service._pending is None
