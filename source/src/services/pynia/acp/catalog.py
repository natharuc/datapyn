"""First-class ACP agents Pynia can spawn."""

from __future__ import annotations

import base64
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

AgentId = Literal["claude", "cursor", "copilot", "codex"]
AGENT_IDS: tuple[AgentId, ...] = ("claude", "cursor", "copilot", "codex")

StatusKind = Literal[
    "missing_runtime",
    "not_installed",
    "not_authenticated",
    "ready",
]


@dataclass(frozen=True)
class LaunchSpec:
    """One way to start an ACP agent (first match in PATH wins)."""

    command: str
    args: tuple[str, ...] = ()
    needs_node: bool = False


@dataclass(frozen=True)
class InstallHint:
    """Platform install instructions shown in Settings."""

    windows: str
    other: str
    docs_url: str
    login_command: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentSpec:
    id: AgentId
    label: str
    color: str
    icon_name: str
    launches: tuple[LaunchSpec, ...]
    install: InstallHint
    auth_method_id: Optional[str] = None
    mcp_via_cursor_json: bool = False


AGENTS: dict[AgentId, AgentSpec] = {
    "claude": AgentSpec(
        id="claude",
        label="Claude",
        color="#D97757",
        icon_name="claude.svg",
        launches=(
            LaunchSpec("claude-agent-acp", needs_node=True),
            LaunchSpec(
                "npx",
                ("-y", "@agentclientprotocol/claude-agent-acp"),
                needs_node=True,
            ),
        ),
        install=InstallHint(
            windows="npm install -g @anthropic-ai/claude-code @agentclientprotocol/claude-agent-acp",
            other="npm install -g @anthropic-ai/claude-code @agentclientprotocol/claude-agent-acp",
            docs_url="https://github.com/agentclientprotocol/claude-agent-acp",
            login_command=("claude", "/login"),
        ),
        auth_method_id=None,
    ),
    "cursor": AgentSpec(
        id="cursor",
        label="Cursor",
        color="#888888",
        icon_name="cursor.svg",
        launches=(
            LaunchSpec("agent", ("acp",)),
            LaunchSpec("cursor-agent", ("acp",)),
        ),
        install=InstallHint(
            windows=(
                "powershell -NoProfile -ExecutionPolicy Bypass -Command "
                "\"irm 'https://cursor.com/install?win32=true' | iex\""
            ),
            other="curl https://cursor.com/install -fsS | bash",
            docs_url="https://cursor.com/docs/cli/acp",
            login_command=("agent", "login"),
        ),
        auth_method_id="cursor_login",
        mcp_via_cursor_json=True,
    ),
    "copilot": AgentSpec(
        id="copilot",
        label="GitHub Copilot",
        color="#9B59B6",
        icon_name="copilot.svg",
        launches=(
            LaunchSpec("copilot", ("--acp", "--stdio")),
        ),
        install=InstallHint(
            windows="npm install -g @github/copilot",
            other="npm install -g @github/copilot",
            docs_url="https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli",
            login_command=("copilot", "/login"),
        ),
        auth_method_id=None,
    ),
    "codex": AgentSpec(
        id="codex",
        label="Codex",
        color="#10A37F",
        icon_name="codex.svg",
        launches=(
            LaunchSpec("codex-acp", needs_node=True),
            LaunchSpec(
                "npx",
                ("-y", "@agentclientprotocol/codex-acp"),
                needs_node=True,
            ),
        ),
        install=InstallHint(
            windows="npm install -g @openai/codex @agentclientprotocol/codex-acp",
            other="npm install -g @openai/codex @agentclientprotocol/codex-acp",
            docs_url="https://github.com/agentclientprotocol/codex-acp",
            login_command=("codex", "login"),
        ),
        auth_method_id=None,
    ),
}


def get_agent(agent_id: str) -> Optional[AgentSpec]:
    if agent_id in AGENTS:
        return AGENTS[agent_id]  # type: ignore[index]
    return None


def list_agents() -> list[AgentSpec]:
    return [AGENTS[aid] for aid in AGENT_IDS]


def extra_bin_dirs() -> list[Path]:
    """Well-known install locations that may be missing from PATH (GUI apps)."""
    dirs: list[Path] = []
    home = Path.home()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    if appdata:
        dirs.append(Path(appdata) / "npm")
    if local:
        dirs.append(Path(local) / "cursor-agent")
        dirs.append(Path(local) / "Programs" / "cursor" / "resources" / "app" / "bin")
        versions = Path(local) / "cursor-agent" / "versions"
        if versions.is_dir():
            dirs.extend(sorted(versions.iterdir(), reverse=True))
    dirs.append(home / ".local" / "bin")
    dirs.append(home / ".cursor" / "bin")
    dirs.append(home / ".npm-global" / "bin")
    prefix = os.environ.get("npm_config_prefix") or os.environ.get("NPM_CONFIG_PREFIX")
    if prefix:
        dirs.append(Path(prefix))
        dirs.append(Path(prefix) / "bin")
    return dirs


