"""
CopilotClient - GitHub Copilot integration using the official SDK.

Uses the GitHub Copilot SDK (copilot) which communicates with the
Copilot CLI via JSON-RPC.

The client maintains a persistent session to preserve conversation context.
Tool execution is thread-safe via QMetaObject.invokeMethod.
"""

import json
import logging
import time
import threading
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from PyQt6.QtCore import (
    QObject, QThread, pyqtSignal, pyqtSlot,
    QMutex, QMutexLocker, Qt, QMetaObject, Q_ARG,
)

if TYPE_CHECKING:
    from .mcp_tools import MCPToolRegistry

logger = logging.getLogger(__name__)

# Default models - will be updated from SDK at runtime
DEFAULT_MODELS = [
    {"id": "gpt-4o", "name": "GPT-4o"},
    {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
]


def _try_import_sdk():
    """Try to import the Copilot SDK."""
    try:
        from copilot import CopilotClient as SDKClient
        from copilot import Tool as SDKTool
        from copilot.generated.session_events import SessionEventType
        return SDKClient, SDKTool, SessionEventType, None
    except ImportError as e:
        return None, None, None, str(e)


class ThreadSafeToolExecutor(QObject):
    """
    Executes MCP tools on the main thread regardless of calling thread.
    
    When SDK calls a tool handler from its async context (worker thread),
    this executor ensures the actual execution happens on the main thread
    where Qt widgets can be safely manipulated.
    """
    
    # Signal to execute on main thread
    _execute_signal = pyqtSignal(str, str)
    _result_ready = pyqtSignal()
    
    def __init__(self, registry: "MCPToolRegistry", parent=None):
        super().__init__(parent)
        self._registry = registry
        self._result: Dict[str, Any] = {}
        self._mutex = QMutex()
        self._pending_event = None
        
        # Connect signal to slot
        self._execute_signal.connect(self._do_execute_on_main_thread, Qt.ConnectionType.QueuedConnection)
    
    @pyqtSlot(str, str)
    def _do_execute_on_main_thread(self, tool_name: str, arguments_json: str) -> None:
        """Execute tool on main thread. Called via signal."""
        try:
            arguments = json.loads(arguments_json) if arguments_json else {}
            logger.info(f"[MAIN THREAD] Executing tool: {tool_name}")
            result = self._registry.execute(tool_name, arguments)
            logger.info(f"[MAIN THREAD] Tool {tool_name} completed, result keys: {result.keys() if isinstance(result, dict) else 'not dict'}")
            with QMutexLocker(self._mutex):
                self._result = result
        except Exception as e:
            logger.exception(f"[MAIN THREAD] Error executing tool {tool_name}")
            with QMutexLocker(self._mutex):
                self._result = {"error": str(e)}
        finally:
            # Signal that result is ready
            if self._pending_event:
                self._pending_event.set()
            self._result_ready.emit()
    
    @pyqtSlot(str, str)
    def _execute_on_main_thread(self, tool_name: str, arguments_json: str) -> None:
        """Execute tool on main thread. Called via QMetaObject.invokeMethod."""
        try:
            arguments = json.loads(arguments_json) if arguments_json else {}
            result = self._registry.execute(tool_name, arguments)
            with QMutexLocker(self._mutex):
                self._result = result
        except Exception as e:
            logger.exception(f"Error executing tool {tool_name}")
            with QMutexLocker(self._mutex):
                self._result = {"error": str(e)}
    
    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Execute tool and return result as string.
        
        Thread-safe: can be called from any thread.
        """
        from PyQt6.QtCore import QThread
        from PyQt6.QtWidgets import QApplication
        import threading
        import time
        
        arguments_json = json.dumps(arguments) if arguments else "{}"
        
        # Check if we're on the main thread
        app = QApplication.instance()
        is_main_thread = app and QThread.currentThread() == app.thread()
        
        if is_main_thread:
            # Direct execution on main thread
            logger.info(f"[DIRECT] Executing tool on main thread: {tool_name}")
            self._execute_on_main_thread(tool_name, arguments_json)
        else:
            # Need to invoke on main thread and wait
            logger.info(f"[WORKER] Scheduling tool on main thread: {tool_name}")
            
            # Create event for waiting
            self._pending_event = threading.Event()
            
            # Emit signal to execute on main thread
            self._execute_signal.emit(tool_name, arguments_json)
            
            # Wait for result with timeout, checking periodically
            start_time = time.time()
            timeout = 30.0
            while not self._pending_event.is_set():
                if time.time() - start_time > timeout:
                    logger.error(f"[WORKER] Timeout waiting for tool {tool_name}")
                    self._pending_event = None
                    return f"Error: Timeout executing {tool_name}"
                time.sleep(0.05)  # Small sleep to avoid busy-waiting
            
            self._pending_event = None
            logger.info(f"[WORKER] Tool {tool_name} completed")
        
        # Get result
        with QMutexLocker(self._mutex):
            result = self._result
            self._result = {}
        
        # Format result as string for SDK
        if "error" in result:
            return f"Error: {result['error']}"
        
        content = result.get("content", [])
        return "\n".join(c.get("text", str(c)) for c in content)


class CopilotWorker(QObject):
    """Worker that manages Copilot SDK client in background thread."""

    # Signals
    chunk = pyqtSignal(str)  # Streaming text chunk
    complete = pyqtSignal(str)  # Full response
    error = pyqtSignal(str)  # Error message
    auth_ok = pyqtSignal()  # Auth verified
    auth_needed = pyqtSignal()  # Auth required
    auth_started = pyqtSignal(str)  # Login process started with info message
    models_ready = pyqtSignal(list)  # List of available models
    tool_call = pyqtSignal(str, dict, str)  # tool_name, arguments, tool_call_id
    tool_result = pyqtSignal(str, str)  # tool_name, result
    thinking = pyqtSignal(str)  # Reasoning text
    finished = pyqtSignal()
    ready = pyqtSignal()  # Worker is ready to accept chat requests
    inline_complete = pyqtSignal(str)  # Inline completion result

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
        self._loop = None  # Persistent event loop
        self._inline_prompt = ""  # For inline completions

    def set_model(self, model: str):
        self._model = model

    def set_prompt(self, prompt: str):
        self._prompt = prompt

    def set_system_message(self, system_message: str):
        self._system_message = system_message
    
    def set_inline_prompt(self, prompt: str):
        """Set prompt for inline completion request."""
        self._inline_prompt = prompt

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
        if self._session and self._loop and not self._loop.is_closed():
            try:
                # Run abort() coroutine in the worker's event loop
                self._loop.run_until_complete(self._session.abort())
            except Exception:
                pass

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
            self._sdk_client = SDKClient()
            self._loop.run_until_complete(self._sdk_client.start())

            # List models to verify auth (async)
            try:
                models = self._loop.run_until_complete(self._sdk_client.list_models())
                model_list = [{"id": m.id, "name": m.name} for m in models]
                self.models_ready.emit(model_list)
                self.auth_ok.emit()
                # Keep worker alive - emit ready for subsequent chats
                self.ready.emit()
            except Exception as e:
                logger.info(f"Auth check failed: {e}")
                self.auth_needed.emit()
                self.finished.emit()

        except Exception as e:
            logger.exception("Error initializing Copilot SDK")
            self.error.emit(str(e))
            self.finished.emit()

    def run_login(self):
        """Run GitHub CLI login process automatically. Keep loop/client persistent."""
        import asyncio
        import subprocess
        import shutil
        
        # Use persistent event loop
        self._ensure_loop()
        
        try:
            # Check if gh CLI is available
            gh_path = shutil.which("gh")
            if not gh_path:
                self.error.emit(
                    "GitHub CLI not found. Please install it from https://cli.github.com/ "
                    "and restart DataPyn."
                )
                self.finished.emit()
                return
            
            self.auth_started.emit("Opening browser for GitHub authentication...")
            
            # Run gh auth login with web flow
            # -w opens browser, -s sets scopes, -h for github.com
            process = subprocess.Popen(
                [gh_path, "auth", "login", "-w", "-h", "github.com", "-s", "read:user,repo,gist"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            
            # Wait for process to complete (user authenticates in browser)
            stdout, stderr = process.communicate(timeout=180)  # 3 min timeout
            
            if process.returncode == 0:
                logger.info("GitHub auth completed successfully")
                # Now verify with SDK (async)
                SDKClient, _, _, _ = _try_import_sdk()
                if SDKClient:
                    self._sdk_client = SDKClient()
                    self._loop.run_until_complete(self._sdk_client.start())
                    try:
                        models = self._loop.run_until_complete(self._sdk_client.list_models())
                        model_list = [{"id": m.id, "name": m.name} for m in models]
                        self.models_ready.emit(model_list)
                        self.auth_ok.emit()
                        # Keep worker alive for chats
                        self.ready.emit()
                    except Exception as e:
                        logger.warning(f"Auth verification failed: {e}")
                        self.auth_ok.emit()
                        self.ready.emit()  # Still ready for chats
            else:
                error_msg = stderr.strip() or stdout.strip() or "Authentication failed"
                logger.error(f"GitHub auth failed: {error_msg}")
                self.error.emit(f"GitHub authentication failed: {error_msg}")
                self.finished.emit()
                
        except subprocess.TimeoutExpired:
            self.error.emit("Authentication timed out. Please try again.")
            self.finished.emit()
        except Exception as e:
            logger.exception("Error during GitHub login")
            self.error.emit(str(e))
            self.finished.emit()

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
        if not self._sdk_client:
            self._sdk_client = SDKClient()
            await self._sdk_client.start()
            logger.info("Copilot SDK client started")

        # Build SDK tools if we have an executor
        if self._tool_executor and not self._sdk_tools:
            self._sdk_tools = self._build_sdk_tools(SDKTool)
            logger.info(f"Built {len(self._sdk_tools)} SDK tools")
            for t in self._sdk_tools:
                logger.info(f"  Tool: {t.name}")

        # Create session if needed (or recreate to update tools)
        if not self._session:
            await self._async_create_session()
            logger.info("Copilot session created")

        if not self._prompt:
            self.error.emit("No message to send")
            return

        # Stream response
        full_response = ""
        
        # Set up event collection
        events = []
        idle_event = asyncio.Event()
        
        def on_event(event):
            events.append(event)
            if event.type == EventType.SESSION_IDLE:
                idle_event.set()
            elif event.type == EventType.SESSION_ERROR:
                idle_event.set()
        
        # Register handler
        unsubscribe = self._session.on(on_event)
        
        try:
            # Send message
            await self._session.send({"prompt": self._prompt})
            
            # Wait for idle with timeout, processing events as they come
            start_time = time.time()
            timeout = 180  # 3 minutes for complex workflows with multiple tool calls
            
            while not idle_event.is_set() and not self._cancelled:
                if time.time() - start_time > timeout:
                    self.error.emit("Chat request timed out")
                    break
                
                # Process any queued events
                while events:
                    event = events.pop(0)
                    event_type = event.type
                    
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
                    
                    elif event_type == EventType.TOOL_EXECUTION_START:
                        tool_name = getattr(event.data, "tool_name", "") or ""
                        arguments = getattr(event.data, "arguments", {}) or {}
                        tool_call_id = getattr(event.data, "tool_call_id", "") or ""
                        if tool_name:
                            self.tool_call.emit(tool_name, arguments, tool_call_id)
                    
                    elif event_type == EventType.TOOL_EXECUTION_COMPLETE:
                        tool_name = getattr(event.data, "tool_name", "") or ""
                        result = getattr(event.data, "result", None)
                        result_text = str(result) if result else ""
                        if tool_name:
                            self.tool_result.emit(tool_name, result_text)
                    
                    elif event_type == EventType.SESSION_ERROR:
                        error_msg = getattr(event.data, "message", "") or str(event.data)
                        self.error.emit(error_msg)
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
            
            self.complete.emit(full_response)
            
        except Exception as e:
            logger.exception("Error during chat")
            self.error.emit(str(e))
        finally:
            unsubscribe()

    async def _async_create_session(self):
        """Create a new session with current configuration (async)."""
        # Get list of our registered tool names
        our_tool_names = set()
        if self._sdk_tools:
            our_tool_names = {t.name for t in self._sdk_tools}
        
        # Hook to block any tool not in our registry
        async def on_pre_tool_use(input_data, invocation):
            tool_name = input_data.get("toolName", "")
            if tool_name not in our_tool_names:
                logger.warning(f"Blocking built-in tool: {tool_name}")
                return {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"Tool '{tool_name}' is not available. Use only DataPyn tools.",
                }
            logger.info(f"Allowing tool: {tool_name}")
            return {"permissionDecision": "allow"}
        
        config = {
            "model": self._model,
            "streaming": True,
            # Disable common built-in skills
            "disabled_skills": [
                "view", "grep", "shell", "bash", "read_file", "write_file",
                "search_files", "list_directory", "report_intent", "search_code",
                "file_search", "web_search", "fetch_webpage", "terminal",
                "run_command", "list_files", "read", "write", "search",
            ],
            "hooks": {
                "on_pre_tool_use": on_pre_tool_use,
            },
        }
        
        if self._sdk_tools:
            config["tools"] = self._sdk_tools
            logger.info(f"Creating session with {len(self._sdk_tools)} tools: {list(our_tool_names)}")
        
        if self._system_message:
            config["system_message"] = {
                "message": self._system_message,
            }
        
        self._session = await self._sdk_client.create_session(config)

    def _build_sdk_tools(self, SDKTool) -> List[Any]:
        """Build SDK Tool objects from MCP tool definitions."""
        if not self._tool_executor:
            logger.warning("No tool executor available - no tools will be registered")
            return []
        
        registry = self._tool_executor._registry
        sdk_tools = []
        
        for tool_schema in registry.list_tools():
            tool_name = tool_schema.get("name", "")
            tool_desc = tool_schema.get("description", "")
            input_schema = tool_schema.get("inputSchema", {})
            
            # Build proper JSON schema for SDK
            tool_params = {
                "type": "object",
                "properties": input_schema.get("properties", {}),
                "required": list(input_schema.get("properties", {}).keys()),
            }

            # Create async handler that executes via the thread-safe executor
            # SDK expects: async def handler(invocation) -> dict with textResultForLlm
            def make_handler(name):
                async def handler(invocation):
                    arguments = invocation.get("arguments", {}) if isinstance(invocation, dict) else {}
                    logger.info(f"SDK calling tool: {name} with {arguments}")
                    result = self._tool_executor.execute(name, arguments)
                    logger.info(f"SDK tool result for {name}: {result[:200] if result else 'empty'}")
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
        
        try:
            if not self._loop or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
            
            self._loop.run_until_complete(self._async_init_session())
        except Exception as e:
            logger.warning(f"SDK session pre-init error: {e}")

    async def _async_init_session(self):
        """Async session initialization without completion."""
        SDKClient, _, EventType, import_err = _try_import_sdk()
        if SDKClient is None:
            return
        
        # Initialize client
        if not self._sdk_client:
            self._sdk_client = SDKClient()
            await self._sdk_client.start()
            logger.info("Copilot SDK client started (pre-init)")
        
        # Create session
        if not self._session:
            config = {
                "model": "gpt-4o-mini",  # Fast model for completions
                "streaming": True,
            }
            if self._system_message:
                config["system_message"] = {
                    "message": self._system_message,
                }
            self._session = await self._sdk_client.create_session(config)
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
            self._sdk_client = SDKClient()
            await self._sdk_client.start()
            logger.info("[COPILOT-WORKER] SDK client started")
        
        # Create session without tools for faster response
        if not self._session:
            logger.info("[COPILOT-WORKER] Creating new session (gpt-4o-mini)...")
            config = {
                "model": "gpt-4o-mini",  # Faster model for completions
                "streaming": True,
            }
            if self._system_message:
                config["system_message"] = {
                    "message": self._system_message,
                }
            self._session = await self._sdk_client.create_session(config)
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
            await self._session.send({"prompt": self._inline_prompt})
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
    tool_result = pyqtSignal(str, str)
    thinking = pyqtSignal(str)
    models_changed = pyqtSignal(list)
    inline_completion_ready = pyqtSignal(str)  # Inline completion result

    def __init__(self, parent=None, tool_registry: "MCPToolRegistry" = None):
        super().__init__(parent)
        self._model = "gpt-4o"
        self._system_message = ""
        self._is_authenticated = False
        self._username = None  # GitHub username
        self._available_models = DEFAULT_MODELS.copy()
        
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
            self._tool_executor = ThreadSafeToolExecutor(tool_registry)

    def set_tool_registry(self, registry: "MCPToolRegistry") -> None:
        """Set or update the MCP tool registry."""
        self._tool_executor = ThreadSafeToolExecutor(registry)

    @property
    def is_authenticated(self) -> bool:
        return self._is_authenticated

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str):
        self._model = value

    @property
    def system_message(self) -> str:
        return self._system_message

    @system_message.setter
    def system_message(self, value: str):
        self._system_message = value

    def available_models(self) -> List[Dict[str, str]]:
        """Return list of available models (updated from SDK)."""
        return self._available_models
    
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
        self._session_thread = QThread()
        self._session_worker.moveToThread(self._session_thread)
        
        # Connect signals
        self._session_thread.started.connect(self._session_worker.run_init)
        self._session_worker.auth_ok.connect(self._on_auth_success)
        self._session_worker.auth_needed.connect(self._on_auth_needed)
        self._session_worker.models_ready.connect(self._on_models_loaded)
        self._session_worker.error.connect(self._on_init_error)
        self._session_worker.ready.connect(self._on_session_ready)
        # Note: Do NOT connect finished to cleanup - worker stays alive
        
        self._session_thread.start()

    def send_chat(self, messages: List[Dict[str, str]]) -> None:
        """
        Send a chat message to Copilot using persistent session.
        
        Args:
            messages: List of message dicts with "role" and "content" keys.
                      The last user message is used as the prompt.
        """
        # Extract prompt from last user message
        user_messages = [m for m in messages if m.get("role") == "user"]
        if not user_messages:
            self.chat_error.emit("No user message to send")
            return
        
        prompt = user_messages[-1].get("content", "")
        if not prompt:
            self.chat_error.emit("Empty message")
            return
        
        # Use persistent session worker if available
        if self._session_worker and self._session_thread and self._session_thread.isRunning():
            self._session_worker.set_model(self._model)
            self._session_worker.set_prompt(prompt)
            self._session_worker.set_system_message(self._system_message)
            
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
            self._worker.set_prompt(prompt)
            self._worker.set_system_message(self._system_message)
            
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
            self._worker.auth_ok.connect(self._on_auth_success)
            self._worker.finished.connect(self._on_worker_finished)
            
            self._worker_thread.start()

    def cancel(self) -> None:
        """Cancel current operation."""
        if self._session_worker:
            self._session_worker.cancel()
        if self._worker:
            self._worker.cancel()

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
        """Sign out (CLI manages credentials)."""
        self._is_authenticated = False
        self._username = None
        self._cleanup_worker()
        self._cleanup_session_worker()

    def _on_auth_success(self):
        self._is_authenticated = True
        # Try to get username from GitHub CLI
        username = self._get_github_username()
        self._username = username
        self.authenticated.emit(username or "Copilot")
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
            result = subprocess.run(
                [gh_path, "api", "user", "-q", ".login"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.debug(f"Could not get GitHub username: {e}")
        return ""

    def _on_auth_needed(self):
        """Auth not found - start automatic login process."""
        self.do_login()

    def _on_auth_started(self, message: str):
        """Login process started."""
        self.auth_started.emit(message)

    def do_login(self) -> None:
        """Start automatic GitHub login process. Creates persistent session on success."""
        self._cleanup_worker()
        self._cleanup_session_worker()
        
        # Create as session worker - it will become persistent on success
        self._session_worker = CopilotWorker(self._tool_executor)
        self._session_thread = QThread()
        self._session_worker.moveToThread(self._session_thread)
        
        # Connect signals
        self._session_thread.started.connect(self._session_worker.run_login)
        self._session_worker.auth_ok.connect(self._on_auth_success)
        self._session_worker.auth_started.connect(self._on_auth_started)
        self._session_worker.models_ready.connect(self._on_models_loaded)
        self._session_worker.error.connect(self._on_init_error)
        self._session_worker.ready.connect(self._on_session_ready)
        # Note: Do NOT connect finished to cleanup - worker stays alive
        
        self._session_thread.start()

    def _on_models_loaded(self, models: list):
        if models:
            self._available_models = models
            self.models_changed.emit(models)

    def _on_init_error(self, error: str):
        self._is_authenticated = False
        self.auth_failed.emit(error)

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
        self._cleanup_worker()
        self._cleanup_session_worker()
        self._cleanup_completion_worker()