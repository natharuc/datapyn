"""
CopilotClient - GitHub Copilot integration using the official SDK.

Uses the GitHub Copilot SDK (copilot) which communicates with the
Copilot CLI via JSON-RPC.

The client maintains a persistent session to preserve conversation context.
Tool execution is thread-safe via QMetaObject.invokeMethod.
"""

import json
import logging
import os
import sys
import time
import functools
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .copilot_sdk_compat import apply_sdk_compat_patches

apply_sdk_compat_patches()

from PyQt6.QtCore import (
    QObject, QThread, pyqtSignal, pyqtSlot,
    QMutex, QMutexLocker, Qt, QMetaObject, Q_ARG,
)

if TYPE_CHECKING:
    from .mcp_tools import MCPToolRegistry

logger = logging.getLogger(__name__)


def _safe_log_preview(value: Any, limit: int = 200) -> str:
    """Return ASCII-safe log preview (Windows consoles often use cp1252)."""
    if value is None:
        return "empty"
    text = str(value)
    if len(text) > limit:
        text = text[:limit] + "..."
    return text.encode("ascii", errors="backslashreplace").decode("ascii")

from .copilot_models import (
    fallback_models,
    find_model,
    model_supported_reasoning_efforts,
    model_supports_reasoning_effort,
    normalize_models,
    normalize_reasoning_effort,
    usage_snapshot_from_event,
    usage_snapshot_for_model,
    usage_snapshot_from_quota,
)
from .copilot_attachments import (
    AttachmentValidationError,
    build_sdk_attachments,
    validate_attachments_for_model,
)
from .copilot_settings import get_copilot_settings
from .copilot_process import popen_hidden, run_hidden

# Backward-compatible alias for modules that import _CREATE_NO_WINDOW from here.
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Default models - will be updated from SDK at runtime
DEFAULT_MODELS = fallback_models()

_CLI_DISCOVERY_CACHE: Optional[tuple] = None
_MAX_RGLOB_PER_FOLDER = 6


def _parse_copilot_cli_version(text: str) -> tuple:
    """Parse 'GitHub Copilot CLI 0.0.411.' into (0, 0, 411)."""
    import re
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def _read_copilot_cli_version(cli_path: str) -> tuple:
    """Return semver tuple for a Copilot CLI binary."""
    def _run_version(args: list) -> tuple:
        try:
            result = run_hidden(
                args,
                text=True,
                timeout=12,
                env={**os.environ, "ELECTRON_RUN_AS_NODE": ""},
            )
            output = f"{result.stdout}\n{result.stderr}"
            if result.returncode != 0 or "Cannot find" in output:
                return (0, 0, 0)
            return _parse_copilot_cli_version(output)
        except Exception:
            return (0, 0, 0)

    version = _run_version([cli_path, "--no-auto-update", "--version"])
    if version != (0, 0, 0):
        return version
    return _run_version([cli_path, "--version"])


def invalidate_copilot_cli_cache() -> None:
    """Clear cached CLI discovery (call after npm install/update)."""
    global _CLI_DISCOVERY_CACHE
    _CLI_DISCOVERY_CACHE = None


def _discover_copilot_cli_candidates() -> list:
    """Collect Copilot CLI binaries from SDK bundle, VS Code/Cursor, npm, WinGet, PATH."""
    import sys
    import shutil
    from pathlib import Path

    seen = set()
    candidates: list = []

    def add(path) -> None:
        if not path:
            return
        resolved = Path(path)
        if not resolved.exists():
            return
        if sys.platform == "win32" and resolved.suffix.lower() in {".cmd", ".bat"}:
            return
        key = str(resolved.resolve())
        if key in seen:
            return
        seen.add(key)
        candidates.append(str(resolved))

    def add_rglob(folder: Path, pattern: str) -> None:
        count = 0
        try:
            for nested in folder.rglob(pattern):
                add(nested)
                count += 1
                if count >= _MAX_RGLOB_PER_FOLDER:
                    break
        except OSError:
            pass

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        add(Path(sys._MEIPASS) / "copilot" / "bin" / "copilot.exe")

    for site_pkg in sys.path:
        bundled = Path(site_pkg) / "copilot" / "bin" / "copilot.exe" if sys.platform == "win32" else Path(site_pkg) / "copilot" / "bin" / "copilot"
        add(bundled)

    app_data = os.environ.get("APPDATA", "")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    user_profile = os.environ.get("USERPROFILE", "")

    if sys.platform == "win32":
        for product in ("Code", "Code - Insiders", "Cursor"):
            storage = Path(app_data) / product / "User" / "globalStorage" / "github.copilot-chat"
            if not storage.is_dir():
                continue
            for sub in ("copilotCli", "copilot-cli", "copilot"):
                folder = storage / sub
                if not folder.is_dir():
                    continue
                add(folder / "copilot.exe")
                add_rglob(folder, "copilot.exe")

        add(Path(app_data) / "npm" / "copilot.exe")

        winget_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_root.is_dir():
            try:
                for pkg in winget_root.glob("GitHub.Copilot*"):
                    add(pkg / "copilot.exe")
                    add_rglob(pkg, "copilot.exe")
            except OSError:
                pass

        for path in (
            Path(local_app_data) / "GitHub CLI" / "copilot" / "copilot.exe",
            Path(app_data) / "GitHub CLI" / "copilot" / "copilot.exe",
            Path(local_app_data) / "Programs" / "copilot" / "copilot.exe",
            Path(user_profile) / ".copilot" / "bin" / "copilot.exe",
            Path(user_profile) / "scoop" / "shims" / "copilot.exe",
        ):
            add(path)
    else:
        home = Path.home()
        for path in (
            home / ".copilot" / "bin" / "copilot",
            home / ".local" / "bin" / "copilot",
            Path("/usr/local/bin/copilot"),
        ):
            add(path)

    copilot_in_path = shutil.which("copilot")
    if copilot_in_path:
        add(copilot_in_path)

    return candidates


def _pick_newest_copilot_cli() -> tuple:
    """Pick the newest working Copilot CLI. Returns (path, version_tuple)."""
    global _CLI_DISCOVERY_CACHE
    if _CLI_DISCOVERY_CACHE is not None:
        return _CLI_DISCOVERY_CACHE

    best_path = ""
    best_version = (0, 0, 0)
    for cli_path in _discover_copilot_cli_candidates():
        version = _read_copilot_cli_version(cli_path)
        if version == (0, 0, 0):
            continue
        if version >= best_version:
            best_version = version
            best_path = cli_path

    _CLI_DISCOVERY_CACHE = (best_path, best_version)
    return _CLI_DISCOVERY_CACHE


def _verify_cli_works(cli_path: str) -> bool:
    """Verify that a copilot CLI binary actually works (not a broken shim)."""
    return _read_copilot_cli_version(cli_path) != (0, 0, 0)


def _get_sdk_options():
    """Get SDK client options, preferring the newest working Copilot CLI."""
    try:
        from copilot import SubprocessConfig
    except ImportError:
        SubprocessConfig = None

    cli_path, version = _pick_newest_copilot_cli()
    cli_env = {**os.environ, "ELECTRON_RUN_AS_NODE": ""}
    if cli_path and SubprocessConfig is not None:
        logger.info("Using Copilot CLI v%s.%s.%s at %s", *version, cli_path)
        return SubprocessConfig(cli_path=cli_path, env=cli_env)
    if cli_path:
        logger.info("Using Copilot CLI v%s.%s.%s at %s (legacy SDK config)", *version, cli_path)
        return {"cli_path": cli_path, "env": cli_env}
    logger.debug("No working Copilot CLI found; SDK will use its default bundled CLI")
    return None


def _gh_executable() -> str:
    import shutil
    return shutil.which("gh") or ""


def _is_gh_logged_in(gh_path: str = "") -> bool:
    """Return True when GitHub CLI reports an active github.com session."""
    gh_path = gh_path or _gh_executable()
    if not gh_path:
        return False
    import subprocess
    try:
        result = run_hidden(
            [gh_path, "auth", "status", "-h", "github.com"],
            text=True,
            timeout=12,
        )
        output = f"{result.stdout}\n{result.stderr}"
        if result.returncode != 0:
            return False
        output_lower = output.lower()
        return (
            "logged in to github.com" in output_lower
            or "logado em github.com" in output_lower
            or "logged in to github.com account" in output_lower
        )
    except Exception as exc:
        logger.debug("Could not check gh auth status: %s", exc)
        return False


def _try_import_sdk():
    """Try to import the Copilot SDK."""
    try:
        from copilot import CopilotClient as SDKClient
        from copilot.generated.session_events import SessionEventType

        try:
            from copilot.tools import Tool as SDKTool
        except ImportError:
            from copilot import Tool as SDKTool  # SDK <= 0.1.x

        return SDKClient, SDKTool, SessionEventType, None
    except ImportError as e:
        return None, None, None, str(e)


_DEFAULT_DISABLED_SKILLS = [
    "view", "grep", "shell", "bash", "read_file", "write_file",
    "search_files", "list_directory", "report_intent", "search_code",
    "file_search", "web_search", "fetch_webpage", "terminal",
    "run_command", "list_files", "read", "write", "search",
]


