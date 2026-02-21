"""
CopilotClient - Handles GitHub Copilot integration using the official SDK.

Uses the github-copilot-sdk which wraps the Copilot CLI for authentication
and communication with GitHub Copilot.

The client runs async operations in a QThread to avoid blocking the UI.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt

logger = logging.getLogger(__name__)

# Fallback models if API is unavailable
# Models available in Copilot CLI (from --model option):
# "claude-sonnet-4.6", "claude-sonnet-4.5", "claude-haiku-4.5", "claude-opus-4.6",
# "claude-opus-4.6-fast", "claude-opus-4.5", "claude-sonnet-4", "gemini-3-pro-preview",
# "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.2", "gpt-5.1-codex-max", "gpt-5.1-codex",
# "gpt-5.1", "gpt-5", "gpt-5.1-codex-mini", "gpt-5-mini", "gpt-4.1"
# Note: Some premium models require interactive confirmation first (run 'copilot --model MODEL_NAME')
DEFAULT_COPILOT_MODELS = [
    {"id": "gpt-4.1", "name": "GPT-4.1"},
    {"id": "gpt-5-mini", "name": "GPT-5 Mini"},
    {"id": "gpt-5", "name": "GPT-5"},
    {"id": "gpt-5.1", "name": "GPT-5.1"},
    {"id": "claude-sonnet-4", "name": "Claude Sonnet 4"},
    {"id": "claude-sonnet-4.5", "name": "Claude Sonnet 4.5"},
    {"id": "claude-sonnet-4.6", "name": "Claude Sonnet 4.6"},
    {"id": "claude-haiku-4.5", "name": "Claude Haiku 4.5"},
    {"id": "gemini-3-pro-preview", "name": "Gemini 3 Pro Preview"},
]


class SDKWorker(QObject):
    """Worker that runs async SDK operations in a background thread."""

    # Signals
    auth_status_ready = pyqtSignal(bool, str, str)  # is_authenticated, login, status_message
    models_ready = pyqtSignal(list)  # list of model dicts
    chat_response = pyqtSignal(str)  # response text
    chat_chunk = pyqtSignal(str)  # streaming chunk
    model_activated = pyqtSignal(str, bool)  # model_id, success
    error = pyqtSignal(str)  # error message
    finished = pyqtSignal()

    def __init__(self, operation: str, **kwargs):
        super().__init__()
        self.operation = operation
        self.kwargs = kwargs
        self._cancelled = False
        self._loop = None
        self._client = None
        self._session = None

    def cancel(self):
        self._cancelled = True

    def run(self):
        """Execute the async operation."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._execute())
        except Exception as e:
            logger.exception(f"SDK worker error: {e}")
            self.error.emit(str(e))
        finally:
            if self._loop:
                self._loop.close()
            self.finished.emit()

    async def _execute(self):
        """Execute the appropriate async operation."""
        try:
            from copilot import CopilotClient as SDKClient

            if self.operation == "check_auth":
                await self._check_auth(SDKClient)
            elif self.operation == "list_models":
                await self._list_models(SDKClient)
            elif self.operation == "send_message":
                await self._send_message(SDKClient)
            elif self.operation == "activate_model":
                await self._activate_model()
        except ImportError:
            self.error.emit(
                "github-copilot-sdk not installed. Install with: pip install github-copilot-sdk"
            )
        except Exception as e:
            logger.exception(f"SDK operation error: {e}")
            self.error.emit(str(e))

    async def _check_auth(self, SDKClient):
        """Check authentication status."""
        client = SDKClient()
        try:
            await client.start()
            auth = await client.get_auth_status()
            self.auth_status_ready.emit(
                auth.isAuthenticated,
                auth.login or "",
                auth.statusMessage or ""
            )
        finally:
            await client.stop()

    async def _list_models(self, SDKClient):
        """List available models with policy information."""
        client = SDKClient()
        try:
            await client.start()
            models = await client.list_models()
            model_list = []
            for m in models:
                model_info = {
                    "id": m.id,
                    "name": m.name,
                    "policy_state": m.policy.state if m.policy else "enabled",
                    "policy_terms": m.policy.terms if m.policy else None,
                }
                model_list.append(model_info)
            self.models_ready.emit(model_list)
        finally:
            await client.stop()

    async def _activate_model(self):
        """Activate a model using the CLI with automatic confirmation."""
        import subprocess
        import os

        model_id = self.kwargs.get("model_id", "")

        try:
            # Get CLI path
            import copilot.bin
            cli_path = os.path.join(os.path.dirname(copilot.bin.__file__), "copilot.exe")
        except Exception:
            cli_path = "copilot"

        logger.info(f"Activating model {model_id} using CLI: {cli_path}")

        try:
            # Run CLI with model and pipe "1" to select "Yes, enable this model"
            # Use subprocess with input to simulate user selection
            process = await asyncio.create_subprocess_exec(
                cli_path,
                "--model", model_id,
                "--non-interactive",  # Try non-interactive mode first
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Send "1" to select first option and then quit
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=b"1\nq\n"),
                timeout=30
            )

            logger.debug(f"CLI stdout: {stdout.decode() if stdout else ''}")
            logger.debug(f"CLI stderr: {stderr.decode() if stderr else ''}")

            # Check if activation was successful by listing models again
            from copilot import CopilotClient as SDKClient
            client = SDKClient()
            await client.start()
            try:
                models = await client.list_models()
                for m in models:
                    if m.id == model_id:
                        if m.policy and m.policy.state == "enabled":
                            logger.info(f"Model {model_id} activated successfully")
                            self.model_activated.emit(model_id, True)
                            return
                        break
            finally:
                await client.stop()

            # If we get here, activation may have failed
            logger.warning(f"Model {model_id} activation may have failed")
            self.model_activated.emit(model_id, False)

        except asyncio.TimeoutError:
            logger.error(f"Timeout activating model {model_id}")
            self.model_activated.emit(model_id, False)
        except Exception as e:
            logger.exception(f"Error activating model {model_id}: {e}")
            self.model_activated.emit(model_id, False)

    async def _send_message(self, SDKClient):
        """Send a chat message."""
        messages = self.kwargs.get("messages", [])
        model = self.kwargs.get("model", "gpt-4o")

        logger.info(f"Starting send_message with model={model}")

        client = SDKClient()
        try:
            await client.start()
            logger.debug("Client started")

            # Check auth first
            auth = await client.get_auth_status()
            logger.debug(f"Auth status: {auth.isAuthenticated}")
            if not auth.isAuthenticated:
                self.error.emit("Not authenticated. Please run 'copilot login' first.")
                return

            # Create session with model config
            logger.debug(f"Creating session with model: {model}")
            session = await client.create_session({"model": model})
            logger.debug(f"Session created: {session.session_id}")

            # Get user message
            user_message = messages[-1]["content"] if messages else ""
            logger.info(f"Sending message: {user_message[:100]}...")
            full_response = ""

            # Import event types
            from copilot.generated.session_events import SessionEventType

            # Subscribe to events for streaming
            def handle_event(event):
                nonlocal full_response
                if self._cancelled:
                    return

                try:
                    event_type = event.type
                    logger.debug(f"Received event: {event_type}")

                    # Handle streaming delta (chunks)
                    if event_type == SessionEventType.ASSISTANT_MESSAGE_DELTA:
                        if hasattr(event, 'data') and hasattr(event.data, 'content'):
                            chunk = event.data.content
                            if chunk:
                                logger.debug(f"Delta chunk: {chunk[:50]}...")
                                full_response += chunk
                                self.chat_chunk.emit(chunk)

                    # Handle complete message
                    elif event_type == SessionEventType.ASSISTANT_MESSAGE:
                        if hasattr(event, 'data') and hasattr(event.data, 'content'):
                            content = event.data.content
                            logger.debug(f"Complete message: {content[:100] if content else 'None'}...")
                            if content:
                                # Only use if we didn't get deltas
                                if not full_response:
                                    full_response = content

                except Exception as e:
                    logger.warning(f"Error handling event: {e}")

            unsubscribe = session.on(handle_event)
            logger.debug("Event handler subscribed")

            try:
                # Send message and wait for completion
                logger.info("Calling send_and_wait...")
                response = await session.send_and_wait({"prompt": user_message}, timeout=120)
                logger.info(f"send_and_wait returned: {type(response)}")

                # Get final response content if not already collected via streaming
                if not full_response:
                    # Try to get from response object
                    if response and hasattr(response, 'data') and hasattr(response.data, 'content'):
                        full_response = response.data.content or ""
                        logger.debug(f"Got response from return value: {full_response[:100] if full_response else 'empty'}...")

                    # If still empty, try to get messages from session
                    if not full_response:
                        try:
                            messages_list = await session.get_messages()
                            if messages_list:
                                # Get the last assistant message
                                for msg in reversed(messages_list):
                                    if hasattr(msg, 'role') and msg.role == 'assistant':
                                        if hasattr(msg, 'content') and msg.content:
                                            full_response = msg.content
                                            logger.debug(f"Got response from get_messages: {full_response[:100]}...")
                                            break
                        except Exception as e:
                            logger.warning(f"Could not get messages: {e}")

                logger.info(f"Final response length: {len(full_response)}")

                # Always emit the response (even if empty, UI will handle it)
                response_to_emit = full_response if full_response else "I received your message but couldn't generate a response."
                self.chat_response.emit(response_to_emit)
            finally:
                unsubscribe()

        except Exception as e:
            logger.exception(f"Error sending message: {e}")
            self.error.emit(str(e))
        finally:
            await client.stop()
            logger.debug("Client stopped")


