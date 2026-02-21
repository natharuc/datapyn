"""
CopilotClient - Handles GitHub Copilot authentication and API communication.

Uses GitHub's Device Flow for OAuth authentication, then communicates
with the Copilot Chat API to send/receive messages.

The client runs network operations in a QThread to avoid blocking the UI.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal, QSettings, Qt

logger = logging.getLogger(__name__)

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
COPILOT_CHAT_URL = "https://api.githubcopilot.com/chat/completions"
COPILOT_MODELS_URL = "https://api.githubcopilot.com/models"

# GitHub Copilot OAuth client ID (public, used by VS Code Copilot extension)
COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"

# Alternative client IDs if needed
# VS Code Insiders: "01ab8ac9400c4e429b23"
# GitHub CLI: "178c6fc778ccc68e1d6a"

# Fallback models if API is unavailable
DEFAULT_COPILOT_MODELS = [
    {"id": "gpt-4o", "name": "GPT-4o"},
    {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
    {"id": "claude-3.5-sonnet", "name": "Claude 3.5 Sonnet"},
    {"id": "o3-mini", "name": "o3-mini"},
]


class AuthWorker(QObject):
    """Worker that handles GitHub Device Flow authentication in background."""

    device_code_ready = pyqtSignal(str, str, str)  # user_code, verification_uri, device_code
    auth_success = pyqtSignal(str)  # github_token
    auth_error = pyqtSignal(str)  # error message
    finished = pyqtSignal()

    def __init__(self, device_code: str = "", interval: int = 5):
        super().__init__()
        self.device_code = device_code
        self.interval = interval
        self._cancelled = False
        self._phase = "device_code"  # "device_code" or "poll"

    def cancel(self):
        self._cancelled = True

    def set_phase(self, phase: str, device_code: str = "", interval: int = 5):
        self._phase = phase
        self.device_code = device_code
        self.interval = interval

    def run(self):
        """Execute the authentication flow."""
        try:
            import requests
        except ImportError:
            self.auth_error.emit("requests library not available.")
            self.finished.emit()
            return

        try:
            if self._phase == "device_code":
                self._request_device_code(requests)
            elif self._phase == "poll":
                self._poll_for_token(requests)
        except Exception as e:
            self.auth_error.emit(str(e))
        finally:
            self.finished.emit()

    def _request_device_code(self, requests):
        """Request device code from GitHub."""
        resp = requests.post(
            GITHUB_DEVICE_CODE_URL,
            data={"client_id": COPILOT_CLIENT_ID, "scope": "copilot"},
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            self.auth_error.emit(f"Failed to get device code: HTTP {resp.status_code}")
            return

        data = resp.json()
        user_code = data.get("user_code", "")
        verification_uri = data.get("verification_uri", "")
        device_code = data.get("device_code", "")
        self.interval = data.get("interval", 5)

        self.device_code_ready.emit(user_code, verification_uri, device_code)

    def _poll_for_token(self, requests):
        """Poll GitHub for the access token."""
        max_attempts = 60
        for _ in range(max_attempts):
            if self._cancelled:
                return

            time.sleep(self.interval)

            resp = requests.post(
                GITHUB_ACCESS_TOKEN_URL,
                data={
                    "client_id": COPILOT_CLIENT_ID,
                    "device_code": self.device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
                timeout=15,
            )

            if resp.status_code != 200:
                continue

            data = resp.json()
            error = data.get("error", "")

            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                self.interval += 5
                continue
            elif error == "expired_token":
                self.auth_error.emit("Device code expired. Please try again.")
                return
            elif error == "access_denied":
                self.auth_error.emit("Authorization denied by user.")
                return
            elif error:
                self.auth_error.emit(f"Authentication error: {error}")
                return

            token = data.get("access_token", "")
            if token:
                self.auth_success.emit(token)
                return

        self.auth_error.emit("Authentication timed out.")


class ChatWorker(QObject):
    """Worker that sends chat requests to Copilot API in background."""

    response_chunk = pyqtSignal(str)  # text chunk (for streaming)
    response_complete = pyqtSignal(str)  # full response text
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, copilot_token: str, messages: List[Dict], model: str = "gpt-4o"):
        super().__init__()
        self.copilot_token = copilot_token
        self.messages = messages
        self.model = model
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        """Send chat completion request."""
        try:
            import requests
        except ImportError:
            self.error.emit("requests library not available.")
            self.finished.emit()
            return

        try:
            resp = requests.post(
                COPILOT_CHAT_URL,
                json={
                    "messages": self.messages,
                    "model": self.model,
                    "stream": True,
                },
                headers={
                    "Authorization": f"Bearer {self.copilot_token}",
                    "Content-Type": "application/json",
                    "Editor-Version": "DataPyn/1.0.0",
                    "Copilot-Integration-Id": "datapyn-ide",
                },
                stream=True,
                timeout=60,
            )

            if resp.status_code == 401:
                self.error.emit("Authentication expired. Please sign in again.")
                return

            if resp.status_code != 200:
                self.error.emit(f"Copilot API error: HTTP {resp.status_code}")
                return

            full_response = ""
            for line in resp.iter_lines():
                if self._cancelled:
                    break

                if not line:
                    continue

                line_str = line.decode("utf-8")
                if not line_str.startswith("data: "):
                    continue

                data_str = line_str[6:]
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                    choices = data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_response += content
                            self.response_chunk.emit(content)
                except json.JSONDecodeError:
                    continue

            self.response_complete.emit(full_response)

        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class CopilotTokenWorker(QObject):
    """Worker to exchange GitHub token for Copilot token."""

    token_ready = pyqtSignal(str)  # copilot_token
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, github_token: str):
        super().__init__()
        self.github_token = github_token

    def run(self):
        try:
            import requests

            logger.debug(f"Requesting Copilot token from {COPILOT_TOKEN_URL}")
            resp = requests.get(
                COPILOT_TOKEN_URL,
                headers={
                    "Authorization": f"token {self.github_token}",
                    "Accept": "application/json",
                },
                timeout=15,
            )
            logger.debug(f"Copilot token response: {resp.status_code}")
            if resp.status_code == 401 or resp.status_code == 403:
                # Check if it's the "unapproved client" error
                error_msg = ""
                try:
                    data = resp.json()
                    if "error_details" in data:
                        error_msg = data.get("error_details", {}).get("message", "")
                except Exception:
                    pass

                if "approved clients" in error_msg.lower() or resp.status_code == 403:
                    logger.error(f"Copilot API rejected client: {error_msg}")
                    self.error.emit(
                        "GitHub Copilot API requires an approved client. "
                        "DataPyn cannot directly access Copilot. "
                        "Consider using the MCP integration with VS Code or JetBrains."
                    )
                else:
                    logger.error(f"Token request failed: {resp.status_code} - {resp.text[:200] if resp.text else 'no body'}")
                    self.error.emit(f"GitHub token expired or invalid. Please sign in again. (HTTP {resp.status_code})")
                return
            if resp.status_code != 200:
                logger.error(f"Token request failed: {resp.status_code}")
                self.error.emit(f"Failed to get Copilot token: HTTP {resp.status_code}")
                return

            data = resp.json()
            token = data.get("token", "")
            if token:
                logger.info("Copilot token obtained successfully")
                self.token_ready.emit(token)
            else:
                logger.error("No token in response")
                self.error.emit("No Copilot token in response. Is Copilot enabled for your account?")
        except Exception as e:
            logger.exception("Error getting Copilot token")
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class ModelsWorker(QObject):
    """Worker to fetch available models from Copilot API."""

    models_ready = pyqtSignal(list)  # list of model dicts
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, copilot_token: str):
        super().__init__()
        self.copilot_token = copilot_token

    def run(self):
        try:
            import requests

            resp = requests.get(
                COPILOT_MODELS_URL,
                headers={
                    "Authorization": f"Bearer {self.copilot_token}",
                    "Accept": "application/json",
                    "Editor-Version": "DataPyn/1.0.0",
                    "Copilot-Integration-Id": "datapyn-ide",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch models: HTTP {resp.status_code}")
                self.models_ready.emit(DEFAULT_COPILOT_MODELS)
                return

            data = resp.json()
            models_list = data.get("models", data.get("data", []))

            if not models_list:
                self.models_ready.emit(DEFAULT_COPILOT_MODELS)
                return

            # Parse models from API response
            parsed_models = []
            for m in models_list:
                model_id = m.get("id", m.get("name", ""))
                model_name = m.get("name", m.get("id", ""))
                if model_id:
                    parsed_models.append({"id": model_id, "name": model_name})

            if parsed_models:
                self.models_ready.emit(parsed_models)
            else:
                self.models_ready.emit(DEFAULT_COPILOT_MODELS)

        except Exception as e:
            logger.warning(f"Error fetching models: {e}")
            self.models_ready.emit(DEFAULT_COPILOT_MODELS)
        finally:
            self.finished.emit()


class CopilotClient(QObject):
    """
    Client for GitHub Copilot integration.

    Manages authentication, token lifecycle, and chat communication.

    Signals:
        auth_required(str, str): user_code, verification_uri - user needs to authenticate
        authenticated(str): username - authentication successful
        auth_failed(str): error message
        models_updated(list): list of available models
        chat_response_chunk(str): streaming text chunk
        chat_response_complete(str): full response text
        chat_error(str): error message
    """

    auth_required = pyqtSignal(str, str)  # user_code, verification_uri
    authenticated = pyqtSignal(str)  # username or status
    auth_failed = pyqtSignal(str)
    models_updated = pyqtSignal(list)  # list of model dicts
    chat_response_chunk = pyqtSignal(str)
    chat_response_complete = pyqtSignal(str)
    chat_error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._github_token: str = ""
        self._copilot_token: str = ""
        self._model: str = "gpt-4o"
        self._available_models: List[Dict[str, str]] = DEFAULT_COPILOT_MODELS.copy()
        self._active_threads: list = []
        self._settings = QSettings("DataPyn", "CopilotAuth")

        # Strong references to prevent garbage collection during auth
        self._poll_worker = None
        self._poll_thread = None
        self._token_worker = None
        self._token_thread = None

        # Try to restore token from settings
        self._github_token = self._settings.value("github_token", "", type=str)

    @property
    def is_authenticated(self) -> bool:
        return bool(self._github_token)

    @property
    def has_copilot_token(self) -> bool:
        return bool(self._copilot_token)

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str):
        self._model = value

    def available_models(self) -> List[Dict[str, str]]:
        """Return list of available models for the user."""
        return self._available_models

    def refresh_token_if_needed(self) -> None:
        """Refresh Copilot token if we have a GitHub token but no Copilot token."""
        if self._github_token and not self._copilot_token:
            self._refresh_copilot_token()

    def validate_saved_token(self) -> None:
        """
        Validate saved GitHub token asynchronously.
        If valid, gets Copilot token. If invalid, clears saved token silently.
        """
        if self._github_token and not self._copilot_token:
            self._refresh_copilot_token()

    def clear_invalid_token(self) -> None:
        """Clear tokens without emitting auth_failed signal."""
        self._github_token = ""
        self._copilot_token = ""
        self._settings.remove("github_token")

    def start_auth(self) -> None:
        """Start the GitHub Device Flow authentication."""
        # Clear any existing tokens to start fresh
        self._github_token = ""
        self._copilot_token = ""
        self._settings.remove("github_token")

        worker = AuthWorker()
        worker.set_phase("device_code")
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.device_code_ready.connect(self._on_device_code_ready)
        worker.auth_error.connect(self._on_auth_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(lambda: self._cleanup_thread(thread, worker))

        self._active_threads.append((thread, worker))
        thread.start()

    def _on_device_code_ready(self, user_code: str, verification_uri: str, device_code: str) -> None:
        """Device code received - notify UI and start polling."""
        self.auth_required.emit(user_code, verification_uri)

        # Start polling for token in a separate thread
        self._start_polling(device_code)

    def _start_polling(self, device_code: str) -> None:
        """Start polling for token in background."""
        worker = AuthWorker()
        worker.set_phase("poll", device_code=device_code)
        thread = QThread()

        # Store references to prevent garbage collection
        self._poll_worker = worker
        self._poll_thread = thread

        worker.moveToThread(thread)

        # Use QueuedConnection to ensure signals are processed in the main thread
        thread.started.connect(worker.run)
        worker.auth_success.connect(self._on_github_token, Qt.ConnectionType.QueuedConnection)
        worker.auth_error.connect(self._on_auth_error, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._cleanup_poll_thread, Qt.ConnectionType.QueuedConnection)

        self._active_threads.append((thread, worker))
        thread.start()

    def _on_github_token(self, token: str) -> None:
        """GitHub token received."""
        self._github_token = token
        self._settings.setValue("github_token", token)
        # Exchange for Copilot token (authenticated will be emitted when ready)
        self._refresh_copilot_token()

    def _refresh_copilot_token(self) -> None:
        """Exchange GitHub token for Copilot API token."""
        if not self._github_token:
            return

        worker = CopilotTokenWorker(self._github_token)
        thread = QThread()

        # Store reference to prevent garbage collection
        self._token_worker = worker
        self._token_thread = thread

        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.token_ready.connect(self._on_copilot_token, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(self._on_auth_error, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._cleanup_token_thread, Qt.ConnectionType.QueuedConnection)

        self._active_threads.append((thread, worker))
        thread.start()

    def _on_copilot_token(self, token: str) -> None:
        """Copilot API token received."""
        self._copilot_token = token
        self.authenticated.emit("Copilot ready")
        # Fetch available models
        self._fetch_available_models()

    def _fetch_available_models(self) -> None:
        """Fetch available models from Copilot API."""
        if not self._copilot_token:
            return

        worker = ModelsWorker(self._copilot_token)
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.models_ready.connect(self._on_models_ready)
        worker.finished.connect(thread.quit)
        worker.finished.connect(lambda: self._cleanup_thread(thread, worker))

        self._active_threads.append((thread, worker))
        thread.start()

    def _on_models_ready(self, models: List[Dict[str, str]]) -> None:
        """Models list received from API."""
        self._available_models = models
        self.models_updated.emit(models)

    def _on_auth_error(self, error: str) -> None:
        """Authentication error."""
        # If token expired, clear it to force re-authentication
        if "expired" in error.lower() or "invalid" in error.lower() or "403" in error:
            self._github_token = ""
            self._copilot_token = ""
            self._settings.remove("github_token")
        self.auth_failed.emit(error)

    def send_chat(self, messages: List[Dict[str, str]]) -> None:
        """
        Send a chat message to Copilot.

        Args:
            messages: List of message dicts with "role" and "content" keys.
        """
        if not self._copilot_token:
            if self._github_token:
                self._refresh_copilot_token()
                self.chat_error.emit("Refreshing Copilot token. Please try again.")
                return
            self.chat_error.emit("Not authenticated. Please sign in first.")
            return

        worker = ChatWorker(self._copilot_token, messages, self._model)
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.response_chunk.connect(self.chat_response_chunk.emit)
        worker.response_complete.connect(self.chat_response_complete.emit)
        worker.error.connect(self.chat_error.emit)
        worker.finished.connect(thread.quit)
        worker.finished.connect(lambda: self._cleanup_thread(thread, worker))

        self._active_threads.append((thread, worker))
        thread.start()

    def sign_out(self) -> None:
        """Sign out and clear tokens."""
        self._github_token = ""
        self._copilot_token = ""
        self._settings.remove("github_token")

    def _cleanup_poll_thread(self) -> None:
        """Clean up polling thread and worker."""
        try:
            if self._poll_thread and self._poll_worker:
                self._active_threads = [
                    (t, w) for t, w in self._active_threads if t is not self._poll_thread
                ]
                self._poll_worker.deleteLater()
                self._poll_thread.deleteLater()
        except RuntimeError:
            pass
        finally:
            self._poll_worker = None
            self._poll_thread = None

    def _cleanup_token_thread(self) -> None:
        """Clean up token exchange thread and worker."""
        try:
            if self._token_thread and self._token_worker:
                self._active_threads = [
                    (t, w) for t, w in self._active_threads if t is not self._token_thread
                ]
                self._token_worker.deleteLater()
                self._token_thread.deleteLater()
        except RuntimeError:
            pass
        finally:
            self._token_worker = None
            self._token_thread = None

    def _cleanup_thread(self, thread, worker) -> None:
        """Remove finished thread from active list."""
        try:
            self._active_threads = [
                (t, w) for t, w in self._active_threads if t is not thread
            ]
            worker.deleteLater()
            thread.deleteLater()
        except RuntimeError:
            pass

    def cleanup(self) -> None:
        """Clean up resources."""
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
