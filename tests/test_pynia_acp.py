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


def test_acp_prompt_includes_tools_and_user_text():
    from src.services.pynia.acp.turn_context import collect_tab_context, format_acp_prompt

    ctx = collect_tab_context("tab-1")
    text = format_acp_prompt("monta um gráfico com esses dados", ctx)
    assert "datapyn_chart" in text
    assert "datapyn_snapshot" in text
    assert "You are Pynia" in text
    assert "ALWAYS use" in text
    assert "THIS TURN" in text
    assert "datapyn_chart operation=create" in text
    assert "monta um gráfico com esses dados" in text


def test_acp_prompt_includes_active_result():
    from src.services.pynia.acp.turn_context import format_acp_prompt

    ctx = {
        "tab_id": "t1",
        "execution_state": {
            "active_result": {
                "rows": 10,
                "columns": ["produto", "premio"],
                "preview": "produto premio\nA 1",
            }
        },
    }
    text = format_acp_prompt("grafico", ctx)
    assert "premio" in text
    assert "grafico" in text
    assert '"rows": 10' in text or "rows" in text


def test_acp_prompt_says_already_connected_and_lists_variables():
    from src.services.pynia.acp.turn_context import format_acp_prompt, format_acp_prompt_parts

    ctx = {
        "tab_id": "t1",
        "tab_name": "ESIM",
        "connection_name": "ESIM",
        "database": "ESIM",
        "is_connected": True,
        "variables": {"df": "DataFrame(10, 3)"},
        "execution_state": {"active_result": {"rows": 10, "columns": ["id"]}},
    }
    text = format_acp_prompt("quantas linhas tem o df?", ctx)
    assert "connected=ESIM" in text
    assert "Do NOT call datapyn_database operation=connect or open" in text
    assert '"df": "DataFrame(10, 3)"' in text
    assert "already connected" in text.lower()
    parts = format_acp_prompt_parts("ok", ctx)
    assert "is_connected is true" in parts[2]["text"]


def test_action_directive_chart_and_query():
    from src.services.pynia.acp.turn_context import action_directive, format_acp_prompt_parts

    chart = action_directive(
        "preciso criar um gráfico de valor de emissao por mes",
        {"execution_state": {"active_result": {"columns": ["mes", "valor_emissao"]}}},
    )
    assert "datapyn_chart" in chart
    assert "valor_emissao" in chart
    assert "Do not ask" in chart
    query = action_directive("analisar e escrever uma query de premio por produto")
    assert "datapyn_run" in query
    parts = format_acp_prompt_parts("cria um grafico", {"tab_id": "t1"})
    assert parts[-1]["text"] == "cria um grafico"
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "text"
    assert "CURRENT TAB JSON" in parts[1]["text"]
    assert "datapyn://" not in parts[1]["text"]
    assert "INSIDE DataPyn" in parts[0]["text"]
    assert "no DataPyn HTTP" in parts[0]["text"]


def test_mcp_tool_schema_is_json_schema():
    from src.services.pynia.tools.registry import PyniaToolRegistry

    registry = PyniaToolRegistry(parent=None, legacy_registry=MagicMock())
    tools = registry.list_tools()
    chart = next(t for t in tools if t["name"] == "datapyn_chart")
    props = chart["inputSchema"]["properties"]
    assert "optional" not in props["operation"]
    assert "operation" in chart["inputSchema"]["required"]
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


def test_send_prompt_requires_agent(qapp):
    host = PyniaAcpHost(mcp_registry=None)
    try:
        with pytest.raises(RuntimeError, match="Choose an agent first"):
            host.send_prompt("tab-1", "hello")
        assert host.state("tab-1").agent_id is None
        assert host.state("tab-1").messages == []
        host.set_agent("tab-1", "claude")
        assert host.state("tab-1").agent_id == "claude"
    finally:
        host.shutdown()


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


def test_mcp_server_config_for_session_has_no_type(qapp):
    host = PyniaMcpHost(MagicMock())
    host.port = 1234
    host.token = "abc"
    cfg = host.mcp_server_config("tab-x")
    assert cfg["name"] == "datapyn"
    assert "type" not in cfg
    copilot = host.mcp_server_config("tab-x", include_type=True)
    assert copilot["type"] == "stdio"