def _sdk_system_message(text: Optional[str]) -> Optional[Dict[str, str]]:
    """Build SDK 0.3+ system message config from plain text."""
    if not text:
        return None
    return {"mode": "append", "content": text}


def _session_error_text(error_data: Any) -> str:
    """Extract a user-facing message from a Copilot SESSION_ERROR payload."""
    if error_data is None:
        return "Copilot session error"
    message = getattr(error_data, "message", None)
    if message:
        return str(message)
    return str(error_data)


async def _sdk_create_session(
    sdk_client,
    *,
    model: str,
    streaming: bool = True,
    tools: Optional[List[Any]] = None,
    system_message: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    disabled_skills: Optional[List[str]] = None,
    our_tool_names: Optional[set] = None,
):
    """Create a Copilot SDK session using the keyword-only SDK 0.3+ API."""
    from copilot.session import PermissionHandler

    kwargs: Dict[str, Any] = {
        "on_permission_request": PermissionHandler.approve_all,
        "model": model,
        "streaming": streaming,
    }
    if tools:
        kwargs["tools"] = tools

    sys_msg = _sdk_system_message(system_message)
    if sys_msg:
        kwargs["system_message"] = sys_msg

    if disabled_skills is not None:
        kwargs["disabled_skills"] = disabled_skills

    if our_tool_names is not None:
        async def on_pre_tool_use(input_data, invocation):
            tool_name = input_data.get("toolName", "")
            if tool_name not in our_tool_names:
                logger.warning("Blocking built-in tool: %s", tool_name)
                return {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Tool '{tool_name}' is not available. Use only DataPyn tools."
                    ),
                }
            logger.info("Allowing tool: %s", tool_name)
            return {"permissionDecision": "allow"}

        kwargs["hooks"] = {"on_pre_tool_use": on_pre_tool_use}

    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort

    try:
        return await sdk_client.create_session(**kwargs)
    except Exception:
        if kwargs.pop("reasoning_effort", None):
            logger.warning(
                "SDK rejected reasoning_effort; retrying session without it",
                exc_info=True,
            )
            return await sdk_client.create_session(**kwargs)
        raise