def prepend_bin_dirs_to_path() -> None:
    """Ensure npm / Cursor CLI dirs are on PATH for this process."""
    parts = os.environ.get("PATH", "").split(os.pathsep)
    seen = {p.lower() for p in parts if p}
    extra: list[str] = []
    for directory in extra_bin_dirs():
        if not directory.is_dir():
            continue
        raw = str(directory)
        if raw.lower() in seen:
            continue
        seen.add(raw.lower())
        extra.append(raw)
    if extra:
        os.environ["PATH"] = os.pathsep.join(extra + parts)


def which_command(command: str) -> Optional[str]:
    """Resolve a CLI, including standard npm/Cursor locations outside PATH."""
    found = shutil.which(command)
    if found:
        return found
    names = [command]
    if sys.platform == "win32":
        lower = command.lower()
        if not Path(command).suffix:
            names.extend(
                [
                    f"{command}.cmd",
                    f"{command}.CMD",
                    f"{command}.bat",
                    f"{command}.exe",
                    f"{command}.ps1",
                ]
            )
        elif lower.endswith(".cmd"):
            names.append(command[:-4] + ".CMD")
    for directory in extra_bin_dirs():
        if not directory.is_dir():
            continue
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
    return None


def node_available() -> bool:
    return which_command("node") is not None and which_command("npx") is not None


def resolve_launch(
    spec: AgentSpec, *, allow_npx: bool = True
) -> Optional[tuple[str, list[str]]]:
    """Return (executable, args) for the first launch spec whose command exists."""
    prepend_bin_dirs_to_path()
    for launch in spec.launches:
        if launch.command == "npx" and not allow_npx:
            continue
        path = which_command(launch.command)
        if not path:
            continue
        if launch.needs_node and launch.command == "npx" and not node_available():
            continue
        return path, list(launch.args)
    return None


def resolve_global_launch(spec: AgentSpec) -> Optional[tuple[str, list[str]]]:
    """Like resolve_launch, but ignore npx -y fallbacks (treat as not installed)."""
    return resolve_launch(spec, allow_npx=False)


def popen_argv(command: str, args: list[str]) -> list[str]:
    """Build an argv list that can start .cmd/.bat on Windows."""
    if sys.platform == "win32" and command.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", command, *args]
    return [command, *args]


def agent_icons_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "assets" / "icons" / "agents"


def icon_path(spec: AgentSpec) -> Path:
    return agent_icons_dir() / spec.icon_name


def probe_status(spec: AgentSpec) -> StatusKind:
    """Cheap PATH/runtime probe — does not spawn the agent."""
    if all(launch.needs_node or launch.command == "npx" for launch in spec.launches):
        if not node_available() and resolve_launch(spec) is None:
            return "missing_runtime"
    if resolve_launch(spec) is None:
        if any(launch.needs_node for launch in spec.launches) and not node_available():
            return "missing_runtime"
        return "not_installed"
    return "ready"


def default_cwd() -> str:
    from src.core.workspace_service import get_workspace_service

    return str(get_workspace_service().current_workspace)


def hidden_popen_kwargs() -> dict:
    """Windows: hide console windows when spawning ACP agents."""
    import subprocess

    kwargs: dict = {}
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        kwargs["creationflags"] = flags
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startup
    return kwargs


def icon_data_uri(spec: AgentSpec) -> str:
    """data: URL for the agent SVG (safe inside the chat WebView CSP)."""
    path = icon_path(spec)
    if not path.is_file():
        return ""
    try:
        encoded = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"data:image/svg+xml;base64,{encoded}"


def load_agent_icon(spec: AgentSpec, size: int = 24):
    """Render an agent SVG as a QIcon."""
    from PyQt6.QtCore import QByteArray, QRectF, Qt
    from PyQt6.QtGui import QIcon, QPainter, QPixmap
    from PyQt6.QtSvg import QSvgRenderer

    path = icon_path(spec)
    if not path.is_file():
        return None
    try:
        renderer = QSvgRenderer(QByteArray(path.read_bytes()))
        if not renderer.isValid():
            return None
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        return QIcon(pixmap)
    except Exception:
        return None
