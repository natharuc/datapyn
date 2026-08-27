"""Shared stdio ACP adapter — spawn, handshake, session, and listener dispatch."""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from typing import Any, Optional

from ..agent import (
    LIVE_TEST_COMMAND,
    ActionRequest,
    FixStep,
    GrantResult,
    IAcpAgent,
    IAcpAgentListener,
    ModelInfo,
    NullAcpAgentListener,
    QuestionRequest,
    ReasoningInfo,
)
from ..catalog import get_agent, prepend_bin_dirs_to_path, resolve_launch
from ..client import AcpClient
from ..installer import install_command, probe_agent, run_install
from ..permission import permission_summary
from ..protocol import client_version
from ..service import AcpSessionService
from ..session_config import NormalizedConfig, merge_config_snapshot, normalize_config

logger = logging.getLogger(__name__)

_AUTH_HINTS = (
    "auth",
    "login",
    "unauthor",
    "not authenticated",
    "sign in",
        "logged in",
        "forbidden",
    )

_COMPLETION_PROMPT = (
    "You are a code completion engine. Return ONLY the ghost-text to insert "
    "at the cursor. No markdown, no explanation, no tools.\n\n{body}"
)


def _looks_like_auth(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(token in text for token in _AUTH_HINTS)


def _selector_items(selector: dict[str, Any], cls):
    out = []
    for item in selector.get("values") or []:
        value = str(item.get("value") or "")
        if not value:
            continue
        out.append(
            cls(
                id=value,
                name=str(item.get("name") or value),
                description=str(item.get("description") or ""),
            )
        )
    return out


def _is_question_permission(params: dict[str, Any]) -> bool:
    if params.get("questions"):
        return True
    options = params.get("options") or []
    ids = [
        str(item.get("optionId") or item.get("id") or "")
        for item in options
        if isinstance(item, dict)
    ]
    if not ids:
        return False
    return not any(
        "allow" in oid.lower() or "reject" in oid.lower() or "deny" in oid.lower()
        for oid in ids
    )


def _node_step() -> FixStep:
    if os.name == "nt":
        return FixStep(
            "Install Node.js LTS (includes npm), then reopen the terminal",
            "winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements",
        )
    return FixStep(
        "Install Node.js LTS (includes npm) from https://nodejs.org",
        "",
    )


def _rerun_step() -> FixStep:
    return FixStep(
        "When you finish the steps above, re-run the live ACP tests",
        LIVE_TEST_COMMAND,
    )


class StdioAcpAgent(IAcpAgent):
    """ACP over stdio. Subclasses only set agent_id and capability flags."""

    _exposes_models = True
    _exposes_reasoning = False

    def __init__(
        self,
        agent_id: str,
        listener: Optional[IAcpAgentListener] = None,
        *,
        pool=None,
        cwd: Optional[str] = None,
        extra_args: Optional[list[str]] = None,
        mcp_servers: Optional[list[dict]] = None,
        launch: Optional[tuple[str, list[str]]] = None,
    ):
        self._agent_id = agent_id
        self._listener = listener or NullAcpAgentListener()
        self._pool = pool
        self._cwd = cwd or ""
        self._extra_args = list(extra_args or [])
        self._mcp_servers = list(mcp_servers or [])
        self._opened_mcp: list = []
        self._session_lock = threading.Lock()
        self._launch = launch
        self._client: Optional[AcpClient] = None
        self._owns_client = pool is None
        self._session_id = ""
        self._completion_session_id = ""
        self._config: Optional[NormalizedConfig] = None
        self._ready = False
        self._retained = False
        self._wired = False
        self._completion_chunks: list[str] = []
        self._acp = AcpSessionService()

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def completion_session_id(self) -> str:
        return self._completion_session_id

    @property
    def is_ready(self) -> bool:
        return self._ready and bool(self._session_id)

    @property
    def exposes_models(self) -> bool:
        return bool(self._exposes_models)

    @property
    def exposes_reasoning(self) -> bool:
        return bool(self._exposes_reasoning)

    @property
    def current_model(self) -> str:
        if not self._config:
            return ""
        return str(self._config.model.get("current") or "")

    @property
    def current_reasoning(self) -> str:
        if not self._config:
            return ""
        return str(self._config.reasoning.get("current") or "")

    @property
    def config_snapshot(self) -> dict[str, Any]:
        if self._config:
            return dict(self._config.raw)
        return {}

    def bind(
        self,
        *,
        cwd: Optional[str] = None,
        extra_args: Optional[list[str]] = None,
        mcp_servers: Optional[list[dict]] = None,
    ) -> None:
        if cwd is not None:
            self._cwd = cwd
        if extra_args is not None:
            self._extra_args = list(extra_args)
        if mcp_servers is not None:
            self._mcp_servers = list(mcp_servers)

    def grant_configuration(self, *, install: bool = True) -> GrantResult:
        prepend_bin_dirs_to_path()
        spec = get_agent(self._agent_id)
        if self._session_id and self._client and self._client.is_running:
            if list(self._mcp_servers or []) != list(self._opened_mcp or []):
                try:
                    self._open_live_session()
                except Exception as exc:
                    logger.warning("ACP MCP rebind failed for %s: %s", self._agent_id, exc)
            self._apply_saved_prefs()
            return self._ready_result()

        if self._launch is None:
            probe = probe_agent(self._agent_id)
            if probe.status == "missing_runtime":
                return GrantResult(
                    ok=False,
                    agent_id=self._agent_id,
                    status="missing_runtime",
                    detail=probe.detail or "Node.js (node + npm) is required.",
                    steps=[_node_step(), _rerun_step()],
                )
            if probe.status == "not_installed":
                cmd = install_command(spec) if spec else probe.detail
                if install and spec is not None:
                    code, out = run_install(spec)
                    if code != 0:
                        return GrantResult(
                            ok=False,
                            agent_id=self._agent_id,
                            status="not_installed",
                            detail=out or f"Install failed for {self._agent_id}",
                            steps=[
                                FixStep("Install the agent CLI", cmd or ""),
                                _rerun_step(),
                            ],
                        )
                    probe = probe_agent(self._agent_id)
                    if probe.status != "ready":
                        return GrantResult(
                            ok=False,
                            agent_id=self._agent_id,
                            status=probe.status,
                            detail=probe.detail or "CLI still not on PATH after install.",
                            steps=[
                                FixStep("Install the agent CLI", cmd or ""),
                                _rerun_step(),
                            ],
                        )
                else:
                    return GrantResult(
                        ok=False,
                        agent_id=self._agent_id,
                        status="not_installed",
                        detail=probe.detail or f"{self._agent_id} is not installed",
                        steps=[
                            FixStep("Install the agent CLI", cmd or ""),
                            _rerun_step(),
                        ],
                    )

        try:
            self._open_live_session()
        except Exception as exc:
            logger.warning("ACP grant failed for %s: %s", self._agent_id, exc)
            login = ""
            if spec and spec.install.login_command:
                login = " ".join(spec.install.login_command)
            if _looks_like_auth(exc):
                steps = []
                if login:
                    steps.append(FixStep("Authenticate the CLI (browser login)", login))
                steps.append(_rerun_step())
                return GrantResult(
                    ok=False,
                    agent_id=self._agent_id,
                    status="not_authenticated",
                    detail=str(exc),
                    steps=steps,
                )
            cmd = install_command(spec) if spec else ""
            return GrantResult(
                ok=False,
                agent_id=self._agent_id,
                status="not_installed",
                detail=str(exc),
                steps=[
                    FixStep("Check the CLI is on PATH and try installing again", cmd),
                    _rerun_step(),
                ],
            )

        self._apply_saved_prefs()
        self._ready = True
        return self._ready_result()

    def send_message(
        self,
        text: str = "",
        attachments: Optional[list] = None,
        *,
        blocks: Optional[list[dict[str, Any]]] = None,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        if not self._session_id or not self._client:
            raise RuntimeError("Call grant_configuration first")
        if blocks is not None:
            payload: list[dict[str, Any]] | str = blocks
        else:
            payload = text
            if attachments:
                from ..turn_context import format_acp_prompt_parts

                payload = format_acp_prompt_parts(text, {}, attachments=attachments)
        return self._acp.prompt(self._client, self._session_id, payload, timeout=timeout)

    def list_models(self) -> list[ModelInfo]:
        if not self._config:
            return []
        return _selector_items(self._config.model, ModelInfo)

    def list_reasoning(self) -> list[ReasoningInfo]:
        if not self._config:
            return []
        return _selector_items(self._config.reasoning, ReasoningInfo)

    def composer_config(self) -> dict[str, Any]:
        if not self._config:
            from ..session_config import composer_selectors

            return composer_selectors({}, loading=not self._ready)
        return self._config.to_selectors()

    def cancel(self) -> None:
        if self._client and self._session_id:
            try:
                self._acp.cancel(self._client, self._session_id)
            except Exception:
                pass

    def close(self) -> None:
        self._unwire()
        if self._client:
            for sid in (self._session_id, self._completion_session_id):
                if sid:
                    try:
                        self._client.session_close(sid)
                    except Exception:
                        pass
        self._session_id = ""
        self._completion_session_id = ""
        self._ready = False
        self._config = None
        if self._pool is not None and self._retained:
            try:
                self._pool.release_session(self._agent_id)
            except Exception:
                pass
            self._retained = False
        elif self._owns_client and self._client is not None:
            try:
                self._client.stop()
            except Exception:
                pass
        self._client = None

    def answer_action(self, rpc_id: object, option_id: str) -> None:
        self._respond_permission(rpc_id, option_id)

    def answer_questions(self, rpc_id: object, answers: Any) -> None:
        if isinstance(answers, str):
            self._respond_permission(rpc_id, answers)
            return
        if isinstance(answers, dict) and answers.get("optionId"):
            self._respond_permission(rpc_id, str(answers.get("optionId")))
            return
        if isinstance(answers, list) and answers:
            first = answers[0]
            option = first.get("optionId") if isinstance(first, dict) else first
            self._respond_permission(rpc_id, str(option))
            return
        self._respond_permission(rpc_id, "reject-once")

    def complete(self, body: str, timeout: float = 4.0) -> str:
        if not self._client or not self._client.is_running:
            grant = self.grant_configuration(install=False)
            if not grant.ok or not self._client:
                return ""
        cwd = self._cwd or tempfile.gettempdir()
        session_id = self._completion_session_id
        if not session_id:
            session_id, _cfg = self._acp.open_session(self._client, cwd, mcp_servers=[])
            self._completion_session_id = session_id
        self._completion_chunks = []
        prompt = _COMPLETION_PROMPT.format(body=body)
        try:
            result = self._acp.prompt(self._client, session_id, prompt, timeout=timeout)
        except Exception:
            return ""
        text = "".join(self._completion_chunks).strip()
        if not text and isinstance(result, dict):
            text = str(result.get("text") or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return text

    def _apply_model(self, model_id: str) -> None:
        self._push_option("model", model_id)

    def _apply_reasoning(self, level: str) -> None:
        self._push_option("reasoning", level)

    def _ready_result(self) -> GrantResult:
        return GrantResult(
            ok=True,
            agent_id=self._agent_id,
            status="ready",
            detail="ACP session ready",
            models=self.list_models(),
            reasoning=self.list_reasoning(),
        )

    def _open_live_session(self) -> None:
        with self._session_lock:
            self._open_live_session_locked()

    def _open_live_session_locked(self) -> None:
        wanted_mcp = list(self._mcp_servers or [])
        already = bool(self._session_id and self._client and self._client.is_running)
        if already and wanted_mcp == list(self._opened_mcp or []):
            return
        if already and self._session_id and self._client:
            try:
                self._client.session_close(self._session_id)
            except Exception:
                pass
            self._session_id = ""
        spec = get_agent(self._agent_id)
        cwd = self._cwd or tempfile.gettempdir()
        extra = list(self._extra_args)
        if self._pool is not None:
            client = self._pool.acquire(
                self._agent_id, cwd=cwd, extra_args=extra or None
            )
            self._client = client
        else:
            launch = self._launch
            if launch is None:
                if spec is None:
                    raise RuntimeError(f"Unknown agent: {self._agent_id}")
                resolved = resolve_launch(spec)
                if resolved is None:
                    raise RuntimeError(f"Agent {self._agent_id} is not installed")
                launch = resolved
            command, args = launch
            args = list(args) + extra
            if self._client is None:
                self._client = AcpClient(self._agent_id)
            self._client.start(command, args, cwd=cwd)
            self._acp.handshake(
                self._client,
                auth_method_id=spec.auth_method_id if spec else None,
                version=client_version(),
            )
        self._wire()
        previous = self._config.raw if self._config else None
        session_id, cfg = self._acp.open_session(
            self._client, cwd, self._mcp_servers, previous=previous
        )
        self._session_id = session_id
        self._config = cfg
        self._opened_mcp = wanted_mcp
        if self._pool is not None and not self._retained:
            self._pool.retain(self._agent_id)
            self._retained = True
        try:
            self._listener.on_config_changed()
        except Exception:
            logger.debug("on_config_changed failed", exc_info=True)

    def _apply_saved_prefs(self) -> None:
        if not self._session_id or not self._client or not self._config:
            return
        from src.services.pynia.settings import get_pynia_settings

        settings = get_pynia_settings()
        cfg = normalize_config(
            self._config.raw,
            model_id=settings.agent_model_id(self._agent_id),
            thought_level=settings.agent_thought_level(self._agent_id),
        )
        self._config = cfg
        pref_model = settings.agent_model_id(self._agent_id)
        model_ids = {item["value"] for item in cfg.model.get("values") or []}
        if pref_model and pref_model in model_ids and not cfg.model.get("hidden"):
            self._push_option("model", pref_model)
        pref_thought = settings.agent_thought_level(self._agent_id)
        thought_ids = {item["value"] for item in cfg.reasoning.get("values") or []}
        if pref_thought and pref_thought in thought_ids and not cfg.reasoning.get("hidden"):
            self._push_option("reasoning", pref_thought)

    def _push_option(self, kind: str, value: str) -> None:
        if not self._client or not self._session_id or not self._config:
            return
        selector = self._config.model if kind == "model" else self._config.reasoning
        config_id = str(selector.get("id") or kind)
        if selector.get("hidden"):
            return
        cfg = self._acp.set_option(
            self._client,
            self._session_id,
            config_id,
            value,
            previous=self._config.raw,
            kind=kind,
        )
        self._config = cfg
        try:
            self._listener.on_config_changed()
        except Exception:
            logger.debug("on_config_changed failed", exc_info=True)

    def _respond_permission(self, rpc_id: object, option_id: str) -> None:
        if not self._client:
            return
        self._client.respond(
            rpc_id,
            {"outcome": {"outcome": "selected", "optionId": option_id}},
        )

    def _wire(self) -> None:
        if self._wired or self._client is None:
            return
        from PyQt6.QtCore import Qt

        self._client.session_update.connect(
            self._on_session_update, Qt.ConnectionType.DirectConnection
        )
        self._client.permission_request.connect(
            self._on_permission, Qt.ConnectionType.DirectConnection
        )
        self._wired = True

    def _unwire(self) -> None:
        if not self._wired or self._client is None:
            self._wired = False
            return
        try:
            self._client.session_update.disconnect(self._on_session_update)
        except TypeError:
            pass
        try:
            self._client.permission_request.disconnect(self._on_permission)
        except TypeError:
            pass
        self._wired = False

    def _on_session_update(self, acp_session_id: str, update: dict) -> None:
        if acp_session_id == self._completion_session_id:
            if update.get("sessionUpdate") == "agent_message_chunk":
                content = update.get("content") or {}
                self._completion_chunks.append(content.get("text") or "")
            if update.get("sessionUpdate") == "tool_call" and self._client:
                try:
                    self._acp.cancel(self._client, self._completion_session_id)
                except Exception:
                    pass
            return
        if acp_session_id != self._session_id:
            return
        kind = update.get("sessionUpdate") or ""
        if kind in {"agent_message_chunk", "agent_thought_chunk"}:
            content = update.get("content") or {}
            text = content.get("text") or ""
            if not text:
                return
            if kind == "agent_thought_chunk":
                self._listener.on_thinking(text)
                return
            self._listener.on_receive_message(text)
            return
        if kind in {"tool_call", "tool_call_update"}:
            self._listener.on_tool_event(update)
            return
        if kind == "config_option_update":
            incoming: dict[str, Any] = {}
            if update.get("configOptions") is not None:
                incoming["configOptions"] = update.get("configOptions")
            if update.get("models") is not None:
                incoming["models"] = update.get("models")
            if not incoming:
                return
            previous = self._config.raw if self._config else {}
            merged = merge_config_snapshot(previous, incoming)
            if self._client:
                self._client.last_session_info = merge_config_snapshot(
                    self._client.last_session_info, incoming
                )
            self._config = normalize_config(merged)
            self._listener.on_config_changed()

    def _on_permission(self, rpc_id: object, params: dict) -> None:
        session_id = str((params or {}).get("sessionId") or "")
        if session_id and session_id != self._session_id:
            return
        payload = params or {}
        if _is_question_permission(payload):
            options = payload.get("options") or []
            self._listener.on_questions(
                QuestionRequest(
                    rpc_id=rpc_id,
                    session_id=session_id,
                    prompt=str(payload.get("title") or payload.get("message") or ""),
                    options=[item for item in options if isinstance(item, dict)],
                    params=payload,
                )
            )
            return
        self._listener.on_action(
            ActionRequest(
                rpc_id=rpc_id,
                session_id=session_id,
                params=payload,
                summary=permission_summary(payload),
            )
        )