class ThreadSafeToolExecutor(QObject):
    """
    Executes MCP tools on the main Qt thread from any background thread.

    Uses a queued signal with BlockingQueuedConnection — more reliable than
    QMetaObject.invokeMethod across Python thread-pool / asyncio workers.
    """

    _execute_requested = pyqtSignal(str, str)

    def __init__(self, registry: "MCPToolRegistry", parent=None):
        super().__init__(parent)
        self._registry = registry
        self._result: Dict[str, Any] = {}
        self._mutex = QMutex()

        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            self.moveToThread(app.thread())

        self._execute_requested.connect(
            self._do_execute_on_main_thread,
            Qt.ConnectionType.BlockingQueuedConnection,
        )

    @pyqtSlot(str, str)
    def _do_execute_on_main_thread(self, tool_name: str, arguments_json: str) -> None:
        """Execute tool on the GUI thread."""
        start = time.perf_counter()
        try:
            arguments = json.loads(arguments_json) if arguments_json else {}
            logger.info("[MAIN THREAD] Executing tool: %s", tool_name)
            result = self._registry.execute(tool_name, arguments)
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("[MAIN THREAD] Tool %s finished in %.0fms", tool_name, elapsed_ms)
            with QMutexLocker(self._mutex):
                self._result = result
        except Exception as e:
            logger.exception("[MAIN THREAD] Error executing tool %s", tool_name)
            with QMutexLocker(self._mutex):
                self._result = {"error": str(e)}

    @staticmethod
    def _format_result(result: Dict[str, Any]) -> str:
        if "error" in result:
            return f"Error: {result['error']}"
        content = result.get("content", [])
        return "\n".join(c.get("text", str(c)) for c in content)

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute a tool and return the SDK-facing text result."""
        results = self.execute_batch([(tool_name, arguments or {})])
        return results[0] if results else "Error: empty tool result"

    def execute_batch(self, calls: List[tuple]) -> List[str]:
        """Execute multiple tools with a single main-thread hop when possible."""
        from PyQt6.QtWidgets import QApplication

        if not calls:
            return []

        normalized = []
        for item in calls:
            if not item:
                continue
            name = item[0]
            args = item[1] if len(item) > 1 else {}
            normalized.append((name, args if isinstance(args, dict) else {}))

        app = QApplication.instance()
        on_main = app and QThread.currentThread() == app.thread()

        def _run_all_on_main() -> List[str]:
            outputs: List[str] = []
            for tool_name, arguments in normalized:
                arguments_json = json.dumps(arguments) if arguments else "{}"
                self._do_execute_on_main_thread(tool_name, arguments_json)
                with QMutexLocker(self._mutex):
                    outputs.append(self._format_result(dict(self._result)))
                    self._result = {}
            return outputs

        if on_main:
            return _run_all_on_main()

        outputs: List[str] = []
        for tool_name, arguments in normalized:
            arguments_json = json.dumps(arguments) if arguments else "{}"
            logger.debug("[WORKER] Dispatching tool to main thread: %s", tool_name)
            try:
                self._execute_requested.emit(tool_name, arguments_json)
            except Exception as e:
                logger.exception("Failed to dispatch tool %s to main thread", tool_name)
                outputs.append(f"Error: Could not run {tool_name} on main thread ({e})")
                continue
            with QMutexLocker(self._mutex):
                outputs.append(self._format_result(dict(self._result)))
                self._result = {}
        return outputs


class CopilotWorker(QObject):
    """Worker that manages Copilot SDK client in background thread."""

    # Signals
    chunk = pyqtSignal(str)  # Streaming text chunk
    complete = pyqtSignal(str)  # Full response
    error = pyqtSignal(str)  # Error message
    auth_ok = pyqtSignal()  # Auth verified
    auth_needed = pyqtSignal()  # Auth required
    auth_started = pyqtSignal(str)  # Login process started with info message
    auth_required = pyqtSignal(str, str)  # Device code and verification URL
    models_ready = pyqtSignal(list)  # List of available models
    usage_ready = pyqtSignal(dict)  # Account/session usage snapshot
    tool_call = pyqtSignal(str, dict, str)  # tool_name, arguments, tool_call_id
    tool_result = pyqtSignal(str, str, str)  # tool_name, result, tool_call_id
    thinking = pyqtSignal(str)  # Reasoning text
    finished = pyqtSignal()
    ready = pyqtSignal()  # Worker is ready to accept chat requests
    inline_complete = pyqtSignal(str)  # Inline completion result
    gh_not_found = pyqtSignal()  # GitHub CLI not installed
    license_warning = pyqtSignal(str)  # License may not support chat

    def __init__(self, tool_executor: ThreadSafeToolExecutor = None):
        super().__init__()
        self._model = "gpt-4o"
        self._sdk_client = None
        self._session = None
        self._tool_executor = tool_executor
        self._sdk_tools: List[Any] = []
        self._cancelled = False
        self._prompt = ""
        self._system_message = ""
        self._reasoning_effort = "auto"
        self._available_models = [dict(model) for model in DEFAULT_MODELS]
        self._session_signature = None
        self._loop = None  # Persistent event loop
        self._inline_prompt = ""  # For inline completions
        self._login_process = None
        self._attachments: List[Dict[str, Any]] = []

    def set_model(self, model: str):
        self._model = model

    def set_prompt(self, prompt: str):
        self._prompt = prompt

    def set_system_message(self, system_message: str):
        self._system_message = system_message

    def set_reasoning_effort(self, effort: str):
        self._reasoning_effort = normalize_reasoning_effort(effort)

    def set_available_models(self, models: List[Dict[str, Any]]):
        self._available_models = normalize_models(models) or [dict(model) for model in DEFAULT_MODELS]
    
    def set_inline_prompt(self, prompt: str):
        """Set prompt for inline completion request."""
        self._inline_prompt = prompt

    def set_attachments(self, attachments: Optional[List[Dict[str, Any]]]):
        """Set image attachments for the next chat turn."""
        self._attachments = list(attachments or [])

    def _ensure_loop(self):
        """Ensure event loop is available and active. Creates one if needed.
        
        Returns the event loop. This prevents creating multiple loops
        which can cause resource leaks.
        """
        import asyncio
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    def cancel(self):
        self._cancelled = True
        login_process = getattr(self, "_login_process", None)
        if login_process is not None and login_process.poll() is None:
            try:
                login_process.kill()
            except Exception:
                pass
        if self._session and self._loop and not self._loop.is_closed():
            try:
                # Run abort() coroutine in the worker's event loop
                self._loop.run_until_complete(self._session.abort())
            except Exception:
                pass

    def _complete_auth_from_gh(self) -> bool:
        """Verify Copilot SDK access after GitHub CLI authentication succeeds."""
        self._ensure_loop()
        SDKClient, _, _, import_err = _try_import_sdk()
        if SDKClient is None:
            self.error.emit(f"Copilot SDK not available: {import_err}")
            self.finished.emit()
            return False

        try:
            if self._sdk_client is None:
                self._sdk_client = SDKClient(_get_sdk_options())
                self._loop.run_until_complete(self._sdk_client.start())
            model_list = self._loop.run_until_complete(self._fetch_models())
            self.set_available_models(model_list)
            self.models_ready.emit(model_list)
            self.usage_ready.emit(self._loop.run_until_complete(self._async_usage_snapshot()))
            self.auth_ok.emit()
            self.ready.emit()
            return True
        except Exception as exc:
            logger.warning("Auth verification failed after GitHub login: %s", exc)
            self.error.emit(str(exc))
            self.finished.emit()
            return False

    @pyqtSlot()
    def run_refresh_metadata(self):
        """Refresh model and quota metadata without sending a chat message."""
        self._ensure_loop()
        try:
            self._loop.run_until_complete(self._async_refresh_metadata())
        except Exception as e:
            logger.warning("Failed to refresh Copilot metadata: %s", e)

    async def _clear_models_cache(self) -> None:
        if not self._sdk_client:
            return
        lock = getattr(self._sdk_client, "_models_cache_lock", None)
        if lock is None:
            self._sdk_client._models_cache = None
            return
        async with lock:
            self._sdk_client._models_cache = None

    async def _fetch_models(self) -> list:
        """Fetch models from the CLI, bypassing SDK cache when refreshing."""
        await self._clear_models_cache()
        models = await self._sdk_client.list_models()
        return normalize_models(models)

    async def _async_refresh_metadata(self):
        """Fetch latest model metadata and quota from the SDK server."""
        if not self._sdk_client:
            SDKClient, _, _, import_err = _try_import_sdk()
            if SDKClient is None:
                self.error.emit(f"Copilot SDK not available: {import_err}")
                return
            self._sdk_client = SDKClient(_get_sdk_options())
            await self._sdk_client.start()

        model_list = await self._fetch_models()
        if model_list:
            self.set_available_models(model_list)
            self.models_ready.emit(model_list)
            logger.info("Refreshed %d Copilot models", len(model_list))
        self.usage_ready.emit(await self._async_usage_snapshot())

    async def _async_usage_snapshot(self) -> Dict[str, Any]:
        """Fetch account quota and convert it to the UI usage shape."""
        if not self._sdk_client:
            return usage_snapshot_for_model(self._available_models, self._model)
        try:
            quota = await self._sdk_client.rpc.account.get_quota()
            return usage_snapshot_from_quota(quota, self._available_models, self._model)
        except Exception as e:
            logger.info("Copilot quota is unavailable: %s", e)
            return usage_snapshot_for_model(self._available_models, self._model)

    def run_init(self):
        """Initialize SDK client and verify auth. Keep loop/client alive for session persistence."""
        # Use persistent event loop
        self._ensure_loop()
        
        try:
            SDKClient, SDKTool, _, import_err = _try_import_sdk()
            if SDKClient is None:
                self.error.emit(f"Copilot SDK not available: {import_err}")
                self.finished.emit()
                return

            # Create client and start (async)
            self._sdk_client = SDKClient(_get_sdk_options())
            self._loop.run_until_complete(self._sdk_client.start())

            # List models to verify auth (async)
            try:
                model_list = self._loop.run_until_complete(self._fetch_models())
                logger.info("SDK returned %d models", len(model_list))
                self.set_available_models(model_list)
                self.models_ready.emit(model_list)
                self.usage_ready.emit(self._loop.run_until_complete(self._async_usage_snapshot()))
                self.auth_ok.emit()
                # Keep worker alive - emit ready for subsequent chats
                self.ready.emit()
            except Exception as e:
                error_str = str(e)
                logger.warning(f"list_models failed (may be normal for enterprise): {e}")
                # Check if this is a 403 error - indicates license doesn't support chat
                if "403" in error_str or "unauthorized" in error_str.lower():
                    self.license_warning.emit(
                        "Your Copilot license may not support Chat API. "
                        "Chat may not work. Contact your organization admin."
                    )
                # Emit default models for enterprise accounts that may not list models
                self.models_ready.emit(fallback_models())
                self.auth_ok.emit()
                self.ready.emit()

        except Exception as e:
            logger.exception("Error initializing Copilot SDK")
            self.error.emit(str(e))
            self.finished.emit()

    def run_login(self):
        """Run GitHub CLI login process automatically. Keep loop/client persistent."""
        import re
        import subprocess
        import time

        self._cancelled = False
        self._login_process = None
        self._ensure_loop()

        try:
            gh_path = _gh_executable()
            if not gh_path:
                self.gh_not_found.emit()
                self.finished.emit()
                return

            if _is_gh_logged_in(gh_path):
                logger.info("GitHub CLI already authenticated; verifying Copilot SDK")
                self.auth_started.emit("Verifying GitHub authentication...")
                self._complete_auth_from_gh()
                return

            self.auth_started.emit("Starting GitHub authentication...")

            process = popen_hidden(
                [gh_path, "auth", "login", "-h", "github.com", "-p", "https", "-w"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self._login_process = process

            device_code = None
            verification_url = None
            output_lines = []

            try:
                for _ in range(20):
                    if self._cancelled:
                        process.kill()
                        self.error.emit("Authentication cancelled")
                        self.finished.emit()
                        return

                    line = process.stdout.readline()
                    if not line:
                        break
                    output_lines.append(line)
                    logger.debug("gh output: %s", line.strip())

                    code_match = re.search(r"code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})", line, re.IGNORECASE)
                    if code_match:
                        device_code = code_match.group(1)
                        logger.info("Found device code: %s", device_code)

                    url_match = re.search(r"(https://github\.com/login/device)", line)
                    if url_match:
                        verification_url = url_match.group(1)

                    if device_code:
                        break
                    if "Press Enter" in line or "open github.com" in line:
                        break

                if device_code:
                    verification_url = verification_url or "https://github.com/login/device"
                    self.auth_required.emit(device_code, verification_url)
                    try:
                        process.stdin.write("\n")
                        process.stdin.flush()
                    except Exception:
                        pass

                    for _ in range(90):
                        if self._cancelled:
                            process.kill()
                            self.error.emit("Authentication cancelled")
                            self.finished.emit()
                            return
                        if _is_gh_logged_in(gh_path):
                            if process.poll() is None:
                                try:
                                    process.kill()
                                except Exception:
                                    pass
                            break
                        time.sleep(2)
                    else:
                        if process.poll() is None:
                            process.kill()
                        self.error.emit("Authentication timed out. Please try again.")
                        self.finished.emit()
                        return
                else:
                    stdout_rest, _ = process.communicate(timeout=30)
                    output_lines.append(stdout_rest or "")

            except subprocess.TimeoutExpired:
                process.kill()
                self.error.emit("Authentication timed out. Please try again.")
                self.finished.emit()
                return
            finally:
                self._login_process = None

            full_output = "".join(output_lines)
            if _is_gh_logged_in(gh_path) or process.returncode in (0, None) or "Logged in as" in full_output:
                logger.info("GitHub auth completed successfully")
                self._complete_auth_from_gh()
                return

            error_msg = full_output.strip() or "Authentication failed"
            logger.error("GitHub auth failed: %s", error_msg)
            self.error.emit(f"GitHub authentication failed: {error_msg}")
            self.finished.emit()

        except subprocess.TimeoutExpired:
            self.error.emit("Authentication timed out. Please try again.")
            self.finished.emit()
        except Exception as e:
            logger.exception("Error during GitHub login")
            self.error.emit(str(e))
            self.finished.emit()
        finally:
            self._login_process = None

    def run_add_account_login(self):
        """Run GitHub CLI login to add another account (never short-circuit on existing auth)."""
        import re
        import subprocess
        import time

        self._cancelled = False
        self._login_process = None
        self._ensure_loop()

        try:
            gh_path = _gh_executable()
            if not gh_path:
                self.gh_not_found.emit()
                self.finished.emit()
                return

            self.auth_started.emit("Adding GitHub account...")
            process = popen_hidden(
                [gh_path, "auth", "login", "-h", "github.com", "-p", "https", "-w"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self._login_process = process

            device_code = None
            verification_url = None
            output_lines = []

            try:
                for _ in range(20):
                    if self._cancelled:
                        process.kill()
                        self.error.emit("Authentication cancelled")
                        self.finished.emit()
                        return

                    line = process.stdout.readline()
                    if not line:
                        break
                    output_lines.append(line)
                    logger.debug("gh output: %s", line.strip())

                    code_match = re.search(r"code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})", line, re.IGNORECASE)
                    if code_match:
                        device_code = code_match.group(1)

                    url_match = re.search(r"(https://github\.com/login/device)", line)
                    if url_match:
                        verification_url = url_match.group(1)

                    if device_code:
                        break
                    if "Press Enter" in line or "open github.com" in line:
                        break

                if device_code:
                    verification_url = verification_url or "https://github.com/login/device"
                    self.auth_required.emit(device_code, verification_url)
                    try:
                        process.stdin.write("\n")
                        process.stdin.flush()
                    except Exception:
                        pass

                    for _ in range(90):
                        if self._cancelled:
                            process.kill()
                            self.error.emit("Authentication cancelled")
                            self.finished.emit()
                            return
                        if process.poll() is not None:
                            break
                        time.sleep(2)
                else:
                    stdout_rest, _ = process.communicate(timeout=30)
                    output_lines.append(stdout_rest or "")

            except subprocess.TimeoutExpired:
                process.kill()
                self.error.emit("Authentication timed out. Please try again.")
                self.finished.emit()
                return
            finally:
                self._login_process = None

            full_output = "".join(output_lines)
            if _is_gh_logged_in(gh_path) or process.returncode in (0, None) or "Logged in as" in full_output:
                logger.info("GitHub account added successfully")
                self._complete_auth_from_gh()
                return

            error_msg = full_output.strip() or "Authentication failed"
            self.error.emit(f"GitHub authentication failed: {error_msg}")
            self.finished.emit()

        except Exception as e:
            logger.exception("Error during GitHub add-account login")
            self.error.emit(str(e))
            self.finished.emit()
        finally:
            self._login_process = None

    @pyqtSlot()
    def reset_chat_session(self):
        """Destroy the persistent SDK session so the next chat starts fresh."""
        try:
            self._ensure_loop()
            self._loop.run_until_complete(self._async_reset_chat_session())
        except Exception as e:
            logger.warning("Error resetting Copilot chat session: %s", e)

    async def _async_reset_chat_session(self):
        if not self._session:
            self._session_signature = None
            return
        try:
            await self._session.destroy()
        except Exception:
            try:
                await self._session.abort()
            except Exception:
                pass
        self._session = None
        self._session_signature = None
        self._tool_call_counts = {}
        logger.info("[CHAT] Copilot session reset for new chat")

    @pyqtSlot()
    def run_chat(self):
        """Send chat message and stream response. Uses persistent loop/client."""
        try:
            self._do_chat()
        except Exception as e:
            logger.exception("Error in Copilot chat")
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def _do_chat(self):
        """Internal chat implementation using persistent asyncio loop."""
        # Use persistent loop
        self._ensure_loop()
        
        self._loop.run_until_complete(self._async_chat())

    async def _async_chat(self):
        """Async chat implementation."""
        import asyncio
        
        # Reset cancellation flag at start of each chat
        self._cancelled = False
        
        SDKClient, SDKTool, EventType, import_err = _try_import_sdk()
        if SDKClient is None:
            self.error.emit(f"Copilot SDK not available: {import_err}")
            return

        # Initialize client if needed
        logger.info(f"[CHAT] sdk_client exists: {self._sdk_client is not None}, session exists: {self._session is not None}")
        if not self._sdk_client:
            logger.info("[CHAT] Creating new SDK client")
            self._sdk_client = SDKClient(_get_sdk_options())
            await self._sdk_client.start()
            logger.info("[CHAT] Copilot SDK client started")

        # Build SDK tools if we have an executor
        if self._tool_executor and not self._sdk_tools:
            self._sdk_tools = self._build_sdk_tools(SDKTool)
            logger.info(f"[CHAT] Built {len(self._sdk_tools)} SDK tools")
            for t in self._sdk_tools:
                logger.info(f"  Tool: {t.name}")

        session_signature = self._build_session_signature()

        # Create session if needed, or recreate when stable session config changes.
        if not self._session or self._session_signature != session_signature:
            logger.info("[CHAT] Creating new session")
            if self._session:
                try:
                    await self._session.abort()
                except Exception:
                    pass
            await self._async_create_session()
            self._session_signature = session_signature
            logger.info("[CHAT] Copilot session created")

        if not self._prompt and not self._attachments:
            self.error.emit("No message to send")
            return

        try:
            sdk_attachments = validate_attachments_for_model(
                self._attachments,
                self._available_models,
                self._model,
            )
        except AttachmentValidationError as exc:
            self.error.emit(str(exc))
            return

        # Stream response
        full_response = ""
        
        # Set up event collection
        events = []
        idle_event = asyncio.Event()
        session_error: Optional[str] = None
        start_time = time.time()
        last_event_time = start_time
        idle_timeout = 180  # 3 minutes without SDK activity
        max_turn_timeout = 600  # 10 minutes absolute cap
        event_count = 0
        
        def on_event(event):
            nonlocal session_error, last_event_time
            last_event_time = time.time()
            events.append(event)
            logger.debug(f"SDK event: {event.type}")
            if event.type == EventType.SESSION_IDLE:
                logger.info(f"Session idle, full_response so far: {len(full_response)} chars")
                idle_event.set()
            elif event.type == EventType.SESSION_ERROR:
                error_data = getattr(event, "data", None)
                session_error = _session_error_text(error_data)
                logger.error("Session error: %s", error_data)
                idle_event.set()
        
        # Register handler
        unsubscribe = self._session.on(on_event)
        our_tool_names = {t.name for t in self._sdk_tools} if self._sdk_tools else set()
        
        try:
            logger.info("[CHAT] Sending message, prompt_len=%s, attachments=%s",
                        len(self._prompt), len(sdk_attachments))
            logger.info("[CHAT] Prompt: %s", _safe_log_preview(self._prompt, 100))
            await self._session.send(
                self._prompt,
                attachments=build_sdk_attachments(sdk_attachments) or None,
            )
            logger.info("[CHAT] Message sent, waiting for events...")
            
            while not idle_event.is_set() and not self._cancelled:
                now = time.time()
                if now - start_time > max_turn_timeout:
                    self.error.emit("Chat request timed out")
                    break
                if now - last_event_time > idle_timeout:
                    self.error.emit("Chat request timed out")
                    break
                
                # Process any queued events
                while events:
                    event = events.pop(0)
                    event_type = event.type
                    event_count += 1
                    
                    # Log all event types for debugging
                    logger.info(f"[CHAT] Event #{event_count}: {event_type}")
                    
                    if event_type == EventType.ASSISTANT_MESSAGE_DELTA:
                        delta = getattr(event.data, "delta_content", "") or ""
                        if delta:
                            full_response += delta
                            self.chunk.emit(delta)
                    
                    elif event_type == EventType.ASSISTANT_MESSAGE:
                        content = getattr(event.data, "content", "") or ""
                        if content:
                            full_response = content
                    
                    elif event_type == EventType.ASSISTANT_REASONING:
                        reasoning = getattr(event.data, "reasoning_text", "") or ""
                        if reasoning:
                            self.thinking.emit(reasoning)
                    
                    elif event_type == EventType.ASSISTANT_REASONING_DELTA:
                        reasoning_delta = getattr(event.data, "reasoning_text", "") or ""
                        if reasoning_delta:
                            self.thinking.emit(reasoning_delta)

                    elif event_type in (EventType.ASSISTANT_USAGE, EventType.SESSION_USAGE_INFO):
                        snapshot = usage_snapshot_from_event(event.data, self._available_models, self._model)
                        if snapshot.get("available"):
                            self.usage_ready.emit(snapshot)
                    
                    elif event_type == EventType.TOOL_EXECUTION_START:
                        tool_name = getattr(event.data, "tool_name", "") or ""
                        arguments = getattr(event.data, "arguments", {}) or {}
                        tool_call_id = getattr(event.data, "tool_call_id", "") or ""
                        if tool_name and tool_name in our_tool_names:
                            self.tool_call.emit(tool_name, arguments, tool_call_id)
                    
                    elif event_type == EventType.TOOL_EXECUTION_COMPLETE:
                        tool_name = getattr(event.data, "tool_name", "") or ""
                        tool_call_id = getattr(event.data, "tool_call_id", "") or ""
                        result = getattr(event.data, "result", None)
                        result_text = str(result) if result else ""
                        if tool_name and tool_name in our_tool_names:
                            self.tool_result.emit(tool_name, result_text, tool_call_id)
                    
                    elif event_type == EventType.SESSION_ERROR:
                        session_error = _session_error_text(getattr(event, "data", None))
                        logger.error("[CHAT] Session error: %s", session_error)
                        break
                
                # Brief sleep to avoid busy loop
                await asyncio.sleep(0.05)
            
            # Process remaining events
            while events:
                event = events.pop(0)
                if event.type == EventType.ASSISTANT_MESSAGE_DELTA:
                    delta = getattr(event.data, "delta_content", "") or ""
                    if delta:
                        full_response += delta
                        self.chunk.emit(delta)
                elif event.type == EventType.ASSISTANT_REASONING_DELTA:
                    reasoning_delta = getattr(event.data, "reasoning_text", "") or ""
                    if reasoning_delta:
                        self.thinking.emit(reasoning_delta)
                elif event.type == EventType.TOOL_EXECUTION_COMPLETE:
                    tool_name = getattr(event.data, "tool_name", "") or ""
                    tool_call_id = getattr(event.data, "tool_call_id", "") or ""
                    result = getattr(event.data, "result", None)
                    result_text = str(result) if result else ""
                    if tool_name and tool_name in our_tool_names:
                        self.tool_result.emit(tool_name, result_text, tool_call_id)
                elif event.type == EventType.SESSION_ERROR:
                    session_error = _session_error_text(getattr(event, "data", None))
                    logger.error("[CHAT] Session error (drain): %s", session_error)
                elif event.type in (EventType.ASSISTANT_USAGE, EventType.SESSION_USAGE_INFO):
                    snapshot = usage_snapshot_from_event(event.data, self._available_models, self._model)
                    if snapshot.get("available"):
                        self.usage_ready.emit(snapshot)

            if session_error:
                error_msg = session_error
                if "403" in error_msg or "unauthorized" in error_msg.lower():
                    self.error.emit(
                        "Your Copilot license does not include Chat API access. "
                        "This is common with some enterprise licenses. "
                        "Please contact your organization admin to enable Copilot Chat."
                    )
                else:
                    self.error.emit(error_msg)
                return
            
            self.usage_ready.emit(await self._async_usage_snapshot())
            logger.info(f"Chat complete, response length: {len(full_response)} chars")
            if not full_response:
                logger.warning("Empty response from Copilot - enterprise account may not have chat access")
            self.complete.emit(full_response)
            
        except Exception as e:
            logger.exception("Error during chat")
            self.error.emit(str(e))
        finally:
            unsubscribe()

    async def _async_create_session(self):
        """Create a new session with current configuration (async)."""
        our_tool_names = {t.name for t in self._sdk_tools} if self._sdk_tools else set()
        if self._sdk_tools:
            logger.info(
                "Creating session with %d tools: %s",
                len(self._sdk_tools),
                list(our_tool_names),
            )

        applied_effort = self._reasoning_effort
        supported_efforts = model_supported_reasoning_efforts(self._available_models, self._model)
        reasoning_effort = None
        if applied_effort != "auto" and applied_effort in supported_efforts:
            reasoning_effort = applied_effort
        elif applied_effort != "auto":
            logger.info(
                "Reasoning effort %s is not supported by model %s",
                applied_effort,
                self._model,
            )

        self._session = await _sdk_create_session(
            self._sdk_client,
            model=self._model,
            streaming=True,
            tools=self._sdk_tools or None,
            system_message=self._system_message,
            reasoning_effort=reasoning_effort,
            disabled_skills=_DEFAULT_DISABLED_SKILLS,
            our_tool_names=our_tool_names,
        )

    def _build_session_signature(self):
        """Return a stable signature for SDK session configuration."""
        tool_names = tuple(t.name for t in self._sdk_tools) if self._sdk_tools else ()
        return (self._model, self._system_message, self._reasoning_effort, tool_names)

    def _build_sdk_tools(self, SDKTool) -> List[Any]:
        """Build SDK Tool objects from MCP tool definitions."""
        if not self._tool_executor:
            logger.warning("No tool executor available - no tools will be registered")
            return []

        try:
            from copilot.tools import ToolInvocation, ToolResult
        except ImportError:
            ToolInvocation = None
            ToolResult = None

        registry = self._tool_executor._registry
        sdk_tools = []

        for tool_schema in registry.list_tools():
            tool_name = tool_schema.get("name", "")
            tool_desc = tool_schema.get("description", "")
            input_schema = tool_schema.get("inputSchema", {})

            # Build proper JSON schema for SDK (honor optional parameters)
            raw_properties = input_schema.get("properties", {})
            properties = {}
            required = []
            for name, props in raw_properties.items():
                clean = {k: v for k, v in props.items() if k != "optional"}
                properties[name] = clean
                if not props.get("optional", False):
                    required.append(name)
            tool_params = {
                "type": "object",
                "properties": properties,
                "required": required,
            }

            def make_handler(name):
                async def handler(invocation):
                    if ToolInvocation is not None and isinstance(invocation, ToolInvocation):
                        arguments = invocation.arguments or {}
                    elif isinstance(invocation, dict):
                        arguments = invocation.get("arguments", {})
                    elif hasattr(invocation, "arguments"):
                        arguments = invocation.arguments or {}
                    else:
                        arguments = {}

                    logger.info("SDK calling tool: %s with %s", name, _safe_log_preview(arguments, 120))
                    result = self._tool_executor.execute(name, arguments)
                    logger.info("SDK tool result for %s: %s", name, _safe_log_preview(result, 200))

                    if ToolResult is not None:
                        return ToolResult(
                            text_result_for_llm=result,
                            result_type="success",
                            session_log=f"Executed {name}",
                        )
                    return {
                        "textResultForLlm": result,
                        "resultType": "success",
                        "sessionLog": f"Executed {name}",
                    }

                return handler

            sdk_tool = SDKTool(
                name=tool_name,
                description=tool_desc,
                handler=make_handler(tool_name),
                parameters=tool_params,
            )
            sdk_tools.append(sdk_tool)
            logger.info(f"Registered SDK tool: {tool_name}")

        logger.info(f"Built {len(sdk_tools)} SDK tools: {[t.name for t in sdk_tools]}")
        return sdk_tools

    @pyqtSlot()
    def run_inline_completion(self):
        """Run inline completion request using existing SDK client.
        
        Does NOT emit finished to keep worker alive for subsequent requests.
        """
        import time
        start = time.time()
        logger.info("[COPILOT-WORKER] Starting inline completion request...")
        try:
            self._cancelled = False
            self._do_inline_completion()
            elapsed = time.time() - start
            logger.info(f"[COPILOT-WORKER] Inline completion finished in {elapsed:.2f}s")
        except Exception as e:
            elapsed = time.time() - start
            logger.warning(f"[COPILOT-WORKER] Inline completion error after {elapsed:.2f}s: {e}")
            self.inline_complete.emit("")
        # Note: Do NOT emit finished - worker stays alive for more requests

    @pyqtSlot()
    def _init_sdk_session(self):
        """Initialize SDK client and session for faster first completion.
        
        Called in background after authentication to pre-warm the session.
        """
        import asyncio

        if self._cancelled:
            return
        
        try:
            if not self._loop or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
            
            self._loop.run_until_complete(self._async_init_session())
        except Exception as e:
            logger.warning(f"SDK session pre-init error: {e}")

    async def _async_init_session(self):
        """Async session initialization without completion."""
        if self._cancelled:
            return

        SDKClient, _, EventType, import_err = _try_import_sdk()
        if SDKClient is None:
            return
        
        # Initialize client
        if not self._sdk_client:
            if self._cancelled:
                return
            self._sdk_client = SDKClient(_get_sdk_options())
            await self._sdk_client.start()
            logger.info("Copilot SDK client started (pre-init)")
        
        # Create session
        if not self._session:
            if self._cancelled:
                return
            self._session = await _sdk_create_session(
                self._sdk_client,
                model="gpt-4o-mini",
                streaming=True,
                system_message=self._system_message,
            )
            logger.info("Copilot completion session created (pre-init)")

    def _do_inline_completion(self):
        """Internal inline completion implementation."""
        import asyncio
        
        # Use persistent loop if available
        if not self._loop or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        
        self._loop.run_until_complete(self._async_inline_completion())

    async def _async_inline_completion(self):
        """Async inline completion - simpler than full chat."""
        import asyncio
        
        SDKClient, _, EventType, import_err = _try_import_sdk()
        if SDKClient is None:
            logger.warning("[COPILOT-WORKER] SDK import failed, emitting empty")
            self.inline_complete.emit("")
            return
        
        # Initialize client if needed
        if not self._sdk_client:
            logger.info("[COPILOT-WORKER] Creating new SDK client...")
            self._sdk_client = SDKClient(_get_sdk_options())
            await self._sdk_client.start()
            logger.info("[COPILOT-WORKER] SDK client started")
        
        # Create session without tools for faster response
        if not self._session:
            logger.info("[COPILOT-WORKER] Creating new session (gpt-4o-mini)...")
            self._session = await _sdk_create_session(
                self._sdk_client,
                model="gpt-4o-mini",
                streaming=True,
                system_message=self._system_message,
            )
            logger.info("[COPILOT-WORKER] Session created successfully")
        
        if not self._inline_prompt:
            logger.info("[COPILOT-WORKER] No inline prompt set, emitting empty")
            self.inline_complete.emit("")
            return
        
        logger.info(
            f"[COPILOT-WORKER] Sending prompt ({len(self._inline_prompt)} chars): "
            f"{self._inline_prompt[:100]}..."
        )
        
        # Collect response
        full_response = ""
        idle_event = asyncio.Event()
        events = []
        
        def on_event(event):
            events.append(event)
            if event.type == EventType.SESSION_IDLE:
                logger.info("[COPILOT-WORKER] Session became idle")
                idle_event.set()
            elif event.type == EventType.SESSION_ERROR:
                logger.warning(f"[COPILOT-WORKER] Session error: {event}")
                idle_event.set()
        
        unsubscribe = self._session.on(on_event)
        
        try:
            await self._session.send(self._inline_prompt)
            logger.info("[COPILOT-WORKER] Prompt sent, waiting for response...")
            
            # Short timeout for fast completions (3 seconds)
            start_time = time.time()
            timeout = 3
            
            while not idle_event.is_set() and not self._cancelled:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    logger.warning(
                        f"[COPILOT-WORKER] Timeout after {elapsed:.1f}s, "
                        f"response so far: {len(full_response)} chars"
                    )
                    break
                
                while events:
                    event = events.pop(0)
                    if event.type == EventType.ASSISTANT_MESSAGE_DELTA:
                        delta = getattr(event.data, "delta_content", "") or ""
                        if delta:
                            full_response += delta
                    elif event.type == EventType.ASSISTANT_MESSAGE:
                        content = getattr(event.data, "content", "") or ""
                        if content:
                            full_response = content
                
                await asyncio.sleep(0.02)
            
            logger.info(
                f"[COPILOT-WORKER] Response collected: {len(full_response)} chars"
            )
            self.inline_complete.emit(full_response)
        finally:
            unsubscribe()

    def run_cleanup(self):
        """Clean up SDK resources."""
        import asyncio
        
        # Create a single event loop for this method
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            if self._session:
                try:
                    loop.run_until_complete(self._session.destroy())
                except Exception:
                    pass
                self._session = None
            
            if self._sdk_client:
                try:
                    loop.run_until_complete(self._sdk_client.stop())
                except Exception:
                    pass
                self._sdk_client = None
        except Exception:
            logger.exception("Error during cleanup")
        finally:
            try:
                loop.close()
            except Exception:
                pass
            self.finished.emit()


class CopilotClient(QObject):
    """
    Client for GitHub Copilot integration using the official SDK.

    Maintains a persistent session to preserve conversation context.
    Tools execute on the main thread for Qt widget safety.

    Signals:
        auth_required(str, str): user_code, verification_uri
        authenticated(str): username/status
        auth_failed(str): error message
        chat_response_chunk(str): streaming text chunk
        chat_response_complete(str): full response
        chat_error(str): error message
        tool_called(str, dict, str): tool_name, arguments, tool_call_id
        tool_result(str, str): tool_name, result
        thinking(str): reasoning/thinking text
        models_changed(list): updated model list
        inline_completion_ready(str): inline code completion text
    """

    auth_required = pyqtSignal(str, str)
    authenticated = pyqtSignal(str)
    auth_failed = pyqtSignal(str)
    auth_started = pyqtSignal(str)  # Login process started with info message
    chat_response_chunk = pyqtSignal(str)
    chat_response_complete = pyqtSignal(str)
    chat_error = pyqtSignal(str)
    tool_called = pyqtSignal(str, dict, str)
    tool_result = pyqtSignal(str, str, str)
    thinking = pyqtSignal(str)
    models_changed = pyqtSignal(list)
    usage_changed = pyqtSignal(dict)
    inline_completion_ready = pyqtSignal(str)  # Inline completion result
    gh_not_found = pyqtSignal()  # GitHub CLI not installed
    license_warning = pyqtSignal(str)  # License may not support chat

    def __init__(self, parent=None, tool_registry: "MCPToolRegistry" = None):
        super().__init__(parent)
        settings = get_copilot_settings()
        self._model = settings.chat_selected_model
        self._reasoning_effort = settings.chat_reasoning_effort
        self._system_message = ""
        self._is_authenticated = False
        self._username = None  # GitHub username
        self._available_models = [dict(model) for model in DEFAULT_MODELS]
        self._usage_snapshot = usage_snapshot_for_model(self._available_models, self._model)
        
        # Thread management - persistent session worker
        self._session_thread: Optional[QThread] = None
        self._session_worker: Optional[CopilotWorker] = None
        
        # Temporary workers for auth operations
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[CopilotWorker] = None
        
        # Inline completion worker (managed separately)
        self._completion_thread: Optional[QThread] = None
        self._completion_worker: Optional[CopilotWorker] = None
        
        # LSP client for fast completions (optional)
        self._lsp_client = None
        
        # Tool execution - lives on main thread
        self._tool_executor: Optional[ThreadSafeToolExecutor] = None
        if tool_registry:
            from PyQt6.QtWidgets import QApplication
            self._tool_executor = ThreadSafeToolExecutor(
                tool_registry,
                parent=QApplication.instance(),
            )

    def set_tool_registry(self, registry: "MCPToolRegistry", parent: QObject = None) -> None:
        """Set or update the MCP tool registry."""
        from PyQt6.QtWidgets import QApplication
        if parent is None:
            parent = QApplication.instance()
        self._tool_executor = ThreadSafeToolExecutor(registry, parent=parent)

    @property
    def is_authenticated(self) -> bool:
        return self._is_authenticated

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str):
        self._model = value or "gpt-4o"
        get_copilot_settings().set_chat_selected_model(self._model)
        self._usage_snapshot = usage_snapshot_for_model(self._available_models, self._model)
        self.usage_changed.emit(self._usage_snapshot)

    @property
    def reasoning_effort(self) -> str:
        return self._reasoning_effort

    @reasoning_effort.setter
    def reasoning_effort(self, value: str):
        self._reasoning_effort = normalize_reasoning_effort(value)
        get_copilot_settings().set_chat_reasoning_effort(self._reasoning_effort)

    def model_supports_reasoning_effort(self, model_id: str = "") -> bool:
        """Return whether a model can use the reasoning effort selector."""
        return model_supports_reasoning_effort(self._available_models, model_id or self._model)

    @property
    def system_message(self) -> str:
        return self._system_message

    @system_message.setter
    def system_message(self, value: str):
        self._system_message = value

    def available_models(self) -> List[Dict[str, str]]:
        """Return list of available models (updated from SDK)."""
        return self._available_models

    def usage_snapshot(self) -> Dict[str, Any]:
        """Return the best available usage snapshot."""
        return dict(self._usage_snapshot)

    def refresh_metadata(self) -> None:
        """Refresh Copilot model and quota metadata from the SDK server."""
        if self._session_worker and self._session_thread and self._session_thread.isRunning():
            QMetaObject.invokeMethod(
                self._session_worker,
                "run_refresh_metadata",
                Qt.ConnectionType.QueuedConnection,
            )
            return
        self.start_auth()
    
    @property
    def lsp_client(self):
        """Get the LSP client for fast completions (or None if not set up)."""
        return self._lsp_client
    
    def set_lsp_client(self, client) -> None:
        """Set the LSP client for fast inline completions."""
        self._lsp_client = client
    
    def setup_lsp_client(self, server_path: str) -> bool:
        """
        Set up the LSP client for fast completions.
        
        Args:
            server_path: Path to the copilot-language-server executable
            
        Returns:
            True if setup started successfully
        """
        from src.services.copilot.copilot_lsp_client import CopilotLSPClient
        
        # Clean up existing client
        if self._lsp_client:
            try:
                self._lsp_client.stop()
            except Exception:
                pass
        
        self._lsp_client = CopilotLSPClient(server_path, self)
        
        # Connect LSP signals
        self._lsp_client.auth_required.connect(self.auth_required.emit)
        self._lsp_client.authenticated.connect(self._on_lsp_authenticated)
        self._lsp_client.status_changed.connect(self._on_lsp_status_changed)
        
        # Start the server
        if self._lsp_client.start():
            # Initialize with workspace
            self._lsp_client.initialize()
            return True
        
        self._lsp_client = None
        return False
    
    def _on_lsp_authenticated(self, username: str):
        """Handle LSP authentication success."""
        logger.info(f"[COPILOT] LSP authenticated: {username}")
        # LSP auth is independent, just log it
    
    def _on_lsp_status_changed(self, status: str):
        """Handle LSP status changes."""
        logger.info(f"[COPILOT] LSP status: {status}")

    def start_auth(self) -> None:
        """Start authentication check with SDK. Creates persistent session worker."""
        self._cleanup_worker()
        self._cleanup_session_worker()
        
        # Create persistent session worker
        self._session_worker = CopilotWorker(self._tool_executor)
        self._session_worker.set_model(self._model)
        self._session_worker.set_reasoning_effort(self._reasoning_effort)
        self._session_worker.set_available_models(self._available_models)
        self._session_thread = QThread()
        self._session_worker.moveToThread(self._session_thread)
        
        # Connect signals
        self._session_thread.started.connect(self._session_worker.run_init)
        self._session_worker.auth_ok.connect(self._on_auth_success)
        self._session_worker.auth_needed.connect(self._on_auth_needed)
        self._session_worker.models_ready.connect(self._on_models_loaded)
        self._session_worker.usage_ready.connect(self._on_usage_loaded)
        self._session_worker.error.connect(self._on_init_error)
        self._session_worker.ready.connect(self._on_session_ready)
        self._session_worker.license_warning.connect(self.license_warning.emit)
        # Note: Do NOT connect finished to cleanup - worker stays alive
        
        self._session_thread.start()

    def send_chat(
        self,
        messages: List[Dict[str, str]],
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Send a chat message to Copilot using persistent session.
        
        Args:
            messages: List of message dicts with "role" and "content" keys.
                      The last user message is used as the prompt.
            attachments: Optional image attachments for the current turn.
        """
        # Extract prompt from last user message and system rules from latest system message.
        system_messages = [m for m in messages if m.get("role") == "system"]
        if system_messages:
            self._system_message = system_messages[-1].get("content", "")

        user_messages = [m for m in messages if m.get("role") == "user"]
        if not user_messages:
            self.chat_error.emit("No user message to send")
            return
        
        prompt = user_messages[-1].get("content", "")
        if not prompt and not attachments:
            self.chat_error.emit("Empty message")
            return
        
        # Use persistent session worker if available
        if self._session_worker and self._session_thread and self._session_thread.isRunning():
            self._session_worker.set_model(self._model)
            self._session_worker.set_reasoning_effort(self._reasoning_effort)
            self._session_worker.set_available_models(self._available_models)
            self._session_worker.set_prompt(prompt)
            self._session_worker.set_system_message(self._system_message)
            self._session_worker.set_attachments(attachments)
            
            # Ensure signals are connected (only once)
            try:
                self._session_worker.chunk.disconnect()
                self._session_worker.complete.disconnect()
                self._session_worker.error.disconnect()
                self._session_worker.tool_call.disconnect()
                self._session_worker.tool_result.disconnect()
                self._session_worker.thinking.disconnect()
            except (TypeError, RuntimeError):
                pass  # Not connected yet
            
            self._session_worker.chunk.connect(self.chat_response_chunk.emit)
            self._session_worker.complete.connect(self.chat_response_complete.emit)
            self._session_worker.error.connect(self.chat_error.emit)
            self._session_worker.tool_call.connect(self.tool_called.emit)
            self._session_worker.tool_result.connect(self.tool_result.emit)
            self._session_worker.thinking.connect(self.thinking.emit)
            
            # Invoke run_chat on worker thread
            QMetaObject.invokeMethod(
                self._session_worker,
                "run_chat",
                Qt.ConnectionType.QueuedConnection,
            )
        else:
            # Fallback: create temporary worker (should not happen if auth succeeded)
            logger.warning("No session worker - creating temporary worker")
            self._cleanup_worker()
            
            self._worker = CopilotWorker(self._tool_executor)
            self._worker.set_model(self._model)
            self._worker.set_reasoning_effort(self._reasoning_effort)
            self._worker.set_available_models(self._available_models)
            self._worker.set_prompt(prompt)
            self._worker.set_system_message(self._system_message)
            self._worker.set_attachments(attachments)
            
            self._worker_thread = QThread()
            self._worker.moveToThread(self._worker_thread)
            
            # Connect signals
            self._worker_thread.started.connect(self._worker.run_chat)
            self._worker.chunk.connect(self.chat_response_chunk.emit)
            self._worker.complete.connect(self.chat_response_complete.emit)
            self._worker.error.connect(self.chat_error.emit)
            self._worker.tool_call.connect(self.tool_called.emit)
            self._worker.tool_result.connect(self.tool_result.emit)
            self._worker.thinking.connect(self.thinking.emit)
            self._worker.usage_ready.connect(self._on_usage_loaded)
            self._worker.auth_ok.connect(self._on_auth_success)
            self._worker.finished.connect(self._on_worker_finished)
            
            self._worker_thread.start()

    def cancel(self) -> None:
        """Cancel current operation."""
        if self._session_worker:
            self._session_worker.cancel()
        if self._worker:
            self._worker.cancel()

    def cancel_pending_auth(self) -> None:
        """Cancel an in-progress GitHub login/auth verification."""
        self._is_authenticated = False
        if self._session_worker:
            self._session_worker.cancel()
        self._cleanup_session_worker()
        self.auth_failed.emit("Authentication cancelled")

    def reset_chat_session(self) -> None:
        """Reset the persistent Copilot SDK session (new chat thread)."""
        if self._session_worker and self._session_thread and self._session_thread.isRunning():
            QMetaObject.invokeMethod(
                self._session_worker,
                "reset_chat_session",
                Qt.ConnectionType.QueuedConnection,
            )

    def request_inline_completion(
        self,
        prefix: str,
        suffix: str,
        language: str,
        request_id: int = 0,
        context: str = "",
    ) -> None:
        """
        Request inline code completion from Copilot.
        
        Uses a lightweight prompt to get code suggestions for ghost text.
        Result is emitted via inline_completion_ready signal.
        
        Args:
            prefix: Code before cursor
            suffix: Code after cursor
            language: Programming language (python, sql)
            request_id: Optional ID to track requests
            context: Additional context (e.g., database schema for SQL)
        """
        if not self._is_authenticated:
            logger.info("[COPILOT] Inline completion skipped: not authenticated")
            self.inline_completion_ready.emit("")
            return
        
        logger.info(
            f"[COPILOT] request_inline_completion: lang={language}, "
            f"prefix={len(prefix)} chars, suffix={len(suffix)} chars"
        )
        
        # Build completion prompt - keep it short for fast response
        prefix_truncated = prefix[-800:] if len(prefix) > 800 else prefix
        suffix_truncated = suffix[:200] if len(suffix) > 200 else suffix
        
        # Include context if provided (database schema for SQL, namespace for Python)
        context_section = ""
        if context:
            # Truncate context to avoid token limits
            context_truncated = context[:1500] if len(context) > 1500 else context
            if language == "sql":
                context_section = f"\n\nAvailable database schema:\n{context_truncated}\n"
            else:
                context_section = f"\n\nContext:\n{context_truncated}\n"
        
        prompt = f"""Complete this {language} code. Output ONLY the code to add at the cursor position. No explanations, no markdown, no code blocks - just the raw code.{context_section}
```{language}
{prefix_truncated}<CURSOR>{suffix_truncated}
```

Output ONLY the completion text (what should replace <CURSOR>):"""
        
        system_msg = (
            "You are a code completion assistant. Output ONLY the code completion, nothing else. "
            "No explanations, no markdown formatting, no code fences. Just raw code."
        )
        
        # Use persistent completion worker if available, else create new one
        if self._completion_worker and self._completion_thread and self._completion_thread.isRunning():
            # Reuse existing worker - just update prompt and trigger
            self._completion_worker.set_inline_prompt(prompt)
            self._completion_worker.set_system_message(system_msg)
            # Invoke run_inline_completion via Qt event loop (thread-safe)
            QMetaObject.invokeMethod(
                self._completion_worker,
                "run_inline_completion",
                Qt.ConnectionType.QueuedConnection,
            )
        else:
            # Create new persistent completion worker
            self._cleanup_completion_worker()
            
            self._completion_worker = CopilotWorker(None)  # No tool executor
            self._completion_worker.set_model("gpt-4o-mini")  # Use faster model
            self._completion_worker.set_inline_prompt(prompt)
            self._completion_worker.set_system_message(system_msg)
            
            self._completion_thread = QThread()
            self._completion_worker.moveToThread(self._completion_thread)
            
            # Connect signals - worker stays alive (no finished->quit)
            self._completion_worker.inline_complete.connect(self._on_inline_completion_received)
            self._completion_worker.error.connect(self._on_completion_error)
            self._completion_thread.started.connect(self._completion_worker.run_inline_completion)
            
            self._completion_thread.start()
    
    def _on_inline_completion_received(self, response: str) -> None:
        """Handle inline completion response."""
        logger.info(
            f"[COPILOT] Raw inline response ({len(response)} chars): "
            f"{response[:100]}..."
        )
        cleaned = self._clean_completion_response(response)
        logger.info(
            f"[COPILOT] Cleaned response ({len(cleaned)} chars): "
            f"{cleaned[:80]}..."
        )
        self.inline_completion_ready.emit(cleaned)
    
    def _on_completion_received(self, response: str) -> None:
        """Handle completion response (legacy)."""
        cleaned = self._clean_completion_response(response)
        self.inline_completion_ready.emit(cleaned)
    
    def _on_completion_error(self, msg: str) -> None:
        """Handle completion error."""
        logger.warning(f"Inline completion error: {msg}")
        self.inline_completion_ready.emit("")
    
    def _on_completion_thread_finished(self) -> None:
        """Cleanup completion thread after it finishes."""
        # Only cleanup if these are still the active ones
        # (prevent double cleanup race condition)
        pass  # Cleanup is handled by _cleanup_completion_worker
    
    def _cleanup_completion_worker(self) -> None:
        """Cancel and cleanup completion worker."""
        worker = self._completion_worker
        thread = self._completion_thread
        
        # Clear references first to prevent recursion
        self._completion_worker = None
        self._completion_thread = None
        
        if worker:
            try:
                worker.cancel()
                # Disconnect signals to prevent callbacks
                worker.complete.disconnect()
                worker.inline_complete.disconnect()
                worker.error.disconnect()
                worker.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
        
        if thread:
            try:
                # Disconnect thread signals
                thread.started.disconnect()
                thread.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            
            if thread.isRunning():
                thread.quit()
                if not thread.wait(2000):  # Wait up to 2 seconds
                    logger.warning("Completion thread did not terminate, forcing...")
                    thread.terminate()
                    thread.wait(500)
            
            try:
                thread.deleteLater()
            except RuntimeError:
                pass
        
        if worker:
            try:
                worker.deleteLater()
            except RuntimeError:
                pass

    def _clean_completion_response(self, response: str) -> str:
        """Clean completion response from chat artifacts."""
        text = response.strip()
        
        # Remove markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            # Find end of code block
            end_idx = -1
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip() == "```":
                    end_idx = i
                    break
            if end_idx > 0:
                text = "\n".join(lines[1:end_idx])
        
        # Remove single backticks
        if text.startswith("`") and text.endswith("`") and text.count("`") == 2:
            text = text[1:-1]
        
        # Remove common prefixes like "Here's" or "The completion is:"
        prefixes = ["here's", "here is", "the completion", "completion:"]
        lower = text.lower()
        for prefix in prefixes:
            if lower.startswith(prefix):
                # Find the actual code after the prefix
                idx = text.find("\n")
                if idx > 0:
                    text = text[idx:].strip()
                break
        
        return text

    def _preinit_completion_session(self) -> None:
        """Pre-initialize completion worker and SDK session for faster first completion.
        
        This creates the worker thread and SDK session in background so that
        the first completion request doesn't have to wait for initialization.
        """
        if self._completion_worker or self._completion_thread:
            # Already initialized
            return
        
        logger.info("Pre-initializing completion session...")
        
        try:
            self._completion_worker = CopilotWorker(None)  # No tool executor
            self._completion_worker.set_model("gpt-4o-mini")  # Fast model
            self._completion_worker.set_system_message(
                "You are a code completion assistant. Output ONLY the code completion, nothing else."
            )
            # Empty prompt - session will be created but no completion sent
            self._completion_worker.set_inline_prompt("")
            
            self._completion_thread = QThread()
            self._completion_worker.moveToThread(self._completion_thread)
            
            # Connect signals
            self._completion_worker.inline_complete.connect(self._on_inline_completion_received)
            self._completion_worker.error.connect(self._on_completion_error)
            
            # Start thread but don't trigger completion (no started connection)
            self._completion_thread.start()
            
            # Trigger session initialization in background
            QMetaObject.invokeMethod(
                self._completion_worker,
                "_init_sdk_session",
                Qt.ConnectionType.QueuedConnection,
            )
            
            logger.info("Completion session pre-initialization started")
        except Exception as e:
            logger.warning(f"Failed to pre-init completion session: {e}")

    def sign_out(self) -> None:
        """Sign out - clears local state and runs gh auth logout."""
        self._is_authenticated = False
        self._username = None
        self._cleanup_worker()
        self._cleanup_session_worker()
        
        # Actually logout from GitHub CLI
        import subprocess
        import shutil
        try:
            gh_path = shutil.which("gh")
            if gh_path:
                # Run gh auth logout with --hostname to avoid prompts
                run_hidden(
                    [gh_path, "auth", "logout", "--hostname", "github.com"],
                    timeout=10,
                )
                logger.info("GitHub auth logout completed")
        except Exception as e:
            logger.warning(f"Failed to run gh auth logout: {e}")

    def _on_auth_success(self):
        self._is_authenticated = True
        # Try to get username from GitHub CLI
        username = self._get_github_username()
        self._username = username
        self.authenticated.emit(username or "Copilot")
        
        # Note: CopilotAuthService handles state persistence and lock release
        # via its signal handler (_on_chat_authenticated)
        
        # Pre-initialize completion worker/session for faster first completion
        self._preinit_completion_session()

    def _get_github_username(self) -> str:
        """Get GitHub username from gh CLI."""
        try:
            import subprocess
            import shutil
            gh_path = shutil.which("gh")
            if not gh_path:
                return ""
            result = run_hidden(
                [gh_path, "api", "user", "-q", ".login"],
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.debug(f"Could not get GitHub username: {e}")
        return ""

    def _on_auth_needed(self):
        """Auth not found - just update state, don't auto-login.
        
        User must click Sign In button to start login process.
        Emits auth_failed so CopilotAuthService can release the lock.
        """
        self._is_authenticated = False
        # Emit auth_failed to notify CopilotAuthService (which releases the lock)
        self.auth_failed.emit("Not authenticated - sign in required")

    def _on_auth_started(self, message: str):
        """Login process started."""
        self.auth_started.emit(message)

    def do_login(self) -> None:
        """Start automatic GitHub login process. Creates persistent session on success."""
        self._cleanup_worker()
        self._cleanup_session_worker()
        
        # Create as session worker - it will become persistent on success
        self._session_worker = CopilotWorker(self._tool_executor)
        self._session_worker.set_model(self._model)
        self._session_worker.set_reasoning_effort(self._reasoning_effort)
        self._session_worker.set_available_models(self._available_models)
        self._session_thread = QThread()
        self._session_worker.moveToThread(self._session_thread)
        
        # Connect signals
        self._session_thread.started.connect(self._session_worker.run_login)
        self._session_worker.auth_ok.connect(self._on_auth_success)
        self._session_worker.auth_started.connect(self._on_auth_started)
        self._session_worker.auth_required.connect(self.auth_required.emit)
        self._session_worker.models_ready.connect(self._on_models_loaded)
        self._session_worker.usage_ready.connect(self._on_usage_loaded)
        self._session_worker.error.connect(self._on_init_error)
        self._session_worker.gh_not_found.connect(self._on_gh_not_found)
        self._session_worker.ready.connect(self._on_session_ready)
        self._session_worker.license_warning.connect(self.license_warning.emit)
        # Note: Do NOT connect finished to cleanup - worker stays alive
        
        self._session_thread.start()

    def do_add_account_login(self) -> None:
        """Start GitHub login to add another account without logging everyone out."""
        self._cleanup_worker()
        self._cleanup_session_worker()

        self._session_worker = CopilotWorker(self._tool_executor)
        self._session_worker.set_model(self._model)
        self._session_worker.set_reasoning_effort(self._reasoning_effort)
        self._session_worker.set_available_models(self._available_models)
        self._session_thread = QThread()
        self._session_worker.moveToThread(self._session_thread)

        self._session_thread.started.connect(self._session_worker.run_add_account_login)
        self._session_worker.auth_ok.connect(self._on_auth_success)
        self._session_worker.auth_started.connect(self._on_auth_started)
        self._session_worker.auth_required.connect(self.auth_required.emit)
        self._session_worker.models_ready.connect(self._on_models_loaded)
        self._session_worker.usage_ready.connect(self._on_usage_loaded)
        self._session_worker.error.connect(self._on_init_error)
        self._session_worker.gh_not_found.connect(self._on_gh_not_found)
        self._session_worker.ready.connect(self._on_session_ready)
        self._session_worker.license_warning.connect(self.license_warning.emit)

        self._session_thread.start()

    def _on_models_loaded(self, models: list):
        logger.info(f"Models loaded: {len(models)} models")
        if models:
            self._available_models = normalize_models(models)
            if not find_model(self._available_models, self._model):
                self._model = self._available_models[0].get("id", self._model)
                get_copilot_settings().set_chat_selected_model(self._model)
            if self._session_worker:
                self._session_worker.set_model(self._model)
                self._session_worker.set_available_models(self._available_models)
            self._usage_snapshot = usage_snapshot_for_model(self._available_models, self._model)
            get_copilot_settings().set_chat_usage_snapshot(self._usage_snapshot)
            self.models_changed.emit(self._available_models)
            self.usage_changed.emit(self._usage_snapshot)
        else:
            # Keep default models for enterprise accounts that may not list models
            logger.warning("No models returned from SDK, keeping defaults")
            # Still emit to update UI
            self.models_changed.emit(self._available_models)
            self._usage_snapshot = usage_snapshot_for_model(self._available_models, self._model)
            self.usage_changed.emit(self._usage_snapshot)

    def _on_usage_loaded(self, snapshot: dict):
        """Handle account/session quota updates from the SDK worker."""
        if not isinstance(snapshot, dict):
            return
        self._usage_snapshot = snapshot
        get_copilot_settings().set_chat_usage_snapshot(self._usage_snapshot)
        self.usage_changed.emit(self._usage_snapshot)

    def _on_init_error(self, error: str):
        self._is_authenticated = False
        self.auth_failed.emit(error)
        # Note: CopilotAuthService handles lock release via auth_failed signal handler

    def _on_gh_not_found(self):
        """GitHub CLI not found - emit dedicated signal."""
        self._is_authenticated = False
        self.gh_not_found.emit()

    def _on_worker_finished(self):
        """Cleanup after worker finishes."""
        pass

    def _cleanup_worker(self):
        """Clean up current worker and thread."""
        if self._worker:
            try:
                self._worker.cancel()
            except RuntimeError:
                pass
        
        if self._worker_thread and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait(3000)
        
        if self._worker:
            try:
                self._worker.deleteLater()
            except RuntimeError:
                pass
            self._worker = None
        
        if self._worker_thread:
            try:
                self._worker_thread.deleteLater()
            except RuntimeError:
                pass
            self._worker_thread = None

    def _cleanup_session_worker(self):
        """Clean up persistent session worker and thread."""
        if self._session_worker:
            try:
                self._session_worker.cancel()
            except RuntimeError:
                pass
        
        if self._session_thread and self._session_thread.isRunning():
            self._session_thread.quit()
            self._session_thread.wait(3000)
        
        if self._session_worker:
            try:
                self._session_worker.deleteLater()
            except RuntimeError:
                pass
            self._session_worker = None
        
        if self._session_thread:
            try:
                self._session_thread.deleteLater()
            except RuntimeError:
                pass
            self._session_thread = None

    def _on_session_ready(self):
        """Session worker is ready to accept chat requests."""
        logger.info("Session worker ready for chat")

    def cleanup(self) -> None:
        """Clean up all resources."""
        if self._lsp_client:
            try:
                self._lsp_client.cleanup()
            except Exception:
                pass
            self._lsp_client = None
        self._cleanup_worker()
        self._cleanup_session_worker()
        self._cleanup_completion_worker()