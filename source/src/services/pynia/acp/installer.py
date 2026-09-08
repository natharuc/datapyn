"""Detect, install, and handshake-test ACP agents."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional

from .catalog import (
    AgentSpec,
    StatusKind,
    get_agent,
    hidden_popen_kwargs,
    node_available,
    popen_argv,
    prepend_bin_dirs_to_path,
    probe_status,
    resolve_global_launch,
    resolve_launch,
    which_command,
)
from .client import AcpClient
from .service import AcpSessionService

logger = logging.getLogger(__name__)

OutputCb = Optional[Callable[[str], None]]


@dataclass
class ProbeResult:
    agent_id: str
    status: StatusKind
    command: Optional[str]
    detail: str = ""


def probe_agent(agent_id: str) -> ProbeResult:
    spec = get_agent(agent_id)
    if spec is None:
        return ProbeResult(agent_id, "not_installed", None, "Unknown agent")
    prepend_bin_dirs_to_path()
    status = probe_status(spec)
    launch = resolve_launch(spec)
    command = None
    if launch:
        command = " ".join([launch[0], *launch[1]])
    detail = ""
    if status == "missing_runtime":
        detail = "Node.js (node + npx) is required."
    elif status == "not_installed":
        detail = install_command(spec)
    return ProbeResult(spec.id, status, command, detail)


def install_command(spec: AgentSpec) -> str:
    if os.name == "nt" and spec.id == "copilot":
        if which_command("npm"):
            return "npm install -g @github/copilot"
        return (
            "winget install --id GitHub.Copilot "
            "--accept-package-agreements --accept-source-agreements"
        )
    if os.name == "nt" and spec.id == "cursor":
        return spec.install.windows
    if spec.id in {"claude", "codex"} and not which_command("npm"):
        return spec.install.windows if os.name == "nt" else spec.install.other
    return spec.install.windows if os.name == "nt" else spec.install.other


def _emit(on_output: OutputCb, text: str) -> None:
    if on_output:
        on_output(text)


def run_install(
    spec: AgentSpec,
    timeout: float = 300.0,
    on_output: OutputCb = None,
) -> tuple[int, str]:
    """Install the agent CLI. Skip when a global install is already on disk."""
    prepend_bin_dirs_to_path()
    existing = resolve_global_launch(spec)
    if existing:
        msg = f"Already installed: {existing[0]}"
        _emit(on_output, msg)
        return 0, msg

    if spec.id in {"claude", "codex", "copilot"} and not which_command("npm"):
        if spec.id == "copilot" and which_command("winget"):
            pass
        else:
            msg = "npm was not found. Install Node.js, then try again."
            _emit(on_output, msg)
            return 1, msg

    cmd = install_command(spec)
    _emit(on_output, f"$ {cmd}")
    kwargs = hidden_popen_kwargs()
    kwargs.update(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        shell=True,
        bufsize=1,
    )
    lines: list[str] = []
    try:
        proc = subprocess.Popen(cmd, **kwargs)
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                text = line.rstrip("\r\n")
                if text:
                    lines.append(text)
                    _emit(on_output, text)
        except Exception:
            pass
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            msg = f"Install timed out after {int(timeout)}s"
            _emit(on_output, msg)
            return 1, "\n".join(lines + [msg])
        prepend_bin_dirs_to_path()
        found = resolve_global_launch(spec) or resolve_launch(spec)
        if code == 0 and found:
            done = f"Installed: {found[0]}"
            _emit(on_output, done)
            lines.append(done)
        elif code != 0:
            _emit(on_output, f"Install exited with code {code}")
        return code, "\n".join(lines)
    except Exception as exc:
        _emit(on_output, str(exc))
        return 1, str(exc)


def run_login(spec: AgentSpec, timeout: float = 5.0) -> tuple[int, str]:
    """Kick off the CLI login (often opens a browser)."""
    if not spec.install.login_command:
        return 1, "No login command"
    prepend_bin_dirs_to_path()
    exe = spec.install.login_command[0]
    args = list(spec.install.login_command[1:])
    path = which_command(exe)
    if not path:
        return 1, f"{exe} not found"
    argv = popen_argv(path, args)
    kwargs = hidden_popen_kwargs()
    # Login needs a visible console / browser on some CLIs.
    kwargs.pop("startupinfo", None)
    kwargs.pop("creationflags", None)
    try:
        subprocess.Popen(argv, **kwargs)
        return 0, "Login started"
    except Exception as exc:
        return 1, str(exc)


def handshake_test(spec: AgentSpec, cwd: Optional[str] = None, timeout: float = 45.0) -> tuple[bool, str]:
    """Spawn the agent, initialize, session/new, tiny prompt, then stop.

    Validates ACP connectivity only. DataPyn MCP tools (`datapyn_*`) are attached
    when a real chat turn starts (via session/new mcpServers or Copilot/Cursor config).
    """
    prepend_bin_dirs_to_path()
    launch = resolve_launch(spec)
    if launch is None:
        return False, "Agent is not installed"
    command, args = launch
    work = cwd or tempfile.gettempdir()
    client = AcpClient(spec.id)
    try:
        client.start(command, args, cwd=work)
        svc = AcpSessionService()
        init = svc.handshake(client, auth_method_id=spec.auth_method_id, version="test")
        session_id, _cfg = svc.open_session(client, work, mcp_servers=[])
        try:
            svc.prompt(client, session_id, "Reply with the single word: pong", timeout=timeout)
        except Exception as exc:
            logger.info("Handshake prompt skipped: %s", exc)
        client.session_close(session_id)
        proto = init.get("protocolVersion", "?")
        return (
            True,
            f"ACP {proto} · session {session_id} · "
            "DataPyn MCP tools attach on the next chat message",
        )
    except Exception as exc:
        return False, str(exc)
    finally:
        client.stop()


def runtime_ok() -> bool:
    return node_available()
