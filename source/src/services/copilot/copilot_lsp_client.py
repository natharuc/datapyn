"""
Copilot Language Server Protocol Client.

JSON-RPC 2.0 client for communicating with the copilot-language-server.
Provides fast inline completions (<500ms) via the official LSP protocol.
"""

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, QTimer

logger = logging.getLogger(__name__)


class CopilotLSPClient(QObject):
    """
    LSP client for GitHub Copilot Language Server.
    
    Communicates via JSON-RPC 2.0 over stdio to get fast inline completions.
    
    Signals:
        initialized: Server has been initialized
        auth_required(str, str): user_code, verification_uri
        authenticated(str): username/status
        completion_ready(str): inline completion text
        error(str): error message
        status_changed(str): status update (e.g., "SignedIn", "SignedOut")
        log_message(str, str): message and level (info/error/debug)
    """
    
    initialized = pyqtSignal()
    auth_required = pyqtSignal(str, str)  # user_code, verification_uri
    authenticated = pyqtSignal(str)
    completion_ready = pyqtSignal(str)
    error = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    log_message = pyqtSignal(str, str)  # message, level
    
    def __init__(self, server_path: str, parent=None):
        super().__init__(parent)
        
        self._server_path = server_path
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Request tracking
        self._request_id = 0
        self._pending_requests: Dict[int, Callable] = {}
        
        # State
        self._initialized = False
        self._is_authenticated = False
        self._current_document_version = 0
        self._current_document_uri = ""
        
        # Completion tracking
        self._pending_completion_id: Optional[int] = None
    
    @property
    def is_initialized(self) -> bool:
        """Check if the server is initialized."""
        return self._initialized
    
    @property
    def is_authenticated(self) -> bool:
        """Check if the user is authenticated."""
        return self._is_authenticated
    
    def _log(self, message: str, level: str = "info") -> None:
        """Log message to both logger and output panel signal."""
        if level == "error":
            logger.error(f"[LSP] {message}")
        elif level == "debug":
            logger.debug(f"[LSP] {message}")
        else:
            logger.info(f"[LSP] {message}")
        self.log_message.emit(f"[LSP] {message}", level)

    def start(self) -> bool:
        """
        Start the language server process.
        
        Returns:
            True if started successfully.
        """
        if self._process and self._process.poll() is None:
            logger.warning("[LSP] Server already running")
            return True
        
        try:
            logger.info(f"[LSP] Starting server: {self._server_path}")
            
            # Start process
            self._process = subprocess.Popen(
                [self._server_path, "--stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,  # Unbuffered
            )
            
            # Start reader thread
            self._reader_thread = threading.Thread(
                target=self._read_loop,
                daemon=True,
                name="CopilotLSP-Reader"
            )
            self._reader_thread.start()
            
            logger.info("[LSP] Server process started")
            return True
        
        except Exception as e:
            logger.exception(f"[LSP] Failed to start server: {e}")
            self.error.emit(f"Failed to start Copilot server: {e}")
            return False
    
    def stop(self) -> None:
        """Stop the language server."""
        if self._process:
            try:
                # Send shutdown request
                self._send_request("shutdown", {})
                self._send_notification("exit", {})
                
                # Give it a moment to close gracefully
                self._process.wait(timeout=2)
            except Exception:
                pass
            
            try:
                self._process.terminate()
            except Exception:
                pass
            
            self._process = None
        
        self._initialized = False
        self._is_authenticated = False
        logger.info("[LSP] Server stopped")
    
    def initialize(self, workspace_path: str = "") -> None:
        """
        Initialize the server with LSP handshake.
        
        Args:
            workspace_path: Path to the workspace folder (optional)
        """
        if not self._process:
            self.error.emit("Server not started")
            return
        
        workspace_uri = f"file:///{workspace_path.replace(os.sep, '/')}" if workspace_path else ""
        
        def on_init_response(result, error):
            if error:
                logger.error(f"[LSP] Initialize failed: {error}")
                self.error.emit(f"Initialize failed: {error}")
                return
            
            logger.info("[LSP] Initialize response received")
            
            # Send initialized notification
            self._send_notification("initialized", {})
            
            # Send configuration
            self._send_notification("workspace/didChangeConfiguration", {
                "settings": {
                    "telemetry": {"telemetryLevel": "off"},
                    "http": {"proxy": None, "proxyStrictSSL": True}
                }
            })
            
            self._initialized = True
            self.initialized.emit()
            
            # Check authentication status
            self.check_status()
        
        self._send_request("initialize", {
            "processId": os.getpid(),
            "workspaceFolders": [
                {"uri": workspace_uri, "name": "workspace"}
            ] if workspace_uri else [],
            "capabilities": {
                "workspace": {"workspaceFolders": True},
                "window": {"showDocument": {"support": True}},
                "textDocument": {
                    "inlineCompletion": {
                        "dynamicRegistration": True
                    }
                }
            },
            "initializationOptions": {
                "editorInfo": {"name": "DataPyn", "version": "1.0.0"},
                "editorPluginInfo": {"name": "copilot-datapyn", "version": "1.0.0"}
            }
        }, on_init_response)
    
    def check_status(self, auto_sign_in: bool = True) -> None:
        """Check authentication status.
        
        Args:
            auto_sign_in: If True and not signed in, automatically start sign-in
        """
        def on_status(result, error):
            if error:
                self._log(f"checkStatus error: {error}", "error")
                return
            
            status = result.get("status", "Unknown") if result else "Unknown"
            self._log(f"Auth status: {status}", "info")
            
            self._is_authenticated = status == "SignedIn"
            self.status_changed.emit(status)
            
            if self._is_authenticated:
                user = result.get("user", "GitHub User")
                self._log(f"Authenticated as {user}", "info")
                self.authenticated.emit(user)
            elif auto_sign_in and status in ("NotSignedIn", "SignedOut", "Unknown"):
                # Auto-trigger sign-in for device flow
                self._log("Not authenticated, starting sign-in flow...", "info")
                self.sign_in()
        
        self._send_request("checkStatus", {}, on_status)
    
    def sign_in(self) -> None:
        """Start the sign-in process."""
        def on_sign_in(result, error):
            if error:
                self._log(f"signIn error: {error}", "error")
                self.error.emit(f"Sign-in failed: {error}")
                return
            
            if not result:
                return
            
            status = result.get("status", "")
            
            if status == "SignedIn":
                user = result.get("user", "GitHub User")
                self._is_authenticated = True
                self._log(f"Signed in as {user}", "info")
                self.authenticated.emit(user)
                self.status_changed.emit("SignedIn")
            
            elif status in ("NotSignedIn", "SignedOut"):
                # Device flow - need user to visit URL
                user_code = result.get("userCode", "")
                verification_uri = result.get("verificationUri", "https://github.com/login/device")
                
                if user_code:
                    self._log(f"Device flow: enter code {user_code} at {verification_uri}", "info")
                    self.auth_required.emit(user_code, verification_uri)
                    
                    # Execute the finish command to complete device flow
                    command = result.get("command", {})
                    if command.get("command") == "github.copilot.finishDeviceFlow":
                        self._execute_command("github.copilot.finishDeviceFlow", [])
        
        self._send_request("signIn", {}, on_sign_in)
    
    def sign_out(self) -> None:
        """Sign out from Copilot."""
        def on_sign_out(result, error):
            self._is_authenticated = False
            self.status_changed.emit("SignedOut")
        
        self._send_request("signOut", {}, on_sign_out)
    
    def _execute_command(self, command: str, args: List[Any]) -> None:
        """Execute a workspace command."""
        def on_result(result, error):
            if error:
                logger.warning(f"[LSP] Command {command} error: {error}")
            else:
                logger.info(f"[LSP] Command {command} completed")
                # Re-check status after command
                QTimer.singleShot(1000, self.check_status)
        
        self._send_request("workspace/executeCommand", {
            "command": command,
            "arguments": args
        }, on_result)
    
    def open_document(self, uri: str, language_id: str, text: str, version: int = 1) -> None:
        """
        Notify server that a document was opened.
        
        Args:
            uri: Document URI (file:///path/to/file.py)
            language_id: Language identifier (python, sql, etc.)
            text: Full document text
            version: Document version (increment on changes)
        """
        self._current_document_uri = uri
        self._current_document_version = version
        
        self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": language_id,
                "version": version,
                "text": text
            }
        })
        
        logger.debug(f"[LSP] Document opened: {uri}, lang={language_id}")
    
    def change_document(self, uri: str, version: int, text: str) -> None:
        """
        Notify server of document changes.
        
        Args:
            uri: Document URI
            version: New version number
            text: New full document text
        """
        self._current_document_version = version
        
        self._send_notification("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": version},
            "contentChanges": [{"text": text}]
        })
    
    def close_document(self, uri: str) -> None:
        """Notify server that a document was closed."""
        self._send_notification("textDocument/didClose", {
            "textDocument": {"uri": uri}
        })
    
    def request_completion(
        self,
        uri: str,
        version: int,
        line: int,
        character: int,
        trigger_kind: int = 2
    ) -> None:
        """
        Request inline completion at a position.
        
        Args:
            uri: Document URI
            version: Document version
            line: Line number (0-indexed)
            character: Character position (0-indexed)
            trigger_kind: 1=manual, 2=automatic
        """
        if not self._initialized or not self._is_authenticated:
            self.completion_ready.emit("")
            return
        
        # Cancel any pending completion request
        if self._pending_completion_id:
            self._send_notification("$/cancelRequest", {"id": self._pending_completion_id})
        
        start_time = time.time()
        
        def on_completion(result, error):
            elapsed = (time.time() - start_time) * 1000
            
            if error:
                logger.warning(f"[LSP] Completion error after {elapsed:.0f}ms: {error}")
                self.completion_ready.emit("")
                return
            
            # Extract completion text
            items = result.get("items", []) if result else []
            
            if items:
                insert_text = items[0].get("insertText", "")
                logger.info(
                    f"[LSP] Completion received in {elapsed:.0f}ms: "
                    f"{insert_text[:50]}..."
                )
                self.completion_ready.emit(insert_text)
            else:
                logger.debug(f"[LSP] No completions in {elapsed:.0f}ms")
                self.completion_ready.emit("")
            
            self._pending_completion_id = None
        
        req_id = self._send_request("textDocument/inlineCompletion", {
            "textDocument": {"uri": uri, "version": version},
            "position": {"line": line, "character": character},
            "context": {"triggerKind": trigger_kind},
            "formattingOptions": {"tabSize": 4, "insertSpaces": True}
        }, on_completion)
        
        self._pending_completion_id = req_id
        logger.debug(f"[LSP] Requesting completion at {line}:{character}")
    
    def _send_request(
        self,
        method: str,
        params: Dict[str, Any],
        callback: Optional[Callable] = None
    ) -> int:
        """
        Send a JSON-RPC request.
        
        Returns:
            Request ID
        """
        with self._lock:
            self._request_id += 1
            req_id = self._request_id
            if callback:
                self._pending_requests[req_id] = callback
        
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }
        
        self._write_message(message)
        return req_id
    
    def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        self._write_message(message)
    
    def _write_message(self, message: Dict[str, Any]) -> None:
        """Write a message to the server stdin."""
        if not self._process or self._process.poll() is not None:
            return
        
        try:
            content = json.dumps(message)
            content_bytes = content.encode("utf-8")
            header = f"Content-Length: {len(content_bytes)}\r\n\r\n"
            
            self._process.stdin.write(header.encode("utf-8"))
            self._process.stdin.write(content_bytes)
            self._process.stdin.flush()
        except Exception as e:
            logger.error(f"[LSP] Write error: {e}")
    
    def _read_loop(self) -> None:
        """Background thread loop for reading server responses."""
        try:
            while self._process and self._process.poll() is None:
                try:
                    message = self._read_message()
                    if message:
                        self._handle_message(message)
                except Exception as e:
                    if self._process and self._process.poll() is None:
                        logger.error(f"[LSP] Read error: {e}")
                    break
        except Exception as e:
            logger.error(f"[LSP] Reader thread error: {e}")
        
        logger.info("[LSP] Reader thread exiting")
    
    def _read_message(self) -> Optional[Dict[str, Any]]:
        """Read a single JSON-RPC message from stdout."""
        if not self._process:
            return None
        
        # Read headers
        headers = {}
        while True:
            line = self._process.stdout.readline()
            if not line:
                return None
            
            line = line.decode("utf-8")
            if line in ("\r\n", "\n"):
                break
            
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip()] = value.strip()
        
        # Read content
        content_length = int(headers.get("Content-Length", 0))
        if content_length <= 0:
            return None
        
        content = self._process.stdout.read(content_length)
        if not content:
            return None
        
        return json.loads(content.decode("utf-8"))
    
    def _handle_message(self, message: Dict[str, Any]) -> None:
        """Handle a received JSON-RPC message."""
        # Response to a request
        if "id" in message and ("result" in message or "error" in message):
            req_id = message["id"]
            with self._lock:
                callback = self._pending_requests.pop(req_id, None)
            
            if callback:
                result = message.get("result")
                error = message.get("error")
                if error:
                    error = error.get("message", str(error))
                callback(result, error)
        
        # Notification from server
        elif "method" in message:
            self._handle_notification(message["method"], message.get("params", {}))
    
    def _handle_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Handle a server notification."""
        if method == "didChangeStatus":
            status = params.get("status", "Unknown")
            logger.info(f"[LSP] Status notification: {status}")
            self._is_authenticated = status == "SignedIn"
            self.status_changed.emit(status)
        
        elif method == "window/logMessage":
            msg = params.get("message", "")
            level = params.get("type", 3)  # 1=error, 2=warn, 3=info, 4=log
            if level <= 2:
                logger.warning(f"[LSP] Server: {msg}")
            else:
                logger.debug(f"[LSP] Server: {msg}")
        
        elif method == "window/showMessage":
            msg = params.get("message", "")
            logger.info(f"[LSP] Message: {msg}")