def test_mcp_wrap_and_normalize_tool_names():
    from src.services.pynia.acp.mcp_host import normalize_mcp_tool_name, wrap_tool_result

    assert normalize_mcp_tool_name("datapyn-datapyn_query") == "datapyn_query"
    assert normalize_mcp_tool_name("datapyn/datapyn_snapshot") == "datapyn_snapshot"
    assert normalize_mcp_tool_name("datapyn_edit") == "datapyn_edit"
    wrapped = wrap_tool_result({"content": [{"type": "text", "text": "hello"}]})
    assert wrapped["content"][0]["text"] == "hello"
    assert wrapped["isError"] is False
    err = wrap_tool_result({"error": "nope"})
    assert err["isError"] is True
    assert err["content"][0]["text"] == "nope"


def test_send_mcp_dead_socket_does_not_raise():
    import threading

    from src.services.pynia.acp.mcp_host import _send_mcp

    conn = MagicMock()
    conn.sendall.side_effect = OSError(10038, "not a socket")
    assert _send_mcp(conn, threading.Lock(), {"ok": True}) is False


def test_dispatch_tool_dead_socket_does_not_raise():
    import threading

    host = PyniaMcpHost(MagicMock())
    host._handle_mcp = MagicMock(return_value={"jsonrpc": "2.0", "id": 1, "result": {}})
    conn = MagicMock()
    conn.sendall.side_effect = OSError(10038, "not a socket")
    done = MagicMock()
    host._dispatch_tool(
        conn,
        threading.Lock(),
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        "tab-1",
        done,
    )
    done.assert_called_once()


def test_mcp_parallel_tools_and_prefixed_name(qapp):
    registry = MagicMock()
    registry.list_tools.return_value = [{"name": "datapyn_query"}]
    registry.execute.side_effect = lambda name, args: {
        "content": [{"type": "text", "text": name}]
    }
    registry.pin_session = MagicMock()
    host = PyniaMcpHost(registry)
    host.start()
    try:
        sock = socket.create_connection(("127.0.0.1", host.port), timeout=5)
        sock.sendall((json.dumps({"token": host.token, "tab_id": "tab-x"}) + "\n").encode())
        for req_id, name in (
            (1, "datapyn-datapyn_query"),
            (2, "datapyn_snapshot"),
            (3, "datapyn_inspect"),
        ):
            sock.sendall(
                (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "method": "tools/call",
                            "params": {"name": name, "arguments": {}},
                        }
                    )
                    + "\n"
                ).encode()
            )
        sock.settimeout(0.2)
        buf = b""
        replies = {}
        import time

        deadline = time.time() + 8
        while time.time() < deadline and len(replies) < 3:
            qapp.processEvents()
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                msg = json.loads(line.decode())
                replies[msg.get("id")] = msg
        assert set(replies) == {1, 2, 3}
        assert replies[1]["result"]["content"][0]["text"] == "datapyn_query"
        assert replies[1]["result"]["isError"] is False
        called = [c[0][0] for c in registry.execute.call_args_list]
        assert "datapyn_query" in called
        sock.sendall(
            (json.dumps({"jsonrpc": "2.0", "id": 99, "method": "ping", "params": {}}) + "\n").encode()
        )
        ping_deadline = time.time() + 5
        while time.time() < ping_deadline:
            qapp.processEvents()
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            buf += chunk
            if b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                ping = json.loads(line.decode())
                assert ping["id"] == 99
                break
        else:
            raise AssertionError("socket died after parallel tools/call")
        sock.close()
    finally:
        host.stop()


def test_silent_python_exec_and_property_hint(qapp):
    from src.services.copilot.mcp_tools import MCPToolRegistry

    registry = MCPToolRegistry.__new__(MCPToolRegistry)
    namespace: dict = {}
    session = MagicMock()
    session.namespace = namespace
    session.update_namespace = lambda data: namespace.update(data)
    registry._get_active_session_widget = lambda: MagicMock()
    registry._get_active_session = lambda: session

    ok = MCPToolRegistry._run_silent_python(registry, {"code": "x = 1\nprint(x)"})
    assert "error" not in ok
    assert "1" in ok["content"][0]["text"]

    namespace["wb"] = type("WB", (), {"sheet_names": ["a", "b"]})()
    bad = MCPToolRegistry._run_silent_python(
        registry, {"code": "print(wb.sheet_names())"}
    )
    assert bad.get("error")
    assert "print(wb.sheet_names)" in bad["error"]