class CopilotClient(QObject):
    """
    Client for GitHub Copilot integration using the official SDK.

    The SDK uses the bundled Copilot CLI for authentication and communication.

    Authentication:
        Users must authenticate using the Copilot CLI before using this client.
        Run in terminal: copilot login

        The CLI path is: <python-env>/Lib/site-packages/copilot/bin/copilot.exe

        After authentication, the token is stored and reused automatically.

    Signals:
        authenticated(str): username - authentication successful
        auth_failed(str): error message
        models_updated(list): list of available models
        model_activation_required(str, str): model_id, terms - model needs activation
        model_activated(str, bool): model_id, success - model activation result
        chat_response_chunk(str): streaming text chunk
        chat_response_complete(str): full response text
        chat_error(str): error message
    """

    # Signals for UI communication
    authenticated = pyqtSignal(str)  # username or status
    auth_failed = pyqtSignal(str)
    models_updated = pyqtSignal(list)  # list of model dicts
    model_activation_required = pyqtSignal(str, str)  # model_id, terms
    model_activated = pyqtSignal(str, bool)  # model_id, success
    chat_response_chunk = pyqtSignal(str)
    chat_response_complete = pyqtSignal(str)
    chat_error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_authenticated = False
        self._username = ""
        self._model = "gpt-4.1"  # Default model that works without activation
        self._available_models: List[Dict[str, str]] = DEFAULT_COPILOT_MODELS.copy()
        self._active_threads: list = []

    @property
    def is_authenticated(self) -> bool:
        return self._is_authenticated

    @property
    def has_copilot_token(self) -> bool:
        return self._is_authenticated

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str):
        self._model = value

    def set_model(self, model_id: str) -> bool:
        """
        Set the model, checking if it requires activation.

        Args:
            model_id: The model ID to set

        Returns:
            True if model was set successfully, False if activation is required
        """
        try:
            # Find model info
            model_info = None
            for m in self._available_models:
                if m.get("id") == model_id:
                    model_info = m
                    break

            if not model_info:
                # Model not found in list, try to use it anyway
                self._model = model_id
                return True

            # Check if model requires activation
            policy_state = model_info.get("policy_state", "enabled")
            if policy_state == "disabled":
                terms = model_info.get("policy_terms", "")
                self.model_activation_required.emit(model_id, terms or "Enable access to this model.")
                return False

            self._model = model_id
            return True
        except Exception as e:
            logger.exception(f"Error setting model {model_id}: {e}")
            # On error, just set the model and hope for the best
            self._model = model_id
            return True

    def get_model_activation_command(self, model_id: str) -> str:
        """Get the command to activate a model in the CLI."""
        try:
            import copilot.bin
            import os
            cli_path = os.path.join(os.path.dirname(copilot.bin.__file__), "copilot.exe")
        except Exception:
            cli_path = "copilot"
        return f'{cli_path} --model {model_id}'

    def activate_model(self, model_id: str) -> None:
        """
        Activate a model that requires user confirmation.

        This runs the CLI in a background thread and attempts to
        automatically accept the model terms.

        Args:
            model_id: The ID of the model to activate
        """
        worker = SDKWorker("activate_model", model_id=model_id)
        thread = QThread()

        self._activation_worker = worker
        self._activation_thread = thread

        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.model_activated.connect(self._on_model_activated, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(lambda e: logger.warning(f"Model activation error: {e}"))
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._cleanup_activation_thread, Qt.ConnectionType.QueuedConnection)

        self._active_threads.append((thread, worker))
        thread.start()

    def _on_model_activated(self, model_id: str, success: bool):
        """Handle model activation result."""
        if success:
            # Update the model in available models list
            for m in self._available_models:
                if m.get("id") == model_id:
                    m["policy_state"] = "enabled"
                    break
            # Refresh models list
            self._fetch_models()
        self.model_activated.emit(model_id, success)

    def _cleanup_activation_thread(self) -> None:
        """Clean up activation thread."""
        self._cleanup_thread_ref("_activation_thread", "_activation_worker")

    def available_models(self) -> List[Dict[str, str]]:
        """Return list of available models for the user."""
        return self._available_models

    def start_auth(self) -> None:
        """
        Check authentication status.

        The SDK uses GitHub CLI authentication. Users must run 'gh auth login' first.
        """
        worker = SDKWorker("check_auth")
        thread = QThread()

        self._auth_worker = worker
        self._auth_thread = thread

        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.auth_status_ready.connect(self._on_auth_status, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(self._on_auth_error, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._cleanup_auth_thread, Qt.ConnectionType.QueuedConnection)

        self._active_threads.append((thread, worker))
        thread.start()

    def _on_auth_status(self, is_authenticated: bool, login: str, status_message: str):
        """Handle authentication status response."""
        self._is_authenticated = is_authenticated
        self._username = login

        if is_authenticated:
            self.authenticated.emit(f"Logged in as {login}")
            # Fetch available models
            self._fetch_models()
        else:
            # Get the path to the copilot CLI
            try:
                import copilot.bin
                import os
                cli_path = os.path.join(os.path.dirname(copilot.bin.__file__), "copilot.exe")
            except Exception:
                cli_path = "copilot"

            self.auth_failed.emit(
                f"{status_message}\n\n"
                "Please authenticate using the Copilot CLI:\n"
                f"Run in terminal: {cli_path} login\n\n"
                "Or add to PATH and run: copilot login"
            )

    def _on_auth_error(self, error: str):
        """Handle authentication error."""
        self._is_authenticated = False
        self.auth_failed.emit(error)

    def _fetch_models(self) -> None:
        """Fetch available models from Copilot."""
        worker = SDKWorker("list_models")
        thread = QThread()

        self._models_worker = worker
        self._models_thread = thread

        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.models_ready.connect(self._on_models_ready, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(lambda e: logger.warning(f"Failed to fetch models: {e}"))
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._cleanup_models_thread, Qt.ConnectionType.QueuedConnection)

        self._active_threads.append((thread, worker))
        thread.start()

    def _on_models_ready(self, models: List[Dict[str, str]]):
        """Handle models list response."""
        if models:
            self._available_models = models
            self.models_updated.emit(models)

    def send_chat(self, messages: List[Dict[str, str]]) -> None:
        """
        Send a chat message to Copilot.

        Args:
            messages: List of message dicts with "role" and "content" keys.
        """
        if not self._is_authenticated:
            self.chat_error.emit("Not authenticated. Please sign in first.")
            return

        # Check if there's already a chat operation in progress
        if hasattr(self, '_chat_thread') and self._chat_thread and self._chat_thread.isRunning():
            logger.warning("Chat operation already in progress, ignoring new request")
            return

        worker = SDKWorker("send_message", messages=messages, model=self._model)
        thread = QThread()

        self._chat_worker = worker
        self._chat_thread = thread

        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.chat_chunk.connect(self._on_chat_chunk, Qt.ConnectionType.QueuedConnection)
        worker.chat_response.connect(self._on_chat_response, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(self.chat_error.emit, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._cleanup_chat_thread, Qt.ConnectionType.QueuedConnection)

        self._active_threads.append((thread, worker))
        thread.start()

    def _on_chat_chunk(self, chunk: str):
        """Handle chat chunk from worker."""
        self.chat_response_chunk.emit(chunk)

    def _on_chat_response(self, response: str):
        """Handle chat response from worker."""
        logger.info(f"Chat response received: {len(response)} chars")
        self.chat_response_complete.emit(response)

    def sign_out(self) -> None:
        """Sign out (clear local state, user must use gh auth logout)."""
        self._is_authenticated = False
        self._username = ""

    def refresh_token_if_needed(self) -> None:
        """Refresh authentication status."""
        self.start_auth()

    def validate_saved_token(self) -> None:
        """Validate authentication status."""
        self.start_auth()

    def clear_invalid_token(self) -> None:
        """Clear authentication state."""
        self._is_authenticated = False
        self._username = ""

    def _cleanup_auth_thread(self) -> None:
        """Clean up auth thread."""
        self._cleanup_thread_ref("_auth_thread", "_auth_worker")

    def _cleanup_models_thread(self) -> None:
        """Clean up models thread."""
        self._cleanup_thread_ref("_models_thread", "_models_worker")

    def _cleanup_chat_thread(self) -> None:
        """Clean up chat thread."""
        self._cleanup_thread_ref("_chat_thread", "_chat_worker")

    def _cleanup_thread_ref(self, thread_attr: str, worker_attr: str) -> None:
        """Clean up a thread reference."""
        try:
            thread = getattr(self, thread_attr, None)
            worker = getattr(self, worker_attr, None)
            if thread and worker:
                self._active_threads = [
                    (t, w) for t, w in self._active_threads if t is not thread
                ]
                worker.deleteLater()
                thread.deleteLater()
        except RuntimeError:
            pass
        finally:
            setattr(self, thread_attr, None)
            setattr(self, worker_attr, None)

    def cleanup(self) -> None:
        """Clean up all resources."""
        for thread, worker in self._active_threads:
            try:
                if hasattr(worker, "cancel"):
                    worker.cancel()
                if thread.isRunning():
                    thread.quit()
                    thread.wait(2000)
            except RuntimeError:
                pass
        self._active_threads.clear()



























