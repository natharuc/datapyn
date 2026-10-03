"""Per-tab Pynia ACP conversations with streaming, MCP and durable history."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import subprocess
import threading
import uuid

from src.services.pynia.acp.attachments import attachments_from_paths, display_attachments, normalize_attachments
from src.services.pynia.acp.binding import TabChatState
from src.services.pynia.acp.activity import format_activity_tool, merge_activity_tool
from src.services.pynia.acp.catalog import get_agent, list_agents, probe_status, resolve_launch, which_command, popen_argv
from src.services.pynia.acp.client_transport import AcpTransport
from src.services.pynia.acp.permission import allow_option_id, permission_should_ask, permission_should_reject, reject_option_id
from src.services.pynia.acp.service import AcpSessionService
from src.services.pynia.acp.session_config import composer_selectors, merge_config_snapshot
from src.services.pynia.acp.turn_context import format_acp_prompt_parts

from .process_group import own_process_group
from .pynia_mcp import McpBridge
from .workspace import read_document, write_document
from .configuration_defaults import load_defaults, normalize_pynia


class Conversation:
    def __init__(self, session_id, state=None):
        self.state = TabChatState.from_dict(session_id, state)
        self.state.config_snapshot = (state or {}).get("config_snapshot") or {}
        empty = not (self.state.messages or self.state.acp_session_id or self.state.config_snapshot)
        self.fresh_conversation = empty and (not self.state.agent_id or (state or {}).get("fresh_conversation") is True)
        self.defaults_applied = bool((state or {}).get("defaults_applied", False))
        self.configuration_defaults = {}
        self.client = None
        self.group = None
        self.operation = threading.RLock()
        self.lock = threading.RLock()
        self.permissions = {}
        self.error = None
        self.context = {}
        self.turn_id = None
        self.cancelled = threading.Event()
        self.closed = False
        self.inline_lock = threading.Lock()
        self.inline_chunks = []


class PyniaService:
    def __init__(self, emit, runtime_rpc, runtime_query, catalog, *, launch_resolver=None, state_path=None):
        self.emit = emit
        self.runtime_rpc = runtime_rpc
        self.runtime_query = runtime_query
        self.catalog_provider = catalog
        self.launch_resolver = launch_resolver or resolve_launch
        self.root = Path(state_path or os.environ.get("DATAPYN_WORKSPACE_PATH") or os.environ.get("DATAPYN_RUNTIME_STATE_PATH") or Path.home() / ".datapyn-tauri-preview") / "pynia"
        self.conversations = {}
        self.pending_tools = {}
        self.lock = threading.RLock()
        self.mcp = None
        self.acp = AcpSessionService()
        self.closed = False
        self.installations = {}

    def _path(self, session_id):
        # Session IDs are protocol identifiers, but never filesystem paths.
        return self.root / (uuid.uuid5(uuid.NAMESPACE_URL, session_id).hex + ".json")

    def _conversation(self, session_id, data=None, defaults=None):
        if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
            raise ValueError("session_id must be a nonempty string of at most 128 characters")
        with self.lock:
            if session_id not in self.conversations:
                path = self._path(session_id)
                saved = data
                if saved is None and path.is_file():
                    saved = read_document(str(path))["document"]
                conversation = Conversation(session_id, saved)
                if conversation.fresh_conversation:
                    conversation.configuration_defaults = normalize_pynia(defaults if defaults is not None else load_defaults(self.root.parent).get("pynia", {}))
                    identifier = conversation.configuration_defaults.get("default_agent_id")
                    if not conversation.state.agent_id and identifier and get_agent(identifier) is not None:
                        conversation.state.agent_id = identifier
                self.conversations[session_id] = conversation
            return self.conversations[session_id]

    def state(self, conversation):
        with conversation.lock:
            state = conversation.state
            return {**state.to_dict(), "busy": state.busy, "selectors": composer_selectors(state.config_snapshot, loading=state.config_loading),
                    "fresh_conversation": conversation.fresh_conversation, "defaults_applied": conversation.defaults_applied,
                    "permissions": [{"request_id": identifier, "params": entry[1]} for identifier, entry in conversation.permissions.items()],
                    "error": conversation.error, "auth_methods": conversation.client.auth_methods if conversation.client is not None else []}

    def _emit_state(self, conversation):
        self.emit({"event": "pynia.state", "payload": {"session_id": conversation.state.tab_id, "state": self.state(conversation)}})

    def _persist(self, conversation):
        with conversation.lock:
            document = conversation.state.to_dict()
            document["config_snapshot"] = conversation.state.config_snapshot
            document["defaults_applied"] = conversation.defaults_applied
            document["fresh_conversation"] = conversation.fresh_conversation
        # Keep complete recent turns. A pathological agent cannot grow a local
        # history indefinitely; the existing workspace cap is 16 MiB.
        while len(json.dumps(document, ensure_ascii=False).encode("utf-8")) > 15 * 1024 * 1024 and len(document["messages"]) > 2:
            document["messages"].pop(0)
        write_document(str(self._path(conversation.state.tab_id)), document)

    def _error(self, conversation, error):
        with conversation.lock:
            conversation.error = str(error)
        self.emit({"event": "pynia.error", "payload": {"session_id": conversation.state.tab_id, "error": str(error)}})

    def _bridge(self):
        with self.lock:
            if self.mcp is None:
                self.mcp = McpBridge(self._tool)
            return self.mcp

    def _mcp_config(self, conversation, cwd):
        bridge = self._bridge()
        args = ["--mcp-stdio"] if getattr(sys, "frozen", False) else ["-u", "-m", "datapyn_runtime", "--mcp-stdio"]
        env = {"DATAPYN_MCP_HOST": "127.0.0.1", "DATAPYN_MCP_PORT": str(bridge.port), "DATAPYN_MCP_TOKEN": bridge.token,
               "DATAPYN_TAB_ID": conversation.state.tab_id, "PYTHONUTF8": "1"}
        if not getattr(sys, "frozen", False):
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        config = {"name": "datapyn", "command": sys.executable, "args": args, "env": [{"name": key, "value": value} for key, value in env.items()]}
        native = {"mcpServers": {"datapyn": {"command": sys.executable, "args": args, "env": env}}}
        if conversation.state.agent_id in {"cursor", "copilot"}:
            directory = cwd / ".cursor" if conversation.state.agent_id == "cursor" else cwd
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / ("mcp.json" if conversation.state.agent_id == "cursor" else "datapyn-mcp.json")
            path.write_text(json.dumps(native), encoding="utf-8")
            if conversation.state.agent_id == "copilot":
                return [], ["--additional-mcp-config", f"@{path}"]
        return [config], []

    def _prepare(self, conversation):
        if conversation.closed or self.closed:
            raise RuntimeError("Pynia conversation is closed")
        if conversation.client is not None and conversation.client.is_running and conversation.state.acp_session_id:
            return
        specification = get_agent(conversation.state.agent_id)
        if specification is None:
            raise ValueError("Choose an installed ACP agent first")
        launch = self.launch_resolver(specification)
        if launch is None:
            raise RuntimeError(f"{specification.label} is unavailable. {specification.install.windows if os.name == 'nt' else specification.install.other}")
        cwd = self.root / "workspaces" / uuid.uuid5(uuid.NAMESPACE_URL, conversation.state.tab_id).hex
        cwd.mkdir(parents=True, exist_ok=True)
        servers, extra = self._mcp_config(conversation, cwd)
        client = AcpTransport(specification.id)
        client.session_update.connect(lambda session, update: self._update(conversation, session, update))
        client.permission_request.connect(lambda rpc_id, params: self._permission(conversation, rpc_id, params))
        client.process_exited.connect(lambda code: self._process_exited(conversation, code))
        conversation.client = client
        try:
            client.start(launch[0], list(launch[1]) + extra, cwd=str(cwd))
            conversation.group = own_process_group(client._proc.pid)
            self.acp.handshake(client, version="1.57.0")
            previous = conversation.state.acp_session_id
            preferred = composer_selectors(conversation.state.config_snapshot)
            fresh_defaults = conversation.fresh_conversation and not previous
            if fresh_defaults:
                defaults = conversation.configuration_defaults
                agent_defaults = defaults.get("agent_prefs", {}).get(conversation.state.agent_id, {})
                for kind, field in (("model", "model_id"), ("reasoning", "thought_level")):
                    fallback = defaults.get(field, "") if defaults.get("default_agent_id") == conversation.state.agent_id else ""
                    desired = agent_defaults.get(field) or fallback
                    if desired:
                        preferred.setdefault(kind, {})["current"] = desired
            # Resume only when explicitly supported by the selected agent.
            capabilities = client.agent_capabilities.get("sessionCapabilities") or {}
            if previous and capabilities.get("resume"):
                try:
                    client.session_resume(previous, str(cwd), servers)
                    session_id, snapshot = previous, client.last_session_info
                except Exception:
                    session_id, normalized = self.acp.open_session(client, str(cwd), servers)
                    snapshot = normalized.raw
            else:
                session_id, normalized = self.acp.open_session(client, str(cwd), servers)
                snapshot = normalized.raw
            with conversation.lock:
                conversation.state.acp_session_id = session_id
                conversation.state.config_snapshot = snapshot
                conversation.state.completion_session_id = None
                conversation.state.acp_session_recreated = bool(previous and session_id != previous)
                conversation.error = None
            for kind in ("model", "reasoning"):
                desired = preferred.get(kind, {}).get("current")
                selector = composer_selectors(snapshot).get(kind) or {}
                values = {item["value"] for item in selector.get("values", [])}
                if desired and desired in values and not selector.get("hidden") and desired != selector.get("current"):
                    normalized = self.acp.set_option(client, session_id, selector["id"], desired, snapshot, kind=kind)
                    snapshot = normalized.raw
                    conversation.state.config_snapshot = snapshot
            if fresh_defaults:
                conversation.defaults_applied = True
                conversation.fresh_conversation = False
            self._persist(conversation)
        except BaseException:
            self._stop_client(conversation)
            raise

    def _process_exited(self, conversation, code):
        if not conversation.closed and not self.closed and conversation.client is not None and not conversation.client._stopping and code not in {0, -1}:
            self._error(conversation, f"ACP agent exited with code {code}")

    def _stop_client(self, conversation):
        client, conversation.client = conversation.client, None
        if client is not None:
            client.stop(timeout=1)
        group, conversation.group = conversation.group, None
        if group is not None:
            group.close()

    def _run_prepare(self, conversation):
        with conversation.operation:
            try:
                self._prepare(conversation)
            except Exception as exc:
                self._error(conversation, exc)
            finally:
                with conversation.lock:
                    conversation.state.config_loading = False
                    conversation.state.session_ready.set()
                self._emit_state(conversation)

    def _update(self, conversation, session, update):
        if session and session == conversation.state.completion_session_id:
            if update.get("sessionUpdate") == "agent_message_chunk":
                conversation.inline_chunks.append(str((update.get("content") or {}).get("text") or ""))
            if update.get("sessionUpdate") == "tool_call" and conversation.client:
                conversation.client.session_cancel(session)
            return
        if session != conversation.state.acp_session_id:
            return
        kind = update.get("sessionUpdate")
        payload = {"session_id": conversation.state.tab_id}
        with conversation.lock:
            if kind in {"agent_message_chunk", "agent_thought_chunk"}:
                text = str((update.get("content") or {}).get("text") or "")
                if not text:
                    return
                payload["text"] = text[:32768]
                if kind == "agent_message_chunk":
                    if not conversation.state.messages or conversation.state.messages[-1].get("role") != "assistant":
                        conversation.state.append_message("assistant", "")
                    message = conversation.state.messages[-1]
                    message["content"] = (str(message.get("content", "")) + text)[:1024 * 1024]
                    event = "pynia.chunk"
                else:
                    conversation.state.turn_activity["thinking"] = (conversation.state.turn_activity.get("thinking", "") + text)[-8000:]
                    event = "pynia.thinking"
            elif kind in {"tool_call", "tool_call_update"}:
                payload["payload"] = update
                tools = conversation.state.turn_activity.setdefault("tools", [])
                card = format_activity_tool(update)
                if card:
                    conversation.state.turn_activity["tools"] = merge_activity_tool(tools, card)[-64:]
                event = "pynia.tool"
            elif kind == "config_option_update":
                incoming = {key: update[key] for key in ("models", "configOptions") if key in update}
                conversation.state.config_snapshot = merge_config_snapshot(conversation.state.config_snapshot, incoming)
                if conversation.client:
                    conversation.client.last_session_info = merge_config_snapshot(conversation.client.last_session_info, incoming)
                self._emit_state(conversation)
                return
            else:
                return
        self.emit({"event": event, "payload": payload})

    def _permission(self, conversation, rpc_id, params):
        if params.get("sessionId") == conversation.state.completion_session_id and conversation.client:
            self._respond_permission(conversation, rpc_id, reject_option_id(params))
            return
        if params.get("sessionId") and params["sessionId"] != conversation.state.acp_session_id:
            return
        if permission_should_reject(params):
            self._respond_permission(conversation, rpc_id, reject_option_id(params))
            return
        option_ids = [str(option.get("optionId") or option.get("id") or "") for option in params.get("options", []) if isinstance(option, dict)]
        question = bool(params.get("questions")) or bool(option_ids and not any(any(word in identifier.lower() for word in ("allow", "reject", "deny")) for identifier in option_ids))
        if not question and not permission_should_ask(params):
            self._respond_permission(conversation, rpc_id, allow_option_id(params))
            return
        request_id = uuid.uuid4().hex
        with conversation.lock:
            conversation.permissions[request_id] = (rpc_id, params)
        self.emit({"event": "pynia.permission", "payload": {"session_id": conversation.state.tab_id, "request_id": request_id, "params": params}})
        self._emit_state(conversation)

    def _respond_permission(self, conversation, rpc_id, option_id, answers=None):
        if conversation.client is not None:
            result = {"outcome": {"outcome": "selected", "optionId": option_id}}
            if answers is not None:
                result["answers"] = answers
            conversation.client.respond(rpc_id, result)

    def _run_turn(self, conversation, text, files, context, persona, turn_id):
        with conversation.operation:
            try:
                self._prepare(conversation)
                if conversation.cancelled.is_set():
                    return
                with conversation.lock:
                    conversation.state.locked = True
                    conversation.state.append_message("assistant", "")
                prompt = format_acp_prompt_parts(text, context, attachments=files)
                if persona:
                    prompt.insert(0, {"type": "text", "text": "User's preferred assistant instructions:\n" + persona[:24000]})
                self._emit_state(conversation)
                result = self.acp.prompt(conversation.client, conversation.state.acp_session_id, prompt, timeout=300)
                if result.get("stopReason") == "cancelled":
                    conversation.cancelled.set()
            except Exception as exc:
                self._error(conversation, exc)
                with conversation.lock:
                    conversation.state.append_message("assistant", str(exc), error=True)
            finally:
                with conversation.lock:
                    activity = conversation.state.consume_activity()
                    if activity and conversation.state.messages and conversation.state.messages[-1].get("role") == "assistant":
                        conversation.state.messages[-1]["activity"] = activity
                    conversation.state.busy = False
                    conversation.turn_id = None
                self._persist(conversation)
                self._emit_state(conversation)
                self.emit({"event": "pynia.turn_ended", "payload": {"session_id": conversation.state.tab_id, "turn_id": turn_id,
                          "cancelled": conversation.cancelled.is_set()}})

    def _request_frontend(self, session_id, name, arguments):
        identifier, done, box = uuid.uuid4().hex, threading.Event(), {}
        with self.lock:
            self.pending_tools[identifier] = (done, box)
        try:
            self.emit({"event": "pynia.tool_request", "payload": {"session_id": session_id, "request_id": identifier, "name": name, "arguments": arguments}})
            if not done.wait(timeout=120):
                raise TimeoutError("The desktop did not answer the Pynia tool request")
            if box.get("error"):
                raise RuntimeError(str(box["error"]))
            return box.get("result") or {}
        finally:
            with self.lock:
                self.pending_tools.pop(identifier, None)

    def _tool(self, session_id, name, arguments):
        if session_id not in self.conversations:
            raise ValueError("The MCP tab is no longer open")
        if name == "datapyn_query":
            return self.runtime_query(session_id, arguments)
        if name == "datapyn_snapshot" and arguments.get("action") == "variables":
            return self.runtime_rpc(session_id, "variable.inspect", {"variable_name": "__namespace__"})
        if name == "datapyn_snapshot" and arguments.get("action") == "schema":
            return self.runtime_rpc(session_id, "explorer.snapshot", {})
        if name == "datapyn_inspect" and arguments.get("kind") == "variable":
            return self.runtime_rpc(session_id, "variable.inspect", {**arguments, "name": arguments.get("variable_name")})
        if name == "datapyn_database":
            operation = arguments.get("operation")
            catalog = self.catalog_provider()
            if operation == "list":
                return catalog.list()
            if operation == "schema":
                return self.runtime_rpc(session_id, "explorer.snapshot", arguments)
            if operation == "tables":
                return self.runtime_rpc(session_id, "explorer.list", {"schema": arguments.get("schema_name"), "node": {"kind": "category", "category": "table", "schema": arguments.get("schema_name")}})
            if operation == "describe":
                return self.runtime_rpc(session_id, "explorer.details", {"name": arguments.get("table_name"), "schema": arguments.get("schema_name")})
            if operation == "sample":
                query = self.runtime_rpc(session_id, "explorer.query", {"name": arguments.get("table_name"), "schema": arguments.get("schema_name"), "limit": arguments.get("limit", 100)})
                return self.runtime_query(session_id, {"language": "sql", "code": query["code"]})
            if operation == "create":
                config = {key: arguments[key] for key in ("db_type", "host", "port", "database", "username") if key in arguments}
                return catalog.save_connection({"name": arguments.get("connection_name"), "config": config}, save_password=False)
            if operation in {"connect", "open"}:
                identifier = catalog.resolve_ref(arguments.get("connection_group"), arguments.get("connection_name"))
                return self.runtime_rpc(session_id, "connection.connect", {"connection_id": identifier})
        return self._request_frontend(session_id, name, arguments)

    def dispatch(self, method, params):
        if self.closed:
            raise RuntimeError("Pynia is shutting down")
        if method == "pynia.catalog":
            return {"agents": [{"id": spec.id, "label": spec.label, "color": spec.color, "status": probe_status(spec),
                                "detail": "Authentication is verified when opening the ACP conversation",
                                "install_command": spec.install.windows if os.name == "nt" else spec.install.other,
                                "docs_url": spec.install.docs_url, "login_command": list(spec.install.login_command)} for spec in list_agents()]}
        if method == "pynia.install":
            agent_id = params.get("agent_id")
            if get_agent(agent_id) is None:
                raise ValueError("Unknown ACP agent")
            with self.lock:
                if agent_id in self.installations:
                    raise RuntimeError("The selected ACP agent is already being installed")
                self.installations[agent_id] = None
            threading.Thread(target=self._install, args=(agent_id,), name=f"pynia-install-{agent_id}", daemon=True).start()
            return {"status": "installing"}
        if method == "pynia.attach":
            paths = params.get("paths")
            if not isinstance(paths, list) or len(paths) > 4 or any(not isinstance(path, str) for path in paths):
                raise ValueError("paths must be a list of at most four file paths")
            return {"attachments": attachments_from_paths(paths)}
        if method == "pynia.tool_reply":
            with self.lock:
                pending = self.pending_tools.get(params.get("request_id"))
                if pending is None:
                    raise ValueError("The Pynia tool request already ended")
                pending[1].update({"result": params.get("result"), "error": params.get("error")})
                pending[0].set()
            return {"status": "answered"}
        conversation = self._conversation(params.get("session_id"), params.get("data"), params.get("defaults"))
        if method == "pynia.state":
            return self.state(conversation)
        if method == "pynia.inline":
            return self.inline(conversation, params)
        if method == "pynia.select_agent":
            agent_id = params.get("agent_id")
            if get_agent(agent_id) is None:
                raise ValueError("Unknown ACP agent")
            with conversation.lock:
                if conversation.state.busy:
                    raise RuntimeError("Pynia is already working on this tab")
                if conversation.state.locked and conversation.state.agent_id != agent_id:
                    raise RuntimeError("Clear the conversation before changing its agent")
                if conversation.fresh_conversation and params.get("defaults") is not None:
                    conversation.configuration_defaults = normalize_pynia(params["defaults"])
                if conversation.state.agent_id != agent_id:
                    self._stop_client(conversation)
                    conversation.state.acp_session_id = None
                conversation.state.agent_id = agent_id
                conversation.state.config_loading = True
                conversation.state.session_ready.clear()
            self._emit_state(conversation)
            threading.Thread(target=self._run_prepare, args=(conversation,), daemon=True).start()
            return {"status": "preparing"}
        if method == "pynia.prompt":
            text = params.get("text", "")
            if not isinstance(text, str) or len(text) > 128000:
                raise ValueError("text must be a string of at most 128000 characters")
            files = normalize_attachments(params.get("attachments"))
            if not text.strip() and not files:
                raise ValueError("Write a message or add an attachment")
            with conversation.lock:
                if not conversation.state.agent_id:
                    raise ValueError("Choose an ACP agent first")
                if conversation.state.busy:
                    raise RuntimeError("Pynia is already working on this tab")
                conversation.state.busy = True
                conversation.state.reset_activity()
                conversation.error = None
                conversation.cancelled.clear()
                conversation.context = deepcopy(params.get("context") or {})
                conversation.state.append_message("user", text, attachments=display_attachments(files))
                turn_id = uuid.uuid4().hex
                conversation.turn_id = turn_id
            self._emit_state(conversation)
            threading.Thread(target=self._run_turn, args=(conversation, text, files, conversation.context, str(params.get("persona", "")), turn_id), daemon=True).start()
            return {"status": "queued", "turn_id": turn_id}
        if method == "pynia.cancel":
            conversation.cancelled.set()
            if conversation.client is not None and conversation.state.acp_session_id:
                conversation.client.session_cancel(conversation.state.acp_session_id)
            return {"status": "cancelling"}
        if method == "pynia.clear":
            if conversation.state.busy:
                raise RuntimeError("Cancel the active turn before clearing it")
            self._stop_client(conversation)
            with conversation.lock:
                conversation.state = TabChatState(tab_id=conversation.state.tab_id, agent_id=conversation.state.agent_id)
                conversation.configuration_defaults = normalize_pynia(params.get("defaults") if params.get("defaults") is not None else load_defaults(self.root.parent).get("pynia", {}))
                conversation.fresh_conversation = True
                conversation.defaults_applied = False
                conversation.permissions.clear()
                conversation.error = None
            self._persist(conversation)
            self._emit_state(conversation)
            return self.state(conversation)
        if method == "pynia.answer_permission":
            with conversation.lock:
                permission = conversation.permissions.get(params.get("request_id"))
            if permission is None:
                raise ValueError("Unknown permission request")
            option = params.get("option_id") or reject_option_id(permission[1])
            allowed = {item.get("optionId", item.get("id")) for item in permission[1].get("options", [])}
            if allowed and option not in allowed:
                raise ValueError("Unknown permission option")
            with conversation.lock:
                conversation.permissions.pop(params.get("request_id"), None)
            self._respond_permission(conversation, permission[0], option, params.get("answers"))
            self._emit_state(conversation)
            return {"status": "answered"}
        if method in {"pynia.config", "pynia.authenticate"}:
            with conversation.lock:
                if conversation.state.busy or conversation.state.config_loading:
                    raise RuntimeError("Wait for the current Pynia operation before changing agent configuration")
                conversation.state.config_loading = True
            self._emit_state(conversation)
            threading.Thread(target=self._configuration, args=(conversation, method, dict(params)), daemon=True).start()
            return {"status": "queued"}
        raise ValueError(f"Unknown Pynia method: {method}")

    def inline(self, conversation, params):
        body = params.get("body")
        if not isinstance(body, str) or len(body) > 32000:
            raise ValueError("body must be a string of at most 32000 characters")
        timeout = float(params.get("timeout", 4))
        if not 1 <= timeout <= 8:
            raise ValueError("timeout must be between one and eight seconds")
        if conversation.state.busy or not conversation.state.agent_id or not conversation.inline_lock.acquire(blocking=False):
            return {"text": ""}
        try:
            if conversation.client is None or not conversation.client.is_running:
                # Opening/authenticating an agent never blocks an editor request.
                return {"text": ""}
            if not conversation.state.completion_session_id:
                cwd = self.root / "workspaces" / uuid.uuid5(uuid.NAMESPACE_URL, conversation.state.tab_id).hex
                identifier, _normalized = self.acp.open_session(conversation.client, str(cwd), [])
                conversation.state.completion_session_id = identifier
            conversation.inline_chunks = []
            text = "You are a code completion engine. Return ONLY the ghost text to insert at the cursor. No markdown, explanation or tools.\n\n" + body
            try:
                self.acp.prompt(conversation.client, conversation.state.completion_session_id, text, timeout=timeout)
            except TimeoutError:
                conversation.client.session_cancel(conversation.state.completion_session_id)
                return {"text": ""}
            return {"text": "".join(conversation.inline_chunks)[:16000]}
        finally:
            conversation.inline_lock.release()

    def _configuration(self, conversation, method, params):
        with conversation.operation:
            try:
                self._prepare(conversation)
                if method == "pynia.authenticate":
                    available = {str(item.get("id") or item.get("methodId") or "") for item in conversation.client.auth_methods}
                    if params.get("method_id") not in available:
                        raise ValueError("Choose an authentication method advertised by this ACP agent")
                    conversation.client.authenticate(str(params.get("method_id", "")))
                else:
                    identifier, value = str(params.get("config_id", "")), str(params.get("value", ""))
                    normalized = self.acp.set_option(conversation.client, conversation.state.acp_session_id, identifier, value,
                                                     conversation.state.config_snapshot, kind=params.get("kind", "model"))
                    conversation.state.config_snapshot = normalized.raw
                    self._persist(conversation)
                self._emit_state(conversation)
            except Exception as exc:
                self._error(conversation, exc)
            finally:
                with conversation.lock:
                    conversation.state.config_loading = False
                self._emit_state(conversation)

    def _install(self, agent_id):
        process, group, error = None, None, None
        exit_code = -1
        try:
            if self.closed:
                raise RuntimeError("Pynia is shutting down")
            packages = {"claude": ["@anthropic-ai/claude-code", "@agentclientprotocol/claude-agent-acp"],
                        "codex": ["@openai/codex", "@agentclientprotocol/codex-acp"], "copilot": ["@github/copilot"]}
            if agent_id in packages:
                npm = which_command("npm")
                if npm is None:
                    raise RuntimeError("Install Node.js LTS with npm before installing this agent")
                argv = popen_argv(npm, ["install", "-g", *packages[agent_id]])
            elif os.name == "nt":
                argv = ["powershell.exe", "-NoProfile", "-Command", "irm 'https://cursor.com/install?win32=true' | iex"]
            else:
                argv = ["sh", "-c", "curl https://cursor.com/install -fsS | bash"]
            process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            group = own_process_group(process.pid)
            with self.lock:
                self.installations[agent_id] = group
            def read_output():
                remaining = 256 * 1024
                for raw in iter(lambda: process.stdout.read(4096), b""):
                    if self.closed:
                        break
                    if remaining <= 0:
                        continue  # Drain output so a noisy installer cannot deadlock.
                    raw = raw[:remaining]
                    remaining -= len(raw)
                    self.emit({"event": "pynia.install_output", "payload": {"agent_id": agent_id, "text": raw.decode("utf-8", errors="replace")}})
            threading.Thread(target=read_output, daemon=True).start()
            exit_code = process.wait(timeout=300)
            if exit_code:
                error = f"The {agent_id} installer exited with code {exit_code}"
        except Exception as exc:
            error = str(exc)
        finally:
            if group is not None:
                group.close()
            if process is not None:
                if process.poll() is None:
                    process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            with self.lock:
                self.installations.pop(agent_id, None)
            if not self.closed:
                self.emit({"event": "pynia.install_finished", "payload": {"agent_id": agent_id, "success": exit_code == 0, "exit_code": exit_code, "error": error}})

    def detach(self, session_id):
        with self.lock:
            conversation = self.conversations.pop(session_id, None)
        if conversation is not None:
            conversation.closed = True
            conversation.cancelled.set()
            self._stop_client(conversation)

    def close(self):
        self.closed = True
        for session_id in list(self.conversations):
            self.detach(session_id)
        if self.mcp is not None:
            self.mcp.close()
        with self.lock:
            for group in list(self.installations.values()):
                if group is not None:
                    group.close()
            for done, box in self.pending_tools.values():
                box["error"] = "Pynia is shutting down"
                done.set()