def test_copilot_mcp_json_enables_datapyn_tools(qapp, tmp_path):
    registry = MagicMock()
    registry.list_tools.return_value = [{"name": "datapyn_chart"}]
    host = PyniaMcpHost(registry)
    host.start()
    try:
        path = Path(host.write_copilot_mcp_json(str(tmp_path), "tab-x"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        server = payload["mcpServers"]["datapyn"]
        assert server["type"] == "stdio"
        assert server["tools"] == ["*"]
        env = server["env"]
        assert env["DATAPYN_MCP_PORT"] == str(host.port)
        assert env["DATAPYN_MCP_TOKEN"] == host.token
        assert env["DATAPYN_TAB_ID"] == "tab-x"
        assert (tmp_path / ".copilot" / "mcp-config.json").is_file()
    finally:
        host.stop()


def test_autocomplete_uses_separate_session(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.pynia.acp.pool.resolve_launch", _fake_launch)
    monkeypatch.setattr("src.services.pynia.acp.catalog.resolve_launch", _fake_launch)
    monkeypatch.setattr("src.services.pynia.acp.host.default_cwd", lambda: str(tmp_path))
    settings = type(
        "S",
        (),
        {
            "autocomplete_enabled": True,
            "default_agent_id": "claude",
            "agent_model_id": lambda self, _id: "",
            "agent_thought_level": lambda self, _id: "",
            "set_agent_model_id": lambda self, _id, _value: None,
            "set_agent_thought_level": lambda self, _id, _value: None,
        },
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


def test_permission_auto_allows_datapyn_rejects_http_probe():
    from src.services.pynia.acp.permission import (
        permission_should_ask,
        permission_should_reject,
        reject_option_id,
    )

    curl = {
        "toolCall": {
            "toolCallId": "toolu_1",
            "title": "Verificar se o servidor DataPyn está respondendo",
            "kind": "execute",
            "status": "pending",
            "rawInput": {"command": "curl -s http://localhost:3001/api/chart 2>&1 | head -c 100"},
            "commands": ["curl -s http://localhost:3001/api/chart 2>&1 | head -c 100"],
        }
    }
    assert permission_should_reject(curl) is True
    assert permission_should_ask(curl) is False
    assert reject_option_id(curl) == "reject-once"
    assert permission_should_ask({"toolCall": {"title": "datapyn_chart", "kind": "other"}}) is False
    assert permission_should_ask({"toolCall": {"name": "datapyn_snapshot"}}) is False
    assert permission_should_reject({"toolCall": {"name": "datapyn_inspect"}}) is False


def test_permission_asks_only_for_destructive_sql():
    from src.services.pynia.acp.permission import permission_should_ask

    assert permission_should_ask({"toolCall": {"rawInput": {"command": "DROP TABLE foo"}}}) is True
    assert permission_should_ask({"toolCall": {"rawInput": {"sql": "DELETE FROM users"}}}) is True
    assert permission_should_ask({"toolCall": {"rawInput": {"command": "UPDATE accounts SET x=1"}}}) is True
    assert permission_should_ask({"toolCall": {"rawInput": {"sql": "TRUNCATE TABLE logs"}}}) is True
    assert permission_should_ask({"toolCall": {"title": "Update chart", "kind": "execute"}}) is False
    assert permission_should_ask({"toolCall": {"rawInput": {"sql": "SELECT * FROM users"}}}) is False
    assert permission_should_ask({"toolCall": {"kind": "delete", "title": "Remove file"}}) is True


def test_composer_selectors_from_acp_and_saved_prefs():
    from src.services.pynia.acp.session_config import composer_selectors

    snapshot = {
        "configOptions": [
            {
                "id": "model",
                "category": "model",
                "name": "Model",
                "currentValue": "sonnet",
                "options": [
                    {"value": "sonnet", "name": "Sonnet"},
                    {"value": "opus", "name": "Opus"},
                ],
            },
            {
                "id": "thought_level",
                "category": "thought_level",
                "currentValue": "high",
                "options": [{"value": "high", "name": "High"}, {"value": "low", "name": "Low"}],
            },
        ]
    }
    sel = composer_selectors(snapshot)
    assert sel["model"]["current"] == "sonnet"
    assert sel["reasoning"]["current"] == "high"
    assert sel["reasoning"]["hidden"] is False
    preferred = composer_selectors(snapshot, model_id="opus", thought_level="low")
    assert preferred["model"]["current"] == "opus"
    assert preferred["reasoning"]["current"] == "low"
    foreign = composer_selectors(snapshot, model_id="gpt-4.1", thought_level="xhigh")
    assert foreign["model"]["current"] == "sonnet"
    assert foreign["reasoning"]["current"] == "high"
    assert all(item["value"] != "gpt-4.1" for item in foreign["model"]["values"])
    empty = composer_selectors({}, model_id="gpt-4.1", thought_level="low")
    assert empty["model"]["hidden"] is True
    assert empty["model"]["values"] == []
    assert empty["reasoning"]["hidden"] is True
    assert empty["reasoning"]["values"] == []
    loading = composer_selectors({}, loading=True)
    assert loading["model"]["loading"] is True
    assert loading["model"]["hidden"] is False
    assert loading["reasoning"]["hidden"] is True


def test_merge_config_snapshot_keeps_option_lists():
    from src.services.pynia.acp.session_config import composer_selectors, merge_config_snapshot

    previous = {
        "sessionId": "sess-1",
        "configOptions": [
            {
                "id": "model",
                "category": "model",
                "currentValue": "sonnet",
                "options": [
                    {"value": "sonnet", "name": "Sonnet"},
                    {"value": "opus", "name": "Opus"},
                ],
            },
            {
                "id": "thought_level",
                "category": "thought_level",
                "currentValue": "low",
                "options": [{"value": "low", "name": "Low"}, {"value": "high", "name": "High"}],
            },
        ],
    }
    incoming = {
        "configOptions": [
            {"id": "model", "category": "model", "currentValue": "opus"},
            {"id": "thought_level", "category": "thought_level", "currentValue": "high"},
        ]
    }
    merged = merge_config_snapshot(previous, incoming)
    sel = composer_selectors(merged)
    assert sel["model"]["current"] == "opus"
    assert {item["value"] for item in sel["model"]["values"]} == {"sonnet", "opus"}
    assert sel["model"]["hidden"] is False
    assert sel["reasoning"]["current"] == "high"
    assert sel["reasoning"]["hidden"] is False
    wiped = merge_config_snapshot(previous, {"configOptions": []})
    assert wiped["configOptions"] == previous["configOptions"]


def test_composer_selectors_config_id_legacy_models_and_mode():
    from src.services.pynia.acp.session_config import composer_selectors, filter_values

    sel = composer_selectors(
        {
            "configOptions": [
                {
                    "configId": "model",
                    "category": "model",
                    "currentValue": "a",
                    "options": [
                        {"id": "a", "name": "Alpha", "description": "fast"},
                        {"value": "b", "name": "Beta"},
                    ],
                },
                {
                    "id": "mode",
                    "category": "mode",
                    "currentValue": "ask",
                    "options": [{"value": "ask", "name": "Ask"}, {"value": "bypass", "name": "Bypass"}],
                },
            ]
        }
    )
    assert {item["value"] for item in sel["model"]["values"]} == {"a", "b"}
    assert sel["model"]["values"][0]["description"] == "fast"
    assert sel["reasoning"]["hidden"] is True
    assert all(item["value"] != "ask" for item in sel["model"]["values"])

    legacy = composer_selectors(
        {
            "models": {
                "availableModels": [{"modelId": "sonnet", "name": "Sonnet"}],
                "currentModelId": "sonnet",
            }
        }
    )
    assert legacy["model"]["current"] == "sonnet"
    assert legacy["model"]["hidden"] is False
    assert legacy["reasoning"]["hidden"] is True

    values = [
        {"value": "gpt-5", "name": "GPT-5", "description": "flagship"},
        {"value": "sonnet", "name": "Claude Sonnet"},
    ]
    assert [item["value"] for item in filter_values(values, "son")] == ["sonnet"]
    assert [item["value"] for item in filter_values(values, "FLAG")] == ["gpt-5"]
    assert len(filter_values(values, "")) == 2


def test_agent_prefs_isolated_per_agent(monkeypatch):
    from src.services.pynia.settings import PyniaSettingsManager, get_pynia_settings, reset_pynia_settings

    store: dict[str, str] = {}

    class Mem:
        def value(self, key, default=""):
            return store.get(key, default)

        def setValue(self, key, value):
            store[key] = value

    mem = Mem()
    reset_pynia_settings()
    try:
        monkeypatch.setattr(
            PyniaSettingsManager,
            "_settings",
            property(lambda self: mem),
        )
        settings = get_pynia_settings()
        store["default_agent_id"] = "claude"
        store["model_id"] = "legacy-sonnet"
        store["thought_level"] = "high"
        assert settings.agent_model_id("claude") == "legacy-sonnet"
        assert settings.agent_thought_level("claude") == "high"
        assert settings.agent_model_id("copilot") == ""
        settings.set_agent_model_id("copilot", "gpt-5")
        settings.set_agent_thought_level("copilot", "low")
        settings.set_agent_model_id("claude", "opus")
        assert settings.agent_model_id("copilot") == "gpt-5"
        assert settings.agent_thought_level("copilot") == "low"
        assert settings.agent_model_id("claude") == "opus"
        assert settings.agent_thought_level("claude") == "high"
    finally:
        reset_pynia_settings()


class _MemPyniaSettings:
    def __init__(self):
        self.autocomplete_enabled = False
        self.default_agent_id = ""
        self._models: dict[str, str] = {}
        self._thoughts: dict[str, str] = {}

    def agent_model_id(self, agent_id: str) -> str:
        return self._models.get(agent_id, "")

    def set_agent_model_id(self, agent_id: str, value: str) -> None:
        self._models[agent_id] = value

    def agent_thought_level(self, agent_id: str) -> str:
        return self._thoughts.get(agent_id, "")

    def set_agent_thought_level(self, agent_id: str, value: str) -> None:
        self._thoughts[agent_id] = value


def test_set_session_config_keeps_prefs_per_agent(qapp, monkeypatch):
    settings = _MemPyniaSettings()
    monkeypatch.setattr("src.services.pynia.settings.get_pynia_settings", lambda: settings)
    host = PyniaAcpHost(mcp_registry=None)
    try:
        state = host.state("tab-1")
        state.agent_id = "copilot"
        state.config_snapshot = {
            "configOptions": [
                {
                    "id": "model",
                    "category": "model",
                    "currentValue": "auto",
                    "options": [
                        {"value": "auto", "name": "Auto"},
                        {"value": "gpt-5", "name": "GPT-5"},
                    ],
                }
            ]
        }
        host.set_session_config("tab-1", "model", "sonnet")
        assert settings.agent_model_id("copilot") == ""
        host.set_session_config("tab-1", "model", "gpt-5")
        assert settings.agent_model_id("copilot") == "gpt-5"
        host.set_session_config("tab-1", "model", "auto")
        assert settings.agent_model_id("copilot") == "auto"
        host.state("tab-2").agent_id = "claude"
        host.state("tab-2").config_snapshot = {
            "configOptions": [
                {
                    "id": "model",
                    "category": "model",
                    "currentValue": "sonnet",
                    "options": [{"value": "sonnet", "name": "Sonnet"}],
                }
            ]
        }
        host.set_session_config("tab-2", "model", "sonnet")
        assert settings.agent_model_id("claude") == "sonnet"
        assert settings.agent_model_id("copilot") == "auto"
    finally:
        host.shutdown()


def _wait_session_ready(host, qapp, tab_id: str, timeout: float = 15) -> None:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        state = host.state(tab_id)
        if state.session_ready.is_set() and not state.config_loading and state.acp_session_id:
            qapp.processEvents()
            return
        qapp.processEvents()
        time.sleep(0.05)


def test_set_agent_populates_selectors_before_prompt(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.pynia.acp.pool.resolve_launch", _fake_launch)
    monkeypatch.setattr("src.services.pynia.acp.catalog.resolve_launch", _fake_launch)
    monkeypatch.setattr("src.services.pynia.acp.host.default_cwd", lambda: str(tmp_path))
    settings = _MemPyniaSettings()
    monkeypatch.setattr("src.services.pynia.settings.get_pynia_settings", lambda: settings)
    host = PyniaAcpHost(mcp_registry=None)
    seen = []
    host.config_options_changed.connect(lambda _tab, sel: seen.append(sel))
    try:
        host.set_agent("tab-1", "claude")
        assert host.state("tab-1").locked is False
        _wait_session_ready(host, qapp, "tab-1")
        state = host.state("tab-1")
        assert state.acp_session_id
        assert state.config_snapshot.get("configOptions")
        assert seen
        last = seen[-1]
        assert last["model"]["values"]
        assert last["reasoning"]["values"]
        assert last["model"]["hidden"] is False
        assert last["reasoning"]["hidden"] is False
        assert last["model"]["loading"] is False
    finally:
        host.shutdown()


def test_host_auto_allows_non_destructive_tools(qapp):
    from src.services.pynia.acp.agent import ActionRequest

    host = PyniaAcpHost(mcp_registry=None)
    agent = MagicMock()
    host._agents["tab-1"] = agent
    host._states["tab-1"] = TabChatState(tab_id="tab-1", agent_id="claude", acp_session_id="sess-1")
    asked = []
    host.permission_needed.connect(lambda *args: asked.append(args))
    try:
        host._handle_action(
            "tab-1",
            ActionRequest(
                rpc_id=7,
                session_id="sess-1",
                params={
                    "sessionId": "sess-1",
                    "toolCall": {
                        "kind": "execute",
                        "title": "Check server",
                        "rawInput": {"command": "curl -s http://localhost:3001/api/chart"},
                    },
                    "options": [{"optionId": "allow-once"}],
                },
            ),
        )
        agent.answer_action.assert_called_once()
        assert asked == []

        host._handle_action(
            "tab-1",
            ActionRequest(
                rpc_id=8,
                session_id="sess-1",
                params={
                    "sessionId": "sess-1",
                    "toolCall": {"rawInput": {"command": "DROP TABLE t"}},
                    "options": [{"optionId": "allow-once"}],
                },
            ),
        )
        assert len(asked) == 1
        assert asked[0][0] == "tab-1"
    finally:
        host.shutdown()


def test_prompt_emits_composer_config(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.pynia.acp.pool.resolve_launch", _fake_launch)
    monkeypatch.setattr("src.services.pynia.acp.catalog.resolve_launch", _fake_launch)
    monkeypatch.setattr("src.services.pynia.acp.host.default_cwd", lambda: str(tmp_path))
    host = PyniaAcpHost(mcp_registry=None)
    seen = []
    host.config_options_changed.connect(lambda _tab, sel: seen.append(sel))
    try:
        host.set_agent("tab-1", "claude")
        host.send_prompt("tab-1", "hello")
        import time

        deadline = time.time() + 15
        while host.state("tab-1").busy and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        qapp.processEvents()
        assert seen
        last = seen[-1]
        assert last["model"]["values"]
        assert last["reasoning"]["values"]
    finally:
        host.shutdown()


def test_stringify_tool_result_accepts_mcp_dict():
    from src.ui.components.copilot_output_panel import stringify_tool_result

    text, is_error = stringify_tool_result({"ok": "datapyn_run", "elapsed_ms": 3})
    assert "datapyn_run" in text
    assert is_error is False
    err, is_error = stringify_tool_result({"error": "no block"})
    assert "no block" in err
    assert is_error is True
    clipped, _ = stringify_tool_result("x" * 800)
    assert clipped.endswith("...")
    assert len(clipped) == 503


def test_prompt_parts_include_image_attachments():
    from src.services.pynia.acp.turn_context import format_acp_prompt_parts

    parts = format_acp_prompt_parts(
        "o que e isso?",
        {"tab_id": "t1"},
        attachments=[
            {
                "kind": "image",
                "name": "print.png",
                "mime": "image/png",
                "data": "aGVsbG8=",
            }
        ],
    )
    images = [p for p in parts if p.get("type") == "image"]
    assert len(images) == 1
    assert images[0]["data"] == "aGVsbG8="
    assert images[0]["mimeType"] == "image/png"
    assert parts[-1]["text"] == "o que e isso?"


def test_attachments_normalize_and_prompt_blocks():
    from src.services.pynia.acp.attachments import (
        attachments_from_image_bytes,
        display_attachments,
        normalize_attachments,
        prompt_blocks_for_attachments,
    )

    raw = attachments_from_image_bytes(b"\x89PNG", name="shot.png")
    assert raw and raw["kind"] == "image"
    files = normalize_attachments([raw, {"kind": "file", "name": "a.sql", "text": "SELECT 1"}])
    assert len(files) == 2
    blocks = prompt_blocks_for_attachments(files)
    assert blocks[0]["type"] == "image"
    assert "SELECT 1" in blocks[1]["text"]
    shown = display_attachments(files)
    assert shown[0]["src"].startswith("data:image/png;base64,")


def test_mcp_initialize_includes_in_process_instructions(qapp):
    from src.services.pynia.acp.mcp_host import MCP_INSTRUCTIONS, PyniaMcpHost

    registry = MagicMock()
    registry.list_tools.return_value = []
    host = PyniaMcpHost(registry)
    result = host._handle_mcp({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, "")
    assert result["result"]["instructions"] == MCP_INSTRUCTIONS
    assert "in-process" in MCP_INSTRUCTIONS
    assert "no HTTP" in MCP_INSTRUCTIONS
